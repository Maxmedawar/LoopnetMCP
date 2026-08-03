"""Strict Stripe envelope normalization with no SDK dependency."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cre_mcp.platform.providers.core import (
    NormalizedProviderEvent,
    ProviderValidationError,
)

STRIPE_SUBSCRIPTION_EVENT_TYPES = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.pending_update_applied",
        "customer.subscription.pending_update_expired",
        "customer.subscription.resumed",
        "customer.subscription.trial_will_end",
    }
)
STRIPE_INVOICE_EVENT_TYPES = frozenset(
    {
        "invoice.payment_failed",
        "invoice.payment_succeeded",
    }
)
STRIPE_EVENT_TYPES = STRIPE_SUBSCRIPTION_EVENT_TYPES | STRIPE_INVOICE_EVENT_TYPES


def _identity(value: dict[str, Any]) -> tuple[str, str, datetime]:
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
    return (event_id.strip(), event_type.strip(), occurred_at)


def _object(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("object"), dict):
        raise ProviderValidationError("invalid_envelope")
    return data["object"]


def parse_stripe_event(value: dict[str, Any]) -> NormalizedProviderEvent:
    event_id, event_type, occurred_at = _identity(value)
    if event_type not in STRIPE_EVENT_TYPES:
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type="unsupported",
            occurred_at=occurred_at,
            action="reject",
        )
    obj = _object(value)
    customer = obj.get("customer")
    object_id = obj.get("id")
    if (
        not isinstance(customer, str)
        or not customer.strip()
        or not isinstance(object_id, str)
        or not object_id.strip()
    ):
        raise ProviderValidationError(
            "invalid_envelope",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        )
    if event_type == "invoice.payment_failed":
        subscription = obj.get("subscription")
        if not isinstance(subscription, str) or not subscription.strip():
            raise ProviderValidationError(
                "missing_subscription_correlation",
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                durable=True,
            )
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            action="payment_failed",
            external_account_id=customer.strip(),
            external_object_id=subscription.strip(),
        )
    if event_type == "invoice.payment_succeeded":
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            action="payment_succeeded",
            external_account_id=customer.strip(),
            external_object_id=object_id.strip(),
        )

    if event_type in {
        "customer.subscription.deleted",
        "customer.subscription.paused",
    }:
        action = (
            "cancel"
            if event_type == "customer.subscription.deleted"
            else "pause"
        )
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            action=action,
            external_account_id=customer.strip(),
            external_object_id=object_id.strip(),
            subscription_status=(
                "canceled" if action == "cancel" else "paused"
            ),
        )

    status = obj.get("status")
    if not isinstance(status, str) or status not in {
        "trialing",
        "active",
        "past_due",
        "paused",
        "canceled",
        "unpaid",
        "grace_period",
    }:
        raise ProviderValidationError(
            "invalid_subscription_status",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        )
    if status in {"canceled", "past_due", "grace_period", "unpaid", "paused"}:
        action = "pause" if status == "paused" else "restrict"
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            action=action,
            external_account_id=customer.strip(),
            external_object_id=object_id.strip(),
            subscription_status=(
                "paused" if status == "paused" else "unpaid"
            ),
        )
    if status == "trialing":
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            action="trialing_not_paid",
            external_account_id=customer.strip(),
            external_object_id=object_id.strip(),
            subscription_status="trialing",
        )
    items = obj.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    if not isinstance(data, list):
        data = []
    prices: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        price_id = price.get("id") if isinstance(price, dict) else None
        if isinstance(price_id, str) and price_id.strip():
            prices.append(price_id.strip())
    period_raw = obj.get("current_period_end")
    if period_raw is None:
        period_end = None
    elif isinstance(period_raw, bool) or not isinstance(period_raw, int):
        raise ProviderValidationError(
            "invalid_period_end",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        )
    else:
        try:
            period_end = datetime.fromtimestamp(period_raw, UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise ProviderValidationError(
                "invalid_period_end",
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                durable=True,
            ) from exc

    return NormalizedProviderEvent(
        provider="stripe",
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        action="subscription",
        external_account_id=customer.strip(),
        external_object_id=object_id.strip(),
        subscription_status=status,
        mapping_keys=tuple(prices),
        current_period_end=period_end,
    )


__all__ = [
    "STRIPE_EVENT_TYPES",
    "STRIPE_INVOICE_EVENT_TYPES",
    "STRIPE_SUBSCRIPTION_EVENT_TYPES",
    "parse_stripe_event",
]
