"""Deterministic lender waiver/extension/modification request assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


REQUEST_TYPES = frozenset({"waiver", "extension", "modification"})
COUNSEL_FLAG = (
    "Counsel review required — this is a business request draft, not legal advice, "
    "a reservation-of-rights analysis, or an enforceable loan-document amendment."
)
LENDER_HISTORY_POINTER = "cre_mcp.ledger.report.lender_track_record"

_LOAN_FIELDS = frozenset(
    {
        "loan",
        "loan_id",
        "loan_number",
        "lender",
        "borrower",
        "guarantor",
        "property",
        "collateral",
        "balance",
        "balance_cents",
        "original_balance_cents",
        "rate",
        "maturity",
        "maturity_date",
        "payment_status",
        "covenants",
        "cause",
        "cure_plan",
        "contact",
        "servicer",
    }
)
_ASK_FIELDS = frozenset(
    {
        "type",
        "terms",
        "cause",
        "cure_plan",
        "requested_until",
        "justification",
        "supporting_documents",
    }
)
_COVENANT_FIELDS = frozenset(
    {
        "status",
        "projection_label",
        "warning",
        "lender_ledger_pointer",
        "missing_inputs",
        "periods",
        "first_breach_period",
        "cash_sweep_activation_timeline",
        "early_warnings",
        "assumption_sheet",
        "covenant_levels",
        "covenant_computability",
        "valuation_dependent_covenants",
        "test",
        "covenant",
        "period",
        "projected_noi",
        "beginning_balance",
        "projected_debt_service",
        "ending_balance",
        "valuation",
        "dscr",
        "dscr_covenant",
        "dscr_breach",
        "dscr_status",
        "ltv",
        "ltv_covenant",
        "ltv_breach",
        "ltv_status",
        "debt_yield",
        "debt_yield_covenant",
        "debt_yield_breach",
        "debt_yield_status",
        "cash_sweep_active",
        "cash_sweep_basis",
        "cushion",
        "actual",
        "threshold",
        "minimum",
        "maximum",
        "result",
        "breach",
        "breached",
        "cause",
        "cure_plan",
        "as_of",
    }
)


def _text(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _structured_value(value: Any) -> str:
    if value is None:
        return "Not supplied"
    if isinstance(value, str):
        return value.strip() or "Not supplied"
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _covenant_payload(value: Any) -> tuple[Any, list[str]]:
    if value is None:
        return None, []
    if isinstance(value, Mapping):
        return dict(value), [
            f"covenant_results.{key}"
            for key in value
            if key not in _COVENANT_FIELDS
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows: list[dict[str, Any]] = []
        unrecognized: list[str] = []
        for index, row in enumerate(value):
            if not isinstance(row, Mapping):
                raise ValueError(f"covenant_results[{index}] must be an object")
            rows.append(dict(row))
            unrecognized.extend(
                f"covenant_results[{index}].{key}"
                for key in row
                if key not in _COVENANT_FIELDS
            )
        return rows, unrecognized
    raise ValueError("covenant_results must be an object, a list of objects, or null")


def _row_is_breach(row: Mapping[str, Any]) -> bool:
    for key in ("breach", "breached", "dscr_breach", "ltv_breach", "debt_yield_breach"):
        if row.get(key) is True:
            return True
    status = str(row.get("status", row.get("result", ""))).strip().casefold()
    return status in {"breach", "breached", "failed", "fail", "noncompliant", "non-compliant"}


def _breach_summary(payload: Any) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    first_breach: Any = None
    early_warnings: list[Any] = []
    if isinstance(payload, Mapping):
        raw_periods = payload.get("periods")
        if isinstance(raw_periods, Sequence) and not isinstance(raw_periods, (str, bytes)):
            rows.extend(row for row in raw_periods if isinstance(row, Mapping))
        elif any(key in payload for key in ("breach", "breached", "status", "result")):
            rows.append(payload)
        first_breach = payload.get("first_breach_period")
        raw_warnings = payload.get("early_warnings")
        if isinstance(raw_warnings, Sequence) and not isinstance(raw_warnings, (str, bytes)):
            early_warnings = list(raw_warnings)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        rows.extend(row for row in payload if isinstance(row, Mapping))
    breached_rows = [dict(row) for row in rows if _row_is_breach(row)]
    forecast_first_breach_present = False
    if isinstance(first_breach, Mapping):
        forecast_first_breach_present = any(value is not None for value in first_breach.values())
    elif first_breach is not None:
        forecast_first_breach_present = True
    return {
        "breach_detected": bool(breached_rows) or forecast_first_breach_present,
        "breached_tests": breached_rows,
        "first_breach_period": first_breach,
        "early_warnings": early_warnings,
        "source": (
            "caller-supplied covenant results; compatible with the structured output of "
            "cre_mcp.debt.covenants.covenant_forecast"
        ),
    }


def prepare_waiver_request(
    loan: Mapping[str, Any] | None,
    covenant_results: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ask: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a review-ready business memo without implying lender consent."""

    if not isinstance(loan, Mapping):
        raise ValueError("loan must be an object")
    if not isinstance(ask, Mapping):
        raise ValueError("ask must be an object")
    ask_type = _text(ask.get("type"), "ask.type").casefold()
    if ask_type not in REQUEST_TYPES:
        allowed = ", ".join(sorted(REQUEST_TYPES))
        raise ValueError(f"ask.type must be one of: {allowed}")

    covenant_payload, covenant_unrecognized = _covenant_payload(covenant_results)
    cause = ask.get("cause", loan.get("cause"))
    if cause is None and isinstance(covenant_payload, Mapping):
        cause = covenant_payload.get("cause")
    cure_plan = ask.get("cure_plan", loan.get("cure_plan"))
    if cure_plan is None and isinstance(covenant_payload, Mapping):
        cure_plan = covenant_payload.get("cure_plan")
    terms = ask.get("terms")
    missing_inputs = []
    if covenant_payload is None:
        missing_inputs.append("covenant_results")
    if cause is None:
        missing_inputs.append("cause")
    if cure_plan is None:
        missing_inputs.append("cure_plan")
    if terms is None:
        missing_inputs.append("ask.terms")

    lender = loan.get("lender")
    lender_label = str(lender).strip() if lender not in (None, "") else None
    loan_identifier = next(
        (
            str(loan[key]).strip()
            for key in ("loan", "loan_id", "loan_number")
            if loan.get(key) not in (None, "")
        ),
        None,
    )
    request = {
        "type": ask_type,
        "terms": terms,
        "requested_until": ask.get("requested_until"),
        "justification": ask.get("justification"),
        "supporting_documents": ask.get("supporting_documents"),
    }
    covenant_summary = _breach_summary(covenant_payload)
    memo = {
        "title": f"{ask_type.title()} request" + (f" — {loan_identifier}" if loan_identifier else ""),
        "loan_facts": dict(loan),
        "covenant_test_results": covenant_payload,
        "covenant_summary": covenant_summary,
        "cause": cause,
        "cure_plan": cure_plan,
        "request": request,
    }
    memo_text = "\n\n".join(
        (
            f"REQUEST MEMO — {memo['title']}",
            f"Loan facts\n{_structured_value(memo['loan_facts'])}",
            f"Covenant test results\n{_structured_value(covenant_payload)}",
            f"Cause\n{_structured_value(cause)}",
            f"Cure plan\n{_structured_value(cure_plan)}",
            f"Requested {ask_type}\n{_structured_value(request)}",
            COUNSEL_FLAG,
        )
    )
    history_note = (
        f"Review read-only lender execution history for {lender_label!r} via "
        f"{LENDER_HISTORY_POINTER}; history is context only and does not predict consent."
        if lender_label is not None
        else f"Lender is not supplied; add it before consulting {LENDER_HISTORY_POINTER}."
    )
    unrecognized = sorted(
        [f"loan.{key}" for key in loan if key not in _LOAN_FIELDS]
        + [f"ask.{key}" for key in ask if key not in _ASK_FIELDS]
        + covenant_unrecognized
    )
    return {
        "status": "draft_for_lender_and_counsel_review",
        "memo": memo,
        "memo_text": memo_text,
        "facts": dict(loan),
        "covenant_test_results": covenant_payload,
        "covenant_summary": covenant_summary,
        "cause": cause,
        "cure_plan": cure_plan,
        "ask": request,
        "missing_inputs": missing_inputs,
        "counsel_flag": COUNSEL_FLAG,
        "lender_history_note": history_note,
        "lender_history": {
            "lender": lender_label,
            "read_only_function": LENDER_HISTORY_POINTER,
            "result": None,
            "note": history_note,
        },
        "unrecognized_inputs": unrecognized,
    }


__all__ = [
    "COUNSEL_FLAG",
    "LENDER_HISTORY_POINTER",
    "REQUEST_TYPES",
    "prepare_waiver_request",
]
