"""Deterministic post-transaction fund mandate and side-letter checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.execution.guardrails import capital_guardrail

_AMOUNT_FIELDS = (
    "value_cents",
    "gross_asset_value_cents",
    "investment_cents",
    "exposure_cents",
    "cost_cents",
    "purchase_price_cents",
    "basis_cents",
    "value",
    "gross_asset_value",
    "investment",
    "exposure",
    "cost",
    "purchase_price",
    "basis",
)
_DEBT_FIELDS = ("debt_cents", "loan_balance_cents", "debt", "loan_balance")


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    try:
        result = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _pct(value: Any, label: str) -> Decimal:
    number = _decimal(value, label)
    normalized = number * 100 if number <= 1 else number
    if normalized < 0 or normalized > 100:
        raise ValueError(f"{label} must be between 0% and 100%")
    return normalized


def _output_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    return int(integral) if value == integral else float(value)


def _output_pct(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001")))


def _field_amount(
    values: Mapping[str, Any],
    fields: Sequence[str],
    label: str,
    *,
    required: bool,
) -> tuple[Decimal | None, str | None, str | None]:
    for field in fields:
        if field in values and values[field] is not None:
            amount = _decimal(values[field], f"{label}.{field}")
            if amount < 0:
                raise ValueError(f"{label}.{field} cannot be negative")
            unit = "cents" if field.endswith("_cents") else "currency_units"
            return amount, field, unit
    if required:
        raise ValueError(f"{label} must supply an exposure amount")
    return None, None, None


def _asset_rows(
    portfolio: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    proposed_deal: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    if isinstance(portfolio, Mapping):
        metadata = portfolio
        raw_assets = portfolio.get("assets", portfolio.get("portfolio", []))
    else:
        metadata = {}
        raw_assets = portfolio
    if not isinstance(raw_assets, Sequence) or isinstance(raw_assets, (str, bytes)):
        raise ValueError("portfolio must be a list of assets or a mapping containing assets")
    if not isinstance(proposed_deal, Mapping):
        raise ValueError("proposed_deal must be a mapping")

    rows: list[dict[str, Any]] = []
    for index, raw in enumerate([*raw_assets, proposed_deal]):
        if not isinstance(raw, Mapping):
            raise ValueError("every portfolio asset must be a mapping")
        proposed = index == len(raw_assets)
        label = "proposed_deal" if proposed else f"portfolio[{index}]"
        amount, amount_field, unit = _field_amount(
            raw, _AMOUNT_FIELDS, label, required=True
        )
        debt, debt_field, debt_unit = _field_amount(
            raw, _DEBT_FIELDS, label, required=False
        )
        if debt is not None and debt_unit != unit:
            raise ValueError(f"{label} debt and exposure amounts must use the same unit")
        rows.append(
            {
                "name": str(
                    raw.get("asset")
                    or raw.get("name")
                    or raw.get("deal")
                    or raw.get("property")
                    or raw.get("id")
                    or label
                ),
                "amount": amount,
                "amount_field": amount_field,
                "unit": unit,
                "debt": debt,
                "debt_field": debt_field,
                "geography": raw.get("geography")
                or raw.get("market")
                or raw.get("state"),
                "asset_type": raw.get("asset_type") or raw.get("property_type"),
                "proposed": proposed,
                "source": raw.get("source")
                or raw.get("source_label")
                or "caller-supplied mandate input",
            }
        )
    units = {row["unit"] for row in rows}
    if len(units) != 1:
        raise ValueError("all portfolio and proposed exposure amounts must use one unit")
    if sum((row["amount"] for row in rows), Decimal(0)) <= 0:
        raise ValueError("post-transaction portfolio exposure must be greater than zero")
    return rows, metadata


def _limit_entries(value: Any, label: str) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return [(str(key), item) for key, item in value.items()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        entries: list[tuple[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise ValueError(f"{label}[{index}] must be a mapping")
            category = item.get("name") or item.get("geography") or item.get("asset_type")
            maximum = item.get("max_pct", item.get("limit_pct", item.get("max")))
            if category is None or maximum is None:
                raise ValueError(f"{label}[{index}] must supply a category and max_pct")
            entries.append((str(category), maximum))
        return entries
    raise ValueError(f"{label} must be a mapping or list of limit mappings")


def _category_checks(
    *,
    rows: Sequence[Mapping[str, Any]],
    total: Decimal,
    rules: Any,
    field: str,
    label: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for category, raw_limit in _limit_entries(rules, label):
        limit_pct = _pct(
            raw_limit.get("max_pct", raw_limit.get("limit_pct", raw_limit.get("max")))
            if isinstance(raw_limit, Mapping)
            else raw_limit,
            f"{label}.{category}",
        )
        amount = sum(
            (
                row["amount"]
                for row in rows
                if str(row.get(field) or "").strip().casefold()
                == category.strip().casefold()
            ),
            Decimal(0),
        )
        exposure = amount * 100 / total
        passed = exposure <= limit_pct
        checks.append(
            {
                "limit": f"{label}.{category}",
                "category": category,
                "passed": passed,
                "status": "pass" if passed else "fail",
                "computed_exposure_pct": _output_pct(exposure),
                "limit_pct": _output_pct(limit_pct),
                "computed_exposure_amount": _output_number(amount),
                "calculation": f"{_output_number(amount)} / {_output_number(total)}",
            }
        )
    return checks


def _key_person_check(
    rule: Any,
    portfolio_metadata: Mapping[str, Any],
    proposed_deal: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(rule, Mapping):
        required_name = rule.get("name") or rule.get("person")
        active = rule.get("active")
        if active is None:
            active = rule.get("satisfied")
    elif isinstance(rule, str):
        required_name = rule
        active = None
    elif isinstance(rule, bool):
        required_name = None
        active = None if rule else True
    else:
        raise ValueError("key_person must be a bool, name, or mapping")
    if active is None:
        active = proposed_deal.get(
            "key_person_active", portfolio_metadata.get("key_person_active")
        )
    if active is None:
        return {
            "limit": "key_person",
            "passed": False,
            "status": "insufficient_data",
            "required_person": required_name,
            "computed_active": None,
            "detail": "No caller-supplied key-person status was available.",
        }
    passed = bool(active)
    return {
        "limit": "key_person",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "required_person": required_name,
        "computed_active": bool(active),
    }


def _side_letter_reviews(
    side_letters: Any,
    rows: Sequence[Mapping[str, Any]],
    total: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if side_letters is None:
        return [], []
    if not isinstance(side_letters, Sequence) or isinstance(side_letters, (str, bytes)):
        raise ValueError("side_letters must be a list of mappings")
    reviews: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for index, side_letter in enumerate(side_letters):
        if not isinstance(side_letter, Mapping):
            raise ValueError(f"side_letters[{index}] must be a mapping")
        investor = str(side_letter.get("investor") or "").strip()
        if not investor:
            raise ValueError(f"side_letters[{index}].investor cannot be blank")
        provision = side_letter.get("provision")
        review: dict[str, Any] = {
            "investor": investor,
            "provision": provision,
            "status": "review_required",
            "conflicts": [],
        }
        if isinstance(provision, Mapping):
            provision_checks: list[dict[str, Any]] = []
            if provision.get("max_single_asset_pct") is not None:
                limit_pct = _pct(
                    provision["max_single_asset_pct"],
                    f"side_letters[{index}].max_single_asset_pct",
                )
                max_row = max(rows, key=lambda row: row["amount"])
                exposure = max_row["amount"] * 100 / total
                provision_checks.append(
                    {
                        "provision": "max_single_asset_pct",
                        "computed_exposure_pct": _output_pct(exposure),
                        "limit_pct": _output_pct(limit_pct),
                        "passed": exposure <= limit_pct,
                        "asset": max_row["name"],
                    }
                )
            for field, key in (
                ("geography", "geography_limits"),
                ("asset_type", "asset_type_limits"),
            ):
                if provision.get(key) is not None:
                    provision_checks.extend(
                        _category_checks(
                            rows=rows,
                            total=total,
                            rules=provision[key],
                            field=field,
                            label=key,
                        )
                    )
            for field, key in (
                ("geography", "prohibited_geographies"),
                ("asset_type", "prohibited_asset_types"),
            ):
                prohibited = provision.get(key, [])
                if prohibited:
                    if not isinstance(prohibited, Sequence) or isinstance(
                        prohibited, (str, bytes)
                    ):
                        raise ValueError(f"side_letters[{index}].{key} must be a list")
                    for category in prohibited:
                        matching = [
                            row["name"]
                            for row in rows
                            if str(row.get(field) or "").strip().casefold()
                            == str(category).strip().casefold()
                        ]
                        provision_checks.append(
                            {
                                "provision": key,
                                "category": category,
                                "passed": not matching,
                                "matching_assets": matching,
                            }
                        )
            failed = [check for check in provision_checks if not check["passed"]]
            review["checks"] = provision_checks
            review["conflicts"] = failed
            review["status"] = "conflict" if failed else "no_numeric_conflict_found"
            if failed:
                conflicts.append(
                    {
                        "investor": investor,
                        "provision": provision,
                        "failed_checks": failed,
                        "counsel_action": "Review with fund counsel before approving the proposed deal.",
                    }
                )
        else:
            review["detail"] = (
                "Unstructured provision was surfaced verbatim; no legal interpretation was inferred."
            )
        reviews.append(review)
    return reviews, conflicts


def check_mandate_limits(
    fund_rules: Mapping[str, Any],
    portfolio: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    proposed_deal: Mapping[str, Any],
) -> dict[str, Any]:
    """Check post-deal concentration, leverage, key-person, and side-letter limits."""
    if not isinstance(fund_rules, Mapping):
        raise ValueError("fund_rules must be a mapping")
    reject_unsubstantiated_performance_claims(fund_rules, portfolio, proposed_deal)
    rows, portfolio_metadata = _asset_rows(portfolio, proposed_deal)
    total = sum((row["amount"] for row in rows), Decimal(0))
    unit = rows[0]["unit"]
    limits: list[dict[str, Any]] = []

    if fund_rules.get("max_single_asset_pct") is not None:
        limit_pct = _pct(
            fund_rules["max_single_asset_pct"], "max_single_asset_pct"
        )
        max_row = max(rows, key=lambda row: row["amount"])
        exposure = max_row["amount"] * 100 / total
        passed = exposure <= limit_pct
        limits.append(
            {
                "limit": "max_single_asset_pct",
                "passed": passed,
                "status": "pass" if passed else "fail",
                "asset": max_row["name"],
                "proposed_deal_is_max": max_row["proposed"],
                "computed_exposure_pct": _output_pct(exposure),
                "limit_pct": _output_pct(limit_pct),
                "computed_exposure_amount": _output_number(max_row["amount"]),
                "calculation": (
                    f"{_output_number(max_row['amount'])} / {_output_number(total)}"
                ),
            }
        )

    if fund_rules.get("geography_limits") is not None:
        limits.extend(
            _category_checks(
                rows=rows,
                total=total,
                rules=fund_rules["geography_limits"],
                field="geography",
                label="geography_limits",
            )
        )
    if fund_rules.get("asset_type_limits") is not None:
        limits.extend(
            _category_checks(
                rows=rows,
                total=total,
                rules=fund_rules["asset_type_limits"],
                field="asset_type",
                label="asset_type_limits",
            )
        )

    if fund_rules.get("max_leverage") is not None:
        leverage_limit = _pct(fund_rules["max_leverage"], "max_leverage")
        missing_debt = [row["name"] for row in rows if row["debt"] is None]
        if missing_debt:
            limits.append(
                {
                    "limit": "max_leverage",
                    "passed": False,
                    "status": "insufficient_data",
                    "limit_pct": _output_pct(leverage_limit),
                    "computed_exposure_pct": None,
                    "missing_debt_inputs": missing_debt,
                }
            )
        else:
            total_debt = sum((row["debt"] for row in rows), Decimal(0))
            leverage = total_debt * 100 / total
            passed = leverage <= leverage_limit
            limits.append(
                {
                    "limit": "max_leverage",
                    "passed": passed,
                    "status": "pass" if passed else "fail",
                    "computed_exposure_pct": _output_pct(leverage),
                    "limit_pct": _output_pct(leverage_limit),
                    "total_debt": _output_number(total_debt),
                    "calculation": (
                        f"{_output_number(total_debt)} / {_output_number(total)}"
                    ),
                }
            )

    if fund_rules.get("key_person") is not None:
        limits.append(
            _key_person_check(
                fund_rules["key_person"], portfolio_metadata, proposed_deal
            )
        )

    side_letter_reviews, side_letter_conflicts = _side_letter_reviews(
        fund_rules.get("side_letters", []), rows, total
    )
    unresolved_side_letters = [
        review
        for review in side_letter_reviews
        if review["status"] == "review_required"
    ]
    breaches = [check for check in limits if not check["passed"]]
    passed = not breaches and not side_letter_conflicts and not unresolved_side_letters
    counsel_flags: list[str] = []
    if breaches:
        counsel_flags.append(
            "REVIEW WITH FUND COUNSEL — one or more mandate limits failed or lacked required inputs; do not approve the proposed deal until resolved."
        )
    if side_letter_conflicts:
        counsel_flags.append(
            "REVIEW WITH FUND COUNSEL — one or more investor side-letter provisions conflict with the computed post-deal exposures."
        )
    if side_letter_reviews:
        counsel_flags.append(
            "All side-letter provisions require fund-counsel interpretation; unstructured text was surfaced without inferring legal meaning."
        )

    if breaches or side_letter_conflicts:
        overall_status = "fail"
    elif unresolved_side_letters:
        overall_status = "review_required"
    else:
        overall_status = "pass"

    return {
        "passed": passed,
        "overall_status": overall_status,
        "limits": limits,
        "breaches": breaches,
        "post_transaction": {
            "total_exposure": _output_number(total),
            "exposure_basis_unit": unit,
            "assets": [
                {
                    "name": row["name"],
                    "exposure_amount": _output_number(row["amount"]),
                    "exposure_field": row["amount_field"],
                    "geography": row["geography"],
                    "asset_type": row["asset_type"],
                    "proposed": row["proposed"],
                    "source": row["source"],
                }
                for row in rows
            ],
        },
        "side_letter_reviews": side_letter_reviews,
        "side_letter_conflicts": side_letter_conflicts,
        "unresolved_side_letters": unresolved_side_letters,
        "counsel_flags": counsel_flags,
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Treat this as an arithmetic screen only; fund/securities counsel must interpret "
            "the partnership agreement, mandate, key-person provisions, and every side letter before approval."
        ),
    }


__all__ = ["check_mandate_limits"]
