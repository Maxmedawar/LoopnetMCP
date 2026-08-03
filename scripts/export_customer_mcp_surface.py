#!/usr/bin/env python3
"""Export the reviewed customer MCP reconciliation as deterministic JSON."""

from __future__ import annotations

import json

from cre_mcp.surface import CUSTOMER_SURFACE


def main() -> None:
    """Print the locked 45-versus-274 reconciliation without secrets."""
    print(
        json.dumps(
            CUSTOMER_SURFACE.reconciliation_report(),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
