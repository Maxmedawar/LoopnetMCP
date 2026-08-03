"""Transfer-consent and due-on-sale screening for CRE transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from cre_mcp.leases.models import CitedClaim
from cre_mcp.obligations.restrictions import RestrictionSet, extract_restrictions

IntendedTransfer = Literal[
    "assignment", "sublease", "master_lease", "sale", "transfer_of_control"
]

_TIMING_NOTE = (
    "CONVENTION — begin consent review before signing/closing and build time for "
    "document review, questions, conditions, and execution; the cited documents "
    "and the consenting party control the actual notice and timing requirements."
)


@dataclass(frozen=True)
class ConsentRequirement:
    who: str
    trigger: str
    timing_note: str
    evidence: CitedClaim


@dataclass(frozen=True)
class ConsentFatalFlag:
    code: str
    message: str
    evidence: CitedClaim


@dataclass
class ConsentScreen:
    intended: IntendedTransfer
    lease_assignment_subletting: CitedClaim
    assignment_subletting_standard: str | None
    due_on_sale: CitedClaim
    loan_transfer_triggers: list[CitedClaim] = field(default_factory=list)
    change_of_control_catches: list[CitedClaim] = field(default_factory=list)
    required_consents: list[ConsentRequirement] = field(default_factory=list)
    fatal_flags: list[ConsentFatalFlag] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    counsel_routing: str = (
        "Route classification, enforceability, waiver/amendment effect, lender trigger, "
        "consent form, and closing sequencing to transaction and lender counsel."
    )
    posture: str = (
        "Advisory deterministic screen only; no legal conclusion or authorization to transfer."
    )

    @property
    def lease_transfer_clause(self) -> CitedClaim:
        return self.lease_assignment_subletting


def _structured_claim(value: Any, *, locator: str) -> CitedClaim:
    rendered = str(value).strip() or "structured input supplied"
    return CitedClaim.stated(
        value,
        quote=rendered[:200],
        locator=locator,
        confidence=1.0,
        source="structured_input",
    )


def _standard(claim: CitedClaim) -> str | None:
    if claim.status == "missing" or not isinstance(claim.value, Mapping):
        return None
    value = claim.value.get("standard")
    return str(value) if value is not None else None


def _applies(claim: CitedClaim, intended: IntendedTransfer) -> bool:
    if not isinstance(claim.value, Mapping):
        return False
    applies = set(str(item) for item in claim.value.get("applies_to", []))
    if not applies:
        return intended in {"assignment", "sublease", "master_lease"}
    if intended == "master_lease":
        return bool(applies & {"assignment", "sublease"})
    return intended in applies


def _select_clause(restrictions: RestrictionSet, intended: IntendedTransfer) -> CitedClaim:
    relevant = [
        claim for claim in restrictions.assignment_subletting_clauses
        if _applies(claim, intended)
    ]
    if not relevant:
        # A clause may be unclear about whether it reaches the intended
        # structure. Preserve it as the screen evidence rather than inventing a
        # clean permission.
        relevant = restrictions.assignment_subletting_clauses
    if not relevant:
        return CitedClaim.missing(source="lease")
    priority = {
        "prohibited": 0,
        "consent_required": 1,
        "consent_not_unreasonably_withheld": 2,
        "conditional_free": 3,
        "free": 4,
        "change_of_control_exception": 5,
        "unclear": 6,
    }
    return min(relevant, key=lambda claim: priority.get(_standard(claim) or "", 99))


def _truthy_due_on_sale(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        for key in ("present", "applies", "triggered", "requires_consent", "value"):
            if isinstance(value.get(key), bool):
                return bool(value[key])
        rendered = str(value).casefold()
    elif value is None:
        return None
    else:
        rendered = str(value).casefold()
    if any(token in rendered for token in ("none", "not applicable", "does not apply", "no due")):
        return False
    if any(token in rendered for token in ("due on sale", "due-on-sale", "becomes due", "lender consent", "approval required")):
        return True
    return None


def _materialize_transfer_terms(loan_terms: Mapping[str, Any]) -> list[CitedClaim]:
    raw = loan_terms.get("transfer_provisions")
    if raw is None:
        return []
    if isinstance(raw, (str, Mapping)):
        values = [raw]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = [raw]
    return [
        _structured_claim(value, locator=f"loan_terms.transfer_provisions[{index}]")
        for index, value in enumerate(values)
    ]


def _term_may_trigger(claim: CitedClaim, intended: IntendedTransfer) -> bool:
    rendered = str(claim.value).casefold()
    if any(token in rendered for token in ("permitted without consent", "no consent required", "not a transfer")):
        return False
    trigger_words = ("consent", "approval", "prohibit", "due", "transfer", "assignment", "sale", "change of control")
    if not any(token in rendered for token in trigger_words):
        return False
    intended_words = {
        "assignment": ("assign", "transfer"),
        "sublease": ("sublease", "sublet", "transfer"),
        "master_lease": ("lease", "sublease", "assign", "transfer"),
        "sale": ("sale", "sell", "transfer", "due"),
        "transfer_of_control": ("control", "ownership", "transfer"),
    }
    return any(token in rendered for token in intended_words[intended])


def screen_transfer_consents(docs: Mapping[str, Any]) -> ConsentScreen:
    """Screen lease and structured loan terms for transfer consent triggers.

    ``loan_terms`` may be omitted.  In that case the screen remains callable and
    explicitly reports that lender/due-on-sale review is missing.
    """
    if not isinstance(docs, Mapping):
        raise TypeError("docs must be a mapping")
    intended = str(docs.get("intended", ""))
    allowed = {"assignment", "sublease", "master_lease", "sale", "transfer_of_control"}
    if intended not in allowed:
        raise ValueError(
            "docs.intended must be assignment, sublease, master_lease, sale, or transfer_of_control"
        )
    intended_typed: IntendedTransfer = intended  # type: ignore[assignment]

    lease_text = docs.get("lease_text")
    if lease_text is None:
        restrictions = RestrictionSet(kind="lease")
        lease_gap = True
    elif not isinstance(lease_text, str):
        raise TypeError("docs.lease_text must be a string when supplied")
    else:
        restrictions = extract_restrictions(lease_text, "lease")
        lease_gap = False
    selected = _select_clause(restrictions, intended_typed)
    standard = _standard(selected)
    screen = ConsentScreen(
        intended=intended_typed,
        lease_assignment_subletting=selected,
        assignment_subletting_standard=standard,
        due_on_sale=CitedClaim.missing(source="structured_input"),
    )

    if lease_gap:
        screen.gaps.append("lease_text_missing")
    elif selected.status == "missing":
        screen.gaps.append("lease_assignment_subletting_language_not_found")
    elif standard == "unclear":
        screen.gaps.append("lease_transfer_standard_unclear")

    screen.change_of_control_catches = [
        claim
        for claim in restrictions.assignment_subletting_clauses
        if isinstance(claim.value, Mapping)
        and (
            "transfer_of_control" in claim.value.get("applies_to", [])
            or claim.value.get("change_of_control_is_assignment") is not None
        )
    ]

    if standard in {"consent_required", "consent_not_unreasonably_withheld"} and _applies(selected, intended_typed):
        screen.required_consents.append(
            ConsentRequirement(
                who="Landlord",
                trigger=f"Cited lease transfer standard: {standard}",
                timing_note=_TIMING_NOTE,
                evidence=selected,
            )
        )

    absolute_block = standard == "prohibited" and _applies(selected, intended_typed)
    if absolute_block:
        screen.required_consents.append(
            ConsentRequirement(
                who="Landlord and transaction counsel",
                trigger="Absolute prohibition screen; determine whether an amendment, waiver, or different structure is available",
                timing_note=_TIMING_NOTE,
                evidence=selected,
            )
        )
        code = (
            "deal_killer_absolute_prohibition_master_lease"
            if intended_typed == "master_lease"
            else "absolute_transfer_prohibition"
        )
        label = "DEAL-KILLER FLAG — " if intended_typed == "master_lease" else "FATAL FLAG — "
        screen.fatal_flags.append(
            ConsentFatalFlag(
                code=code,
                message=(
                    label
                    + f"the cited lease screen classifies the intended {intended_typed} against "
                    "absolute prohibition language. Counsel must confirm scope and available paths."
                ),
                evidence=selected,
            )
        )

    if intended_typed == "transfer_of_control":
        catching = [
            claim for claim in screen.change_of_control_catches
            if isinstance(claim.value, Mapping)
            and claim.value.get("change_of_control_is_assignment") is True
        ]
        for claim in catching:
            claim_standard = _standard(claim)
            if claim_standard in {"consent_required", "consent_not_unreasonably_withheld"}:
                screen.required_consents.append(
                    ConsentRequirement(
                        who="Landlord",
                        trigger="Cited change-of-control language is screened as an assignment trigger",
                        timing_note=_TIMING_NOTE,
                        evidence=claim,
                    )
                )
            elif claim_standard == "prohibited":
                screen.fatal_flags.append(
                    ConsentFatalFlag(
                        code="change_of_control_absolute_prohibition",
                        message=(
                            "FATAL FLAG — cited language may treat the intended change of control as "
                            "an absolutely prohibited assignment; counsel must classify the transaction."
                        ),
                        evidence=claim,
                    )
                )

    loan_terms = docs.get("loan_terms")
    if loan_terms is None:
        screen.gaps.append("loan_terms_missing_due_on_sale_and_transfer_review_not_performed")
    elif not isinstance(loan_terms, Mapping):
        raise TypeError("docs.loan_terms must be a mapping when supplied")
    else:
        due_raw = loan_terms.get("due_on_sale")
        due_state = _truthy_due_on_sale(due_raw)
        if due_raw is None:
            screen.gaps.append("loan_terms_due_on_sale_missing")
        else:
            screen.due_on_sale = _structured_claim(due_raw, locator="loan_terms.due_on_sale")
        screen.loan_transfer_triggers = _materialize_transfer_terms(loan_terms)
        triggered_terms = [
            claim for claim in screen.loan_transfer_triggers
            if _term_may_trigger(claim, intended_typed)
        ]
        due_triggered = due_state is True and intended_typed in {
            "sale", "transfer_of_control", "assignment"
        }
        evidence = screen.due_on_sale if due_triggered else (triggered_terms[0] if triggered_terms else None)
        if evidence is not None:
            screen.required_consents.append(
                ConsentRequirement(
                    who="Lender / loan servicer",
                    trigger="Structured loan terms indicate a due-on-sale or transfer-consent trigger for the intended transaction",
                    timing_note=_TIMING_NOTE,
                    evidence=evidence,
                )
            )
            screen.fatal_flags.append(
                ConsentFatalFlag(
                    code="loan_transfer_trigger_requires_resolution",
                    message=(
                        "FATAL FLAG — supplied loan terms indicate a transfer/due-on-sale trigger that "
                        "must be resolved with lender and counsel before relying on the structure."
                    ),
                    evidence=evidence,
                )
            )

    # Stable de-duplication retains the first and strongest cited reason.
    unique_requirements: list[ConsentRequirement] = []
    requirement_keys: set[tuple[str, str]] = set()
    for requirement in screen.required_consents:
        key = (requirement.who, requirement.evidence.locator)
        if key not in requirement_keys:
            requirement_keys.add(key)
            unique_requirements.append(requirement)
    screen.required_consents = unique_requirements
    screen.gaps = sorted(set(screen.gaps))
    return screen


__all__ = [
    "IntendedTransfer",
    "ConsentRequirement",
    "ConsentFatalFlag",
    "ConsentScreen",
    "screen_transfer_consents",
]
