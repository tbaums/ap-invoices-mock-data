"""Deterministic duplicate detection over extracted invoices.

The agents read unstructured documents into structured invoices; this module
decides what counts as a duplicate. Keeping the decision in code (rather than
asking a model "are any of these duplicates?") means the answer is reproducible
and auditable — the same 12 invoices always yield the same findings.

Three signals, checked in order of strength:

  1. exact_invoice_number      same vendor + same invoice number
  2. same_vendor_amount_date   same vendor + same total + same invoice date
  3. same_vendor_amount_window same vendor + same total, dates within N days
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .models import DuplicateMatch, Invoice

NEAR_DATE_WINDOW_DAYS = 60


def _norm(value: str) -> str:
    """Fold case, punctuation and legal suffixes so 'Acme, Inc.' == 'ACME Inc'."""
    text = (value or "").lower()
    text = re.sub(r"\b(inc|llc|llp|ltd|co|corp|company|group|partners)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _norm_number(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _cents(value: float) -> int:
    return int(round(float(value or 0.0) * 100))


def _parse_date(value: str) -> date | None:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _sort_key(invoice: Invoice) -> tuple[str, str, str]:
    """Earliest submission first, so the first sighting is the 'original'."""
    return (
        invoice.received_date or invoice.invoice_date or "9999-99-99",
        invoice.invoice_date or "9999-99-99",
        invoice.source_file,
    )


def _classify(candidate: Invoice, prior: Invoice) -> tuple[str, str, str] | None:
    """Return (match_type, confidence, rationale) if `candidate` repeats `prior`."""
    if _norm(candidate.vendor_name) != _norm(prior.vendor_name):
        return None

    same_number = (
        _norm_number(candidate.invoice_number)
        and _norm_number(candidate.invoice_number) == _norm_number(prior.invoice_number)
    )
    same_total = _cents(candidate.total) == _cents(prior.total)

    if same_number:
        agreement = "and the same total" if same_total else "though the totals differ"
        return (
            "exact_invoice_number",
            "high",
            f"Invoice {prior.invoice_number} from {prior.vendor_name} was already "
            f"received on {prior.received_date or prior.invoice_date} ({agreement}).",
        )

    if not same_total:
        return None

    if candidate.invoice_date and candidate.invoice_date == prior.invoice_date:
        return (
            "same_vendor_amount_date",
            "high",
            f"Same vendor, same invoice date ({prior.invoice_date}) and same total "
            f"under a different invoice number.",
        )

    left, right = _parse_date(candidate.invoice_date), _parse_date(prior.invoice_date)
    if left and right and abs((left - right).days) <= NEAR_DATE_WINDOW_DAYS:
        return (
            "same_vendor_amount_window",
            "medium",
            f"Same vendor and same total {abs((left - right).days)} days apart "
            f"under a different invoice number — verify before paying.",
        )

    return None


def find_duplicates(invoices: list[Invoice]) -> list[DuplicateMatch]:
    """Match each invoice against every earlier one; first match wins."""
    ordered = sorted(invoices, key=_sort_key)
    matches: list[DuplicateMatch] = []
    originals: list[Invoice] = []

    for invoice in ordered:
        for prior in originals:
            verdict = _classify(invoice, prior)
            if verdict is None:
                continue
            match_type, confidence, rationale = verdict
            matches.append(
                DuplicateMatch(
                    original_file=prior.source_file,
                    duplicate_file=invoice.source_file,
                    vendor_name=prior.vendor_name,
                    invoice_number=prior.invoice_number,
                    total=prior.total,
                    currency=prior.currency or "USD",
                    match_type=match_type,
                    confidence=confidence,
                    rationale=rationale,
                )
            )
            break
        else:
            originals.append(invoice)

    return matches


def duplicate_exposure(matches: list[DuplicateMatch]) -> float:
    """Total that would be paid twice if every duplicate cleared."""
    return round(sum(match.total for match in matches), 2)
