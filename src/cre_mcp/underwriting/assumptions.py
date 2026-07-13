"""Overridable underwriting defaults by property type."""

from typing import Any, ClassVar

from pydantic import BaseModel


class UnderwritingAssumptions(BaseModel):
    """Financing and operating assumptions used when listing facts are absent."""

    ltv: float = 0.65
    annual_interest_rate: float = 0.07
    amortization_years: int = 25
    expense_ratio: float = 0.30
    vacancy_rate: float = 0.05
    exit_cap_spread_bps: float = 50.0
    replacement_cost_per_sf: float | None = None
    hold_years: int = 5

    PROPERTY_DEFAULTS: ClassVar[dict[str, dict[str, Any]]] = {
        "multifamily": {
            "ltv": 0.70,
            "annual_interest_rate": 0.065,
            "amortization_years": 30,
            "expense_ratio": 0.40,
            "vacancy_rate": 0.05,
        },
        "retail": {
            "ltv": 0.65,
            "annual_interest_rate": 0.07,
            "amortization_years": 25,
            "expense_ratio": 0.20,
            "vacancy_rate": 0.05,
        },
        "industrial": {
            "ltv": 0.65,
            "annual_interest_rate": 0.07,
            "amortization_years": 25,
            "expense_ratio": 0.25,
            "vacancy_rate": 0.05,
        },
        "office": {
            "ltv": 0.65,
            "annual_interest_rate": 0.07,
            "amortization_years": 25,
            "expense_ratio": 0.35,
            "vacancy_rate": 0.10,
        },
        "hospitality": {
            "ltv": 0.60,
            "annual_interest_rate": 0.075,
            "amortization_years": 20,
            "expense_ratio": 0.55,
            "vacancy_rate": 0.15,
        },
    }

    @classmethod
    def for_property_type(
        cls,
        property_type: str | None,
        overrides: dict[str, Any] | None = None,
    ) -> "UnderwritingAssumptions":
        """Build defaults for a property type, then apply caller overrides."""
        values = dict(cls.PROPERTY_DEFAULTS.get((property_type or "").casefold(), {}))
        values.update(overrides or {})
        return cls(**values)
