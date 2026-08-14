"""Structured-output salvage tests. No network, no API key.

The model intermittently wraps its structured output in an envelope whose key
is not stable run to run ("input" and "mode" have both been seen in the wild).
A dropped document silently understates the duplicate count, so the unwrap
matches on shape rather than on a list of key names.

Run with pytest, or directly:  python tests/test_salvage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ap_invoice_flow.crews import _salvage  # noqa: E402


class FakeOutput:
    """Stands in for a CrewAI CrewOutput."""

    def __init__(self, pydantic=None, json_dict=None, raw=""):
        self.pydantic = pydantic
        self.json_dict = json_dict
        self.raw = raw


FIELDS = {
    "vendor_name": "Halcyon Print & Signage Co.",
    "invoice_number": "HPS-4471",
    "invoice_date": "2026-07-06",
    "total": 6178.59,
}


def test_plain_dict_is_used_as_is():
    invoice = _salvage(FakeOutput(json_dict=dict(FIELDS)))
    assert invoice is not None
    assert invoice.invoice_number == "HPS-4471"


def test_input_envelope_is_unwrapped():
    invoice = _salvage(FakeOutput(json_dict={"input": dict(FIELDS)}))
    assert invoice is not None
    assert invoice.total == 6178.59


def test_mode_envelope_is_unwrapped():
    """The shape that dropped an invoice on the first hosted run."""
    invoice = _salvage(FakeOutput(json_dict={"mode": dict(FIELDS)}))
    assert invoice is not None
    assert invoice.vendor_name == "Halcyon Print & Signage Co."


def test_arbitrary_envelope_key_is_unwrapped():
    invoice = _salvage(FakeOutput(json_dict={"some_unseen_wrapper": dict(FIELDS)}))
    assert invoice is not None
    assert invoice.invoice_number == "HPS-4471"


def test_raw_json_string_is_parsed():
    import json

    invoice = _salvage(FakeOutput(raw=json.dumps(FIELDS)))
    assert invoice is not None
    assert invoice.invoice_number == "HPS-4471"


def test_fenced_json_block_is_parsed():
    import json

    invoice = _salvage(FakeOutput(raw="```json\n" + json.dumps(FIELDS) + "\n```"))
    assert invoice is not None
    assert invoice.invoice_number == "HPS-4471"


def test_pydantic_output_wins_when_present():
    from ap_invoice_flow.models import Invoice

    already = Invoice(vendor_name="Acme", invoice_number="A-1", total=1.0)
    assert _salvage(FakeOutput(pydantic=already)) is already


def test_unparseable_output_returns_none():
    assert _salvage(FakeOutput(raw="I could not read that invoice, sorry.")) is None


def test_envelope_without_invoice_fields_returns_none():
    assert _salvage(FakeOutput(json_dict={"mode": {"unrelated": 1}})) is None


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
