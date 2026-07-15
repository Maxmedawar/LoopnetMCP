"""Read-only diligence requests from truth conflicts and data-room gaps.

The builder deliberately consumes reports instead of opening either subsystem's
database.  In particular, ``DataRoomStore.completeness_index`` maintains a
snapshot and can auto-match documents, so calling it here would not be a
read-only operation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


# Relative field weights are ranking conventions, expressed in basis points to
# keep the calculation transparent and free of binary floating-point output.
# They are not cap-rate assumptions or appraised-value multipliers.
FIELD_WEIGHTS_BPS: dict[str, int] = {
    "noi": 10_000,
    "net_operating_income": 10_000,
    "base_rent": 9_000,
    "rent": 9_000,
    "gross_potential_rent": 8_500,
    "effective_gross_income": 8_500,
    "operating_expenses": 8_000,
    "occupancy": 8_000,
    "occupancy_rate": 8_000,
    "rentable_sf": 7_500,
    "tenant_name": 7_000,
    "lease_expiration": 7_000,
    "lease_commencement": 6_500,
    "security_deposit": 5_000,
    "deposit": 5_000,
    "guarantor": 5_000,
}
DEFAULT_FIELD_WEIGHT_BPS = 2_500


# Missing documents do not have an honest dollar magnitude.  This separate
# proxy ranks the unquantified request tier without inventing valuation dollars.
DOCUMENT_PRIORITY_BPS: dict[str, int] = {
    "purchase_sale_agreement": 10_000,
    "all_leases": 9_800,
    "lease_amendments": 9_700,
    "rent_roll": 9_600,
    "t12_operating_statement": 9_500,
    "historical_financials": 9_000,
    "tenant_ledgers": 9_000,
    "tenant_financials": 8_800,
    "title_commitment": 8_800,
    "phase_i": 8_800,
    "pca": 8_500,
    "alta_survey": 8_400,
    "tax_bills": 8_200,
    "estoppels": 8_000,
    "security_deposit_ledger": 8_000,
    "cam_reconciliations": 7_800,
    "insurance_loss_runs": 7_500,
    "seller_disclosures": 7_500,
    "service_contracts": 7_000,
    "tenant_cois": 6_500,
}
DEFAULT_DOCUMENT_PRIORITY_BPS = 5_000

_STATUS_FACTOR_BPS = {"missing": 10_000, "requested": 7_500}
_MONETARY_UNITS = {
    "usd",
    "usd_per_year",
    "usd_per_month",
    "usd_per_sqft",
}

_TRUTH_REPORT_KEYS = {
    "deal_id",
    "resolutions",
    "conflicts",
    "doc_kinds_present",
    "generated_at",
}
_DATA_ROOM_INDEX_KEYS = {
    "deal_id",
    "initialized",
    "deal_type",
    "taxonomy_name",
    "taxonomy_item_count",
    "as_of",
    "deal_stage",
    "current_phase",
    "current_phase_source",
    "score",
    "earned_weighted_points",
    "possible_weighted_points",
    "formula",
    "items",
    "blockers",
    "unassigned_gaps",
    "conditional_not_activated",
    "auto_matches",
    "auto_match_limit",
    "note",
}
_CONFLICT_KEYS = {
    "field",
    "subject",
    "rule",
    "severity",
    "claims",
    "resolved_value",
    "resolved_value_cents",
    "resolved_amount_cents",
    "resolution",
    "needs_human_review",
    "explanation",
    # Explicit alternate shape for callers that already split the resolution.
    "winner",
    "losers",
}
_CLAIM_KEYS = {
    "field",
    "subject",
    "figure",
    "flags",
    # Explicit flattened figure form.
    "value",
    "unit",
    "value_cents",
    "amount_cents",
    "lineage",
}
_FIGURE_KEYS = {
    "value",
    "unit",
    "confidence",
    "lineage",
    "value_cents",
    "amount_cents",
}
_LINEAGE_KEYS = {
    "document_id",
    "doc_kind",
    "source_channel",
    "page",
    "cell",
    "bbox",
    "raw_text",
    "extraction_method",
    "origin",
}
_DATA_ROOM_ITEM_KEYS = {
    "doc_key",
    "label",
    "phase",
    "requirement",
    "required",
    "trigger",
    "why_it_matters",
    "what_missing_costs",
    "deal_id",
    "status",
    "assignee",
    "due_date",
    "source_document_id",
    "notes",
    "updated_at",
    "conditional_active",
    "in_current_phase_scope",
    "graded",
    "weight",
    "status_credit",
    "weighted_credit",
    "auto_match_doc_kind",
}
_DATA_ROOM_STATUSES = {"missing", "requested", "received", "reviewed", "issue_found"}


def _error(message: str, **details: Any) -> dict[str, Any]:
    return {"error": message, **details}


def _normalized_deal_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("deal_id must be a non-blank string")
    return value.strip()


def _unknown_keys(report: Mapping[str, Any], allowed: set[str]) -> list[str]:
    return sorted(str(key) for key in report if key not in allowed)


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = _unknown_keys(value, allowed)
    if unknown:
        raise ValueError(f"unrecognized input fields at {path}: {', '.join(unknown)}")


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a list")
    return list(value)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("monetary value must be numeric")
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        if text.startswith("$"):
            text = text[1:].strip()
        if negative:
            text = f"-{text}"
        value = text
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("monetary value must be numeric") from exc
    if not amount.is_finite():
        raise ValueError("monetary value must be finite")
    return amount


def _integer_cents(value: Any, *, already_cents: bool = False) -> int:
    amount = _decimal(value)
    if already_cents:
        integral = amount.to_integral_value(rounding=ROUND_HALF_UP)
        if amount != integral:
            raise ValueError("a *_cents value must be an integer")
        return int(integral)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _field_key(value: Any) -> str:
    return str(value or "unknown").strip().casefold().replace(" ", "_") or "unknown"


def _lineage(claim: Mapping[str, Any]) -> Mapping[str, Any]:
    figure = claim.get("figure")
    if isinstance(figure, Mapping) and isinstance(figure.get("lineage"), Mapping):
        return figure["lineage"]
    if isinstance(claim.get("lineage"), Mapping):
        return claim["lineage"]
    return {}


def _claim_value(claim: Mapping[str, Any]) -> tuple[Any, str | None, bool]:
    """Return (value, unit, value_is_already_cents) for supported report shapes."""

    figure_value = claim.get("figure")
    figure = figure_value if isinstance(figure_value, Mapping) else claim
    for key in ("value_cents", "amount_cents"):
        if key in figure:
            return figure[key], "cents", True
    return figure.get("value"), str(figure.get("unit")) if figure.get("unit") else None, False


def _claim_cents(claim: Mapping[str, Any]) -> int | None:
    value, unit, already_cents = _claim_value(claim)
    if value is None:
        return None
    if already_cents:
        return _integer_cents(value, already_cents=True)
    if unit is None or unit.strip().casefold() not in _MONETARY_UNITS:
        return None
    return _integer_cents(value)


def _citation(claim: Mapping[str, Any]) -> dict[str, Any]:
    lineage = _lineage(claim)
    page = lineage.get("page")
    cell = lineage.get("cell")
    document_id = lineage.get("document_id")
    location = str(cell) if cell else (f"p{page}" if page is not None else None)
    return {
        "document_id": str(document_id) if document_id is not None else None,
        "doc_kind": str(lineage.get("doc_kind")) if lineage.get("doc_kind") else None,
        "location": location,
        "raw_text": str(lineage.get("raw_text") or ""),
    }


def _claims_for(conflict: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_claims = conflict.get("claims")
    if raw_claims is not None:
        claims = _as_list(raw_claims, "truth_report.conflicts[].claims")
    else:
        claims = []
        winner = conflict.get("winner")
        if winner is not None:
            claims.append(winner)
        if conflict.get("losers") is not None:
            claims.extend(_as_list(conflict["losers"], "truth_report.conflicts[].losers"))
    normalized: list[Mapping[str, Any]] = []
    for index, raw_claim in enumerate(claims):
        path = f"truth_report.conflicts[].claims[{index}]"
        claim = _as_mapping(raw_claim, path)
        _reject_unknown(claim, _CLAIM_KEYS, path)
        figure = claim.get("figure")
        if figure is not None:
            figure_mapping = _as_mapping(figure, f"{path}.figure")
            _reject_unknown(figure_mapping, _FIGURE_KEYS, f"{path}.figure")
        else:
            figure_mapping = claim
        lineage = figure_mapping.get("lineage")
        if lineage is not None:
            lineage_mapping = _as_mapping(lineage, f"{path}.lineage")
            _reject_unknown(lineage_mapping, _LINEAGE_KEYS, f"{path}.lineage")
        normalized.append(claim)
    return normalized


def _resolved_cents(conflict: Mapping[str, Any], claims: list[Mapping[str, Any]]) -> int | None:
    if "resolved_value_cents" in conflict:
        return _integer_cents(conflict["resolved_value_cents"], already_cents=True)
    if "resolved_amount_cents" in conflict:
        return _integer_cents(conflict["resolved_amount_cents"], already_cents=True)
    if "resolved_value" in conflict and claims:
        _, unit, already_cents = _claim_value(claims[0])
        if already_cents:
            return _integer_cents(conflict["resolved_value"], already_cents=True)
        if unit is not None and unit.strip().casefold() in _MONETARY_UNITS:
            return _integer_cents(conflict["resolved_value"])
    return _claim_cents(claims[0]) if claims else None


def _money_text(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    absolute = abs(amount_cents)
    dollars, cents = divmod(absolute, 100)
    return f"{sign}${dollars:,}.{cents:02d}"


def _conflict_request(
    conflict: Mapping[str, Any],
    *,
    conflict_index: int,
    honest_gaps: list[str],
) -> dict[str, Any] | None:
    _reject_unknown(conflict, _CONFLICT_KEYS, f"truth_report.conflicts[{conflict_index}]")
    if not isinstance(conflict.get("field"), str) or not str(conflict["field"]).strip():
        raise ValueError(f"truth_report.conflicts[{conflict_index}].field must be non-blank text")
    if "needs_human_review" in conflict and not isinstance(
        conflict["needs_human_review"], bool
    ):
        raise ValueError(
            f"truth_report.conflicts[{conflict_index}].needs_human_review must be boolean"
        )
    resolution = str(conflict.get("resolution") or "").strip().casefold()
    if resolution and resolution not in {"auto_hierarchy", "corroborated", "unresolved"}:
        raise ValueError(
            f"truth_report.conflicts[{conflict_index}].resolution is unrecognized"
        )
    needs_review = conflict.get("needs_human_review") is True
    if resolution != "unresolved" and not needs_review:
        return None

    field = _field_key(conflict.get("field"))
    subject_value = conflict.get("subject")
    subject = str(subject_value).strip() if subject_value not in (None, "") else None
    claims = _claims_for(conflict)
    claim_amounts: list[tuple[int, Mapping[str, Any]]] = []
    for claim in claims:
        cents = _claim_cents(claim)
        if cents is not None:
            claim_amounts.append((cents, claim))

    winner_cents = _resolved_cents(conflict, claims)
    magnitude_cents: int | None = None
    if winner_cents is not None and claim_amounts:
        magnitude_cents = max(abs(amount - winner_cents) for amount, _ in claim_amounts)

    field_weight_bps = FIELD_WEIGHTS_BPS.get(field, DEFAULT_FIELD_WEIGHT_BPS)
    weighted_impact_cents = (
        magnitude_cents * field_weight_bps // 10_000
        if magnitude_cents is not None
        else None
    )
    if magnitude_cents is None:
        honest_gaps.append(
            f"Conflict {field}{f' [{subject}]' if subject else ''} has no comparable "
            "monetary claims, so no dollar valuation impact was estimated."
        )

    citations = [_citation(claim) for claim in claims]
    reported_values = [
        {"amount_cents": amount, "citation": _citation(claim)}
        for amount, claim in claim_amounts
    ]
    if reported_values:
        values_text = ", ".join(_money_text(item["amount_cents"]) for item in reported_values)
    else:
        values_text = "the conflicting non-monetary values in the cited sources"
    subject_text = f" for {subject}" if subject else ""
    request_text = (
        f"Please provide the authoritative source and supporting detail needed to resolve "
        f"the {field.replace('_', ' ')} conflict{subject_text}. The cited sources report "
        f"{values_text}; please identify the controlling value and provide the executed or "
        "source document that supports it."
    )
    why = str(conflict.get("explanation") or "").strip()
    if not why:
        why = (
            f"The unresolved {field.replace('_', ' ')} conflict can change underwriting "
            "and valuation; the engine does not average competing source claims."
        )

    return {
        "request_id": f"conflict:{conflict_index}:{field}:{subject or ''}",
        "request_type": "truth_conflict",
        "field": field,
        "subject": subject,
        "request_text": request_text,
        "why_it_matters": why,
        "reported_values": reported_values,
        "citations": citations,
        "conflict_magnitude_cents": magnitude_cents,
        "field_weight_bps": field_weight_bps,
        "valuation_impact_cents": weighted_impact_cents,
        "ranking_tier": "quantified_conflict" if weighted_impact_cents is not None else "unquantified_conflict",
        "rank_basis": (
            "conflict_magnitude_cents * field_weight_bps // 10000"
            if weighted_impact_cents is not None
            else "unquantified conflict; field weight is a tie-breaker only"
        ),
    }


def _document_request(item: Mapping[str, Any]) -> dict[str, Any] | None:
    _reject_unknown(item, _DATA_ROOM_ITEM_KEYS, "data_room_index.items[]")
    status = str(item.get("status") or "").strip().casefold()
    if status not in _DATA_ROOM_STATUSES:
        raise ValueError("data_room_index.items[].status is missing or unrecognized")
    for key in ("required", "conditional_active", "graded"):
        if key in item and not isinstance(item[key], bool):
            raise ValueError(f"data_room_index.items[].{key} must be boolean")
    if status not in {"missing", "requested"}:
        return None
    # A missing inactive conditional is explicitly out of scope.  A caller can
    # activate it in the data-room workflow by changing its status.
    if item.get("required") is False and item.get("conditional_active") is False:
        return None
    # Respect phase gating when the produced index supplies it.  Minimal report
    # fixtures without grading metadata remain usable.
    if "graded" in item and item.get("graded") is not True:
        return None

    doc_key = str(item.get("doc_key") or "").strip()
    if not doc_key:
        raise ValueError("data_room_index.items[].doc_key must be a non-blank string")
    label = str(item.get("label") or doc_key.replace("_", " ")).strip()
    why = str(item.get("why_it_matters") or item.get("what_missing_costs") or "").strip()
    if not why:
        why = "This in-scope document gap leaves a diligence assumption unsupported."
    prefix = "As a follow-up, please provide" if status == "requested" else "Please provide"
    request_text = f"{prefix} {label}."
    priority_bps = DOCUMENT_PRIORITY_BPS.get(doc_key, DEFAULT_DOCUMENT_PRIORITY_BPS)
    proxy_points = priority_bps * _STATUS_FACTOR_BPS[status] // 10_000
    return {
        "request_id": f"document:{doc_key}",
        "request_type": "missing_document",
        "doc_key": doc_key,
        "label": label,
        "phase": str(item.get("phase")) if item.get("phase") else None,
        "status": status,
        "request_text": request_text,
        "why_it_matters": why,
        "valuation_impact_cents": None,
        "document_priority_bps": priority_bps,
        "status_factor_bps": _STATUS_FACTOR_BPS[status],
        "document_priority_points": proxy_points,
        "ranking_tier": "unquantified_document_gap",
        "rank_basis": "document_priority_bps * status_factor_bps // 10000",
    }


def diligence_request_list(
    deal_id: str,
    truth_report: Mapping[str, Any] | None,
    data_room_index: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build a ready-to-send, valuation-ranked request list without writes.

    Both source reports are required explicitly.  This keeps the function a
    deterministic read of the truth reconciliation and data-room index supplied
    by the caller, and avoids side effects in either owning subsystem.
    """

    try:
        normalized_id = _normalized_deal_id(deal_id)
        truth = _as_mapping(truth_report, "truth_report")
        room = _as_mapping(data_room_index, "data_room_index")
    except (ArithmeticError, TypeError, ValueError) as exc:
        return _error(str(exc))

    unrecognized: dict[str, list[str]] = {}
    truth_unknown = _unknown_keys(truth, _TRUTH_REPORT_KEYS)
    room_unknown = _unknown_keys(room, _DATA_ROOM_INDEX_KEYS)
    if truth_unknown:
        unrecognized["truth_report"] = truth_unknown
    if room_unknown:
        unrecognized["data_room_index"] = room_unknown
    if unrecognized:
        return _error(
            "unrecognized input fields",
            unrecognized_inputs=unrecognized,
        )

    for label, report in (("truth_report", truth), ("data_room_index", room)):
        report_deal_id = report.get("deal_id")
        if report_deal_id is not None and str(report_deal_id).strip() != normalized_id:
            return _error(
                f"{label}.deal_id does not match deal_id",
                deal_id=normalized_id,
                report_deal_id=str(report_deal_id),
            )

    try:
        conflicts = _as_list(truth.get("conflicts", []), "truth_report.conflicts")
        room_items = _as_list(room.get("items", []), "data_room_index.items")
        honest_gaps: list[str] = []
        conflict_requests: list[dict[str, Any]] = []
        for index, raw_conflict in enumerate(conflicts):
            conflict = _as_mapping(raw_conflict, "truth_report.conflicts[]")
            request = _conflict_request(
                conflict,
                conflict_index=index,
                honest_gaps=honest_gaps,
            )
            if request is not None:
                conflict_requests.append(request)

        document_requests: list[dict[str, Any]] = []
        seen_doc_keys: set[str] = set()
        for raw_item in room_items:
            item = _as_mapping(raw_item, "data_room_index.items[]")
            request = _document_request(item)
            if request is None:
                continue
            doc_key = request["doc_key"]
            if doc_key in seen_doc_keys:
                raise ValueError(f"duplicate data-room item for doc_key {doc_key!r}")
            seen_doc_keys.add(doc_key)
            document_requests.append(request)
    except (ArithmeticError, TypeError, ValueError) as exc:
        return _error(str(exc))

    conflict_requests.sort(
        key=lambda item: (
            item["valuation_impact_cents"] is not None,
            item["valuation_impact_cents"] or 0,
            item["field_weight_bps"],
            item["request_id"],
        ),
        reverse=True,
    )
    document_requests.sort(
        key=lambda item: (
            item["document_priority_points"],
            item["document_priority_bps"],
            item["doc_key"],
        ),
        reverse=True,
    )

    initialized = room.get("initialized")
    if initialized is False:
        honest_gaps.append(
            "The data-room index is not initialized, so missing-document coverage cannot be assessed."
        )
    if not truth.get("conflicts") and not truth.get("resolutions"):
        honest_gaps.append(
            "The truth report contains no conflicts or resolutions; this may be a genuine empty state or an unpopulated report."
        )

    requests = [*conflict_requests, *document_requests]
    for rank, request in enumerate(requests, start=1):
        request["rank"] = rank
    ready_to_send = "\n".join(
        f"{request['rank']}. {request['request_text']} Why it matters: {request['why_it_matters']}"
        for request in requests
    )

    return {
        "deal_id": normalized_id,
        "request_count": len(requests),
        "unresolved_conflict_count": len(conflict_requests),
        "missing_document_count": len(document_requests),
        "requests": requests,
        "ready_to_send_request_list": ready_to_send,
        "valuation_impact_conventions": {
            "conflict_formula": "conflict_magnitude_cents * field_weight_bps // 10000",
            "conflict_magnitude": "maximum absolute difference between the reconciliation winner and cited monetary claims",
            "field_weights_bps": dict(FIELD_WEIGHTS_BPS),
            "default_field_weight_bps": DEFAULT_FIELD_WEIGHT_BPS,
            "document_formula": "document_priority_bps * status_factor_bps // 10000",
            "document_priority_bps": dict(DOCUMENT_PRIORITY_BPS),
            "default_document_priority_bps": DEFAULT_DOCUMENT_PRIORITY_BPS,
            "status_factor_bps": dict(_STATUS_FACTOR_BPS),
            "cross_tier_order": (
                "Quantified monetary conflicts first by weighted integer cents; "
                "unquantified conflicts next; document gaps last by priority proxy."
            ),
            "limitation": (
                "Weights are transparent triage conventions, not appraisal assumptions. "
                "No dollar impact is invented for a missing document or non-monetary conflict."
            ),
        },
        "honest_gaps": honest_gaps,
        "read_only_sources": ["truth reconciliation report", "data-room completeness index"],
    }


__all__ = [
    "DEFAULT_DOCUMENT_PRIORITY_BPS",
    "DEFAULT_FIELD_WEIGHT_BPS",
    "DOCUMENT_PRIORITY_BPS",
    "FIELD_WEIGHTS_BPS",
    "diligence_request_list",
]
