"""Penny-exact capital-call forecasting from governed commitment inputs."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.config import CreConfig
from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.execution.guardrails import capital_guardrail


NEED_CATEGORIES = ("acquisitions", "capex", "reserves")


def _text(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _cents(value: Any, label: str, *, allow_zero: bool = True) -> int:
    """Accept only exact integer cents; floats are deliberately ambiguous."""

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


def _fraction(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a decimal or percentage")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a decimal or percentage") from exc
    if not number.is_finite():
        raise ValueError(f"{label} must be finite")
    normalized = number / Decimal(100) if number > 1 else number
    if normalized < 0 or normalized > 1:
        raise ValueError(f"{label} must be between 0 and 100 percent")
    return normalized


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FundCommitmentStore:
    """Own only the ``fund_commitments`` table in the shared cache database."""

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
            CREATE TABLE IF NOT EXISTS fund_commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                investor TEXT NOT NULL UNIQUE,
                committed_cents INTEGER NOT NULL,
                funded_cents INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                CHECK(length(trim(investor)) > 0),
                CHECK(committed_cents >= 0),
                CHECK(funded_cents >= 0),
                CHECK(funded_cents <= committed_cents)
            );
            CREATE INDEX IF NOT EXISTS idx_fund_commitments_investor
                ON fund_commitments(investor, id);
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

    def replace_inputs(
        self, commitments: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized: list[tuple[str, int, int]] = []
        seen: set[str] = set()
        for index, item in enumerate(commitments):
            if not isinstance(item, Mapping):
                raise ValueError(f"commitments[{index}] must be a mapping")
            investor = _text(item.get("investor"), f"commitments[{index}].investor")
            key = investor.casefold()
            if key in seen:
                raise ValueError(f"duplicate investor in commitments: {investor}")
            seen.add(key)
            committed = _cents(
                item.get("committed_cents"),
                f"commitments[{index}].committed_cents",
            )
            funded = _cents(
                item.get("funded_cents", 0),
                f"commitments[{index}].funded_cents",
            )
            if funded > committed:
                raise ValueError(
                    f"commitments[{index}].funded_cents cannot exceed committed_cents"
                )
            normalized.append((investor, committed, funded))

        now = _now()
        rows: list[dict[str, Any]] = []
        with self.connection() as connection:
            existing_rows = connection.execute(
                "SELECT id, investor FROM fund_commitments ORDER BY id"
            ).fetchall()
            existing_by_key = {
                str(row["investor"]).casefold(): row for row in existing_rows
            }
            supplied_keys = {investor.casefold() for investor, _, _ in normalized}
            for key, row in existing_by_key.items():
                if key not in supplied_keys:
                    connection.execute(
                        "DELETE FROM fund_commitments WHERE id=?", (int(row["id"]),)
                    )
            for investor, committed, funded in normalized:
                existing = existing_by_key.get(investor.casefold())
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO fund_commitments(
                            investor, committed_cents, funded_cents, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (investor, committed, funded, now),
                    )
                    row_id = int(cursor.lastrowid)
                else:
                    row_id = int(existing["id"])
                    connection.execute(
                        """
                        UPDATE fund_commitments
                        SET investor=?, committed_cents=?, funded_cents=?, updated_at=?
                        WHERE id=?
                        """,
                        (investor, committed, funded, now, row_id),
                    )
                row = connection.execute(
                    "SELECT * FROM fund_commitments WHERE id=?",
                    (row_id,),
                ).fetchone()
                assert row is not None
                rows.append(dict(row))
        return rows

    def all(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM fund_commitments ORDER BY investor COLLATE NOCASE, id"
            ).fetchall()
        return [dict(row) for row in rows]


def _pipeline_rows(
    pipeline_needs: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> list[dict[str, Any]]:
    if isinstance(pipeline_needs, Mapping):
        if "month" in pipeline_needs:
            raw_rows: list[Any] = [pipeline_needs]
        else:
            raw_rows = [
                {"month": month, **dict(value)}
                for month, value in pipeline_needs.items()
                if isinstance(value, Mapping)
            ]
            if len(raw_rows) != len(pipeline_needs):
                raise ValueError(
                    "pipeline_needs mapping values must be acquisition/capex/reserve mappings"
                )
    elif isinstance(pipeline_needs, Sequence) and not isinstance(
        pipeline_needs, (str, bytes, bytearray)
    ):
        raw_rows = list(pipeline_needs)
    else:
        raise ValueError("pipeline_needs must be a list or month-keyed mapping")

    rows: list[dict[str, Any]] = []
    seen_months: set[str] = set()
    for index, item in enumerate(raw_rows):
        if not isinstance(item, Mapping):
            raise ValueError(f"pipeline_needs[{index}] must be a mapping")
        month = _text(item.get("month"), f"pipeline_needs[{index}].month")
        if month in seen_months:
            raise ValueError(f"duplicate pipeline month: {month}")
        seen_months.add(month)
        categories: dict[str, int] = {}
        for category in NEED_CATEGORIES:
            raw = item.get(f"{category}_cents", item.get(category, 0))
            categories[f"{category}_cents"] = _cents(
                raw, f"pipeline_needs[{index}].{category}_cents"
            )
        rows.append(
            {
                "month": month,
                **categories,
                "source_ref": {
                    "kind": "caller_input",
                    "field": "pipeline_needs",
                    "index": index,
                },
            }
        )
    rows.sort(key=lambda row: row["month"])
    return rows


def _allocate_cents(
    amount_cents: int,
    remaining_by_id: Mapping[int, int],
    labels_by_id: Mapping[int, str],
) -> dict[int, int]:
    """Pro-rata largest-remainder allocation with exact capacity and sum invariants."""

    total_capacity = sum(remaining_by_id.values())
    allocatable = min(amount_cents, total_capacity)
    if allocatable == 0 or total_capacity == 0:
        return {row_id: 0 for row_id in remaining_by_id}
    allocations = {
        row_id: allocatable * capacity // total_capacity
        for row_id, capacity in remaining_by_id.items()
    }
    remainders = {
        row_id: allocatable * capacity % total_capacity
        for row_id, capacity in remaining_by_id.items()
    }
    pennies_left = allocatable - sum(allocations.values())
    order = sorted(
        remaining_by_id,
        key=lambda row_id: (
            -remainders[row_id],
            labels_by_id[row_id].casefold(),
            row_id,
        ),
    )
    for row_id in order[:pennies_left]:
        allocations[row_id] += 1
    if sum(allocations.values()) != allocatable:
        raise ArithmeticError("capital-call penny allocation did not balance")
    if any(allocations[row_id] > remaining_by_id[row_id] for row_id in allocations):
        raise ArithmeticError("capital-call allocation exceeded an unfunded commitment")
    return allocations


def forecast_capital_calls(
    pipeline_needs: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    commitments: Sequence[Mapping[str, Any]] | None = None,
    *,
    gp_coinvest_pct: Any = 0,
    governing_docs: Mapping[str, Any] | str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Forecast calls without recording forecast amounts as actual funded capital.

    Supplied commitments are an authoritative current snapshot: matching governed
    rows are updated and omitted investors are retired from the owned table.  When
    ``commitments`` is omitted, existing governed rows are used.  The schedule is
    deterministic, penny exact, and bounded by each investor's unfunded amount.
    """

    reject_unsubstantiated_performance_claims(
        pipeline_needs,
        commitments,
        governing_docs,
    )
    store = FundCommitmentStore(db_path, config=config)
    if commitments is not None:
        if isinstance(commitments, (str, bytes, bytearray)) or not isinstance(
            commitments, Sequence
        ):
            raise ValueError("commitments must be a list of mappings")
        commitment_rows = store.replace_inputs(commitments)
    else:
        commitment_rows = store.all()
    pipeline = _pipeline_rows(pipeline_needs)
    gp_fraction = _fraction(gp_coinvest_pct, "gp_coinvest_pct")

    remaining = {
        int(row["id"]): int(row["committed_cents"]) - int(row["funded_cents"])
        for row in commitment_rows
    }
    labels = {int(row["id"]): str(row["investor"]) for row in commitment_rows}
    initial_unfunded = dict(remaining)
    called_by_id = {row_id: 0 for row_id in remaining}
    schedule: list[dict[str, Any]] = []
    total_gp = 0
    total_gap = 0

    for need in pipeline:
        gross = sum(int(need[f"{category}_cents"]) for category in NEED_CATEGORIES)
        gp_call = int(
            (Decimal(gross) * gp_fraction).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        lp_need = gross - gp_call
        allocations = _allocate_cents(lp_need, remaining, labels)
        investor_lines: list[dict[str, Any]] = []
        for row in sorted(
            commitment_rows,
            key=lambda item: (str(item["investor"]).casefold(), int(item["id"])),
        ):
            row_id = int(row["id"])
            call = allocations[row_id]
            remaining[row_id] -= call
            called_by_id[row_id] += call
            investor_lines.append(
                {
                    "investor": row["investor"],
                    "commitment_id": row_id,
                    "call_cents": call,
                    "projected_unfunded_cents": remaining[row_id],
                    "source": {"table": "fund_commitments", "id": row_id},
                }
            )
        lp_call = sum(line["call_cents"] for line in investor_lines)
        gap = lp_need - lp_call
        if lp_call + gap + gp_call != gross:
            raise ArithmeticError("capital-call schedule did not balance to gross need")
        total_gp += gp_call
        total_gap += gap
        schedule.append(
            {
                "month": need["month"],
                "needs_cents": {
                    category: int(need[f"{category}_cents"])
                    for category in NEED_CATEGORIES
                },
                "gross_need_cents": gross,
                "gp_coinvest_cents": gp_call,
                "gp_coinvest_source_ref": {
                    "kind": "caller_input",
                    "field": "gp_coinvest_pct",
                },
                "lp_call_cents": lp_call,
                "unfunded_gap_cents": gap,
                "investor_calls": investor_lines,
                "source_ref": need["source_ref"],
                "balance_check_cents": gross - gp_call - lp_call - gap,
            }
        )

    investor_tracking: list[dict[str, Any]] = []
    for row in sorted(
        commitment_rows,
        key=lambda item: (str(item["investor"]).casefold(), int(item["id"])),
    ):
        row_id = int(row["id"])
        investor_tracking.append(
            {
                "investor": row["investor"],
                "commitment_id": row_id,
                "committed_cents": int(row["committed_cents"]),
                "funded_cents": int(row["funded_cents"]),
                "opening_unfunded_cents": initial_unfunded[row_id],
                "forecast_call_cents": called_by_id[row_id],
                "projected_funded_cents": int(row["funded_cents"])
                + called_by_id[row_id],
                "projected_unfunded_cents": remaining[row_id],
                "source": {"table": "fund_commitments", "id": row_id},
            }
        )

    if governing_docs is None:
        remedy = {
            "status": "UNRESOLVED",
            "note": (
                "No default remedy is modeled because governing documents were not "
                "provided. Obtain the executed fund/JV documents and review with fund "
                "and securities counsel before issuing or enforcing a call."
            ),
            "source": None,
        }
    else:
        if isinstance(governing_docs, Mapping):
            supplied_note = governing_docs.get("default_remedy") or governing_docs.get(
                "capital_call_remedies"
            )
            source_label = governing_docs.get("source") or governing_docs.get("source_label")
        else:
            supplied_note = governing_docs
            source_label = "caller-supplied governing_docs"
        remedy = {
            "status": "CALLER-SUPPLIED — NOT LEGALLY VALIDATED",
            "note": _text(supplied_note, "governing_docs default remedy"),
            "source": _text(source_label, "governing_docs source label"),
        }

    return {
        "schedule": schedule,
        "investor_tracking": investor_tracking,
        "totals_cents": {
            "gross_need": sum(item["gross_need_cents"] for item in schedule),
            "gp_coinvest": total_gp,
            "lp_calls": sum(item["lp_call_cents"] for item in schedule),
            "unfunded_gap": total_gap,
        },
        "gp_coinvest_pct": str(gp_fraction),
        "gp_coinvest_source_ref": {
            "kind": "caller_input",
            "field": "gp_coinvest_pct",
        },
        "allocation_method": (
            "Pro rata to then-remaining unfunded commitments; integer floors followed "
            "by deterministic largest-remainder pennies. Forecast calls do not mutate "
            "actual funded_cents."
        ),
        "distribution_forecast": {
            "status": "NOT MODELED",
            "reason": "No governed distribution inputs were supplied to this call forecast.",
        },
        "default_remedy": remedy,
        "counsel_flag": (
            "Review call authority, notice, timing, GP co-invest, default remedies, "
            "waivers, and securities-law communications with fund/securities counsel."
        ),
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Have fund/securities counsel approve the governing-document interpretation "
            "and call notice before sending funding instructions or accepting money."
        ),
    }


__all__ = ["FundCommitmentStore", "forecast_capital_calls"]
