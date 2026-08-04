"""Strict Stripe test-mode normalization and read-only reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from curl_cffi.requests import AsyncSession, RequestsError

from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import (
    AdminAuditError,
    AdminForbiddenError,
    AdminNotFoundError,
    AdminValidationError,
    canonical_json,
    validate_reason,
)

from cre_mcp.platform.providers.core import (
    NormalizedProviderEvent,
    ProviderSyncService,
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
STRIPE_SIGNAL_EVENT_TYPES = frozenset(
    {
        "customer.updated",
        "entitlements.active_entitlement_summary.updated",
    }
)
STRIPE_EVENT_TYPES = (
    STRIPE_SUBSCRIPTION_EVENT_TYPES
    | STRIPE_INVOICE_EVENT_TYPES
    | STRIPE_SIGNAL_EVENT_TYPES
)

_STRIPE_API_BASE = "https://api.stripe.com/v1"
_STRIPE_SUBSCRIPTION_STATUSES = frozenset(
    {
        "active",
        "canceled",
        "incomplete",
        "incomplete_expired",
        "past_due",
        "paused",
        "trialing",
        "unpaid",
    }
)
_STRIPE_GRANTING_STATUSES = frozenset({"active"})


def _subscription_period_raw(value: dict[str, Any]) -> int | None:
    """Use legacy shared period or the conservative earliest item period."""
    top_level = value.get("current_period_end")
    if top_level is not None:
        if isinstance(top_level, bool) or not isinstance(top_level, int):
            raise ValueError("invalid period")
        return top_level
    items = value.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    if not isinstance(data, list) or not data:
        return None
    periods: list[int] = []
    for item in data:
        raw = item.get("current_period_end") if isinstance(item, dict) else None
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError("invalid period")
        periods.append(raw)
    return min(periods)


class StripeProviderUnavailableError(RuntimeError):
    """Stripe test reconciliation is disabled or could not be read safely."""


class StripeReadTransport(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> dict[str, Any]: ...


class CurlCffiStripeTransport:
    """Fixed-host GET-only transport for Stripe's test API."""

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        if url != f"{_STRIPE_API_BASE}/subscriptions":
            raise StripeProviderUnavailableError("Stripe read path is not allowed")
        try:
            async with AsyncSession(timeout=20, allow_redirects=False) as session:
                response = await session.get(url, params=params, headers=headers)
        except RequestsError as exc:
            raise StripeProviderUnavailableError(
                "Stripe test API could not be reached"
            ) from exc
        if response.status_code != 200:
            raise StripeProviderUnavailableError(
                f"Stripe test API returned HTTP {response.status_code}"
            )
        try:
            value = response.json()
        except (TypeError, ValueError) as exc:
            raise StripeProviderUnavailableError(
                "Stripe test API did not return JSON"
            ) from exc
        if not isinstance(value, dict):
            raise StripeProviderUnavailableError(
                "Stripe test API returned an invalid response"
            )
        return value


@dataclass(frozen=True)
class StripeSubscriptionSnapshot:
    subscription_id: str
    customer_id: str
    status: str
    price_ids: tuple[str, ...]
    current_period_end: datetime | None


class StripeReadClient:
    """Bounded, paginated, read-only access to Stripe test subscriptions."""

    def __init__(
        self,
        *,
        api_key: str,
        api_version: str,
        transport: StripeReadTransport | None = None,
    ) -> None:
        if not api_key.startswith(("sk_test_", "rk_test_")):
            raise StripeProviderUnavailableError(
                "Stripe reconciliation requires a test-mode API key"
            )
        self._api_key = api_key
        self._api_version = api_version
        self._transport = transport or CurlCffiStripeTransport()

    @classmethod
    def from_config(
        cls,
        config: CreConfig,
        *,
        transport: StripeReadTransport | None = None,
    ) -> "StripeReadClient":
        if config.stripe_api_key is None:
            raise StripeProviderUnavailableError(
                "Stripe test API key is not configured"
            )
        return cls(
            api_key=config.stripe_api_key.get_secret_value(),
            api_version=config.stripe_api_version,
            transport=transport,
        )

    @staticmethod
    def _snapshot(value: Any, customer_id: str) -> StripeSubscriptionSnapshot:
        if not isinstance(value, dict):
            raise StripeProviderUnavailableError(
                "Stripe subscription entry is invalid"
            )
        subscription_id = value.get("id")
        customer = value.get("customer")
        status = value.get("status")
        livemode = value.get("livemode")
        if (
            not isinstance(subscription_id, str)
            or not subscription_id
            or customer != customer_id
            or status not in _STRIPE_SUBSCRIPTION_STATUSES
            or livemode is not False
        ):
            raise StripeProviderUnavailableError(
                "Stripe subscription identity, mode, or status is invalid"
            )
        items = value.get("items")
        if not isinstance(items, dict) or items.get("has_more") is True:
            raise StripeProviderUnavailableError(
                "Stripe subscription prices are incomplete"
            )
        data = items.get("data")
        if not isinstance(data, list):
            raise StripeProviderUnavailableError(
                "Stripe subscription prices are invalid"
            )
        prices: list[str] = []
        for item in data:
            price = item.get("price") if isinstance(item, dict) else None
            price_id = price.get("id") if isinstance(price, dict) else None
            if not isinstance(price_id, str) or not price_id:
                raise StripeProviderUnavailableError(
                    "Stripe subscription price is invalid"
                )
            prices.append(price_id)
        try:
            period_raw = _subscription_period_raw(value)
        except ValueError as exc:
            raise StripeProviderUnavailableError(
                "Stripe subscription period is invalid"
            ) from exc
        if period_raw is not None:
            try:
                period_end = datetime.fromtimestamp(period_raw, UTC)
            except (OverflowError, OSError, ValueError) as exc:
                raise StripeProviderUnavailableError(
                    "Stripe subscription period is invalid"
                ) from exc
        else:
            period_end = None
        return StripeSubscriptionSnapshot(
            subscription_id=subscription_id,
            customer_id=customer_id,
            status=status,
            price_ids=tuple(prices),
            current_period_end=period_end,
        )

    async def list_subscriptions(
        self,
        customer_id: str,
    ) -> tuple[StripeSubscriptionSnapshot, ...]:
        if (
            not isinstance(customer_id, str)
            or not customer_id.startswith("cus_")
            or len(customer_id) > 255
        ):
            raise StripeProviderUnavailableError("Stripe customer id is invalid")
        params = {"customer": customer_id, "status": "all", "limit": "100"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Stripe-Version": self._api_version,
            "Accept": "application/json",
            "User-Agent": "MedawarCRE-Stripe-Reconciler/1.0",
        }
        subscriptions: list[StripeSubscriptionSnapshot] = []
        seen: set[str] = set()
        for _page_number in range(100):
            payload = await self._transport.get_json(
                f"{_STRIPE_API_BASE}/subscriptions",
                params=dict(params),
                headers=dict(headers),
            )
            if payload.get("object") != "list" or not isinstance(
                payload.get("has_more"), bool
            ):
                raise StripeProviderUnavailableError(
                    "Stripe subscription page is invalid"
                )
            data = payload.get("data")
            if not isinstance(data, list):
                raise StripeProviderUnavailableError(
                    "Stripe subscription page data is invalid"
                )
            page = [self._snapshot(item, customer_id) for item in data]
            for snapshot in page:
                if snapshot.subscription_id in seen:
                    raise StripeProviderUnavailableError(
                        "Stripe subscription pagination repeated an object"
                    )
                seen.add(snapshot.subscription_id)
                subscriptions.append(snapshot)
            if payload["has_more"] is False:
                return tuple(subscriptions)
            if not page:
                raise StripeProviderUnavailableError(
                    "Stripe subscription pagination is incomplete"
                )
            params["starting_after"] = page[-1].subscription_id
        raise StripeProviderUnavailableError(
            "Stripe subscription pagination exceeded the safety limit"
        )


class StripeReconciliationService:
    """Repair one workspace from Stripe's complete test subscription state."""

    def __init__(
        self,
        config: CreConfig,
        *,
        reader: StripeReadClient | None = None,
        sync: ProviderSyncService | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(config.cache_db_path).expanduser()
        self.reader = reader
        self.sync = sync or ProviderSyncService(config)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _actor(
        connection: sqlite3.Connection,
        actor_user_id: int,
    ) -> sqlite3.Row:
        actor = connection.execute(
            """
            SELECT user_id,role FROM platform_internal_admins
            WHERE user_id=? AND active=1
            """,
            (actor_user_id,),
        ).fetchone()
        if actor is None or str(actor["role"]) != "platform_admin":
            raise AdminForbiddenError(
                "Active platform administrator authority is required"
            )
        return actor

    def _workspace_state_tx(
        self,
        connection: sqlite3.Connection,
        workspace_public_id: str,
        actor_user_id: int,
    ) -> tuple[int, str, list[dict[str, Any]]]:
        self._actor(connection, actor_user_id)
        workspace = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id=?",
            (workspace_public_id,),
        ).fetchone()
        if workspace is None:
            raise AdminNotFoundError("Workspace does not exist")
        workspace_id = int(workspace["id"])
        accounts = connection.execute(
            """
            SELECT external_account_id FROM platform_external_accounts
            WHERE workspace_id=? AND provider='stripe'
            ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()
        if len(accounts) != 1:
            raise AdminValidationError(
                "Workspace must have exactly one Stripe customer mapping"
            )
        rows = connection.execute(
            """
            SELECT subscription.external_subscription_id,
                   subscription.status AS subscription_status,
                   subscription.plan_key,
                   subscription.current_period_end,
                   grant.profile AS grant_profile,
                   grant.status AS grant_status
            FROM platform_subscriptions AS subscription
            LEFT JOIN platform_access_grants AS grant
              ON grant.source='stripe'
             AND grant.external_ref=subscription.external_subscription_id
            WHERE subscription.workspace_id=?
              AND subscription.provider='stripe'
            UNION ALL
            SELECT grant.external_ref,
                   NULL AS subscription_status,
                   grant.plan_key,
                   NULL AS current_period_end,
                   grant.profile AS grant_profile,
                   grant.status AS grant_status
            FROM platform_access_grants AS grant
            LEFT JOIN platform_subscriptions AS subscription
              ON subscription.provider='stripe'
             AND subscription.external_subscription_id=grant.external_ref
            WHERE grant.workspace_id=?
              AND grant.source='stripe'
              AND subscription.id IS NULL
            ORDER BY 1
            """,
            (workspace_id, workspace_id),
        ).fetchall()
        return (
            workspace_id,
            str(accounts[0]["external_account_id"]),
            [dict(row) for row in rows],
        )

    def _workspace_state(
        self,
        workspace_public_id: str,
        actor_user_id: int,
    ) -> tuple[int, str, list[dict[str, Any]]]:
        with self._connect() as connection:
            return self._workspace_state_tx(
                connection,
                workspace_public_id,
                actor_user_id,
            )

    def _mapping_for(
        self,
        price_ids: tuple[str, ...],
    ) -> tuple[str, str]:
        if not price_ids:
            raise StripeProviderUnavailableError(
                "Stripe subscription has no mapped price"
            )
        mappings = []
        for price_id in dict.fromkeys(price_ids):
            mapping = self.config.stripe_price_mappings.get(price_id)
            if mapping is None:
                raise StripeProviderUnavailableError(
                    "Stripe subscription contains an unmapped price"
                )
            mappings.append(mapping)
        identities = {
            (mapping.plan_key, mapping.profile.value) for mapping in mappings
        }
        if len(identities) != 1:
            raise StripeProviderUnavailableError(
                "Stripe subscription prices map to conflicting plans"
            )
        return next(iter(identities))

    @staticmethod
    def _event_id(
        subscription_id: str,
        state: dict[str, Any],
        observed_at: datetime,
    ) -> str:
        digest = hashlib.sha256(
            canonical_json(
                {
                    "domain": "stripe-test-reconciliation-v1",
                    "observed_at": observed_at.astimezone(UTC).isoformat(),
                    "subscription_id": subscription_id,
                    "state": state,
                }
            ).encode("utf-8")
        ).hexdigest()
        return f"stripe_reconcile_{digest}"

    def _planned_events(
        self,
        customer_id: str,
        snapshots: tuple[StripeSubscriptionSnapshot, ...],
        local_rows: list[dict[str, Any]],
        observed_at: datetime,
    ) -> tuple[list[NormalizedProviderEvent], int]:
        local = {
            str(row["external_subscription_id"]): row for row in local_rows
        }
        events: list[NormalizedProviderEvent] = []
        discrepancies = 0
        provider_ids = {snapshot.subscription_id for snapshot in snapshots}

        for snapshot in snapshots:
            row = local.get(snapshot.subscription_id)
            if snapshot.status in _STRIPE_GRANTING_STATUSES:
                plan_key, profile = self._mapping_for(snapshot.price_ids)
                period = (
                    snapshot.current_period_end.isoformat()
                    if snapshot.current_period_end is not None
                    else None
                )
                if (
                    row is None
                    or row["subscription_status"] != "active"
                    or row["plan_key"] != plan_key
                    or row["current_period_end"] != period
                    or row["grant_profile"] != profile
                    or row["grant_status"] != "active"
                ):
                    discrepancies += 1
                state = {
                    "action": "subscription",
                    "period_end": period,
                    "prices": list(snapshot.price_ids),
                    "status": snapshot.status,
                }
                events.append(
                    NormalizedProviderEvent(
                        provider="stripe",
                        event_id=self._event_id(
                            snapshot.subscription_id,
                            state,
                            observed_at,
                        ),
                        event_type="stripe.reconciliation.subscription",
                        occurred_at=observed_at,
                        action="subscription",
                        external_account_id=customer_id,
                        external_object_id=snapshot.subscription_id,
                        subscription_status="active",
                        mapping_keys=snapshot.price_ids,
                        current_period_end=snapshot.current_period_end,
                    )
                )
            elif row is not None:
                if (
                    row["subscription_status"] != "canceled"
                    or row["grant_status"] != "revoked"
                ):
                    discrepancies += 1
                state = {"action": "cancel", "status": snapshot.status}
                events.append(
                    NormalizedProviderEvent(
                        provider="stripe",
                        event_id=self._event_id(
                            snapshot.subscription_id,
                            state,
                            observed_at,
                        ),
                        event_type="stripe.reconciliation.subscription",
                        occurred_at=observed_at,
                        action="cancel",
                        external_account_id=customer_id,
                        external_object_id=snapshot.subscription_id,
                        subscription_status="canceled",
                    )
                )

        for subscription_id, row in local.items():
            if subscription_id in provider_ids:
                continue
            if (
                row["subscription_status"] != "canceled"
                or row["grant_status"] != "revoked"
            ):
                discrepancies += 1
            state = {"action": "cancel", "status": "absent"}
            events.append(
                NormalizedProviderEvent(
                    provider="stripe",
                    event_id=self._event_id(
                        subscription_id,
                        state,
                        observed_at,
                    ),
                    event_type="stripe.reconciliation.absent",
                    occurred_at=observed_at,
                    action="cancel",
                    external_account_id=customer_id,
                    external_object_id=subscription_id,
                    subscription_status="canceled",
                )
            )
        return events, discrepancies

    def _audit_tx(
        self,
        connection: sqlite3.Connection,
        workspace_public_id: str,
        workspace_id: int,
        actor_user_id: int,
        reason_code: str,
        reason: str,
        local_rows: list[dict[str, Any]],
        report: dict[str, Any],
    ) -> None:
        actor = self._actor(connection, actor_user_id)
        workspace = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id=?",
            (workspace_public_id,),
        ).fetchone()
        if workspace is None or int(workspace["id"]) != workspace_id:
            raise AdminNotFoundError("Workspace does not exist")
        before = [
            {
                "subscription_id": row["external_subscription_id"],
                "subscription_status": row["subscription_status"],
                "plan_key": row["plan_key"],
                "grant_profile": row["grant_profile"],
                "grant_status": row["grant_status"],
            }
            for row in local_rows
        ]
        changes_before = connection.total_changes
        connection.execute(
            """
            INSERT INTO platform_admin_audit(
                actor_user_id,actor_role,action,workspace_id,
                target_type,target_id,reason_code,reason,
                before_json,after_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(actor["user_id"]),
                str(actor["role"]),
                "stripe.reconcile",
                workspace_id,
                "workspace_stripe_state",
                workspace_public_id,
                reason_code,
                reason,
                canonical_json(before),
                canonical_json(report),
                datetime.now(UTC).isoformat(),
            ),
        )
        if connection.total_changes != changes_before + 1:
            raise AdminAuditError

    def _apply_reconciliation(
        self,
        workspace_public_id: str,
        expected_workspace_id: int,
        expected_customer_id: str,
        actor_user_id: int,
        reason_code: str,
        reason: str,
        snapshots: tuple[StripeSubscriptionSnapshot, ...],
        observation: datetime,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                workspace_id, customer_id, local_rows = self._workspace_state_tx(
                    connection,
                    workspace_public_id,
                    actor_user_id,
                )
                if (
                    workspace_id != expected_workspace_id
                    or customer_id != expected_customer_id
                ):
                    raise AdminValidationError(
                        "Stripe customer mapping changed during reconciliation"
                    )
                events, discrepancy_count = self._planned_events(
                    customer_id,
                    snapshots,
                    local_rows,
                    observation,
                )
                results: list[dict[str, Any]] = []
                for event in events:
                    result = self.sync.ingest_tx(connection, event)
                    results.append(
                        {
                            "subscription_id": event.external_object_id,
                            "action": event.action,
                            "outcome": result.outcome,
                            "reason_code": result.reason_code,
                        }
                    )
                report: dict[str, Any] = {
                    "provider": "stripe",
                    "mode": "test",
                    "complete": True,
                    "observed_at": observation.astimezone(UTC).isoformat(),
                    "discrepancy_count": discrepancy_count,
                    "results": results,
                }
                self._audit_tx(
                    connection,
                    workspace_public_id,
                    workspace_id,
                    actor_user_id,
                    reason_code,
                    reason,
                    local_rows,
                    report,
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return report

    async def reconcile_workspace(
        self,
        workspace_public_id: str,
        *,
        actor_user_id: int,
        reason_code: Any,
        reason: Any,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        workspace_id, customer_id, _local_rows = await asyncio.to_thread(
            self._workspace_state,
            workspace_public_id,
            actor_user_id,
        )
        reader = self.reader or StripeReadClient.from_config(self.config)
        snapshots = await reader.list_subscriptions(customer_id)
        observation = observed_at or datetime.now(UTC)
        if observation.tzinfo is None:
            observation = observation.replace(tzinfo=UTC)
        return await asyncio.to_thread(
            self._apply_reconciliation,
            workspace_public_id,
            workspace_id,
            customer_id,
            actor_user_id,
            normalized_code,
            normalized_reason,
            snapshots,
            observation.astimezone(UTC),
        )


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


def parse_stripe_event(
    value: dict[str, Any],
    *,
    expected_livemode: bool = False,
) -> NormalizedProviderEvent:
    event_id, event_type, occurred_at = _identity(value)
    livemode = value.get("livemode")
    if event_type in STRIPE_EVENT_TYPES and not isinstance(livemode, bool):
        raise ProviderValidationError(
            "stripe_mode_missing",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        )
    if isinstance(livemode, bool) and livemode is not expected_livemode:
        raise ProviderValidationError(
            "stripe_mode_mismatch",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        )
    if event_type not in STRIPE_EVENT_TYPES:
        return NormalizedProviderEvent(
            provider="stripe",
            event_id=event_id,
            event_type="unsupported",
            occurred_at=occurred_at,
            action="reject",
        )
    obj = _object(value)
    if event_type in STRIPE_SIGNAL_EVENT_TYPES:
        if event_type == "customer.updated":
            customer = obj.get("id")
        else:
            customer = obj.get("customer")
        if not isinstance(customer, str) or not customer.strip():
            raise ProviderValidationError(
                "invalid_envelope",
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
            action="reconciliation_signal_only",
            external_account_id=customer.strip(),
            external_object_id=customer.strip(),
        )

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
    try:
        period_raw = _subscription_period_raw(obj)
    except ValueError as exc:
        raise ProviderValidationError(
            "invalid_period_end",
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            durable=True,
        ) from exc
    if period_raw is not None:
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
    else:
        period_end = None

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
    "STRIPE_SIGNAL_EVENT_TYPES",
    "STRIPE_SUBSCRIPTION_EVENT_TYPES",
    "StripeProviderUnavailableError",
    "StripeReadClient",
    "StripeReadTransport",
    "StripeReconciliationService",
    "StripeSubscriptionSnapshot",
    "parse_stripe_event",
]
