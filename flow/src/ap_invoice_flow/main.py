"""CLI entry point.

    python -m ap_invoice_flow.main https://github.com/tbaums/ap-invoices-mock-data
"""

from __future__ import annotations

import argparse
import json
import sys

from .flow import run_review

DEFAULT_REPO = "https://github.com/tbaums/ap-invoices-mock-data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ap-invoice-flow",
        description="Review the invoices in a GitHub repository and report duplicate submissions.",
    )
    parser.add_argument(
        "repo_url",
        nargs="?",
        default=DEFAULT_REPO,
        help=f"GitHub repository URL (default: {DEFAULT_REPO})",
    )
    parser.add_argument(
        "--path",
        default="",
        dest="path_filter",
        help="Only read documents whose path contains this substring, e.g. 'invoices/'",
    )
    parser.add_argument(
        "--extractor",
        choices=("agent", "regex"),
        default="agent",
        help="'agent' uses the LLM (needs ANTHROPIC_API_KEY); "
        "'regex' parses the fixture layout offline",
    )
    parser.add_argument(
        "--model",
        default="",
        help="LiteLLM model id (default: anthropic/claude-opus-5, or $AP_FLOW_MODEL)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4, help="Parallel extraction workers (default: 4)"
    )
    parser.add_argument("--json", dest="json_path", default="", help="Write full results to a JSON file")
    parser.add_argument("--out", dest="report_path", default="", help="Write the report to a markdown file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        result = run_review(
            repo_url=args.repo_url,
            path_filter=args.path_filter,
            extractor=args.extractor,
            model=args.model,
            concurrency=args.concurrency,
        )
    except Exception as error:  # noqa: BLE001 - surface the reason, don't traceback at the user
        print(f"error: {error}", file=sys.stderr)
        return 1

    print()
    print(result.report)
    print()
    print(
        f"— {result.invoices_parsed} invoices, {result.unique_invoices} unique, "
        f"{len(result.duplicates)} duplicates, ${result.duplicate_exposure:,.2f} exposure"
    )

    if args.report_path:
        with open(args.report_path, "w", encoding="utf-8") as handle:
            handle.write(result.report + "\n")
        print(f"— report written to {args.report_path}", file=sys.stderr)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(result.model_dump(), handle, indent=2)
        print(f"— results written to {args.json_path}", file=sys.stderr)

    if result.parse_failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
