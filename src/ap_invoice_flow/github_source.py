"""Read markdown documents out of a public GitHub repository.

Only needs the GitHub REST API and raw.githubusercontent.com. A GITHUB_TOKEN in
the environment is used if present (it only raises the rate limit; public repos
do not require it).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

# Repo furniture, not invoices — skipped at any depth, so a repo that documents
# itself in a subdirectory doesn't get its own docs read in as invoices.
SKIP_BASENAMES = {"readme.md", "license.md", "contributing.md", "changelog.md", "security.md"}


@dataclass
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None
    subpath: str = ""

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class Document:
    path: str
    text: str


class GitHubError(RuntimeError):
    pass


def parse_repo_url(url: str) -> RepoRef:
    """Accept the shapes a person actually pastes into a flow input."""
    raw = url.strip().rstrip("/")
    if not raw:
        raise GitHubError("No repository URL was provided.")

    # git@github.com:owner/repo.git
    ssh = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", raw)
    if ssh:
        return RepoRef(ssh.group("owner"), ssh.group("repo"))

    # bare owner/repo
    bare = re.match(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?$", raw)
    if bare and "github.com" not in raw:
        return RepoRef(bare.group("owner"), bare.group("repo"))

    web = re.match(
        r"^(?:https?://)?(?:www\.)?github\.com/"
        r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?"
        r"(?:/(?:tree|blob)/(?P<ref>[^/]+)(?P<subpath>/.*)?)?$",
        raw,
    )
    if web:
        return RepoRef(
            owner=web.group("owner"),
            repo=web.group("repo"),
            ref=web.group("ref"),
            subpath=(web.group("subpath") or "").strip("/"),
        )

    raise GitHubError(f"Could not read a GitHub owner/repo out of {url!r}.")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ap-invoice-flow"}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(url: str) -> requests.Response:
    response = requests.get(url, headers=_headers(), timeout=30)
    if response.status_code == 404:
        raise GitHubError(f"Not found (is the repository public?): {url}")
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise GitHubError(
            "GitHub rate limit reached. Set GITHUB_TOKEN in the environment and re-run."
        )
    response.raise_for_status()
    return response


def fetch_markdown_documents(ref: RepoRef, path_filter: str = "") -> list[Document]:
    """Return every markdown file in the repo, minus repo furniture.

    `path_filter` narrows to paths containing that substring (e.g. "invoices/").
    """
    branch = ref.ref
    if not branch:
        branch = _get(f"{API}/repos/{ref.slug}").json()["default_branch"]

    tree = _get(f"{API}/repos/{ref.slug}/git/trees/{branch}?recursive=1").json()
    if tree.get("truncated"):
        raise GitHubError(
            f"{ref.slug} is too large to list in one request; point the flow at a subdirectory."
        )

    wanted = path_filter or ref.subpath
    paths = []
    for node in tree.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node["path"]
        if not path.lower().endswith(".md"):
            continue
        # Markdown sitting at the repo root is documentation (README, FLOW,
        # CONTRIBUTING, ...), not an invoice. Invoices live in a folder. This
        # is why a bare run doesn't need a path filter to behave sensibly; pass
        # `path_filter` explicitly for a repo that really does keep invoices at
        # the top level.
        if "/" not in path:
            continue
        if path.rsplit("/", 1)[-1].lower() in SKIP_BASENAMES:
            continue
        if wanted and wanted not in path:
            continue
        paths.append(path)

    documents = []
    for path in sorted(paths):
        text = _get(f"{RAW}/{ref.slug}/{branch}/{path}").text
        documents.append(Document(path=path, text=text))

    if not documents:
        where = f" under {wanted!r}" if wanted else ""
        raise GitHubError(f"No markdown documents found in {ref.slug}{where}.")
    return documents
