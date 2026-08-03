"""Package a master-lease control position for an exit discussion.

The value indication capitalizes only the net spread and then shows the effect
of the remaining contractual term.  It is a disclosed arithmetic convention,
not an appraisal, market quote, assignability conclusion, or legal opinion.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

CONVENTION_CAP_RATE_LOW = Decimal("0.10")
CONVENTION_CAP_RATE_HIGH = Decimal("0.15")

_MONEY_CONTAINERS = (
    "economics",
    "position_status",
    "status",
    "financials",
    "rent_owed_vs_received_exposure",
)


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _first(position: Mapping[str, Any], *keys: str) -> tuple[Any, str | None]:
    for key in keys:
        if key in position and position[key] is not None:
            return position[key], key
    for container_name in _MONEY_CONTAINERS:
        nested = position.get(container_name)
        if not isinstance(nested, Mapping):
            continue
        for key in keys:
            if key in nested and nested[key] is not None:
                return nested[key], f"{container_name}.{key}"
    return None, None


def _cents(
    value: Any,
    *,
    name: str,
    nullable: bool = True,
    signed: bool = False,
) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if not signed and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal rate")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal rate") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal rate")
    return result


def _cap_rates(position: Mapping[str, Any]) -> tuple[Decimal, Decimal, str]:
    raw, source = _first(
        position,
        "spread_cap_rate_range",
        "cap_rate_range",
        "exit_cap_rate_range",
    )
    if raw is None:
        return (
            CONVENTION_CAP_RATE_LOW,
            CONVENTION_CAP_RATE_HIGH,
            "module convention; not a market observation",
        )
    if isinstance(raw, Mapping):
        low_raw = raw.get("low", raw.get("minimum"))
        high_raw = raw.get("high", raw.get("maximum"))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
        low_raw, high_raw = raw
    else:
        raise ValueError("cap_rate_range must be a two-item sequence or low/high mapping")
    low = _decimal(low_raw, name="cap_rate_range low")
    high = _decimal(high_raw, name="cap_rate_range high")
    if low <= 0 or high <= 0 or low > high or high >= 1:
        raise ValueError(
            "cap_rate_range must use decimal rates greater than 0 and less than 1, "
            "with low no greater than high"
        )
    return low, high, str(source)


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _temporal_date(value: Any, *, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be an ISO date or datetime")
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date or datetime") from exc


def _remaining_term(position: Mapping[str, Any]) -> tuple[int | None, str, list[str]]:
    gaps: list[str] = []
    explicit, source = _first(
        position, "remaining_term_months", "term_remaining_months"
    )
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit < 0:
            raise ValueError("remaining_term_months must be a non-negative integer")
        return explicit, str(source), gaps

    term_raw, term_source = _first(position, "term_months")
    if term_raw is None:
        return None, "missing", ["remaining_term_months_or_term_months_missing"]
    if isinstance(term_raw, bool) or not isinstance(term_raw, int) or term_raw < 0:
        raise ValueError("term_months must be a non-negative integer")
    started_raw, started_source = _first(position, "started_at", "commenced_at")
    if started_raw is None:
        gaps.append(
            "started_at_missing; full original term is shown as a remaining-term convention"
        )
        return term_raw, f"{term_source}; original term convention", gaps
    started = _temporal_date(started_raw, name="started_at")
    as_of_raw, as_of_source = _first(position, "as_of", "exit_as_of")
    as_of = _temporal_date(as_of_raw, name="as_of") if as_of_raw is not None else date.today()
    elapsed = (as_of.year - started.year) * 12 + as_of.month - started.month
    if as_of.day < started.day:
        elapsed -= 1
    elapsed = max(0, elapsed)
    remaining = max(0, term_raw - elapsed)
    basis = f"derived from {term_source}, {started_source}, and {as_of_source or 'system date'}"
    if as_of_raw is None:
        gaps.append("as_of_missing; system date used for remaining-term derivation")
    return remaining, basis, gaps


def _spread_economics(position: Mapping[str, Any]) -> dict[str, Any]:
    explicit, explicit_source = _first(
        position, "net_annual_spread_cents", "annual_net_spread_cents"
    )
    if explicit is not None:
        net = _cents(explicit, name=str(explicit_source), nullable=False, signed=True)
        return {
            "net_annual_spread_cents": net,
            "annual_sublease_received_cents": None,
            "annual_master_rent_cents": None,
            "annual_expenses_cents": None,
            "basis": f"explicit {explicit_source}",
            "revenue_basis": "provided net spread",
            "gaps": [],
        }

    annual_received_raw, annual_received_source = _first(
        position,
        "annual_sublease_received_cents",
        "sublease_received_annual_cents",
    )
    annual_billed_raw, annual_billed_source = _first(
        position,
        "annual_sublease_billed_cents",
        "sublease_billed_annual_cents",
    )
    master_annual_raw, master_annual_source = _first(
        position, "annual_master_rent_cents", "master_rent_annual_cents"
    )
    expenses_annual_raw, expenses_annual_source = _first(
        position,
        "annual_expenses_cents",
        "expense_annual_cents",
        "operating_expenses_annual_cents",
    )

    revenue_raw = annual_received_raw
    revenue_source = annual_received_source
    revenue_basis = "cash received"
    if revenue_raw is None and annual_billed_raw is not None:
        revenue_raw = annual_billed_raw
        revenue_source = annual_billed_source
        revenue_basis = "billed, not cash received"

    monthly_mode = revenue_raw is None
    if monthly_mode:
        monthly_received_raw, monthly_received_source = _first(
            position, "monthly_sublease_received_cents", "sublease_received_cents"
        )
        monthly_billed_raw, monthly_billed_source = _first(
            position, "monthly_sublease_billed_cents", "sublease_billed_cents"
        )
        revenue_raw = monthly_received_raw
        revenue_source = monthly_received_source
        revenue_basis = "cash received; one-period amount annualized by 12"
        if revenue_raw is None and monthly_billed_raw is not None:
            revenue_raw = monthly_billed_raw
            revenue_source = monthly_billed_source
            revenue_basis = "billed, not cash received; one-period amount annualized by 12"

    gaps: list[str] = []
    if revenue_raw is None:
        gaps.append("sublease_received_or_billed_cents_missing")
        revenue = None
    else:
        revenue = _cents(revenue_raw, name=str(revenue_source), nullable=False)
        if monthly_mode:
            assert revenue is not None
            revenue *= 12

    if master_annual_raw is not None:
        master = _cents(
            master_annual_raw, name=str(master_annual_source), nullable=False
        )
    else:
        master_monthly_raw, master_monthly_source = _first(
            position,
            "monthly_master_rent_cents",
            "master_rent_cents",
            "master_rent_due_cents",
            "master_rent_owed_cents",
        )
        master_monthly = _cents(
            master_monthly_raw,
            name=str(master_monthly_source or "master_rent_cents"),
        )
        master = master_monthly * 12 if master_monthly is not None else None
        master_annual_source = (
            f"{master_monthly_source} annualized by 12" if master_monthly_source else None
        )
    if master is None:
        gaps.append("master_rent_cents_missing")

    if expenses_annual_raw is not None:
        expenses = _cents(
            expenses_annual_raw, name=str(expenses_annual_source), nullable=False
        )
    else:
        expenses_monthly_raw, expenses_monthly_source = _first(
            position,
            "monthly_expenses_cents",
            "monthly_expense_cents",
            "expense_cents",
            "expenses_cents",
        )
        expenses_monthly = _cents(
            expenses_monthly_raw,
            name=str(expenses_monthly_source or "expenses_cents"),
        )
        expenses = expenses_monthly * 12 if expenses_monthly is not None else 0
        expenses_annual_source = (
            f"{expenses_monthly_source} annualized by 12"
            if expenses_monthly_source
            else "zero-expense convention"
        )
        if expenses_monthly is None:
            gaps.append("expenses_missing; zero used only as a disclosed arithmetic convention")

    net = revenue - master - expenses if revenue is not None and master is not None else None
    return {
        "net_annual_spread_cents": net,
        "annual_sublease_received_cents": revenue,
        "annual_master_rent_cents": master,
        "annual_expenses_cents": expenses,
        "basis": {
            "revenue": revenue_source,
            "master_rent": master_annual_source,
            "expenses": expenses_annual_source,
        },
        "revenue_basis": revenue_basis if revenue_raw is not None else "missing",
        "gaps": gaps,
    }


def _exposure(position: Mapping[str, Any], spread: Mapping[str, Any]) -> dict[str, Any]:
    owed_raw, owed_source = _first(
        position,
        "master_rent_due_cents",
        "master_rent_owed_cents",
        "monthly_master_rent_cents",
        "master_rent_cents",
    )
    received_raw, received_source = _first(
        position, "sublease_received_cents", "monthly_sublease_received_cents"
    )
    owed = _cents(owed_raw, name=str(owed_source or "master_rent_due_cents"))
    received = _cents(
        received_raw, name=str(received_source or "sublease_received_cents")
    )
    if owed is None:
        annual_owed = spread.get("annual_master_rent_cents")
        owed = _round_cents(Decimal(annual_owed) / Decimal(12)) if annual_owed is not None else None
        owed_source = "annual master rent divided by 12" if owed is not None else None
    if received is None:
        annual_received = spread.get("annual_sublease_received_cents")
        received = (
            _round_cents(Decimal(annual_received) / Decimal(12))
            if annual_received is not None
            else None
        )
        received_source = "annual receipts divided by 12" if received is not None else None
    shortfall = (
        max(0, owed - received) if owed is not None and received is not None else None
    )
    return {
        "risk": (
            "Master rent remains owed when sublease rent is late, uncollected, or lost; "
            "the buyer acquires that negative-carry exposure with the position."
        ),
        "period_master_rent_owed_cents": owed,
        "period_sublease_rent_received_cents": received,
        "period_rent_shortfall_cents": shortfall,
        "basis": {"owed": owed_source, "received": received_source},
    }


def _consent_screen(position: Mapping[str, Any]) -> tuple[Any, list[Any], list[str]]:
    lease_text = position.get("lease_text")
    loan_terms = position.get("loan_terms")
    explicit = position.get("consents_required")
    required: list[Any]
    if explicit is None:
        required = []
    elif isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        required = list(explicit)
    else:
        raise ValueError("consents_required must be a JSON list when supplied")
    gaps: list[str] = []
    if lease_text is None and loan_terms is None:
        gaps.append(
            "lease_text_and_loan_terms_missing; job 214 transfer-consent screen did not run"
        )
        return None, required, gaps
    if lease_text is not None and not isinstance(lease_text, str):
        raise TypeError("lease_text must be a string when supplied")
    if loan_terms is not None and not isinstance(loan_terms, Mapping):
        raise TypeError("loan_terms must be a mapping when supplied")
    try:
        from cre_mcp.obligations.tools import screen_transfer_consents

        screen = screen_transfer_consents(
            lease_text=lease_text,
            loan_terms=loan_terms,
            intended="assignment",
        )
    except Exception as exc:  # The package remains usable while exposing the gap.
        gaps.append(
            "job 214 transfer-consent screen failed: "
            f"{str(exc) or exc.__class__.__name__}"
        )
        return None, required, gaps
    screened_required = screen.get("required_consents", [])
    if isinstance(screened_required, list):
        required.extend(screened_required)
    else:
        gaps.append("job 214 consent output did not contain a required_consents list")
    screen_gaps = screen.get("honesty", {}).get("gaps", [])
    if isinstance(screen_gaps, list):
        gaps.extend(str(gap) for gap in screen_gaps)
    return screen, required, gaps


def package_control_exit(
    position: Mapping[str, Any],
    buyer_view: bool,
) -> dict[str, Any]:
    """Build a JSON-friendly assignment package with disclosed value assumptions."""

    position = _mapping(position, name="position")
    if not isinstance(buyer_view, bool):
        raise ValueError("buyer_view must be a boolean")

    spread = _spread_economics(position)
    exposure = _exposure(position, spread)
    remaining_months, remaining_basis, term_gaps = _remaining_term(position)
    cap_low, cap_high, cap_source = _cap_rates(position)
    annual_net = spread["net_annual_spread_cents"]

    capitalized_low: int | None = None
    capitalized_high: int | None = None
    remaining_net: int | None = None
    indicated_low: int | None = None
    indicated_high: int | None = None
    if annual_net is not None and annual_net >= 0:
        capitalized_low = _round_cents(Decimal(annual_net) / cap_high)
        capitalized_high = _round_cents(Decimal(annual_net) / cap_low)
        if remaining_months is not None:
            remaining_net = _round_cents(
                Decimal(annual_net) * Decimal(remaining_months) / Decimal(12)
            )
            indicated_low = min(capitalized_low, remaining_net)
            indicated_high = min(capitalized_high, remaining_net)

    consent_screen, consents_required, consent_gaps = _consent_screen(position)
    position_id = position.get("position_id")
    security_raw, security_source = _first(position, "security_cents")
    reserves_raw, reserves_source = _first(
        position, "reserves_cents", "stated_reserves_cents", "reserve_balance_cents"
    )
    security_cents = _cents(
        security_raw, name=str(security_source or "security_cents")
    )
    reserves_cents = _cents(
        reserves_raw, name=str(reserves_source or "reserves_cents")
    )

    risks = [
        {
            "risk": "negative_carry",
            "detail": (
                "Master rent continues even when sublease receipts stop; confirm current "
                "collections, arrears, reserves, and guaranties."
            ),
        },
        {
            "risk": "subtenant_credit_and_concentration",
            "detail": (
                "The indicated spread is only as durable as subtenant payment, occupancy, "
                "renewal, and enforceable credit support."
            ),
        },
        {
            "risk": "assignment_and_change_of_control_consents",
            "detail": (
                "Landlord, lender, subtenant, or other consent may be required; use the "
                "cited job 214 screen and signed documents before structuring a transfer."
            ),
        },
        {
            "risk": "wasting_term_and_reversion",
            "detail": (
                "A control position is term-limited. Straight capitalization can overstate "
                "value because no residual property ownership is assumed."
            ),
        },
        {
            "risk": "owner_default_casualty_and_condemnation",
            "detail": (
                "Owner performance, casualty, condemnation, termination, restoration, and "
                "rent-abatement rights can interrupt the modeled spread."
            ),
        },
    ]
    if annual_net is not None and annual_net < 0:
        risks.insert(
            1,
            {
                "risk": "non_positive_net_spread",
                "detail": (
                    "The supplied economics produce negative annual net spread; a positive "
                    "spread capitalization indication is not shown."
                ),
            },
        )
    if "billed, not cash received" in str(spread["revenue_basis"]):
        risks.insert(
            1,
            {
                "risk": "billing_is_not_collection",
                "detail": (
                    "The spread uses billed rent because cash receipts were absent; this can "
                    "materially overstate transferable cash flow."
                ),
            },
        )

    assumptions_and_gaps = [*spread["gaps"], *term_gaps, *consent_gaps]
    assignable_summary = {
        "position_id": str(position_id) if position_id is not None else None,
        "net_annual_spread_cents": annual_net,
        "net_spread_components": {
            "annual_sublease_received_cents": spread[
                "annual_sublease_received_cents"
            ],
            "annual_master_rent_cents": spread["annual_master_rent_cents"],
            "annual_expenses_cents": spread["annual_expenses_cents"],
            "basis": spread["basis"],
            "revenue_basis": spread["revenue_basis"],
        },
        "spread_cap_rate_range": {
            "low": str(cap_low),
            "high": str(cap_high),
            "source": cap_source,
        },
        "spread_capitalization_value_range_cents": {
            "low": capitalized_low,
            "high": capitalized_high,
        },
        "remaining_term_months": remaining_months,
        "remaining_term_basis": remaining_basis,
        "undiscounted_remaining_net_spread_cents": remaining_net,
        "term_limited_value_indication_range_cents": {
            "low": indicated_low,
            "high": indicated_high,
        },
        "cash_accounts_not_included_in_indication": {
            "security_cents": security_cents,
            "reserves_cents": reserves_cents,
        },
        "convention_note": (
            "Value equals annual net spread divided by the stated cap-rate range. "
            "The term-limited indication is capped at undiscounted remaining spread; "
            "neither calculation discounts monthly cash flow, prices default risk, or "
            "adds a property residual."
        ),
    }

    buyer_gets = [
        "Only assignable master-lease and sublease rights actually transferred under executed documents.",
        "The remaining net-spread opportunity, subject to collection, vacancy, expense, and cure risk.",
        "Operational records, deposits, reserves, receivables, options, and claims only to the extent expressly included and transferable.",
    ]
    buyer_assumes = [
        "Master rent and other master-tenant payment duties regardless of subtenant collection.",
        "Performance, maintenance, insurance, use, notice, cure, surrender, and indemnity duties allocated by the signed documents.",
        "Subtenant administration and sandwich risk: a downstream breach can become an owner-side default.",
        "Remaining-term, consent, owner-credit, casualty, condemnation, and termination exposure.",
    ]

    return {
        "rent_owed_vs_received_exposure": exposure,
        "assignable_value_summary": assignable_summary,
        "buyer_view": buyer_view,
        "view_note": (
            "Buyer diligence view: verify every transferred right, assumed duty, cash-flow "
            "input, cure item, and consent before pricing."
            if buyer_view
            else "Seller packaging view: disclose economics, defaults, duties, and consent dependencies without presenting the position as cleared or guaranteed."
        ),
        "consents_required": consents_required,
        "consent_screen": consent_screen,
        "consent_cross_link": {
            "module": "cre_mcp.obligations.tools.screen_transfer_consents",
            "checklist_job": 214,
            "note": (
                "Run the cited transfer-consent screen against complete lease and loan "
                "documents; its output is issue spotting, not legal consent clearance."
            ),
        },
        "buyer_gets": buyer_gets,
        "buyer_assumes": buyer_assumes,
        "honest_risks": risks,
        "honesty": {
            "posture": (
                "Scenario and arithmetic packaging only; no appraisal, fairness opinion, "
                "marketability, enforceability, assignability, tax, accounting, or legal conclusion."
            ),
            "assumptions_and_gaps": assumptions_and_gaps,
            "cap_rate_is_a_convention": cap_source.startswith("module convention"),
            "cash_flow_and_documents_require_verification": True,
            "counsel_review_required": True,
        },
    }


__all__ = [
    "CONVENTION_CAP_RATE_LOW",
    "CONVENTION_CAP_RATE_HIGH",
    "package_control_exit",
]
