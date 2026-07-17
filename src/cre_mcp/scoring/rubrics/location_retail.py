"""Location-within-location street-retail rubric data."""

from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.rubrics._helpers import disqualifier, signal

LOCATION_RETAIL_RUBRIC = Rubric(
    strategy="location_retail",
    display_name="Location-Within-Location Retail",
    signals=[signal(key, T.LWL_WEIGHTS) for key in T.LWL_WEIGHTS],
    disqualifiers=[
        disqualifier("lwl_not_street_level"),
        disqualifier("lwl_bottom_quartile_traffic"),
        disqualifier("lwl_special_assessment"),
        disqualifier("lwl_zoning_prohibits_retail"),
    ],
    include_core=True,
    market_weight=T.DEFAULT_MARKET_WEIGHT,
)
