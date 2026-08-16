"""The Stripe billing lifecycle, on the real hosted PostgreSQL path.

`tests/platform/test_stripe_launch.py`, `test_provider_webhooks.py` and
`test_provider_security_repairs.py` prove Stripe test-mode semantics against the
sanctioned test adapter, whose stores are SQLite files. Everything moved onto
PostgreSQL in the last few commits and Stripe was never exercised there. This
proves the same claims where they have to hold: the production `create_http_app`
boot, the platform authority stores answering out of PostgreSQL, the real
`/v1/webhooks/stripe` route and a real MCP client, all on one loopback socket.

The claims, in the order the handoff states them:

  1. a correctly signed test-mode event is accepted; a wrong signature, a stale
     timestamp and an oversized body are each refused
  2. the same event id delivered twice has effect once, and the duplicate is
     recorded as a duplicate rather than silently dropped
  3. an older event does not overwrite a newer projection
  4. a paid subscription makes the workspace entitlement active and `tools/list`
     shows the entitled profile's tool set
  5. a plan change moves the profile and the visible tool set moves with it on
     the very next request
  6. failed payment, recovery, cancellation and period-end expiry each drive the
     entitlement to the right state
  7. an already-issued, still-unexpired OAuth token stops authorizing on the
     very next protected call once the entitlement is gone
  8. the Stripe customer is bound to the workspace by server state, and a
     webhook naming a customer the server does not know grants nothing

Every access token below is issued with a twelve-hour TTL on purpose. If a
denial could be explained by expiry, none of it would prove anything about
revocation.

No Stripe credential is used anywhere. Every event is a representative fixture
signed with the local webhook secret, exactly as the SQLite gates do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from pydantic import ValidationError

from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.dbapi import clear_platform_backend
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.surface import CUSTOMER_SURFACE
from tests.platform.provider_helpers import (
    STRIPE_SECRET,
    json_bytes,
    signed_headers,
    stripe_event,
)
from tests.platform.test_authoritative_oauth import (
    REDIRECT,
    _live_http,
    _raw_initialized_session,
    _raw_mcp_request,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
MCP_SCOPE = "mcp:tools"
REASON = {
    "reason_code": "initial_provisioning",
    "reason": "Bound from the internal billing operations runbook.",
}

# Both names must be real on the customer surface. Asserting that an invented
# name is absent from tools/list passes no matter what the server does.
LOCAL_TOOL = "cre_pipeline"
OPERATOR_ONLY_TOOL = "cre_offer"
LOCAL_SCOUT_TOOL_COUNT = 8
NATIONAL_SCOUT_TOOL_COUNT = 10
FULL_OPERATOR_TOOL_COUNT = 20

PRICE_MAPPINGS = {
    "price_local": {"plan_key": "local", "profile": "local_scout"},
    "price_national": {"plan_key": "national", "profile": "national_scout"},
    "price_operator": {"plan_key": "operator", "profile": "full_operator"},
}


@pytest.fixture
def hosted_app(postgres_database, tmp_path, monkeypatch):
    """The production hosted app, booted against a live migrated cluster."""
    from cre_mcp.server import create_http_app

    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()

    def _as(role: str) -> str:
        return app_dsn.replace("user=medawarcre_test_app", f"user={role}")

    monkeypatch.setenv("MEDAWARCRE_DATABASE_URL", app_dsn)
    monkeypatch.setenv("MEDAWARCRE_APP_DATABASE_URL", app_dsn)
    monkeypatch.setenv("MEDAWARCRE_MIGRATION_DATABASE_URL", migration_dsn)
    monkeypatch.setenv(
        "MEDAWARCRE_OAUTH_DATABASE_URL", _as("medawarcre_test_oauth")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_ADMISSION_DATABASE_URL", _as("medawarcre_test_admission")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_BACKUP_DATABASE_URL", _as("medawarcre_test_backup")
    )
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", "sk_test_stripe_lifecycle")
    monkeypatch.setenv("CRE_STRIPE_API_KEY", "sk_test_stripelifecyclenotarealkey")
    monkeypatch.setenv("CRE_STRIPE_WEBHOOK_SECRET", STRIPE_SECRET)
    monkeypatch.setenv("CRE_SKOOL_WEBHOOK_SECRET", "whsec_skool_stripe_lifecycle")

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "must-not-be-created.db",
        stripe_webhook_secret=STRIPE_SECRET,
        skool_webhook_secret="whsec_skool_stripe_lifecycle",
        stripe_price_mappings=PRICE_MAPPINGS,
    )
    app = create_http_app(config=config, path="/mcp")
    try:
        yield app, config, app_dsn
    finally:
        app.state.hosted_persistence.close()
        clear_platform_backend()


def _rows(dsn: str, statement: str, parameters=()) -> list[tuple]:
    """Read as the cluster owner, bypassing row-level security deliberately.

    Verification has to see what is actually stored. An application-role
    connection cannot: row-level security filters every tenant row against
    `app.workspace_id`, which only an admitted request sets.
    """
    owner = dsn.replace("user=medawarcre_test_app", "user=postgres")
    with psycopg.connect(owner) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement, parameters).fetchall()


def _grants(dsn: str, workspace_row_id: int) -> list[tuple]:
    return [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in _rows(
            dsn,
            "SELECT external_ref, status, profile FROM platform_access_grants "
            "WHERE workspace_id=%s AND source='stripe' "
            "ORDER BY external_ref",
            (workspace_row_id,),
        )
    ]


def _provider_events(dsn: str) -> list[tuple]:
    return [
        (str(row[0]), str(row[1]), int(row[2]))
        for row in _rows(
            dsn,
            "SELECT event_id, outcome, duplicate_count "
            "FROM platform_provider_events WHERE provider='stripe' "
            "ORDER BY id",
        )
    ]


async def _provision(app, config, dsn, *, name: str, customer: str):
    """One workspace, one customer, one operator, one server-owned mapping.

    The Stripe customer id is bound to the workspace by an audited internal
    operator through `AdminControlStore`, which is the only writer of
    `platform_external_accounts`. Nothing a webhook carries can create it.
    """
    platform = app.state.hosted_persistence.platform_api
    repository = PlatformRepository(config=config)

    for key in ("local", "national", "operator", "jv"):
        if not any(item.key == key for item in await repository.list_plans()):
            assert await repository.create_plan(key, key.title()) is not None

    workspace = await repository.create_workspace(name)
    assert workspace is not None
    subject = await repository.create_user(
        f"{customer}@example.test", f"{name} Customer"
    )
    assert subject is not None
    assert (
        await repository.add_membership(
            workspace.public_id, subject.id, role="owner"
        )
        is not None
    )
    assert (
        await repository.claim_territory(
            workspace.public_id, "TX territory", state="TX"
        )
        is not None
    )

    # Binding a paying customer is an internal action, never self-service.
    operator = await repository.create_user(
        f"{customer}-operator@example.test", f"{name} Operator"
    )
    assert operator is not None
    with psycopg.connect(
        dsn.replace("user=medawarcre_test_app", "user=postgres")
    ) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_internal_admins"
            "(user_id, role, active, created_at, updated_at) "
            "VALUES (%s,'platform_admin',1,%s,%s)",
            (operator.id, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()

    mapping = platform.admin.create_external_account(
        actor_user_id=operator.id,
        public_id=workspace.public_id,
        provider="stripe",
        external_account_id=customer,
        subject_user_id=subject.id,
        metadata=None,
        **REASON,
    )
    assert mapping["external_account"]["external_account_id"] == customer
    return workspace, subject, operator


def _token(config, workspace, subject, label: str) -> str:
    """A twelve-hour access token. Expiry must never explain a denial below."""
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client(label, (REDIRECT,), (MCP_SCOPE,))
    return auth.issue_session(
        workspace.public_id,
        subject.id,
        client.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    ).access_token


async def _webhook(
    client: httpx.AsyncClient,
    event: dict,
    *,
    secret: str | None = None,
    timestamp: int | None = None,
) -> httpx.Response:
    body = json_bytes(event)
    return await client.post(
        "/v1/webhooks/stripe",
        content=body,
        headers=signed_headers(
            "stripe", body, secret=secret, timestamp=timestamp
        ),
    )


async def _tool_names(client, token, session_id, request_id: int) -> set[str]:
    listed = await _raw_mcp_request(
        client,
        token,
        method="tools/list",
        request_id=request_id,
        params={},
        session_id=session_id,
    )
    assert listed.status_code == 200, listed.text
    return {tool["name"] for tool in listed.json()["result"]["tools"]}


async def _list_searches(client, token, session_id, request_id: int):
    return await _raw_mcp_request(
        client,
        token,
        method="tools/call",
        request_id=request_id,
        params={
            "name": LOCAL_TOOL,
            "arguments": {"action": "list_searches", "arguments": {}},
        },
        session_id=session_id,
    )


def test_a_live_mode_stripe_key_is_refused_before_anything_boots():
    """Test-mode enforcement is a construction-time property of the config.

    A hosted process cannot be talked into holding a live-mode Stripe key, so
    no PostgreSQL fixture is needed to prove it.
    """
    with pytest.raises(ValidationError, match="test-mode"):
        CreConfig(_env_file=None, stripe_api_key="sk_live_forbidden")


async def test_stripe_webhook_validation_replay_and_ordering_on_postgresql(
    hosted_app,
):
    """Requirements 1, 2, 3 and 8, over the real hosted webhook route."""
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence
    assert bundle.backend == "postgres"

    workspace, _, _ = await _provision(
        app, config, dsn, name="Stripe Ingress", customer="cus_ingress"
    )

    activation = stripe_event(
        "evt_pg_activate",
        customer="cus_ingress",
        prices=("price_local",),
        created=1000,
    )

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            # 1a. A wrong signing secret is refused outright.
            wrong_secret = await _webhook(
                client, activation, secret="whsec_not_the_configured_secret"
            )

            # 1b. A correctly computed signature over the same body, stamped an
            #     hour ago, is refused as a replay window violation -- a
            #     different, explicit failure from a bad digest.
            stale_stamp = await _webhook(
                client,
                activation,
                timestamp=int(datetime.now(UTC).timestamp()) - 3600,
            )

            # 1c. An oversized body is refused before the HMAC is ever computed,
            #     so an attacker cannot make the server hash unbounded input.
            oversized = b"{" + b"x" * (config.provider_webhook_max_body_bytes + 8)
            too_large = await client.post(
                "/v1/webhooks/stripe",
                content=oversized,
                headers=signed_headers("stripe", oversized),
            )

            # 1d. Test-mode enforcement at the event level: a correctly signed
            #     live-mode event is quarantined, never applied.
            live_mode = await _webhook(
                client,
                stripe_event(
                    "evt_pg_livemode",
                    customer="cus_ingress",
                    prices=("price_local",),
                    created=1000,
                    extra_envelope={"livemode": True},
                ),
            )

            # 8. A webhook naming a customer the server has never bound creates
            #    nothing and grants nothing.
            unknown = await _webhook(
                client,
                stripe_event(
                    "evt_pg_unknown_customer",
                    customer="cus_never_bound_by_the_server",
                    prices=("price_operator",),
                    created=1000,
                ),
            )

            # 1e. And the correctly signed test-mode event is accepted.
            accepted = await _webhook(client, activation)

            # 2. The exact same event id, redelivered with a *different* body,
            #    must have no second effect and must be recorded as a duplicate.
            duplicate = await _webhook(
                client,
                stripe_event(
                    "evt_pg_activate",
                    customer="cus_ingress",
                    status="canceled",
                    prices=("price_operator",),
                    created=1000,
                ),
            )

            # 3. An older event for the same subscription must not overwrite the
            #    newer projection.
            stale = await _webhook(
                client,
                stripe_event(
                    "evt_pg_older_upgrade",
                    customer="cus_ingress",
                    prices=("price_operator",),
                    created=500,
                ),
            )

    assert wrong_secret.status_code == 400
    assert wrong_secret.json()["error"]["code"] == "invalid_webhook_signature"

    assert stale_stamp.status_code == 400
    assert (
        stale_stamp.json()["error"]["code"] == "webhook_timestamp_out_of_range"
    )

    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "webhook_body_too_large"

    assert live_mode.status_code == 202
    assert live_mode.json()["reason_code"] == "stripe_mode_mismatch"

    assert unknown.status_code == 202
    assert unknown.json()["outcome"] == "quarantined"
    assert unknown.json()["reason_code"] == "unmapped_external_account"

    assert accepted.status_code == 200
    assert accepted.json()["outcome"] == "applied"

    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate"

    assert stale.status_code == 200
    assert stale.json()["outcome"] == "stale"

    # The projection is the one the accepted event asked for -- not the
    # duplicate's cancellation, and not the older event's upgrade.
    assert _grants(dsn, workspace.id) == [("sub_1", "active", "local_scout")]

    # Durable, in PostgreSQL: one row per event id, the duplicate counted rather
    # than dropped, and the two refused-at-the-door requests journalled nothing.
    stored = _provider_events(dsn)
    assert ("evt_pg_activate", "applied", 1) in stored
    assert ("evt_pg_livemode", "quarantined", 0) in stored
    assert ("evt_pg_unknown_customer", "quarantined", 0) in stored
    assert ("evt_pg_older_upgrade", "stale", 0) in stored
    assert [row[0] for row in stored].count("evt_pg_activate") == 1

    # "Recorded as a duplicate rather than silently dropped" means there is a
    # second attempt row saying so, alongside the single applied event.
    assert _rows(
        dsn,
        "SELECT attempt.outcome FROM platform_provider_event_attempts attempt "
        "JOIN platform_provider_events event "
        "ON event.id = attempt.provider_event_id "
        "WHERE event.event_id=%s ORDER BY attempt.id",
        ("evt_pg_activate",),
    ) == [("applied",), ("duplicate",)]

    # And the unknown customer created no workspace, no account and no grant.
    assert _rows(
        dsn,
        "SELECT count(*) FROM platform_external_accounts "
        "WHERE external_account_id=%s",
        ("cus_never_bound_by_the_server",),
    ) == [(0,)]
    assert _rows(dsn, "SELECT count(*) FROM platform_access_grants") == [(1,)]

    # The one mapping that does exist was written by an audited internal
    # operator, not by anything a webhook carried.
    assert _rows(
        dsn,
        "SELECT count(*) FROM platform_admin_audit "
        "WHERE action='external_account.create' AND workspace_id=%s",
        (workspace.id,),
    ) == [(1,)]


async def test_stripe_activation_upgrade_and_downgrade_move_the_tool_surface(
    hosted_app,
):
    """Requirements 4 and 5: the visible surface follows the paid plan."""
    app, config, dsn = hosted_app
    workspace, subject, _ = await _provision(
        app, config, dsn, name="Stripe Surface", customer="cus_surface"
    )
    token = _token(config, workspace, subject, "Surface Client")

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            # 4. A paid subscription is what turns the entitlement on. Before
            #    it, the customer holds a valid token and still has no access.
            before = await _raw_mcp_request(
                client,
                token,
                method="initialize",
                request_id=1,
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stripe-surface", "version": "1"},
                },
            )
            assert before.status_code == 403, before.text

            activated = await _webhook(
                client,
                stripe_event(
                    "evt_surface_activate",
                    customer="cus_surface",
                    prices=("price_local",),
                    created=1000,
                ),
            )
            assert activated.status_code == 200
            assert activated.json()["outcome"] == "applied"
            assert _grants(dsn, workspace.id) == [
                ("sub_1", "active", "local_scout")
            ]

            session_id = await _raw_initialized_session(client, token)
            local = await _tool_names(client, token, session_id, 2)
            assert len(local) == LOCAL_SCOUT_TOOL_COUNT
            assert LOCAL_TOOL in local
            assert OPERATOR_ONLY_TOOL in set(CUSTOMER_SURFACE.tools)
            assert OPERATOR_ONLY_TOOL not in local

            # The entitled surface is not merely listed -- it runs, all the way
            # through atomic admission and the request-scoped repository.
            allowed = await _list_searches(client, token, session_id, 3)
            assert allowed.status_code == 200
            assert allowed.json()["result"]["isError"] is False
            assert allowed.json()["result"]["structuredContent"]["count"] == 0

            # 5. Upgrade. The plan change arrives as a webhook and the surface
            #    moves with it on the very next request, on the same session and
            #    the same token.
            upgraded = await _webhook(
                client,
                stripe_event(
                    "evt_surface_upgrade",
                    customer="cus_surface",
                    prices=("price_operator",),
                    created=2000,
                ),
            )
            assert upgraded.status_code == 200
            assert upgraded.json()["outcome"] == "applied"
            operator_names = await _tool_names(client, token, session_id, 4)
            assert len(operator_names) == FULL_OPERATOR_TOOL_COUNT
            assert OPERATOR_ONLY_TOOL in operator_names

            # Downgrade, and the tool that only the operator plan pays for is
            # gone again -- and refused when named directly, not merely hidden.
            downgraded = await _webhook(
                client,
                stripe_event(
                    "evt_surface_downgrade",
                    customer="cus_surface",
                    prices=("price_national",),
                    created=3000,
                ),
            )
            assert downgraded.status_code == 200
            assert downgraded.json()["outcome"] == "applied"
            national = await _tool_names(client, token, session_id, 5)
            assert len(national) == NATIONAL_SCOUT_TOOL_COUNT
            assert OPERATOR_ONLY_TOOL not in national

            hidden = await _raw_mcp_request(
                client,
                token,
                method="tools/call",
                request_id=6,
                params={"name": OPERATOR_ONLY_TOOL, "arguments": {}},
                session_id=session_id,
            )
            assert hidden.status_code in {200, 403}
            if hidden.status_code == 200:
                payload = hidden.json()
                assert "error" in payload or payload["result"]["isError"] is True

    assert _grants(dsn, workspace.id) == [("sub_1", "active", "national_scout")]


async def test_failed_payment_recovery_and_period_end_expiry(hosted_app):
    """Requirement 6, each state driven by a real signed event."""
    app, config, dsn = hosted_app
    workspace, subject, _ = await _provision(
        app, config, dsn, name="Stripe Dunning", customer="cus_dunning"
    )

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            assert (
                await _webhook(
                    client,
                    stripe_event(
                        "evt_dunning_activate",
                        customer="cus_dunning",
                        prices=("price_national",),
                        created=1000,
                    ),
                )
            ).status_code == 200
            assert _grants(dsn, workspace.id) == [
                ("sub_1", "active", "national_scout")
            ]

            # Failed payment. The subscription goes unpaid and the grant is
            # revoked -- access is not left running on an unpaid invoice.
            failed = await _webhook(
                client,
                stripe_event(
                    "evt_dunning_failed",
                    event_type="invoice.payment_failed",
                    object_id="in_dunning",
                    customer="cus_dunning",
                    status="open",
                    prices=(),
                    created=2000,
                    extra_object={"subscription": "sub_1"},
                ),
            )
            assert failed.status_code == 200
            assert _grants(dsn, workspace.id) == [
                ("sub_1", "revoked", "national_scout")
            ]
            assert _rows(
                dsn,
                "SELECT status FROM platform_subscriptions "
                "WHERE workspace_id=%s AND provider='stripe'",
                (workspace.id,),
            ) == [("unpaid",)]

            # Recovery. The customer pays; the next subscription event carries
            # the live state and access comes back.
            recovered = await _webhook(
                client,
                stripe_event(
                    "evt_dunning_recovered",
                    customer="cus_dunning",
                    prices=("price_national",),
                    created=3000,
                ),
            )
            assert recovered.status_code == 200
            assert recovered.json()["outcome"] == "applied"
            assert _grants(dsn, workspace.id) == [
                ("sub_1", "active", "national_scout")
            ]

            # A token issued after recovery reaches the entitled surface.
            recovered_token = _token(
                config, workspace, subject, "Recovered Client"
            )
            session_id = await _raw_initialized_session(client, recovered_token)
            assert (
                len(await _tool_names(client, recovered_token, session_id, 2))
                == NATIONAL_SCOUT_TOOL_COUNT
            )

            # Period-end expiry. A subscription whose paid period has already
            # ended bounds the grant in the past. The grant row survives for
            # audit; the entitlement it confers does not.
            expired = await _webhook(
                client,
                stripe_event(
                    "evt_dunning_period_end",
                    customer="cus_dunning",
                    prices=("price_national",),
                    created=4000,
                    period_end=int(
                        (datetime.now(UTC) - timedelta(days=1)).timestamp()
                    ),
                ),
            )
            assert expired.status_code == 200
            assert expired.json()["outcome"] == "applied"

            # The same session and the same token that listed ten tools one
            # request ago.
            after_expiry = await _list_searches(
                client, recovered_token, session_id, 3
            )
            reinitialize = await _raw_mcp_request(
                client,
                recovered_token,
                method="initialize",
                request_id=4,
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stripe-expiry", "version": "1"},
                },
            )

    # The paid period is over, so the token authorizes nothing -- and starting
    # over buys nothing either: the transport hands out no new session.
    assert after_expiry.status_code == 403, after_expiry.text
    assert reinitialize.status_code == 403, reinitialize.text
    assert "mcp-session-id" not in reinitialize.headers

    stored_end = _rows(
        dsn,
        "SELECT ends_at FROM platform_access_grants "
        "WHERE workspace_id=%s AND source='stripe'",
        (workspace.id,),
    )[0][0]
    assert stored_end is not None
    # Compared as an instant rather than as text: the column type is the
    # backend's business, and a lexicographic comparison of two different
    # timestamp spellings would pass without meaning anything.
    ends_at = (
        datetime.fromisoformat(stored_end)
        if isinstance(stored_end, str)
        else stored_end
    )
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=UTC)
    assert ends_at < datetime.now(UTC)
    # And the grant row itself is still there, still marked active: the paid
    # period ended, which is not the same event as a revocation.
    assert _grants(dsn, workspace.id) == [("sub_1", "active", "national_scout")]


async def test_cancellation_stops_an_already_issued_unexpired_token(hosted_app):
    """Requirement 7 -- the gate, asserted as the exact door.

    Two independent mechanisms deny here: the OAuth session is revoked and the
    grant is gone. A loose `in {401, 403}` cannot tell them apart -- neutering
    OAuth session revocation still yields a 403 from the entitlement check, so
    the loose form passes while the requirement that an already-issued token
    stops authorizing has silently regressed.
    """
    app, config, dsn = hosted_app
    workspace, subject, _ = await _provision(
        app, config, dsn, name="Stripe Cancel Gate", customer="cus_cancel_gate"
    )
    token = _token(config, workspace, subject, "Cancel Gate Client")

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            activated = await _webhook(
                client,
                stripe_event(
                    "evt_gate_activate",
                    customer="cus_cancel_gate",
                    prices=("price_local",),
                    created=1000,
                ),
            )
            assert activated.status_code == 200
            assert _grants(dsn, workspace.id) == [
                ("sub_1", "active", "local_scout")
            ]

            session_id = await _raw_initialized_session(client, token)
            before = await _list_searches(client, token, session_id, 2)
            assert before.status_code == 200
            assert before.json()["result"]["isError"] is False

            canceled = await _webhook(
                client,
                stripe_event(
                    "evt_gate_cancel",
                    event_type="customer.subscription.deleted",
                    customer="cus_cancel_gate",
                    status="canceled",
                    prices=(),
                    created=2000,
                ),
            )
            assert canceled.status_code == 200
            assert canceled.json()["outcome"] == "applied"

            # The same token is well inside its twelve-hour TTL, and the call
            # asserted here is the one that succeeded above under this same
            # token and session -- so a refusal now can only come from the
            # cancellation.
            after = await _list_searches(client, token, session_id, 3)

    assert after.status_code == 401, (
        "a canceled Stripe subscription must invalidate the already-issued "
        "token itself, not merely fail the entitlement check; got "
        f"{after.status_code}"
    )
    assert after.json()["error"] == "invalid_token"

    # Durable, not process-local: a fresh read of PostgreSQL shows the grant
    # revoked and the OAuth session revoked.
    assert _grants(dsn, workspace.id) == [("sub_1", "revoked", "local_scout")]
    assert _rows(
        dsn,
        "SELECT count(*) FROM platform_oauth_sessions "
        "WHERE workspace_id=%s AND revoked_at IS NOT NULL",
        (workspace.public_id,),
    )[0][0] >= 1

    # Nothing about this ran through a local file.
    assert not config.cache_db_path.exists()
