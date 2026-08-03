"""Single source of truth for cross-cutting registry expectations.

Bump EXPECTED_TOOL_COUNT in the same commit that registers new tools —
every registration test imports it instead of hardcoding a magic number.
"""

EXPECTED_TOOL_COUNT = 274
