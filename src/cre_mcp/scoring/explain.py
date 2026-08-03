"""Human-readable score explanations."""

from cre_mcp.models.deals import DealContext
from cre_mcp.models.scoring import Rubric, RubricResult, SignalResult
from cre_mcp.scoring.rubrics import thresholds as T


def _signal_text(result: SignalResult) -> str:
    normalized = result.normalized if result.normalized is not None else 0.0
    raw = "unknown" if result.raw_value is None else f"{result.raw_value:.2f}"
    return f"{result.key} ({raw} → {normalized:.2f})"


def _gate_lead(rubric: Rubric, result: RubricResult) -> str:
    missing = {signal.key for signal in result.signal_results if signal.missing}
    ordered = sorted(
        (signal for signal in rubric.signals if signal.key in missing),
        key=lambda signal: signal.weight,
        reverse=True,
    )[: T.GATE_MISSING_SIGNAL_LIMIT]
    keys = [signal.key for signal in ordered]
    actions: list[str] = []
    for key in keys:
        action = T.GATE_MISSING_INPUT_GUIDANCE.get(
            key,
            T.GATE_DEFAULT_MISSING_INPUT_GUIDANCE,
        )
        if action not in actions:
            actions.append(action)
    missing_text = ", ".join(keys) or "the rubric's required inputs"
    action_text = "; ".join(actions) or T.GATE_DEFAULT_MISSING_INPUT_GUIDANCE
    return (
        "Not rated — insufficient data to score. "
        f"Biggest missing inputs: {missing_text}. Get them by: {action_text}. "
    )


def render_explanation(
    ctx: DealContext,
    rubric: Rubric,
    result: RubricResult,
    *,
    final_score: float,
    grade: str,
    market_component: float | None,
    core_component: float | None,
    gated: bool = False,
) -> str:
    """Render strengths, weaknesses, market context, and a FACTS next step."""
    if result.disqualified:
        reasons = "; ".join(result.disqualifier_hits)
        return (
            f"DQ under {rubric.display_name}: {reasons} FACTS next step: "
            "resolve the disqualifier before analysis continues."
        )

    available = [signal for signal in result.signal_results if not signal.missing]
    strengths = sorted(available, key=lambda item: item.weighted_points, reverse=True)[:3]
    weaknesses = sorted(
        available,
        key=lambda item: (
            item.normalized if item.normalized is not None else 0.0,
            item.weighted_points,
        ),
    )[:3]
    missing = [signal.key for signal in result.signal_results if signal.missing]
    market_line = (
        f"Market component {market_component:.2f}/100."
        if market_component is not None
        else "Market component unavailable and excluded from the blend."
    )
    core_line = (
        f" Core component {core_component:.2f}/100."
        if core_component is not None
        else ""
    )
    path_metric = ctx.market.permits_trailing_12m if ctx.market else None
    path_line = (
        f" Path of progress: {path_metric.value:g} permitted units as of "
        f"{path_metric.as_of or 'unknown'}."
        if path_metric and path_metric.value is not None
        else " Path-of-progress permit data is unavailable."
    )
    strength_line = ", ".join(_signal_text(item) for item in strengths) or "none covered"
    weakness_line = ", ".join(_signal_text(item) for item in weaknesses) or "none covered"
    missing_line = ", ".join(missing[:6]) or "none"
    explanation = (
        f"{rubric.display_name} scored {final_score:.2f}/100 ({grade}) at "
        f"{result.coverage:.0%} rubric coverage. Top strengths: {strength_line}. "
        f"Top weaknesses: {weakness_line}. Missing signals: {missing_line}. "
        f"{market_line}{core_line}{path_line} "
        "FACTS next step: verify the highest-impact missing inputs, then Analyze "
        "and Control the deal assumptions."
    )
    return f"{_gate_lead(rubric, result)}{explanation}" if gated else explanation
