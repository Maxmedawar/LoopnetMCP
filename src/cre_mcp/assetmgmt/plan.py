"""Durable asset-management initiatives and arithmetic business-plan ranking.

Only ``am_initiatives`` is owned by this module.  Money is stored and returned
as integer cents.  Ranking conventions are disclosed with the result so a
recommendation can be reproduced rather than accepted as narrative judgment.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from cre_mcp.config import CreConfig

DEFAULT_EXECUTION_SUCCESS_BY_STATUS: dict[str, Decimal] = {
    "planned": Decimal("0.65"),
    "approved": Decimal("0.80"),
    "in_progress": Decimal("0.90"),
    "complete": Decimal("1.00"),
    "blocked": Decimal("0.25"),
    "cancelled": Decimal("0.00"),
}
UNKNOWN_STATUS_SUCCESS = Decimal("0.50")
RANKING_FORMULA = (
    "capitalized_noi_value_cents = round_half_up("
    "noi_impact_cents_annual / input_cap_rate); "
    "value_less_cost_cents = capitalized_noi_value_cents - cost_cents; "
    "risk_adjusted_value_cents = round_half_up("
    "value_less_cost_cents * execution_success_probability)"
)


def _required_text(value: Any, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank when provided")
    return normalized


def _integer_cents(value: Any, name: str, *, non_negative: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_months(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("months must be a positive integer when provided")
    return value


def _iso_date(value: date | datetime | str | None, name: str = "start") -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    normalized = str(value).strip()
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date when provided") from exc


def _round_decimal(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rate(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a decimal rate greater than 0 and less than 1")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"{name} must be a decimal rate greater than 0 and less than 1"
        ) from exc
    if not normalized.is_finite() or normalized <= 0 or normalized >= 1:
        raise ValueError(f"{name} must be a decimal rate greater than 0 and less than 1")
    return normalized


def _probability(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a probability from 0 through 1")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a probability from 0 through 1") from exc
    if not normalized.is_finite() or normalized < 0 or normalized > 1:
        raise ValueError(f"{name} must be a probability from 0 through 1")
    return normalized


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _decode_baseline(raw: Any) -> tuple[dict[str, Any], str | None]:
    try:
        decoded = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError) as exc:
        return {}, f"baseline_json could not be decoded: {exc}"
    if not isinstance(decoded, dict):
        return {}, "baseline_json was not an object"
    return decoded, None


class InitiativeStore:
    """Own and query asset-management initiative baselines in shared SQLite."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if isinstance(db_path, CreConfig):
            resolved = db_path.cache_db_path
        else:
            resolved = db_path or (config or CreConfig()).cache_db_path
        self.db_path = Path(resolved).expanduser()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction and initialize only the owned initiative table."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS am_initiatives (
                deal_id TEXT NOT NULL,
                initiative TEXT NOT NULL,
                owner TEXT,
                cost_cents INTEGER NOT NULL,
                noi_impact_cents_annual INTEGER NOT NULL,
                start TEXT,
                months INTEGER,
                status TEXT,
                baseline_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(deal_id, initiative),
                CHECK(cost_cents >= 0),
                CHECK(months IS NULL OR months > 0)
            );
            CREATE INDEX IF NOT EXISTS idx_am_initiatives_plan
                ON am_initiatives(deal_id, start, status, initiative);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def upsert_initiative(
        self,
        deal_id: str,
        initiative: str,
        cost_cents: int,
        noi_impact_cents_annual: int,
        owner: str | None = None,
        start: date | datetime | str | None = None,
        months: int | None = None,
        status: str | None = "planned",
        baseline: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or replace one initiative without adding undeclared table columns."""

        if baseline is not None and not isinstance(baseline, Mapping):
            raise ValueError("baseline must be a mapping when provided")
        normalized_deal = _required_text(deal_id, "deal_id")
        normalized_initiative = _required_text(initiative, "initiative")
        baseline_json = json.dumps(
            dict(baseline or {}),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        values = (
            normalized_deal,
            normalized_initiative,
            _optional_text(owner, "owner"),
            _integer_cents(cost_cents, "cost_cents", non_negative=True),
            _integer_cents(
                noi_impact_cents_annual,
                "noi_impact_cents_annual",
                non_negative=False,
            ),
            _iso_date(start),
            _positive_months(months),
            _optional_text(status, "status"),
            baseline_json,
        )
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO am_initiatives(
                    deal_id, initiative, owner, cost_cents,
                    noi_impact_cents_annual, start, months, status, baseline_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id, initiative) DO UPDATE SET
                    owner=excluded.owner,
                    cost_cents=excluded.cost_cents,
                    noi_impact_cents_annual=excluded.noi_impact_cents_annual,
                    start=excluded.start,
                    months=excluded.months,
                    status=excluded.status,
                    baseline_json=excluded.baseline_json
                """,
                values,
            )
            row = connection.execute(
                """
                SELECT deal_id, initiative, owner, cost_cents,
                       noi_impact_cents_annual, start, months, status, baseline_json
                FROM am_initiatives WHERE deal_id=? AND initiative=?
                """,
                (normalized_deal, normalized_initiative),
            ).fetchone()
        if row is None:
            raise RuntimeError("initiative upsert did not produce a durable row")
        return self._result_row(row)

    @staticmethod
    def _result_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        baseline, error = _decode_baseline(result["baseline_json"])
        result["baseline"] = baseline
        if error is not None:
            result["baseline_parse_error"] = error
        return result

    def list_initiatives(self, deal_id: str) -> list[dict[str, Any]]:
        normalized_deal = _required_text(deal_id, "deal_id")
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT deal_id, initiative, owner, cost_cents,
                       noi_impact_cents_annual, start, months, status, baseline_json
                FROM am_initiatives
                WHERE deal_id=?
                ORDER BY CASE WHEN start IS NULL THEN 1 ELSE 0 END,
                         start, initiative
                """,
                (normalized_deal,),
            ).fetchall()
        return [self._result_row(row) for row in rows]


def upsert_initiative(
    deal_id: str,
    initiative: str,
    cost_cents: int,
    noi_impact_cents_annual: int,
    owner: str | None = None,
    start: date | datetime | str | None = None,
    months: int | None = None,
    status: str | None = "planned",
    baseline: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Convenience insertion function for callers that do not retain a store."""

    return InitiativeStore(db_path).upsert_initiative(
        deal_id,
        initiative,
        cost_cents,
        noi_impact_cents_annual,
        owner,
        start,
        months,
        status,
        baseline,
    )


def _initiative_overlaps_year(row: Mapping[str, Any], year: int) -> bool:
    if row.get("start") is None:
        return True
    start = date.fromisoformat(str(row["start"]))
    months = int(row["months"] or 1)
    # Completion is the first day outside the scheduled execution window.
    completion = _add_months(start, months)
    return start <= date(year, 12, 31) and completion > date(year, 1, 1)


def _milestones(row: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    baseline = row.get("baseline") or {}
    supplied = baseline.get("milestones")
    if isinstance(supplied, Sequence) and not isinstance(supplied, (str, bytes)):
        milestones = [dict(item) if isinstance(item, Mapping) else {"milestone": str(item)} for item in supplied]
        return milestones, []
    start_text = row.get("start")
    if start_text is None:
        return [], [f"{row['initiative']}: start is unset, so dated milestones cannot be inferred."]
    start = date.fromisoformat(str(start_text))
    months = row.get("months")
    milestones = [{"milestone": "kickoff", "date": start.isoformat()}]
    gaps: list[str] = []
    if months is None:
        gaps.append(
            f"{row['initiative']}: months is unset, so target completion cannot be inferred."
        )
    else:
        milestones.append(
            {
                "milestone": "target_completion",
                "date": _add_months(start, int(months)).isoformat(),
                "date_convention": "start plus execution months",
            }
        )
    return milestones, gaps


def _normalize_budget_hooks(
    supplied: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    initiatives: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | list[dict[str, Any]], int | None, list[str]]:
    gaps: list[str] = []
    baseline_noi: int | None = None
    if supplied is None:
        hooks: dict[str, Any] | list[dict[str, Any]] = []
    elif isinstance(supplied, Mapping):
        hooks = dict(supplied)
        raw_baseline = supplied.get(
            "baseline_noi_cents_annual",
            supplied.get("budgeted_noi_cents_annual"),
        )
        if raw_baseline is not None:
            baseline_noi = _integer_cents(
                raw_baseline,
                "baseline_noi_cents_annual",
                non_negative=False,
            )
    elif isinstance(supplied, Sequence) and not isinstance(supplied, (str, bytes)):
        hooks = []
        for index, item in enumerate(supplied):
            if not isinstance(item, Mapping):
                raise ValueError(f"budget_hooks[{index}] must be a mapping")
            hooks.append(dict(item))
    else:
        raise ValueError("budget_hooks must be a mapping or sequence of mappings")

    initiative_hooks: list[dict[str, Any]] = []
    for row in initiatives:
        hook = (row.get("baseline") or {}).get("budget_hooks")
        if hook is not None:
            initiative_hooks.append({"initiative": row["initiative"], "hooks": hook})
    if initiative_hooks:
        if isinstance(hooks, dict):
            hooks["initiative_hooks"] = initiative_hooks
        else:
            hooks.extend(initiative_hooks)
    if baseline_noi is None:
        gaps.append(
            "No baseline_noi_cents_annual budget hook was supplied; ending annual NOI is not asserted."
        )
    return hooks, baseline_noi, gaps


def business_plan(
    deal_id: str,
    year: int,
    budget_hooks: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    store: InitiativeStore | None = None,
) -> dict[str, Any]:
    """Assemble a year plan with accountable initiatives and an NOI bridge."""

    if isinstance(year, bool) or not isinstance(year, int) or year < 1900 or year > 9999:
        raise ValueError("year must be a four-digit integer")
    normalized_deal = _required_text(deal_id, "deal_id")
    all_rows = (store or InitiativeStore(db_path)).list_initiatives(normalized_deal)
    included = [row for row in all_rows if _initiative_overlaps_year(row, year)]
    excluded = [row["initiative"] for row in all_rows if row not in included]
    gaps: list[str] = []
    plan_rows: list[dict[str, Any]] = []
    for row in included:
        milestones, milestone_gaps = _milestones(row)
        gaps.extend(milestone_gaps)
        if row.get("owner") is None:
            gaps.append(f"{row['initiative']}: owner is unassigned.")
        plan_rows.append(
            {
                "initiative": row["initiative"],
                "owner": row.get("owner"),
                "status": row.get("status"),
                "start": row.get("start"),
                "months": row.get("months"),
                "cost_cents": int(row["cost_cents"]),
                "noi_impact_cents_annual": int(row["noi_impact_cents_annual"]),
                "milestones": milestones,
                "baseline": row.get("baseline", {}),
            }
        )
    hooks, baseline_noi, budget_gaps = _normalize_budget_hooks(
        budget_hooks, included
    )
    gaps.extend(budget_gaps)
    initiative_noi = sum(row["noi_impact_cents_annual"] for row in plan_rows)
    expected_ending = (
        baseline_noi + initiative_noi if baseline_noi is not None else None
    )
    total_cost = sum(row["cost_cents"] for row in plan_rows)
    return {
        "deal_id": normalized_deal,
        "year": year,
        "initiatives": plan_rows,
        "excluded_outside_year": excluded,
        "budget_hooks": hooks,
        "totals": {
            "initiative_count": len(plan_rows),
            "cost_cents": total_cost,
            "noi_impact_cents_annual": initiative_noi,
        },
        "expected_noi_bridge": {
            "baseline_noi_cents_annual": baseline_noi,
            "initiative_noi_impact_cents_annual": initiative_noi,
            "expected_noi_cents_annual": expected_ending,
            "calculation": (
                "expected_noi_cents_annual = baseline_noi_cents_annual + "
                "sum(initiative.noi_impact_cents_annual)"
            ),
            "initiative_lines": [
                {
                    "initiative": row["initiative"],
                    "noi_impact_cents_annual": row["noi_impact_cents_annual"],
                }
                for row in plan_rows
            ],
        },
        "honest_gaps": gaps,
    }


def rank_initiatives(
    deal_id: str,
    input_cap_rate: float | Decimal | str = 0.07,
    execution_success_by_status: Mapping[str, float | Decimal | str] | None = None,
    bandwidth: int = 3,
    *,
    db_path: str | Path | CreConfig | None = None,
    store: InitiativeStore | None = None,
) -> dict[str, Any]:
    """Rank initiatives by disclosed value math, then apply a hard bandwidth cap."""

    normalized_deal = _required_text(deal_id, "deal_id")
    cap_rate = _rate(input_cap_rate, "input_cap_rate")
    if isinstance(bandwidth, bool) or not isinstance(bandwidth, int) or bandwidth < 0:
        raise ValueError("bandwidth must be a non-negative integer")
    success_by_status = dict(DEFAULT_EXECUTION_SUCCESS_BY_STATUS)
    if execution_success_by_status is not None:
        if not isinstance(execution_success_by_status, Mapping):
            raise ValueError("execution_success_by_status must be a mapping")
        for raw_status, raw_probability in execution_success_by_status.items():
            status = _required_text(raw_status, "execution status").casefold()
            success_by_status[status] = _probability(
                raw_probability,
                f"execution_success_by_status[{status}]",
            )

    rows = (store or InitiativeStore(db_path)).list_initiatives(normalized_deal)
    scored: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").strip().casefold()
        probability = success_by_status.get(status, UNKNOWN_STATUS_SUCCESS)
        probability_source = (
            f"execution_success_by_status[{status}]"
            if status in success_by_status
            else "unknown-status fallback convention"
        )
        capitalized_value = _round_decimal(
            Decimal(int(row["noi_impact_cents_annual"])) / cap_rate
        )
        value_less_cost = capitalized_value - int(row["cost_cents"])
        risk_adjusted = _round_decimal(Decimal(value_less_cost) * probability)
        scored.append(
            {
                "deal_id": normalized_deal,
                "initiative": row["initiative"],
                "owner": row.get("owner"),
                "status": row.get("status"),
                "cost_cents": int(row["cost_cents"]),
                "noi_impact_cents_annual": int(row["noi_impact_cents_annual"]),
                "input_cap_rate": float(cap_rate),
                "capitalized_noi_value_cents": capitalized_value,
                "value_less_cost_cents": value_less_cost,
                "execution_success_probability": float(probability),
                "execution_probability_source": probability_source,
                "risk_adjusted_value_cents": risk_adjusted,
                "execution_months": row.get("months"),
                "formula": RANKING_FORMULA,
                "calculation_inputs": {
                    "noi_impact_cents_annual": int(row["noi_impact_cents_annual"]),
                    "input_cap_rate": float(cap_rate),
                    "cost_cents": int(row["cost_cents"]),
                    "execution_success_probability": float(probability),
                },
            }
        )
    scored.sort(
        key=lambda item: (
            -item["risk_adjusted_value_cents"],
            item["execution_months"] if item["execution_months"] is not None else 10**9,
            str(item["initiative"]).casefold(),
        )
    )
    for rank, item in enumerate(scored, start=1):
        selected = rank <= bandwidth and item["risk_adjusted_value_cents"] > 0
        item["rank"] = rank
        item["bandwidth_selected"] = selected
        item["recommended"] = selected
        if selected:
            reason = (
                f"Selected at rank {rank} within bandwidth {bandwidth}: "
                f"risk-adjusted value {item['risk_adjusted_value_cents']} cents is positive."
            )
        elif item["risk_adjusted_value_cents"] <= 0:
            reason = (
                f"Not selected: risk-adjusted value is "
                f"{item['risk_adjusted_value_cents']} cents, which is not positive."
            )
        else:
            reason = f"Not selected: rank {rank} exceeds bandwidth {bandwidth}."
        item["recommendation_math"] = reason

    conventions = {
        "formula": RANKING_FORMULA,
        "rounding": "Integer cents, ROUND_HALF_UP at each named formula output.",
        "execution_success_by_status": {
            status: float(probability)
            for status, probability in sorted(success_by_status.items())
        },
        "unknown_status_success_probability": float(UNKNOWN_STATUS_SUCCESS),
        "bandwidth": (
            "At most the first bandwidth positive-value rows are selected; "
            "a non-positive row is never recommended merely to fill capacity."
        ),
        "time": (
            "Execution months is a shorter-time tiebreak only. No unsupported "
            "monthly cash-flow timing or discount curve is inferred."
        ),
    }
    return {
        "deal_id": normalized_deal,
        "input_cap_rate": float(cap_rate),
        "bandwidth": bandwidth,
        "ranked_initiatives": scored,
        "initiatives": scored,
        "selected_initiatives": [
            item for item in scored if item["bandwidth_selected"]
        ],
        "formula": RANKING_FORMULA,
        "conventions": conventions,
        "honest_gaps": [
            "Capitalizing one annual NOI increment is a screening convention, not a full DCF.",
            "Execution probabilities are labeled conventions, not measured failure statistics.",
            "Dependencies among initiatives and a month-by-month discount curve are not modeled.",
        ],
    }


__all__ = [
    "DEFAULT_EXECUTION_SUCCESS_BY_STATUS",
    "InitiativeStore",
    "RANKING_FORMULA",
    "business_plan",
    "rank_initiatives",
    "upsert_initiative",
]
