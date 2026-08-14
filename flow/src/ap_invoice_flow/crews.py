"""The two crews the flow drives: one extracts, one reports."""

from __future__ import annotations

import os

from crewai import LLM, Agent, Crew, Process, Task

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


def extract_invoice(path: str, text: str, llm: LLM) -> Invoice:
    """Run a one-agent crew over a single document and return the structured invoice."""
    agent = _extraction_agent(llm)
    crew = Crew(
        agents=[agent],
        tasks=[_extraction_task(agent, path, text)],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff()
    invoice = result.pydantic
    if invoice is None:
        raise ValueError(f"No structured output returned for {path}")
    invoice.source_file = path  # the path is ours, not the model's, to decide
    return invoice


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
