"""Deterministic counteroffer parsing and novice-safe negotiation coaching."""

from __future__ import annotations

import math
import re
from typing import Any

from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.execution.offer import recommend_offer
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import CounterAdvice
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.underwriting.metrics import mortgage_constant

_MONEY = r"\$?\s*\d(?:[\d,]*\d)?(?:\.\d+)?\s*(?:m(?:illion)?|k|thousand)?"


def _money(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.casefold().replace("$", "").replace(",", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m(?:illion)?|k|thousand)?", normalized)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix and suffix.startswith("m"):
        number *= 1_000_000
    elif suffix in {"k", "thousand"}:
        number *= 1_000
    return number if math.isfinite(number) else None


def _context_money(text: str, labels: str) -> float | None:
    match = re.search(
        rf"(?:{labels})(?:\s+(?:is|of|at|to|equals|=))?[^\d$]{{0,18}}({_MONEY})",
        text,
        re.IGNORECASE,
    )
    return _money(match.group(1)) if match else None


def _days(text: str, labels: str) -> int | None:
    patterns = (
        rf"(?:{labels})\s*(?:period\s*)?(?:of|is|in|:|=|-)?\s*"
        rf"(\d{{1,3}})\s*(?:business\s+)?days?",
        rf"(\d{{1,3}})[-\s]*(?:business\s+)?days?\s*(?:of\s+)?(?:{labels})",
    )
    for pattern in patterns:
        if match := re.search(pattern, text, re.IGNORECASE):
            return int(match.group(1))
    return None


def _parse_counter(text: str) -> dict[str, Any]:
    price = _context_money(
        text,
        r"purchase\s+price|counter(?:offer)?|seller\s+(?:wants|asks)|price",
    )
    if price is None:
        candidates = [_money(item) for item in re.findall(_MONEY, text, re.IGNORECASE)]
        values = [item for item in candidates if item is not None]
        price = max(values) if values else None

    earnest_match = None
    earnest_patterns = (
        rf"(\d+(?:\.\d+)?\s*%|{_MONEY})\s*"
        rf"(?:earnest(?:\s+money)?|deposit|emd)",
        rf"(?:earnest(?:\s+money)?|deposit|emd)[^\d$%]{{0,10}}"
        rf"(\d+(?:\.\d+)?\s*%|{_MONEY})",
    )
    for pattern in earnest_patterns:
        earnest_match = re.search(pattern, text, re.IGNORECASE)
        if earnest_match:
            break
    earnest_amount: float | None = None
    earnest_pct: float | None = None
    if earnest_match:
        raw_earnest = earnest_match.group(1)
        if "%" in raw_earnest:
            earnest_pct = float(raw_earnest.replace("%", "").strip())
        else:
            earnest_amount = _money(raw_earnest)
            if earnest_amount is not None and price:
                earnest_pct = 100 * earnest_amount / price

    lowered = text.casefold()
    go_hard = bool(
        re.search(
            r"non[- ]?refundable|go(?:es)?\s+hard|hard\s+(?:on|at|day)|"
            r"deposit[^.\n]{0,30}(?:hard|non[- ]?refundable)",
            lowered,
        )
    )
    day_one_hard = go_hard and bool(
        re.search(r"day\s*(?:one|1)|immediate(?:ly)?|at\s+(?:signing|execution)", lowered)
    )
    financing_contingency: bool | None = None
    if re.search(
        r"waiv(?:e|ed|ing)[^.\n]{0,20}financ|no\s+financing\s+contingency|"
        r"cash(?:-only|\s+offer)",
        lowered,
    ):
        financing_contingency = False
    elif re.search(
        r"subject\s+to\s+financ|financing\s+contingency|loan\s+contingency",
        lowered,
    ):
        financing_contingency = True

    return {
        "price": price,
        "earnest_amount": earnest_amount,
        "earnest_pct": earnest_pct,
        "dd_days": _days(text, r"due\s+diligence|diligence|inspection|dd"),
        "close_days": _days(
            text,
            r"clos(?:e|ing)|days?\s+to\s+close|after\s+diligence",
        ),
        "go_hard": go_hard,
        "day_one_hard": day_one_hard,
        "financing_contingency": financing_contingency,
    }


def _assumption(ctx: DealContext, key: str) -> float | None:
    if ctx.underwriting is None:
        return None
    item = ctx.underwriting.assumptions_used.get(key)
    value = item.get("value") if isinstance(item, dict) else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _counter_dscr(ctx: DealContext, price: float | None) -> float | None:
    if not price or price <= 0:
        return None
    noi = (
        ctx.underwriting.noi
        if ctx.underwriting and ctx.underwriting.noi is not None
        else ctx.listing.noi_usd
    )
    ltv = _assumption(ctx, "ltv")
    rate = _assumption(ctx, "annual_interest_rate")
    amortization = _assumption(ctx, "amortization_years")
    constant = mortgage_constant(rate, int(amortization) if amortization else None)
    if noi is None or ltv is None or not 0 < ltv < 1 or not constant:
        return None
    debt_service = price * ltv * constant
    return noi / debt_service if debt_service > 0 else None


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    increment = T.COUNTER_PRICE_ROUNDING_INCREMENT
    return math.floor(value / increment) * increment


def _currency(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else "not stated"


def _read(parsed: dict[str, Any]) -> str:
    terms = [f"price {_currency(parsed['price'])}"]
    if parsed["earnest_amount"] is not None:
        terms.append(f"earnest money {_currency(parsed['earnest_amount'])}")
    elif parsed["earnest_pct"] is not None:
        terms.append(f"earnest money {parsed['earnest_pct']:.2f}%")
    if parsed["dd_days"] is not None:
        terms.append(f"{parsed['dd_days']} days of due diligence")
    if parsed["close_days"] is not None:
        terms.append(f"a {parsed['close_days']}-day close")
    if parsed["go_hard"]:
        terms.append("a non-refundable or go-hard deposit")
    if parsed["financing_contingency"] is False:
        terms.append("no financing contingency")
    elif parsed["financing_contingency"] is True:
        terms.append("a financing contingency")
    return "I read the seller's counter as " + ", ".join(terms) + "."


def handle_counter(ctx: DealContext, counter_text: str) -> CounterAdvice:
    """Parse a seller counter and compare it with price, cap, debt, and term gates."""
    if not counter_text.strip():
        raise ValueError("counter_text is required")
    parsed = _parse_counter(counter_text)
    offer = recommend_offer(ctx)
    strategy = str(offer.key_terms.get("strategy", "core"))
    minimum_dscr = T.OFFER_MIN_DSCR_BY_STRATEGY.get(
        strategy,
        T.OFFER_MIN_DSCR_BY_STRATEGY["core"],
    )
    price = parsed["price"]
    counter_cap = (
        100 * ctx.listing.noi_usd / price
        if ctx.listing.noi_usd is not None and price
        else None
    )
    counter_dscr = _counter_dscr(ctx, price)
    red_flags: list[str] = []
    reasoning: list[str] = []

    if parsed["day_one_hard"]:
        red_flags.append(
            "Day-one non-refundable/go-hard deposit: money would be at risk before "
            "title, leases, physical condition, and financing are verified."
        )
    elif parsed["go_hard"]:
        red_flags.append(
            "Go-hard or non-refundable deposit language needs a precise post-diligence trigger."
        )
    if parsed["financing_contingency"] is False:
        red_flags.append(
            "Financing contingency is waived before a written lender commitment."
        )
    if (
        parsed["earnest_pct"] is not None
        and parsed["earnest_pct"] > T.COUNTER_MAX_EARNEST_MONEY_PCT
    ):
        red_flags.append(
            f"Earnest money is {parsed['earnest_pct']:.2f}% of price, above the "
            f"{T.COUNTER_MAX_EARNEST_MONEY_PCT:.2f}% coaching ceiling."
        )
    if parsed["dd_days"] is not None and parsed["dd_days"] < T.COUNTER_MIN_DD_DAYS:
        red_flags.append(
            f"The {parsed['dd_days']}-day diligence period is shorter than the "
            f"{T.COUNTER_MIN_DD_DAYS}-day guardrail."
        )
    if (
        parsed["close_days"] is not None
        and parsed["close_days"] < T.COUNTER_MIN_CLOSE_DAYS
    ):
        red_flags.append(
            f"The {parsed['close_days']}-day closing window is compressed versus the "
            f"{T.COUNTER_MIN_CLOSE_DAYS}-day lender/title guardrail."
        )
    if price is not None and offer.walk_price is not None and price > offer.walk_price:
        red_flags.append(
            f"Counter price {_currency(price)} exceeds the modeled walk price "
            f"of {_currency(offer.walk_price)}."
        )
    if counter_cap is not None and offer.walk_cap is not None and counter_cap < offer.walk_cap:
        reasoning.append(
            f"The counter implies a {counter_cap:.2f}% cap, below the modeled "
            f"{offer.walk_cap:.2f}% walk-cap floor."
        )
    if counter_dscr is not None:
        if counter_dscr < minimum_dscr:
            red_flags.append(
                f"Modeled DSCR is {counter_dscr:.2f}x at the counter, below the "
                f"{minimum_dscr:.2f}x financing guardrail."
            )
        else:
            reasoning.append(
                f"Modeled DSCR is {counter_dscr:.2f}x versus the {minimum_dscr:.2f}x guardrail."
            )
    else:
        reasoning.append("DSCR could not be recomputed because financing or NOI inputs are incomplete.")

    material_term_risk = bool(
        parsed["go_hard"]
        or parsed["financing_contingency"] is False
        or (
            parsed["dd_days"] is not None
            and parsed["dd_days"] < T.COUNTER_MIN_DD_DAYS
        )
    )
    if price is None:
        verdict = "hold"
        reasoning.insert(0, "No reliable purchase price was parsed; clarify a complete written term sheet.")
    elif offer.walk_price is not None and price > offer.walk_price:
        verdict = "walk"
        reasoning.insert(0, "The price is above the modeled ceiling; do not trade safeguards to bridge it.")
    elif counter_dscr is not None and counter_dscr < minimum_dscr:
        verdict = "walk" if offer.walk_price is not None and price >= offer.walk_price else "counter"
        reasoning.insert(0, "The counter does not support the minimum modeled debt coverage.")
    elif (
        offer.target_price is not None
        and price <= offer.target_price * (1 + T.COUNTER_ACCEPT_PRICE_TOLERANCE_PCT)
        and not material_term_risk
    ):
        verdict = "accept"
        reasoning.insert(0, "Price is at or near the modeled target and no material term trap was parsed.")
    else:
        verdict = "counter"
        reasoning.insert(0, "Economics or risk allocation should be moved back to the guarded target terms.")

    suggested_price = None if verdict in {"hold", "walk"} else (
        price if verdict == "accept" else _round_price(offer.target_price)
    )
    suggested_counter = {
        "price": suggested_price,
        "earnest_money_pct": T.OFFER_EARNEST_MONEY_PCT_RANGE[0],
        "due_diligence_days": T.OFFER_DD_DAYS_RANGE[1],
        "closing_days": T.OFFER_CLOSE_DAYS_RANGE[1],
        "deposit_status": "refundable through the diligence period",
        "financing_contingency": "retain until written lender commitment",
    }
    if verdict == "walk":
        response = (
            "Thank you for the counter. I cannot support the proposed economics and "
            "risk allocation within my underwriting, so I am stepping back. Please "
            "contact me if the seller's position changes."
        )
    elif verdict == "hold":
        response = (
            "Thank you. Before I respond economically, please send one complete written "
            "counter stating price, earnest money/refundability, diligence, closing, and "
            "financing-contingency terms."
        )
    else:
        response = (
            f"Thank you for the counter. I can respond at {_currency(suggested_price)}, "
            f"with {T.OFFER_EARNEST_MONEY_PCT_RANGE[0]:.1f}% earnest money refundable "
            f"through {T.OFFER_DD_DAYS_RANGE[1]} days of diligence, a "
            f"{T.OFFER_CLOSE_DAYS_RANGE[1]}-day closing period, and a financing "
            "contingency retained until written lender commitment. All terms remain "
            "subject to documentation and review."
        )
    guardrail = execution_guardrail(
        "confirm the parsed terms against the seller's written counter, have your lender "
        "re-run proceeds, and have CRE counsel review deposit, contingency, default, and "
        "remedy language before acceptance."
    )
    return CounterAdvice(
        read=_read(parsed),
        verdict=verdict,
        suggested_counter=suggested_counter,
        reasoning=reasoning,
        reply_template=f"{response}\n\n{guardrail}",
        red_flags=red_flags,
    )


__all__ = ["handle_counter"]
