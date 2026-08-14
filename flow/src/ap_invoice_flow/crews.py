"""The two crews the flow drives: one extracts, one reports."""

from __future__ import annotations

import json
import os
import re
import time

from crewai import LLM, Agent, Crew, Process, Task
from pydantic import ValidationError

from .models import Invoice

DEFAULT_MODEL = "anthropic/claude-opus-5"


def build_llm(model: str | None = None) -> LLM:
    """CrewAI routes through LiteLLM, so the model id carries its provider prefix."""
    return LLM(model=model or os.getenv("AP_FLOW_MODEL") or DEFAULT_MODEL)


def _extraction_agent(llm: LLM) -> Agent:
    return Agent(
        role="Accounts Payable Analyst",
        goal="Read an invoice document and record its fields exactly as the vendor wrote them.",
        backstory=(
            "You process an AP inbox for a mid-size software company. You have seen every "
            "invoice layout there is, and you copy figures across without rounding, "
            "reformatting, or correcting them."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )


def _extraction_task(agent: Agent, path: str, text: str) -> Task:
    return Task(
        description=(
            f"Extract the invoice below into structured fields.\n\n"
            f"Repository path: {path}\n\n"
            "Rules:\n"
            "- Copy the vendor name and invoice number verbatim, including punctuation.\n"
            "- Give every date as YYYY-MM-DD.\n"
            "- Amounts are plain numbers: no currency symbols, no thousands separators.\n"
            "- `total` is the amount due, not the subtotal.\n"
            "- Leave a field as an empty string if the document does not state it. "
            "Never infer, correct, or fill in a value that is not written down.\n"
            f"- Set source_file to exactly: {path}\n\n"
            "--- BEGIN DOCUMENT ---\n"
            f"{text}\n"
            "--- END DOCUMENT ---"
        ),
        expected_output="The invoice's fields, populated from the document.",
        agent=agent,
        output_pydantic=Invoice,
    )


EXTRACTION_ATTEMPTS = 3


def _salvage(result) -> Invoice | None:
    """Recover an Invoice when CrewAI could not bind the structured output itself.

    The model occasionally returns its fields wrapped in an extra envelope
    (`{"input": {...}}`), which fails validation against Invoice. The data is
    right there — unwrap it rather than losing the document.
    """
    if getattr(result, "pydantic", None) is not None:
        return result.pydantic

    data = getattr(result, "json_dict", None)
    if not isinstance(data, dict):
        raw = str(getattr(result, "raw", "") or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None

    if not isinstance(data, dict):
        return None
    # Peel one envelope layer if the real fields are nested inside it.
    if "vendor_name" not in data:
        for key in ("input", "invoice", "output", "result"):
            nested = data.get(key)
            if isinstance(nested, dict) and "vendor_name" in nested:
                data = nested
                break

    try:
        return Invoice.model_validate(data)
    except ValidationError:
        return None


def extract_invoice(path: str, text: str, llm: LLM) -> Invoice:
    """Run a one-agent crew over a single document and return the structured invoice.

    Retried, because a dropped document silently understates the duplicate count.
    """
    last_error: Exception | None = None

    for attempt in range(1, EXTRACTION_ATTEMPTS + 1):
        try:
            agent = _extraction_agent(llm)
            crew = Crew(
                agents=[agent],
                tasks=[_extraction_task(agent, path, text)],
                process=Process.sequential,
                verbose=False,
            )
            invoice = _salvage(crew.kickoff())
            if invoice is not None:
                invoice.source_file = path  # the path is ours, not the model's, to decide
                return invoice
            last_error = ValueError("no structured output returned")
        except Exception as error:  # noqa: BLE001 - retried below, re-raised if it persists
            last_error = error

        if attempt < EXTRACTION_ATTEMPTS:
            time.sleep(1.5 * attempt)

    raise RuntimeError(f"{EXTRACTION_ATTEMPTS} attempts failed: {last_error}")


def _reporting_agent(llm: LLM) -> Agent:
    return Agent(
        role="AP Controls Lead",
        goal="Tell the AP team, in plain language, whether this batch contains duplicate submissions.",
        backstory=(
            "You brief a procurement team that has to decide what to pay. You lead with the "
            "answer, name the specific files, and never claim a finding the evidence does "
            "not support. You write tightly: no caveat sections, no scope disclaimers, no "
            "restating the question back."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )


def write_report(findings_json: str, llm: LLM) -> str:
    """Turn the deterministic findings into a short markdown briefing."""
    agent = _reporting_agent(llm)
    task = Task(
        description=(
            "Write a short markdown report for the accounts-payable team from the review "
            "findings below.\n\n"
            "The findings are already verified — treat them as fact. Do not re-derive them, "
            "add duplicates that are not listed, or drop any that are.\n\n"
            "Write exactly three things, in this order, and nothing else:\n"
            "1. A single sentence: how many duplicates, and the dollar total at risk.\n"
            "2. A markdown table of the duplicates — duplicate file, original file, vendor, "
            "invoice number, amount, why it matched. If there are none, write "
            "'No duplicate submissions found.' instead of a table.\n"
            "3. Two sentences on what AP should do next.\n\n"
            "Hard limits: under 200 words total. No heading above the first sentence, no "
            "preamble, no caveat or scope-limitation section, no commentary on what the "
            "review could not determine, no restating these instructions.\n\n"
            "--- FINDINGS (JSON) ---\n"
            f"{findings_json}\n"
            "--- END FINDINGS ---"
        ),
        expected_output="A markdown briefing: verdict, table of duplicates, recommended action.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return str(crew.kickoff())
