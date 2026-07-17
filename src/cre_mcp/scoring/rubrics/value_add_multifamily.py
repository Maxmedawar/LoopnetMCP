"""Value-add multifamily rubric data."""

from cre_mcp.models.scoring import Rubric
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.rubrics._helpers import disqualifier, signal

VALUE_ADD_MULTIFAMILY_RUBRIC = Rubric(
    strategy="value_add_multifamily",
    display_name="Value-Add Multifamily",
    signals=[signal(key, T.VAM_WEIGHTS) for key in T.VAM_WEIGHTS],
    disqualifiers=[
        disqualifier("vam_dscr_below_one"),
        disqualifier("vam_negative_absorption_pipeline"),
        disqualifier("vam_unpriced_deferred_maintenance"),
    ],
    include_core=True,
    market_weight=T.DEFAULT_MARKET_WEIGHT,
)
