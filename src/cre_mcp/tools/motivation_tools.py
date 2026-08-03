"""Unregistered Phase 29 MCP-compatible wrappers for motivation scoring."""

from __future__ import annotations

from typing import Any

from cre_mcp.source_rights.output import safe_error_message

from ..graph.motivation import (
    TRIGGER_BASE_SEVERITY,
    MotivationSignal,
    TriggerType,
    score_motivation,
)


def _validated_signals(
    property_id: str,
    signals: list[dict[str, Any]],
    owner_name: str | None = None,
) -> list[MotivationSignal]:
    validated: list[MotivationSignal] = []
    for raw_signal in signals:
        payload = dict(raw_signal)
        supplied_property_id = payload.get("property_id")
        if supplied_property_id is not None and supplied_property_id != property_id:
            raise ValueError(
                f"signal property_id {supplied_property_id!r} does not match "
                f"requested property_id {property_id!r}"
            )
        payload["property_id"] = property_id
        if owner_name is not None:
            payload["owner_name"] = owner_name
        validated.append(MotivationSignal.model_validate(payload))
    return validated


async def owner_motivation(
    property_id: str,
    signals: list[dict[str, Any]],
    owner_name: str | None = None,
) -> dict[str, Any]:
    """Validate supplied events and return one property's motivation estimate."""

    try:
        validated = _validated_signals(property_id, signals, owner_name)
        result = score_motivation(validated)
        if not validated:
            result = result.model_copy(
                update={"property_id": property_id, "owner_name": owner_name}
            )
        return result.model_dump(mode="json")
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def record_trigger_event(
    property_id: str,
    trigger_type: str,
    evidence_source: str,
    severity: float | None = None,
    evidence_url: str | None = None,
    evidence_date: str | None = None,
    freshness_days: int | None = None,
    owner_name: str | None = None,
) -> dict[str, Any]:
    """Normalize and score one in-memory trigger event without persistence."""

    try:
        normalized_trigger = TriggerType(trigger_type)
        signal = MotivationSignal(
            property_id=property_id,
            owner_name=owner_name,
            trigger_type=normalized_trigger,
            evidence_source=evidence_source,
            evidence_url=evidence_url,
            evidence_date=evidence_date,
            severity=(
                TRIGGER_BASE_SEVERITY[normalized_trigger]
                if severity is None
                else severity
            ),
            freshness_days=freshness_days,
        )
        return score_motivation([signal]).model_dump(mode="json")
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def find_motivated_owners(
    signals_by_property: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]] | dict[str, str]:
    """Score properties independently and rank likely owner engagement."""

    try:
        ranked = []
        for property_id, raw_signals in signals_by_property.items():
            validated = _validated_signals(property_id, raw_signals)
            result = score_motivation(validated)
            if not validated:
                result = result.model_copy(update={"property_id": property_id})
            ranked.append(result)
        ranked.sort(key=lambda item: item.engagement_probability, reverse=True)
        return [item.model_dump(mode="json") for item in ranked]
    except Exception as exc:
        return {"error": safe_error_message(exc)}
