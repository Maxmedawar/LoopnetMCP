"""Release contract for withholding dead capabilities from the hosted surface.

Fifteen capabilities are entitled to ``full_operator`` (and most also to
``jv_partner``) and counted in the locked 253 grouped actions, but every hosted
call fails. Each one reaches a *direct* ``DealStore`` construction, and
``DealStore.__init__`` refuses any hosted or untrusted context. That is the
whole criterion: a capability is alive on hosted when it routes through the
``get_deal_store``/``get_search_store`` accessors, which return the certified
hosted port when one is bound, and dead when it constructs the store itself.

Until each one routes through a certified hosted port, the hosted surface must
neither advertise nor execute it, while trusted local stdio and the locked
reconciliation counts stay unchanged.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.capabilities import CAPABILITIES
from cre_mcp.access.context import TenantContext
from cre_mcp.access.middleware import install_access
from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.surface import CUSTOMER_SURFACE, build_customer_server
from cre_mcp.surface.catalog import HOSTED_WITHHELD_CAPABILITIES, LEGACY_TOOL_IDS
from cre_mcp.surface.server import resolve_surface_call

DEAD_HOSTED_CAPABILITIES = (
    "closing_day_runbook",
    "closing_runway",
    "counterparty_dossier",
    "data_room_index",
    "flag_unattended",
    "init_data_room",
    "init_transaction_plan",
    "meeting_briefing",
    "morning_queue",
    "overnight_changes",
    "record_listing_snapshot",
    "stale_listing_signals",
    "transaction_critical_path",
    "update_data_room_item",
    "who_to_call",
)

# The exact denial the hosted path must produce for a withheld action. It must
# differ from the dispatcher's "grouped action is unavailable" fall-through,
# which fires when a resolved action has no internal tool.
WITHHELD_DENIAL = "grouped action is not available"


def _capabilities_reaching_deal_store() -> set[str]:
    """Grouped actions that reach a direct ``DealStore`` construction."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "src"
    package = "cre_mcp"
    deal_store = (f"{package}.deals.store", "DealStore")
    # These accessors return the certified hosted port when one is bound, so
    # reaching them is not fatal. Everything else that reaches a direct
    # construction is dead, because DealStore.__init__ refuses hosted contexts.
    safe = {
        (f"{package}.deals.store", "get_deal_store"),
        (f"{package}.deals.store", "get_search_store"),
    }

    def module_name(path: pathlib.Path) -> str:
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    trees: dict[str, ast.Module] = {}
    packages: set[str] = set()
    for path in src.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        name = module_name(path)
        if path.name == "__init__.py":
            packages.add(name)
        trees[name] = ast.parse(path.read_text(encoding="utf-8"))

    def imports_of(mod: str, tree: ast.Module) -> dict[str, tuple[str, str]]:
        found: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                anchor = mod if mod in packages else mod.rsplit(".", 1)[0]
                for _ in range(node.level - 1):
                    anchor = anchor.rsplit(".", 1)[0] if "." in anchor else package
                target = f"{anchor}.{node.module}" if node.module else anchor
            else:
                target = node.module or ""
            if target.startswith(package):
                for alias in node.names:
                    found[alias.asname or alias.name] = (target, alias.name)
        return found

    def module_aliases_of(mod: str, tree: ast.Module) -> dict[str, str]:
        """Local name -> module it refers to, for attribute-qualified calls.

        Covers `import cre_mcp.deals.store as s`, `from cre_mcp.deals import
        store as s`, and the plain forms. Without this, `s.DealStore()` is
        invisible: the bare attribute name resolves in a module that no longer
        imports it, and a newly dead capability is missed silently.
        """
        found: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(package) and alias.name in trees:
                        found[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = mod if mod in packages else mod.rsplit(".", 1)[0]
                    for _ in range(node.level - 1):
                        anchor = anchor.rsplit(".", 1)[0] if "." in anchor else package
                    target = f"{anchor}.{node.module}" if node.module else anchor
                else:
                    target = node.module or ""
                if not target.startswith(package):
                    continue
                for alias in node.names:
                    candidate = f"{target}.{alias.name}"
                    if candidate in trees:
                        found[alias.asname or alias.name] = candidate
        return found

    imports = {mod: imports_of(mod, tree) for mod, tree in trees.items()}
    module_aliases = {mod: module_aliases_of(mod, tree) for mod, tree in trees.items()}
    definitions = {
        mod: {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        for mod, tree in trees.items()
    }

    def resolve(mod: str, name: str, depth: int = 0) -> tuple[str, str]:
        if depth > 16:
            # Truncating here would silently return a partial resolution and
            # could drop a dead capability from the derived set. The deepest
            # real chain in this tree is 2 hops, so this is a loud tripwire
            # rather than a limit anyone should hit.
            raise AssertionError(
                f"alias chain deeper than 16 hops at {mod}.{name}; "
                "the derivation would truncate silently"
            )
        if name in definitions.get(mod, {}):
            return (mod, name)
        target = imports.get(mod, {}).get(name)
        if target is None or target == (mod, name):
            return (mod, name)
        return resolve(target[0], target[1], depth + 1)

    def calls(mod: str, node: ast.AST) -> set[tuple[str, str]]:
        """Resolved callees of one definition.

        A bare-name-only match is evadable at every propagation step, not just
        at the seed: `import cre_mcp.deals.store as s; s.DealStore()` hides a
        construction, and `import cre_mcp.dataroom as d; d.closing_runway()`
        hides a dead function. Attribute callees are therefore resolved through
        the module a local name is bound to.

        When the qualifier is not a known module (`self.x()`, an instance), the
        attribute name is resolved in module scope. That fallback is UNSOUND IN
        BOTH DIRECTIONS: it can mark a live capability dead when an unrelated
        method shares a name bound in that module, and it misses a call whose
        name is not bound there at all. See the module docstring for what this
        derivation does and does not establish.
        """
        aliases = module_aliases.get(mod, {})
        out: set[tuple[str, str]] = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if isinstance(func, ast.Name):
                out.add(resolve(mod, func.id))
            elif isinstance(func, ast.Attribute):
                qualifier = func.value
                target = (
                    aliases.get(qualifier.id)
                    if isinstance(qualifier, ast.Name)
                    else None
                )
                if target is not None:
                    out.add(resolve(target, func.attr))
                else:
                    out.add(resolve(mod, func.attr))
        return out

    dead = {deal_store}
    changed = True
    while changed:
        changed = False
        for mod, mapping in definitions.items():
            for name, node in mapping.items():
                key = (mod, name)
                if key in dead or key in safe:
                    continue
                # The whole definition is walked, so for a class ANY method
                # reaching a dead callee marks the class dead, not only
                # __init__. That is deliberately over-broad: a store created
                # lazily outside __init__ is reached just as surely, and
                # over-marking fails the set-equality pin loudly rather than
                # under-withholding silently.
                if any(callee in dead for callee in calls(mod, node)):
                    dead.add(key)
                    changed = True

    return {
        capability_id
        for capability_id in CUSTOMER_SURFACE.capability_to_tool
        if resolve(CAPABILITIES[capability_id].module, capability_id) in dead
    }


def _context(profile: Profile) -> TenantContext:
    return TenantContext(
        workspace_id=f"withheld-{profile.value}",
        profile=profile,
        quota_limits={},
        territories=("TX",),
        actor_id="withheld-test-actor",
        session_id="withheld-test-session",
    )


def _internal_fixture() -> FastMCP:
    """Register every withheld capability so the denial cannot be a fall-through.

    If withholding were removed, these actions would resolve and EXECUTE here,
    returning a value instead of raising. That is what makes the end-to-end
    denial pin fail when its behaviour is deleted, rather than passing because
    the internal tool happens to be missing.
    """
    internal = FastMCP(name="withheld-internal-fixture")
    for capability_id in DEAD_HOSTED_CAPABILITIES:

        async def executed() -> dict:
            return {"executed": True}

        internal.tool(name=capability_id)(executed)
    return internal


def _installed_surface(tmp_path: Path, ctx: TenantContext):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    audit = AuditLog(tmp_path / "audit.jsonl")
    app = build_customer_server(_internal_fixture())
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _context: ctx,
        tool_call_resolver=resolve_surface_call,
        tool_visibility_resolver=CUSTOMER_SURFACE.is_visible,
    )
    return app, audit, uninstall


def test_withheld_set_matches_the_recorded_dead_capabilities() -> None:
    assert tuple(sorted(HOSTED_WITHHELD_CAPABILITIES)) == DEAD_HOSTED_CAPABILITIES
    assert set(HOSTED_WITHHELD_CAPABILITIES) <= set(CAPABILITIES)
    for capability_id, reason in HOSTED_WITHHELD_CAPABILITIES.items():
        assert isinstance(reason, str) and reason.strip(), capability_id


def test_withheld_actions_are_absent_from_every_hosted_tool_spec() -> None:
    withheld = set(HOSTED_WITHHELD_CAPABILITIES)
    reachable: set[str] = set()
    for spec in CUSTOMER_SURFACE.tools.values():
        assert spec.hosted_capability_ids, spec.name
        assert withheld.isdisjoint(spec.hosted_capability_ids), spec.name
        assert set(spec.hosted_capability_ids) <= set(spec.capability_ids)
        reachable |= set(spec.hosted_capability_ids)

    assert reachable == set(CUSTOMER_SURFACE.capability_to_tool) - withheld
    assert len(reachable) == 238


@pytest.mark.parametrize("capability_id", DEAD_HOSTED_CAPABILITIES)
def test_withheld_action_never_appears_in_an_advertised_tool_description(
    capability_id: str,
) -> None:
    hosted = build_customer_server(FastMCP(name="withheld-description-fixture"))

    for spec in CUSTOMER_SURFACE.tools.values():
        description = hosted._tool_manager._tools[spec.name].description
        actions = description.split("Exact actions:", 1)[1]
        assert capability_id not in {
            action.strip().rstrip(".") for action in actions.split(",")
        }


@pytest.mark.parametrize("capability_id", DEAD_HOSTED_CAPABILITIES)
def test_withheld_action_is_not_resolvable_from_its_own_group(
    capability_id: str,
) -> None:
    tool_name = CUSTOMER_SURFACE.capability_to_tool[capability_id]

    assert CUSTOMER_SURFACE.resolve(
        tool_name,
        {"action": capability_id, "arguments": {}},
    ) is None
    assert resolve_surface_call(
        tool_name,
        {"action": capability_id, "arguments": {}},
    ) is None


@pytest.mark.parametrize("profile", (Profile.FULL_OPERATOR, Profile.JV_PARTNER))
async def test_withheld_actions_are_hidden_from_a_live_tool_listing(
    tmp_path,
    profile: Profile,
) -> None:
    app, _audit, uninstall = _installed_surface(tmp_path, _context(profile))
    try:
        async with Client(app) as client:
            tools = await client.list_tools()
    finally:
        uninstall()

    for tool in tools:
        for capability_id in DEAD_HOSTED_CAPABILITIES:
            assert capability_id not in tool.description, tool.name


@pytest.mark.parametrize("profile", (Profile.FULL_OPERATOR, Profile.JV_PARTNER))
@pytest.mark.parametrize("capability_id", DEAD_HOSTED_CAPABILITIES)
async def test_direct_hosted_call_to_a_withheld_action_is_denied(
    tmp_path,
    capability_id: str,
    profile: Profile,
) -> None:
    if profile.value not in CAPABILITIES[capability_id].allowed_profiles:
        pytest.skip(f"{capability_id} is not entitled to {profile.value}")
    ctx = _context(profile)
    app, audit, uninstall = _installed_surface(tmp_path, ctx)
    tool_name = CUSTOMER_SURFACE.capability_to_tool[capability_id]
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match=WITHHELD_DENIAL):
                await client.call_tool(
                    tool_name,
                    {"action": capability_id, "arguments": {}},
                )
    finally:
        uninstall()

    # The middleware audits the denial against the grouped tool it was addressed
    # to, not the withheld capability id, so pin that and require the withheld
    # capability itself to appear nowhere in the audit.
    events = audit.events(ctx.workspace_id)
    assert any(
        event.tool == tool_name and event.decision == "denied" for event in events
    )
    assert all(event.tool != capability_id for event in events)


def test_withholding_preserves_the_locked_reconciliation_counts() -> None:
    report = CUSTOMER_SURFACE.reconciliation_report()

    assert report["internal_capability_count"] == 274
    assert report["grouped_action_count"] == 253
    assert report["internal_only_capability_count"] == 21
    assert report["hosted_withheld_capability_count"] == 15
    assert report["hosted_reachable_action_count"] == 238
    assert report["profile_tool_counts"] == {
        Profile.LOCAL_SCOUT.value: 8,
        Profile.NATIONAL_SCOUT.value: 10,
        Profile.FULL_OPERATOR.value: 20,
        Profile.JV_PARTNER.value: 11,
    }
    assert set(report["hosted_withheld_reasons"]) == set(DEAD_HOSTED_CAPABILITIES)


def _catalog_with_withheld(monkeypatch, withheld: dict[str, str]):
    from cre_mcp.surface import catalog as catalog_module

    monkeypatch.setattr(
        catalog_module,
        "HOSTED_WITHHELD_CAPABILITIES",
        MappingProxyType(withheld),
    )
    return catalog_module.CustomerSurfaceCatalog


def test_withholding_an_internal_only_capability_is_rejected(monkeypatch) -> None:
    build = _catalog_with_withheld(
        monkeypatch,
        {"capabilities": "internal-only capability may not be withheld here"},
    )

    with pytest.raises(RuntimeError, match="grouped customer action"):
        build()


def test_withholding_a_legacy_tool_id_is_rejected(monkeypatch) -> None:
    build = _catalog_with_withheld(
        monkeypatch,
        {"find_contact": "legacy id whose reconciliation would overstate reach"},
    )

    with pytest.raises(RuntimeError, match="legacy tool id"):
        build()


def test_no_withheld_capability_is_a_legacy_tool_id() -> None:
    assert set(HOSTED_WITHHELD_CAPABILITIES).isdisjoint(LEGACY_TOOL_IDS)


def test_withholding_every_action_of_a_tool_is_rejected(monkeypatch) -> None:
    # Pick a tool with no legacy action, so the empty-tool guard is what fires
    # rather than the legacy-id guard ahead of it.
    target = next(
        spec
        for spec in CUSTOMER_SURFACE.tools.values()
        if set(spec.hosted_capability_ids).isdisjoint(LEGACY_TOOL_IDS)
    )
    build = _catalog_with_withheld(
        monkeypatch,
        {action: "every action of one tool" for action in target.capability_ids},
    )

    with pytest.raises(RuntimeError, match=f"would empty surface tool '{target.name}'"):
        build()


def test_withholding_a_profiles_last_action_hides_that_tool_for_it(
    monkeypatch,
) -> None:
    build = _catalog_with_withheld(
        monkeypatch,
        {"net_sale_proceeds": "only cre_disposition action for national_scout"},
    )
    catalog = build()

    assert "cre_disposition" not in catalog.visible_names(Profile.NATIONAL_SCOUT)
    assert "cre_disposition" in catalog.visible_names(Profile.FULL_OPERATOR)
    assert len(catalog.visible_names(Profile.NATIONAL_SCOUT)) == 9


@pytest.mark.parametrize("capability_id", DEAD_HOSTED_CAPABILITIES)
async def test_every_withheld_capability_fails_closed_under_an_untrusted_context(
    capability_id: str,
) -> None:
    """Each withheld capability fails closed rather than doing hosted work.

    IMPORTANT — what this does NOT prove. No ``HostedRequestRepositories`` are
    bound here, so ``get_deal_store()`` also raises on an untrusted context.
    A live, accessor-routed capability would therefore fail this way too, and
    this pin CANNOT on its own distinguish dead from alive. Guarding against
    withholding a working capability is the job of
    ``test_withheld_set_equals_the_capabilities_that_reach_a_direct_deal_store``,
    whose set equality fails in both directions.

    What this pin does add is that the failure is the admission error rather
    than a crash, a hang, or partial hosted work.
    """
    import importlib
    import inspect

    from cre_mcp.access.context import use_context
    from cre_mcp.postgres.domains import AdmittedRequestUnavailable

    # Structured arguments for the capabilities whose validation runs before
    # the store construction, so the probe reaches the store rather than
    # bouncing off argument validation.
    structured: dict[str, dict[str, object]] = {
        "who_to_call": {
            "need": {"type": "debt", "deal_context": {"deal_id": "probe"}}
        },
        "closing_day_runbook": {"closing_date": "2026-01-01"},
    }
    module = importlib.import_module(CAPABILITIES[capability_id].module)
    function = getattr(module, capability_id)
    overrides = structured.get(capability_id, {})
    arguments = {
        name: overrides.get(name, "probe")
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.default is inspect.Parameter.empty
    }

    # A dead capability either raises the admission error or catches it and
    # returns it as an error payload. Both are failures; succeeding is not.
    with use_context(_context(Profile.FULL_OPERATOR)):
        try:
            result = function(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except AdmittedRequestUnavailable as raised:
            assert "persistence unavailable" in str(raised)
            return

    assert isinstance(result, dict), result
    assert "persistence unavailable" in repr(result), result


def test_withheld_set_equals_the_capabilities_that_reach_a_direct_deal_store() -> None:
    """Drift detector over the withheld set. NOT a proof of completeness.

    Derives, from the source, the grouped actions that reach a direct
    ``DealStore`` construction, and requires the withheld set to equal it. Set
    equality means the pin goes red in both directions — a newly dead action
    left advertised, and a live action wrongly withheld — so any source change
    that moves the derived set forces a human decision.

    What it resolves: import aliases, package ``__init__`` re-exports (missing
    those is what once hid ``closing_day_runbook``), attribute calls qualified
    by a module alias, and every method of a class rather than only
    ``__init__``. Annotations and other non-call references do not propagate,
    which is why ``DealStore._validate_stage(...)`` — resolved by attribute
    name, not treated as a construction — does not mark its caller dead.

    What it does NOT establish is that the derived set is complete. Static
    resolution here is unsound in both directions; known families, not
    exhaustive: subclassing ``DealStore``; binding it to a module-level name
    and calling that; constructing it at module scope; and the module-scope
    fallback for non-module qualifiers, which can both over- and under-match.

    Callees that are themselves ``Call`` or ``Subscript`` nodes contribute
    nothing, so ``getattr(mod, "DealStore")()`` and dict dispatch ``_D["k"]()``
    are invisible. A fully-dotted ``cre_mcp.deals.store.DealStore()`` after a
    plain dotted import is missed too, but through the module-scope fallback
    above rather than that family: its callee is an ``Attribute`` whose value is
    itself an ``Attribute``. None exists in this tree.

    Completeness of the shipped fifteen rests instead on runtime evidence
    recorded in the launch ledger: independent reviewers bound a real
    ``HostedRequestRepositories`` — under which a direct construction raises
    while ``get_deal_store()`` returns the port — executed every grouped
    action, and each reproduced exactly these fifteen. Promoting that runtime
    derivation to a second pin here is the recommended follow-up; it has none
    of the static blind spots above.

    A red result from this pin therefore means "the source moved, go look",
    never "add whatever the derivation now reports".
    """
    assert set(HOSTED_WITHHELD_CAPABILITIES) == _capabilities_reaching_deal_store()


def test_withheld_capabilities_keep_entitlement_and_grouped_classification() -> None:
    for capability_id in DEAD_HOSTED_CAPABILITIES:
        capability = CAPABILITIES[capability_id]

        assert "full_operator" in capability.allowed_profiles
        assert capability_id in CUSTOMER_SURFACE.capability_to_tool
        assert capability_id not in CUSTOMER_SURFACE.internal_capabilities
        assert capability_id in CUSTOMER_SURFACE.tools[
            CUSTOMER_SURFACE.capability_to_tool[capability_id]
        ].capability_ids
