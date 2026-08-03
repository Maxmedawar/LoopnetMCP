"""Shared anti-fraud refusal checks for capital outputs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

ANTI_FRAUD_WARNING = (
    "MODELED OR TARGET RETURNS ARE SCENARIOS, NOT PROMISES. No performance outcome is "
    "assured; verify all inputs and disclose material risks, conflicts, fees, assumptions, "
    "and the possibility of partial or total loss."
)

_BLOCKED_KEYS = {
    "guaranteed_return",
    "return_guarantee",
    "guaranteed_irr",
    "guaranteed_yield",
    "performance_guarantee",
    "promised_return",
    "risk_free",
    "no_risk",
}
_BLOCKED_TEXT = re.compile(
    r"(?:guarantee(?:d)?|promise(?:d)?|assure(?:d)?)\s+(?:return|irr|yield|profit|performance)"
    r"|(?:return|irr|yield|profit|performance)\s+(?:is\s+)?(?:guarantee(?:d)?|promise(?:d)?|assure(?:d)?)"
    r"|risk[\s-]*free|no[\s-]*risk",
    re.IGNORECASE,
)


def _walk(value: Any) -> list[tuple[str | None, Any]]:
    items: list[tuple[str | None, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().casefold().replace("-", "_").replace(" ", "_")
            items.append((normalized_key, item))
            items.extend(_walk(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            items.extend(_walk(item))
    else:
        items.append((None, value))
    return items


def reject_unsubstantiated_performance_claims(*payloads: Any) -> None:
    """Refuse guarantee/risk-free language before it enters a model or draft."""
    for payload in payloads:
        for key, value in _walk(payload):
            if (
                key in _BLOCKED_KEYS
                and value is not None
                and value is not False
                and value != ""
            ):
                raise ValueError(
                    f"refused anti-fraud claim field '{key}': performance guarantees are not allowed"
                )
            if isinstance(value, str) and _BLOCKED_TEXT.search(value):
                raise ValueError(
                    "refused anti-fraud language: promised, guaranteed, assured, or risk-free "
                    "performance claims are not allowed"
                )


__all__ = [
    "ANTI_FRAUD_WARNING",
    "reject_unsubstantiated_performance_claims",
]
