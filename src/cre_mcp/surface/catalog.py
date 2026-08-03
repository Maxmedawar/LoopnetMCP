"""Locked reconciliation and grouped customer-tool catalog.

The internal FastMCP server owns 274 exact capabilities. The hosted customer
server exposes a much smaller set of coherent tools whose ``action`` values are
the exact internal capability IDs. Capabilities are never renamed, copied, or
deleted to make the customer list smaller.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from cre_mcp.access.capabilities import CAPABILITIES, export_matrix
from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile

if TYPE_CHECKING:
    from cre_mcp.access.engine import AccessEngine


CAPABILITY_INVENTORY_SHA256 = (
    "3ef968d84b76ad8092cf6dd4ca2629924214ac6b1ae54a6d080afd17ad837d1f"
)

# The older broad CRE-engine server exposed these 45 names directly. Every one
# remains an exact capability in the current 274-capability inventory and is
# assigned to a grouped hosted tool below. This tuple is archaeology evidence,
# not a second server implementation.
LEGACY_TOOL_IDS = (
    "search_properties",
    "get_property_details",
    "get_market_overview",
    "market_intel",
    "compare_markets",
    "get_rent_comparables",
    "get_comps",
    "analyze_deal",
    "find_deals",
    "find_distressed",
    "owner_lookup",
    "recommend_offer",
    "generate_loi",
    "find_contact",
    "draft_outreach",
    "handle_counter",
    "financing_options",
    "qualify_me",
    "size_debt",
    "due_diligence_plan",
    "closing_plan",
    "save_deal",
    "list_deals",
    "add_to_pipeline",
    "update_deal_stage",
    "list_pipeline",
    "save_search",
    "list_searches",
    "check_alerts",
    "recommend_structure",
    "start_exchange",
    "exchange_status",
    "identify_replacement",
    "calc_boot_basis",
    "add_investor",
    "list_investors",
    "record_commitment",
    "check_solicitation",
    "model_waterfall",
    "draft_ppm",
    "draft_form_d",
    "after_tax_returns",
    "operating_playbook",
    "backtest_score",
    "record_deal_outcome",
)


@dataclass(frozen=True, slots=True)
class SurfaceToolSpec:
    """One visible grouped tool and its exact internal actions."""

    name: str
    description: str
    profiles: tuple[Profile, ...]
    capability_ids: tuple[str, ...]


_ALL_PROFILES = tuple(Profile)
_NATIONAL_PROFILES = (Profile.NATIONAL_SCOUT, Profile.FULL_OPERATOR)
_JV_PROFILES = (Profile.JV_PARTNER, Profile.FULL_OPERATOR)
_FULL_PROFILE = (Profile.FULL_OPERATOR,)

_SURFACE_DEFINITIONS: tuple[
    tuple[str, str, tuple[Profile, ...]], ...
] = (
    (
        "cre_discover",
        "Find listings and distressed deals, inspect listing details, and run saved searches.",
        _ALL_PROFILES,
    ),
    (
        "cre_property",
        "Resolve owners, parcels, zoning, nearby context, seller motivation, and site facts.",
        _ALL_PROFILES,
    ),
    (
        "cre_market",
        "Retrieve market intelligence, rent and sale comps, and listing-market context.",
        _ALL_PROFILES,
    ),
    (
        "cre_evaluate",
        "Analyze, underwrite, value, stress-test, and calibrate a deal.",
        _ALL_PROFILES,
    ),
    (
        "cre_offer",
        "Recommend offers, draft LOIs, and coach counters and negotiation terms.",
        _ALL_PROFILES,
    ),
    (
        "cre_contact",
        "Find contacts, draft outreach, and manage relationship follow-through.",
        _ALL_PROFILES,
    ),
    (
        "cre_finance",
        "Size debt, assess qualification, compare capital paths, and manage lender evidence.",
        _ALL_PROFILES,
    ),
    (
        "cre_diligence",
        "Plan diligence and reconcile title, physical, environmental, lease, and document evidence.",
        _ALL_PROFILES,
    ),
    (
        "cre_pipeline",
        "Save deals, manage stages and alerts, record events, and review the working queue.",
        _ALL_PROFILES,
    ),
    (
        "cre_close",
        "Coordinate the data room, closing runway, funding package, and postmortem.",
        _ALL_PROFILES,
    ),
    (
        "cre_compare",
        "Compare markets and national portfolio signals.",
        _NATIONAL_PROFILES,
    ),
    (
        "cre_disposition",
        "Prepare a sale, match buyers, normalize bids, and compare exit paths.",
        _NATIONAL_PROFILES,
    ),
    (
        "cre_leasing",
        "Abstract leases, model rent and recoveries, and manage tenant leasing decisions.",
        _NATIONAL_PROFILES,
    ),
    (
        "cre_structure",
        "Evaluate entity and 1031 structures with irreversible-step guardrails.",
        _JV_PROFILES,
    ),
    (
        "cre_capital",
        "Manage investors, solicitation checks, waterfalls, and draft raise documents.",
        _JV_PROFILES,
    ),
    (
        "cre_partner",
        "Model JV structures, fund limits, capital calls, marks, and investor reporting.",
        _JV_PROFILES,
    ),
    (
        "cre_portfolio",
        "Review portfolio exposure, ownership performance, and decision analytics.",
        _JV_PROFILES,
    ),
    (
        "cre_operations",
        "Run property, asset, certificate, obligation, vendor, and maintenance workflows.",
        _FULL_PROFILE,
    ),
    (
        "cre_construction",
        "Control budgets, bids, pay applications, draws, schedules, and closeout.",
        _FULL_PROFILE,
    ),
    (
        "cre_books",
        "Manage tenancy accounting, charges, cash reconciliation, billing, and AR aging.",
        _FULL_PROFILE,
    ),
)

# A module is a classification aid only. The exposed action remains the exact
# key from CAPABILITIES, and the locked inventory digest prevents a new action
# from being silently exposed by a later module edit.
_MODULE_GROUPS = MappingProxyType(
    {
        "cre_mcp.analytics.tools": "cre_portfolio",
        "cre_mcp.assetmgmt.tools": "cre_operations",
        "cre_mcp.books.tools": "cre_books",
        "cre_mcp.closing.tools": "cre_close",
        "cre_mcp.command.tools": "cre_pipeline",
        "cre_mcp.compliance.tools": "cre_diligence",
        "cre_mcp.construction.tools": "cre_construction",
        "cre_mcp.dataroom.tools": "cre_close",
        "cre_mcp.debt.tools": "cre_finance",
        "cre_mcp.disposition.tools": "cre_disposition",
        "cre_mcp.envscreen.tools": "cre_diligence",
        "cre_mcp.finops.tools": "cre_finance",
        "cre_mcp.fund.tools": "cre_partner",
        "cre_mcp.leaseops.tools": "cre_operations",
        "cre_mcp.leases.tools": "cre_leasing",
        "cre_mcp.leasing.tools": "cre_leasing",
        "cre_mcp.negotiation.tools": "cre_offer",
        "cre_mcp.notes.tools": "cre_finance",
        "cre_mcp.obligations.tools": "cre_diligence",
        "cre_mcp.physical.tools": "cre_diligence",
        "cre_mcp.pmops.tools": "cre_operations",
        "cre_mcp.prospect.tools": "cre_property",
        "cre_mcp.relations.tools": "cre_contact",
        "cre_mcp.scenarios.tools": "cre_evaluate",
        "cre_mcp.siteintel.tools": "cre_market",
        "cre_mcp.taxecon.tools": "cre_evaluate",
        "cre_mcp.title.tools": "cre_diligence",
        "cre_mcp.tools.capital_tools": "cre_capital",
        "cre_mcp.tools.decision_tools": "cre_evaluate",
        "cre_mcp.tools.eval_tools": "cre_evaluate",
        "cre_mcp.tools.ledger_tools": "cre_diligence",
        "cre_mcp.tools.listing_tools": "cre_discover",
        "cre_mcp.tools.market_tools": "cre_market",
        "cre_mcp.tools.memory_tools": "cre_pipeline",
        "cre_mcp.tools.motivation_tools": "cre_property",
        "cre_mcp.tools.nearby_tools": "cre_property",
        "cre_mcp.tools.ops_tools": "cre_evaluate",
        "cre_mcp.tools.owner_tools": "cre_property",
        "cre_mcp.tools.pipeline_tools": "cre_pipeline",
        "cre_mcp.tools.structure_tools": "cre_structure",
        "cre_mcp.tools.truth_tools": "cre_diligence",
        "cre_mcp.valuation.tools": "cre_evaluate",
        "cre_mcp.verifyreg.tools": "cre_diligence",
        "cre_mcp.zoning.tools": "cre_property",
    }
)

_ACTION_GROUP_OVERRIDES = MappingProxyType(
    {
        "analyze_deal": "cre_evaluate",
        "find_deals": "cre_discover",
        "find_distressed": "cre_discover",
        "get_market_overview": "cre_market",
        "compare_markets": "cre_compare",
        "closing_plan": "cre_close",
        "draft_outreach": "cre_contact",
        "due_diligence_plan": "cre_diligence",
        "financing_options": "cre_finance",
        "find_contact": "cre_contact",
        "generate_loi": "cre_offer",
        "handle_counter": "cre_offer",
        "list_deals": "cre_pipeline",
        "qualify_me": "cre_finance",
        "recommend_offer": "cre_offer",
        "save_deal": "cre_pipeline",
        "size_debt": "cre_finance",
        "net_sale_proceeds": "cre_disposition",
        "diligence_request_list": "cre_diligence",
        "trace_input_lineage": "cre_diligence",
    }
)

_INTERNAL_MODULE_REASONS = MappingProxyType(
    {
        "cre_mcp.tools.about_tools": "server inventory and assumptions administration",
        "cre_mcp.tools.arbitrage_tools": "combined-opportunity workflow",
        "cre_mcp.tools.control_tools": "combined-opportunity workflow",
        "cre_mcp.mlops.tools": "internal control-position operations",
    }
)


def _inventory_digest() -> str:
    payload = json.dumps(
        export_matrix(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class CustomerSurfaceCatalog:
    """Validated map from grouped tools to exact internal capability IDs."""

    def __init__(self) -> None:
        if _inventory_digest() != CAPABILITY_INVENTORY_SHA256:
            raise RuntimeError(
                "capability inventory changed; review and re-lock the customer surface"
            )
        definitions = {
            name: (description, profiles)
            for name, description, profiles in _SURFACE_DEFINITIONS
        }
        assignments: dict[str, list[str]] = {name: [] for name in definitions}
        internal: dict[str, str] = {}
        capability_to_tool: dict[str, str] = {}
        for capability_id, capability in sorted(CAPABILITIES.items()):
            if capability.module in _INTERNAL_MODULE_REASONS:
                internal[capability_id] = _INTERNAL_MODULE_REASONS[capability.module]
                continue
            group = _ACTION_GROUP_OVERRIDES.get(capability_id)
            if group is None:
                group = _MODULE_GROUPS.get(capability.module)
            if group not in definitions:
                raise RuntimeError(
                    f"capability {capability_id!r} has no reviewed surface classification"
                )
            assignments[group].append(capability_id)
            capability_to_tool[capability_id] = group

        accounted = set(capability_to_tool) | set(internal)
        if accounted != set(CAPABILITIES):
            raise RuntimeError("customer surface does not account for every capability")
        if set(capability_to_tool) & set(internal):
            raise RuntimeError("a capability cannot be both customer-grouped and internal")
        if not set(LEGACY_TOOL_IDS) <= set(capability_to_tool):
            raise RuntimeError("every legacy tool must map to a grouped customer action")

        tools: dict[str, SurfaceToolSpec] = {}
        for name, (description, profiles) in definitions.items():
            capability_ids = tuple(assignments[name])
            if not capability_ids:
                raise RuntimeError(f"surface tool {name!r} has no actions")
            tools[name] = SurfaceToolSpec(
                name=name,
                description=description,
                profiles=profiles,
                capability_ids=capability_ids,
            )

        self.tools = MappingProxyType(tools)
        self.internal_capabilities = MappingProxyType(internal)
        self.capability_to_tool = MappingProxyType(capability_to_tool)

    def resolve(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve a facade call to one exact capability and its arguments."""
        spec = self.tools.get(tool_name)
        if spec is None or not isinstance(arguments, Mapping):
            return None
        action = arguments.get("action")
        action_arguments = arguments.get("arguments", {})
        if type(action) is not str or action not in spec.capability_ids:
            return None
        if action_arguments is None:
            action_arguments = {}
        if type(action_arguments) is not dict:
            return None
        exact_arguments = dict(action_arguments)
        return action, exact_arguments

    def is_visible(
        self,
        ctx: TenantContext | None,
        tool_name: str,
        engine: "AccessEngine",
    ) -> bool:
        """Require both facade-profile visibility and a live entitled action."""
        spec = self.tools.get(tool_name)
        if ctx is None or spec is None or ctx.profile not in spec.profiles:
            return False
        return any(
            engine.check_tool(ctx, capability_id).outcome == "allowed"
            for capability_id in spec.capability_ids
        )

    def visible_names(self, profile: Profile) -> tuple[str, ...]:
        return tuple(
            name
            for name, spec in self.tools.items()
            if profile in spec.profiles
            and any(
                profile.value in CAPABILITIES[capability_id].allowed_profiles
                for capability_id in spec.capability_ids
            )
        )

    def reconciliation_report(self) -> dict[str, Any]:
        """Return the complete 45-versus-274 reconciliation without secrets."""
        return {
            "capability_inventory_sha256": CAPABILITY_INVENTORY_SHA256,
            "internal_capability_count": len(CAPABILITIES),
            "legacy_tool_count": len(LEGACY_TOOL_IDS),
            "grouped_action_count": len(self.capability_to_tool),
            "internal_only_capability_count": len(self.internal_capabilities),
            "profile_tool_counts": {
                profile.value: len(self.visible_names(profile)) for profile in Profile
            },
            "legacy_mapping": {
                capability_id: self.capability_to_tool[capability_id]
                for capability_id in LEGACY_TOOL_IDS
            },
            "capability_mapping": {
                capability_id: self.capability_to_tool.get(capability_id, "internal")
                for capability_id in sorted(CAPABILITIES)
            },
            "internal_reasons": dict(self.internal_capabilities),
            "non_mcp_internal_classes": (
                "admin",
                "billing",
                "database",
                "security",
                "provider_repair",
            ),
        }


CUSTOMER_SURFACE = CustomerSurfaceCatalog()


__all__ = [
    "CAPABILITY_INVENTORY_SHA256",
    "CUSTOMER_SURFACE",
    "LEGACY_TOOL_IDS",
    "CustomerSurfaceCatalog",
    "SurfaceToolSpec",
]
