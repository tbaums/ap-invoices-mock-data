"""Structured types shared across the flow."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(description="What was billed")
    quantity: float = Field(default=1.0, description="Units billed")
    unit_price: float = Field(default=0.0, description="Price per unit")
    amount: float = Field(default=0.0, description="Extended amount for this line")


class Invoice(BaseModel):
    """One accounts-payable invoice, extracted from a source document."""

    source_file: str = Field(default="", description="Repository path of the source document")
    vendor_name: str = Field(description="Company that issued the invoice")
    invoice_number: str = Field(description="Vendor's invoice number, verbatim")
    invoice_date: str = Field(default="", description="Invoice date as YYYY-MM-DD")
    received_date: str = Field(default="", description="Date AP received it, as YYYY-MM-DD")
    bill_to: str = Field(default="", description="Company being billed")
    purchase_order: str = Field(default="", description="PO or agreement reference")
    payment_terms: str = Field(default="", description="e.g. Net 30")
    due_date: str = Field(default="", description="Payment due date as YYYY-MM-DD")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float = Field(default=0.0)
    tax: float = Field(default=0.0)
    total: float = Field(default=0.0, description="Total amount due")
    currency: str = Field(default="USD")


class DuplicateMatch(BaseModel):
    """A duplicate-submission finding: `duplicate_file` repeats `original_file`."""

    original_file: str
    duplicate_file: str
    vendor_name: str
    invoice_number: str
    total: float
    currency: str = "USD"
    match_type: str = Field(description="Which signal fired")
    confidence: str = Field(description="high | medium | low")
    rationale: str = Field(default="")


class ReviewResult(BaseModel):
    """Everything the flow produces, in one object."""

    repo_url: str = ""
    documents_scanned: int = 0
    invoices_parsed: int = 0
    unique_invoices: int = 0
    duplicates: list[DuplicateMatch] = Field(default_factory=list)
    duplicate_exposure: float = 0.0
    invoices: list[Invoice] = Field(default_factory=list)
    report: str = ""
    parse_failures: list[str] = Field(default_factory=list)
