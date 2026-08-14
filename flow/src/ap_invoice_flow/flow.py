"""The flow: GitHub repo URL in, duplicate-invoice report out.

    fetch_documents -> extract_invoices -> detect_duplicates -> write_report

Agents do the unstructured work (reading documents into fields) and the narrative
write-up. Code does the adjudication, so the duplicate list is reproducible.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field

from . import crews
from .duplicates import duplicate_exposure, find_duplicates
from .github_source import Document, fetch_markdown_documents, parse_repo_url
from .models import DuplicateMatch, Invoice, ReviewResult
from .regex_extractor import extract_invoice as regex_extract


class InvoiceReviewState(BaseModel):
    repo_url: str = ""
    path_filter: str = ""
    extractor: str = "agent"  # "agent" (LLM) or "regex" (offline fallback)
    model: str = ""
    concurrency: int = 4

    documents: list[dict] = Field(default_factory=list)
    invoices: list[Invoice] = Field(default_factory=list)
    duplicates: list[DuplicateMatch] = Field(default_factory=list)
    parse_failures: list[str] = Field(default_factory=list)
    report: str = ""


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class InvoiceDuplicateReviewFlow(Flow[InvoiceReviewState]):
    """Kick off with inputs={"repo_url": "https://github.com/owner/repo"}."""

    @start()
    def fetch_documents(self) -> list[Document]:
        ref = parse_repo_url(self.state.repo_url)
        _log(f"[1/4] Reading {ref.slug} ...")
        documents = fetch_markdown_documents(ref, self.state.path_filter)
        self.state.documents = [{"path": d.path, "text": d.text} for d in documents]
        _log(f"      found {len(documents)} document(s)")
        return documents

    @listen(fetch_documents)
    def extract_invoices(self, documents: list[Document]) -> list[Invoice]:
        _log(f"[2/4] Extracting invoices with the {self.state.extractor} extractor ...")

        if self.state.extractor == "regex":
            invoices, failures = [], []
            for document in documents:
                try:
                    invoices.append(regex_extract(document.path, document.text))
                except Exception as error:  # noqa: BLE001 - reported, not swallowed
                    failures.append(f"{document.path}: {error}")
        else:
            llm = crews.build_llm(self.state.model or None)

            def run(document: Document) -> tuple[str, Invoice | None, str]:
                try:
                    return document.path, crews.extract_invoice(document.path, document.text, llm), ""
                except Exception as error:  # noqa: BLE001 - reported, not swallowed
                    return document.path, None, str(error)

            workers = max(1, min(self.state.concurrency, len(documents)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(run, documents))

            invoices = [invoice for _, invoice, _ in results if invoice is not None]
            failures = [f"{path}: {error}" for path, invoice, error in results if invoice is None]

        # Stable order regardless of how the threads finished.
        invoices.sort(key=lambda inv: inv.source_file)
        self.state.invoices = invoices
        self.state.parse_failures = failures

        _log(f"      parsed {len(invoices)} invoice(s), {len(failures)} failure(s)")
        for failure in failures:
            _log(f"      ! {failure}")
        return invoices

    @listen(extract_invoices)
    def detect_duplicates(self, invoices: list[Invoice]) -> list[DuplicateMatch]:
        _log("[3/4] Checking for duplicate submissions ...")
        duplicates = find_duplicates(invoices)
        self.state.duplicates = duplicates
        _log(f"      {len(duplicates)} duplicate(s) found")
        return duplicates

    @listen(detect_duplicates)
    def write_report(self, duplicates: list[DuplicateMatch]) -> ReviewResult:
        result = ReviewResult(
            repo_url=self.state.repo_url,
            documents_scanned=len(self.state.documents),
            invoices_parsed=len(self.state.invoices),
            unique_invoices=len(self.state.invoices) - len(duplicates),
            duplicates=duplicates,
            duplicate_exposure=duplicate_exposure(duplicates),
            invoices=self.state.invoices,
            parse_failures=self.state.parse_failures,
        )

        if self.state.extractor == "regex":
            _log("[4/4] Writing report (offline extractor: skipping the narrative agent) ...")
            result.report = render_plain_report(result)
        else:
            _log("[4/4] Writing report ...")
            findings = result.model_dump(include={
                "repo_url", "documents_scanned", "invoices_parsed",
                "unique_invoices", "duplicates", "duplicate_exposure",
            })
            llm = crews.build_llm(self.state.model or None)
            result.report = crews.write_report(json.dumps(findings, indent=2), llm)

        self.state.report = result.report
        return result


def render_plain_report(result: ReviewResult) -> str:
    """A no-LLM report, so the offline path still produces something readable."""
    lines = [
        "# Duplicate Invoice Review",
        "",
        f"Repository: {result.repo_url}",
        f"Documents scanned: {result.documents_scanned}  |  "
        f"Invoices parsed: {result.invoices_parsed}  |  "
        f"Unique: {result.unique_invoices}",
        "",
    ]
    if not result.duplicates:
        lines.append("No duplicate submissions found.")
        return "\n".join(lines)

    lines += [
        f"**{len(result.duplicates)} duplicate submission(s) found — "
        f"${result.duplicate_exposure:,.2f} at risk of double payment.**",
        "",
        "| Duplicate file | Original file | Vendor | Invoice # | Amount | Match |",
        "|---|---|---|---|---|---|",
    ]
    for match in result.duplicates:
        lines.append(
            f"| `{match.duplicate_file}` | `{match.original_file}` | {match.vendor_name} "
            f"| {match.invoice_number} | ${match.total:,.2f} | {match.match_type} "
            f"({match.confidence}) |"
        )
    lines += ["", "Hold each duplicate and confirm against the original before releasing payment."]
    return "\n".join(lines)


def run_review(
    repo_url: str,
    path_filter: str = "",
    extractor: str = "agent",
    model: str = "",
    concurrency: int = 4,
) -> ReviewResult:
    flow = InvoiceDuplicateReviewFlow()
    return flow.kickoff(
        inputs={
            "repo_url": repo_url,
            "path_filter": path_filter,
            "extractor": extractor,
            "model": model,
            "concurrency": concurrency,
        }
    )
