"""Deterministic negotiation plans with visible assumptions and authority gates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.decision.frontier import DEFAULT_STRUCTURES
from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.positioning import AUTHORITY_MATRIX

from .concessions import value_concession


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def _optional_number(value: Any, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _value_range(raw: Any) -> tuple[float, float]:
    if isinstance(raw, Mapping):
        low_raw = raw.get("low", raw.get("min"))
        high_raw = raw.get("high", raw.get("max"))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
        low_raw, high_raw = raw
    else:
        raise TypeError("value_range must be [low, high] or a low/high mapping")
    low = _number(low_raw, "value_range low")
    high = _number(high_raw, "value_range high")
    if low > high:
        raise ValueError("value_range low cannot exceed high")
    return low, high


def _items(raw: Any, name: str) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, Sequence):
        raise TypeError(f"counterparty {name} must be a string or list")
    return list(raw)


def _counterparty_assessment(counterparty: Mapping[str, Any]) -> dict[str, Any]:
    priorities = _items(counterparty.get("priorities"), "priorities")
    constraints = _items(counterparty.get("constraints"), "constraints")
    history = _items(counterparty.get("history"), "history")
    provided = {
        "priorities": [
            {"label": "provided_fact", "value": item, "source": "counterparty.priorities"}
            for item in priorities
        ],
        "constraints": [
            {"label": "provided_fact", "value": item, "source": "counterparty.constraints"}
            for item in constraints
        ],
        "history": [
            {"label": "conduct_evidence", "value": item, "source": "counterparty.history"}
            for item in history
        ],
    }

    inferences: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    signals = (
        (
            ("close", "closing", "timing", "deadline", "quarter"),
            "timing or closing certainty may matter",
        ),
        (
            ("price", "reduction", "discount", "cut"),
            "price preservation may matter",
        ),
        (
            ("deposit", "earnest", "hard money"),
            "deposit certainty may matter",
        ),
        (
            ("finance", "financing", "cash", "certainty"),
            "execution certainty may matter",
        ),
    )
    for evidence in history:
        evidence_text = str(evidence)
        lowered = evidence_text.casefold()
        for keywords, inference in signals:
            if any(keyword in lowered for keyword in keywords):
                identity = (inference, evidence_text)
                if identity in seen:
                    continue
                seen.add(identity)
                inferences.append(
                    {
                        "label": "inference",
                        "inferred_priority": inference,
                        "conduct_evidence": evidence_text,
                        "confidence": "low",
                        "honesty": (
                            "Conduct supports a negotiation hypothesis, not a fact about motive. "
                            "Validate it by asking the counterparty."
                        ),
                    }
                )
    return {
        "provided": provided,
        "inferences": inferences,
        "unknowns": [
            name
            for name, values in (
                ("priorities", priorities),
                ("constraints", constraints),
                ("history", history),
            )
            if not values
        ],
    }


def _normalize_structures(structure_options: Sequence[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(structure_options):
        if isinstance(raw, str):
            item: dict[str, Any] = {"name": raw}
        elif isinstance(raw, Mapping):
            item = dict(raw)
        else:
            raise TypeError("each structure option must be a name or mapping")
        name = str(item.get("name", item.get("structure", ""))).strip()
        if not name:
            raise ValueError("each structure option needs a nonblank name")
        cost = _optional_number(item.get("cost_to_us"), f"{name}.cost_to_us")
        value = _optional_number(item.get("value_to_them"), f"{name}.value_to_them")
        ratio = None if cost in (None, 0) or value is None else round(value / cost, 4)
        normalized.append(
            {
                "name": name,
                "provided_terms": item,
                "recognized_decision_frontier_structure": name in DEFAULT_STRUCTURES,
                "cost_to_us": cost,
                "value_to_them": value,
                "value_cost_ratio": ratio,
                "input_order": index,
            }
        )
    return sorted(normalized, key=lambda item: (item["name"].casefold(), item["input_order"]))


def _concession_sequence(
    deal_economics: Mapping[str, Any], structures: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_concessions = deal_economics.get("concessions", [])
    if raw_concessions is None:
        raw_concessions = []
    if isinstance(raw_concessions, Mapping) or isinstance(raw_concessions, str):
        raise TypeError("deal_economics.concessions must be a list")
    if not isinstance(raw_concessions, Sequence):
        raise TypeError("deal_economics.concessions must be a list")

    candidates: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_concessions):
        if not isinstance(raw, Mapping):
            raise TypeError("each concession must be a mapping")
        giver = str(raw.get("giver", "us")).strip().casefold()
        if giver != "us":
            raise ValueError(
                "plan concessions must be offers made by us; model concessions from them separately"
            )
        valued = value_concession(raw, deal_economics, perspective="both")
        candidates.append(
            {
                **valued,
                "cost_to_us": valued["giver_cost"],
                "value_to_them": valued["receiver_value"],
                "party_mapping": {
                    "giver": "us",
                    "receiver": "them",
                    "source": (
                        "provided concession.giver"
                        if "giver" in raw
                        else "explicit plan-perspective default"
                    ),
                },
                "name": str(raw.get("name", raw.get("type"))),
                "give": raw.get("give", raw.get("type")),
                "get": raw.get(
                    "get",
                    "A documented reciprocal term must be named before offering this give.",
                ),
                "required_get": raw.get(
                    "get",
                    "Name and document a reciprocal term; never concede unconditionally.",
                ),
                "input_order": index,
            }
        )
    for structure in structures:
        cost = structure["cost_to_us"]
        value = structure["value_to_them"]
        ratio = structure["value_cost_ratio"]
        trade_candidate = bool(
            value is not None
            and ((cost == 0 and value > 0) or (ratio is not None and ratio >= 1.5))
        )
        candidates.append(
            {
                "type": "structure_option",
                "name": structure["name"],
                "give": f"Offer {structure['name']} structure",
                "get": "Counterparty acceptance of documented economics and protections",
                "required_get": (
                    "Final economics, remedies, and approvals documented in definitive agreements."
                ),
                "cost_to_us": cost,
                "value_to_them": value,
                "giver_cost": cost,
                "receiver_value": value,
                "value_cost_ratio": ratio,
                "asymmetry_flag": trade_candidate,
                "trade_candidate": trade_candidate,
                "calculation": (
                    "Uses only provided cost_to_us/value_to_them; unknown values are not estimated."
                ),
                "risk_notes": [
                    "Structure changes can shift tax, financing, title, control, and remedy risk; route to counsel."
                ],
                "input_order": len(raw_concessions) + structure["input_order"],
            }
        )

    def rank_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        ratio = item.get("value_cost_ratio")
        cost = item.get("cost_to_us", item.get("giver_cost"))
        return (
            0 if item.get("trade_candidate") else 1,
            0 if ratio is not None else 1,
            -(ratio or 0),
            math.inf if cost is None else cost,
            str(item.get("name", item.get("type", ""))).casefold(),
            item.get("input_order", 0),
        )

    ordered = sorted(candidates, key=rank_key)
    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
        item["rank_basis"] = (
            "Trade candidates first; then evidenced value-to-them/cost-to-us ratio, "
            "lower cost, and deterministic name/input-order tie-breaks. Unknown values rank last."
        )
        item.pop("input_order", None)
    assumptions.append(
        {
            "name": "structure_trade_candidate_ratio",
            "value": 1.5,
            "source": "explicit_default",
            "effect": "Structure option is a trade candidate only at or above this evidenced ratio.",
        }
    )
    if raw_concessions:
        assumptions.append(
            {
                "name": "concession_party_mapping",
                "value": {"giver": "us", "receiver": "them"},
                "source": "explicit_plan_perspective",
                "effect": (
                    "Raw plan concessions are ranked only as gives from us; concessions "
                    "from them must be modeled separately to avoid reversing cost and value."
                ),
            }
        )
    return ordered, assumptions


def build_negotiation_plan(
    deal_economics: Mapping[str, Any],
    counterparty: Mapping[str, Any] | None = None,
    structure_options: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic anchor, give-get sequence, gates, and BATNA frame.

    Numeric recommendations are based only on supplied economics and the
    explicit defaults listed in ``assumptions``. Counterparty conduct produces
    labeled hypotheses with the source conduct quoted verbatim.
    """

    if not isinstance(deal_economics, Mapping):
        raise TypeError("deal_economics must be a mapping")
    if counterparty is None:
        counterparty = {}
    if not isinstance(counterparty, Mapping):
        raise TypeError("counterparty must be a mapping")
    if structure_options is None:
        structure_options = []
    if isinstance(structure_options, (str, bytes)) or not isinstance(
        structure_options, Sequence
    ):
        raise TypeError("structure_options must be a list")

    role = str(deal_economics.get("role", "buyer")).strip().casefold()
    if role not in {"buyer", "seller"}:
        raise ValueError("role must be buyer or seller")
    low, high = _value_range(deal_economics.get("value_range"))
    target = _number(deal_economics.get("target"), "target")
    walk_away = _number(deal_economics.get("walk_away"), "walk_away")
    if not low <= target <= high:
        raise ValueError("target must fall inside value_range")
    if not low <= walk_away <= high:
        raise ValueError("walk_away must fall inside value_range")
    if role == "buyer" and walk_away < target:
        raise ValueError("buyer walk_away cannot be below target")
    if role == "seller" and walk_away > target:
        raise ValueError("seller walk_away cannot exceed target")

    buffer_pct = _number(deal_economics.get("anchor_buffer_pct", 0.02), "anchor_buffer_pct")
    if buffer_pct > 1:
        raise ValueError("anchor_buffer_pct must be a decimal between 0 and 1")
    explicit_anchor = deal_economics.get("anchor")
    if explicit_anchor is not None:
        anchor_amount = _number(explicit_anchor, "anchor")
        if role == "buyer" and not low <= anchor_amount <= target:
            raise ValueError("buyer anchor must be between value_range low and target")
        if role == "seller" and not target <= anchor_amount <= high:
            raise ValueError("seller anchor must be between target and value_range high")
        anchor_source = "provided deal_economics.anchor"
        anchor_formula = "provided anchor"
    elif role == "buyer":
        anchor_amount = max(low, target * (1 - buffer_pct))
        anchor_source = "calculated"
        anchor_formula = "max(value_range.low, target * (1 - anchor_buffer_pct))"
    else:
        anchor_amount = min(high, target * (1 + buffer_pct))
        anchor_source = "calculated"
        anchor_formula = "min(value_range.high, target * (1 + anchor_buffer_pct))"
    anchor_amount = round(anchor_amount, 2)

    structures = _normalize_structures(structure_options)
    concessions, sequencing_assumptions = _concession_sequence(
        deal_economics, structures
    )
    approval_limits = deal_economics.get("approval_limits")
    if approval_limits is not None and not isinstance(approval_limits, Mapping):
        raise TypeError("approval_limits must be a mapping when provided")
    approval_limits = dict(approval_limits or {})

    approval_evaluation: list[dict[str, Any]] = []
    interpreted_limits = {"max_price_without_ic", "max_price_without_approval"}
    for name in sorted(approval_limits):
        value = approval_limits[name]
        if name in interpreted_limits:
            limit = _number(value, f"approval_limits.{name}")
            approval_evaluation.append(
                {
                    "limit": name,
                    "value": limit,
                    "anchor_amount": anchor_amount,
                    "within_limit": anchor_amount <= limit,
                    "interpretation": "buyer/open-price ceiling",
                }
            )
        else:
            approval_evaluation.append(
                {
                    "limit": name,
                    "value": value,
                    "within_limit": None,
                    "interpretation": (
                        "not automatically interpreted; accountable human must apply this limit"
                    ),
                }
            )

    walk_triggers: list[dict[str, Any]] = [
        {
            "trigger": (
                f"economics above {walk_away:.2f}"
                if role == "buyer"
                else f"economics below {walk_away:.2f}"
            ),
            "action": "walk or obtain a newly underwritten and explicitly approved mandate",
            "basis": "provided walk_away",
        },
        {
            "trigger": "contingency waiver, hard deposit, or remedy exposure not priced in the economics",
            "action": "pause and route exact language to CRE counsel and the accountable human approver",
            "basis": "legal downside is not valued by this plan",
        },
    ]
    if approval_limits:
        walk_triggers.append(
            {
                "trigger": "any term outside the provided approval_limits",
                "action": "stop; obtain explicit human approval and append it to neg_approvals",
                "basis": approval_limits,
            }
        )
    else:
        walk_triggers.append(
            {
                "trigger": "any nonstandard term without a supplied approval limit",
                "action": "treat authority as unknown and obtain explicit human approval",
                "basis": "no numeric approval limits were provided",
            }
        )
    for evaluation in approval_evaluation:
        if evaluation["within_limit"] is False:
            walk_triggers.append(
                {
                    "trigger": (
                        f"anchor {anchor_amount:.2f} exceeds "
                        f"{evaluation['limit']}={evaluation['value']:.2f}"
                    ),
                    "action": "stop and obtain the named explicit human approval",
                    "basis": evaluation,
                }
            )

    batna_value = deal_economics.get("batna")
    batna = {
        "description": batna_value if batna_value else "unknown — no BATNA was provided",
        "status": "provided" if batna_value else "unknown",
        "framing": (
            "Compare every package with the supplied alternative after time, certainty, "
            "capital, and diligence costs; do not call the BATNA superior without that comparison."
        ),
        "activation_trigger": walk_triggers[0]["trigger"],
    }

    assumptions: list[dict[str, Any]] = [
        {"name": "role", "value": role, "source": "provided" if "role" in deal_economics else "explicit_default"},
        {"name": "value_range", "value": [low, high], "source": "provided"},
        {"name": "target", "value": target, "source": "provided"},
        {"name": "walk_away", "value": walk_away, "source": "provided"},
        {
            "name": "anchor_buffer_pct",
            "value": buffer_pct,
            "source": "provided" if "anchor_buffer_pct" in deal_economics else "explicit_default",
            "effect": anchor_formula,
        },
        {
            "name": "daily_carry",
            "value": deal_economics.get("daily_carry"),
            "source": "provided" if deal_economics.get("daily_carry") is not None else "unknown",
            "effect": "Used only when a concession calculation calls for carry.",
        },
        {
            "name": "approval_limits",
            "value": approval_limits or None,
            "source": "provided" if approval_limits else "unknown",
        },
        {
            "name": "batna",
            "value": batna_value,
            "source": "provided" if batna_value else "unknown",
        },
        *sequencing_assumptions,
    ]

    return {
        "anchor": {
            "amount": anchor_amount,
            "role": role,
            "execution_vocabulary": "open_price",
            "basis": {
                "value_range": [low, high],
                "target": target,
                "walk_away": walk_away,
                "formula": anchor_formula,
                "source": anchor_source,
            },
            "rationale": (
                "Open with a bounded, explainable anchor that leaves room to reach the target "
                "without crossing the supplied walk-away."
            ),
        },
        "concessions": concessions,
        "concession_sequencing": concessions,
        "walk_away_triggers": walk_triggers,
        "approval_limits": approval_limits,
        "approval_limit_evaluation": approval_evaluation,
        "authority": dict(AUTHORITY_MATRIX),
        "authority_posture": (
            "AUTHORITY_MATRIX governs action class; supplied approval_limits are internal "
            "posture only and never grant the AI authority to submit, accept, or commit. "
            "Only named ceiling keys are evaluated; all other limits require human interpretation."
        ),
        "batna": batna,
        "counterparty_assessment": _counterparty_assessment(counterparty),
        "structure_options": structures,
        "assumptions": assumptions,
        "input_snapshot": {
            "deal_economics": dict(deal_economics),
            "counterparty": dict(counterparty),
            "structure_options": list(structure_options),
        },
        "guardrail": execution_guardrail(
            "confirm the written term package, approval authority, lender implications, "
            "and counsel review before offering or accepting it."
        ),
    }


__all__ = ["build_negotiation_plan"]
