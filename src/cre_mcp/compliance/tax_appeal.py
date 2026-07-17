"""Assemble property-tax appeal evidence without representing a filing.

The output is an arithmetic and document-collection aid for a tax consultant or
counsel.  It does not select a legally supportable valuation method, determine
admissibility, calculate a statutory deadline, or submit an appeal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


EVIDENCE_ASSEMBLY_DISCLAIMER = (
    "EVIDENCE ASSEMBLY ONLY — not a tax appeal or filing. A qualified property-tax "
    "consultant or counsel must verify the evidence, procedure, and deadline and "
    "prepare and submit any appeal."
)

_CENTS = Decimal("0.01")
_RATE = Decimal("0.000001")


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{label} must be a finite {qualifier} number")
    return number


def _money(value: Decimal) -> float:
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def _rate(value: Any) -> tuple[Decimal, str]:
    supplied = _decimal(value, "cap_rate", positive=True)
    interpretation = "decimal"
    if supplied > 1:
        if supplied > 100:
            raise ValueError("cap_rate cannot exceed 100 percent")
        supplied /= 100
        interpretation = "percent"
    if supplied > 1:
        raise ValueError("cap_rate must be no more than 1.0 (100 percent)")
    return supplied.quantize(_RATE, rounding=ROUND_HALF_UP), interpretation


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    return text or None


def _condition_notes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        note = value.strip()
        return [note] if note else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        notes = [str(item).strip() for item in value if str(item).strip()]
        return notes
    raise TypeError("condition_notes must be text, a sequence of notes, or null")


def build_appeal_package(
    assessment: Mapping[str, Any],
    jurisdiction: Mapping[str, Any],
) -> dict[str, Any]:
    """Build transparent over-assessment evidence and a filing handoff checklist.

    ``cap_rate`` must be supplied in ``assessment`` (preferred) or
    ``jurisdiction``. Values such as ``0.075`` and ``7.5`` are interpreted as
    7.5 percent and the interpretation is returned. Comparable observations are
    input evidence only; the function does not decide whether they are legally
    comparable.
    """

    if not isinstance(assessment, Mapping):
        raise TypeError("assessment must be a mapping")
    if not isinstance(jurisdiction, Mapping):
        raise TypeError("jurisdiction must be a mapping")

    assessed_value = _decimal(
        assessment.get("assessed_value"), "assessed_value", positive=True
    )
    noi_actual = _decimal(assessment.get("noi_actual"), "noi_actual")
    sf = _decimal(assessment.get("sf"), "sf", positive=True)
    cap_input = assessment.get("cap_rate", jurisdiction.get("cap_rate"))
    if cap_input is None:
        raise ValueError(
            "cap_rate is required in assessment or jurisdiction; no market cap rate is inferred"
        )
    cap_rate, cap_interpretation = _rate(cap_input)

    raw_comps = assessment.get("comps", [])
    if raw_comps is None:
        raw_comps = []
    if not isinstance(raw_comps, Sequence) or isinstance(raw_comps, (str, bytes)):
        raise TypeError("comps must be a sequence of mappings with psf")
    comp_psf: list[Decimal] = []
    for index, comp in enumerate(raw_comps):
        if not isinstance(comp, Mapping):
            raise TypeError(f"comps[{index}] must be a mapping")
        comp_psf.append(_decimal(comp.get("psf"), f"comps[{index}].psf", positive=True))

    notes = _condition_notes(assessment.get("condition_notes"))
    indicated_value = noi_actual / cap_rate
    income_difference = assessed_value - indicated_value
    assessed_psf = assessed_value / sf
    average_comp_psf = sum(comp_psf, Decimal("0")) / len(comp_psf) if comp_psf else None
    comp_difference_psf = (
        assessed_psf - average_comp_psf if average_comp_psf is not None else None
    )
    comp_indicated_value = average_comp_psf * sf if average_comp_psf is not None else None

    income_line = {
        "type": "income_approach",
        "formula": "noi_actual / cap_rate",
        "noi_actual": _money(noi_actual),
        "cap_rate": float(cap_rate),
        "indicated_value": _money(indicated_value),
        "assessed_value": _money(assessed_value),
        "assessed_minus_indicated": _money(income_difference),
        "supports_over_assessment": income_difference > 0,
    }
    comp_line = {
        "type": "comparable_psf",
        "formula": "assessed_value / sf compared with arithmetic mean of supplied comp psf",
        "assessed_psf": _money(assessed_psf),
        "comp_psf": [_money(value) for value in comp_psf],
        "average_comp_psf": _money(average_comp_psf) if average_comp_psf is not None else None,
        "assessed_minus_average_comp_psf": (
            _money(comp_difference_psf) if comp_difference_psf is not None else None
        ),
        "comp_indicated_value": (
            _money(comp_indicated_value) if comp_indicated_value is not None else None
        ),
        "supports_over_assessment": (
            comp_difference_psf > 0 if comp_difference_psf is not None else None
        ),
        "comparability_status": "UNVERIFIED — consultant/counsel review required",
    }
    condition_line = {
        "type": "condition",
        "notes": notes,
        "supports_over_assessment": True if notes else None,
        "verification_status": (
            "SUPPLIED — obtain dated photos/reports and professional review"
            if notes
            else "UNKNOWN — no condition notes supplied"
        ),
    }

    deadline = _optional_text(jurisdiction.get("deadline"))
    board = _optional_text(jurisdiction.get("board"))
    deadline_source = _optional_text(jurisdiction.get("deadline_source"))
    deadline_row = {
        "deadline": deadline,
        "board": board,
        "source": deadline_source or "user-supplied jurisdiction input",
        "status": "TRACK INPUT; PROFESSIONAL MUST VERIFY" if deadline else "UNKNOWN",
        "action": (
            "Consultant/counsel to verify governing rule and filing receipt requirements"
        ),
    }

    checklist = [
        {
            "item": "assessment_notice_and_tax_bill",
            "status": "required_not_verified",
        },
        {"item": "actual_noi_support", "status": "input_supplied"},
        {
            "item": "cap_rate_support",
            "status": "input_supplied; market/legal support not verified",
        },
        {
            "item": "comparable_records",
            "status": "input_supplied" if comp_psf else "missing",
        },
        {
            "item": "condition_photos_reports",
            "status": "notes_supplied; corroboration needed" if notes else "missing",
        },
        {
            "item": "board_forms_authorization_and_fee",
            "status": "consultant/counsel to obtain and verify",
        },
        {
            "item": "deadline_and_proof_of_receipt",
            "status": "input supplied; verify" if deadline else "UNKNOWN; verify immediately",
        },
    ]

    return {
        "package_type": "property_tax_appeal_evidence_assembly",
        "filing_status": "NOT FILED",
        "disclaimer": EVIDENCE_ASSEMBLY_DISCLAIMER,
        "consultant_counsel_required": True,
        "assessment_inputs": {
            "assessed_value": _money(assessed_value),
            "noi_actual": _money(noi_actual),
            "sf": _money(sf),
            "cap_rate": float(cap_rate),
            "cap_rate_input_interpretation": cap_interpretation,
        },
        "income_approach": income_line,
        "comparable_psf_evidence": comp_line,
        "condition_evidence": condition_line,
        "evidence_lines": [income_line, comp_line, condition_line],
        "package_checklist": checklist,
        "deadline_tracking": deadline_row,
        "deadline_tracking_rows": [deadline_row],
    }


__all__ = ["EVIDENCE_ASSEMBLY_DISCLAIMER", "build_appeal_package"]
