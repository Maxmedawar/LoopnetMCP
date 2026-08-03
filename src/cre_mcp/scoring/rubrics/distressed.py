"""NDE distressed and note-tape rubric data."""

from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.rubrics._helpers import disqualifier, signal

DISTRESSED_RUBRIC = Rubric(
    strategy="distressed",
    display_name="NDE Distressed / Note-Tape",
    signals=[signal(key, T.DISTRESSED_WEIGHTS) for key in T.DISTRESSED_WEIGHTS],
    disqualifiers=[
        disqualifier("distressed_title_defect"),
        disqualifier("distressed_junior_lien_default"),
        disqualifier("distressed_collateral_below_30"),
        disqualifier("distressed_1031_clock"),
    ],
    include_core=True,
    market_weight=T.DEFAULT_MARKET_WEIGHT,
)

__all__ = ["DISTRESSED_RUBRIC"]
