"""Single-tenant NNN retail rubric data."""

from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.rubrics._helpers import disqualifier, signal

NNN_RETAIL_RUBRIC = Rubric(
    strategy="nnn_retail",
    display_name="Single-Tenant NNN Retail",
    signals=[signal(key, T.NNN_WEIGHTS) for key in T.NNN_WEIGHTS],
    disqualifiers=[
        disqualifier("nnn_short_lease_sub_ig"),
        disqualifier("nnn_single_franchisee_low_cap"),
        disqualifier("nnn_environmental_rec"),
        disqualifier("nnn_cap_below_tier"),
    ],
    include_core=True,
    market_weight=T.DEFAULT_MARKET_WEIGHT,
)
