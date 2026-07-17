"""The machine-readable tool capability matrix.

One entry per registered MCP tool, authored as JSON in
``capability_matrix.json`` next to this module. Tests enforce that the matrix
covers exactly the registered tool set and that declared parameter names exist
on the real tool schemas. A tool without an entry is denied in cloud mode.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ToolCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    allowed_profiles: tuple[str, ...]
    sensitive: bool = False
    sensitive_params: tuple[str, ...] = ()
    territory_params: tuple[str, ...] = ()
    # Identity-shaped argument names (see engine.RESERVED_IDENTITY_ARGS) that
    # are legitimate business parameters on THIS tool and must survive cloud
    # sanitization instead of being stripped as identity-smuggling attempts.
    preserve_params: tuple[str, ...] = ()
    ownership_relevant: bool = False
    quota: str | None = None
    approval: str | None = None
    module: str = ""


_MATRIX_PATH = Path(__file__).with_name("capability_matrix.json")


def _load() -> dict[str, ToolCapability]:
    if not _MATRIX_PATH.exists():
        return {}
    raw = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    return {
        name: ToolCapability.model_validate({"tool": name, **entry})
        for name, entry in raw.items()
    }


CAPABILITIES: dict[str, ToolCapability] = _load()


def capability_for(tool_name: str) -> ToolCapability | None:
    return CAPABILITIES.get(tool_name)


def export_matrix() -> dict[str, dict]:
    """The matrix as plain JSON-ready data."""
    return {
        name: cap.model_dump(exclude={"tool"}) for name, cap in CAPABILITIES.items()
    }
