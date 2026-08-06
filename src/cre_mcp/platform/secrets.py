"""Provider-neutral production secret boundary.

The founder decision this implements: a local ``.env`` file is never the
production source of truth for a real credential. Production secrets live in
the deployment platform's managed secret store and reach the process at runtime
through environment injection or a secret mount, under a least-privilege
service identity.

This module is the seam that makes that decision checkable. It is deliberately
**provider-neutral**: it names no cloud vendor, imports no vendor SDK, and adds
no dependency. Every managed secret store presents a secret to a process as an
environment variable or a mounted file exported into one, so the process
environment is the one channel this repository can require today without
choosing infrastructure that has not been chosen.

Three properties matter more than the inventory itself:

- **Names only.** Nothing here reads, returns, stores, logs, or raises a secret
  *value*. A caller learns which variable is absent, never what any variable
  contains. ``ProductionSecret`` describes a credential; it never holds one.
- **Read at call time.** Presence is resolved from the mapping passed in (the
  live process environment by default) at the moment of the call. Nothing is
  captured at import, so rotating a value in the managed store and restarting
  is sufficient — no code change and no rebuild.
- **The file is not consulted.** ``CreConfig`` reads a local ``.env`` for
  development convenience, and ``pydantic-settings`` ranks real environment
  variables above it, so an injected production secret already outranks a stale
  developer file. This boundary looks only at the injected environment, which
  is the production channel.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

# An environment variable name, and nothing that could be mistaken for a value.
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

# How each credential is enforced. The distinction is the point: a class that
# promised more enforcement than the code performs would be the same false
# assurance this phase exists to remove.
REQUIREMENTS = frozenset(
    {
        # The hosted serving process refuses to start without it. Enforced by
        # ``verify_production_secrets`` before any connection or socket.
        "required",
        # Required only when ``activated_by`` holds in the same environment.
        # Enforced by ``verify_production_secrets`` under that condition.
        "conditional",
        # No environment signal exists to enforce on, so start-up says nothing
        # about it. Its absence disables the feature closed at the point of
        # use; ``fail_closed_as`` records exactly how.
        "self_gating",
        # Read by an operator command, never by the serving process. Injected
        # for the duration of that command and absent from the running service.
        "operator",
        # An enrichment source. Absent means that source is unavailable, which
        # is a narrower product rather than an unsafe one.
        "optional",
    }
)


class ProductionSecretsUnavailable(RuntimeError):
    """A required production secret was not injected.

    Carries the missing variable *names* and nothing else, so the exception —
    including anything that logs its traceback — cannot disclose a credential.
    """

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            "required production secrets are not present in the process "
            f"environment: {', '.join(missing)}"
        )


@dataclass(frozen=True)
class ProductionSecret:
    """One production credential, described by name and never by value."""

    name: str
    consumer: str
    purpose: str
    requirement: str
    rotation: str
    least_privilege: str
    aliases: tuple[str, ...] = ()
    activated_by: tuple[str, str] | None = None
    fail_closed_as: str | None = None

    def __post_init__(self) -> None:
        if self.requirement not in REQUIREMENTS:
            raise ValueError(f"unknown requirement: {self.requirement}")
        for name in self.accepted_names:
            # A credential would not match this shape, so a value cannot be
            # smuggled into the inventory and printed by a trusting caller.
            if not _ENV_NAME.match(name):
                raise ValueError(f"not an environment variable name: {name!r}")
        if (self.requirement == "conditional") != (self.activated_by is not None):
            raise ValueError(f"{self.name}: condition and requirement disagree")
        if (self.requirement == "self_gating") != (self.fail_closed_as is not None):
            raise ValueError(f"{self.name}: self-gating and behaviour disagree")

    @property
    def accepted_names(self) -> tuple[str, ...]:
        """Every variable name the consumer will actually read.

        A managed store should set only ``name``. The legacy aliases exist
        because ``CreConfig`` still accepts them, and calling a secret missing
        while its accepted alias is set would be a false alarm.
        """
        return (self.name, *self.aliases)


def _legacy(name: str) -> tuple[str, ...]:
    """The ``LOOPNET_`` alias ``CreConfig._env_aliases`` also accepts."""
    return (name.replace("CRE_", "LOOPNET_", 1),)


PRODUCTION_SECRETS: tuple[ProductionSecret, ...] = (
    ProductionSecret(
        name="MEDAWARCRE_DATABASE_URL",
        consumer="cre_mcp.postgres.config.PostgresSettings.from_env",
        purpose="hosted request-path PostgreSQL connection string",
        requirement="required",
        rotation="rotate the login role's password in the managed store, then "
        "restart; the DSN is read per process, never baked into an image",
        least_privilege="logs in as the single login role that is a member of "
        "medawarcre_app, which is NOLOGIN NOINHERIT and holds no DDL",
    ),
    ProductionSecret(
        name="MEDAWARCRE_OAUTH_DATABASE_URL",
        consumer="cre_mcp.postgres.oauth_authority."
        "PostgresOAuthAuthorityRepository.from_env",
        purpose="OAuth authority connection string, separate so the authority "
        "pool carries its own credential and its own limits",
        requirement="required",
        rotation="rotate the login role's password in the managed store, then "
        "restart",
        least_privilege="member of medawarcre_oauth only; no reach into deal, "
        "search, or provider tables",
    ),
    ProductionSecret(
        name="MEDAWARCRE_ADMISSION_DATABASE_URL",
        consumer="cre_mcp.postgres.admission.PostgresAdmissionRepository.from_env",
        purpose="admission and durable decision-audit connection string",
        requirement="required",
        rotation="rotate the login role's password in the managed store, then "
        "restart",
        least_privilege="member of medawarcre_admission only; append-only on "
        "the decision audit",
    ),
    ProductionSecret(
        name="CRE_CLERK_SECRET_KEY",
        aliases=_legacy("CRE_CLERK_SECRET_KEY"),
        consumer="cre_mcp.platform.connection.ClerkHumanIdentityVerifier",
        purpose="Clerk Backend API credential used to verify a browser session "
        "and read the signed-in user's record",
        requirement="conditional",
        activated_by=("CRE_HUMAN_IDENTITY_PROVIDER", "clerk"),
        rotation="issue a second Clerk secret key, update the managed store, "
        "restart, then revoke the first; Clerk allows the keys to overlap",
        least_privilege="a Clerk instance secret key is instance-wide, so it is "
        "held only by the serving process; the browser receives the "
        "publishable key at build time and never this one",
    ),
    ProductionSecret(
        name="CRE_STRIPE_API_KEY",
        aliases=_legacy("CRE_STRIPE_API_KEY"),
        consumer="cre_mcp.platform.providers.stripe.StripeReadClient.from_config",
        purpose="Stripe read access used to reconcile subscription state",
        requirement="self_gating",
        fail_closed_as="StripeProviderUnavailableError when absent",
        rotation="create a second restricted key, update the managed store, "
        "restart, then revoke the first",
        least_privilege="a restricted read-only key; MedawarCRE never writes to "
        "Stripe, so a write-capable key is over-privileged",
    ),
    ProductionSecret(
        name="CRE_STRIPE_WEBHOOK_SECRET",
        aliases=_legacy("CRE_STRIPE_WEBHOOK_SECRET"),
        consumer="cre_mcp.platform.api.PlatformApi._webhook",
        purpose="Stripe webhook signing secret",
        requirement="self_gating",
        fail_closed_as="404 provider_not_configured when no signing secret is set",
        rotation="set CRE_STRIPE_WEBHOOK_SECRETS to the old and the new secret "
        "together, cut over at Stripe, then drop the old one; no restart gap",
        least_privilege="verification only; it authorizes no API call",
    ),
    ProductionSecret(
        name="CRE_SKOOL_WEBHOOK_SECRET",
        aliases=_legacy("CRE_SKOOL_WEBHOOK_SECRET"),
        consumer="cre_mcp.platform.api.PlatformApi._webhook",
        purpose="Skool relay signing secret",
        requirement="self_gating",
        fail_closed_as="404 provider_not_configured when no signing secret is set",
        rotation="set CRE_SKOOL_WEBHOOK_SECRETS to the old and the new secret "
        "together, cut over at the relay, then drop the old one; no restart gap",
        least_privilege="verification only; it authorizes no API call",
    ),
    ProductionSecret(
        name="MEDAWARCRE_MIGRATION_DATABASE_URL",
        consumer="cre_mcp.postgres.cli (medawarcre-postgres migrate)",
        purpose="schema migration connection string",
        requirement="operator",
        rotation="rotate the login role's password in the managed store",
        least_privilege="the only credential carrying DDL; injected for the "
        "duration of a migration command and absent from the serving process",
    ),
    ProductionSecret(
        name="MEDAWARCRE_APP_DATABASE_URL",
        consumer="cre_mcp.postgres.cli (release smoke check)",
        purpose="app-role connection string used by the release verifier",
        requirement="operator",
        rotation="rotate with MEDAWARCRE_DATABASE_URL; the same underlying role",
        least_privilege="member of medawarcre_app only",
    ),
    ProductionSecret(
        name="MEDAWARCRE_BACKUP_DATABASE_URL",
        consumer="cre_mcp.postgres.cli (backup, restore, release check)",
        purpose="backup and restore connection string",
        requirement="operator",
        rotation="rotate the login role's password in the managed store",
        least_privilege="member of medawarcre_backup only; read and restore, no "
        "application writes",
    ),
    ProductionSecret(
        name="CRE_PROXY_URL",
        aliases=_legacy("CRE_PROXY_URL"),
        consumer="cre_mcp.http.fetch and cre_mcp.http.browser",
        purpose="outbound scraping proxy, whose URL embeds its own credentials",
        requirement="optional",
        rotation="replace the URL in the managed store, then restart",
        least_privilege="outbound HTTP only; it reaches no MedawarCRE data",
    ),
    ProductionSecret(
        name="CRE_CENSUS_API_KEY",
        aliases=_legacy("CRE_CENSUS_API_KEY"),
        consumer="cre_mcp.market.census",
        purpose="US Census API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a public-data read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_BLS_API_KEY",
        aliases=_legacy("CRE_BLS_API_KEY"),
        consumer="cre_mcp.market.bls",
        purpose="Bureau of Labor Statistics API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a public-data read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_FRED_API_KEY",
        aliases=_legacy("CRE_FRED_API_KEY"),
        consumer="cre_mcp.market.fred",
        purpose="FRED macro-series API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a public-data read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_HUD_API_TOKEN",
        aliases=_legacy("CRE_HUD_API_TOKEN"),
        consumer="cre_mcp.market.hud and cre_mcp.geo.crosswalk",
        purpose="HUD API token",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a public-data read token; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_BEA_API_KEY",
        aliases=_legacy("CRE_BEA_API_KEY"),
        consumer="cre_mcp.market.bea",
        purpose="Bureau of Economic Analysis API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a public-data read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_RENTCAST_API_KEY",
        aliases=_legacy("CRE_RENTCAST_API_KEY"),
        consumer="cre_mcp.market.rent_comps",
        purpose="RentCast rent-comparable API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a metered vendor read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_SKIPTRACE_API_KEY",
        aliases=_legacy("CRE_SKIPTRACE_API_KEY"),
        consumer="cre_mcp.execution.contacts",
        purpose="skip-trace vendor API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a metered vendor read key; its use is gated by the "
        "source-rights registry, not by possession of the key",
    ),
    ProductionSecret(
        name="CRE_ATTOM_API_KEY",
        aliases=_legacy("CRE_ATTOM_API_KEY"),
        consumer="cre_mcp.enrichment.providers.attom",
        purpose="ATTOM property-record API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a metered vendor read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_REGRID_API_KEY",
        aliases=_legacy("CRE_REGRID_API_KEY"),
        consumer="cre_mcp.enrichment.providers.regrid",
        purpose="Regrid parcel-record API key",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a metered vendor read key; it reaches no customer data",
    ),
    ProductionSecret(
        name="CRE_SOCRATA_APP_TOKEN",
        aliases=_legacy("CRE_SOCRATA_APP_TOKEN"),
        consumer="cre_mcp.zoning.permits",
        purpose="Socrata open-data application token",
        requirement="optional",
        rotation="replace in the managed store, then restart",
        least_privilege="a rate-limit token over public data; it grants no "
        "additional read scope",
    ),
)


def _present(environ: Mapping[str, str], secret: ProductionSecret) -> bool:
    """A blank or whitespace-only injection is an absent secret.

    A managed store that resolves a missing key to an empty string would
    otherwise look like a satisfied requirement and fail later, deeper, and
    less clearly.
    """
    return any(environ.get(name, "").strip() for name in secret.accepted_names)


def _activated(environ: Mapping[str, str], secret: ProductionSecret) -> bool:
    if secret.activated_by is None:
        return True
    variable, expected = secret.activated_by
    candidates = (variable, *_legacy(variable)) if "CRE_" in variable else (variable,)
    return any(
        environ.get(name, "").strip().casefold() == expected.casefold()
        for name in candidates
    )


def required_production_secrets(
    environ: Mapping[str, str] | None = None,
) -> tuple[ProductionSecret, ...]:
    """Every secret the hosted serving process must be given, in this environment.

    Operator secrets are excluded by construction — the serving process must
    not hold the migration credential. Self-gating and optional secrets are
    excluded because their absence is already a closed, narrower service rather
    than an unsafe one.
    """
    resolved = os.environ if environ is None else environ
    return tuple(
        secret
        for secret in PRODUCTION_SECRETS
        if secret.requirement == "required"
        or (secret.requirement == "conditional" and _activated(resolved, secret))
    )


def missing_production_secrets(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """The canonical names of required secrets absent from the environment.

    Returns names. It cannot return a value: nothing but ``secret.name`` is
    ever placed in the result.
    """
    resolved = os.environ if environ is None else environ
    return tuple(
        sorted(
            secret.name
            for secret in required_production_secrets(resolved)
            if not _present(resolved, secret)
        )
    )


def verify_production_secrets(environ: Mapping[str, str] | None = None) -> None:
    """Fail closed when the managed store has not injected a required secret.

    Called before the hosted process opens a database connection or binds a
    socket, so a misconfigured deployment stops at the boundary with an
    actionable list of variable names instead of a connection error whose real
    cause is a missing credential.
    """
    missing = missing_production_secrets(environ)
    if missing:
        raise ProductionSecretsUnavailable(missing)


__all__ = [
    "PRODUCTION_SECRETS",
    "REQUIREMENTS",
    "ProductionSecret",
    "ProductionSecretsUnavailable",
    "missing_production_secrets",
    "required_production_secrets",
    "verify_production_secrets",
]
