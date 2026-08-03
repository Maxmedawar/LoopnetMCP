"""Profile-specific customer MCP surface over the internal capability server."""

from .catalog import (
    CUSTOMER_SURFACE,
    LEGACY_TOOL_IDS,
    CustomerSurfaceCatalog,
    SurfaceToolSpec,
)
from .server import build_customer_server

__all__ = [
    "CUSTOMER_SURFACE",
    "LEGACY_TOOL_IDS",
    "CustomerSurfaceCatalog",
    "SurfaceToolSpec",
    "build_customer_server",
]
