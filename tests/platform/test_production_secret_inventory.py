"""Pins for the production secret inventory and the hosted startup preflight.

`src/cre_mcp/platform/secrets.py` and the `build_postgres_hosted_persistence`
preflight that consumes it shipped in `5452be3` with no test of their own: that
commit's message and ledger entry both describe the module as read and deleted,
and its test module covers only `CreConfig`. These pins close that gap.

The sharpest of them is `test_every_activation_condition_names_a_real_setting`.
The module `5452be3` did delete was rejected for gating credentials behind
`CRE_STRIPE_ENABLED` and `CRE_SKOOL_ENABLED`, flags nothing in this codebase
reads — so the secrets would silently never have been required while the code
read as though it checked them. Nothing stopped the surviving module from
acquiring the same defect. Now something does.
"""

from __future__ import annotations

import importlib
import re
import traceback
import typing
from pathlib import Path

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.secrets import (
    PRODUCTION_SECRETS,
    REQUIREMENTS,
    ProductionSecret,
    ProductionSecretsUnavailable,
    missing_production_secrets,
    required_production_secrets,
    verify_production_secrets,
)

DEPLOY_DOC = Path(__file__).resolve().parents[2] / "deploy" / "DEPLOY.md"

# A value a deployer would actually inject, used to prove nothing echoes one.
SENTINEL = "postgresql://medawarcre:SENTINELdoNOTleak@127.0.0.1:5432/medawarcre"

REQUIRED_NAMES = (
    "MEDAWARCRE_DATABASE_URL",
    "MEDAWARCRE_OAUTH_DATABASE_URL",
    "MEDAWARCRE_ADMISSION_DATABASE_URL",
)

# Every credential the inventory describes, written out rather than derived, so
# that deleting one fails here. See test_the_inventory_has_not_silently_shrunk.
EXPECTED_INVENTORY = frozenset(
    {
        "MEDAWARCRE_DATABASE_URL",
        "MEDAWARCRE_OAUTH_DATABASE_URL",
        "MEDAWARCRE_ADMISSION_DATABASE_URL",
        "MEDAWARCRE_MIGRATION_DATABASE_URL",
        "MEDAWARCRE_APP_DATABASE_URL",
        "MEDAWARCRE_BACKUP_DATABASE_URL",
        "CRE_CLERK_SECRET_KEY",
        "CRE_STRIPE_API_KEY",
        "CRE_STRIPE_WEBHOOK_SECRET",
        "CRE_SKOOL_WEBHOOK_SECRET",
        "CRE_PROXY_URL",
        "CRE_CENSUS_API_KEY",
        "CRE_BLS_API_KEY",
        "CRE_FRED_API_KEY",
        "CRE_HUD_API_TOKEN",
        "CRE_BEA_API_KEY",
        "CRE_RENTCAST_API_KEY",
        "CRE_SKIPTRACE_API_KEY",
        "CRE_ATTOM_API_KEY",
        "CRE_REGRID_API_KEY",
        "CRE_SOCRATA_APP_TOKEN",
    }
)


def _by_name(name: str) -> ProductionSecret:
    for secret in PRODUCTION_SECRETS:
        if secret.name == name:
            return secret
    raise AssertionError(f"the inventory no longer describes {name}")


def _env(**values: str) -> dict[str, str]:
    """A complete environment: only what is passed is present."""
    return dict(values)


def _satisfied(**overrides: str) -> dict[str, str]:
    environ = {name: SENTINEL for name in REQUIRED_NAMES}
    environ.update(overrides)
    return environ


def test_the_inventory_names_are_unique_and_every_requirement_is_known():
    names = [secret.name for secret in PRODUCTION_SECRETS]

    assert len(names) == len(set(names)), "a duplicated name would mask one entry"
    assert {secret.requirement for secret in PRODUCTION_SECRETS} <= REQUIREMENTS


def test_only_required_and_activated_conditional_secrets_are_demanded():
    """Operator, self-gating, and optional secrets are never start-up blockers.

    The serving process must not hold the migration credential, so an operator
    secret appearing here would be a privilege defect and not just noise.
    """
    demanded = {
        secret.name for secret in required_production_secrets(_env())
    }

    assert demanded == set(REQUIRED_NAMES)
    for secret in PRODUCTION_SECRETS:
        if secret.requirement in {"operator", "self_gating", "optional"}:
            assert secret.name not in demanded


def test_a_conditional_secret_is_demanded_only_when_its_condition_holds():
    clerk = _by_name("CRE_CLERK_SECRET_KEY")
    variable, expected = clerk.activated_by

    off = {s.name for s in required_production_secrets(_env(**{variable: "disabled"}))}
    on = {s.name for s in required_production_secrets(_env(**{variable: expected}))}
    legacy_variable = variable.replace("CRE_", "LOOPNET_", 1)
    through_alias = {
        s.name
        for s in required_production_secrets(_env(**{legacy_variable: expected}))
    }

    assert clerk.name not in off
    assert clerk.name in on
    assert clerk.name in through_alias


def test_every_activation_condition_names_a_real_setting():
    """The defect that rejected the deleted module cannot recur unnoticed.

    A condition on a variable nothing reads, or on a value the setting cannot
    take, silently makes its credential optional forever.
    """
    accepted: set[str] = set()
    for name, field in CreConfig.model_fields.items():
        accepted.add(f"CRE_{name.upper()}")
        accepted.add(f"LOOPNET_{name.upper()}")

    for secret in PRODUCTION_SECRETS:
        if secret.activated_by is None:
            continue
        variable, expected = secret.activated_by
        assert variable in accepted, (
            f"{secret.name} is gated on {variable}, which no setting accepts"
        )
        field_name = variable.split("_", 1)[1].lower()
        annotation = CreConfig.model_fields[field_name].annotation
        allowed = typing.get_args(annotation)
        assert expected in allowed, (
            f"{secret.name} is gated on {variable}=={expected!r}, "
            f"which is not one of {allowed}"
        )


def test_an_alias_satisfies_the_requirement_it_is_an_alias_for():
    clerk = _by_name("CRE_CLERK_SECRET_KEY")
    variable, expected = clerk.activated_by
    environ = _satisfied(**{variable: expected})
    environ["LOOPNET_CLERK_SECRET_KEY"] = SENTINEL

    assert clerk.name not in missing_production_secrets(environ)


@pytest.mark.parametrize("blank", ["", " ", "\t", "\n", "   \r\n  "])
def test_a_blank_injection_counts_as_absent(blank):
    """A managed store resolving a missing key to '' must not look satisfied."""
    environ = _satisfied(MEDAWARCRE_DATABASE_URL=blank)

    assert missing_production_secrets(environ) == ("MEDAWARCRE_DATABASE_URL",)


def test_missing_names_are_sorted_canonical_and_never_a_value():
    environ = _satisfied(MEDAWARCRE_OAUTH_DATABASE_URL="")
    environ["LOOPNET_CLERK_SECRET_KEY"] = SENTINEL

    missing = missing_production_secrets(environ)

    # Two assertions were removed from here rather than kept: `list(missing) ==
    # sorted(missing)` and a SENTINEL check, both against a one-element tuple
    # whose exact value the line above already pins. Neither could fail. The
    # ordering property is genuinely carried by the multi-element cases below.
    assert missing == ("MEDAWARCRE_OAUTH_DATABASE_URL",)


def test_verification_passes_when_every_required_secret_is_injected():
    assert verify_production_secrets(_satisfied()) is None


def test_verification_reports_names_only_and_carries_them_on_the_exception():
    with pytest.raises(ProductionSecretsUnavailable) as raised:
        verify_production_secrets(_env(MEDAWARCRE_DATABASE_URL=SENTINEL))

    assert raised.value.missing == (
        "MEDAWARCRE_ADMISSION_DATABASE_URL",
        "MEDAWARCRE_OAUTH_DATABASE_URL",
    )
    assert SENTINEL not in str(raised.value)
    assert all(SENTINEL not in str(arg) for arg in raised.value.args)


def test_presence_is_resolved_at_call_time_rather_than_at_import():
    """Rotation must need no rebuild, which means no import-time capture."""
    environ: dict[str, str] = {}

    before = missing_production_secrets(environ)
    environ.update({name: SENTINEL for name in REQUIRED_NAMES})
    after = missing_production_secrets(environ)

    assert before == tuple(sorted(REQUIRED_NAMES))
    assert after == ()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"requirement": "invented"}, "unknown requirement"),
        ({"name": "postgresql://user:pw@host/db"}, "not an environment variable"),
        ({"aliases": ("sk_live_realcredential",)}, "not an environment variable"),
        ({"requirement": "conditional"}, "condition and requirement disagree"),
        (
            {"activated_by": ("CRE_HUMAN_IDENTITY_PROVIDER", "clerk")},
            "condition and requirement disagree",
        ),
        ({"requirement": "self_gating"}, "self-gating and behaviour disagree"),
        ({"fail_closed_as": "closed"}, "self-gating and behaviour disagree"),
    ],
)
def test_a_malformed_inventory_entry_is_rejected_at_construction(kwargs, expected):
    """The name fields cannot be used to smuggle a value into a printed list."""
    fields = {
        "name": "MEDAWARCRE_EXAMPLE_URL",
        "consumer": "example",
        "purpose": "example",
        "requirement": "required",
        "rotation": "example",
        "least_privilege": "example",
    }
    fields.update(kwargs)

    with pytest.raises(ValueError, match=expected):
        ProductionSecret(**fields)


def test_no_inventory_entry_carries_anything_value_shaped():
    for secret in PRODUCTION_SECRETS:
        for name in secret.accepted_names:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        assert secret.consumer.strip()
        assert secret.purpose.strip()
        assert secret.rotation.strip()
        assert secret.least_privilege.strip()


def test_the_presence_check_and_the_consumer_agree_on_what_counts_as_injected(
    monkeypatch,
):
    """`_present` strips before deciding a value was injected; so must the reader.

    When they disagree, a DSN carrying one stray leading space counts as
    present and then reaches psycopg unstripped, which cannot read it as a URL
    and falls back to keyword/value parsing — the shape that echoed a whole
    connection string, password included, into a traceback.
    """
    from cre_mcp.postgres.config import PostgresSettings

    monkeypatch.setenv(
        "MEDAWARCRE_DATABASE_URL", " postgresql://u:p@127.0.0.1:1/db\t"
    )

    assert PostgresSettings.from_env().dsn == "postgresql://u:p@127.0.0.1:1/db"


def test_the_migration_runner_strips_its_dsn_for_the_same_reason():
    """`MigrationRunner` had the identical presence-check disagreement.

    It validates with `if not dsn.strip()` and then stored the raw value, so a
    migration DSN with one stray leading space passed validation and reached
    psycopg unstripped. Pinned separately because the repair is invisible to
    every other test here.
    """
    from cre_mcp.postgres.migrations import MigrationRunner, load_migrations

    runner = MigrationRunner(
        " postgresql://u:p@127.0.0.1:1/db\t", load_migrations()
    )

    assert runner._dsn == "postgresql://u:p@127.0.0.1:1/db"


def test_a_raised_refusal_discloses_nothing_from_the_real_environment(monkeypatch):
    """The other pins pass synthetic mappings, so they cannot see this.

    A mutant that reads `os.environ` directly when building the message would
    be invisible to every test that hands `verify_production_secrets` its own
    dictionary.
    """
    monkeypatch.setenv("MEDAWARCRE_DATABASE_URL", SENTINEL)
    monkeypatch.delenv("MEDAWARCRE_OAUTH_DATABASE_URL", raising=False)
    monkeypatch.delenv("MEDAWARCRE_ADMISSION_DATABASE_URL", raising=False)

    with pytest.raises(ProductionSecretsUnavailable) as raised:
        verify_production_secrets()

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert SENTINEL not in rendered
    assert SENTINEL not in str(vars(raised.value))


CONNECTION_OPENERS = (
    ("cre_mcp.postgres.oauth_authority", "PostgresOAuthAuthorityRepository"),
    ("cre_mcp.postgres.admission", "PostgresAdmissionRepository"),
)

# psycopg cannot read this as a URL, so it falls back to keyword/value parsing
# and quotes the whole token — the entire DSN — back in its error message.
UNREADABLE_DSN = "postgressql://appuser:openercanary@10.0.0.5:5432/medawarcre"


@pytest.mark.parametrize("module_name, class_name", CONNECTION_OPENERS)
def test_no_connection_opener_chains_a_dsn_echoing_cause(module_name, class_name):
    """The fix belongs to the class of site, not to the one that was reported.

    A review found this defect in `postgres/runtime.py`. It was repaired there
    and nowhere else, while three siblings opened a connection from their own
    `*_DATABASE_URL` and chained the cause. Neither repository below is
    constructed by the hosted process yet, so this was not a live disclosure —
    but they hold the two credentials the start-up preflight now requires an
    operator to inject, and `cre_mcp.server` installs a root logging sink that
    would render the chain the moment the domain wiring lands.
    """
    from cre_mcp.postgres.config import PostgresSettings

    repository_class = getattr(importlib.import_module(module_name), class_name)
    repository = repository_class(PostgresSettings(dsn=UNREADABLE_DSN))

    with pytest.raises(Exception) as raised:
        repository.open(wait=False)

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "openercanary" not in rendered
    assert UNREADABLE_DSN not in rendered
    assert raised.value.__cause__ is None


def test_the_backup_connection_splitter_does_not_echo_the_dsn_it_failed_to_read():
    """This one is reachable today, through `medawarcre-postgres backup`.

    Its entire purpose is to lift the password out of a DSN so it never reaches
    a child process environment, which makes chaining psycopg's quote-it-back
    parse error the sharpest version of the defect.
    """
    from cre_mcp.postgres.backup import BackupError, _command_connection

    with pytest.raises(BackupError) as raised:
        _command_connection(UNREADABLE_DSN)

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "openercanary" not in rendered
    assert UNREADABLE_DSN not in rendered
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "variable, value",
    [
        ("CRE_STRIPE_API_KEY", "sk_live_configvalidatorcanary"),
        ("CRE_OAUTH_ISSUER", "not-a-url-configvalidatorcanary"),
        ("CRE_CONNECTION_URL", "http://evil.example/configvalidatorcanary"),
    ],
)
def test_a_rejected_configuration_value_is_never_echoed_back(
    monkeypatch, variable, value
):
    """The guard that rejects a bad credential must not print it.

    Pydantic renders `input_value=...` into every `ValidationError`, so the
    live-key guard disclosed the live key: setting `CRE_STRIPE_API_KEY` to an
    `sk_live_` value produced an uncaught traceback on stderr containing it, at
    import of `cre_mcp.server`. The refusal must name the field, never the
    value — for every validated field, not only the credential ones.
    """
    monkeypatch.setenv(variable, value)

    with pytest.raises(Exception) as raised:
        CreConfig(_env_file=None)

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "configvalidatorcanary" not in rendered
    assert "configvalidatorcanary" not in str(raised.value)
    assert variable in str(raised.value), "the refusal must still name the field"


def test_the_backup_command_connection_moves_the_password_out_of_argv(monkeypatch):
    """`pg_dump` takes its connection string on the command line.

    A password left in that string is readable by any local user through `ps`.
    This is the function whose whole purpose is to prevent that, and it was
    unpinned: changing `pop("password")` to `get("password")` left the entire
    repository green while putting the credential back on the command line.

    It moves the password into the child's *environment*, which is readable
    only by the process owner rather than by every local user. An earlier
    version of this docstring said it kept the password out of the child
    environment, which is the opposite of what the code does.
    """
    from cre_mcp.postgres.backup import _command_connection

    # Set in the parent, because the assertion below is otherwise vacuous: the
    # function copies `os.environ`, and a test process that never had PGOPTIONS
    # passes whether or not the scrub runs. A reviewer deleted the scrub and
    # the whole repository stayed green.
    monkeypatch.setenv("PGOPTIONS", "-c log_statement=all")
    monkeypatch.setenv("PGPASSWORD", "inheritedcanary")
    monkeypatch.setenv("PGSSLPASSWORD", "inheritedsslcanary")

    dsn = (
        "postgresql://appuser:argvcanary@10.0.0.5:5432/medawarcre"
        "?sslpassword=sslcanary"
    )
    safe_connection, environment = _command_connection(dsn)

    assert "argvcanary" not in safe_connection
    assert "sslcanary" not in safe_connection
    assert "appuser" in safe_connection, "the pin must not pass on an empty string"
    assert environment["PGPASSWORD"] == "argvcanary"
    assert environment["PGSSLPASSWORD"] == "sslcanary"
    assert "PGOPTIONS" not in environment

    # A DSN carrying no credential, which is the shape a socket/trust/.pgpass
    # or IAM deployment uses — and this repository's own PostgreSQL fixtures.
    # Without this case the two `pop` calls above are unfalsifiable: the DSN
    # above supplies both values, so `_command_connection` re-sets them whether
    # or not the scrub ran, and a reviewer deleted both scrubs with the whole
    # repository green. The remedy for the PGOPTIONS vacuity was applied to
    # three variables and worked for one.
    _, inherited = _command_connection(
        "host=/tmp/sock port=5432 dbname=medawarcre user=medawarcre_backup"
    )

    assert "PGPASSWORD" not in inherited, (
        "an ambient PGPASSWORD reached the pg_dump child"
    )
    assert "PGSSLPASSWORD" not in inherited
    assert "PGOPTIONS" not in inherited


@pytest.mark.parametrize(
    "factory, attribute",
    [
        ("cre_mcp.postgres.config:PostgresSettings", "dsn"),
        (
            "cre_mcp.postgres.oauth_authority:PostgresOAuthAuthorityRepository",
            "settings",
        ),
        ("cre_mcp.postgres.admission:PostgresAdmissionRepository", "settings"),
    ],
)
def test_no_dsn_holding_object_prints_its_connection_string(factory, attribute):
    """`repr` is what a debugger, a log line, and a crash dump reach for.

    Every one of these classes carries a redacting `__repr__` and a docstring
    promising it, and none of them was pinned — the chain-suppression class was
    closed at four sites and the redaction class at none.
    """
    from cre_mcp.postgres.config import PostgresSettings

    module_name, class_name = factory.split(":")
    target = getattr(importlib.import_module(module_name), class_name)
    settings = PostgresSettings(dsn="postgresql://u:reprcanary@127.0.0.1:1/db")
    instance = settings if target is PostgresSettings else target(settings)

    assert "reprcanary" not in repr(instance)
    assert "reprcanary" not in str(instance)
    assert "reprcanary" not in f"{instance}"
    assert "reprcanary" not in "{}".format(instance)


def test_the_least_privilege_claim_this_module_makes_matches_the_role_contract():
    """The one prose field a reviewer can check mechanically, checked.

    `least_privilege` is otherwise unpinned prose, and the request-path entry's
    description of `medawarcre_app` was wrong until review caught it. This
    holds that specific claim to `bootstrap_roles.sql`.
    """
    roles_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "postgres"
        / "bootstrap_roles.sql"
    )
    roles = roles_path.read_text()
    # Every `ALTER ROLE`, not the first: PostgreSQL applies the last one, so
    # reading only `re.search` let a later `ALTER ROLE medawarcre_app WITH
    # SUPERUSER CREATEDB CREATEROLE BYPASSRLS;` sit behind a compliant earlier
    # statement.
    # `WITH` is optional in PostgreSQL's grammar, and requiring it let
    # `ALTER ROLE medawarcre_app SUPERUSER CREATEDB CREATEROLE LOGIN;` pass.
    # `\s+` after ROLE, and the identifier optionally quoted: a literal single
    # space let `ALTER ROLE  medawarcre_app WITH SUPERUSER …` (two spaces) slip
    # past while `assert declarations` still held on the compliant statement.
    declarations = re.findall(
        r'ALTER\s+ROLE\s+"?medawarcre_app"?\s+(?:WITH\s+)?([^;]*);',
        roles,
        flags=re.IGNORECASE,
    )
    assert declarations, "the role contract no longer declares this role"
    # Each declaration on its own, not their concatenation: PostgreSQL applies
    # the last one, and checking the joined text let a later
    # `ALTER ROLE … WITH SUPERUSER CREATEDB CREATEROLE BYPASSRLS;` hide behind
    # the compliant earlier statement's tokens.
    for declaration in declarations:
        single = " ".join(declaration.split()).upper()
        for required in ("NOLOGIN", "INHERIT", "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE"):
            assert required in single, (
                f"an ALTER ROLE for medawarcre_app omits {required}: {single}"
            )
        for forbidden in (r"\bSUPERUSER\b", r"\bCREATEDB\b", r"\bCREATEROLE\b",
                          r"\bBYPASSRLS\b", r"\bNOINHERIT\b", r"\bLOGIN\b"):
            assert not re.search(forbidden, single), (
                f"an ALTER ROLE for medawarcre_app confers {forbidden}: {single}"
            )
    attributes = " ".join(" ".join(declarations).split()).upper()
    claim = _by_name("MEDAWARCRE_DATABASE_URL").least_privilege

    for attribute in ("NOLOGIN", "INHERIT"):
        assert attribute in attributes, f"{attribute} is no longer declared"
        assert attribute in claim, f"the inventory no longer claims {attribute}"
    assert "NOINHERIT" not in attributes
    assert "NOINHERIT" not in claim

    # The attribute tokens alone left the rest of the sentence free text: a
    # review rewrote "holds no DDL" to "holds full DDL and is a superuser" and
    # the whole suite stayed green. The role is NOSUPERUSER in the contract and
    # holds no DDL grant, so a claim asserting either is false.
    assert "NOSUPERUSER" in attributes
    lowered = claim.casefold()
    assert "no ddl" in lowered, "the claim no longer states the role holds no DDL"
    for forbidden in ("superuser", "full ddl", "all privileges"):
        assert forbidden not in lowered.replace("nosuperuser", ""), (
            f"the claim asserts {forbidden!r}, which the role contract denies"
        )

    # The clause this commit added — "the runtime pool rejects a session that
    # resolves to any other role" — was itself falsifiable with the suite
    # green. It rests on one call, so the call is what pins it.
    assert "rejects" in lowered, "the claim no longer asserts the pool rejects"
    pool_source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "cre_mcp"
        / "postgres"
        / "pool.py"
    ).read_text()
    assert "assert_exact_group_session(" in pool_source, (
        "the runtime pool no longer asserts an exact group session, so the "
        "inventory's rejection claim is no longer backed by anything"
    )

    # And no GRANT in any shipped migration hands that role DDL. Every file,
    # not just 0001: a review added `GRANT CREATE ON SCHEMA medawarcre TO
    # medawarcre_app` to 0008 and this check stayed green.
    sql_root = (
        Path(__file__).resolve().parents[2] / "src" / "cre_mcp" / "postgres" / "sql"
    )
    # `bootstrap_roles.sql` is included: it lives outside `sql/`, is applied as
    # superuser, and a `GRANT medawarcre_migration TO medawarcre_app;` there was
    # invisible to a glob that stopped at the migrations.
    # Comments stripped before anything else: these files are written with
    # `--` comments above their statements, and splitting on `;` left the
    # comment attached to the front of the following fragment, so a grant
    # preceded by any comment line — or appended after the trailing comment
    # block in `bootstrap_roles.sql` — did not match the leading-keyword test.
    schema = re.sub(
        r"--[^\n]*",
        "",
        "\n".join(
            sorted(path.read_text() for path in sql_root.glob("*.sql")) + [roles]
        ),
    )
    assert "medawarcre_app" in schema, "the scan found no grants, so it is not a check"
    # Case-insensitive, because the extraction was upper-cased only *after*
    # matching, so a lower-case `grant create on schema … to medawarcre_app;`
    # was invisible in all nine files. Anchored to the start of a line because
    # the first case-insensitive attempt matched the substring "grants" inside
    # the PL/pgSQL relation-name array in 0001 and ran on to a CREATE POLICY.
    # Split on statement terminators rather than anchoring to line starts: the
    # anchor could not see `SELECT 1; GRANT medawarcre_migration TO
    # medawarcre_app;`, where the grant is not the first token on its line.
    statements = [
        f"{fragment.strip()};"
        for fragment in schema.split(";")
        if re.match(
            r"^\s*(?:GRANT|ALTER\s+DEFAULT\s+PRIVILEGES)\b",
            fragment,
            flags=re.IGNORECASE,
        )
        and re.search(r"\bmedawarcre_app\b", fragment, flags=re.IGNORECASE)
    ]
    assert statements, "the scan matched no grants, so it is not a check"
    for statement in statements:
        upper = statement.upper()
        # Word-bounded on purpose: a bare substring test matches the column
        # name CREATED_AT, which is how this check first failed.
        for privilege in (r"\bCREATE\b", r"\bALL\s+PRIVILEGES\b", r"\bALL\s+ON\b"):
            assert not re.search(privilege, upper), (
                f"medawarcre_app is granted {privilege}: {statement[:80]}"
            )
        # `GRANT <role> TO medawarcre_app;` confers that role's privileges by
        # inheritance without naming a single privilege keyword, so none of the
        # patterns above can see it.
        # The comma-separated form too: `GRANT a, b TO medawarcre_app;` names
        # no privilege keyword and was not matched when this required exactly
        # one identifier before TO.
        membership = re.match(
            r"^\s*GRANT\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*"
            r"[A-Za-z_][A-Za-z0-9_]*)*)\s+TO\s+(.*)$",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if membership is not None:
            granted = {
                role.strip().casefold() for role in membership.group(1).split(",")
            }
            # Only when medawarcre_app is the *grantee*. `GRANT medawarcre_app
            # TO <login_role>;` is the intended pattern DEPLOY.md describes, and
            # flagging it would be a false positive.
            grantee_side = membership.group(2)
            if (
                "medawarcre_app" not in granted
                and re.search(
                    r"\bmedawarcre_app\b", grantee_side, flags=re.IGNORECASE
                )
            ):
                raise AssertionError(
                    "medawarcre_app is granted membership of "
                    f"{sorted(granted)}, which confers those roles' "
                    f"privileges: {statement[:80]}"
                )

    # The role's own attributes live outside `sql/`, so the glob above cannot
    # see a CREATEDB or CREATEROLE added to the bootstrap contract.
    for forbidden_attribute in ("NOCREATEDB", "NOCREATEROLE"):
        assert forbidden_attribute in attributes, (
            f"medawarcre_app is no longer {forbidden_attribute} in the role "
            "contract, so it can create databases or roles"
        )


def _resolve(path: str) -> object:
    """Resolve a dotted `module.Class.method` path, module part first."""
    parts = path.split(".")
    module = None
    consumed = 0
    for index in range(len(parts), 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:index]))
        except ImportError:
            continue
        consumed = index
        break
    if module is None:
        raise AssertionError(f"no importable module in {path!r}")
    resolved: object = module
    for attribute in parts[consumed:]:
        resolved = getattr(resolved, attribute)
    return resolved


def test_every_consumer_names_a_live_code_path():
    """A `consumer` is a claim about where a credential is read.

    Without this, the field is prose the suite only checks for non-emptiness,
    so it can name a module that does not exist while every other pin stays
    green — and a reader auditing least privilege would be auditing fiction.
    """
    for secret in PRODUCTION_SECRETS:
        # Entries annotate the consumer, e.g. "cre_mcp.postgres.cli (migrate)".
        path = secret.consumer.split(" ", 1)[0].rstrip(",")
        try:
            _resolve(path)
        except (AssertionError, AttributeError) as error:
            raise AssertionError(
                f"{secret.name} names consumer {path!r}, which does not "
                f"resolve: {error}"
            ) from error


def test_the_inventory_has_not_silently_shrunk():
    """Deleting an entry must fail here rather than pass everywhere.

    Every other pin in this file reads *from* `PRODUCTION_SECRETS`, so removing
    an entry removes its own coverage along with its runbook obligation. A
    review demonstrated 14 of the 21 could be deleted outright — including both
    webhook signing secrets — with the whole repository green, because the
    source scan below can only see names matching `MEDAWARCRE_*_URL`.

    This list is deliberately literal. It is not derived from the module it
    checks, because a derived expectation cannot notice a deletion.
    """
    assert {secret.name for secret in PRODUCTION_SECRETS} == EXPECTED_INVENTORY


def test_no_credential_the_code_reads_is_missing_from_the_inventory():
    """The other direction: a credential the code reads but nobody described.

    Narrow by construction — it can only see `MEDAWARCRE_*_URL`, because the
    `CRE_*` credentials are `CreConfig` fields read through pydantic aliases
    rather than named literally at their point of use. Those are covered by the
    exact-set pin above, not by this one.
    """
    source_root = Path(__file__).resolve().parents[2] / "src"
    read_by_code = {
        name
        for path in source_root.rglob("*.py")
        for name in re.findall(r"\bMEDAWARCRE_[A-Z0-9_]*_URL\b", path.read_text())
    }
    inventoried = {secret.name for secret in PRODUCTION_SECRETS}

    assert read_by_code, "the scan found nothing, so it is not a check"
    assert not read_by_code - inventoried, (
        "these connection strings are read by src/ but the inventory does not "
        f"describe them: {sorted(read_by_code - inventoried)}"
    )


def test_the_runbook_names_every_secret_a_deployer_must_provide():
    """`deploy/DEPLOY.md` is the operational contract, so it must be complete.

    A deployer following a runbook that omits a start-up-blocking variable gets
    a refused process and no way to know which name it wanted.
    """
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]*)`", DEPLOY_DOC.read_text()))

    undocumented = sorted(
        secret.name
        for secret in PRODUCTION_SECRETS
        if secret.requirement != "optional" and secret.name not in documented
    )

    assert not undocumented, (
        "these are demanded at start-up or by an operator command but appear "
        f"in no runbook table: {undocumented}"
    )
