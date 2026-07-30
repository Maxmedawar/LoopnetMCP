"""Regression coverage for deterministic SQLite connection ownership."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.authority import AuthorityResolver
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository


def _fd_count() -> int:
    for candidate in (Path("/proc/self/fd"), Path("/dev/fd")):
        if candidate.is_dir():
            return len(os.listdir(candidate))
    pytest.skip("platform does not expose a process file-descriptor directory")


async def test_repeated_repository_reads_do_not_grow_fds(tmp_path):
    path = tmp_path / "repository.db"
    repository = PlatformRepository(path)
    assert await repository.create_plan("pro", "Professional") is not None
    assert len(await repository.list_plans()) == 1
    baseline = _fd_count()

    for _ in range(200):
        assert len(await repository.list_plans()) == 1

    assert _fd_count() <= baseline + 3


async def test_repeated_authority_and_entitlement_resolves_do_not_grow_fds(
    tmp_path,
):
    path = tmp_path / "platform.db"
    repository = PlatformRepository(path)
    plan = await repository.create_plan("pro", "Professional")
    workspace = await repository.create_workspace("FD Lifecycle")
    user = await repository.create_user("fd@example.test", "FD Owner")
    assert plan is not None and workspace is not None and user is not None
    membership = await repository.add_membership(
        workspace.public_id,
        user.id,
        role="owner",
    )
    assert membership is not None

    auth = OAuthSessionStore(path)
    client = auth.register_client(
        "FD Client",
        ("https://claude.ai/api/mcp/auth_callback",),
        ("mcp:tools",),
    )
    tokens = auth.issue_session(
        workspace.public_id,
        user.id,
        client.client_id,
        scopes=("mcp:tools",),
    )
    entitlements = EntitlementStore(path)
    entitlements.grant_access(
        workspace=workspace.public_id,
        source="manual",
        external_ref="fd-grant",
        profile=Profile.FULL_OPERATOR,
        plan_key="pro",
        subject_user_id=user.id,
        scope="subject",
    )
    resolver = AuthorityResolver(path)

    assert resolver.resolve(tokens.access_token).access_allowed
    assert entitlements.get_account(workspace.public_id) is not None
    baseline = _fd_count()

    for _ in range(200):
        assert resolver.resolve(tokens.access_token).access_allowed
        assert entitlements.get_account(workspace.public_id) is not None

    assert _fd_count() <= baseline + 3
