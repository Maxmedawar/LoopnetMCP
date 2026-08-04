"""Configuration file loading and environment precedence tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cre_mcp.config import CreConfig


def test_config_loads_cre_keys_from_dotenv_file(tmp_path, monkeypatch):
    names = (
        "CRE_CENSUS_API_KEY",
        "CRE_BLS_API_KEY",
        "CRE_FRED_API_KEY",
        "CRE_HUD_API_TOKEN",
        "CRE_BEA_API_KEY",
        "CRE_ATTOM_API_KEY",
        "CRE_REGRID_API_KEY",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{name}={name.casefold()}-fixture" for name in names)
        + "\nUNRELATED_SETTING=ignored\n"
    )

    config = CreConfig(_env_file=env_file)

    assert config.census_api_key.get_secret_value() == "cre_census_api_key-fixture"
    assert config.bls_api_key.get_secret_value() == "cre_bls_api_key-fixture"
    assert config.fred_api_key.get_secret_value() == "cre_fred_api_key-fixture"
    assert config.hud_api_token.get_secret_value() == "cre_hud_api_token-fixture"
    assert config.bea_api_key.get_secret_value() == "cre_bea_api_key-fixture"
    assert config.attom_api_key.get_secret_value() == "cre_attom_api_key-fixture"
    assert config.regrid_api_key.get_secret_value() == "cre_regrid_api_key-fixture"


def test_oauth_refresh_family_max_age_defaults_to_90_and_reads_environment(
    monkeypatch,
):
    monkeypatch.delenv("CRE_OAUTH_REFRESH_FAMILY_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("LOOPNET_OAUTH_REFRESH_FAMILY_MAX_AGE_DAYS", raising=False)
    assert CreConfig(_env_file=None).oauth_refresh_family_max_age_days == 90

    monkeypatch.setenv("CRE_OAUTH_REFRESH_FAMILY_MAX_AGE_DAYS", "45")
    assert CreConfig(_env_file=None).oauth_refresh_family_max_age_days == 45


def test_env_example_documents_every_provider_setting_without_skool_secret():
    text = (Path(__file__).parents[1] / ".env.example").read_text()
    expected = {
        "CRE_STRIPE_WEBHOOK_SECRET",
        "CRE_SKOOL_WEBHOOK_SECRET",
        "CRE_PROVIDER_WEBHOOK_MAX_BODY_BYTES",
        "CRE_PROVIDER_GRANT_LEASE_SECONDS",
        "CRE_STRIPE_PRICE_MAPPINGS",
        "CRE_SKOOL_TIER_MAPPINGS",
    }

    for name in expected:
        assert text.count(name) == 1
    assert "# CRE_SKOOL_WEBHOOK_SECRET=" in text
    assert "CRE_SKOOL_WEBHOOK_SECRET=replace" not in text


def test_clerk_and_connection_urls_are_https_origins_except_loopback():
    config = CreConfig(
        _env_file=None,
        oauth_issuer="http://localhost:8000/",
        connection_url="http://127.0.0.1:5173/connect",
        clerk_issuer="https://clerk.example.test/",
        clerk_authorized_parties=(
            "https://connect.example.test/",
            "https://connect.example.test",
        ),
    )
    assert config.oauth_issuer == "http://localhost:8000"
    assert config.clerk_issuer == "https://clerk.example.test"
    assert config.clerk_authorized_parties == ("https://connect.example.test",)

    invalid = (
        {"oauth_issuer": "http://mcp.example.test"},
        {"oauth_issuer": "https://mcp.example.test/oauth"},
        {"connection_url": "http://connect.example.test/connect"},
        {"connection_url": "https://connect.example.test/connect#token"},
        {"clerk_issuer": "https://clerk.example.test/path"},
        {"clerk_authorized_parties": ("https://connect.example.test/path",)},
    )
    for values in invalid:
        with pytest.raises(ValidationError):
            CreConfig(_env_file=None, **values)


def test_blank_clerk_secrets_and_text_are_unconfigured():
    config = CreConfig(
        _env_file=None,
        clerk_secret_key="   ",
        clerk_publishable_key=" ",
        clerk_issuer=" ",
    )
    assert config.clerk_secret_key is None
    assert config.clerk_publishable_key is None
    assert config.clerk_issuer is None


def test_operations_console_origin_is_https_origin_or_disabled():
    assert (
        CreConfig(
            _env_file=None,
            operations_console_origin="https://operations.example.test/",
        ).operations_console_origin
        == "https://operations.example.test"
    )
    assert (
        CreConfig(
            _env_file=None,
            operations_console_origin="   ",
        ).operations_console_origin
        is None
    )

    for value in (
        "http://operations.example.test",
        "https://operations.example.test/console",
        "https://operations.example.test?workspace=attacker",
    ):
        with pytest.raises(ValidationError):
            CreConfig(_env_file=None, operations_console_origin=value)
