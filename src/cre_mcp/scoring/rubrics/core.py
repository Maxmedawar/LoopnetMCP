"""Shared deal-quality core rubric data."""

from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.rubrics._helpers import disqualifier, signal

CORE_RUBRIC = Rubric(
    strategy="core",
    display_name="Shared Deal-Quality Core",
    signals=[signal(key, T.CORE_WEIGHTS) for key in T.CORE_WEIGHTS],
    disqualifiers=[
        disqualifier("core_title_defect"),
        disqualifier("core_uninsured_extreme_hazard"),
        disqualifier("core_missing_financials"),
    ],
    include_core=False,
    market_weight=T.DEFAULT_MARKET_WEIGHT,
)
