"""Exception-only portfolio watchlist for judgment-requiring events."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from cre_mcp.books import BookStore


DEFAULT_HORIZONS_DAYS = {
    "lease_rollover": 365,
    "loan_maturity": 365,
    "insurance_renewal": 90,
}

_ASSET_INPUT_KEYS = frozenset(
    {
        "asset",
        "deal_id",
        "name",
        "id",
        "leases",
        "lease",
        "lease_rollovers",
        "lease_rollover",
        "rollover_dates",
        "rollover_date",
        "loan_maturities",
        "loan_maturity",
        "insurance_renewals",
        "insurance_renewal",
        "tax_reassessment_flags",
        "tax_reassessment_flag",
        "tax_reassessment",
        "capex_urgents",
        "urgent_capex",
        "capex_urgent",
        "tenant_credit_signals",
        "tenant_credit_signal",
        "credit_signals",
        "collections",
        "collections_rate",
        "collections_period",
        "collections_exception_below",
    }
)
_EVENT_LABEL_KEYS = frozenset({"tenant", "loan", "carrier", "name"})
_LEASE_EVENT_KEYS = frozenset(
    {"rollover_date", "expiration", "expiration_date", "end_date", "date"}
) | _EVENT_LABEL_KEYS
_LOAN_EVENT_KEYS = frozenset({"maturity_date", "maturity", "date"}) | _EVENT_LABEL_KEYS
_INSURANCE_EVENT_KEYS = frozenset(
    {"renewal_date", "expiration", "date"}
) | _EVENT_LABEL_KEYS
_FLAG_KEYS = frozenset({"status", "flag", "reason", "detail", "signal", "tenant"})
_CAPEX_KEYS = frozenset({"urgent", "urgency", "item", "name"})
_COLLECTIONS_KEYS = frozenset(
    {
        "billed_cents",
        "scheduled_cents",
        "collected_cents",
        "rate",
        "collections_rate",
    }
)


def _audit_mapping(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    path: str,
) -> list[str]:
    unknown: list[str] = []
    for raw_key in value:
        key = str(raw_key)
        if isinstance(raw_key, str) and raw_key in allowed:
            continue
        input_path = f"{path}.{key}"
        unknown.append(input_path)
    return unknown


def _audit_nested_mappings(
    value: Any,
    allowed: frozenset[str],
    *,
    path: str,
) -> list[str]:
    if isinstance(value, Mapping):
        return _audit_mapping(
            value,
            allowed,
            path=path,
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        unknown: list[str] = []
        for item_index, item in enumerate(value):
            unknown.extend(
                _audit_nested_mappings(
                    item,
                    allowed,
                    path=f"{path}[{item_index}]",
                )
            )
        return unknown
    return []


def _audit_asset(asset: Mapping[str, Any], index: int) -> list[str]:
    base = f"portfolio[{index}]"
    unknown = _audit_mapping(
        asset,
        _ASSET_INPUT_KEYS,
        path=base,
    )
    nested_specs = (
        (
            ("leases", "lease", "lease_rollovers", "lease_rollover", "rollover_dates", "rollover_date"),
            _LEASE_EVENT_KEYS,
        ),
        (
            ("loan_maturities", "loan_maturity"),
            _LOAN_EVENT_KEYS,
        ),
        (
            ("insurance_renewals", "insurance_renewal"),
            _INSURANCE_EVENT_KEYS,
        ),
        (
            ("tax_reassessment_flags", "tax_reassessment_flag", "tax_reassessment"),
            _FLAG_KEYS,
        ),
        (
            ("capex_urgents", "urgent_capex", "capex_urgent"),
            _CAPEX_KEYS,
        ),
        (
            ("tenant_credit_signals", "tenant_credit_signal", "credit_signals"),
            _FLAG_KEYS,
        ),
        (
            ("collections", "collections_rate"),
            _COLLECTIONS_KEYS,
        ),
    )
    for aliases, allowed in nested_specs:
        for key in aliases:
            if key in asset and asset[key] is not None:
                unknown.extend(
                    _audit_nested_mappings(
                        asset[key],
                        allowed,
                        path=f"{base}.{key}",
                    )
                )
    return unknown


def _as_date(value: Any, *, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _asset_name(asset: Mapping[str, Any], index: int) -> str:
    value = (
        asset.get("asset")
        or asset.get("deal_id")
        or asset.get("name")
        or asset.get("id")
    )
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"portfolio[{index}] needs asset, deal_id, name, or id")
    return normalized


def _event_values(asset: Mapping[str, Any], plural: str, singular: str) -> list[Any]:
    value = asset.get(plural)
    if value is None:
        value = asset.get(singular)
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
        return list(value)
    return [value]


def _event_date(value: Any, keys: Sequence[str], *, name: str) -> tuple[date, str]:
    if isinstance(value, Mapping):
        raw = None
        for key in keys:
            if value.get(key) is not None:
                raw = value[key]
                break
        if raw is None:
            raise ValueError(f"{name} event needs one of: {', '.join(keys)}")
        label = str(
            value.get("tenant")
            or value.get("loan")
            or value.get("carrier")
            or value.get("name")
            or "event"
        )
        return _as_date(raw, name=name), label
    return _as_date(value, name=name), "event"


def _add_dated(
    items: list[dict[str, Any]],
    *,
    asset: str,
    category: str,
    event_date: date,
    label: str,
    as_of: date,
    horizon: int,
) -> None:
    days = (event_date - as_of).days
    if days > horizon:
        return
    if days < 0:
        timing = f"{abs(days)} days overdue"
    else:
        timing = f"due in {days} days"
    items.append(
        {
            "asset": asset,
            "category": category,
            "days_to_event": days,
            "why_it_needs_judgment": (
                f"{label} is {timing}; confirm economics, responsibility, and action owner."
            ),
        }
    )


def _truthy_flags(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if value is True:
        return ["flag supplied"]
    if isinstance(value, Mapping):
        status = str(value.get("status") or "").strip().casefold()
        if value.get("flag") is False or status in {
            "clear",
            "resolved",
            "ok",
            "stable",
            "current",
            "positive",
            "good",
            "paid",
        }:
            return []
        detail = (
            value.get("reason")
            or value.get("detail")
            or value.get("signal")
            or value.get("status")
            or value.get("tenant")
        )
        return [str(detail or "flag supplied")]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        details: list[str] = []
        for item in value:
            details.extend(_truthy_flags(item))
        return details
    normalized = str(value).strip()
    if not normalized or normalized.casefold() in {"none", "clear", "resolved", "ok", "stable"}:
        return []
    return [normalized]


def _urgent_capex(value: Any) -> list[tuple[str, float]]:
    results: list[tuple[str, float]] = []
    for item in _event_values({"items": value}, "items", "item"):
        if isinstance(item, Mapping):
            urgent = item.get("urgent")
            raw_urgency = item.get("urgency", 0)
            levels = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}
            if isinstance(raw_urgency, str):
                score = levels.get(raw_urgency.strip().casefold(), 0.0)
            elif isinstance(raw_urgency, bool):
                score = 4.0 if raw_urgency else 0.0
            else:
                try:
                    score = float(raw_urgency)
                except (TypeError, ValueError):
                    score = 0.0
            if urgent is True or score >= 3:
                results.append((str(item.get("item") or item.get("name") or "urgent CapEx"), score or 4.0))
        elif item:
            results.append((str(item), 3.0))
    return results


def _structured_collections(asset: Mapping[str, Any]) -> tuple[float | None, str | None]:
    value = asset.get("collections")
    if value is None:
        value = asset.get("collections_rate")
    if value is None:
        return None, None
    if isinstance(value, Mapping):
        billed = value.get("billed_cents", value.get("scheduled_cents"))
        collected = value.get("collected_cents")
        if billed is not None and collected is not None:
            if isinstance(billed, bool) or not isinstance(billed, int):
                raise ValueError("collections.billed_cents must be integer cents")
            if isinstance(collected, bool) or not isinstance(collected, int):
                raise ValueError("collections.collected_cents must be integer cents")
            rate = collected / billed if billed > 0 else None
            return rate, f"{collected} collected cents / {billed} billed cents"
        value = value.get("rate", value.get("collections_rate"))
    if value is None:
        return None, None
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("collections rate must be numeric") from exc
    if rate > 1:
        rate /= 100
    return rate, f"caller-supplied collections rate {rate:.2%}"


def _books_collections(
    deal_id: str,
    period: str,
    db_path: str | Path | None,
) -> tuple[float | None, str | None]:
    books = BookStore(db_path)
    tenancy_ids = {
        str(row["tenancy_id"])
        for row in books.list_tenancies()
        if str(row.get("deal_id")) == deal_id
    }
    charges = [
        row
        for row in books.list_charges(period=period)
        if str(row["tenancy_id"]) in tenancy_ids
    ]
    billed = sum(int(row["amount_cents"]) for row in charges)
    charge_ids = {str(row["charge_id"]) for row in charges}
    collected = 0
    for receipt in books.list_receipts(status="matched"):
        matched = {str(value) for value in receipt.get("matched_charge_ids", [])}
        if matched and matched.issubset(charge_ids):
            collected += int(receipt["amount_cents"])
    if billed <= 0:
        return None, f"books period {period} has no billed cents for deal"
    return collected / billed, f"books: {collected} matched collected cents / {billed} billed cents in {period}"


def portfolio_watchlist(
    portfolio: Sequence[Mapping[str, Any]],
    as_of: date | datetime | str | None = None,
    horizons_days: Mapping[str, int] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return only exceptions; assets without an exception are deliberately absent."""

    if isinstance(portfolio, (str, bytes)) or not isinstance(portfolio, Sequence):
        raise ValueError("portfolio must be a sequence of asset mappings")
    point = date.today() if as_of is None else _as_date(as_of, name="as_of")
    horizons = dict(DEFAULT_HORIZONS_DAYS)
    for key, value in (horizons_days or {}).items():
        if key not in horizons:
            raise ValueError(f"unknown horizon category {key!r}")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"horizons_days.{key} must be a non-negative integer")
        horizons[key] = value

    exceptions: list[dict[str, Any]] = []
    unrecognized_inputs: list[str] = []
    asset_count = 0
    for index, asset in enumerate(portfolio):
        if not isinstance(asset, Mapping):
            raise ValueError(f"portfolio[{index}] must be a mapping")
        unrecognized_inputs.extend(_audit_asset(asset, index))
        asset_count += 1
        name = _asset_name(asset, index)
        lease_events = _event_values(asset, "leases", "lease")
        lease_events += _event_values(asset, "lease_rollovers", "lease_rollover")
        lease_events += _event_values(asset, "rollover_dates", "rollover_date")
        for event in lease_events:
            event_date, label = _event_date(
                event,
                ("rollover_date", "expiration", "expiration_date", "end_date", "date"),
                name=f"portfolio[{index}].lease",
            )
            _add_dated(
                exceptions,
                asset=name,
                category="lease_rollover",
                event_date=event_date,
                label=label,
                as_of=point,
                horizon=horizons["lease_rollover"],
            )
        for event in _event_values(asset, "loan_maturities", "loan_maturity"):
            event_date, label = _event_date(
                event,
                ("maturity_date", "maturity", "date"),
                name=f"portfolio[{index}].loan_maturity",
            )
            _add_dated(
                exceptions,
                asset=name,
                category="loan_maturity",
                event_date=event_date,
                label=label,
                as_of=point,
                horizon=horizons["loan_maturity"],
            )
        for event in _event_values(asset, "insurance_renewals", "insurance_renewal"):
            event_date, label = _event_date(
                event,
                ("renewal_date", "expiration", "date"),
                name=f"portfolio[{index}].insurance_renewal",
            )
            _add_dated(
                exceptions,
                asset=name,
                category="insurance_renewal",
                event_date=event_date,
                label=label,
                as_of=point,
                horizon=horizons["insurance_renewal"],
            )

        tax_value = asset.get(
            "tax_reassessment_flags",
            asset.get("tax_reassessment_flag", asset.get("tax_reassessment")),
        )
        for detail in _truthy_flags(tax_value):
            exceptions.append(
                {
                    "asset": name,
                    "category": "tax_reassessment",
                    "severity": "high",
                    "why_it_needs_judgment": (
                        f"Tax reassessment exception: {detail}; quantify timing, appeal rights, and NOI impact."
                    ),
                }
            )
        for item, score in _urgent_capex(
            asset.get(
                "capex_urgents",
                asset.get("urgent_capex", asset.get("capex_urgent")),
            )
        ):
            severity = "critical" if score >= 4 else "high"
            exceptions.append(
                {
                    "asset": name,
                    "category": "urgent_capex",
                    "severity": severity,
                    "why_it_needs_judgment": (
                        f"{item} is marked urgent (urgency score {score:g}); confirm scope, safety exposure, cost, and owner."
                    ),
                }
            )
        credit_value = asset.get(
            "tenant_credit_signals",
            asset.get("tenant_credit_signal", asset.get("credit_signals")),
        )
        for detail in _truthy_flags(credit_value):
            exceptions.append(
                {
                    "asset": name,
                    "category": "tenant_credit",
                    "severity": "high",
                    "why_it_needs_judgment": (
                        f"Tenant credit signal: {detail}; validate evidence and decide leasing/collections response."
                    ),
                }
            )

        collections_rate, collections_basis = _structured_collections(asset)
        if collections_rate is None and asset.get("collections_period") is not None:
            deal_id = str(asset.get("deal_id") or "").strip()
            if not deal_id:
                raise ValueError(
                    f"portfolio[{index}] needs deal_id to read collections from books"
                )
            collections_rate, collections_basis = _books_collections(
                deal_id,
                str(asset["collections_period"]),
                db_path,
            )
        threshold_value = asset.get("collections_exception_below", 0.90)
        try:
            threshold = float(threshold_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("collections_exception_below must be numeric") from exc
        if threshold > 1:
            threshold /= 100
        if collections_rate is not None and collections_rate < threshold:
            exceptions.append(
                {
                    "asset": name,
                    "category": "collections",
                    "severity": "high" if collections_rate < 0.75 else "medium",
                    "why_it_needs_judgment": (
                        f"Collections are {collections_rate:.2%}, below the {threshold:.2%} convention; "
                        f"basis: {collections_basis}. Determine tenant-specific cause and action."
                    ),
                }
            )

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def urgency_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        if "days_to_event" in item:
            days = int(item["days_to_event"])
            tier = 0 if days <= 30 else 1 if days <= 90 else 2 if days <= 180 else 3
            within_tier = days
        else:
            tier = severity_rank.get(str(item.get("severity")), 3)
            within_tier = 10**9
        return (tier, within_tier, str(item["asset"]), str(item["category"]))

    exceptions.sort(
        key=urgency_key
    )
    quiet_count = asset_count - len({str(item["asset"]) for item in exceptions})
    result = {
        "as_of": point.isoformat(),
        "exceptions": exceptions,
        "items": exceptions,
        "exception_count": len(exceptions),
        "quiet_asset_count": quiet_count,
        "conventions": {
            "horizons_days": horizons,
            "collections_exception_below": (
                "90% unless an asset supplies collections_exception_below"
            ),
            "urgent_capex": "urgent=true or urgency high/critical (numeric score >= 3)",
            "urgency_sort": (
                "Overdue/due within 30 days and critical severity are tier 1; "
                "31-90 days and high severity tier 2; 91-180 days and medium "
                "severity tier 3; later dates and low severity tier 4. Dates "
                "sort ascending within a tier."
            ),
            "output_rule": "exceptions only; assets without an exception are omitted",
        },
        "honest_gaps": [
            "Credit, tax, insurance, and CapEx signals are alerts for judgment, not verified conclusions.",
            "Books collections count only fully matched receipts whose charge set belongs to the selected deal and period.",
        ],
    }
    if unrecognized_inputs:
        result["unrecognized_inputs"] = sorted(set(unrecognized_inputs))
    return result


__all__ = ["DEFAULT_HORIZONS_DAYS", "portfolio_watchlist"]
