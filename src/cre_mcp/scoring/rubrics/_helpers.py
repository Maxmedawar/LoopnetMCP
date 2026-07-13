"""Model constructors for rubric data modules."""

from cre_mcp.models.scoring import Band, DisqualifierSpec, SignalSpec
from cre_mcp.scoring.rubrics import thresholds as T


def signal(key: str, weights: dict[str, float]) -> SignalSpec:
    return SignalSpec(
        key=key,
        label=T.SIGNAL_LABELS[key],
        extractor=key,
        weight=weights[key],
        bands=[Band(up_to=edge, score=score) for edge, score in T.SIGNAL_BANDS.get(key, ())],
        higher_is_better=key not in T.LOWER_IS_BETTER,
        required=key in T.REQUIRED_SIGNALS,
    )


def disqualifier(key: str) -> DisqualifierSpec:
    return DisqualifierSpec(
        key=key,
        predicate=key,
        reason_template=T.DISQUALIFIER_REASONS[key],
    )
