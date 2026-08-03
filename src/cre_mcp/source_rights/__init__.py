"""Fail-closed source-rights controls for external data access.

Exports resolve lazily because configuration imports access-profile types while
access middleware imports this package's gate. Eagerly loading the attestation
store here would pull configuration back into itself during startup.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "SourceRightsDeniedError",
    "DocumentAttestationStore",
    "SourceRightsRegistry",
    "get_rights_registry",
    "is_hosted_execution",
    "require_source",
    "require_url",
    "require_external_document_attestation",
]


_EXPORT_MODULES = {
    "DocumentAttestationStore": "cre_mcp.source_rights.attestations",
    "require_external_document_attestation": "cre_mcp.source_rights.attestations",
    "SourceRightsDeniedError": "cre_mcp.source_rights.gate",
    "is_hosted_execution": "cre_mcp.source_rights.gate",
    "require_source": "cre_mcp.source_rights.gate",
    "require_url": "cre_mcp.source_rights.gate",
    "SourceRightsRegistry": "cre_mcp.source_rights.registry",
    "get_rights_registry": "cre_mcp.source_rights.registry",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
