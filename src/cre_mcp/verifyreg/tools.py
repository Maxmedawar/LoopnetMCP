"""Plain callables for later FastMCP registration by the integration director."""

from __future__ import annotations

from typing import Any

from cre_mcp.verifyreg.registry import verify_counterparty


async def verify_license(name: str, state: str | None, role: str) -> dict[str, Any]:
    """Screen one role without asserting that any candidate is the named party."""
    return await verify_counterparty(name, state, roles=[role])


async def counterparty_screen(name: str, state: str | None = None) -> dict[str, Any]:
    """Screen all supported roles in source-priority order."""
    return await verify_counterparty(name, state)


__all__ = ["counterparty_screen", "verify_license"]
