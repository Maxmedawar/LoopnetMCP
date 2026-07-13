"""Allow running with: python -m cre_mcp"""

from cre_mcp.server import mcp

mcp.run(transport="stdio")
