# ap-invoices-mock-data

Synthetic accounts-payable mock data, generated for a **CrewAI AMP Studio** demo.

The `invoices/` folder holds 12 markdown files that read like invoices received by a
fictional software company's AP inbox. They exist so an agent flow can be pointed at this
repository, read the invoices, and report on whether any of them are duplicate submissions.

## Everything here is fake

- **Larkspur Systems, Inc.** (the bill-to) is an invented company.
- Every vendor, address, phone number, email, bank routing number, account fragment,
  purchase order, and dollar amount is invented.
- All email domains use the reserved `.example` TLD and all phone numbers use the
  reserved `555-01xx` range, so nothing here resolves to a real party.
- No real company, person, customer, vendor, or financial record is represented.

Do not treat any content in this repository as a real financial document.

## Layout

```
invoices/    12 markdown invoices addressed to Larkspur Systems, Inc.
```

Each invoice carries a vendor block, invoice number, invoice date, purchase order or
agreement reference, payment terms, due date, an AP received date, a bill-to block,
itemized line items with quantity and unit price, subtotal, sales tax, and total due.

Generated 2026-08-14.
