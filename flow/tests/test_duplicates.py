"""Detection-logic tests. No network, no API key.

Run with pytest, or directly:  python tests/test_duplicates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ap_invoice_flow.duplicates import duplicate_exposure, find_duplicates  # noqa: E402
from ap_invoice_flow.models import Invoice  # noqa: E402


def make(file: str, vendor: str, number: str, total: float, invoice_date: str, received: str) -> Invoice:
    return Invoice(
        source_file=file,
        vendor_name=vendor,
        invoice_number=number,
        invoice_date=invoice_date,
        received_date=received,
        total=total,
    )


def test_exact_invoice_number_resend_is_a_duplicate():
    invoices = [
        make("a.md", "Acme Corp", "INV-1", 100.0, "2026-01-01", "2026-01-02"),
        make("b.md", "Acme, Inc.", "inv 1", 100.0, "2026-01-01", "2026-02-20"),
    ]
    (match,) = find_duplicates(invoices)
    assert match.original_file == "a.md"
    assert match.duplicate_file == "b.md"
    assert match.match_type == "exact_invoice_number"
    assert match.confidence == "high"


def test_earliest_received_is_treated_as_the_original():
    invoices = [
        make("later.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-03-01"),
        make("earlier.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-01-02"),
    ]
    (match,) = find_duplicates(invoices)
    assert match.original_file == "earlier.md"
    assert match.duplicate_file == "later.md"


def test_different_vendors_are_never_duplicates():
    invoices = [
        make("a.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-01-01"),
        make("b.md", "Globex", "INV-1", 100.0, "2026-01-01", "2026-01-01"),
    ]
    assert find_duplicates(invoices) == []


def test_same_vendor_same_total_same_date_under_a_new_number():
    invoices = [
        make("a.md", "Acme", "INV-1", 250.0, "2026-04-01", "2026-04-02"),
        make("b.md", "Acme", "INV-9", 250.0, "2026-04-01", "2026-04-30"),
    ]
    (match,) = find_duplicates(invoices)
    assert match.match_type == "same_vendor_amount_date"
    assert match.confidence == "high"


def test_same_total_inside_the_window_is_medium_confidence():
    invoices = [
        make("a.md", "Acme", "INV-1", 250.0, "2026-04-01", "2026-04-02"),
        make("b.md", "Acme", "INV-9", 250.0, "2026-05-01", "2026-05-02"),
    ]
    (match,) = find_duplicates(invoices)
    assert match.match_type == "same_vendor_amount_window"
    assert match.confidence == "medium"


def test_same_total_outside_the_window_is_not_flagged():
    invoices = [
        make("a.md", "Acme", "INV-1", 250.0, "2026-01-01", "2026-01-02"),
        make("b.md", "Acme", "INV-9", 250.0, "2026-09-01", "2026-09-02"),
    ]
    assert find_duplicates(invoices) == []


def test_recurring_monthly_charge_is_not_flagged():
    """Same vendor, different amounts each month — a real AP pattern, not a duplicate."""
    invoices = [
        make("jan.md", "Acme", "INV-1", 100.0, "2026-01-31", "2026-02-01"),
        make("feb.md", "Acme", "INV-2", 110.0, "2026-02-28", "2026-03-01"),
        make("mar.md", "Acme", "INV-3", 120.0, "2026-03-31", "2026-04-01"),
    ]
    assert find_duplicates(invoices) == []


def test_three_resends_of_one_invoice_all_point_at_the_same_original():
    invoices = [
        make("a.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-01-02"),
        make("b.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-02-02"),
        make("c.md", "Acme", "INV-1", 100.0, "2026-01-01", "2026-03-02"),
    ]
    matches = find_duplicates(invoices)
    assert len(matches) == 2
    assert {m.original_file for m in matches} == {"a.md"}
    assert duplicate_exposure(matches) == 200.0


def test_exposure_sums_the_duplicated_totals():
    invoices = [
        make("a.md", "Acme", "INV-1", 19733.00, "2026-01-01", "2026-01-02"),
        make("b.md", "Acme", "INV-1", 19733.00, "2026-01-01", "2026-02-02"),
        make("c.md", "Kestrel", "KOI-8823", 42106.62, "2026-01-01", "2026-01-02"),
        make("d.md", "Kestrel", "KOI-8823", 42106.62, "2026-01-01", "2026-03-02"),
    ]
    assert duplicate_exposure(find_duplicates(invoices)) == 61839.62


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL  {name}: {error}")
    print(f"\n{failures} failure(s)")
    raise SystemExit(1 if failures else 0)
