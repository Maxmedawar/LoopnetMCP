"""Geographic resolution and ZIP crosswalk support.

The public objects are loaded lazily so importing the dependency-free
``cre_mcp.geo.constants`` module cannot pull configuration back through the
access engine during application startup.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cre_mcp.geo.crosswalk import GeoCrosswalk
    from cre_mcp.geo.resolver import GeoResolver, resolve


def __getattr__(name: str) -> Any:
    if name == "GeoCrosswalk":
        from cre_mcp.geo.crosswalk import GeoCrosswalk

        return GeoCrosswalk
    if name in {"GeoResolver", "resolve"}:
        from cre_mcp.geo.resolver import GeoResolver, resolve

        return {"GeoResolver": GeoResolver, "resolve": resolve}[name]
    raise AttributeError(name)


__all__ = ["GeoCrosswalk", "GeoResolver", "resolve"]
