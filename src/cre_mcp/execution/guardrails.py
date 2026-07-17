"""Shared novice-safe voice for execution-layer drafts."""

EXECUTION_DISCLAIMER = (
    "This is a starting draft for education and negotiation planning, not legal or "
    "financial advice. Before you sign or send binding terms, have a CRE attorney "
    "review the documents and confirm the financing structure with your lender."
)


def execution_guardrail(next_step: str | None = None) -> str:
    """Return the reusable draft-not-advice gate plus an optional concrete next step."""
    if not next_step:
        return EXECUTION_DISCLAIMER
    return f"{EXECUTION_DISCLAIMER} Next: {next_step.strip()}"


def financing_guardrail(next_step: str | None = None) -> str:
    """Return the shared gate in lender-screening language."""
    instruction = (
        "These financing terms are estimates, not a loan commitment — confirm asset "
        "eligibility, borrower requirements, pricing, proceeds, and reserves with a lender."
    )
    if next_step:
        instruction = f"{instruction} {next_step.strip()}"
    return execution_guardrail(instruction)


def structure_guardrail(next_step: str | None = None) -> str:
    """Return the hard legal/tax/securities gate for ownership decisions."""
    instruction = (
        "This is a deterministic educational draft/estimate, not legal, tax, securities, "
        "or investment advice. Do not change title, touch exchange proceeds, solicit investors, "
        "accept funds, or file a tax position until the named QI/CPA/attorney approves it."
    )
    if next_step:
        instruction = f"{instruction} Next: {next_step.strip()}"
    return instruction


CAPITAL_HARD_GATE = (
    "HARD GATE — A securities attorney must review the structure and documents and sign "
    "off BEFORE you solicit or accept any investor money. State blue-sky notice filings "
    "and Form D are required."
)


def capital_guardrail(next_step: str | None = None) -> str:
    """Return the non-negotiable securities-attorney and anti-fraud gate."""
    instruction = (
        f"{CAPITAL_HARD_GATE} This is a deterministic educational draft/check/scenario, "
        "not legal, securities, tax, or investment advice and not approval of an exemption "
        "or offering. Never describe modeled or target returns as promised, guaranteed, "
        "risk-free, or assured; verify every material fact and disclose risks and conflicts."
    )
    if next_step:
        instruction = f"{instruction} Next: {next_step.strip()}"
    return instruction


__all__ = [
    "CAPITAL_HARD_GATE",
    "capital_guardrail",
    "EXECUTION_DISCLAIMER",
    "execution_guardrail",
    "financing_guardrail",
    "structure_guardrail",
]
