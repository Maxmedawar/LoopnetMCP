"""Facts-only JV structure comparisons backed by the existing capital waterfall."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.capital.waterfall import model_waterfall
from cre_mcp.execution.guardrails import capital_guardrail

_OUTCOME_ORDER = ("downside", "base", "upside")
_CONTROL_FIELDS = ("major_decisions", "removal", "forced_sale", "rofr")


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    try:
        result = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _percent(value: Any, label: str) -> float:
    number = _number(value, label)
    # ``*_pct`` fields are percentage-native, so the common 1% fee must stay
    # 1%. Values strictly between zero and one remain accepted as fractions.
    normalized = number * 100 if 0 < number < 1 else number
    if normalized < 0 or normalized > 100:
        raise ValueError(f"{label} must be between 0% and 100%")
    return normalized


def _first(values: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _promote_terms(structure: Mapping[str, Any]) -> tuple[float, list[dict[str, float]]]:
    raw_tiers = structure.get("promote_tiers", [])
    if raw_tiers is None:
        raw_tiers = []
    if not isinstance(raw_tiers, Sequence) or isinstance(raw_tiers, (str, bytes)):
        raise ValueError("promote_tiers must be a list of mappings")

    parsed: list[tuple[float | None, float, float]] = []
    for index, raw in enumerate(raw_tiers):
        if not isinstance(raw, Mapping):
            raise ValueError("each promote tier must be a mapping")
        gp_value = _first(
            raw,
            ("gp_promote_pct", "promote_pct", "gp_split", "gp_pct", "promote"),
        )
        lp_value = _first(raw, ("lp_split", "lp_pct", "lp_share"))
        if gp_value is None and lp_value is None:
            raise ValueError(f"promote_tiers[{index}] must supply a GP promote or LP split")
        gp_pct = 100 - _percent(lp_value, f"promote_tiers[{index}].lp_split") if gp_value is None else _percent(gp_value, f"promote_tiers[{index}].gp_promote_pct")
        lp_pct = 100 - gp_pct if lp_value is None else _percent(lp_value, f"promote_tiers[{index}].lp_split")
        if not math.isclose(lp_pct + gp_pct, 100.0, abs_tol=1e-9):
            raise ValueError(f"promote_tiers[{index}] LP and GP splits must sum to 100%")
        hurdle_value = _first(
            raw,
            ("lp_irr_hurdle", "hurdle_irr", "hurdle_pct", "irr_hurdle_pct", "hurdle"),
        )
        hurdle = None if hurdle_value is None else _percent(
            hurdle_value, f"promote_tiers[{index}].hurdle"
        )
        if index > 0 and hurdle is None:
            raise ValueError(f"promote_tiers[{index}] must supply an IRR hurdle")
        parsed.append((hurdle, lp_pct, gp_pct))

    explicit_base = _first(structure, ("gp_promote_pct", "gp_promote", "promote_pct"))
    if explicit_base is not None:
        base_promote = _percent(explicit_base, "gp_promote_pct")
    elif parsed:
        base_promote = parsed[0][2]
    else:
        # An omitted promote is modeled as no promote, rather than inheriting the
        # existing waterfall's 20% convenience default.
        base_promote = 0.0

    tiered_splits: list[dict[str, float]] = []
    for hurdle, lp_pct, gp_pct in parsed:
        if hurdle is None or hurdle == 0:
            continue
        tiered_splits.append(
            {
                "lp_irr_hurdle": hurdle,
                "lp_split": lp_pct,
                "gp_split": gp_pct,
            }
        )
    return base_promote, tiered_splits


def _scenario_items(
    deal_cash_flows: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    if isinstance(deal_cash_flows, Mapping):
        supplied = dict(deal_cash_flows)
        raw_scenarios = supplied.get("scenarios", supplied.get("outcomes"))
        if raw_scenarios is None and all(name in supplied for name in _OUTCOME_ORDER):
            raw_scenarios = {name: supplied[name] for name in _OUTCOME_ORDER}
        shared = {
            key: value
            for key, value in supplied.items()
            if key not in {"scenarios", "outcomes", *_OUTCOME_ORDER}
        }
    elif isinstance(deal_cash_flows, Sequence) and not isinstance(
        deal_cash_flows, (str, bytes)
    ):
        raw_scenarios = deal_cash_flows
        shared = {}
    else:
        raise ValueError("deal_cash_flows must be a mapping or a list of scenario mappings")

    if isinstance(raw_scenarios, Mapping):
        items = list(raw_scenarios.items())
        by_name = {str(name).strip().casefold(): (str(name), value) for name, value in items}
        if all(name in by_name for name in _OUTCOME_ORDER):
            items = [by_name[name] for name in _OUTCOME_ORDER]
        else:
            items = [(str(name), value) for name, value in items]
    elif isinstance(raw_scenarios, Sequence) and not isinstance(raw_scenarios, (str, bytes)):
        items = []
        for index, value in enumerate(raw_scenarios):
            if not isinstance(value, Mapping):
                raise ValueError("each outcome scenario must be a mapping")
            name = str(value.get("name") or value.get("scenario") or "").strip()
            if not name:
                name = _OUTCOME_ORDER[index] if index < len(_OUTCOME_ORDER) else ""
            items.append((name, value))
    else:
        raise ValueError(
            "deal_cash_flows must contain three caller-supplied scenarios/outcomes"
        )

    if len(items) != 3 or any(not str(name).strip() for name, _ in items):
        raise ValueError("exactly three named, caller-supplied outcome scenarios are required")
    if len({str(name).strip().casefold() for name, _ in items}) != 3:
        raise ValueError("outcome scenario names must be unique")
    return shared, items


def _scenario_input(
    name: str,
    raw: Any,
    shared: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        details = {**dict(shared), **dict(raw)}
        flows = _first(details, ("annual_cash_flows", "cash_flows"))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        details = dict(shared)
        flows = raw
    else:
        raise ValueError(f"scenario '{name}' must be a cash-flow list or mapping")
    if not isinstance(flows, Sequence) or isinstance(flows, (str, bytes)) or not flows:
        raise ValueError(f"scenario '{name}' must supply non-empty annual_cash_flows")
    total_equity = _first(details, ("total_equity", "equity_required", "equity"))
    total_equity = _number(total_equity, f"scenario '{name}' total_equity")
    if total_equity <= 0:
        raise ValueError(f"scenario '{name}' total_equity must be greater than zero")
    source = str(
        details.get("source")
        or details.get("source_label")
        or "caller-supplied JV outcome scenario"
    ).strip()
    if not source:
        raise ValueError(f"scenario '{name}' source label cannot be blank")
    return {
        "name": str(name).strip(),
        "total_equity": total_equity,
        "annual_cash_flows": list(flows),
        "exit_equity_proceeds": _first(
            details, ("exit_equity_proceeds", "exit_proceeds")
        ),
        "deal_ref": str(details.get("deal_ref") or f"jv-scenario:{name}"),
        "source": source,
    }


def _structure_terms(structure: Mapping[str, Any]) -> dict[str, Any]:
    name = str(structure.get("name") or "").strip()
    if not name:
        raise ValueError("each JV structure must have a non-blank name")
    pref_value = structure.get("pref_pct")
    if pref_value is None:
        raise ValueError(f"JV structure '{name}' must supply pref_pct")
    pref_pct = _percent(pref_value, f"{name}.pref_pct")

    capital = structure.get("capital") or {}
    if not isinstance(capital, Mapping):
        raise ValueError(f"{name}.capital must be a mapping")
    gp_coinvest_value = capital.get("gp_coinvest_pct", 0)
    gp_coinvest_pct = _percent(gp_coinvest_value, f"{name}.capital.gp_coinvest_pct")
    if gp_coinvest_pct >= 100:
        raise ValueError(f"{name}.capital.gp_coinvest_pct must be below 100%")

    control = structure.get("control_rights") or {}
    fees = structure.get("fees") or {}
    if not isinstance(control, Mapping):
        raise ValueError(f"{name}.control_rights must be a mapping")
    if not isinstance(fees, Mapping):
        raise ValueError(f"{name}.fees must be a mapping")
    base_promote, tiered_splits = _promote_terms(structure)
    return {
        "name": name,
        "pref_pct": pref_pct,
        "catch_up": bool(structure.get("catchup", structure.get("catch_up", False))),
        "base_promote_pct": base_promote,
        "tiered_splits": tiered_splits,
        "gp_coinvest_pct": gp_coinvest_pct,
        "capital_call_remedies": capital.get("capital_call_remedies", "NOT PROVIDED"),
        "control_rights": {
            field: control.get(field, "NOT PROVIDED") for field in _CONTROL_FIELDS
        },
        "fees": {
            "am_pct": None
            if fees.get("am_pct") is None
            else _percent(fees["am_pct"], f"{name}.fees.am_pct"),
            "acq_pct": None
            if fees.get("acq_pct") is None
            else _percent(fees["acq_pct"], f"{name}.fees.acq_pct"),
        },
    }


def _sum_year_field(waterfall: Mapping[str, Any], field: str) -> float:
    return round(sum(float(year[field]) for year in waterfall["years"]), 2)


def compare_jv_structures(
    structures: Sequence[Mapping[str, Any]],
    deal_cash_flows: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare caller-supplied JV terms across exactly three supplied outcomes.

    Cash flows are never synthesized. Fee percentages are comparison terms only;
    they affect economics only when the supplied distributable cash already reflects them.
    """
    if not isinstance(structures, Sequence) or isinstance(structures, (str, bytes)):
        raise ValueError("structures must be a list of JV structure mappings")
    if not structures:
        raise ValueError("at least one JV structure is required")
    reject_unsubstantiated_performance_claims(structures, deal_cash_flows)

    shared, raw_scenarios = _scenario_items(deal_cash_flows)
    scenarios = [_scenario_input(name, raw, shared) for name, raw in raw_scenarios]
    terms_list = [_structure_terms(item) for item in structures]
    if len({item["name"].casefold() for item in terms_list}) != len(terms_list):
        raise ValueError("JV structure names must be unique")

    compared: list[dict[str, Any]] = []
    economics_matrix: list[dict[str, Any]] = []
    downside_matrix: list[dict[str, Any]] = []
    for terms in terms_list:
        outcomes: list[dict[str, Any]] = []
        for scenario in scenarios:
            waterfall_terms: dict[str, Any] = {
                "total_equity": scenario["total_equity"],
                "total_equity_source": scenario["source"],
                "annual_cash_flows": scenario["annual_cash_flows"],
                "pref": terms["pref_pct"],
                "gp_promote": terms["base_promote_pct"],
                "lp_equity_pct": 100 - terms["gp_coinvest_pct"],
                "catch_up": terms["catch_up"],
                "lp_residual_split": 100 - terms["base_promote_pct"],
                "tiered_splits": terms["tiered_splits"],
            }
            if scenario["exit_equity_proceeds"] is not None:
                waterfall_terms["exit_equity_proceeds"] = scenario[
                    "exit_equity_proceeds"
                ]
            modeled = model_waterfall(
                {
                    "deal_ref": scenario["deal_ref"],
                    "total_equity": scenario["total_equity"],
                },
                waterfall_terms,
            ).model_dump(mode="json")
            lp_total = _sum_year_field(modeled, "lp_distribution")
            gp_total = _sum_year_field(modeled, "gp_distribution")
            outcome = {
                "scenario": scenario["name"],
                "input_source": scenario["source"],
                "input_total_equity": scenario["total_equity"],
                "input_annual_cash_flows": list(scenario["annual_cash_flows"]),
                "lp_distribution": lp_total,
                "gp_distribution": gp_total,
                "lp_profit": round(lp_total - modeled["lp_contribution"], 2),
                "gp_profit": round(gp_total - modeled["gp_contribution"], 2),
                "waterfall": modeled,
            }
            outcomes.append(outcome)
            economics_matrix.append(
                {
                    "structure": terms["name"],
                    "scenario": scenario["name"],
                    "lp_distribution": lp_total,
                    "gp_distribution": gp_total,
                    "lp_irr_pct": modeled["lp_irr_pct"],
                    "lp_equity_multiple": modeled["lp_equity_multiple"],
                    "gp_promote_earned": modeled["gp_promote_earned"],
                    "input_source": scenario["source"],
                }
            )

        downside = next(
            (
                item
                for item in outcomes
                if item["scenario"].strip().casefold() == "downside"
            ),
            outcomes[0],
        )
        downside_year = downside["waterfall"]["years"][-1]
        downside_matrix.append(
            {
                "structure": terms["name"],
                "scenario": downside["scenario"],
                "lp_distribution": downside["lp_distribution"],
                "gp_distribution": downside["gp_distribution"],
                "unreturned_lp_capital": downside_year["unreturned_lp_capital"],
                "unreturned_gp_capital": downside_year["unreturned_gp_capital"],
                "unpaid_lp_preferred_return": downside_year[
                    "unpaid_lp_preferred_return"
                ],
                "capital_call_remedies": terms["capital_call_remedies"],
                **terms["control_rights"],
            }
        )
        compared.append(
            {
                "name": terms["name"],
                "economic_terms": {
                    "pref_pct": terms["pref_pct"],
                    "catchup": terms["catch_up"],
                    "base_promote_pct": terms["base_promote_pct"],
                    "promote_tiers": terms["tiered_splits"],
                    "gp_coinvest_pct": terms["gp_coinvest_pct"],
                    "fees": terms["fees"],
                },
                "control_rights": terms["control_rights"],
                "capital_call_remedies": terms["capital_call_remedies"],
                "outcomes": outcomes,
                "counsel_flags": [
                    "Review the distribution waterfall, catch-up, promote hurdles, and fee base with fund/securities counsel and a CPA.",
                    "Review major-decision, removal, forced-sale, ROFR, capital-call, dilution, default, and transfer provisions in the governing documents.",
                ],
            }
        )

    guardrail = capital_guardrail(
        "Have fund/securities counsel and a CPA reproduce each structure against the proposed "
        "JV/operating agreement, confirm control and default remedies, and approve any investor-facing use."
    )
    return {
        "structures": compared,
        "scenario_order": [item["name"] for item in scenarios],
        "comparison_matrix": {
            "economics": economics_matrix,
            "control_and_downside": downside_matrix,
        },
        "fee_treatment": (
            "Fee terms are disclosed for comparison but are not deducted again; supplied "
            "distributable cash flows must already reflect any applicable fees."
        ),
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "counsel_flags": [
            "REVIEW WITH FUND/SECURITIES COUNSEL: economics, fiduciary duties, conflicts, control rights, transfer restrictions, capital-call/default remedies, and offering disclosure are governing-document questions.",
            "Modeled outcomes are deterministic scenarios from caller-supplied cash flows, not forecasts or promises.",
        ],
        "guardrail": guardrail,
    }


__all__ = ["compare_jv_structures"]
