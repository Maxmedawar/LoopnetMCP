"""Transparent, evidence-aware disposition readiness audit.

The audit deliberately does not initialize or update a data room.  When one is
already present, its rows are read through a read-only SQLite connection.  The
result is a planning screen, not a statement that documents are legally
sufficient or that a property is marketable.
"""

from __future__ import annotations

import calendar
import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.dataroom.index import PHASE_WEIGHTS, STATUS_CREDITS
from cre_mcp.dataroom.taxonomy import get_taxonomy
from cre_mcp.taxecon import estimate_reassessment

DIMENSION_WEIGHTS: dict[str, float] = {
    "financial_records": 20.0,
    "lease_file": 25.0,
    "title_survey": 15.0,
    "physical": 15.0,
    "tax": 10.0,
    "data_room": 15.0,
}

STATUS_CREDIT: dict[str, float | None] = {
    "ready": 1.0,
    "attention": 0.5,
    "blocked": 0.0,
    "unknown": None,
    "not_applicable": None,
}

READINESS_RUBRIC: dict[str, Any] = {
    "dimension_weights_pct": dict(DIMENSION_WEIGHTS),
    "status_credit": dict(STATUS_CREDIT),
    "score_formula": (
        "sum(dimension_weight * status_credit); unknown and not_applicable receive "
        "zero score contribution, while evidence_coverage_pct separately exposes the "
        "weight supported by known evidence"
    ),
    "overall_status_rule": (
        "blocked if any dimension is blocked; otherwise attention if any dimension is "
        "attention or unknown; otherwise ready (not_applicable dimensions are ignored)"
    ),
    "data_room_thresholds": {
        "ready": "stored/read-only sale-scope completeness >= 85%",
        "attention": "60% to <85%",
        "blocked": "<60%",
        "unknown": "not initialized or no gradable rows",
    },
    "document_status_credit": dict(STATUS_CREDITS),
    "title_survey_freshness": {
        "title_ready_max_age_months": 6,
        "title_attention_max_age_months": 12,
        "survey_ready_max_age_months": 12,
        "survey_attention_max_age_months": 24,
        "note": "Planning convention only; title company, lender, buyer, and jurisdiction requirements control.",
    },
    "lease_sale_window": (
        "Lease critical dates are flagged from 180 days before through 365 days "
        "after target sale. Use cre_mcp.leases.critical_dates vocabulary: "
        "lease_expiration and option notice/exercise events."
    ),
    "lead_time_conventions": {
        "new_or_updated_survey_days": 90,
        "tenant_estoppels_days": 30,
        "title_update_days": 30,
        "financial_cleanup_days": 45,
        "unknown_evidence_collection_days": 10,
    },
}

_FINANCIAL_KEYS = (
    "t12_operating_statement",
    "historical_financials",
    "rent_roll",
    "tenant_ledgers",
    "tax_bills",
)
_LEASE_KEYS = ("rent_roll", "all_leases", "lease_amendments")
_ESTOPPEL_KEYS = ("estoppels", "farm_tenant_estoppels")


def _as_date(value: Any, *, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} cannot be blank")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _add_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _db_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> Path:
    if isinstance(db_path, CreConfig):
        return Path(db_path.cache_db_path).expanduser()
    if db_path is not None:
        return Path(db_path).expanduser()
    return Path((config or CreConfig()).cache_db_path).expanduser()


def _data_room_snapshot(
    deal_id: str,
    deal_type: str,
    *,
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> dict[str, Any]:
    """Read existing data-room rows without invoking its mutating public scorer."""

    path = _db_path(db_path, config)
    base = {
        "initialized": False,
        "deal_type": None,
        "stored_score": None,
        "sale_scope_score": None,
        "items": {},
        "source": "read-only SQLite inspection of existing dataroom tables",
        "database_path": str(path),
    }
    if not path.is_file():
        return {**base, "note": "Data room not initialized: cache database does not exist."}
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            table_names = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('completeness_index', 'dataroom_items')"
                )
            }
            if table_names != {"completeness_index", "dataroom_items"}:
                return {**base, "note": "Data room not initialized: owned tables are absent."}
            metadata = connection.execute(
                "SELECT deal_type, score, current_phase, as_of FROM completeness_index WHERE deal_id=?",
                (deal_id,),
            ).fetchone()
            if metadata is None:
                return {**base, "note": "Data room not initialized for this deal."}
            rows = connection.execute(
                "SELECT doc_key, status, due_date, notes, updated_at "
                "FROM dataroom_items WHERE deal_id=?",
                (deal_id,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {
            **base,
            "note": f"Data-room readiness is unknown because read-only inspection failed: {exc}",
        }

    items = {str(row["doc_key"]): dict(row) for row in rows}
    taxonomy = get_taxonomy(deal_type)
    earned = 0.0
    possible = 0.0
    for requirement in taxonomy:
        row = items.get(requirement["doc_key"])
        status = str(row["status"]) if row is not None else "missing"
        # Conditional rows become sale-scope requirements only when activated.
        if not requirement["required"] and status == "missing":
            continue
        weight = PHASE_WEIGHTS[requirement["phase"]]
        possible += weight
        earned += weight * STATUS_CREDITS.get(status, 0.0)
    sale_score = round(100.0 * earned / possible, 2) if possible else None
    mismatch = str(metadata["deal_type"]).casefold() != deal_type.casefold()
    return {
        **base,
        "initialized": True,
        "deal_type": metadata["deal_type"],
        "stored_score": metadata["score"],
        "stored_current_phase": metadata["current_phase"],
        "stored_as_of": metadata["as_of"],
        "sale_scope_score": sale_score,
        "items": items,
        "taxonomy_mismatch": mismatch,
        "note": (
            "Existing rows scored read-only across all sale phases; this does not prove "
            "document freshness, completeness of a set, accuracy, or legal sufficiency."
        ),
    }


def _dimension(status: str, evidence: list[str], gaps: list[str]) -> dict[str, Any]:
    return {"status": status, "evidence": evidence, "gaps": gaps}


def _fix(
    fix_id: str,
    dimension: str,
    action: str,
    why: str,
    days: int,
    severity: str,
) -> dict[str, Any]:
    unit = "months" if days >= 60 else "weeks" if days >= 14 else "days"
    amount = round(days / 30.44, 1) if unit == "months" else round(days / 7, 1) if unit == "weeks" else days
    return {
        "fix_id": fix_id,
        "dimension": dimension,
        "action": action,
        "why": why,
        "lead_time_days": days,
        "lead_time_label": f"approximately {amount:g} {unit}",
        "severity": severity,
    }


def _status_from_docs(statuses: list[str]) -> str:
    if not statuses:
        return "unknown"
    if any(status in {"missing", "requested", "issue_found"} for status in statuses):
        return "blocked"
    if any(status == "received" for status in statuses):
        return "attention"
    return "ready"


def _tax_screen_has_computable_output(screen: Mapping[str, Any]) -> bool:
    """Require a registered posture and at least one numeric taxecon range value."""

    if str(screen.get("status", "")).strip().upper() == "UNKNOWN":
        return False
    for key in ("projected_assessed_value", "projected_annual_taxes", "annual_noi_delta"):
        output = screen.get(key)
        if isinstance(output, Mapping) and any(
            isinstance(output.get(point), (int, float))
            and not isinstance(output.get(point), bool)
            for point in ("low", "base", "high")
        ):
            return True
    return False


def _event_rows(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    supplied = inputs.get("lease_events")
    if isinstance(supplied, Mapping):
        supplied = supplied.get("dates", supplied.get("events", []))
    rows: list[dict[str, Any]] = []
    for item in _sequence(supplied):
        if isinstance(item, Mapping):
            rows.append(dict(item))
    for item in _sequence(inputs.get("lease_expirations")):
        if isinstance(item, Mapping):
            rows.append({"event": "lease_expiration", **dict(item)})
        else:
            rows.append({"event": "lease_expiration", "date": item})
    for item in _sequence(inputs.get("lease_options")):
        if isinstance(item, Mapping):
            row = dict(item)
            row.setdefault("event", row.get("option_type", "option_notice_deadline"))
            rows.append(row)
    return rows


def disposition_readiness(
    deal_id: str,
    deal_type: str,
    target_sale_date: Any,
    audit_inputs: Mapping[str, Any] | None = None,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Audit six sale-readiness dimensions using an explicitly disclosed rubric.

    ``audit_inputs`` is optional because missing evidence must remain visible.  It
    may contain ``financial_records_complete``, ``estoppels_current``,
    ``lease_events`` (the result or event list from
    :func:`cre_mcp.leases.critical_dates`), ``lease_expirations``,
    ``lease_options``, ``title_age_months``, ``survey_age_months``,
    ``open_work_orders``, ``capex_flags``, and the taxecon inputs ``state``,
    ``county``, ``expected_sale_price``, ``current_assessed_value``, and
    ``current_annual_taxes``.
    """

    normalized_id = str(deal_id).strip()
    if not normalized_id:
        raise ValueError("deal_id cannot be blank")
    normalized_type = str(deal_type).strip().casefold()
    taxonomy = get_taxonomy(normalized_type)  # validates before any DB access
    sale_date = _as_date(target_sale_date, label="target_sale_date")
    audit_date = _as_date(as_of, label="as_of") if as_of is not None else date.today()
    inputs = dict(audit_inputs or {})
    if sale_date < audit_date:
        timeline_note = "Target sale date is in the past; replace it before relying on the runway."
    else:
        timeline_note = None

    snapshot = _data_room_snapshot(
        normalized_id,
        normalized_type,
        db_path=db_path,
        config=config,
    )
    items: dict[str, dict[str, Any]] = snapshot["items"]
    fixes: list[dict[str, Any]] = []

    # Financial records.
    financial_evidence: list[str] = []
    financial_gaps: list[str] = []
    explicit_financial = inputs.get("financial_records_complete")
    applicable_financial = [key for key in _FINANCIAL_KEYS if any(row["doc_key"] == key for row in taxonomy)]
    if isinstance(explicit_financial, bool):
        financial_status = "ready" if explicit_financial else "blocked"
        financial_evidence.append(f"financial_records_complete explicitly supplied as {explicit_financial}")
        if not explicit_financial:
            financial_gaps.append("Financial records are explicitly incomplete.")
    elif snapshot["initialized"]:
        financial_rows = [items[key] for key in applicable_financial if key in items]
        financial_status = _status_from_docs([str(row["status"]) for row in financial_rows])
        financial_evidence.extend(
            f"data-room {key}={items[key]['status']}" for key in applicable_financial if key in items
        )
        missing_keys = [key for key in applicable_financial if key not in items]
        financial_gaps.extend(f"No data-room row for {key}." for key in missing_keys)
        if missing_keys and financial_status == "ready":
            financial_status = "attention"
    else:
        financial_status = "unknown"
        financial_gaps.append("Financial completeness was not supplied and the data room is not initialized.")
    if financial_status != "ready":
        fixes.append(_fix(
            "financial_cleanup",
            "financial_records",
            "Reconcile certified rent roll, T-12, three-year operating history, tenant ledgers, and tax bills.",
            "Buyers need a traceable bridge from leases and ledgers to marketed NOI.",
            45,
            "blocking" if financial_status == "blocked" else "evidence_gap",
        ))
    dimensions: dict[str, dict[str, Any]] = {
        "financial_records": _dimension(financial_status, financial_evidence, financial_gaps)
    }

    # Lease file, estoppels, options, and expirations.
    lease_required_keys = [key for key in _LEASE_KEYS if any(row["doc_key"] == key for row in taxonomy)]
    lease_evidence: list[str] = []
    lease_gaps: list[str] = []
    if not lease_required_keys:
        lease_status = "not_applicable"
        lease_evidence.append("Selected dataroom taxonomy has no income-property lease-file requirements.")
    else:
        lease_rows = [items[key] for key in lease_required_keys if key in items]
        lease_status = _status_from_docs([str(row["status"]) for row in lease_rows]) if snapshot["initialized"] else "unknown"
        lease_evidence.extend(
            f"data-room {key}={items[key]['status']}" for key in lease_required_keys if key in items
        )
        if snapshot["initialized"] and len(lease_rows) < len(lease_required_keys):
            lease_status = "blocked"
            lease_gaps.append("One or more required lease-file taxonomy rows are absent.")
        estoppels_current = inputs.get("estoppels_current")
        if isinstance(estoppels_current, bool):
            lease_evidence.append(f"estoppels_current explicitly supplied as {estoppels_current}")
            if not estoppels_current:
                lease_status = "blocked"
                lease_gaps.append("Tenant estoppels are not current.")
        else:
            estoppel_row = next((items[key] for key in _ESTOPPEL_KEYS if key in items), None)
            if estoppel_row is not None:
                lease_evidence.append(f"data-room estoppel status={estoppel_row['status']}")
            lease_gaps.append("Estoppel freshness was not supplied; a received/reviewed row does not prove current tenant coverage.")
            if lease_status == "ready":
                lease_status = "attention"
        events = _event_rows(inputs)
        window_start, window_end = _add_months(sale_date, -6), _add_months(sale_date, 12)
        in_window: list[dict[str, Any]] = []
        for event in events:
            try:
                event_date = _as_date(event.get("date"), label="lease event date")
            except ValueError:
                lease_gaps.append(f"Unparseable lease event date: {event.get('date')!r}.")
                continue
            event_name = str(event.get("event", "")).casefold()
            if window_start <= event_date <= window_end and (
                "expiration" in event_name or "option" in event_name or "notice" in event_name
            ):
                in_window.append({**event, "date": event_date.isoformat()})
        if events:
            lease_evidence.append(f"{len(events)} lease critical-date events supplied; {len(in_window)} fall in sale window")
        else:
            lease_gaps.append("Lease option/expiration critical-date output was not supplied.")
            if lease_status == "ready":
                lease_status = "attention"
        if in_window:
            lease_status = "attention" if lease_status != "blocked" else lease_status
            lease_gaps.append("Lease expirations/options in the sale window require buyer-facing strategy and disclosure.")
        dimensions["lease_file"] = {
            **_dimension(lease_status, lease_evidence, lease_gaps),
            "sale_window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "events_in_sale_window": in_window,
            "lease_vocabulary_cross_link": "cre_mcp.leases.LeaseAbstract.dates.expiration/options and critical_dates()",
        }
        if inputs.get("estoppels_current") is not True:
            fixes.append(_fix(
                "current_estoppels",
                "lease_file",
                "Order and chase current tenant estoppels; reconcile facts against leases and amendments.",
                "Tenant response cycles and discrepancy cures commonly take weeks.",
                30,
                "blocking" if inputs.get("estoppels_current") is False else "evidence_gap",
            ))
        if not events:
            fixes.append(_fix(
                "lease_critical_dates",
                "lease_file",
                "Run the lease critical-dates audit and flag expirations, option windows, and notices around sale.",
                "Unmodeled lease events can alter buyer underwriting and closing conditions.",
                10,
                "evidence_gap",
            ))

    # Title and survey freshness.
    title_age = _number(inputs.get("title_age_months", inputs.get("title_report_age_months")))
    survey_age = _number(inputs.get("survey_age_months"))
    title_evidence: list[str] = []
    title_gaps: list[str] = []
    title_statuses: list[str] = []
    for label, age, ready_age, attention_age in (
        ("title", title_age, 6.0, 12.0),
        ("survey", survey_age, 12.0, 24.0),
    ):
        if age is None:
            title_statuses.append("unknown")
            title_gaps.append(f"{label.title()} age was not supplied.")
        elif age < 0:
            raise ValueError(f"{label}_age_months must be non-negative")
        else:
            title_evidence.append(f"{label}_age_months={age:g}")
            title_statuses.append("ready" if age <= ready_age else "attention" if age <= attention_age else "blocked")
    if "blocked" in title_statuses:
        title_status = "blocked"
    elif "attention" in title_statuses or "unknown" in title_statuses:
        title_status = "attention" if any(value is not None for value in (title_age, survey_age)) else "unknown"
    else:
        title_status = "ready"
    if survey_age is None or survey_age > 12:
        fixes.append(_fix(
            "survey_update",
            "title_survey",
            "Engage a licensed surveyor for a buyer/title/lender-acceptable ALTA/NSPS update and exceptions overlay.",
            "Survey fieldwork, records, revisions, and certifications can take months.",
            90,
            "blocking" if survey_age is not None and survey_age > 24 else "evidence_gap",
        ))
    if title_age is None or title_age > 6:
        fixes.append(_fix(
            "title_update",
            "title_survey",
            "Order an updated title commitment and underlying exception documents; start cure work.",
            "Liens and exception cures need runway before bidders rely on title.",
            30,
            "blocking" if title_age is not None and title_age > 12 else "evidence_gap",
        ))
    dimensions["title_survey"] = _dimension(title_status, title_evidence, title_gaps)

    # Physical condition.
    work_orders_supplied = "open_work_orders" in inputs
    capex_supplied = "capex_flags" in inputs
    work_orders = _sequence(inputs.get("open_work_orders")) if work_orders_supplied else []
    if work_orders_supplied and isinstance(inputs.get("open_work_orders"), int):
        count = int(inputs["open_work_orders"])
        if count < 0:
            raise ValueError("open_work_orders cannot be negative")
        work_orders = ["unspecified open work order"] * count
    capex_flags = _sequence(inputs.get("capex_flags")) if capex_supplied else []
    physical_evidence: list[str] = []
    physical_gaps: list[str] = []
    if work_orders_supplied:
        physical_evidence.append(f"open_work_orders_count={len(work_orders)}")
    else:
        physical_gaps.append("Open work orders were not supplied.")
    if capex_supplied:
        physical_evidence.append(f"capex_flags_count={len(capex_flags)}")
    else:
        physical_gaps.append("Capex flags were not supplied.")
    if work_orders or capex_flags:
        physical_status = "blocked" if any(
            isinstance(item, Mapping) and str(item.get("severity", "")).casefold() in {"critical", "blocking", "life_safety"}
            for item in [*work_orders, *capex_flags]
        ) else "attention"
        physical_gaps.append("Open physical/capex items need scope, budget, disclosure, and repair-vs-credit decisions.")
        fixes.append(_fix(
            "physical_capex_plan",
            "physical",
            "Triage open work orders and capex flags; document scope, bids, timing, and repair-versus-credit decision.",
            "Unbounded physical issues invite retrades and may require long-lead repair work.",
            120 if physical_status == "blocked" else 60,
            "blocking" if physical_status == "blocked" else "attention",
        ))
    elif work_orders_supplied and capex_supplied:
        physical_status = "ready"
    else:
        physical_status = "unknown"
        fixes.append(_fix(
            "physical_evidence",
            "physical",
            "Collect the open-work-order log, current PCA/capex plan, and life-safety status.",
            "No physical readiness conclusion is possible without current operational inputs.",
            10,
            "evidence_gap",
        ))
    dimensions["physical"] = {
        **_dimension(physical_status, physical_evidence, physical_gaps),
        "open_work_orders": work_orders,
        "capex_flags": capex_flags,
    }

    # Property-tax reassessment screen, delegated to taxecon.
    tax_evidence: list[str] = []
    tax_gaps: list[str] = []
    state = str(inputs.get("state", "")).strip().upper()
    if state:
        tax_screen = estimate_reassessment(
            inputs.get("expected_sale_price", inputs.get("sale_price")),
            inputs.get("current_assessed_value"),
            inputs.get("current_annual_taxes"),
            state,
            inputs.get("county"),
        )
        tax_evidence.append(f"taxecon reassessment status={tax_screen.get('status')}")
        if _tax_screen_has_computable_output(tax_screen):
            tax_status = "attention"
            tax_note = (
                "Buyer-side post-sale reassessment can reduce underwritten NOI and price; "
                "screen supplied from cre_mcp.taxecon.estimate_reassessment without reimplementing tax logic."
            )
        else:
            tax_status = "unknown"
            tax_note = (
                "Taxecon did not return a computable registered-jurisdiction range, so "
                "reassessment exposure remains an evidence gap rather than counted coverage."
            )
            tax_gaps.append(
                f"Taxecon status={tax_screen.get('status')!r} produced no computable tax range; "
                "supply parcel facts and verify the jurisdiction-specific rule."
            )
    else:
        tax_screen = None
        tax_status = "unknown"
        tax_note = "State was not supplied, so taxecon reassessment exposure was not estimated."
        tax_gaps.append("Supply property state and parcel tax facts for the reassessment screen.")
    dimensions["tax"] = {
        **_dimension(tax_status, tax_evidence, tax_gaps),
        "reassessment_exposure_note": tax_note,
        "taxecon_screen": tax_screen,
        "professional_review_required": True,
        "professional_review_flag": "Verify parcel reassessment, assessment, and transfer treatment with the county assessor, CPA, and tax counsel.",
    }
    if tax_status == "unknown":
        fixes.append(_fix(
            "tax_reassessment_screen",
            "tax",
            "Supply parcel tax facts and run the taxecon reassessment screen; obtain local verification where material.",
            "Unquantified buyer tax exposure can reduce bids or drive a late retrade.",
            14,
            "evidence_gap",
        ))

    # Data-room workflow completeness remains distinct from its content dimensions.
    if not snapshot["initialized"]:
        data_room_status = "unknown"
        data_room_gaps = [str(snapshot["note"])]
    elif snapshot.get("taxonomy_mismatch"):
        data_room_status = "blocked"
        data_room_gaps = ["Initialized data-room deal_type does not match the requested disposition taxonomy."]
    else:
        sale_score = snapshot.get("sale_scope_score")
        data_room_status = "unknown" if sale_score is None else "ready" if sale_score >= 85 else "attention" if sale_score >= 60 else "blocked"
        data_room_gaps = [] if data_room_status == "ready" else ["Resolve missing, requested, received-only, and issue-found sale-scope rows."]
    dimensions["data_room"] = {
        **_dimension(
            data_room_status,
            [snapshot["note"]],
            data_room_gaps,
        ),
        "initialized": snapshot["initialized"],
        "stored_phase_gated_score": snapshot.get("stored_score"),
        "read_only_sale_scope_score": snapshot.get("sale_scope_score"),
        "source": snapshot["source"],
    }
    if data_room_status != "ready":
        fixes.append(_fix(
            "data_room_sale_scope",
            "data_room",
            "Initialize if authorized, then assign and resolve sale-scope data-room gaps through reviewed status.",
            "The readiness audit itself intentionally never initializes or writes the data room.",
            45,
            "blocking" if data_room_status == "blocked" else "evidence_gap",
        ))

    # Score and schedule conventions are intentionally mechanical and exposed.
    readiness_score = 0.0
    evidence_coverage = 0.0
    active_weight = sum(
        weight
        for key, weight in DIMENSION_WEIGHTS.items()
        if dimensions[key]["status"] != "not_applicable"
    )
    for key, weight in DIMENSION_WEIGHTS.items():
        status = dimensions[key]["status"]
        credit = STATUS_CREDIT[status]
        if credit is not None:
            readiness_score += weight * credit
            evidence_coverage += weight
    scale = 100.0 / active_weight if active_weight else 0.0
    readiness_score = round(readiness_score * scale, 1)
    evidence_coverage = round(evidence_coverage * scale, 1)
    statuses = [row["status"] for row in dimensions.values() if row["status"] != "not_applicable"]
    overall_status = "blocked" if "blocked" in statuses else "attention" if any(status in {"attention", "unknown"} for status in statuses) else "ready"

    fixes.sort(key=lambda row: (-int(row["lead_time_days"]), row["dimension"], row["fix_id"]))
    longest_days = max((int(row["lead_time_days"]) for row in fixes), default=0)
    base_months = round(longest_days / 30.44, 1)
    months_to_ready = {
        "estimate": base_months,
        "range": {
            "low": round(longest_days * 0.75 / 30.44, 1),
            "base": base_months,
            "high": round(longest_days * 1.5 / 30.44, 1),
        },
        "longest_lead_time_days": longest_days,
        "convention": (
            "Calendar-month planning range based on the single longest listed fix, "
            "assuming fixes run in parallel; low=75% and high=150% of conventional "
            "lead time. It is not a contractor, tenant, title, surveyor, or counsel commitment."
        ),
    }
    days_available = (sale_date - audit_date).days
    runway = {
        "days_to_target_sale": days_available,
        "estimated_days_needed": longest_days,
        "status": "past_due" if days_available < 0 else "insufficient" if days_available < longest_days else "within_convention",
        "note": timeline_note,
    }

    return {
        "deal_id": normalized_id,
        "deal_type": normalized_type,
        "target_sale_date": sale_date.isoformat(),
        "as_of": audit_date.isoformat(),
        "status": overall_status,
        "readiness_score_pct": readiness_score,
        "score": readiness_score,
        "evidence_coverage_pct": evidence_coverage,
        "dimensions": dimensions,
        "fixes": fixes,
        "months_to_ready": months_to_ready,
        "target_runway": runway,
        "rubric": READINESS_RUBRIC,
        "conventions": [
            "Unknown is an evidence gap, never inferred complete.",
            "Readiness score is a planning rubric, not a probability of closing or valuation opinion.",
            "Data-room reads do not prove freshness, execution, tenant coverage, accuracy, or legal sufficiency.",
            "Estoppels conventionally take weeks; new or updated surveys conventionally take months.",
        ],
        "limitations": [
            "Physical readiness depends on user-supplied work-order and capex inputs.",
            "Lease event analysis depends on supplied LeaseAbstract/critical_dates-derived events.",
            "Tax reassessment is a screening note; parcel rules and buyer underwriting can differ.",
            "This audit does not provide legal, tax, securities, engineering, title, survey, or accounting advice.",
        ],
        "professional_review_flags": [
            "CRE counsel should review estoppel, lease, title, survey, disclosure, and sale-process requirements.",
            "CPA/tax counsel and the county assessor should verify reassessment and seller tax treatment.",
            "Licensed physical and survey professionals should scope unresolved property and survey work.",
        ],
    }


__all__ = [
    "DIMENSION_WEIGHTS",
    "READINESS_RUBRIC",
    "STATUS_CREDIT",
    "disposition_readiness",
]
