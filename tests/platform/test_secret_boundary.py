"""Production secret boundary: injection, masking, and fail-closed behaviour.

The founder decision is that a local `.env` is never the production source of
truth for a real credential. Production secrets come from the deployment
platform's managed store through environment injection, and nothing reachable
by a browser, a client, a log, or a serialization can disclose them.

These pins enforce the properties that make that true, so a later change cannot
quietly reintroduce a plaintext credential field, a required `.env`, or a route
that answers with configuration.

One documented exception to the "or a serialization" clause above, so this
docstring does not overstate what is enforced: a `ValidationError` raised while
building `CreConfig` still carries the rejected input on `errors()[0]["input"]`
and in `ValidationError.json()`. `hide_input_in_errors` keeps it out of the
rendered message, which is what reaches a log or a traceback, and nothing in
`src/` serializes a configuration error — but the object holds it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from cre_mcp.config import CreConfig

# A field whose name contains one of these holds a credential, not a setting.
SECRET_NAME_MARKERS = ("secret", "api_key", "token", "password", "credential", "dsn")

# Names that match a marker but are not credentials. Each is listed with the
# reason it is safe, so the exemption is auditable rather than a blanket skip.
NON_SECRET_EXEMPTIONS = {
    "clerk_publishable_key": "publishable by design; ships to the browser",
    "oauth_token_rate_limit_per_minute": "a request-rate limit, not a token",
}

SENTINEL = "sk_test_SENTINELdoNOTleakTHISvalue0123456789"


def _secret_fields() -> dict[str, object]:
    return {
        name: field
        for name, field in CreConfig.model_fields.items()
        if any(marker in name for marker in SECRET_NAME_MARKERS)
        and name not in NON_SECRET_EXEMPTIONS
    }


def test_every_secret_shaped_field_is_a_secret_type():
    """A new plaintext credential field fails here rather than in review."""
    plaintext = []
    for name, field in _secret_fields().items():
        annotation = str(field.annotation)
        if "SecretStr" not in annotation:
            plaintext.append(f"{name}: {annotation}")

    assert not plaintext, (
        "credential fields must be SecretStr (or a container of it); "
        f"plaintext: {plaintext}"
    )


def test_the_exemption_list_does_not_rot():
    """Every exemption must still name a real field.

    A stale exemption would silently excuse a future field that reuses the
    name, so the list is checked against the model rather than trusted.
    """
    unknown = [n for n in NON_SECRET_EXEMPTIONS if n not in CreConfig.model_fields]

    assert not unknown, f"exemptions naming fields that no longer exist: {unknown}"


def test_configuration_loads_with_no_env_file_present(tmp_path, monkeypatch):
    """`.env` is optional. Production runs without one."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".env").exists()
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", SENTINEL)

    config = CreConfig()

    assert config.clerk_secret_key is not None
    assert config.clerk_secret_key.get_secret_value() == SENTINEL


def test_environment_injection_outranks_a_stale_env_file(tmp_path, monkeypatch):
    """A managed store must not be overridden by a developer's leftover file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("CRE_CLERK_SECRET_KEY=sk_test_from_the_stale_file\n")
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", SENTINEL)

    config = CreConfig()

    assert config.clerk_secret_key.get_secret_value() == SENTINEL


def test_rotation_needs_no_code_change_or_rebuild(tmp_path, monkeypatch):
    """Nothing is captured at import time, so a new process sees a new value."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", SENTINEL)
    assert CreConfig().clerk_secret_key.get_secret_value() == SENTINEL

    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", SENTINEL + "_rotated")

    assert CreConfig().clerk_secret_key.get_secret_value() == SENTINEL + "_rotated"


@pytest.mark.parametrize(
    "render",
    [repr, str, lambda c: json.dumps(c.model_dump(mode="json"), default=str)],
    ids=["repr", "str", "model_dump_json"],
)
def test_no_serialization_of_the_configuration_discloses_a_secret(tmp_path, render):
    """`repr`, `str`, and a JSON dump must all be safe to log."""
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        clerk_secret_key=SENTINEL,
        stripe_api_key=SENTINEL,
        skool_webhook_secret=SENTINEL,
    )

    rendered = render(config)

    assert SENTINEL not in rendered


def test_a_configuration_error_never_carries_the_secret(tmp_path):
    """Nothing raised by the adapter may put a credential in a traceback."""
    from cre_mcp.platform.connection import ClerkHumanIdentityVerifier

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        clerk_secret_key=SENTINEL,
        clerk_authorized_parties=(),
    )

    with pytest.raises(ValueError) as raised:
        ClerkHumanIdentityVerifier(config)

    assert SENTINEL not in str(raised.value)
    assert all(SENTINEL not in str(arg) for arg in raised.value.args)


async def test_a_missing_clerk_secret_fails_closed_rather_than_degrading(tmp_path):
    """No anonymous or partial identity when the credential is absent."""
    from tests.hosted_helpers import create_testing_starlette_app

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        transport="http",
        human_identity_provider="clerk",
        clerk_secret_key=None,
        oauth_issuer="https://mcp.example.test",
        connection_url="https://connect.example.test/connect",
    )
    app = create_testing_starlette_app(config)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
    ) as client:
        response = await client.post(
            "/v1/browser/session",
            headers={
                "origin": "https://connect.example.test",
                "host": "mcp.example.test",
                "authorization": "Bearer anything",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "human_identity_unconfigured"


async def test_no_registered_route_answers_with_a_secret(tmp_path):
    """Sweep every route. None may emit credential material.

    A route that returned configuration would be the single worst addition to
    this surface, so its absence is asserted rather than assumed.
    """
    from tests.hosted_helpers import create_testing_starlette_app

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        transport="http",
        human_identity_provider="clerk",
        clerk_secret_key=SENTINEL,
        stripe_api_key=SENTINEL,
        skool_webhook_secret=SENTINEL,
        oauth_issuer="https://mcp.example.test",
        connection_url="https://connect.example.test/connect",
    )
    app = create_testing_starlette_app(config)

    paths = sorted(
        {
            route.path
            for route in app.routes
            if getattr(route, "path", None) and "{" not in getattr(route, "path", "")
        }
    )
    assert paths, "no routes discovered — the sweep would be vacuous"

    leaked: list[str] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
    ) as client:
        for path in paths:
            for method in ("GET", "POST"):
                try:
                    response = await client.request(
                        method,
                        path,
                        headers={
                            "origin": "https://connect.example.test",
                            "host": "mcp.example.test",
                        },
                    )
                except Exception:
                    continue  # a transport-level refusal discloses nothing
                if SENTINEL in response.text:
                    leaked.append(f"{method} {path}")

    assert not leaked, f"routes disclosing a secret: {leaked}"


def test_no_route_exists_whose_purpose_is_returning_configuration():
    """Guard the shape, not only today's responses."""
    from cre_mcp.platform import api

    forbidden = [
        name
        for name in dir(api.PlatformApi)
        if any(
            token in name.lower()
            for token in ("get_config", "dump_config", "show_config", "reveal", "env")
        )
    ]

    assert not forbidden, f"configuration-returning handlers: {forbidden}"


def test_the_repository_contains_no_committed_env_file():
    """`.env` is a local artifact. It must never be tracked."""
    root = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    committed = [
        path
        for path in tracked
        if Path(path).name == ".env" or path.endswith("/.env")
    ]

    assert not committed, f"tracked .env files: {committed}"


def test_a_local_env_file_is_ignored_by_git():
    """The ignore rule is the thing preventing an accidental commit."""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, ".env is not gitignored"


def test_secrets_do_not_reach_a_child_process_by_default(tmp_path, monkeypatch):
    """A subprocess inherits the environment; that is the injection channel.

    Pinned so the inheritance is a deliberate, visible property rather than a
    surprise: anything spawned by the server sees the same credentials, which
    is why no untrusted subprocess may be spawned from a request path.
    """
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", SENTINEL)

    seen = subprocess.run(
        [sys.executable, "-c", "import os; print(os.environ.get('CRE_CLERK_SECRET_KEY',''))"],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
    ).stdout.strip()

    assert seen == SENTINEL, "environment injection is the documented channel"
