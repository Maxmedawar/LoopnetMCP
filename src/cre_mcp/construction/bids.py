"""Trade-bid leveling with explicit plugs, gaps, and double-count screens."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


UNDER_MEDIAN_FLAG_PCT = Decimal("15")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _key(value: str) -> str:
    return " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )


def _money(value: Any, field: str, *, signed: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer number of cents")
    if not signed and value < 0:
        raise ValueError(f"{field} must be a non-negative integer number of cents")
    return value


def _list(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list")
    return value


def _item_text(value: Any, field: str) -> str:
    if isinstance(value, Mapping):
        value = value.get(
            "item",
            value.get("scope", value.get("description", value.get("name"))),
        )
    return _text(value, field)


def _first_money(
    row: Mapping[str, Any],
    keys: Sequence[str],
    field: str,
    *,
    signed: bool = False,
) -> tuple[int | None, str | None]:
    for name in keys:
        if name in row and row[name] is not None:
            return _money(row[name], f"{field}.{name}", signed=signed), name
    return None, None


def _baseline(scope_baseline: Sequence[Any]) -> list[dict[str, Any]]:
    rows = _list(scope_baseline, "scope_baseline")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for index, raw in enumerate(rows):
        field = f"scope_baseline[{index}]"
        item = _item_text(raw, field)
        trade: str | None = None
        plug_cents: int | None = None
        allowance_cents: int | None = None
        if isinstance(raw, Mapping):
            if raw.get("trade") is not None:
                trade = _text(raw["trade"], f"{field}.trade")
            plug_cents, _ = _first_money(
                raw,
                ("plug_cents", "budget_plug_cents", "scope_plug_cents"),
                field,
            )
            allowance_cents, _ = _first_money(
                raw,
                ("target_allowance_cents", "allowance_cents"),
                field,
            )
        identity = (_key(item), _key(trade) if trade is not None else None)
        if identity in seen:
            raise ValueError(f"scope_baseline contains duplicate item/trade {item!r}")
        seen.add(identity)
        output.append(
            {
                "item": item,
                "scope_key": identity[0],
                "trade": trade,
                "trade_key": identity[1],
                "plug_cents": plug_cents,
                "target_allowance_cents": allowance_cents,
            }
        )
    return output


def _allowances(raw: Any, field: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(_list(raw, field)):
        item_field = f"{field}[{index}]"
        item = _item_text(value, item_field)
        if not isinstance(value, Mapping):
            raise ValueError(f"{item_field} must include an integer-cent amount")
        amount, source_key = _first_money(
            value,
            ("amount_cents", "allowance_cents", "cents", "value_cents"),
            item_field,
        )
        if amount is None:
            raise ValueError(f"{item_field} must include an integer-cent amount")
        item_key = _key(item)
        if item_key in seen:
            raise ValueError(f"{field} contains duplicate item {item!r}")
        seen.add(item_key)
        output.append(
            {
                "item": item,
                "scope_key": item_key,
                "amount_cents": amount,
                "source_field": source_key,
            }
        )
    return output


def _exclusions(raw: Any, field: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(_list(raw, field)):
        item_field = f"{field}[{index}]"
        item = _item_text(value, item_field)
        plug_cents: int | None = None
        source_key: str | None = None
        if isinstance(value, Mapping):
            plug_cents, source_key = _first_money(
                value,
                ("plug_cents", "add_back_cents", "budget_plug_cents"),
                item_field,
            )
        item_key = _key(item)
        if item_key in seen:
            raise ValueError(f"{field} contains duplicate item {item!r}")
        seen.add(item_key)
        output.append(
            {
                "item": item,
                "scope_key": item_key,
                "supplied_plug_cents": plug_cents,
                "plug_source_field": source_key,
            }
        )
    return output


def _alternates(raw: Any, field: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, value in enumerate(_list(raw, field)):
        item_field = f"{field}[{index}]"
        item = _item_text(value, item_field)
        amount: int | None = None
        source_key: str | None = None
        selected = False
        alternate_type = "add"
        if isinstance(value, Mapping):
            amount, source_key = _first_money(
                value,
                ("amount_cents", "price_cents", "cents", "value_cents"),
                item_field,
                signed=True,
            )
            selected_raw = value.get("include_in_leveling", value.get("selected", False))
            if not isinstance(selected_raw, bool):
                raise ValueError(f"{item_field}.selected must be boolean")
            selected = selected_raw
            raw_type = value.get("type", value.get("kind", "add"))
            alternate_type = _text(raw_type, f"{item_field}.type").lower()
            if alternate_type not in {"add", "deduct", "alternate"}:
                raise ValueError(f"{item_field}.type must be add, deduct, or alternate")
        if selected and amount is None:
            raise ValueError(f"{item_field} is selected but has no integer-cent amount")
        adjustment = amount
        if adjustment is not None and alternate_type == "deduct" and adjustment > 0:
            adjustment = -adjustment
        output.append(
            {
                "item": item,
                "scope_key": _key(item),
                "amount_cents": amount,
                "adjustment_cents": adjustment if selected else 0,
                "source_field": source_key,
                "type": alternate_type,
                "selected": selected,
            }
        )
    return output


def _unit_prices(raw: Any, field: str) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        raw = [
            {"item": item, "unit_price_cents": amount}
            for item, amount in raw.items()
        ]
    output: list[dict[str, Any]] = []
    for index, value in enumerate(_list(raw, field)):
        item_field = f"{field}[{index}]"
        if not isinstance(value, Mapping):
            raise ValueError(f"{item_field} must be a dictionary")
        item = _item_text(value, item_field)
        amount, source_key = _first_money(
            value,
            ("unit_price_cents", "price_cents", "amount_cents", "cents"),
            item_field,
            signed=True,
        )
        if amount is None:
            raise ValueError(f"{item_field} must include an integer-cent unit price")
        output.append(
            {
                "item": item,
                "unit": value.get("unit"),
                "unit_price_cents": amount,
                "source_field": source_key,
            }
        )
    return output


def _matching_baseline(
    baseline: Sequence[Mapping[str, Any]], scope_key: str, trade_key: str
) -> Mapping[str, Any] | None:
    exact_trade: Mapping[str, Any] | None = None
    unassigned: Mapping[str, Any] | None = None
    for row in baseline:
        if row["scope_key"] != scope_key:
            continue
        if row["trade_key"] == trade_key:
            exact_trade = row
        elif row["trade_key"] is None:
            unassigned = row
    return exact_trade if exact_trade is not None else unassigned


def _median_cents(values: Sequence[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return int(
        ((Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal("2")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def level_bids(
    bids: Sequence[Mapping[str, Any]],
    scope_baseline: Sequence[Any],
) -> dict[str, Any]:
    """Level bids using explicit exclusion plugs and allowance targets.

    The base bid is assumed to contain only what the bidder priced.  A plug is
    always visibly labeled and never promoted to bid evidence.  Missing plugs
    remain zero in arithmetic and are separately reported as unpriced gaps.
    """

    raw_bids = _list(bids, "bids")
    baseline = _baseline(scope_baseline)
    parsed: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_bids):
        if not isinstance(raw, Mapping):
            raise ValueError(f"bids[{index}] must be a dictionary")
        trade = _text(raw.get("trade"), f"bids[{index}].trade")
        contractor = _text(raw.get("contractor"), f"bids[{index}].contractor")
        identity = (_key(trade), contractor.casefold())
        if identity in identities:
            raise ValueError(f"duplicate contractor/trade bid for {contractor!r} / {trade!r}")
        identities.add(identity)
        parsed.append(
            {
                "bid_index": index,
                "trade": trade,
                "trade_key": identity[0],
                "contractor": contractor,
                "base_cents": _money(raw.get("base_cents"), f"bids[{index}].base_cents"),
                "alternates": _alternates(raw.get("alternates", []), f"bids[{index}].alternates"),
                "allowances": _allowances(raw.get("allowances", []), f"bids[{index}].allowances"),
                "exclusions": _exclusions(raw.get("exclusions", []), f"bids[{index}].exclusions"),
                "unit_prices": _unit_prices(raw.get("unit_prices"), f"bids[{index}].unit_prices"),
            }
        )

    # Normalize each allowance to the highest same-trade submitted amount,
    # overridden upward or downward by an explicit baseline target.
    allowance_targets: dict[tuple[str, str], dict[str, Any]] = {}
    for bid in parsed:
        for allowance in bid["allowances"]:
            identity = (bid["trade_key"], allowance["scope_key"])
            existing = allowance_targets.get(identity)
            if existing is None or allowance["amount_cents"] > existing["target_cents"]:
                allowance_targets[identity] = {
                    "target_cents": allowance["amount_cents"],
                    "source": "highest same-trade submitted allowance",
                    "item": allowance["item"],
                }
    for row in baseline:
        target = row["target_allowance_cents"]
        if target is None:
            continue
        matching_trades = {
            bid["trade_key"]
            for bid in parsed
            if row["trade_key"] is None or bid["trade_key"] == row["trade_key"]
        }
        if row["trade_key"] is not None:
            matching_trades.add(row["trade_key"])
        for trade_key in matching_trades:
            allowance_targets[(trade_key, row["scope_key"])] = {
                "target_cents": target,
                "source": "explicit scope-baseline target",
                "item": row["item"],
            }

    comparisons: list[dict[str, Any]] = []
    scope_gaps: list[dict[str, Any]] = []
    for bid in parsed:
        allowance_normalization: list[dict[str, Any]] = []
        allowance_keys = {allowance["scope_key"] for allowance in bid["allowances"]}
        for allowance in bid["allowances"]:
            target_row = allowance_targets[(bid["trade_key"], allowance["scope_key"])]
            adjustment = target_row["target_cents"] - allowance["amount_cents"]
            allowance_normalization.append(
                {
                    "item": allowance["item"],
                    "submitted_allowance_cents": allowance["amount_cents"],
                    "target_allowance_cents": target_row["target_cents"],
                    "adjustment_cents": adjustment,
                    "target_source": target_row["source"],
                    "is_plug": False,
                    "evidence_tag": "leveling normalization; not a bid revision",
                }
            )
        for (trade_key, scope_key), target_row in allowance_targets.items():
            if trade_key == bid["trade_key"] and scope_key not in allowance_keys:
                scope_gaps.append(
                    {
                        "trade": bid["trade"],
                        "contractor": bid["contractor"],
                        "scope_item": target_row["item"],
                        "gap_type": "allowance_silent",
                        "severity": "high",
                        "note": "Peer/baseline allowance exists but this bid is silent; no add-back was assumed because base scope may differ.",
                    }
                )

        exclusion_plugs: list[dict[str, Any]] = []
        exclusion_keys = {exclusion["scope_key"] for exclusion in bid["exclusions"]}
        for exclusion in bid["exclusions"]:
            baseline_row = _matching_baseline(
                baseline, exclusion["scope_key"], bid["trade_key"]
            )
            supplied = exclusion["supplied_plug_cents"]
            if supplied is not None:
                plug = supplied
                plug_source = "bid input exclusion plug"
            elif baseline_row is not None and baseline_row["plug_cents"] is not None:
                plug = baseline_row["plug_cents"]
                plug_source = "scope-baseline plug"
            else:
                plug = 0
                plug_source = "missing; zero used only to preserve arithmetic"
            is_priced = supplied is not None or (
                baseline_row is not None and baseline_row["plug_cents"] is not None
            )
            plug_row = {
                "item": exclusion["item"],
                "plug_cents": plug,
                "adjustment_cents": plug,
                "plug_source": plug_source,
                "flagged_as_plug": True,
                "is_plug": True,
                "priced": is_priced,
                "evidence_tag": "PLUG — not contractor bid evidence",
            }
            exclusion_plugs.append(plug_row)
            scope_gaps.append(
                {
                    "trade": bid["trade"],
                    "contractor": bid["contractor"],
                    "scope_item": exclusion["item"],
                    "gap_type": "excluded_with_plug" if is_priced else "excluded_unpriced",
                    "severity": "high" if is_priced else "critical",
                    "plug_cents": plug if is_priced else None,
                    "note": (
                        "Excluded baseline scope is represented by a visible leveling plug, not bid coverage."
                        if is_priced
                        else "Excluded scope has no plug; obtain pricing before relying on the leveled total."
                    ),
                }
            )

        scope_assessment: list[dict[str, Any]] = []
        for row in baseline:
            if row["trade_key"] is not None and row["trade_key"] != bid["trade_key"]:
                continue
            if row["scope_key"] in exclusion_keys:
                plug = next(
                    plug for plug in exclusion_plugs if _key(plug["item"]) == row["scope_key"]
                )
                status = "excluded_with_plug" if plug["priced"] else "excluded_unpriced"
            else:
                status = "assumed_in_base_unverified"
            scope_assessment.append({"scope_item": row["item"], "status": status})

        selected_alternates = [alternate for alternate in bid["alternates"] if alternate["selected"]]
        adjustments: list[dict[str, Any]] = []
        adjustments.extend(
            {
                "type": "allowance_normalization",
                "item": row["item"],
                "adjustment_cents": row["adjustment_cents"],
                "is_plug": False,
            }
            for row in allowance_normalization
        )
        adjustments.extend(
            {
                "type": "exclusion_plug",
                "item": row["item"],
                "adjustment_cents": row["adjustment_cents"],
                "is_plug": True,
            }
            for row in exclusion_plugs
        )
        adjustments.extend(
            {
                "type": "selected_alternate",
                "item": row["item"],
                "adjustment_cents": row["adjustment_cents"],
                "is_plug": False,
            }
            for row in selected_alternates
        )
        adjustments_cents = sum(row["adjustment_cents"] for row in adjustments)
        leveled = bid["base_cents"] + adjustments_cents
        comparisons.append(
            {
                "bid_index": bid["bid_index"],
                "trade": bid["trade"],
                "contractor": bid["contractor"],
                "base_cents": bid["base_cents"],
                "adjustments_cents": adjustments_cents,
                "leveled_total_cents": leveled,
                "leveled_cents": leveled,
                "arithmetic_check": bid["base_cents"] + adjustments_cents == leveled,
                "adjustments": adjustments,
                "allowance_normalization": allowance_normalization,
                "exclusion_plugs": exclusion_plugs,
                "alternates": bid["alternates"],
                "unit_prices": bid["unit_prices"],
                "scope_assessment": scope_assessment,
            }
        )

    # Search explicitly named priced/plugged scopes for cross-trade overlap.
    priced_sources: dict[str, list[dict[str, str]]] = defaultdict(list)
    for comparison in comparisons:
        for row in comparison["allowance_normalization"]:
            priced_sources[_key(row["item"])].append(
                {"item": row["item"], "trade": comparison["trade"], "contractor": comparison["contractor"], "source": "allowance"}
            )
        for row in comparison["exclusion_plugs"]:
            if row["priced"]:
                priced_sources[_key(row["item"])].append(
                    {"item": row["item"], "trade": comparison["trade"], "contractor": comparison["contractor"], "source": "exclusion_plug"}
                )
        for row in comparison["alternates"]:
            if row["selected"]:
                priced_sources[row["scope_key"]].append(
                    {"item": row["item"], "trade": comparison["trade"], "contractor": comparison["contractor"], "source": "selected_alternate"}
                )
    double_count_checks: list[dict[str, Any]] = []
    for sources in priced_sources.values():
        trade_keys = {_key(source["trade"]) for source in sources}
        if len(trade_keys) > 1:
            double_count_checks.append(
                {
                    "scope_item": sources[0]["item"],
                    "severity": "high",
                    "flag": "possible_cross_trade_double_count",
                    "sources": sources,
                    "note": "Same named scope appears in more than one trade; GC/CM must assign ownership and remove overlap.",
                }
            )

    by_trade: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comparison in comparisons:
        by_trade[_key(comparison["trade"])].append(comparison)
    spread_analysis: list[dict[str, Any]] = []
    for trade_rows in by_trade.values():
        median = _median_cents([row["leveled_total_cents"] for row in trade_rows])
        low = min(row["leveled_total_cents"] for row in trade_rows)
        for row in trade_rows:
            under_pct = (
                (Decimal(median - row["leveled_total_cents"]) / Decimal(median) * Decimal("100"))
                if median > 0 and row["leveled_total_cents"] == low
                else Decimal("0")
            )
            flagged = under_pct > UNDER_MEDIAN_FLAG_PCT
            reasons: list[str] = []
            if flagged:
                if row["exclusion_plugs"]:
                    reasons.append("review exclusions and whether plugs fully reflect transferred scope")
                if any(gap["contractor"] == row["contractor"] and gap["trade"] == row["trade"] for gap in scope_gaps):
                    reasons.append("resolve scope and allowance gaps")
                reasons.append("GC/CM to verify quantities, labor, schedule, bonding, and bidder error")
            spread_analysis.append(
                {
                    "trade": row["trade"],
                    "contractor": row["contractor"],
                    "leveled_total_cents": row["leveled_total_cents"],
                    "median_leveled_cents": median,
                    "under_median_pct": str(under_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "flagged_low_bid": flagged,
                    "threshold_pct": str(UNDER_MEDIAN_FLAG_PCT),
                    "why_review": reasons,
                }
            )

    return {
        "scope_baseline": [
            {
                "item": row["item"],
                "trade": row["trade"],
                "plug_cents": row["plug_cents"],
                "target_allowance_cents": row["target_allowance_cents"],
            }
            for row in baseline
        ],
        "comparisons": comparisons,
        "leveled_bids": comparisons,
        "scope_gaps": scope_gaps,
        "double_count_checks": double_count_checks,
        "spread_analysis": spread_analysis,
        "methodology": {
            "formula": "base_cents + allowance normalization + explicit exclusion plugs + selected alternates",
            "allowance_target": "explicit baseline target when supplied; otherwise highest submitted same-trade allowance",
            "plug_evidence": "all plugs are flagged and are not contractor bid evidence",
            "low_bid_flag": "strictly more than 15% below same-trade median leveled total",
        },
        "professional_review_flags": [
            {"role": "architect", "status": "required", "reason": "confirm drawing/spec scope ownership and design-intent equivalence"},
            {"role": "engineer", "status": "required", "reason": "confirm discipline scope, quantities, alternates, and delegated design"},
            {"role": "gc", "status": "required", "reason": "validate plugs, trade boundaries, exclusions, bidder qualifications, and double counts"},
            {"role": "inspector", "status": "not_field_verified", "reason": "bid pricing and leveling do not establish installed quantity or quality"},
        ],
        "limitations": [
            "Base-bid scope not expressly listed in the input cannot be independently proven included.",
            "A leveling plug improves arithmetic comparability but is not a quote, award, or committed cost.",
            "Double-count screening is limited to explicitly named allowances, selected alternates, and priced exclusion plugs; base-bid overlap still requires GC/CM review.",
        ],
    }


__all__ = ["UNDER_MEDIAN_FLAG_PCT", "level_bids"]
