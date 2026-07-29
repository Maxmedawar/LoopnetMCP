"""Strict normalization for the documented Skool relay contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cre_mcp.platform.providers.core import (
    NormalizedProviderEvent,
    ProviderValidationError,
)

SKOOL_EVENT_TYPES = frozenset(
    {
        "member.added",
        "member.updated",
        "member.removed",
        "member.canceled",
        "member.payment_failed",
        "member.banned",
    }
)
SKOOL_RESTRICTIVE_EVENT_ACTIONS = {
    "member.removed": "remove",
    "member.canceled": "cancel",
    "member.payment_failed": "payment_failed",
    "member.banned": "banned",
}


def parse_skool_event(value: dict[str, Any]) -> NormalizedProviderEvent:
    event_id = value.get("id")
    event_type = value.get("type")
    created = value.get("created")
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or not isinstance(event_type, str)
        or not event_type.strip()
        or isinstance(created, bool)
        or not isinstance(created, int)
    ):
        raise ProviderValidationError("invalid_envelope")
    try:
        occurred_at = datetime.fromtimestamp(created, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ProviderValidationError("invalid_envelope") from exc
    if event_type not in SKOOL_EVENT_TYPES:
        raise ProviderValidationError(
            "unsupported_event_type",
            event_id=event_id.strip(),
            event_type="unsupported",
            occurred_at=occurred_at,
            durable=True,
        )
    member = value.get("member")
    member_id = member.get("id") if isinstance(member, dict) else None
    community = member.get("community") if isinstance(member, dict) else None
    level = member.get("level") if isinstance(member, dict) else None
    community_id = community.get("id") if isinstance(community, dict) else None
    level_id = level.get("id") if isinstance(level, dict) else None
    if not isinstance(member_id, str) or not member_id.strip():
        raise ProviderValidationError(
            "invalid_member",
            event_id=event_id.strip(),
            event_type=event_type.strip(),
            occurred_at=occurred_at,
            durable=True,
        )
    if event_type in SKOOL_RESTRICTIVE_EVENT_ACTIONS:
        action = SKOOL_RESTRICTIVE_EVENT_ACTIONS[event_type]
        mapping_keys: tuple[str, ...] = ()
        status = "canceled"
    elif event_type == "member.updated":
        action = "membership_update"
        status = "active"
        if (
            isinstance(community_id, str)
            and community_id.strip()
            and isinstance(level_id, str)
            and level_id.strip()
        ):
            mapping_keys = (
                f"{community_id.strip()}:{level_id.strip()}",
            )
        else:
            mapping_keys = ()
    else:
        if (
            not isinstance(community_id, str)
            or not community_id.strip()
            or not isinstance(level_id, str)
            or not level_id.strip()
        ):
            raise ProviderValidationError(
                "invalid_tier",
                event_id=event_id.strip(),
                event_type=event_type.strip(),
                occurred_at=occurred_at,
                durable=True,
            )
        action = "subscription"
        mapping_keys = (f"{community_id.strip()}:{level_id.strip()}",)
        status = "active"
    return NormalizedProviderEvent(
        provider="skool",
        event_id=event_id.strip(),
        event_type=event_type.strip(),
        occurred_at=occurred_at,
        action=action,
        external_account_id=member_id.strip(),
        external_object_id=member_id.strip(),
        subscription_status=status,
        mapping_keys=mapping_keys,
    )


__all__ = ["SKOOL_EVENT_TYPES", "parse_skool_event"]
