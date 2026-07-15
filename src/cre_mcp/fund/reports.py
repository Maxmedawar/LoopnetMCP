"""Source-governed quarterly investor-report assembly.

This module owns no tables.  It reads the fund tables in the shared cache database
without altering them and refuses to manufacture zeroes, NAV, or performance claims
when governed rows are absent.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.config import CreConfig
from cre_mcp.execution.guardrails import capital_guardrail

_KNOWN_TABLES = ("fund_marks", "fund_flows", "fund_commitments")
_ID_COLUMNS = {
    "fund_marks": ("mark_id", "id"),
    "fund_flows": ("flow_id", "id"),
    "fund_commitments": ("commitment_id", "id"),
}
_MARK_SOURCES = frozenset({"appraisal", "broker_opinion", "model", "cost"})
_FLOW_TYPES = frozenset({"contribution", "distribution", "fee"})
_PERIOD_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$")


def _resolve_db_path(
    db_path: str | Path | CreConfig | None = None,
    *,
    config: CreConfig | None = None,
) -> Path:
    selected: str | Path | CreConfig | None = db_path if db_path is not None else config
    if isinstance(selected, CreConfig):
        path = selected.cache_db_path
    elif selected is None:
        path = CreConfig().cache_db_path
    else:
        path = Path(selected)
    return Path(path).expanduser()


def _period(value: Any) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not normalized:
        raise ValueError("period cannot be blank")
    if len(normalized) > 80 or any(ord(character) < 32 for character in normalized):
        raise ValueError("period is invalid")
    reject_unsubstantiated_performance_claims({"period": normalized})
    if not _PERIOD_PATTERN.fullmatch(normalized):
        raise ValueError("period must be YYYY-MM or YYYY-Q1 through YYYY-Q4")
    return normalized


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    dollars, remainder = divmod(absolute, 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _read_rows(
    connection: sqlite3.Connection,
    table: str,
    *,
    period: str | None = None,
) -> tuple[list[sqlite3.Row], list[str], list[str]]:
    info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = [str(row[1]) for row in info]
    primary_keys = [
        str(row[1])
        for row in sorted(info, key=lambda item: int(item[5]))
        if int(row[5]) > 0
    ]
    where = ""
    params: tuple[Any, ...] = ()
    if period is not None and "period" in columns:
        where = ' WHERE "period" = ?'
        params = (period,)
    try:
        rows = connection.execute(
            f'SELECT rowid AS "__governed_rowid__", * FROM "{table}"{where}',
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        rows = connection.execute(f'SELECT * FROM "{table}"{where}', params).fetchall()
    return rows, columns, primary_keys


def _row_id(
    table: str,
    row: sqlite3.Row,
    primary_keys: list[str],
) -> Any:
    keys = set(row.keys())
    for column in _ID_COLUMNS[table]:
        if column in keys and row[column] is not None:
            return row[column]
    if "__governed_rowid__" in keys and row["__governed_rowid__"] is not None:
        return row["__governed_rowid__"]
    if primary_keys:
        values = {column: row[column] for column in primary_keys}
        if all(value is not None for value in values.values()):
            return values
    raise ValueError(f"{table} contains a row without a stable row id")


def _ref(
    table: str,
    row: sqlite3.Row,
    primary_keys: list[str],
    *columns: str,
) -> dict[str, Any]:
    return {
        "table": table,
        "id": _row_id(table, row, primary_keys),
        "columns": list(columns),
    }


def _cent_value(row: sqlite3.Row, column: str) -> int | None:
    if column not in row.keys():
        return None
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _figure(
    key: str,
    label: str,
    value_cents: int,
    source_refs: Iterable[dict[str, Any]],
    formula: str,
) -> dict[str, Any]:
    refs = list(source_refs)
    if not refs:
        raise ValueError(f"figure {key} has no governed source rows")
    return {
        "key": key,
        "label": label,
        "value_cents": int(value_cents),
        "display": _money(int(value_cents)),
        "source_refs": refs,
        "formula": formula,
    }


def _fact(figure: dict[str, Any]) -> dict[str, Any]:
    return {
        "figure_key": figure["key"],
        "value_cents": figure["value_cents"],
        "display": figure["display"],
        "source_refs": list(figure["source_refs"]),
    }


def _base_report(period: str, path: Path) -> dict[str, Any]:
    return {
        "period": period,
        "report_status": "DRAFT - GOVERNED FACT ASSEMBLY FOR COUNSEL REVIEW",
        "source_database": str(path),
        "figures": [],
        "portfolio_marks": [],
        "period_flows": [],
        "commitment_balances": [],
        "narrative": [],
        "unanswered_questions": [],
        "data_quality_flags": [],
        "provenance_policy": (
            "Every displayed amount cites each contributing governed table row. "
            "Missing rows are reported as unanswered questions, never filled with zero."
        ),
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "This is a template-only draft assembled from governed rows. Fund counsel, "
            "the administrator, and the responsible accounting professional must verify "
            "the report, offering-document conventions, disclosures, and recipient list "
            "before circulation."
        ),
    }


def _append_mark_data(
    report: dict[str, Any],
    rows: list[sqlite3.Row],
    columns: list[str],
    primary_keys: list[str],
    period: str,
) -> None:
    required = {"asset", "period", "value_cents", "source"}
    if not required.issubset(columns):
        missing = ", ".join(sorted(required - set(columns)))
        report["unanswered_questions"].append(
            f"fund_marks lacks required governed columns ({missing}); no mark figures were stated."
        )
        return

    valid: list[tuple[sqlite3.Row, int, dict[str, Any]]] = []
    asset_counts: Counter[str] = Counter()
    for row in rows:
        cents = _cent_value(row, "value_cents")
        asset = str(row["asset"] or "").strip()
        source = str(row["source"] or "").strip().casefold()
        try:
            source_columns = ["asset", "period", "value_cents", "source"]
            if "source_label" in columns:
                source_columns.append("source_label")
            ref = _ref(
                "fund_marks", row, primary_keys, *source_columns
            )
        except ValueError as exc:
            report["data_quality_flags"].append(str(exc))
            continue
        if not asset or cents is None or cents < 0 or source not in _MARK_SOURCES:
            report["data_quality_flags"].append(
                f"Excluded invalid fund_marks row {ref['id']}; asset, nonnegative integer "
                "value_cents, and an allowed source label are required."
            )
            continue
        value = _figure(
            f"asset_mark:{ref['id']}",
            f"{asset} governed asset mark",
            cents,
            [ref],
            "fund_marks.value_cents for the cited row",
        )
        report["portfolio_marks"].append(
            {
                "asset": asset,
                "period": period,
                "valuation_source_label": source,
                "governed_source_label": (
                    str(row["source_label"])
                    if "source_label" in columns and row["source_label"] is not None
                    else source
                ),
                "value": value,
                "source_ref": ref,
            }
        )
        valid.append((row, cents, ref))
        asset_counts[asset.casefold()] += 1

    if not valid:
        report["unanswered_questions"].append(
            f"No valid governed fund_marks rows exist for {period}; no asset-mark total or NAV was inferred."
        )
        return
    duplicates = sorted(asset for asset, count in asset_counts.items() if count > 1)
    if duplicates:
        report["unanswered_questions"].append(
            "Multiple governed mark rows exist for the same asset and period; resolve which "
            "row controls before stating an aggregate asset-mark total."
        )
        return
    total = _figure(
        "gross_asset_marks_cents",
        "Gross governed asset marks",
        sum(cents for _, cents, _ in valid),
        [ref for _, _, ref in valid],
        "sum(fund_marks.value_cents) for cited period rows; no cash or liabilities included",
    )
    report["figures"].append(total)
    report["narrative"].append(
        {
            "template_id": "governed_asset_marks",
            "text": f"For {period}, governed asset-mark rows total {total['display']}.",
            "facts": [_fact(total)],
            "limitations": (
                "This is not NAV. Valuation source labels are reproduced from fund_marks; "
                "no valuation was generated by this report."
            ),
        }
    )


def _append_flow_data(
    report: dict[str, Any],
    rows: list[sqlite3.Row],
    columns: list[str],
    primary_keys: list[str],
    period: str,
) -> None:
    required = {"period", "type", "cents"}
    if not required.issubset(columns):
        missing = ", ".join(sorted(required - set(columns)))
        report["unanswered_questions"].append(
            f"fund_flows lacks required governed columns ({missing}); no flow figures were stated."
        )
        return
    by_type: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        cents = _cent_value(row, "cents")
        flow_type = str(row["type"] or "").strip().casefold()
        try:
            source_columns = ["period", "type", "cents"]
            source_columns.extend(
                column
                for column in ("investor", "source_label", "attribution")
                if column in columns
            )
            ref = _ref("fund_flows", row, primary_keys, *source_columns)
        except ValueError as exc:
            report["data_quality_flags"].append(str(exc))
            continue
        if cents is None or flow_type not in _FLOW_TYPES:
            report["data_quality_flags"].append(
                f"Excluded invalid fund_flows row {ref['id']}; integer cents and an allowed type are required."
            )
            continue
        value = _figure(
            f"flow:{ref['id']}",
            f"Governed {flow_type} flow",
            cents,
            [ref],
            "fund_flows.cents for the cited row; sign reproduced as stored",
        )
        report["period_flows"].append(
            {
                "period": period,
                "type": flow_type,
                "investor": (
                    str(row["investor"])
                    if "investor" in columns and row["investor"] is not None
                    else None
                ),
                "governed_source_label": (
                    str(row["source_label"])
                    if "source_label" in columns and row["source_label"] is not None
                    else None
                ),
                "attribution": (
                    str(row["attribution"])
                    if "attribution" in columns and row["attribution"] is not None
                    else None
                ),
                "value": value,
                "source_ref": ref,
            }
        )
        by_type[flow_type].append((cents, ref))

    if not by_type:
        report["unanswered_questions"].append(
            f"No valid governed fund_flows rows exist for {period}; no zero flow balances were inferred."
        )
        return
    for flow_type, entries in sorted(by_type.items()):
        total = _figure(
            f"period_{flow_type}_cents",
            f"Period {flow_type}s as recorded",
            sum(cents for cents, _ in entries),
            [ref for _, ref in entries],
            f"sum(fund_flows.cents) for cited {flow_type} rows; sign reproduced as stored",
        )
        report["figures"].append(total)
        report["narrative"].append(
            {
                "template_id": f"governed_period_{flow_type}",
                "text": f"For {period}, governed {flow_type} rows total {total['display']} as recorded.",
                "facts": [_fact(total)],
                "limitations": "No cause, quality assessment, or performance conclusion is inferred.",
            }
        )


def _append_commitment_data(
    report: dict[str, Any],
    rows: list[sqlite3.Row],
    columns: list[str],
    primary_keys: list[str],
) -> None:
    required = {"investor", "committed_cents", "funded_cents"}
    if not required.issubset(columns):
        missing = ", ".join(sorted(required - set(columns)))
        report["unanswered_questions"].append(
            f"fund_commitments lacks required governed columns ({missing}); no commitment figures were stated."
        )
        return
    valid: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        investor = str(row["investor"] or "").strip()
        committed = _cent_value(row, "committed_cents")
        funded = _cent_value(row, "funded_cents")
        try:
            ref = _ref(
                "fund_commitments",
                row,
                primary_keys,
                "investor",
                "committed_cents",
                "funded_cents",
            )
        except ValueError as exc:
            report["data_quality_flags"].append(str(exc))
            continue
        if (
            not investor
            or committed is None
            or funded is None
            or committed < 0
            or funded < 0
        ):
            report["data_quality_flags"].append(
                f"Excluded invalid fund_commitments row {ref['id']}; investor and nonnegative integer cents are required."
            )
            continue
        committed_figure = _figure(
            f"investor_committed:{ref['id']}",
            f"{investor} committed capital",
            committed,
            [ref],
            "fund_commitments.committed_cents for the cited row",
        )
        funded_figure = _figure(
            f"investor_funded:{ref['id']}",
            f"{investor} funded capital",
            funded,
            [ref],
            "fund_commitments.funded_cents for the cited row",
        )
        account: dict[str, Any] = {
            "investor": investor,
            "committed": committed_figure,
            "funded": funded_figure,
            "source_ref": ref,
        }
        if funded <= committed:
            account["unfunded"] = _figure(
                f"investor_unfunded:{ref['id']}",
                f"{investor} unfunded commitment",
                committed - funded,
                [ref],
                "fund_commitments.committed_cents - funded_cents for the cited row",
            )
        else:
            report["data_quality_flags"].append(
                f"fund_commitments row {ref['id']} has funded_cents above committed_cents; "
                "no unfunded figure was stated."
            )
        report["commitment_balances"].append(account)
        valid.append((committed, funded, ref))

    if not valid:
        report["unanswered_questions"].append(
            "No valid governed fund_commitments rows exist; no commitment balances were inferred."
        )
        return
    refs = [ref for _, _, ref in valid]
    committed_total = _figure(
        "total_committed_cents",
        "Total current governed commitments",
        sum(committed for committed, _, _ in valid),
        refs,
        "sum(fund_commitments.committed_cents) for cited current rows",
    )
    funded_total = _figure(
        "total_funded_cents",
        "Total current governed funded capital",
        sum(funded for _, funded, _ in valid),
        refs,
        "sum(fund_commitments.funded_cents) for cited current rows",
    )
    report["figures"].extend((committed_total, funded_total))
    report["narrative"].append(
        {
            "template_id": "governed_commitments",
            "text": (
                f"Current governed commitments total {committed_total['display']}; "
                f"funded amounts total {funded_total['display']}."
            ),
            "facts": [_fact(committed_total), _fact(funded_total)],
            "limitations": (
                "These are current commitment-table balances, not proof of a binding "
                "subscription, funding availability, or period-end capital accounts."
            ),
        }
    )


def quarterly_investor_report(
    period: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Assemble a template-only report from governed fund-table rows.

    The report does not calculate NAV because cash and liability inputs are not
    governed by the three tables read here.  Callers should use ``nav_report`` for
    that separate arithmetic and preserve its source references.
    """

    normalized_period = _period(period)
    path = _resolve_db_path(db_path, config=config)
    report = _base_report(normalized_period, path)
    if not path.exists():
        report["unanswered_questions"].append(
            "The governed source database does not exist; no financial figures or narrative facts were stated."
        )
        return report

    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=10)
    except sqlite3.Error as exc:
        report["unanswered_questions"].append(
            f"The governed source database could not be opened read-only ({exc}); no figures were stated."
        )
        return report
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        for table in _KNOWN_TABLES:
            if not _table_exists(connection, table):
                report["unanswered_questions"].append(
                    f"{table} is unavailable; related figures were omitted rather than inferred as zero."
                )
                continue
            row_period = normalized_period if table in {"fund_marks", "fund_flows"} else None
            rows, columns, primary_keys = _read_rows(
                connection,
                table,
                period=row_period,
            )
            if table == "fund_marks":
                _append_mark_data(report, rows, columns, primary_keys, normalized_period)
            elif table == "fund_flows":
                _append_flow_data(report, rows, columns, primary_keys, normalized_period)
            else:
                _append_commitment_data(report, rows, columns, primary_keys)
    finally:
        connection.close()

    report["unanswered_questions"].append(
        "NAV is not stated by this assembler: governed period-end cash and liability "
        "inputs are required in addition to asset marks."
    )
    report["unanswered_questions"].append(
        "Allocated investor capital accounts are not stated: administrator- and "
        "counsel-approved allocation rules are not persisted in these source tables."
    )
    reject_unsubstantiated_performance_claims(report["narrative"])
    return report


__all__ = ["quarterly_investor_report"]
