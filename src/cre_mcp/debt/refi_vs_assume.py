"""Side-by-side capital-path comparison without a hidden recommendation."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping, Sequence

from cre_mcp.debt.assumable import value_assumable_debt
from cre_mcp.debt.termsheet import (
    NOT_COMPUTABLE,
    QUOTED_TERMS_WARNING,
    TermSheet,
    compare_term_sheets,
)


SUPPORTED_PATHS = {"assume", "refi", "supplemental", "mod", "sale-context", "sale"}


def _not_computable(reason: str, missing: list[str]) -> dict[str, Any]:
    return {
        "status": NOT_COMPUTABLE,
        "reason": reason,
        "missing_inputs": missing,
    }


def _normalize_options(
    options: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(options, Mapping):
        return [
            (str(path).casefold().replace("_", "-"), dict(details) if isinstance(details, Mapping) else {})
            for path, details in options.items()
        ]
    normalized: list[tuple[str, dict[str, Any]]] = []
    for option in options:
        if not isinstance(option, Mapping):
            normalized.append(("unknown", {}))
            continue
        details = dict(option)
        path = str(details.pop("type", details.pop("path", "unknown"))).casefold().replace("_", "-")
        normalized.append((path, details))
    return normalized


def _timing(option: Mapping[str, Any]) -> Any:
    value = option.get("timing", option.get("timing_days"))
    return value if value is not None else _not_computable(
        "No execution timing was supplied; timing is lender- and consent-dependent.",
        ["timing or timing_days"],
    )


def _supplied_risks(option: Mapping[str, Any]) -> list[str]:
    risks = option.get("risks")
    if isinstance(risks, str):
        return [risks]
    if isinstance(risks, Sequence) and not isinstance(risks, (str, bytes)):
        return [str(risk) for risk in risks]
    return []


def _term_path(
    path: str,
    option: Mapping[str, Any],
    current_position: Mapping[str, Any],
) -> dict[str, Any]:
    raw_sheets = option.get("term_sheets")
    if raw_sheets is None:
        one_sheet = option.get("term_sheet", option.get("terms"))
        raw_sheets = [one_sheet] if one_sheet is not None else []
    elif isinstance(raw_sheets, Mapping) or isinstance(raw_sheets, TermSheet):
        raw_sheets = [raw_sheets]
    deal = option.get("deal")
    if not isinstance(deal, Mapping):
        deal = {
            "noi": current_position.get("noi"),
            "price": current_position.get("price", current_position.get("value")),
            "hold_years": current_position.get("hold_years"),
            "exit_assumptions": current_position.get("exit_assumptions"),
        }
    if not raw_sheets:
        return {
            "path": path,
            "status": NOT_COMPUTABLE,
            "cost": _not_computable("A structured term sheet is required.", ["term_sheet"]),
            "proceeds": _not_computable("A structured term sheet is required.", ["term_sheet"]),
            "timing": _timing(option),
            "risks": _supplied_risks(option),
            "missing_inputs": ["term_sheet"],
        }
    comparison = compare_term_sheets(raw_sheets, deal)
    rows = comparison["comparisons"]
    cost = [
        {
            "lender": row["lender"],
            "all_in_cost": row["all_in_cost"],
            "status": row["all_in_cost_detail"]["status"],
        }
        for row in rows
    ]
    proceeds = [
        {
            "lender": row["lender"],
            "gross": row["proceeds"],
            "net_of_stated_reserves_holdbacks": row["proceeds_net_of_stated_reserves_holdbacks"],
            "status": row["net_proceeds_status"],
        }
        for row in rows
    ]
    risks = _supplied_risks(option)
    for row in rows:
        risks.extend(f"{row['lender']}: {note}" for note in row["risk_notes"])
    return {
        "path": path,
        "status": "quoted_path_comparison",
        "cost": cost,
        "proceeds": proceeds,
        "timing": _timing(option),
        "risks": risks,
        "term_sheet_comparison": comparison,
        "missing_inputs": sorted({item for row in rows for item in row["missing_inputs"]}),
    }


def _assume_path(
    option: Mapping[str, Any],
    current_position: Mapping[str, Any],
) -> dict[str, Any]:
    existing = option.get("existing_loan", current_position.get("existing_loan"))
    market = option.get("market", current_position.get("market"))
    price = option.get("price", current_position.get("price"))
    hold_years = option.get("hold_years", current_position.get("hold_years"))
    missing = [
        name
        for name, value in (("existing_loan", existing), ("market", market))
        if not isinstance(value, Mapping)
    ]
    if missing:
        return {
            "path": "assume",
            "status": NOT_COMPUTABLE,
            "cost": _not_computable("Assumption economics require existing and market loan terms.", missing),
            "proceeds": _not_computable("Assumption proceeds gap requires existing and market loan terms.", missing),
            "timing": _timing(option),
            "risks": _supplied_risks(option) + ["Lender consent is required."],
            "missing_inputs": missing,
        }
    result = value_assumable_debt(existing, market, price, hold_years)
    return {
        "path": "assume",
        "status": result["status"],
        "cost": {
            "assumption_fee": result.get("assumption_fee"),
            "net_assumable_debt_value": result.get("net_assumable_debt_value"),
            "conditional_verdict_range": result.get("net_verdict_range"),
        },
        "proceeds": {
            "assumable_balance": result.get("assumable_balance"),
            "gap_vs_market_new_debt": result.get("proceeds_gap_vs_new_debt"),
            "equity_gap": result.get("equity_gap"),
        },
        "timing": _timing(option),
        "risks": _supplied_risks(option) + result["assumption_risks"],
        "assumable_debt_analysis": result,
        "missing_inputs": result["missing_inputs"],
    }


def _mod_path(option: Mapping[str, Any]) -> dict[str, Any]:
    cost = option.get("cost")
    proceeds = option.get("proceeds")
    missing = []
    if cost is None:
        missing.append("cost")
    if proceeds is None:
        missing.append("proceeds")
    return {
        "path": "mod",
        "status": "supplied_path" if not missing else "partially_computable",
        "cost": cost if cost is not None else _not_computable("Modification cost was not supplied.", ["cost"]),
        "proceeds": proceeds if proceeds is not None else _not_computable(
            "Modification proceeds were not supplied.", ["proceeds"]
        ),
        "timing": _timing(option),
        "risks": _supplied_risks(option) or [
            "Modification terms require servicer/lender approval and were not inferred."
        ],
        "missing_inputs": missing,
    }


def _sale_hook() -> str:
    """Return an available tax-economics pointer without executing a sale model."""
    for module_name in ("cre_mcp.taxecon", "cre_mcp.taxecon.tools"):
        try:
            module = import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            continue
        function = getattr(module, "net_sale_proceeds", None)
        if callable(function):
            return f"{function.__module__}.{function.__name__}"
    return "taxecon.net_sale_proceeds"


def _sale_path(option: Mapping[str, Any]) -> dict[str, Any]:
    hook = _sale_hook()
    return {
        "path": "sale-context",
        "status": "external_model_hook",
        "cost": {
            "status": NOT_COMPUTABLE,
            "reason": "Sale taxes and transaction costs are delegated to the tax-economics model.",
            "hook": hook,
        },
        "proceeds": {"status": "use_hook", "hook": hook},
        "timing": _timing(option),
        "risks": _supplied_risks(option) or [
            "Net sale proceeds depend on taxes, debt payoff, closing costs, and supplied sale assumptions."
        ],
        "missing_inputs": [],
    }


def compare_capital_paths(
    current_position: Mapping[str, Any],
    options: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare supplied capital paths without selecting a hidden overall winner."""
    rows: list[dict[str, Any]] = []
    for path, option in _normalize_options(options):
        if path == "assume":
            row = _assume_path(option, current_position)
        elif path in {"refi", "supplemental"}:
            row = _term_path(path, option, current_position)
        elif path == "mod":
            row = _mod_path(option)
        elif path in {"sale", "sale-context"}:
            row = _sale_path(option)
        else:
            row = {
                "path": path,
                "status": NOT_COMPUTABLE,
                "cost": _not_computable("Unsupported capital path.", ["supported path type"]),
                "proceeds": _not_computable("Unsupported capital path.", ["supported path type"]),
                "timing": _timing(option),
                "risks": _supplied_risks(option),
                "missing_inputs": ["path must be assume/refi/supplemental/mod/sale-context"],
            }
        row["warning"] = QUOTED_TERMS_WARNING
        row["lender_ledger_pointer"] = "lender_track_record"
        rows.append(row)
    return {
        "status": "comparison" if rows else NOT_COMPUTABLE,
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "paths": rows,
        "overall_ranking": None,
        "verdict": (
            "No hidden winner is selected. Compare conditional cost/value, proceeds, timing, and risks "
            "against the owner's stated objective and execution constraints."
        ),
        "assumption_sheet": {
            "current_position": dict(current_position),
            "path_inputs": [dict(option) for _, option in _normalize_options(options)],
            "sale_model_hook": _sale_hook(),
            "unmodeled": [
                "lender/servicer approval probability",
                "closing probability",
                "tax outcomes outside the sale-model hook",
                "terms, timing, costs, or proceeds not supplied by the caller",
            ],
        },
    }


__all__ = ["SUPPORTED_PATHS", "compare_capital_paths"]
