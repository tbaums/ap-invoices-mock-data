# ap-invoice-flow

A CrewAI **Flow** that takes a GitHub repository URL, reads the invoices in it, and
reports whether any are duplicate submissions.

This is the code version of the flow built live in CrewAI AMP Studio. It runs against
the synthetic invoices in this repository, and it works against any public repo whose
invoices are markdown files.

## What it does

```
repo URL ─▶ fetch_documents ─▶ extract_invoices ─▶ detect_duplicates ─▶ write_report ─▶ report
             (GitHub API)       (agent, parallel)     (deterministic)      (agent)
```

| Step | Who does it | Why |
|---|---|---|
| `fetch_documents` | Plain code (GitHub REST + raw) | Listing files is not a judgment call |
| `extract_invoices` | **Agent** — one per document, run in parallel | Reading unstructured documents into fields is the part that genuinely needs a model |
| `detect_duplicates` | **Plain code** (`duplicates.py`) | The verdict must be reproducible and auditable — the same invoices always yield the same findings |
| `write_report` | **Agent** | Turning verified findings into a briefing a person reads |

The split matters: the model does the reading, the code does the deciding. A model
asked "are any of these duplicates?" can answer differently run to run. This flow
can't — the agent's only job is to transcribe fields faithfully, and the matching
rules are ordinary Python you can read and argue with.

## What counts as a duplicate

Three signals, checked strongest first. Every finding names which one fired.

| Signal | Rule | Confidence |
|---|---|---|
| `exact_invoice_number` | Same vendor + same invoice number | high |
| `same_vendor_amount_date` | Same vendor + same total + same invoice date, different invoice number | high |
| `same_vendor_amount_window` | Same vendor + same total, invoice dates within 60 days, different invoice number | medium |

Vendor names are normalized before comparison, so `Acme, Inc.` and `ACME Inc` match.
Whichever invoice AP received **first** is treated as the original; later arrivals are
the duplicates. A recurring monthly charge from one vendor at different amounts is not
flagged — see `tests/test_duplicates.py`.

## Setup

Needs Python 3.10–3.13 (CrewAI does not support 3.14 yet).

```bash
cd flow
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e .

cp .env.example .env    # then put your ANTHROPIC_API_KEY in it
```

Or with plain pip: `python3.13 -m venv .venv && .venv/bin/pip install -e .`

## Run

```bash
set -a; . .env; set +a

# Against this repository
.venv/bin/python -m ap_invoice_flow.main https://github.com/tbaums/ap-invoices-mock-data

# Narrow to a subdirectory, save the artifacts
.venv/bin/python -m ap_invoice_flow.main \
  https://github.com/tbaums/ap-invoices-mock-data \
  --path invoices/ --out report.md --json results.json
```

Expected output against this repository: **12 invoices, 9 unique, 3 duplicates,
$108,874.62 exposure.** A full run takes about 35 seconds.

### Options

| Flag | Default | Notes |
|---|---|---|
| `repo_url` | this repo | Accepts `owner/repo`, an https URL, a `/tree/<branch>/<dir>` URL, or an SSH URL |
| `--path` | *(all markdown)* | Only read paths containing this substring |
| `--extractor` | `agent` | `agent` uses the LLM; `regex` runs offline — see below |
| `--model` | `anthropic/claude-opus-5` | Any LiteLLM model id; also settable via `AP_FLOW_MODEL` |
| `--concurrency` | `4` | Parallel extraction workers |
| `--out` / `--json` | *(none)* | Write the report / full structured results to a file |

Exit code is `0` on success, `1` if the run failed, `2` if some documents could not be parsed.

### The offline extractor

`--extractor regex` runs the whole flow with **no API key and no model calls**. It parses
this repository's markdown layout directly, then uses the same duplicate detection and
prints a plain-text report. It exists so the flow still demonstrates end to end if the
API key, the network, or a rate limit gets in the way. It only understands the fixture
layout — it is a safety net, not the product.

```bash
.venv/bin/python -m ap_invoice_flow.main --extractor regex --path invoices/
```

## Tests

Detection logic only — no network, no API key, runs in under a second.

```bash
.venv/bin/python tests/test_duplicates.py
```

## Environment

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | for `--extractor agent` | Model access |
| `AP_FLOW_MODEL` | no | Override the model id |
| `GITHUB_TOKEN` | no | Raises the GitHub API rate limit; public repos work without it |

No credentials are committed to this repository — `.env` is gitignored, and
`.env.example` holds only empty placeholders.

## Notes

- **`crewai[anthropic]`, not plain `crewai`.** CrewAI resolves `anthropic/...` model ids
  through a native provider that ships in the extra. Without it, extraction fails at run
  time with *"Anthropic native provider not available"*.
- **An occasional `validation error` in the log is CrewAI retrying**, not a failed run.
  The model sometimes returns its structured output wrapped in an extra envelope; CrewAI
  retries and recovers. Trust the `parsed N invoice(s), 0 failure(s)` line — and the exit
  code — over the log noise.
- **Rate limits.** Unauthenticated GitHub API access is 60 requests/hour and each run uses
  roughly one per file. Set `GITHUB_TOKEN` if you are demoing repeatedly.

Everything this flow reads in this repository is synthetic. See the root README.
