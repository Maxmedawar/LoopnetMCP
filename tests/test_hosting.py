"""Phase 24 opt-in hosting and container artifact tests."""

import os
import re
import textwrap
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.http.browser import BrowserFetcher
from cre_mcp.http.fetch import FetchClient
from cre_mcp.platform.api import starlette_app
from cre_mcp.platform.secrets import PRODUCTION_SECRETS
from cre_mcp.server import create_http_app, main, mcp, resolve_transport, run_server
from tests.hosted_helpers import (
    create_testing_http_app,
    make_testing_persistence_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def _config(**values) -> CreConfig:
    return CreConfig(_env_file=None, **values)


def test_stdio_is_the_default_transport(monkeypatch):
    monkeypatch.delenv("CRE_TRANSPORT", raising=False)
    monkeypatch.delenv("LOOPNET_TRANSPORT", raising=False)

    config = _config()

    assert config.transport == "stdio"
    assert resolve_transport(config) == "stdio"


def test_http_transport_resolves_from_environment_without_binding(monkeypatch):
    monkeypatch.setenv("CRE_TRANSPORT", "http")
    monkeypatch.setenv("CRE_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("CRE_HTTP_PORT", "8765")

    config = _config()

    assert resolve_transport(config) == "http"
    assert config.http_host == "127.0.0.1"
    assert config.http_port == 8765


# The three connection strings the hosted process must be given before it may
# reach the PostgreSQL gate at all. Injecting them is what keeps the two tests
# below testing what their names say: without them the secret preflight in
# ``build_postgres_hosted_persistence`` short-circuits first, and the
# PostgreSQL gate they exist to guard is never exercised.
_REQUIRED_DATABASE_URLS = (
    "MEDAWARCRE_DATABASE_URL",
    "MEDAWARCRE_OAUTH_DATABASE_URL",
    "MEDAWARCRE_ADMISSION_DATABASE_URL",
)
# Non-blank, so the preflight is satisfied, and unparseable as a conninfo
# string, so psycopg rejects it before opening a socket. No network, no
# reachable database, and no dependence on the developer's environment.
_UNUSABLE_DSN = "this is not a postgresql connection string"
# The exact refusal the database gate produces. Matching the bare word
# "PostgreSQL" is not enough: every terminal message on this path contains it,
# including the unconditional "domain repositories are not yet certified" raise
# at the end of the function, so a version that never attempted the connection
# at all would still satisfy a substring match and the gate these tests exist
# to guard could be deleted without either of them noticing.
_DATABASE_GATE_REFUSAL = "hosted PostgreSQL is unavailable"
# A value that is genuinely in scope, so an assertion that it does not appear
# in a refusal is one the code can violate.
_VALUE_CANARY_DSN = "postgresql://appuser:refusalvaluecanary@127.0.0.1:1/db"


def _clear_inventory_environment(monkeypatch) -> None:
    """Remove every variable the secret preflight consults.

    Without this these tests inherit the developer's shell. Setting
    `CRE_HUMAN_IDENTITY_PROVIDER=clerk` without a Clerk key — a supported
    configuration — makes the preflight demand a fourth credential and refuse
    before the database gate, so the assertions below fail for a reason outside
    the repository. That is the same defect the locale pin exists to remove.
    """
    from cre_mcp.platform.secrets import PRODUCTION_SECRETS

    names = {"CRE_HUMAN_IDENTITY_PROVIDER", "LOOPNET_HUMAN_IDENTITY_PROVIDER"}
    for secret in PRODUCTION_SECRETS:
        names.update(secret.accepted_names)
    for name in sorted(names):
        monkeypatch.delenv(name, raising=False)


def _inject_unusable_database_urls(monkeypatch) -> None:
    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, _UNUSABLE_DSN)


def test_http_app_fails_closed_before_local_state_without_postgres(
    tmp_path, monkeypatch
):
    _inject_unusable_database_urls(monkeypatch)
    config = _config(cache_db_path=tmp_path / "must-not-exist.db")

    with pytest.raises(RuntimeError) as raised:
        create_http_app(config=config)

    assert _DATABASE_GATE_REFUSAL in str(raised.value)
    assert _UNUSABLE_DSN not in str(raised.value)
    assert not config.cache_db_path.exists()
    assert not (tmp_path / "access" / "registry.json").exists()
    assert not (tmp_path / "access" / "audit.jsonl").exists()


def test_standalone_http_fails_closed_before_local_state_without_postgres(
    tmp_path, monkeypatch
):
    _inject_unusable_database_urls(monkeypatch)
    config = _config(cache_db_path=tmp_path / "standalone-must-not-exist.db")

    with pytest.raises(RuntimeError) as raised:
        starlette_app(config=config)

    assert _DATABASE_GATE_REFUSAL in str(raised.value)
    assert _UNUSABLE_DSN not in str(raised.value)
    assert not config.cache_db_path.exists()


def test_http_app_fails_closed_before_local_state_without_injected_secrets(
    tmp_path, monkeypatch
):
    """The preflight is a second closed door, not a replacement for the first.

    Both gates must create no local state. This one also proves the refusal
    names the absent variables and carries no value, which is the whole reason
    the preflight reports names rather than letting a connection fail later.
    """
    _clear_inventory_environment(monkeypatch)
    # One of the three is present, so "the refusal carries no value" is a
    # property this test can actually falsify. With all three absent there is
    # no value in scope at all, and every value-shaped assertion here holds
    # whether or not the code is correct — which is what the previous two
    # versions of this block did, the second while carrying a comment claiming
    # it had fixed exactly that.
    present = "MEDAWARCRE_DATABASE_URL"
    monkeypatch.setenv(present, _VALUE_CANARY_DSN)
    absent = [name for name in _REQUIRED_DATABASE_URLS if name != present]
    config = _config(cache_db_path=tmp_path / "no-secrets-must-not-exist.db")

    with pytest.raises(RuntimeError) as raised:
        create_http_app(config=config)

    message = str(raised.value)
    assert sorted(absent) == sorted(name for name in absent if name in message)
    assert present not in message, "a secret that was injected was named missing"
    assert "refusalvaluecanary" not in message
    assert _VALUE_CANARY_DSN not in message
    assert not config.cache_db_path.exists()
    assert not (tmp_path / "access" / "registry.json").exists()
    assert not (tmp_path / "access" / "audit.jsonl").exists()


@pytest.mark.parametrize(
    "dsn",
    [
        "this is not a postgresql connection string",
        # A scheme psycopg cannot read as a URL, so it falls back to
        # keyword/value parsing and echoes the first whitespace-delimited
        # token — the whole DSN — into its error message. This is the shape
        # that put a password in a traceback.
        "postgres//appuser:tracebackleakcanary@127.0.0.1:1/medawarcre",
        # A well-formed URL that simply refuses. `from_env` strips, so one
        # stray leading space no longer reaches psycopg as an unparseable
        # token; this keeps the case covered from the other side.
        " postgresql://appuser:tracebackleakcanary@127.0.0.1:1/medawarcre",
    ],
)
def test_an_unreadable_dsn_reaches_no_message_or_traceback(
    tmp_path, monkeypatch, dsn
):
    """A refused connection must not put the connection string in a log.

    psycopg's parse error quotes the input back. Chaining it would place the
    password in every formatted traceback and in any `logging.exception()`
    call, so the database gate raises without a cause.
    """
    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, dsn)
    config = _config(cache_db_path=tmp_path / "leak-must-not-exist.db")

    with pytest.raises(RuntimeError) as raised:
        create_http_app(config=config)

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "tracebackleakcanary" not in rendered
    assert dsn.strip() not in rendered
    assert _DATABASE_GATE_REFUSAL in str(raised.value)
    assert not config.cache_db_path.exists()


def test_a_readiness_refusal_is_not_collapsed_into_the_generic_one(
    tmp_path, monkeypatch
):
    """The `except HostedPersistenceUnavailable: raise` re-raise is load-bearing.

    Without it the readiness refusal falls into the generic handler below and
    becomes `hosted PostgreSQL is unavailable (HostedPersistenceUnavailable)`,
    losing the readiness code an operator needs — and it is the exact handler
    the recorded mutation mechanism depends on, so it must not be deletable
    with the suite green.
    """
    from cre_mcp.postgres import runtime

    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, "postgresql://u:p@127.0.0.1:1/db")
    monkeypatch.setattr(runtime.PostgresDatabase, "open", lambda self, wait=True: None)
    monkeypatch.setattr(
        runtime,
        "check_readiness",
        lambda database, expected: SimpleNamespace(ok=False, code="schema_not_ready"),
    )
    config = _config(cache_db_path=tmp_path / "readiness-must-not-exist.db")

    with pytest.raises(RuntimeError) as raised:
        create_http_app(config=config)

    assert "not release-ready (schema_not_ready)" in str(raised.value)
    assert not config.cache_db_path.exists()


def test_the_database_is_closed_even_when_the_gate_refuses(tmp_path, monkeypatch):
    """Every refusal path runs through `finally: database.close()`.

    Without it each refused start-up leaks a pool, which a supervisor restart
    loop turns into exhausted connections on the server that is already
    failing.
    """
    from cre_mcp.postgres import runtime

    closed: list[bool] = []
    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, "postgresql://u:p@127.0.0.1:1/db")
    monkeypatch.setattr(
        runtime.PostgresDatabase, "close", lambda self: closed.append(True)
    )
    config = _config(cache_db_path=tmp_path / "closed-must-not-exist.db")

    with pytest.raises(RuntimeError):
        create_http_app(config=config)

    assert closed == [True]


def test_the_terminal_refusal_is_the_last_statement_of_the_builder(tmp_path, monkeypatch):
    """A healthy database alone must not produce a hosted persistence bundle.

    This is the door the builder's own docstring says keeps a reachable
    PostgreSQL from accidentally reviving SQLite or file-backed hosted
    authority. It had no test: every working-app test patches
    `build_postgres_hosted_persistence` outright, and every real-call test
    stops at an earlier gate, so a review replaced the final `raise` with a
    file-backed bundle and got a working ASGI app out of both entrypoints with
    the whole suite green.

    The first version of this pin used `inspect.getsource`, and two independent
    reviewers walked straight past it: `inspect.getsourcelines` calls
    `inspect.unwrap` first, so a `functools.wraps` decorator — or a module-level
    rebinding to a wrapper — leaves the AST reading the strict function while a
    different callable answers to the name. Both produced a working hosted ASGI
    app against a live migrated cluster with the whole suite green.

    So the source is read from the module file by name rather than from the
    object, and the object bound to the name is required to be exactly the
    function defined there. `functools.wraps` copies `__name__` and
    `__qualname__` but never `__code__`, which is what makes the identity
    checks below survive a wrapper that impersonates the original.
    """
    import ast

    from cre_mcp.postgres import runtime

    name = "build_postgres_hosted_persistence"
    function_object = getattr(runtime, name)
    code = function_object.__code__

    assert getattr(function_object, "__wrapped__", None) is None, (
        f"{name} is wrapped; the callable that runs is not the one defined here"
    )
    assert code.co_name == name, (
        f"the name {name} is bound to {code.co_name!r}, not to the function "
        "defined in runtime.py"
    )
    module_path = Path(runtime.__file__)
    assert Path(code.co_filename) == module_path

    tree = ast.parse(module_path.read_text())
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(definitions) == 1, f"{name} is defined {len(definitions)} times"
    function = definitions[0]

    assert code.co_firstlineno == function.lineno, (
        f"{name} is bound to a callable defined elsewhere in the module"
    )
    assert not function.decorator_list, (
        f"{name} is decorated; a decorator can return a bundle without the "
        "function body containing a single return statement"
    )

    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    assert not returns, (
        "build_postgres_hosted_persistence returned a bundle; the hosted "
        "domain repositories are not certified, so it must only refuse"
    )

    final = function.body[-1]
    assert isinstance(final, ast.Raise), "the builder no longer ends in a refusal"

    # And the refusal actually fires: every gate above it having passed still
    # yields no bundle.
    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, "postgresql://u:p@127.0.0.1:1/db")
    monkeypatch.setattr(runtime.PostgresDatabase, "open", lambda self, wait=True: None)
    monkeypatch.setattr(runtime.PostgresDatabase, "close", lambda self: None)
    monkeypatch.setattr(
        runtime,
        "check_readiness",
        lambda database, expected: SimpleNamespace(ok=True, code="ok"),
    )

    with pytest.raises(RuntimeError, match="not yet certified"):
        runtime.build_postgres_hosted_persistence()

    config = _config(cache_db_path=tmp_path / "certified-must-not-exist.db")
    with pytest.raises(RuntimeError, match="not yet certified"):
        create_http_app(config=config)
    assert not config.cache_db_path.exists()
    assert not (tmp_path / "access" / "registry.json").exists()
    assert not (tmp_path / "access" / "audit.jsonl").exists()


# Every frame that can reach the terminal refusal, including the one the
# container actually runs: Dockerfile CMD is `python -m cre_mcp --http`, which
# is `__main__` -> `main` -> `run_server`.
_HOSTED_ENTRYPOINTS = (
    "create_http_app",
    "starlette_app",
    "run_server",
    "main",
)


def _dockerfile_environment() -> dict[str, str]:
    """The `ENV` block the shipped container sets, parsed from the Dockerfile.

    Derived rather than transcribed on purpose — see the comment at the call
    site. Handles the backslash-continued single `ENV` instruction the
    Dockerfile uses.
    """
    text = (ROOT / "Dockerfile").read_text()
    joined = text.replace("\\\n", " ")
    values: dict[str, str] = {}
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ENV "):
            continue
        for token in stripped[len("ENV ") :].split():
            if "=" not in token:
                continue
            key, _, value = token.partition("=")
            values[key] = value
    assert values, "no ENV assignments parsed from the Dockerfile"
    return values


def _documented_environment() -> frozenset[str]:
    """Every `CRE_*`/`MEDAWARCRE_*` name `deploy/DEPLOY.md` tells an operator to set."""
    documented = frozenset(
        re.findall(
            r"`((?:CRE|LOOPNET|MEDAWARCRE)_[A-Z0-9_]*)`",
            (ROOT / "deploy" / "DEPLOY.md").read_text(),
        )
    )
    assert documented, "no environment names parsed from DEPLOY.md"
    return documented


def test_the_builder_has_exactly_the_pinned_call_sites():
    """A new caller of the builder must be added to the pin deliberately.

    `_HOSTED_ENTRYPOINTS` is a hand-written list, and this correction learned
    twice that a hand-written list is a place to hide — once for the
    environment, once for the runbook, both since derived. This is the same fix
    for the frame list: the set of modules that call the builder is derived
    from `src/`, so adding a caller fails here until someone also decides
    whether it needs an arm. A new caller inherits the refusal, so this is
    regression insurance rather than a security boundary.
    """
    import ast

    source_root = ROOT / "src"
    sites: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "build_postgres_hosted_persistence"
            ):
                sites.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert len(sites) == 3, (
        f"the builder is called from {len(sites)} sites, not the pinned 3: "
        f"{sites}. Add the new caller to _HOSTED_ENTRYPOINTS, or explain here "
        "why it cannot serve."
    )
    assert {site.split(":")[0] for site in sites} == {
        "cre_mcp/server.py",
        "cre_mcp/platform/api.py",
    }


def test_the_module_entrypoint_stays_a_pure_shim():
    """`python -m cre_mcp` is what the container runs, above `main`.

    A reviewer rebound `build_postgres_hosted_persistence` from inside
    `__main__.py` and served a hosted app with a cache database on disk, whole
    suite green — nothing in the repository reads that file. It is two lines,
    and the property that keeps it safe is that it stays two lines: import
    `main`, call it. Anything else there runs before every gate this suite
    pins.
    """
    import ast

    source = (ROOT / "src" / "cre_mcp" / "__main__.py").read_text()
    body = [
        node
        for node in ast.parse(source).body
        if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        )
    ]

    for node in body:
        # `ast.Try` is deliberately absent from this tuple rather than asserted
        # separately: a second `assert not isinstance(node, ast.Try)` could not
        # fail, since Try is a subclass of none of these.
        assert isinstance(node, (ast.Import, ast.ImportFrom, ast.If, ast.Expr)), (
            f"{type(node).__name__} in __main__.py; it must remain a shim that "
            "imports main and calls it"
        )

    calls = [
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls == ["main"], f"__main__.py calls {calls}, expected exactly ['main']"

    # And `main` must be *the* main. A reviewer left the shim's shape intact,
    # pointed the import at a new `cre_mcp.launch_entry` module that wrapped
    # `cre_mcp.server.main` with a recovery branch, and served a hosted app with
    # the whole suite green. Constraining the shape without constraining where
    # the name comes from constrains nothing.
    imports = [
        node
        for node in ast.parse(source).body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(imports) == 1, f"__main__.py has {len(imports)} imports, expected 1"
    imported = imports[0]
    assert isinstance(imported, ast.ImportFrom), "__main__.py must import from"
    assert imported.module == "cre_mcp.server", (
        f"__main__.py imports main from {imported.module!r}, not cre_mcp.server"
    )
    assert [alias.name for alias in imported.names] == ["main"]
    assert all(alias.asname is None for alias in imported.names)

    assert "build_postgres_hosted_persistence" not in source
    assert "HostedPersistenceBundle" not in source


@pytest.mark.parametrize("entrypoint", _HOSTED_ENTRYPOINTS)
@pytest.mark.parametrize("environment", ["stripped", "production_shaped"])
def test_no_entrypoint_recovers_from_the_terminal_refusal(
    tmp_path, monkeypatch, entrypoint, environment
):
    """Refusing in the builder is worth nothing if a caller catches it.

    This defect has now been relocated four times, each repair correct for the
    instance it was given and open at the next frame: into the builder body,
    behind a `functools.wraps` decorator and a module rebinding, into the caller
    `starlette_app`, and into `main` — the frame the Dockerfile actually runs.
    Each time the whole suite stayed green.

    Two things make this arm-set harder to walk around than its predecessors.
    It covers `main`, so there is no frame above the pinned ones left inside
    `src/`. And it runs each entrypoint under a **production-shaped**
    environment as well as a stripped one: a reviewer gated a recovery branch on
    `MEDAWARCRE_MIGRATION_DATABASE_URL`, which a real deployment sets and which
    `_clear_inventory_environment` deletes, so the previous version of this test
    could not see it. Stripping the environment was itself the hiding place.
    """
    import fastmcp

    from cre_mcp.postgres import runtime

    _clear_inventory_environment(monkeypatch)
    for name in _REQUIRED_DATABASE_URLS:
        monkeypatch.setenv(name, "postgresql://u:p@127.0.0.1:1/db")
    if environment == "production_shaped":
        # The container's own ENV block, read from the Dockerfile rather than
        # transcribed. A hand-written list of "production-shaped" names has now
        # failed twice: first it omitted `MEDAWARCRE_MIGRATION_DATABASE_URL`,
        # then `CRE_HTTP_HOST=0.0.0.0` and `CRE_HTTP_PORT=8000`, and each
        # omission was a place to hide a recovery branch. Deriving it means the
        # next `ENV` line is covered without anyone remembering.
        for key, value in _dockerfile_environment().items():
            if key.startswith("CRE_"):
                monkeypatch.setenv(key, value)
        # And every variable the runbook tells a deployment to supply. The
        # Dockerfile's ENV is the image default set, not the deployment's:
        # `CRE_CLERK_PUBLISHABLE_KEY` is documented in DEPLOY.md, is correctly
        # not a secret and so not in PRODUCTION_SECRETS, and is not in the
        # Dockerfile — a reviewer gated a recovery on exactly that gap. Derived
        # from the runbook for the same reason the ENV block is derived from
        # the Dockerfile: a hand-written list is a place to hide.
        for key in _documented_environment():
            if key.startswith("CRE_") and key not in os.environ:
                monkeypatch.setenv(key, f"documented-{key.lower()}")
        # Everything an operator injects, so a branch gated on any of it is
        # exercised rather than hidden. Shapes matter: several of these fields
        # validate, and an invalid one would fail this test for the wrong
        # reason.
        for secret in PRODUCTION_SECRETS:
            if secret.name.endswith("_DATABASE_URL"):
                value = "postgresql://u:p@127.0.0.1:1/db"
            elif secret.name == "CRE_STRIPE_API_KEY":
                value = "sk_test_injectedbyaproductionshapedenvironment"
            elif secret.name.endswith("_URL"):
                value = "http://127.0.0.1:1"
            else:
                value = f"injected-{secret.name.lower()}"
            monkeypatch.setenv(secret.name, value)
        monkeypatch.setenv("CRE_HUMAN_IDENTITY_PROVIDER", "clerk")

    monkeypatch.setattr(runtime.PostgresDatabase, "open", lambda self, wait=True: None)
    monkeypatch.setattr(runtime.PostgresDatabase, "close", lambda self: None)
    monkeypatch.setattr(
        runtime,
        "check_readiness",
        lambda database, expected: SimpleNamespace(ok=True, code="ok"),
    )

    def _must_not_serve(*args, **kwargs):
        raise AssertionError(
            "a hosted server was started after the terminal refusal"
        )

    # Without this a bypassed refusal does not fail the test — it binds
    # 0.0.0.0:8000 and blocks forever, which a reviewer reproduced as an
    # indefinite hang rather than a red test.
    monkeypatch.setattr(fastmcp.FastMCP, "run", _must_not_serve)

    config = _config(cache_db_path=tmp_path / f"{entrypoint}-must-not-exist.db")
    monkeypatch.setattr(
        "cre_mcp.server.CreConfig", lambda *a, **k: config, raising=False
    )
    calls = {
        "create_http_app": lambda: create_http_app(config=config),
        "starlette_app": lambda: starlette_app(config=config),
        "run_server": lambda: run_server(config=config, force_http=True),
        "main": lambda: main(["--http"]),
    }

    with pytest.raises(RuntimeError, match="not yet certified"):
        calls[entrypoint]()

    assert not config.cache_db_path.exists()
    assert not (tmp_path / "access" / "registry.json").exists()
    assert not (tmp_path / "access" / "audit.jsonl").exists()


def test_internal_global_server_rejects_direct_http_app_construction():
    with pytest.raises(RuntimeError, match="stdio-only"):
        mcp.http_app()


def test_internal_global_server_rejects_direct_http_run():
    with pytest.raises(RuntimeError, match="stdio-only"):
        mcp.run(transport="http")


def test_internal_global_server_preserves_default_stdio_run():
    from fastmcp import FastMCP

    with patch.object(FastMCP, "run") as run:
        mcp.run()

    run.assert_called_once_with(transport=None, show_banner=True)


async def test_internal_global_server_rejects_async_http_run_paths():
    with pytest.raises(RuntimeError, match="stdio-only"):
        await mcp.run_async(transport="http")
    with pytest.raises(RuntimeError, match="stdio-only"):
        await mcp.run_http_async()


def test_http_app_constructs_at_mcp_path_without_binding(tmp_path):
    app = create_testing_http_app(
        config=_config(cache_db_path=tmp_path / "platform.db")
    )

    assert callable(app)
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)


def test_http_app_serves_platform_routes_alongside_mcp(tmp_path):
    app = create_testing_http_app(
        config=_config(cache_db_path=tmp_path / "platform.db")
    )

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/v1/me" in paths
    assert "/v1/deals" not in paths
    assert "/v1/deals/{deal_id:int}" not in paths


async def test_http_app_closes_postgres_bundle_once_with_asgi_lifespan(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")
    seeded = make_testing_persistence_bundle(config)
    close = Mock()
    bundle = type(seeded)(
        platform_api=seeded.platform_api,
        domain_repository_provider=seeded.domain_repository_provider,
        oauth_authority=seeded.oauth_authority,
        admission_repository=seeded.admission_repository,
        audit_log=seeded.audit_log,
        close_callback=close,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ):
        app = create_http_app(config=config)

    async with app.router.lifespan_context(app):
        pass
    bundle.close()

    close.assert_called_once_with()


def test_http_app_closes_postgres_bundle_on_construction_failure(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")
    seeded = make_testing_persistence_bundle(config)
    close = Mock()
    bundle = type(seeded)(
        platform_api=seeded.platform_api,
        domain_repository_provider=seeded.domain_repository_provider,
        oauth_authority=seeded.oauth_authority,
        admission_repository=seeded.admission_repository,
        audit_log=seeded.audit_log,
        close_callback=close,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ), patch(
        "cre_mcp.server._build_hosted_customer_server",
        side_effect=RuntimeError("construction failed"),
    ), pytest.raises(RuntimeError, match="construction failed"):
        create_http_app(config=config)

    close.assert_called_once_with()


def test_http_app_rejects_incomplete_lifecycle_bundle_and_closes(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")
    seeded = make_testing_persistence_bundle(config)
    close = Mock()
    bundle = type(seeded)(
        platform_api=seeded.platform_api,
        audit_log=seeded.audit_log,
        domain_repository_provider=None,
        close_callback=close,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ), pytest.raises(RuntimeError, match="explicit PostgreSQL authority"):
        create_http_app(config=config)

    close.assert_called_once_with()


def test_public_standalone_app_cannot_mount_uncertified_deal_routes(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")

    with pytest.raises(TypeError, match="include_uncertified_deal_routes"):
        starlette_app(config=config, include_uncertified_deal_routes=True)


async def test_platform_routes_enforce_auth_through_the_composed_app(tmp_path):
    import httpx

    from cre_mcp.access.profiles import Profile
    from cre_mcp.platform.auth import OAuthSessionStore
    from cre_mcp.platform.repository import PlatformRepository

    config = _config(cache_db_path=tmp_path / "platform.db")
    app = create_testing_http_app(config=config)

    repo = PlatformRepository(config.cache_db_path)
    auth = OAuthSessionStore(config.cache_db_path)
    assert await repo.create_plan("pro", "Professional") is not None
    workspace = await repo.create_workspace("Acme CRE")
    user = await repo.create_user("owner@example.com", "Owner")
    assert workspace is not None and user is not None
    assert await repo.add_membership(workspace.public_id, user.id, role="owner")
    client = auth.register_client(
        "Claude",
        ("https://claude.ai/api/mcp/auth_callback",),
        ("deals:read",),
    )
    from cre_mcp.platform.entitlements import EntitlementStore

    EntitlementStore(config.cache_db_path).grant_access(
        workspace=workspace.public_id,
        source="manual",
        external_ref="hosting-grant",
        profile=Profile.FULL_OPERATOR,
        plan_key="pro",
        subject_user_id=user.id,
        scope="subject",
    )
    tokens = auth.issue_session(
        workspace.public_id,
        user.id,
        client.client_id,
        scopes=("deals:read",),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        unauthorized = await http.get("/v1/me")
        authorized = await http.get(
            "/v1/me", headers={"authorization": f"Bearer {tokens.access_token}"}
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["session"]["workspace_id"] == workspace.public_id


def test_run_server_keeps_stdio_call_shape_by_default(tmp_path):
    with patch("cre_mcp.server.mcp.run") as run:
        run_server(
            _config(transport="stdio", cache_db_path=tmp_path / "platform.db")
        )

    run.assert_called_once_with(transport="stdio")


def test_run_server_binds_configured_http_host_and_port(tmp_path):
    from fastmcp import FastMCP

    hosted = FastMCP(name="hosted-test")
    config = _config(
        transport="http",
        http_host="127.0.0.1",
        http_port=9123,
        cache_db_path=tmp_path / "platform.db",
    )
    bundle = make_testing_persistence_bundle(config)
    close = Mock()
    bundle.close_callback = close
    with patch(
        "cre_mcp.server._build_hosted_customer_server",
        return_value=hosted,
    ), patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ), patch.object(hosted, "run") as run:
        run_server(config)

    run.assert_called_once_with(
        transport="http",
        host="127.0.0.1",
        port=9123,
        json_response=True,
    )
    close.assert_called_once_with()


def test_http_cli_flag_forces_http_without_binding():
    with patch("cre_mcp.server.run_server") as run:
        main(["--http"])

    run.assert_called_once_with(force_http=True)


def test_proxy_is_scoped_to_scraper_policies():
    config = _config(
        proxy_url="https://proxy-user:proxy-pass@example.test:8443",
        source_rights_enabled={
            "listing.loopnet": True,
            "market.census_acs": True,
        },
    )
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        client = FetchClient(config=config)
        client._get_client(client._policy_for_url("https://www.loopnet.com/search"))
        loopnet_kwargs = session_class.call_args.kwargs
        client._get_client(
            client._policy_for_url("https://api.census.gov/data/2024/acs/acs5")
        )
        census_kwargs = session_class.call_args.kwargs

    assert loopnet_kwargs["proxy"] == (
        "https://proxy-user:proxy-pass@example.test:8443"
    )
    assert loopnet_kwargs["allow_redirects"] is False
    assert "proxy" not in census_kwargs
    assert census_kwargs["allow_redirects"] is False


def test_browser_path_and_proxy_feed_nodriver_launch_options():
    fetcher = BrowserFetcher(
        _config(
            browser_path="/usr/bin/chromium",
            proxy_url="https://proxy.example.test:443",
        )
    )

    options = fetcher._launch_options()
    assert options["headless"] is True
    assert options["sandbox"] is False  # required for launchd/service startup
    assert options["browser_executable_path"] == "/usr/bin/chromium"
    # Sandbox-disabling flags must be present so Chromium starts as a service,
    # and the proxy arg is appended after them.
    assert "--no-sandbox" in options["browser_args"]
    assert "--disable-dev-shm-usage" in options["browser_args"]
    assert options["browser_args"][-1] == "--proxy-server=https://proxy.example.test:443"


def test_hosting_artifacts_are_present_and_keep_secrets_out_of_image():
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    tunnel = (ROOT / "deploy/cloudflared-config.example.yml").read_text()
    deploy = (ROOT / "deploy/DEPLOY.md").read_text()
    env_example = (ROOT / ".env.example").read_text()

    assert dockerfile.startswith("FROM python:3.11-slim")
    assert "CRE_TRANSPORT=http" in dockerfile
    assert "CRE_BROWSER_PATH=/usr/bin/chromium" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert '["python", "-m", "cre_mcp", "--http"]' in dockerfile
    assert "pip install '.[truth]'" in dockerfile
    assert 'python -c "import cre_mcp.server"' in dockerfile
    assert "pip install -e ." not in dockerfile
    assert ".env" in dockerignore
    assert "LAUNCH BLOCKED" in tunnel
    assert "service: http://cre-mcp:8000" in tunnel
    assert "service: http_status:404" in tunnel
    assert "Status: **not runnable and not approved for public deployment**" in deploy
    assert "docs/launch/PROGRAM_STATUS.md" in deploy
    assert "there is no supported deployment command" in deploy
    assert "docker run -d" not in deploy
    assert "cloudflared tunnel route dns" not in deploy
    assert "claude mcp add --transport http" not in deploy
    assert "not a production deployment template" in env_example
    assert "MEDAWARCRE_DATABASE_URL" not in env_example
    assert "MEDAWARCRE_OAUTH_DATABASE_URL" not in env_example
