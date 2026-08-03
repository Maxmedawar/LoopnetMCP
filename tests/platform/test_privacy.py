"""Compliance-layer persistence tests: consent, events, and privacy requests."""

import pytest

from cre_mcp.platform.repository import PlatformRepository


async def _member(repository: PlatformRepository):
    workspace = await repository.create_workspace("Medawar CRE")
    user = await repository.create_user("max@efreedom.com", "Max")
    assert workspace is not None and user is not None
    assert await repository.add_membership(workspace.id, user.id, "member") is not None
    return workspace, user


async def test_consent_records_are_append_only_history(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace, user = await _member(repository)

    granted = await repository.record_consent(
        workspace.id, user.id, "marketing", granted=True, version="2026-01"
    )
    withdrawn = await repository.record_consent(
        workspace.id, user.id, "marketing", granted=False, version="2026-07"
    )

    assert granted is not None and withdrawn is not None
    history = await repository.list_consents(workspace.id, user.id)
    assert [item.id for item in history] == [granted.id, withdrawn.id]

    latest = await repository.latest_consent(workspace.id, user.id, "marketing")
    assert latest is not None
    assert latest.granted is False
    assert latest.version == "2026-07"


async def test_consent_rejects_bad_type_and_unknown_user(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace, user = await _member(repository)

    with pytest.raises(ValueError, match="consent_type must be one of"):
        await repository.record_consent(
            workspace.id, user.id, "midnight", granted=True, version="v1"
        )
    assert (
        await repository.record_consent(
            workspace.id, 999, "marketing", granted=True, version="v1"
        )
        is None
    )
    assert await repository.latest_consent(workspace.id, user.id, "marketing") is None


async def test_integration_events_append_and_filter(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None
    client = await repository.connect_client(workspace.id, "Claude Desktop", "mcp")
    assert client is not None

    saved = await repository.log_integration_event(
        workspace.id,
        "deal.saved",
        payload={"deal_ref": "crexi:deal-12"},
        client_id=client.id,
    )
    scored = await repository.log_integration_event(workspace.id, "deal.scored")

    assert saved is not None and scored is not None
    events = await repository.list_integration_events(workspace.id)
    assert [item.event_type for item in events] == ["deal.saved", "deal.scored"]

    only = await repository.list_integration_events(
        workspace.id, event_type="deal.saved"
    )
    assert len(only) == 1
    assert only[0].payload == {"deal_ref": "crexi:deal-12"}
    assert only[0].client_id == client.id
    assert await repository.get_integration_event(workspace.id, saved.id) is not None

    with pytest.raises(ValueError, match="event_type"):
        await repository.log_integration_event(workspace.id, "   ")
    assert await repository.log_integration_event(999, "deal.saved") is None


async def test_privacy_request_lifecycle(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace, user = await _member(repository)

    request = await repository.open_privacy_request(
        workspace.id, user.id, "export", detail="Full account export, please."
    )
    assert request is not None and request.status == "received"

    completed = await repository.update_privacy_request(
        workspace.id, request.id, "completed"
    )
    assert completed is not None and completed.status == "completed"
    matching = await repository.list_privacy_requests(
        workspace.id, status="completed"
    )
    assert [item.id for item in matching] == [request.id]
    assert await repository.list_privacy_requests(
        workspace.id, status="rejected"
    ) == []
    assert await repository.get_privacy_request(workspace.id, request.id) is not None


async def test_privacy_request_validation(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace, user = await _member(repository)

    with pytest.raises(ValueError, match="kind must be one of"):
        await repository.open_privacy_request(
            workspace.id, user.id, "forget-me-eventually"
        )
    request = await repository.open_privacy_request(workspace.id, user.id, "delete")
    assert request is not None
    with pytest.raises(ValueError, match="status must be one of"):
        await repository.update_privacy_request(workspace.id, request.id, "shredded")
    assert await repository.open_privacy_request(workspace.id, 999, "export") is None
    assert await repository.update_privacy_request(workspace.id, 999, "completed") is None
