"""Provider-neutral external account mapping API tests."""

from __future__ import annotations

from .admin_helpers import (
    VALID_REASON,
    api_client,
    audit_rows,
    config_for,
    provision_identity,
    provision_target,
)


async def _setup(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "External Mapping Admin",
        internal_role="platform_admin",
    )
    first = await provision_target(config, "Mapped Workspace")
    second = await provision_target(config, "Other Mapped Workspace")
    return config, actor, first, second


async def test_external_account_create_list_and_delete_roundtrip(tmp_path):
    config, actor, target, _ = await _setup(tmp_path)

    async with api_client(config) as client:
        created = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": "stripe",
                "external_account_id": "cus_123",
                "subject_user_id": target.user_id,
                "metadata": {"region": "us", "mode": "live"},
                **VALID_REASON,
            },
        )
        listed = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
        )
        mapping_id = created.json()["external_account"]["id"]
        deleted = await client.request(
            "DELETE",
            f"/v1/admin/workspaces/{target.workspace_id}"
            f"/external-accounts/{mapping_id}",
            headers=actor.headers,
            json=VALID_REASON,
        )
        after = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
        )

    assert created.status_code == 201
    assert created.json()["external_account"]["provider"] == "stripe"
    assert created.json()["external_account"]["subject_user_id"] == target.user_id
    assert created.json()["external_account"]["metadata"] == {
        "mode": "live",
        "region": "us",
    }
    assert listed.status_code == 200
    assert [item["external_account_id"] for item in listed.json()["external_accounts"]] == [
        "cus_123"
    ]
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert after.json()["external_accounts"] == []
    assert len(audit_rows(config.cache_db_path)) == 2


async def test_duplicate_external_mapping_is_409_and_has_no_failed_audit(tmp_path):
    config, actor, first, second = await _setup(tmp_path)
    payload = {
        "provider": "stripe",
        "external_account_id": "cus_77",
        "subject_user_id": first.user_id,
        **VALID_REASON,
    }

    async with api_client(config) as client:
        created = await client.post(
            f"/v1/admin/workspaces/{first.workspace_id}/external-accounts",
            headers=actor.headers,
            json=payload,
        )
        before = len(audit_rows(config.cache_db_path))
        duplicate = await client.post(
            f"/v1/admin/workspaces/{second.workspace_id}/external-accounts",
            headers=actor.headers,
            json={**payload, "subject_user_id": second.user_id},
        )

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error": {
            "code": "conflict",
            "message": "External account mapping already exists",
        }
    }
    assert len(audit_rows(config.cache_db_path)) == before


async def test_external_identifier_is_trimmed_case_preserving_and_case_sensitive(
    tmp_path,
):
    config, actor, target, _ = await _setup(tmp_path)

    async with api_client(config) as client:
        upper = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": " Stripe ",
                "external_account_id": " Customer-AbC ",
                "subject_user_id": target.user_id,
                **VALID_REASON,
            },
        )
        lower = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": "STRIPE",
                "external_account_id": "customer-abc",
                "subject_user_id": target.user_id,
                **VALID_REASON,
            },
        )

    assert upper.status_code == 201
    assert lower.status_code == 201
    assert upper.json()["external_account"]["provider"] == "stripe"
    assert lower.json()["external_account"]["provider"] == "stripe"
    assert upper.json()["external_account"]["external_account_id"] == "Customer-AbC"
    assert lower.json()["external_account"]["external_account_id"] == "customer-abc"
    assert len(audit_rows(config.cache_db_path)) == 2


async def test_external_mapping_delete_is_workspace_scoped(tmp_path):
    config, actor, first, second = await _setup(tmp_path)
    async with api_client(config) as client:
        created = await client.post(
            f"/v1/admin/workspaces/{first.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": "skool",
                "external_account_id": "member-1",
                "subject_user_id": first.user_id,
                **VALID_REASON,
            },
        )
        mapping_id = created.json()["external_account"]["id"]
        wrong_workspace = await client.request(
            "DELETE",
            f"/v1/admin/workspaces/{second.workspace_id}"
            f"/external-accounts/{mapping_id}",
            headers=actor.headers,
            json=VALID_REASON,
        )
        still_listed = await client.get(
            f"/v1/admin/workspaces/{first.workspace_id}/external-accounts",
            headers=actor.headers,
        )

    assert wrong_workspace.status_code == 404
    assert [item["id"] for item in still_listed.json()["external_accounts"]] == [
        mapping_id
    ]
    assert len(audit_rows(config.cache_db_path)) == 1


async def test_external_mapping_requires_nonblank_provider_and_identifier(tmp_path):
    config, actor, target, _ = await _setup(tmp_path)

    async with api_client(config) as client:
        blank_provider = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": " ",
                "external_account_id": "acct",
                "subject_user_id": target.user_id,
                **VALID_REASON,
            },
        )
        blank_identifier = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": "vendor",
                "external_account_id": " ",
                "subject_user_id": target.user_id,
                **VALID_REASON,
            },
        )

    assert blank_provider.status_code == 422
    assert blank_identifier.status_code == 422
    assert audit_rows(config.cache_db_path) == []
