"""Construction draw forecasting, persistence, and pay-application audits.

All monetary amounts are integer cents.  Forecasts are planning conventions;
they are not contractor invoices, architect certifications, or field
inspection results.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


CX_PROJECTS_TABLE = "cx_projects"
CX_DRAWS_TABLE = "cx_draws"
DRAW_CURVES = frozenset({"linear", "s_curve"})
FORECAST_BASIS = "planning convention; replace with GC schedule of values and lender-approved draw schedule"


def _integer_cents(name: str, value: Any, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer cents")
    if value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier} integer cents")
    return value


def _decimal(name: str, value: Any, *, non_negative: bool = True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not result.is_finite() or (non_negative and result < 0):
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _percentage(name: str, value: Any) -> Decimal:
    result = _decimal(name, value)
    if result > 1:
        if result > 100:
            raise ValueError(f"{name} must be between 0 and 1, or 0 and 100")
        result /= Decimal(100)
    return result


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _iso_month(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("schedule.start is required")
        try:
            if len(text) == 7:
                parsed = date.fromisoformat(f"{text}-01")
            else:
                parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("schedule.start must be an ISO date or YYYY-MM") from exc
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _add_month(start: str, offset: int) -> str:
    year, month = (int(part) for part in start.split("-"))
    month_index = year * 12 + month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def _budget_total(budget: int | Mapping[str, Any]) -> int:
    if isinstance(budget, Mapping):
        for key in ("total_budget_cents", "budget_cents", "total_cents"):
            if key in budget:
                return _integer_cents(f"budget.{key}", budget[key], positive=True)
        line_items = budget.get("line_items")
        if isinstance(line_items, Sequence) and not isinstance(line_items, (str, bytes)):
            total = 0
            for index, item in enumerate(line_items):
                if not isinstance(item, Mapping):
                    raise ValueError(f"budget.line_items[{index}] must be a mapping")
                amount = item.get("amount_cents", item.get("total_cents"))
                total += _integer_cents(
                    f"budget.line_items[{index}].amount_cents", amount
                )
            return _integer_cents("budget line-item total", total, positive=True)
        raise ValueError(
            "budget needs total_budget_cents, budget_cents, total_cents, or line_items"
        )
    return _integer_cents("budget", budget, positive=True)


def _monthly_amounts(total_cents: int, months: int, curve: str) -> list[int]:
    cumulative: list[int] = []
    for month in range(1, months + 1):
        fraction = Decimal(month) / Decimal(months)
        if curve == "s_curve":
            # Smoothstep is transparent, monotonic, and exactly 0/1 at the ends.
            fraction = Decimal(3) * fraction * fraction - Decimal(2) * fraction**3
        cumulative.append(_round_cents(Decimal(total_cents) * fraction))
    cumulative[-1] = total_cents
    amounts: list[int] = []
    prior = 0
    for value in cumulative:
        amounts.append(value - prior)
        prior = value
    return amounts


def _interest_check(
    total_budget_cents: int,
    monthly_amounts: Sequence[int],
    loan_terms: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if loan_terms is None:
        return {
            "status": "not_provided",
            "basis": "not calculated; loan terms were not supplied",
            "required_interest_cents": None,
            "interest_reserve_cents": None,
            "surplus_shortfall_cents": None,
            "monthly_interest": [],
        }

    reserve_value = loan_terms.get("interest_reserve_cents")
    reserve = (
        None
        if reserve_value is None
        else _integer_cents("loan_terms.interest_reserve_cents", reserve_value)
    )
    annual_rate_value = loan_terms.get(
        "annual_interest_rate", loan_terms.get("annual_interest_rate_pct")
    )
    if annual_rate_value is None:
        raise ValueError("loan_terms.annual_interest_rate is required")
    annual_rate = _percentage("loan_terms.annual_interest_rate", annual_rate_value)

    if loan_terms.get("loan_amount_cents") is not None:
        loan_amount = _integer_cents(
            "loan_terms.loan_amount_cents", loan_terms["loan_amount_cents"], positive=True
        )
    elif loan_terms.get("loan_to_cost_pct") is not None:
        loan_amount = _round_cents(
            Decimal(total_budget_cents)
            * _percentage("loan_terms.loan_to_cost_pct", loan_terms["loan_to_cost_pct"])
        )
    else:
        raise ValueError("loan_terms needs loan_amount_cents or loan_to_cost_pct")
    if loan_amount > total_budget_cents:
        raise ValueError("loan amount cannot exceed the construction budget")

    starting_balance = _integer_cents(
        "loan_terms.starting_balance_cents",
        loan_terms.get("starting_balance_cents", 0),
    )
    if starting_balance > loan_amount:
        raise ValueError("starting balance cannot exceed loan amount")

    monthly_rate = annual_rate / Decimal(12)
    cumulative_cost = 0
    prior_balance = starting_balance
    monthly_interest: list[dict[str, Any]] = []
    required = 0
    available_to_draw = loan_amount - starting_balance
    for index, amount in enumerate(monthly_amounts, start=1):
        cumulative_cost += amount
        target_increment = _round_cents(
            Decimal(cumulative_cost)
            * Decimal(available_to_draw)
            / Decimal(total_budget_cents)
        )
        ending_balance = min(loan_amount, starting_balance + target_increment)
        average_balance = (Decimal(prior_balance) + Decimal(ending_balance)) / Decimal(2)
        interest = _round_cents(average_balance * monthly_rate)
        required += interest
        monthly_interest.append(
            {
                "month_number": index,
                "beginning_balance_cents": prior_balance,
                "principal_draw_cents": ending_balance - prior_balance,
                "ending_balance_cents": ending_balance,
                "interest_cents": interest,
                "basis": "planning convention: monthly interest on average loan balance",
            }
        )
        prior_balance = ending_balance

    variance = None if reserve is None else reserve - required
    return {
        "status": (
            "reserve_not_supplied"
            if variance is None
            else "adequate"
            if variance >= 0
            else "shortfall"
        ),
        "basis": (
            "planning convention using pro-rata loan funding and average monthly "
            "outstanding balance; lender mechanics may differ"
        ),
        "loan_amount_cents": loan_amount,
        "annual_interest_rate_pct": float(annual_rate * Decimal(100)),
        "required_interest_cents": required,
        "interest_reserve_cents": reserve,
        "surplus_shortfall_cents": variance,
        "monthly_interest": monthly_interest,
    }


class ConstructionDrawStore:
    """Own only ``cx_projects`` and ``cx_draws`` in the selected SQLite file."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved = db_path or Path.home() / ".cache" / "cre_mcp" / "cache.db"
        self.db_path = Path(resolved).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cx_projects (
                project_id TEXT PRIMARY KEY,
                budget_cents INTEGER NOT NULL CHECK(budget_cents >= 0),
                schedule_start TEXT NOT NULL,
                schedule_months INTEGER NOT NULL CHECK(schedule_months > 0),
                curve TEXT NOT NULL CHECK(curve IN ('linear', 's_curve')),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cx_draws (
                project_id TEXT NOT NULL,
                draw_number INTEGER NOT NULL CHECK(draw_number > 0),
                period TEXT NOT NULL,
                projected_draw_cents INTEGER NOT NULL CHECK(projected_draw_cents >= 0),
                cumulative_draw_cents INTEGER NOT NULL CHECK(cumulative_draw_cents >= 0),
                actual_draw_cents INTEGER CHECK(actual_draw_cents IS NULL OR actual_draw_cents >= 0),
                evidence_basis TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, draw_number),
                FOREIGN KEY(project_id) REFERENCES cx_projects(project_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_cx_draws_period
                ON cx_draws(project_id, period);
            """
        )
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def save_forecast(self, project_id: str, forecast: Mapping[str, Any]) -> dict[str, Any]:
        normalized_id = str(project_id).strip()
        if not normalized_id:
            raise ValueError("project_id cannot be blank")
        total = _integer_cents(
            "forecast.total_budget_cents", forecast.get("total_budget_cents"), positive=True
        )
        rows = forecast.get("monthly_draws")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
            raise ValueError("forecast.monthly_draws must be a non-empty sequence")
        validated_rows: list[Mapping[str, Any]] = []
        prior_cumulative = 0
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                raise ValueError(f"forecast.monthly_draws[{index - 1}] must be a mapping")
            draw_number = row.get("month_number")
            if isinstance(draw_number, bool) or draw_number != index:
                raise ValueError("forecast month numbers must be consecutive positive integers")
            amount = _integer_cents(
                f"forecast.monthly_draws[{index - 1}].projected_draw_cents",
                row.get("projected_draw_cents"),
            )
            cumulative = _integer_cents(
                f"forecast.monthly_draws[{index - 1}].cumulative_draw_cents",
                row.get("cumulative_draw_cents"),
            )
            if cumulative != prior_cumulative + amount:
                raise ValueError("forecast cumulative draw arithmetic is inconsistent")
            _iso_month(row.get("period"))
            validated_rows.append(row)
            prior_cumulative = cumulative
        if prior_cumulative != total:
            raise ValueError("forecast monthly draws do not total the project budget")
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cx_projects(
                    project_id, budget_cents, schedule_start, schedule_months,
                    curve, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    budget_cents=excluded.budget_cents,
                    schedule_start=excluded.schedule_start,
                    schedule_months=excluded.schedule_months,
                    curve=excluded.curve,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_id,
                    total,
                    forecast["schedule"]["start"],
                    forecast["schedule"]["months"],
                    forecast["schedule"]["curve"],
                    json.dumps({"forecast_basis": forecast["forecast_basis"]}, sort_keys=True),
                    now,
                ),
            )
            connection.execute("DELETE FROM cx_draws WHERE project_id=?", (normalized_id,))
            for row in validated_rows:
                connection.execute(
                    """
                    INSERT INTO cx_draws(
                        project_id, draw_number, period, projected_draw_cents,
                        cumulative_draw_cents, actual_draw_cents, evidence_basis, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        normalized_id,
                        row["month_number"],
                        row["period"],
                        row["projected_draw_cents"],
                        row["cumulative_draw_cents"],
                        row["basis"],
                        now,
                    ),
                )
        return {
            "project_id": normalized_id,
            "saved_draw_count": len(validated_rows),
            "table": CX_DRAWS_TABLE,
        }


# Concise alias for callers following the other package store conventions.
DrawStore = ConstructionDrawStore


def forecast_draws(
    budget: int | Mapping[str, Any],
    schedule: Mapping[str, Any],
    loan_terms: Mapping[str, Any] | None = None,
    project_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a penny-exact monthly draw forecast and optional reserve check."""

    if not isinstance(schedule, Mapping):
        raise ValueError("schedule must be a mapping")
    total = _budget_total(budget)
    start = _iso_month(schedule.get("start"))
    months = schedule.get("months")
    if isinstance(months, bool) or not isinstance(months, int) or months <= 0:
        raise ValueError("schedule.months must be a positive integer")
    curve = str(schedule.get("curve", "")).strip().casefold()
    if curve not in DRAW_CURVES:
        raise ValueError("schedule.curve must be linear or s_curve")

    amounts = _monthly_amounts(total, months, curve)
    rows: list[dict[str, Any]] = []
    cumulative = 0
    for index, amount in enumerate(amounts, start=1):
        cumulative += amount
        rows.append(
            {
                "month_number": index,
                "period": _add_month(start, index - 1),
                "projected_draw_cents": amount,
                "cumulative_draw_cents": cumulative,
                "remaining_cost_to_complete_cents": total - cumulative,
                "basis": FORECAST_BASIS,
            }
        )

    embedded_terms = budget.get("loan_terms") if isinstance(budget, Mapping) else None
    terms = loan_terms if loan_terms is not None else embedded_terms
    if terms is not None and not isinstance(terms, Mapping):
        raise ValueError("loan_terms must be a mapping or null")
    result: dict[str, Any] = {
        "total_budget_cents": total,
        "schedule": {"start": start, "months": months, "curve": curve},
        "monthly_draws": rows,
        "projected_draw_total_cents": sum(amounts),
        "forecast_basis": FORECAST_BASIS,
        "interest_reserve_check": _interest_check(total, amounts, terms),
        "professional_review_flags": [
            "GC: replace convention curve with current schedule of values and procurement plan.",
            "architect: certify eligible completed work before each actual draw.",
            "engineer: validate discipline-specific completion where certification is required.",
            "inspector: field-verify actual progress; this forecast is not field evidence.",
            "lender: confirm funding order, retainage, interest calculation, and eligible costs.",
        ],
        "review_flags": {
            "gc_review_required": True,
            "architect_review_required": True,
            "engineer_review_required": True,
            "inspector_review_required": True,
        },
    }
    if project_id is not None:
        result["persistence"] = ConstructionDrawStore(db_path).save_forecast(project_id, result)
    elif db_path is not None:
        raise ValueError("project_id is required when db_path is supplied")
    return result


def _waiver_state(values: Any) -> dict[str, bool]:
    if values is None:
        return {}
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError("evidence.lien_waivers must be a list")
    state: dict[str, bool] = {}
    for index, value in enumerate(values):
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                state[normalized.casefold()] = True
            continue
        if not isinstance(value, Mapping):
            raise ValueError(f"evidence.lien_waivers[{index}] must be text or a mapping")
        item = str(value.get("item", value.get("contractor", ""))).strip()
        if not item:
            raise ValueError(f"evidence.lien_waivers[{index}] needs item or contractor")
        received = value.get("received", True)
        if not isinstance(received, bool):
            raise ValueError(
                f"evidence.lien_waivers[{index}].received must be true or false"
            )
        state[item.casefold()] = received
    return state


def audit_pay_app(
    pay_app: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit line arithmetic and separate invoice support from field evidence."""

    if not isinstance(pay_app, Mapping) or not isinstance(evidence, Mapping):
        raise ValueError("pay_app and evidence must be mappings")
    lines = pay_app.get("lines")
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)) or not lines:
        raise ValueError("pay_app.lines must be a non-empty list")
    retainage_rate = _percentage("pay_app.retainage_pct", pay_app.get("retainage_pct"))
    waiver_state = _waiver_state(evidence.get("lien_waivers", []))

    line_audit: list[dict[str, Any]] = []
    scheduled_total = 0
    prior_total = 0
    current_work_total = 0
    stored_total = 0
    missing_waivers: list[str] = []
    stored_flags: list[dict[str, Any]] = []
    for index, raw in enumerate(lines):
        if not isinstance(raw, Mapping):
            raise ValueError(f"pay_app.lines[{index}] must be a mapping")
        item = str(raw.get("item", "")).strip()
        if not item:
            raise ValueError(f"pay_app.lines[{index}].item is required")
        scheduled = _integer_cents(
            f"pay_app.lines[{index}].scheduled_cents", raw.get("scheduled_cents"), positive=True
        )
        prior = _integer_cents(
            f"pay_app.lines[{index}].prev_billed_cents", raw.get("prev_billed_cents")
        )
        current = _integer_cents(
            f"pay_app.lines[{index}].this_period_cents", raw.get("this_period_cents")
        )
        stored = _integer_cents(
            f"pay_app.lines[{index}].stored_materials_cents",
            raw.get("stored_materials_cents"),
        )
        earned = prior + current + stored
        waiver_identity = str(raw.get("contractor", item)).strip() or item
        balance = scheduled - earned
        line_overbilling = max(0, -balance)
        line_audit.append(
            {
                "item": item,
                "waiver_identity": waiver_identity,
                "scheduled_cents": scheduled,
                "previously_billed_cents": prior,
                "this_period_work_cents": current,
                "stored_materials_cents": stored,
                "earned_to_date_cents": earned,
                "balance_to_finish_cents": balance,
                "over_scheduled_cents": line_overbilling,
                "invoice_basis": "invoice-supported; not field-verified",
            }
        )
        scheduled_total += scheduled
        prior_total += prior
        current_work_total += current
        stored_total += stored
        if current + stored > 0 and not waiver_state.get(waiver_identity.casefold(), False):
            missing_waivers.append(waiver_identity)
        if stored > 0:
            stored_flags.append(
                {
                    "item": item,
                    "stored_materials_cents": stored,
                    "basis": "invoice-reported; location, insurance, title, and inspector verification not supplied",
                    "flag": "GC, architect, inspector, and lender must verify stored-material eligibility.",
                }
            )

    current_gross = current_work_total + stored_total
    earned_to_date = prior_total + current_gross
    retainage_to_date = _round_cents(Decimal(earned_to_date) * retainage_rate)
    prior_retainage = _round_cents(Decimal(prior_total) * retainage_rate)
    retainage = retainage_to_date - prior_retainage
    current_payment = current_gross - retainage
    invoice_progress = Decimal(earned_to_date) / Decimal(scheduled_total)

    claimed_checks: list[dict[str, Any]] = []
    for key, calculated in (
        ("claimed_current_gross_cents", current_gross),
        ("claimed_retainage_cents", retainage),
        ("claimed_payment_due_cents", current_payment),
    ):
        if pay_app.get(key) is None:
            continue
        claimed = _integer_cents(f"pay_app.{key}", pay_app[key])
        claimed_checks.append(
            {
                "field": key,
                "claimed_cents": claimed,
                "calculated_cents": calculated,
                "difference_cents": claimed - calculated,
                "passes": claimed == calculated,
            }
        )

    inspection_value = evidence.get("inspection_pct")
    if inspection_value is None:
        field_progress: dict[str, Any] = {
            "pct": None,
            "basis": "not field-verified; inspection_pct was not supplied",
        }
        progress_overbilling = None
    else:
        inspection_rate = _percentage("evidence.inspection_pct", inspection_value)
        field_progress = {
            "pct": float(inspection_rate * Decimal(100)),
            "basis": "field-verified percentage as reported by inspection evidence",
        }
        supported = _round_cents(Decimal(scheduled_total) * inspection_rate)
        installed_billed = prior_total + current_work_total
        excess = max(0, installed_billed - supported)
        progress_overbilling = {
            "flagged": excess > 0,
            "invoice_supported_installed_work_cents": installed_billed,
            "inspection_supported_cents": supported,
            "excess_cents": excess,
            "stored_materials_excluded_cents": stored_total,
            "basis": (
                "installed-work comparison only; current stored materials are reviewed "
                "separately and prior billing cannot be decomposed from supplied inputs"
            ),
        }

    line_excess = sum(row["over_scheduled_cents"] for row in line_audit)
    return {
        "line_audit": line_audit,
        "totals": {
            "scheduled_cents": scheduled_total,
            "previously_billed_cents": prior_total,
            "this_period_work_cents": current_work_total,
            "stored_materials_cents": stored_total,
            "current_gross_cents": current_gross,
            "retainage_cents": retainage,
            "prior_retainage_cents": prior_retainage,
            "retainage_to_date_cents": retainage_to_date,
            "current_payment_due_cents": current_payment,
            "earned_to_date_cents": earned_to_date,
            "balance_to_finish_cents": scheduled_total - earned_to_date,
            "basis": "invoice-supported arithmetic; not field-verified",
        },
        "retainage_pct": float(retainage_rate * Decimal(100)),
        "math_checks": claimed_checks,
        "math_check_passes": (
            all(check["passes"] for check in claimed_checks) if claimed_checks else None
        ),
        "math_check_status": "tested" if claimed_checks else "not_tested_no_claimed_totals",
        "financial_progress": {
            "pct": float(invoice_progress * Decimal(100)),
            "basis": "invoice-supported; not field-verified",
        },
        "field_progress": field_progress,
        "overbilling": {
            "flagged": line_excess > 0
            or bool(progress_overbilling and progress_overbilling["flagged"]),
            "over_scheduled_cents": line_excess,
            "versus_inspection": progress_overbilling,
        },
        "missing_lien_waivers": missing_waivers,
        "stored_materials_flags": stored_flags,
        "professional_review_flags": [
            "GC: certify the schedule of values, change orders, and stored materials.",
            "architect: certify pay-app eligibility and completed work where contracted.",
            "engineer: validate discipline work where the contract requires certification.",
            "inspector: field-verify progress; invoice support alone is not field verification.",
            "lender/title: validate lien waivers before disbursement.",
        ],
        "review_flags": {
            "gc_review_required": True,
            "architect_review_required": True,
            "engineer_review_required": True,
            "inspector_review_required": True,
        },
    }


__all__ = [
    "CX_DRAWS_TABLE",
    "CX_PROJECTS_TABLE",
    "ConstructionDrawStore",
    "DRAW_CURVES",
    "DrawStore",
    "audit_pay_app",
    "forecast_draws",
]
