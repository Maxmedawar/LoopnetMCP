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


__all__ = ["EXECUTION_DISCLAIMER", "execution_guardrail"]
