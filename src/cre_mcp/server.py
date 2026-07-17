"""CRE deal-intelligence MCP server."""

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Literal

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

mcp = FastMCP(
    name="loopnet",
    instructions=(
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
    ),
)
register_all(mcp)


def resolve_transport(
    config: CreConfig | None = None,
    *,
    force_http: bool = False,
) -> Literal["stdio", "http"]:
    """Resolve the runtime transport without starting or binding the server."""
    if force_http:
        return "http"
    return (config or CreConfig()).transport


def install_access_control(config: CreConfig | None = None):
    """Install tenant-aware access control on the module server instance.

    Hosted mode authenticates API keys against the server-side workspace
    registry; stdio mode resolves to the explicit trusted local workspace.
    Re-invoking replaces any prior access middleware so the last config wins
    (and two apps never stack duplicate enforcement); returns the uninstaller.
    """
    from cre_mcp.access.audit import AuditLog
    from cre_mcp.access.middleware import AccessMiddleware, install_access
    from cre_mcp.access.registry import WorkspaceRegistry

    # Drop any existing access middleware rather than no-op, so a later call
    # with a different registry/audit config is honored instead of ignored.
    for existing in [m for m in mcp.middleware if isinstance(m, AccessMiddleware)]:
        mcp.middleware.remove(existing)
    config = config or CreConfig()
    access_dir = config.cache_db_path.parent / "access"
    registry = WorkspaceRegistry(config.access_registry_path or access_dir / "registry.json")
    audit_log = AuditLog(config.access_audit_path or access_dir / "audit.jsonl")
    return install_access(mcp, registry=registry, audit_log=audit_log)


def create_http_app(path: str = "/mcp", config: CreConfig | None = None):
    """Construct the opt-in Streamable HTTP ASGI application without binding."""
    install_access_control(config)
    return mcp.http_app(path=path, transport="http")


def run_server(
    config: CreConfig | None = None,
    *,
    force_http: bool = False,
) -> None:
    """Run stdio by default or the configured opt-in Streamable HTTP server."""
    config = config or CreConfig()
    transport = resolve_transport(config, force_http=force_http)
    install_access_control(config)
    if transport == "http":
        mcp.run(
            transport="http",
            host=config.http_host,
            port=config.http_port,
        )
        return
    mcp.run(transport="stdio")


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
