"""Regression tests for the xhigh code-review findings on the access layer.

Each test asserts the CORRECT post-fix behavior; before the fixes they fail.
Findings referenced: #1 territory bypass, #2 role/profile stripping,
#3 ZIP-prefix overlap, #4 registry stale state, #7 quota timezone,
#8 falsy-zero sensitive param, #9 unbounded usage growth.
"""

from datetime import UTC, datetime

from cre_mcp.access.capabilities import ToolCapability
from cre_mcp.access.engine import AccessEngine
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.access.profiles import Profile
from cre_mcp.access.territory import location_state, location_within


# -- #1 territory bypass -------------------------------------------------
def test_unresolvable_sibling_location_does_not_bypass_territory(registry, ctx_loc):
    """A bare city with no state must not slip through just because a
    resolvable in-scope sibling value is present in the same call."""
    capability = ToolCapability(
        tool="compare_markets",
        allowed_profiles=("local_scout",),
        territory_params=("locations",),
    )
    engine = AccessEngine(registry, {"compare_markets": capability})

    decision, _sanitized = engine.check_call(
        ctx_loc,
        "compare_markets",
        {"locations": ["Dallas, TX", "Los Angeles"]},
    )

    # The call is denied, so the tool never runs on the out-of-territory value.
    assert decision.outcome == "denied"
    assert "Los Angeles" in decision.reason


# -- #2 role/profile stripping ------------------------------------------
def test_verify_license_keeps_required_role_arg_in_cloud(registry, ctx_nat):
    """verify_license(role=...) is a required business param; the cloud
    sanitizer must preserve it for tools that declare it as safe."""
    engine = AccessEngine(registry)

    decision, sanitized = engine.check_call(
        ctx_nat,
        "verify_license",
        {"name": "Acme LLC", "state": "TX", "role": "broker"},
    )

    assert decision.outcome == "allowed"
    assert sanitized.get("role") == "broker"


def test_set_buyer_profile_keeps_required_profile_arg_in_cloud(registry, ctx_op):
    engine = AccessEngine(registry)

    decision, sanitized = engine.check_call(
        ctx_op,
        "set_buyer_profile",
        {"profile": {"equity": 1_000_000}},
    )

    assert decision.outcome == "allowed"
    assert sanitized.get("profile") == {"equity": 1_000_000}


def test_role_is_still_stripped_for_tools_that_do_not_declare_it(registry, ctx_op):
    """Preservation is per-tool: a tool that never declares role still has
    a client-supplied role stripped (the documented anti-escalation rule)."""
    cap = ToolCapability(
        tool="search_properties",
        allowed_profiles=("full_operator",),
    )
    engine = AccessEngine(registry, {"search_properties": cap})

    _decision, sanitized = engine.check_call(
        ctx_op,
        "search_properties",
        {"location": "TX", "role": "admin", "workspace_id": "ws-other"},
    )

    assert "role" not in sanitized
    assert "workspace_id" not in sanitized


# -- #3 ZIP-prefix overlap ----------------------------------------------
def test_northern_virginia_zip_resolves_to_va_not_dc():
    assert location_state("20101") == "VA"
    assert location_state("20147") == "VA"
    assert location_state("20170") == "VA"
    assert location_within("20101", ("VA",)) is True
    assert location_within("20101", ("DC",)) is False


def test_texas_733_zip_resolves_to_tx_not_ok():
    assert location_state("73301") == "TX"
    assert location_within("73301", ("TX",)) is True


def test_massachusetts_055_zip_resolves_to_ma_not_vt():
    assert location_state("05501") == "MA"


# -- #4 registry stale state --------------------------------------------
def test_grant_added_out_of_band_is_visible_without_restart(tmp_path):
    path = tmp_path / "registry.json"
    live = WorkspaceRegistry(path)
    live.add_grant("k-existing", "ws-existing", Profile.FULL_OPERATOR)

    # A separate process/instance provisions a new workspace on the same file.
    admin = WorkspaceRegistry(path)
    admin.add_grant("k-new", "ws-new", Profile.NATIONAL_SCOUT)

    resolved = live.resolve_key("k-new")
    assert resolved is not None
    assert resolved.workspace_id == "ws-new"


def test_deactivated_grant_stops_working_without_restart(tmp_path):
    path = tmp_path / "registry.json"
    live = WorkspaceRegistry(path)
    live.add_grant("k-live", "ws-live", Profile.FULL_OPERATOR)
    assert live.resolve_key("k-live") is not None

    admin = WorkspaceRegistry(path)
    admin.add_grant("k-live", "ws-live", Profile.FULL_OPERATOR, active=False)

    resolved = live.resolve_key("k-live")
    assert resolved is not None
    assert resolved.active is False


# -- #7 quota timezone ---------------------------------------------------
def test_quota_key_uses_utc_date(tmp_path):
    path = tmp_path / "registry.json"
    reg = WorkspaceRegistry(path)
    reg.record_usage("ws-x", "search")
    utc_today = datetime.now(UTC).date().isoformat()
    assert any(k.endswith(f":{utc_today}") for k in reg._data["usage"])


# -- #8 falsy-zero sensitive param --------------------------------------
def test_zero_valued_sensitive_param_still_triggers_approval(registry, ctx_op):
    cap = ToolCapability(
        tool="wire_funds",
        allowed_profiles=("full_operator",),
        sensitive_params=("amount",),
        approval="transaction",
    )
    engine = AccessEngine(registry, {"wire_funds": cap})

    decision, _ = engine.check_call(ctx_op, "wire_funds", {"amount": 0})

    assert decision.outcome == "approval_required"


# -- #6 middleware reconfigure replaces prior install --------------------
def test_reinstalling_access_control_honors_the_latest_config(tmp_path):
    from cre_mcp.access.middleware import AccessMiddleware
    from cre_mcp.config import CreConfig
    from cre_mcp.server import install_access_control, mcp

    reg_a = tmp_path / "a" / "registry.json"
    reg_b = tmp_path / "b" / "registry.json"
    saved = list(mcp.middleware)
    try:
        install_access_control(
            CreConfig(access_registry_path=reg_a, access_audit_path=tmp_path / "a.jsonl")
        )
        install_access_control(
            CreConfig(access_registry_path=reg_b, access_audit_path=tmp_path / "b.jsonl")
        )
        installed = [m for m in mcp.middleware if isinstance(m, AccessMiddleware)]
        assert len(installed) == 1  # replaced, not stacked
        assert installed[0].engine.registry.path == reg_b  # latest config wins
    finally:
        mcp.middleware[:] = saved


# -- #9 unbounded usage growth ------------------------------------------
def test_stale_daily_usage_keys_are_pruned(tmp_path):
    path = tmp_path / "registry.json"
    reg = WorkspaceRegistry(path)
    reg._data["usage"]["ws-x:search:2000-01-01"] = 7
    reg.record_usage("ws-x", "search")
    assert "ws-x:search:2000-01-01" not in reg._data["usage"]
