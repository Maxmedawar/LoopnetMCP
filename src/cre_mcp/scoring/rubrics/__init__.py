"""Rubric registry and property-type strategy routing."""

from cre_mcp.models.deals import DealContext
from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics.core import CORE_RUBRIC
from cre_mcp.scoring.rubrics.distressed import DISTRESSED_RUBRIC
from cre_mcp.scoring.rubrics.location_retail import LOCATION_RETAIL_RUBRIC
from cre_mcp.scoring.rubrics.nnn_retail import NNN_RETAIL_RUBRIC
from cre_mcp.scoring.rubrics.value_add_multifamily import VALUE_ADD_MULTIFAMILY_RUBRIC

RUBRIC_REGISTRY: dict[str, Rubric] = {
    rubric.strategy: rubric
    for rubric in (
        CORE_RUBRIC,
        DISTRESSED_RUBRIC,
        NNN_RETAIL_RUBRIC,
        VALUE_ADD_MULTIFAMILY_RUBRIC,
        LOCATION_RETAIL_RUBRIC,
    )
}


def applicable_rubrics(ctx: DealContext) -> list[Rubric]:
    """Map listing property type and explicit raw hints to strategy rubrics."""
    explicit = ctx.listing.raw.get("strategy")
    if isinstance(explicit, str) and explicit in RUBRIC_REGISTRY:
        routed = [RUBRIC_REGISTRY[explicit]]
        if ctx.listing.is_distressed and explicit != DISTRESSED_RUBRIC.strategy:
            return [DISTRESSED_RUBRIC, *routed]
        if not ctx.listing.is_distressed:
            return routed
    property_type = (ctx.listing.property_type or "").casefold()
    if property_type == "multifamily":
        asset_rubrics = [VALUE_ADD_MULTIFAMILY_RUBRIC]
    elif property_type == "retail":
        asset_rubrics = [NNN_RETAIL_RUBRIC, LOCATION_RETAIL_RUBRIC]
    else:
        asset_rubrics = [CORE_RUBRIC]
    if ctx.listing.is_distressed:
        return [DISTRESSED_RUBRIC, *asset_rubrics]
    return asset_rubrics


__all__ = [
    "CORE_RUBRIC",
    "DISTRESSED_RUBRIC",
    "LOCATION_RETAIL_RUBRIC",
    "NNN_RETAIL_RUBRIC",
    "RUBRIC_REGISTRY",
    "VALUE_ADD_MULTIFAMILY_RUBRIC",
    "applicable_rubrics",
]
