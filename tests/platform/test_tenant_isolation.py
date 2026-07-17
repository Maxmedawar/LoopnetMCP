"""Adversarial tenant-isolation and platform-hardening tests."""

import sqlite3

import pytest

from cre_mcp.platform.repository import PlatformRepository


async def _two_workspaces(repository: PlatformRepository):
    first = await repository.create_workspace("Alpha CRE")
    second = await repository.create_workspace("Beta CRE")
    assert first is not None and second is not None
    return first, second


async def test_workspace_public_id_bridges_verified_identity_to_repository(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None
    assert workspace.public_id.startswith("ws_")
    assert await repository.get_workspace_by_public_id(workspace.public_id) == workspace

    deal = await repository.save_deal(workspace.public_id, "crexi:1", "Deal One")
    assert deal is not None
    assert deal.workspace_id == workspace.id


async def test_saved_deal_ids_cannot_cross_tenant_boundary(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    alpha, beta = await _two_workspaces(repository)
    beta_deal = await repository.save_deal(beta.id, "crexi:beta", "Beta Deal")
    assert beta_deal is not None

    assert await repository.get_saved_deal(alpha.id, beta_deal.id) is None
    assert (
        await repository.update_saved_deal(
            alpha.id, beta_deal.id, title="Stolen Deal"
        )
        is None
    )
    unchanged = await repository.get_saved_deal(beta.id, beta_deal.id)
    assert unchanged is not None and unchanged.title == "Beta Deal"


async def test_notes_and_outcomes_are_workspace_scoped(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    alpha, beta = await _two_workspaces(repository)
    author = await repository.create_user("owner@example.com", "Owner")
    beta_deal = await repository.save_deal(beta.id, "crexi:beta", "Beta Deal")
    assert author is not None and beta_deal is not None

    note = await repository.add_note(
        beta.id, beta_deal.id, author.id, "Private seller note"
    )
    outcome = await repository.record_outcome(
        beta.id, beta_deal.id, closed=True, purchase_price=2_000_000
    )
    assert note is not None and outcome is not None

    assert await repository.get_note(alpha.id, note.id) is None
    assert await repository.list_notes(alpha.id, beta_deal.id) == []
    assert await repository.update_note(alpha.id, note.id, "stolen") is None
    assert await repository.get_outcome(alpha.id, beta_deal.id) is None
    assert await repository.list_outcomes(alpha.id) == []
    assert [item.id for item in await repository.list_outcomes(beta.id)] == [outcome.id]

async def test_membership_territory_client_and_events_are_workspace_scoped(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    alpha, beta = await _two_workspaces(repository)
    user = await repository.create_user("member@example.com", "Member")
    assert user is not None
    membership = await repository.add_membership(beta.id, user.id, "member")
    territory = await repository.claim_territory(beta.id, "Dallas")
    client = await repository.connect_client(beta.id, "Claude", "mcp")
    event = await repository.log_integration_event(
        beta.id, "deal.saved", client_id=client.id if client else None
    )
    assert membership and territory and client and event

    assert await repository.get_membership(alpha.id, membership.id) is None
    assert await repository.update_membership_role(alpha.id, membership.id, "admin") is None
    assert await repository.get_territory(alpha.id, territory.id) is None
    assert await repository.update_territory(alpha.id, territory.id, name="Stolen") is None
    assert await repository.get_connected_client(alpha.id, client.id) is None
    assert await repository.update_client_status(alpha.id, client.id, "revoked") is None
    assert await repository.get_integration_event(alpha.id, event.id) is None

async def test_consents_and_privacy_requests_are_workspace_scoped(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    alpha, beta = await _two_workspaces(repository)
    user = await repository.create_user("privacy@example.com", "Privacy User")
    assert user is not None
    assert await repository.add_membership(beta.id, user.id, "member") is not None

    consent = await repository.record_consent(
        beta.id, user.id, "privacy", granted=True, version="v1"
    )
    request = await repository.open_privacy_request(
        beta.id, user.id, "export", detail="Private export detail"
    )
    assert consent is not None and request is not None

    assert await repository.get_consent(alpha.id, consent.id) is None
    assert await repository.list_consents(alpha.id, user.id) == []
    assert await repository.get_privacy_request(alpha.id, request.id) is None
    assert await repository.list_privacy_requests(alpha.id) == []
    assert await repository.update_privacy_request(alpha.id, request.id, "completed") is None
    assert [item.id for item in await repository.list_privacy_requests(beta.id)] == [request.id]

async def test_explicit_stage_duplicate_territory_and_noop_update(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None
    deal = await repository.save_deal(workspace.id, "crexi:1", "Deal One")
    assert deal is not None

    moved = await repository.save_deal(
        workspace.id, "crexi:1", "Deal One", stage="under_contract"
    )
    assert moved is not None and moved.stage == "under_contract"

    first = await repository.claim_territory(workspace.id, "Dallas")
    duplicate = await repository.claim_territory(workspace.id, "Dallas")
    assert first is not None and duplicate is None

    unchanged = await repository.update_saved_deal(workspace.id, deal.id)
    assert unchanged is not None and unchanged.updated_at == moved.updated_at


async def test_database_operational_errors_are_not_silently_swallowed(tmp_path, monkeypatch):
    repository = PlatformRepository(tmp_path / "platform.db")

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("disk is unavailable")

    monkeypatch.setattr(repository, "_insert_row", explode)
    with pytest.raises(sqlite3.OperationalError, match="disk is unavailable"):
        await repository.create_user("max@example.com", "Max")


async def test_completed_privacy_request_cannot_reopen(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    user = await repository.create_user("privacy@example.com", "Privacy User")
    assert workspace is not None and user is not None
    assert await repository.add_membership(workspace.id, user.id, "member") is not None
    request = await repository.open_privacy_request(workspace.id, user.id, "delete")
    assert request is not None
    assert await repository.update_privacy_request(
        workspace.id, request.id, "completed"
    ) is not None
    with pytest.raises(ValueError, match="transition"):
        await repository.update_privacy_request(
            workspace.id, request.id, "received"
        )
