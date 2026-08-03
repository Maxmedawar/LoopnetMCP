"""Governed fund marks, cash flows, and penny-exact NAV reporting."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.config import CreConfig
from cre_mcp.execution.guardrails import capital_guardrail


MARK_SOURCES = frozenset({"appraisal", "broker_opinion", "model", "cost"})
FLOW_TYPES = frozenset({"contribution", "distribution", "fee"})
FLOW_ATTRIBUTIONS = frozenset({"capital", "income", "fee", "unclassified"})
_PERIOD = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$")


def _text(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _period(value: Any) -> str:
    normalized = _text(value, "period").upper()
    if not _PERIOD.fullmatch(normalized):
        raise ValueError("period must be YYYY-MM or YYYY-Q1 through YYYY-Q4")
    return normalized


def _period_kind(value: str) -> str:
    return "quarter" if "-Q" in value else "month"


def _period_key(value: str) -> int:
    year_text, subperiod = value.split("-", 1)
    year = int(year_text)
    if subperiod.startswith("Q"):
        return year * 4 + int(subperiod[1:])
    return year * 12 + int(subperiod)


def _cents(value: Any, label: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer number of cents")
    if isinstance(value, int):
        amount = value
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            amount = int(stripped)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be an integer number of cents") from exc
        if str(amount) != stripped and stripped != f"+{amount}":
            raise ValueError(f"{label} must be an integer number of cents")
    else:
        raise ValueError(f"{label} must be an integer number of cents")
    if amount < 0 or (amount == 0 and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"{label} must be {qualifier}")
    return amount


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FundNavStore:
    """Own only ``fund_marks`` and ``fund_flows`` in the shared cache DB."""

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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fund_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                period TEXT NOT NULL,
                value_cents INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_label TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                CHECK(length(trim(asset)) > 0),
                CHECK(value_cents >= 0),
                CHECK(source IN ('appraisal', 'broker_opinion', 'model', 'cost')),
                CHECK(length(trim(source_label)) > 0)
            );
            CREATE INDEX IF NOT EXISTS idx_fund_marks_period_asset
                ON fund_marks(period, asset, id);

            CREATE TABLE IF NOT EXISTS fund_flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                type TEXT NOT NULL,
                cents INTEGER NOT NULL,
                investor TEXT,
                source_label TEXT NOT NULL,
                attribution TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                CHECK(type IN ('contribution', 'distribution', 'fee')),
                CHECK(cents >= 0),
                CHECK(investor IS NULL OR length(trim(investor)) > 0),
                CHECK(length(trim(source_label)) > 0),
                CHECK(attribution IN ('capital', 'income', 'fee', 'unclassified'))
            );
            CREATE INDEX IF NOT EXISTS idx_fund_flows_period_investor
                ON fund_flows(period, investor, id);
            """
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def insert_mark(
        self,
        *,
        asset: str,
        period: str,
        value_cents: int,
        source: str,
        source_label: str,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fund_marks(
                    asset, period, value_cents, source, source_label, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (asset, period, value_cents, source, source_label, _now()),
            )
            row = connection.execute(
                "SELECT * FROM fund_marks WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def insert_flow(
        self,
        *,
        period: str,
        flow_type: str,
        cents: int,
        investor: str | None,
        source_label: str,
        attribution: str,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fund_flows(
                    period, type, cents, investor, source_label, attribution, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    period,
                    flow_type,
                    cents,
                    investor,
                    source_label,
                    attribution,
                    _now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM fund_flows WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def report_rows(
        self, period: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None, list[dict[str, Any]]]:
        with self.connection() as connection:
            all_marks = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM fund_marks ORDER BY id"
                ).fetchall()
            ]
            all_flows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM fund_flows ORDER BY id"
                ).fetchall()
            ]
        kinds = {
            _period_kind(str(row["period"])) for row in [*all_marks, *all_flows]
        }
        kinds.add(_period_kind(period))
        if len(kinds) > 1:
            raise ValueError(
                "mixed YYYY-MM and YYYY-Q# reporting conventions are not comparable; "
                "use one period convention in fund_marks and fund_flows"
            )
        target_key = _period_key(period)
        current_rows = [row for row in all_marks if row["period"] == period]
        flow_rows = [
            row for row in all_flows if _period_key(str(row["period"])) <= target_key
        ]
        prior_periods = {
            str(row["period"])
            for row in all_marks
            if _period_key(str(row["period"])) < target_key
        }
        prior_period = (
            max(prior_periods, key=_period_key) if prior_periods else None
        )
        prior_rows = [
            row for row in all_marks if row["period"] == prior_period
        ]
        return (
            sorted(
                current_rows,
                key=lambda row: (str(row["asset"]).casefold(), int(row["id"])),
            ),
            sorted(
                flow_rows,
                key=lambda row: (_period_key(str(row["period"])), int(row["id"])),
            ),
            prior_period,
            sorted(
                prior_rows,
                key=lambda row: (str(row["asset"]).casefold(), int(row["id"])),
            ),
        )

    def commitment_basis(self) -> tuple[int, list[dict[str, Any]]]:
        """Read calls-owned rows without creating or changing that table."""

        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fund_commitments'"
            ).fetchone()
            if exists is None:
                return 0, []
            rows = connection.execute(
                """
                SELECT id, investor, committed_cents
                FROM fund_commitments ORDER BY investor COLLATE NOCASE, id
                """
            ).fetchall()
        decoded = [dict(row) for row in rows]
        return sum(int(row["committed_cents"]) for row in decoded), decoded


def _governed_row(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["source_ref"] = {"table": table, "id": int(row["id"])}
    return result


def record_fund_mark(
    asset: str,
    period: str,
    value_cents: int,
    source: str,
    *,
    source_label: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Record a caller-supplied valuation mark; never estimate or backfill one."""

    reject_unsubstantiated_performance_claims(asset, source, source_label)
    normalized_source = _text(source, "source").casefold()
    if normalized_source not in MARK_SOURCES:
        raise ValueError(
            "source must be appraisal, broker_opinion, model, or cost"
        )
    row = FundNavStore(db_path, config=config).insert_mark(
        asset=_text(asset, "asset"),
        period=_period(period),
        value_cents=_cents(value_cents, "value_cents"),
        source=normalized_source,
        source_label=(
            _text(source_label, "source_label")
            if source_label is not None
            else normalized_source
        ),
    )
    return {
        **_governed_row("fund_marks", row),
        "valuation_status": "CALLER-SUPPLIED INPUT — NOT INDEPENDENTLY VALIDATED",
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Have the fund administrator/CPA validate the mark policy and have counsel "
            "approve investor-facing use and disclosures."
        ),
    }


def record_fund_flow(
    period: str,
    flow_type: str | None = None,
    cents: int | None = None,
    *,
    type: str | None = None,
    investor: str | None = None,
    source_label: str = "caller-supplied fund flow",
    attribution: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Record a contribution, distribution, or fee as exact integer cents."""

    reject_unsubstantiated_performance_claims(
        flow_type,
        type,
        investor,
        source_label,
        attribution,
    )
    supplied_type = flow_type if flow_type is not None else type
    normalized_type = _text(supplied_type, "flow_type").casefold()
    if normalized_type not in FLOW_TYPES:
        raise ValueError("flow_type must be contribution, distribution, or fee")
    if flow_type is not None and type is not None and flow_type != type:
        raise ValueError("flow_type and type cannot conflict")
    default_attribution = {
        "contribution": "capital",
        "distribution": "unclassified",
        "fee": "fee",
    }[normalized_type]
    normalized_attribution = _text(
        attribution or default_attribution, "attribution"
    ).casefold()
    if normalized_attribution not in FLOW_ATTRIBUTIONS:
        raise ValueError(
            "attribution must be capital, income, fee, or unclassified"
        )
    if normalized_type == "contribution" and normalized_attribution != "capital":
        raise ValueError("contributions must use capital attribution")
    if normalized_type == "fee" and normalized_attribution != "fee":
        raise ValueError("fee flows must use fee attribution")
    normalized_investor = (
        _text(investor, "investor") if investor is not None else None
    )
    row = FundNavStore(db_path, config=config).insert_flow(
        period=_period(period),
        flow_type=normalized_type,
        cents=_cents(cents, "cents"),
        investor=normalized_investor,
        source_label=_text(source_label, "source_label"),
        attribution=normalized_attribution,
    )
    return {
        **_governed_row("fund_flows", row),
        "classification_status": (
            "CALLER-CLASSIFIED"
            if attribution is not None
            else "DEFAULT CLASSIFICATION; distributions remain unclassified"
        ),
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Reconcile this flow to bank, administrator, and governing-document records "
            "before using it in an investor statement."
        ),
    }


def _unique_by_asset(
    rows: list[dict[str, Any]], *, period: str
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["asset"]).casefold()
        if key in selected:
            ids = [int(selected[key]["id"]), int(row["id"])]
            raise ValueError(
                f"duplicate marks for asset={row['asset']!r}, period={period}: ids={ids}; "
                "no supersession rule was supplied, so NAV fails closed"
            )
        selected[key] = row
    return selected


def _fee_accrual(
    store: FundNavStore,
    *,
    convention: str,
    management_fee_bps: int | None,
    fee_period_months: int,
    fee_basis_cents: int | None,
    fee_basis_source: str | None,
    management_fee_source: str | None,
    recorded_fee_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    recorded_fee_cents = sum(int(row["cents"]) for row in recorded_fee_rows)
    result: dict[str, Any] = {
        "convention": convention,
        "recorded_fee_cents": recorded_fee_cents,
        "recorded_fee_sources": [
            {"table": "fund_flows", "id": int(row["id"])}
            for row in recorded_fee_rows
        ],
        "calculated_accrual_cents": None,
        "annual_management_fee_bps": management_fee_bps,
        "fee_period_months": None,
        "basis_cents": None,
        "basis_sources": [],
        "terms_source": None,
        "nav_treatment": (
            "The calculated accrual is informational and is not automatically deducted. "
            "cash_cents and liabilities_cents remain caller-supplied; include any unpaid "
            "fee accrual in liabilities_cents exactly once."
        ),
    }
    if management_fee_bps is None:
        result["calculation_note"] = (
            "No fee rate was supplied; only governed fund_flows fee rows are reported."
        )
        return result
    terms_source = _text(management_fee_source, "management_fee_source")
    bps = _cents(management_fee_bps, "management_fee_bps")
    if bps > 10_000:
        raise ValueError("management_fee_bps cannot exceed 10000")
    months = _cents(fee_period_months, "fee_period_months", allow_zero=False)
    if months > 12:
        raise ValueError("fee_period_months cannot exceed 12")

    if fee_basis_cents is not None:
        basis = _cents(fee_basis_cents, "fee_basis_cents")
        basis_sources = [
            {
                "kind": "caller_input",
                "label": _text(fee_basis_source, "fee_basis_source"),
            }
        ]
    elif convention == "committed":
        basis, commitment_rows = store.commitment_basis()
        if not commitment_rows:
            raise ValueError(
                "committed fee convention requires fund_commitments rows or an explicit "
                "fee_basis_cents and fee_basis_source"
            )
        basis_sources = [
            {"table": "fund_commitments", "id": int(row["id"])}
            for row in commitment_rows
        ]
    else:
        raise ValueError(
            "invested fee convention requires caller-supplied fee_basis_cents and "
            "fee_basis_source; invested capital is never inferred from NAV"
        )
    calculated = int(
        (
            Decimal(basis)
            * Decimal(bps)
            * Decimal(months)
            / Decimal(120_000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    result.update(
        {
            "annual_management_fee_bps": bps,
            "fee_period_months": months,
            "terms_source": {"kind": "caller_input", "label": terms_source},
            "basis_cents": basis,
            "basis_sources": basis_sources,
            "calculated_accrual_cents": calculated,
            "formula": "round_half_up(basis_cents * annual_bps * months / 120000)",
        }
    )
    return result


def nav_report(
    period: str,
    cash_cents: int,
    liabilities_cents: int,
    *,
    cash_source: str | None = None,
    liabilities_source: str | None = None,
    fee_convention: str = "committed",
    management_fee_bps: int | None = None,
    fee_period_months: int = 3,
    fee_basis_cents: int | None = None,
    fee_basis_source: str | None = None,
    management_fee_source: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Build NAV and arithmetic attribution entirely from governed rows and inputs."""

    reject_unsubstantiated_performance_claims(
        cash_source,
        liabilities_source,
        fee_convention,
        fee_basis_source,
        management_fee_source,
    )
    normalized_period = _period(period)
    cash = _cents(cash_cents, "cash_cents")
    liabilities = _cents(liabilities_cents, "liabilities_cents")
    cash_label = _text(cash_source, "cash_source")
    liabilities_label = _text(liabilities_source, "liabilities_source")
    convention = _text(fee_convention, "fee_convention").casefold()
    if convention not in {"committed", "invested"}:
        raise ValueError("fee_convention must be committed or invested")

    store = FundNavStore(db_path, config=config)
    mark_rows, flow_rows, prior_period, prior_rows = store.report_rows(normalized_period)
    current_marks = _unique_by_asset(mark_rows, period=normalized_period)
    prior_marks = _unique_by_asset(
        prior_rows, period=prior_period or "NO PRIOR PERIOD"
    )
    if not current_marks:
        raise ValueError(
            f"no caller-supplied fund_marks exist for period {normalized_period}"
        )

    selected_marks = [
        _governed_row("fund_marks", row)
        for _, row in sorted(current_marks.items(), key=lambda item: item[0].casefold())
    ]
    marks_cents = sum(int(row["value_cents"]) for row in current_marks.values())
    nav_cents = marks_cents + cash - liabilities
    nav_status = (
        "NEGATIVE NAV — DISTRESS/ADMINISTRATOR REVIEW REQUIRED"
        if nav_cents < 0
        else "NONNEGATIVE ARITHMETIC NAV — NOT INDEPENDENTLY VALIDATED"
    )

    through_period_flows = [
        _governed_row("fund_flows", row) for row in flow_rows
    ]
    current_flows = [row for row in flow_rows if row["period"] == normalized_period]
    fee_rows = [row for row in current_flows if row["type"] == "fee"]
    management_fee = _fee_accrual(
        store,
        convention=convention,
        management_fee_bps=management_fee_bps,
        fee_period_months=fee_period_months,
        fee_basis_cents=fee_basis_cents,
        fee_basis_source=fee_basis_source,
        management_fee_source=management_fee_source,
        recorded_fee_rows=fee_rows,
    )

    investors = sorted(
        {
            str(row["investor"])
            for row in flow_rows
            if row["investor"] is not None
        },
        key=str.casefold,
    )
    capital_accounts: list[dict[str, Any]] = []
    for investor in investors:
        rows = [row for row in flow_rows if row["investor"] == investor]
        contributions = sum(
            int(row["cents"]) for row in rows if row["type"] == "contribution"
        )
        distributions = sum(
            int(row["cents"]) for row in rows if row["type"] == "distribution"
        )
        fees = sum(int(row["cents"]) for row in rows if row["type"] == "fee")
        capital_accounts.append(
            {
                "investor": investor,
                "contributions_cents": contributions,
                "distributions_cents": distributions,
                "fees_cents": fees,
                "net_cash_activity_cents": contributions - distributions - fees,
                "source_refs": [
                    {"table": "fund_flows", "id": int(row["id"])} for row in rows
                ],
                "scope": (
                    "Cash-activity capital-account statement only. NAV/profit/loss is not "
                    "allocated because governing allocation rules were not supplied."
                ),
            }
        )

    fund_level_rows = [row for row in flow_rows if row["investor"] is None]
    cumulative_distributions = sum(
        int(row["cents"]) for row in flow_rows if row["type"] == "distribution"
    )
    income_rows = [
        row
        for row in current_flows
        if row["type"] == "distribution" and row["attribution"] == "income"
    ]
    income = sum(int(row["cents"]) for row in income_rows)
    fees = sum(int(row["cents"]) for row in fee_rows)

    asset_names = sorted(set(current_marks) | set(prior_marks))
    mark_changes: list[dict[str, Any]] = []
    appreciation = 0
    for asset in asset_names:
        current = current_marks.get(asset)
        prior = prior_marks.get(asset)
        current_value = int(current["value_cents"]) if current is not None else 0
        prior_value = int(prior["value_cents"]) if prior is not None else 0
        change = current_value - prior_value
        appreciation += change
        mark_changes.append(
            {
                "asset": str((current or prior)["asset"]),
                "current_value_cents": current_value,
                "prior_value_cents": prior_value,
                "change_cents": change,
                "current_source_ref": (
                    {"table": "fund_marks", "id": int(current["id"])}
                    if current is not None
                    else None
                ),
                "prior_source_ref": (
                    {"table": "fund_marks", "id": int(prior["id"])}
                    if prior is not None
                    else None
                ),
            }
        )
    net_attribution = income + appreciation - fees
    attribution_check = net_attribution - (income + appreciation - fees)

    unanswered: list[str] = []
    unclassified_distribution_rows = [
        row
        for row in current_flows
        if row["type"] == "distribution" and row["attribution"] == "unclassified"
    ]
    if unclassified_distribution_rows:
        unanswered.append(
            "Classify current distributions as income or capital from administrator records."
        )
    if prior_period is None:
        unanswered.append(
            "No prior mark period exists; mark change uses a zero arithmetic baseline and "
            "must not be described as accounting or appraisal appreciation."
        )
    if any(current_marks.get(asset) is None or prior_marks.get(asset) is None for asset in asset_names):
        unanswered.append(
            "Portfolio composition changed or an asset lacks a comparable-period mark; "
            "the mark-change component is not pure appreciation."
        )
    unanswered.append(
        "Allocate NAV and profit/loss to investor capital accounts under administrator- "
        "and counsel-approved governing-document rules."
    )

    nav_sources = [row["source_ref"] for row in selected_marks] + [
        {"kind": "caller_input", "field": "cash_cents", "label": cash_label},
        {
            "kind": "caller_input",
            "field": "liabilities_cents",
            "label": liabilities_label,
        },
    ]
    return {
        "period": normalized_period,
        "nav_cents": nav_cents,
        "nav_status": nav_status,
        "nav_formula": {
            "marks_cents": marks_cents,
            "cash_cents": cash,
            "liabilities_cents": liabilities,
            "formula": "marks_cents + cash_cents - liabilities_cents",
            "balance_check_cents": nav_cents - marks_cents - cash + liabilities,
            "sources": nav_sources,
        },
        "marks": selected_marks,
        "cash_input": {
            "cents": cash,
            "source": {"kind": "caller_input", "label": cash_label},
        },
        "liabilities_input": {
            "cents": liabilities,
            "source": {"kind": "caller_input", "label": liabilities_label},
        },
        "management_fee": management_fee,
        "realized_unrealized": {
            "realized_cash_distributions_cents": cumulative_distributions,
            "unrealized_nav_cents": nav_cents,
            "combined_value_cents": cumulative_distributions + nav_cents,
            "classification": (
                "Cash-realized distributions versus current marked NAV; these are value "
                "buckets, not realized/unrealized tax gains."
            ),
            "distribution_source_refs": [
                {"table": "fund_flows", "id": int(row["id"])}
                for row in flow_rows
                if row["type"] == "distribution"
            ],
        },
        "capital_accounts": capital_accounts,
        "fund_level_flows": [
            _governed_row("fund_flows", row) for row in fund_level_rows
        ],
        "return_attribution": {
            "income_cents": income,
            "appreciation_cents": appreciation,
            "fees_cents": fees,
            "net_attributed_return_cents": net_attribution,
            "sum_check_cents": attribution_check,
            "income_source_refs": [
                {"table": "fund_flows", "id": int(row["id"])} for row in income_rows
            ],
            "fee_source_refs": [
                {"table": "fund_flows", "id": int(row["id"])} for row in fee_rows
            ],
            "mark_changes": mark_changes,
            "prior_mark_period": prior_period,
            "labels": {
                "income": "Only distributions explicitly caller-classified as income.",
                "appreciation": (
                    "Arithmetic change in caller-supplied marks, using zero for a missing "
                    "asset-period. It is not a valuation, appraisal conclusion, or pure "
                    "appreciation when portfolio composition changes."
                ),
                "fees": "Governed current-period fund_flows rows of type fee.",
            },
        },
        "governed_flows_through_period": through_period_flows,
        "unanswered_questions": unanswered,
        "valuation_warning": (
            "All NAV marks are caller-supplied inputs with recorded source labels. No "
            "valuation was invented, inferred, or independently validated."
        ),
        "counsel_flag": (
            "Review valuation policy, fee basis, allocation provisions, side letters, "
            "and investor-facing presentation with fund/securities counsel and the fund "
            "administrator/CPA."
        ),
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Reconcile the report to administrator books and source documents, then obtain "
            "fund/securities-counsel approval before investor distribution."
        ),
    }


__all__ = [
    "FLOW_ATTRIBUTIONS",
    "FLOW_TYPES",
    "FundNavStore",
    "MARK_SOURCES",
    "nav_report",
    "record_fund_flow",
    "record_fund_mark",
]
