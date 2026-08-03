"""Forecast-versus-actual initiative tracking with penny-exact deltas.

Property books are consumed read-only.  Because the current books contain
tenant billings and cash rather than initiative-tagged CapEx, a books-derived
NOI actual is used only when the initiative baseline explicitly declares a
metric, comparison baseline, and period.  Costs are never invented from rent
charges.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from cre_mcp.books import BookStore, rent_to_cash
from cre_mcp.books.billing import iter_periods, validate_period
from cre_mcp.config import CreConfig

from .plan import InitiativeStore

BOOK_METRICS = frozenset(
    {"scheduled_cents", "billed_cents", "collected_cents", "outstanding_cents"}
)


def _required_text(value: Any, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _optional_cents(value: Any, name: str, *, non_negative: bool) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents when provided")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_or_zero_months(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer when provided")
    return value


def _as_date(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("as_of must be an ISO date when provided") from exc


def _period_range(from_period: str | None, to_period: str | None) -> list[str] | None:
    if from_period is None and to_period is None:
        return None
    if from_period is None:
        raise ValueError("from_period is required when to_period is provided")
    start = validate_period(from_period, name="from_period")
    end = validate_period(to_period or from_period, name="to_period")
    if start > end:
        raise ValueError("from_period must be on or before to_period")
    return iter_periods(start, end)


def _resolve_alias(
    row: Mapping[str, Any],
    primary: str,
    aliases: Sequence[str],
    *,
    non_negative: bool,
) -> int | None:
    present = [name for name in (primary, *aliases) if name in row]
    if not present:
        return None
    values = [
        _optional_cents(row.get(name), name, non_negative=non_negative)
        for name in present
    ]
    non_null = [value for value in values if value is not None]
    if len(set(non_null)) > 1:
        raise ValueError(f"{', '.join(present)} disagree")
    return non_null[0] if non_null else None


def _normalize_actuals(
    actuals: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if actuals is None:
        return {}
    raw_rows: list[Mapping[str, Any]] = []
    if isinstance(actuals, Mapping):
        if "initiative" in actuals:
            raw_rows = [actuals]
        else:
            for raw_name, raw_value in actuals.items():
                if not isinstance(raw_value, Mapping):
                    raise ValueError(
                        f"actuals[{raw_name!r}] must be a mapping of actual values"
                    )
                value = dict(raw_value)
                value.setdefault("initiative", raw_name)
                raw_rows.append(value)
    elif isinstance(actuals, Sequence) and not isinstance(actuals, (str, bytes)):
        raw_rows = list(actuals)
    else:
        raise ValueError("actuals must be a sequence of mappings or an initiative mapping")

    normalized: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"actuals[{index}] must be a mapping")
        if "initiative" not in raw:
            raise ValueError(f"actuals[{index}] requires initiative")
        initiative = _required_text(raw["initiative"], f"actuals[{index}].initiative")
        if initiative in normalized:
            raise ValueError(f"duplicate actuals for initiative {initiative!r}")
        normalized[initiative] = {
            "initiative": initiative,
            "actual_cost_cents": _resolve_alias(
                raw,
                "actual_cost_cents",
                ("cost_cents",),
                non_negative=True,
            ),
            "actual_noi_impact_cents": _resolve_alias(
                raw,
                "actual_noi_impact_cents",
                ("actual_noi_impact_cents_annual", "noi_impact_cents"),
                non_negative=False,
            ),
            "elapsed_months": _positive_or_zero_months(
                raw.get("elapsed_months"),
                f"actuals[{index}].elapsed_months",
            ),
            "source": raw.get("source") or "structured actual supplied by caller",
        }
    return normalized


def _period_map_total(
    value: Any,
    name: str,
    periods: Sequence[str] | None,
    *,
    non_negative: bool,
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping from YYYY-MM to integer cents")
    selected = set(periods) if periods is not None else None
    total = 0
    for raw_period, raw_cents in value.items():
        period = validate_period(str(raw_period), name=f"{name} period")
        cents = _optional_cents(
            raw_cents,
            f"{name}[{period}]",
            non_negative=non_negative,
        )
        if cents is None:
            raise ValueError(f"{name}[{period}] cannot be null")
        if selected is None or period in selected:
            total += cents
    return total


def _round_fraction(annual_cents: int, months: int) -> int:
    value = Decimal(annual_cents) * Decimal(months) / Decimal(12)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _forecast(
    initiative: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    periods: Sequence[str] | None,
) -> tuple[int, int, dict[str, Any]]:
    baseline = initiative.get("baseline") or {}
    cost_by_period = _period_map_total(
        baseline.get("forecast_cost_cents_by_period"),
        "forecast_cost_cents_by_period",
        periods,
        non_negative=True,
    )
    if cost_by_period is not None:
        forecast_cost = cost_by_period
        cost_basis = "sum(baseline.forecast_cost_cents_by_period in selected period range)"
    elif "forecast_cost_cents" in baseline:
        value = _optional_cents(
            baseline.get("forecast_cost_cents"),
            "baseline.forecast_cost_cents",
            non_negative=True,
        )
        if value is None:
            raise ValueError("baseline.forecast_cost_cents cannot be null")
        forecast_cost = value
        cost_basis = "baseline.forecast_cost_cents"
    else:
        forecast_cost = int(initiative["cost_cents"])
        cost_basis = "am_initiatives.cost_cents total budget"

    noi_by_period = _period_map_total(
        baseline.get("forecast_noi_impact_cents_by_period"),
        "forecast_noi_impact_cents_by_period",
        periods,
        non_negative=False,
    )
    elapsed = actual.get("elapsed_months") if actual is not None else None
    if noi_by_period is not None:
        forecast_noi = noi_by_period
        noi_basis = "sum(baseline.forecast_noi_impact_cents_by_period in selected period range)"
    elif "forecast_noi_impact_cents" in baseline:
        value = _optional_cents(
            baseline.get("forecast_noi_impact_cents"),
            "baseline.forecast_noi_impact_cents",
            non_negative=False,
        )
        if value is None:
            raise ValueError("baseline.forecast_noi_impact_cents cannot be null")
        forecast_noi = value
        noi_basis = "baseline.forecast_noi_impact_cents"
    else:
        annual = _optional_cents(
            baseline.get(
                "forecast_noi_impact_cents_annual",
                initiative["noi_impact_cents_annual"],
            ),
            "forecast_noi_impact_cents_annual",
            non_negative=False,
        )
        assert annual is not None
        comparison_months = (
            int(elapsed)
            if elapsed is not None
            else len(periods)
            if periods is not None
            else 12
        )
        forecast_noi = _round_fraction(annual, comparison_months)
        noi_basis = (
            "round_half_up(forecast_noi_impact_cents_annual * "
            f"{comparison_months} comparison months / 12)"
        )
    return forecast_cost, forecast_noi, {
        "cost": cost_basis,
        "noi": noi_basis,
        "selected_periods": list(periods) if periods is not None else None,
    }


def _book_periods(
    initiative: Mapping[str, Any],
    hook: Mapping[str, Any],
    selected_periods: Sequence[str] | None,
    as_of: date,
) -> list[str]:
    hook_from = hook.get("from_period")
    hook_to = hook.get("to_period")
    if hook_from is not None or hook_to is not None:
        if hook_from is None:
            raise ValueError("books_actuals.from_period is required with to_period")
        return _period_range(str(hook_from), str(hook_to) if hook_to is not None else None) or []
    if selected_periods is not None:
        return list(selected_periods)
    start = initiative.get("start")
    if start is None:
        raise ValueError(
            "books_actuals needs from_period/to_period, tracker periods, or an initiative start"
        )
    first = str(start)[:7]
    last = as_of.strftime("%Y-%m")
    if first > last:
        return []
    return iter_periods(first, last)


def _books_actual(
    initiative: Mapping[str, Any],
    books: BookStore,
    selected_periods: Sequence[str] | None,
    as_of: date,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    baseline = initiative.get("baseline") or {}
    raw_hook = baseline.get("books_actuals", baseline.get("books_actual"))
    if raw_hook is None:
        return None, None, (
            "No structured actual and no explicit baseline.books_actuals mapping; "
            "books were not allocated to this initiative."
        )
    if not isinstance(raw_hook, Mapping):
        raise ValueError("baseline.books_actuals must be a mapping")
    metric = str(raw_hook.get("metric") or "").strip().casefold()
    if metric not in BOOK_METRICS:
        raise ValueError(
            "baseline.books_actuals.metric must be scheduled_cents, billed_cents, "
            "collected_cents, or outstanding_cents"
        )
    if "baseline_cents" not in raw_hook:
        return None, None, (
            "baseline.books_actuals.baseline_cents is required to turn a book metric "
            "level into an initiative NOI impact."
        )
    baseline_cents = _optional_cents(
        raw_hook.get("baseline_cents"),
        "baseline.books_actuals.baseline_cents",
        non_negative=False,
    )
    if baseline_cents is None:
        raise ValueError("baseline.books_actuals.baseline_cents cannot be null")
    periods = _book_periods(initiative, raw_hook, selected_periods, as_of)
    deal_id = str(initiative["deal_id"])
    deal_tenancy_ids = {
        str(row["tenancy_id"])
        for row in books.list_tenancies()
        if str(row["deal_id"]) == deal_id
    }
    requested_tenancies = raw_hook.get("tenancy_ids")
    if requested_tenancies is not None:
        if not isinstance(requested_tenancies, Sequence) or isinstance(
            requested_tenancies, (str, bytes)
        ):
            raise ValueError("baseline.books_actuals.tenancy_ids must be a sequence")
        deal_tenancy_ids &= {str(value) for value in requested_tenancies}

    measured = 0
    trace: list[dict[str, Any]] = []
    for period in periods:
        reconciliation = rent_to_cash(period, store=books)
        relevant = [
            row
            for row in reconciliation["tenancies"]
            if str(row["tenancy_id"]) in deal_tenancy_ids
        ]
        period_value = sum(int(row[metric]) for row in relevant)
        measured += period_value
        trace.append(
            {
                "period": period,
                "metric_cents": period_value,
                "tenancy_ids": [str(row["tenancy_id"]) for row in relevant],
            }
        )
    if metric == "outstanding_cents":
        # Lower receivables are favorable, so preserve the NOI-impact sign
        # convention (positive = favorable) by reversing the level delta.
        actual_impact = baseline_cents - measured
        calculation = (
            "actual_noi_impact_cents = baseline.books_actuals.baseline_cents - "
            "measured_book_metric_cents; lower outstanding is favorable"
        )
    else:
        actual_impact = measured - baseline_cents
        calculation = (
            "actual_noi_impact_cents = measured_book_metric_cents - "
            "baseline.books_actuals.baseline_cents"
        )
    source = {
        "source": "cre_mcp.books.rent_to_cash read-only",
        "metric": metric,
        "periods": periods,
        "measured_book_metric_cents": measured,
        "comparison_baseline_cents": baseline_cents,
        "actual_noi_impact_cents": actual_impact,
        "calculation": calculation,
        "trace": trace,
    }
    return actual_impact, source, None


def _status(
    cost_delta: int | None,
    noi_delta: int | None,
) -> tuple[str, str]:
    cost_adverse = cost_delta is not None and cost_delta > 0
    noi_adverse = noi_delta is not None and noi_delta < 0
    if cost_adverse or noi_adverse:
        return (
            "behind",
            "Behind because actual cost exceeds forecast and/or actual NOI impact is below forecast.",
        )
    if cost_delta is not None and noi_delta is not None:
        return (
            "on_track",
            "On track because actual cost is at or below forecast and actual NOI impact is at or above forecast.",
        )
    return (
        "not_assessable",
        "No adverse known delta is hidden, but both cost and NOI actuals are required to assert on-track.",
    )


def initiative_tracker(
    deal_id: str,
    actuals: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    store: InitiativeStore | None = None,
) -> dict[str, Any]:
    """Compare every initiative baseline with actuals using shown delta math.

    Structured actual items accept ``initiative``, ``actual_cost_cents``,
    ``actual_noi_impact_cents``, and optional ``elapsed_months``.  The shorter
    aliases ``cost_cents`` and ``noi_impact_cents`` are accepted only when they
    agree with any explicit actual fields.
    """

    normalized_deal = _required_text(deal_id, "deal_id")
    point = _as_date(as_of)
    periods = _period_range(from_period, to_period)
    actual_by_name = _normalize_actuals(actuals)
    initiative_store = store or InitiativeStore(db_path)
    initiative_rows = initiative_store.list_initiatives(normalized_deal)
    initiative_names = {str(row["initiative"]) for row in initiative_rows}
    unmatched_actuals = sorted(set(actual_by_name) - initiative_names)
    books_path: str | Path | CreConfig | None = (
        db_path if db_path is not None else initiative_store.db_path
    )
    books = BookStore(books_path)
    gaps: list[str] = []
    if not initiative_rows:
        gaps.append(
            "No am_initiatives rows exist for this deal; there is nothing to assess."
        )
    if unmatched_actuals:
        gaps.append(
            "Structured actuals did not match stored initiatives: "
            + ", ".join(unmatched_actuals)
        )

    tracked: list[dict[str, Any]] = []
    for initiative in initiative_rows:
        name = str(initiative["initiative"])
        actual = actual_by_name.get(name)
        forecast_cost, forecast_noi, forecast_basis = _forecast(
            initiative, actual, periods
        )
        actual_cost = actual.get("actual_cost_cents") if actual is not None else None
        actual_noi = (
            actual.get("actual_noi_impact_cents") if actual is not None else None
        )
        actual_source: Any = actual.get("source") if actual is not None else None
        books_gap: str | None = None
        if actual_noi is None:
            books_noi, books_source, books_gap = _books_actual(
                initiative, books, periods, point
            )
            if books_noi is not None:
                actual_noi = books_noi
                actual_source = books_source
        if actual_cost is None:
            gaps.append(
                f"{name}: actual_cost_cents is unavailable; books contain no initiative-tagged CapEx spend."
            )
        if actual_noi is None:
            gaps.append(f"{name}: {books_gap or 'actual NOI impact is unavailable.'}")

        cost_delta = (
            int(actual_cost) - forecast_cost if actual_cost is not None else None
        )
        noi_delta = int(actual_noi) - forecast_noi if actual_noi is not None else None
        net_delta = (
            noi_delta - cost_delta
            if noi_delta is not None and cost_delta is not None
            else None
        )
        status, status_reason = _status(cost_delta, noi_delta)
        tracked.append(
            {
                "deal_id": normalized_deal,
                "initiative": name,
                "owner": initiative.get("owner"),
                "initiative_status": initiative.get("status"),
                "forecast_cost_cents": forecast_cost,
                "actual_cost_cents": actual_cost,
                "cost_delta_cents": cost_delta,
                "forecast_noi_impact_cents": forecast_noi,
                "actual_noi_impact_cents": actual_noi,
                "noi_delta_cents": noi_delta,
                "net_performance_delta_cents": net_delta,
                "status": status,
                "status_reason": status_reason,
                "forecast_basis": forecast_basis,
                "actual_source": actual_source,
                "delta_math": {
                    "cost": "cost_delta_cents = actual_cost_cents - forecast_cost_cents; positive is unfavorable",
                    "noi": "noi_delta_cents = actual_noi_impact_cents - forecast_noi_impact_cents; negative is unfavorable",
                    "net": "net_performance_delta_cents = noi_delta_cents - cost_delta_cents",
                    "identity_values_cents": {
                        "cost": {
                            "actual": actual_cost,
                            "forecast": forecast_cost,
                            "delta": cost_delta,
                        },
                        "noi": {
                            "actual": actual_noi,
                            "forecast": forecast_noi,
                            "delta": noi_delta,
                        },
                        "net": net_delta,
                    },
                },
            }
        )

    all_cost_actual = all(row["actual_cost_cents"] is not None for row in tracked)
    all_noi_actual = all(
        row["actual_noi_impact_cents"] is not None for row in tracked
    )
    totals = {
        "forecast_cost_cents": sum(row["forecast_cost_cents"] for row in tracked),
        "actual_cost_cents": (
            sum(int(row["actual_cost_cents"]) for row in tracked)
            if all_cost_actual
            else None
        ),
        "cost_delta_cents": (
            sum(int(row["cost_delta_cents"]) for row in tracked)
            if all_cost_actual
            else None
        ),
        "forecast_noi_impact_cents": sum(
            row["forecast_noi_impact_cents"] for row in tracked
        ),
        "actual_noi_impact_cents": (
            sum(int(row["actual_noi_impact_cents"]) for row in tracked)
            if all_noi_actual
            else None
        ),
        "noi_delta_cents": (
            sum(int(row["noi_delta_cents"]) for row in tracked)
            if all_noi_actual
            else None
        ),
    }
    if totals["cost_delta_cents"] is not None and totals["noi_delta_cents"] is not None:
        totals["net_performance_delta_cents"] = (
            totals["noi_delta_cents"] - totals["cost_delta_cents"]
        )
    else:
        totals["net_performance_delta_cents"] = None

    statuses = [row["status"] for row in tracked]
    overall_status = (
        "behind"
        if "behind" in statuses
        else "on_track"
        if statuses and all(status == "on_track" for status in statuses)
        else "not_assessable"
    )
    return {
        "deal_id": normalized_deal,
        "as_of": point.isoformat(),
        "from_period": periods[0] if periods else None,
        "to_period": periods[-1] if periods else None,
        "initiatives": tracked,
        "totals": totals,
        "overall_status": overall_status,
        "unmatched_actual_initiatives": unmatched_actuals,
        "conventions": {
            "cost_delta": "actual - forecast; positive is unfavorable",
            "noi_delta": "actual - forecast; negative is unfavorable",
            "status": (
                "behind if either known delta is adverse; on_track only when both "
                "actual dimensions are present and non-adverse; otherwise not_assessable"
            ),
            "money": "All stored, compared, and returned money amounts are integer cents.",
            "books": (
                "Books are read only and used only through an initiative's explicit "
                "baseline.books_actuals metric mapping."
            ),
        },
        "honest_gaps": gaps,
    }


__all__ = ["BOOK_METRICS", "initiative_tracker"]
