"""Customer-facing HTTP API tests: bearer auth, scope enforcement, the deal
resource, and cross-workspace isolation driven through the ASGI app."""

import httpx
import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import PlatformApi, starlette_app
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
SCOPES = ("deals:read", "deals:write")


class Tenant:
    """A provisioned workspace with a bearer token for the given scopes."""

    def __init__(self, public_id: str, token: str) -> None:
        self.public_id = public_id
        self.token = token

    @property
    def auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


async def _provision(
    config: CreConfig,
    name: str,
    *,
    scopes: tuple[str, ...] = SCOPES,
    grant: bool = True,
) -> Tenant:
    repo = PlatformRepository(config.cache_db_path)
    auth = OAuthSessionStore(config.cache_db_path)
    entitlements = EntitlementStore(config.cache_db_path)

    workspace = await repo.create_workspace(name)
    assert workspace is not None
    user = await repo.create_user(f"{workspace.public_id}@example.com", name)
    assert user is not None
    assert await repo.add_membership(workspace.public_id, user.id, role="owner")

    client = auth.register_client(workspace.public_id, "Claude", (REDIRECT,), scopes)
    if grant:
        entitlements.grant_access(
            workspace=workspace.public_id,
            source="stripe",
            external_ref=f"sub_{workspace.public_id}",
            profile=Profile.FULL_OPERATOR,
            plan_key="pro",
        )
    tokens = auth.issue_session(
        workspace.public_id,
        str(user.id),
        client.client_id,
        Profile.FULL_OPERATOR,
        plan="pro",
        scopes=scopes,
    )
    return Tenant(workspace.public_id, tokens.access_token)


def _client(config: CreConfig) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=starlette_app(config))
    return httpx.AsyncClient(transport=transport, base_url="http://platform.test")


@pytest.fixture
def config(tmp_path) -> CreConfig:
    return CreConfig(cache_db_path=tmp_path / "platform.db")


# --- authentication ----------------------------------------------------------


async def test_me_returns_session_workspace_and_entitlements(config):
    tenant = await _provision(config, "Acme CRE")

    async with _client(config) as client:
        response = await client.get("/v1/me", headers=tenant.auth)

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["workspace_id"] == tenant.public_id
    assert body["workspace"]["public_id"] == tenant.public_id
    assert body["effective_access"]["profile"] == "full_operator"
    assert body["account"]["state"] == "active"


async def test_missing_or_malformed_bearer_is_401(config):
    tenant = await _provision(config, "Acme CRE")

    async with _client(config) as client:
        assert (await client.get("/v1/me")).status_code == 401
        assert (
            await client.get("/v1/me", headers={"authorization": "Basic abc"})
        ).status_code == 401
        assert (
            await client.get(
                "/v1/me", headers={"authorization": "Bearer mcr_at_bogus"}
            )
        ).status_code == 401


async def test_scope_is_enforced_per_route(config):
    tenant = await _provision(config, "Acme CRE", scopes=("deals:read",))

    async with _client(config) as client:
        listed = await client.get("/v1/deals", headers=tenant.auth)
        created = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={"deal_ref": "crexi:1", "title": "Deal"},
        )

    assert listed.status_code == 200
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "forbidden"


# --- deal resource -----------------------------------------------------------


async def test_create_list_and_get_deal_roundtrip(config):
    tenant = await _provision(config, "Acme CRE")

    async with _client(config) as client:
        created = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={
                "deal_ref": "crexi:12",
                "title": "Twelve-Year NNN",
                "payload": {"price_usd": 2_500_000},
            },
        )
        assert created.status_code == 201
        deal_id = created.json()["deal"]["id"]

        listed = await client.get("/v1/deals", headers=tenant.auth)
        fetched = await client.get(f"/v1/deals/{deal_id}", headers=tenant.auth)

    assert [d["deal_ref"] for d in listed.json()["deals"]] == ["crexi:12"]
    assert fetched.status_code == 200
    assert fetched.json()["deal"]["payload"]["price_usd"] == 2_500_000


async def test_update_deal_changes_stage(config):
    tenant = await _provision(config, "Acme CRE")

    async with _client(config) as client:
        created = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={"deal_ref": "crexi:9", "title": "Deal"},
        )
        deal_id = created.json()["deal"]["id"]
        updated = await client.patch(
            f"/v1/deals/{deal_id}",
            headers=tenant.auth,
            json={"stage": "pursuing"},
        )

    assert updated.status_code == 200
    assert updated.json()["deal"]["stage"] == "pursuing"


async def test_invalid_bodies_are_rejected(config):
    tenant = await _provision(config, "Acme CRE")

    async with _client(config) as client:
        blank_ref = await client.post(
            "/v1/deals", headers=tenant.auth, json={"deal_ref": "  ", "title": "X"}
        )
        not_json = await client.post(
            "/v1/deals",
            headers={**tenant.auth, "content-type": "application/json"},
            content=b"not json",
        )
        bad_stage = await client.get(
            "/v1/deals?stage=daydreaming", headers=tenant.auth
        )

    assert blank_ref.status_code == 422
    assert not_json.status_code == 400
    assert bad_stage.status_code == 422


# --- cross-tenant isolation --------------------------------------------------


async def test_a_workspace_cannot_read_or_update_another_workspaces_deal(config):
    alice = await _provision(config, "Alice CRE")
    bob = await _provision(config, "Bob CRE")

    async with _client(config) as client:
        created = await client.post(
            "/v1/deals",
            headers=alice.auth,
            json={"deal_ref": "crexi:secret", "title": "Alice only"},
        )
        alice_deal_id = created.json()["deal"]["id"]

        bob_list = await client.get("/v1/deals", headers=bob.auth)
        bob_read = await client.get(
            f"/v1/deals/{alice_deal_id}", headers=bob.auth
        )
        bob_update = await client.patch(
            f"/v1/deals/{alice_deal_id}",
            headers=bob.auth,
            json={"title": "hijacked"},
        )
        alice_read = await client.get(
            f"/v1/deals/{alice_deal_id}", headers=alice.auth
        )

    assert bob_list.json()["deals"] == []
    assert bob_read.status_code == 404
    assert bob_update.status_code == 404
    # Alice's record is untouched by Bob's attempts.
    assert alice_read.status_code == 200
    assert alice_read.json()["deal"]["title"] == "Alice only"

async def test_deal_defaults_and_strict_field_types(config):
    tenant = await _provision(config, "Strict Inputs")
    async with _client(config) as client:
        created = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={"deal_ref": "manual:default", "title": "Default stage"},
        )
        deal_id = created.json()["deal"]["id"]
        bad_create_title = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={"deal_ref": "manual:bad-title", "title": 42},
        )
        bad_create_payload = await client.post(
            "/v1/deals",
            headers=tenant.auth,
            json={"deal_ref": "manual:bad-payload", "title": "Bad", "payload": []},
        )
        bad_patch_title = await client.patch(
            f"/v1/deals/{deal_id}", headers=tenant.auth, json={"title": 42}
        )
        bad_patch_payload = await client.patch(
            f"/v1/deals/{deal_id}", headers=tenant.auth, json={"payload": []}
        )
        bad_patch_stage = await client.patch(
            f"/v1/deals/{deal_id}", headers=tenant.auth, json={"stage": 7}
        )
        empty_patch = await client.patch(
            f"/v1/deals/{deal_id}", headers=tenant.auth, json={}
        )

    assert created.status_code == 201
    assert created.json()["deal"]["stage"] == "watching"
    assert bad_create_title.status_code == 422
    assert bad_create_payload.status_code == 422
    assert bad_patch_title.status_code == 422
    assert bad_patch_payload.status_code == 422
    assert bad_patch_stage.status_code == 422
    assert empty_patch.status_code == 422
