"""Configuration file loading and environment precedence tests."""

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
