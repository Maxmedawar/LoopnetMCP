"""CRE deal-intelligence MCP server."""

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any, Literal

from fastmcp import FastMCP

from cre_mcp.config import CreConfig
from cre_mcp.tools import register_all
from cre_mcp.tools.deal_tools import analyze_deal, find_deals, find_distressed
from cre_mcp.tools.execution_tools import (
    draft_outreach,
    find_contact,
    financing_options,
    generate_loi,
    handle_counter,
    qualify_me,
    recommend_offer,
    size_debt,
)
from cre_mcp.tools.listing_tools import (
    get_market_overview,
    get_property_details,
    search_properties,
)
from cre_mcp.tools.market_tools import (
    compare_markets,
    get_comps,
    get_rent_comparables,
    market_intel,
)
from cre_mcp.tools.owner_tools import owner_lookup

# Route ALL logging to stderr — stdout is reserved for MCP protocol messages.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

_SERVER_INSTRUCTIONS = (
    "CRE deal-intelligence server for commercial real estate listings and markets. "
    "Use search_properties to find listings by location and filters. "
    "Use get_property_details to get full details on a specific listing. "
    "Use get_market_overview for listing-derived market statistics. "
    "Use market_intel for government fundamentals and compare_markets to rank locations."
    " Use analyze_deal for deep underwriting, find_deals for scored deal discovery,"
    " and find_distressed for REO, auction, foreclosure, and tax-sale opportunities."
    " Use owner_lookup for public assessor parcel and owner enrichment."
    " Use get_rent_comparables for public ZORI, ACS, and HUD rent benchmarks."
    " Use get_comps for county-limited sale comps and labeled value estimates."
    " Use recommend_offer for an explained negotiation range and generate_loi"
    " for a non-binding attorney-review draft."
    " Use find_contact for source-labeled broker, owner, and public registry contacts,"
    " draft_outreach for deterministic first-touch coaching, and handle_counter"
    " for guarded counteroffer parsing and response coaching."
    " Use financing_options to screen lender types, qualify_me to test buyer cash and"
    " sponsor gates, and size_debt for FRED-anchored LTV/DSCR proceeds."
)


class _StdioOnlyFastMCP(FastMCP):
    """Internal catalog that can never become a hosted network surface."""

    @staticmethod
    def _require_stdio(transport: object) -> None:
        if transport not in (None, "stdio"):
            raise RuntimeError(
                "the internal MCP catalog is stdio-only; use the certified hosted builder"
            )

    def http_app(self, *args: Any, **kwargs: Any):
        raise RuntimeError(
            "the internal MCP catalog is stdio-only; use the certified hosted builder"
        )

    def run(
        self,
        transport: object = None,
        show_banner: bool = True,
        **transport_kwargs: Any,
    ) -> None:
        self._require_stdio(transport)
        return super().run(
            transport=transport,
            show_banner=show_banner,
            **transport_kwargs,
        )

    async def run_async(
        self,
        transport: object = None,
        show_banner: bool = True,
        **transport_kwargs: Any,
    ) -> None:
        self._require_stdio(transport)
        return await super().run_async(
            transport=transport,
            show_banner=show_banner,
            **transport_kwargs,
        )

    async def run_http_async(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "the internal MCP catalog is stdio-only; use the certified hosted builder"
        )


def _build_server() -> FastMCP:
    server = _StdioOnlyFastMCP(name="loopnet", instructions=_SERVER_INSTRUCTIONS)
    register_all(server)
    return server


mcp = _build_server()


def resolve_transport(
    config: CreConfig | None = None,
    *,
    force_http: bool = False,
) -> Literal["stdio", "http"]:
    """Resolve the runtime transport without starting or binding the server."""
    if force_http:
        return "http"
    return (config or CreConfig()).transport


_platform_api = None


def _platform(config: CreConfig | None = None):
    """Lazily build (and optionally reconfigure) the shared platform API.

    Construction is deferred off the import path so importing the server does
    not touch the database; the resolved runtime config is applied here by
    ``install_access_control`` before any request is served.
    """
    global _platform_api
    from cre_mcp.platform.api import PlatformApi

    if _platform_api is None:
        _platform_api = PlatformApi(config)
    elif config is not None:
        _platform_api.configure(config)
    return _platform_api


def _register_platform_routes(server: FastMCP, platform_api=None) -> None:
    """Register the customer-facing platform routes on the server once.

    Bound to the module server so they ride the app that ``mcp.run`` builds
    internally, not only the one from ``create_http_app``. Each handler defers
    to the lazily-built shared ``PlatformApi``.
    """
    from cre_mcp.platform.api import PLATFORM_ROUTE_SPECS

    for path, methods, handler_name in PLATFORM_ROUTE_SPECS:

        async def _handler(request, _name=handler_name):
            api = platform_api if platform_api is not None else _platform()
            return await getattr(api, _name)(request)

        server.custom_route(path, methods=list(methods))(_handler)


_register_platform_routes(mcp)


def install_access_control(
    config: CreConfig | None = None,
    *,
    runtime_mode: Literal["stdio", "http"] | None = None,
    server: FastMCP | None = None,
    platform_api=None,
    access_registry=None,
    audit_log=None,
    surface_catalog=None,
):
    """Install tenant-aware access control on the module server instance.

    Hosted mode authenticates only through authoritative OAuth. Stdio mode
    resolves to the explicit trusted local workspace.
    Re-invoking replaces any prior access middleware so the last config wins
    (and two apps never stack duplicate enforcement); returns the uninstaller.
    """
    from cre_mcp.access.audit import AuditLog
    from cre_mcp.access.middleware import AccessMiddleware, install_access
    from cre_mcp.access.registry import WorkspaceRegistry
    from cre_mcp.platform.authority import AuthoritativeOAuthVerifier

    # Drop any existing access middleware rather than no-op, so a later call
    # with a different registry/audit config is honored instead of ignored.
    target = server or mcp
    for existing in [m for m in target.middleware if isinstance(m, AccessMiddleware)]:
        target.middleware.remove(existing)
    config = config or CreConfig()
    # Point the platform routes at the same resolved config (shared cache DB).
    if runtime_mode == "http" and (
        platform_api is None or access_registry is None or audit_log is None
    ):
        raise RuntimeError(
            "hosted HTTP requires an explicit persistence bundle"
        )
    platform = platform_api if platform_api is not None else _platform(config)
    if runtime_mode == "http":
        target.auth = AuthoritativeOAuthVerifier(platform.authority)
    else:
        target.auth = None
    access_dir = config.cache_db_path.parent / "access"
    registry = (
        access_registry
        if access_registry is not None
        else WorkspaceRegistry(
            config.access_registry_path or access_dir / "registry.json"
        )
    )
    resolved_audit_log = (
        audit_log
        if audit_log is not None
        else AuditLog(config.access_audit_path or access_dir / "audit.jsonl")
    )
    tool_call_resolver = None
    tool_visibility_resolver = None
    if surface_catalog is not None:
        from cre_mcp.surface.server import resolve_surface_call

        tool_call_resolver = lambda tool_name, arguments: resolve_surface_call(
            tool_name,
            arguments,
            catalog=surface_catalog,
        )
        tool_visibility_resolver = surface_catalog.is_visible
    return install_access(
        target,
        registry=registry,
        audit_log=resolved_audit_log,
        runtime_mode=runtime_mode,
        config=config,
        tool_call_resolver=tool_call_resolver,
        tool_visibility_resolver=tool_visibility_resolver,
    )


def _build_hosted_customer_server() -> FastMCP:
    """Build the grouped hosted surface over the complete internal server."""
    from cre_mcp.surface import build_customer_server

    return build_customer_server(mcp)


def create_http_app(
    path: str = "/mcp",
    config: CreConfig | None = None,
    *,
    human_identity_verifier=None,
):
    """Construct the opt-in Streamable HTTP ASGI application without binding.

    The FastMCP transport lives at ``path``. The authenticated customer-facing
    platform routes (``/v1/...``) are registered on the server itself (see
    ``_register_platform_routes``), so they are served on the same app — and
    with the same lifespan — whether the app is built here or by ``mcp.run``.
    Platform routes carry their own OAuth bearer-token auth and are independent
    of the MCP access middleware.
    """
    config = config or CreConfig()
    from cre_mcp.postgres.runtime import (
        bind_persistence_lifespan,
        build_postgres_hosted_persistence,
    )

    bundle = build_postgres_hosted_persistence()
    try:
        if getattr(bundle, "backend", None) != "postgres":
            raise RuntimeError("hosted HTTP requires PostgreSQL persistence")
        platform = bundle.platform_api
        if human_identity_verifier is not None:
            raise ValueError(
                "human identity verification must be owned by the persistence bundle"
            )
        from cre_mcp.surface import CUSTOMER_SURFACE

        hosted_server = _build_hosted_customer_server()
        _register_platform_routes(hosted_server, platform)
        install_access_control(
            config,
            runtime_mode="http",
            server=hosted_server,
            platform_api=platform,
            access_registry=bundle.access_registry,
            audit_log=bundle.audit_log,
            surface_catalog=CUSTOMER_SURFACE,
        )
        # JSON responses avoid creating an SSE watcher and per-request stream for
        # ordinary request/response traffic. Streamable HTTP session semantics and
        # transport-level OAuth status codes remain unchanged.
        app = hosted_server.http_app(
            path=path,
            transport="http",
            json_response=True,
        )
        return bind_persistence_lifespan(app, bundle)
    except Exception:
        bundle.close()
        raise


def run_server(
    config: CreConfig | None = None,
    *,
    force_http: bool = False,
) -> None:
    """Run stdio by default or the configured opt-in Streamable HTTP server."""
    config = config or CreConfig()
    transport = resolve_transport(config, force_http=force_http)
    if transport == "http":
        from cre_mcp.postgres.runtime import build_postgres_hosted_persistence
        from cre_mcp.surface import CUSTOMER_SURFACE

        bundle = build_postgres_hosted_persistence()
        uninstall = None
        try:
            platform = bundle.platform_api
            hosted_server = _build_hosted_customer_server()
            _register_platform_routes(hosted_server, platform)
            uninstall = install_access_control(
                config,
                runtime_mode="http",
                server=hosted_server,
                platform_api=platform,
                access_registry=bundle.access_registry,
                audit_log=bundle.audit_log,
                surface_catalog=CUSTOMER_SURFACE,
            )
            hosted_server.run(
                transport="http",
                host=config.http_host,
                port=config.http_port,
                json_response=True,
            )
        finally:
            if uninstall is not None:
                uninstall()
            bundle.close()
        return

    from cre_mcp.access.middleware import AccessMiddleware

    prior_access = [
        item for item in mcp.middleware if isinstance(item, AccessMiddleware)
    ]
    prior_auth = mcp.auth
    uninstall = install_access_control(config, runtime_mode=transport)
    try:
        mcp.run(transport="stdio")
    finally:
        uninstall()
        mcp.middleware.extend(
            item for item in prior_access if item not in mcp.middleware
        )
        mcp.auth = prior_auth


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint; ``--http`` overrides the environment transport."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http",
        action="store_true",
        help="run the Streamable HTTP transport instead of the stdio default",
    )
    args = parser.parse_args(argv)
    run_server(force_http=args.http)


if __name__ == "__main__":
    main()


__all__ = [
    "analyze_deal",
    "compare_markets",
    "create_http_app",
    "find_deals",
    "find_contact",
    "financing_options",
    "find_distressed",
    "get_market_overview",
    "get_comps",
    "get_property_details",
    "get_rent_comparables",
    "generate_loi",
    "draft_outreach",
    "handle_counter",
    "market_intel",
    "main",
    "mcp",
    "owner_lookup",
    "qualify_me",
    "recommend_offer",
    "resolve_transport",
    "run_server",
    "search_properties",
    "size_debt",
]
