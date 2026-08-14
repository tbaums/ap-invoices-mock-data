"""Offline extractor — no LLM, no API key.

This is the safety net. `--extractor agent` is the real path and the one to
demo; this one parses the fixture's markdown layout directly so the flow still
runs end to end when there is no API key, no network to the model, or a rate
limit in the way. It only understands the table layout used by the mock
invoices in this repository.
"""

from __future__ import annotations

import re

from .models import Invoice, LineItem

_FIELD = re.compile(r"^\|\s*\*\*(?P<key>[^*]+)\*\*\s*\|\s*(?P<value>.*?)\s*\|\s*$", re.M)
_MONEY = re.compile(r"-?[\d,]+\.\d{2}")

_FIELD_MAP = {
    "invoice number": "invoice_number",
    "invoice date": "invoice_date",
    "purchase order": "purchase_order",
    "matter number": "purchase_order",
    "payment terms": "payment_terms",
    "due date": "due_date",
    "received by ap": "received_date",
    "subtotal": "subtotal",
    "total due": "total",
}


def _money(value: str) -> float:
    found = _MONEY.search(value.replace("$", ""))
    return float(found.group(0).replace(",", "")) if found else 0.0


def extract_invoice(path: str, text: str) -> Invoice:
    fields: dict[str, str] = {}
    for match in _FIELD.finditer(text):
        key = match.group("key").strip().lower()
        key = re.sub(r"\s*\(.*?\)\s*", "", key)
        fields[key] = match.group("value").strip()

    vendor = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            vendor = stripped.strip("*").strip()
            break

    bill_to = ""
    bill_to_block = re.search(r"\*\*Bill To\*\*\s*\n(?P<name>.+)", text)
    if bill_to_block:
        bill_to = bill_to_block.group("name").strip()

    line_items: list[LineItem] = []
    for row in re.finditer(
        r"^\|\s*\d+\s*\|\s*(?P<desc>[^|]+?)\s*\|\s*(?P<qty>[\d,.]+)\s*\|"
        r"\s*\$(?P<unit>[\d,.]+)\s*\|\s*\$(?P<amount>[\d,.]+)\s*\|",
        text,
        re.M,
    ):
        line_items.append(
            LineItem(
                description=row.group("desc").strip(),
                quantity=float(row.group("qty").replace(",", "")),
                unit_price=float(row.group("unit").replace(",", "")),
                amount=float(row.group("amount").replace(",", "")),
            )
        )

    tax = 0.0
    tax_row = re.search(r"\*\*Sales Tax\*\*[^|]*\|\s*(?P<value>[^|]+)\|", text)
    if tax_row:
        tax = _money(tax_row.group("value"))

    values = {target: fields.get(source, "") for source, target in _FIELD_MAP.items()}

    return Invoice(
        source_file=path,
        vendor_name=vendor,
        invoice_number=values.get("invoice_number", ""),
        invoice_date=values.get("invoice_date", ""),
        received_date=values.get("received_date", ""),
        bill_to=bill_to,
        purchase_order=values.get("purchase_order", ""),
        payment_terms=values.get("payment_terms", ""),
        due_date=values.get("due_date", ""),
        line_items=line_items,
        subtotal=_money(values.get("subtotal", "")),
        tax=tax,
        total=_money(values.get("total", "")),
    )
