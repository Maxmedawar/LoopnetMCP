"""Human-readable score explanations."""

from cre_mcp.models.deals import DealContext
from cre_mcp.models.scoring import Rubric, RubricResult, SignalResult


def _signal_text(result: SignalResult) -> str:
    normalized = result.normalized if result.normalized is not None else 0.0
    raw = "unknown" if result.raw_value is None else f"{result.raw_value:.2f}"
    return f"{result.key} ({raw} → {normalized:.2f})"


def render_explanation(
    ctx: DealContext,
    rubric: Rubric,
    result: RubricResult,
    *,
    final_score: float,
    grade: str,
    market_component: float | None,
    core_component: float | None,
) -> str:
    """Render strengths, weaknesses, market context, and a FACTS next step."""
    if result.disqualified:
        reasons = "; ".join(result.disqualifier_hits)
        return f"DQ under {rubric.display_name}: {reasons} FACTS next step: resolve the disqualifier before analysis continues."

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
        f" Path of progress: {path_metric.value:g} permitted units as of {path_metric.as_of or 'unknown'}."
        if path_metric and path_metric.value is not None
        else " Path-of-progress permit data is unavailable."
    )
    strength_line = ", ".join(_signal_text(item) for item in strengths) or "none covered"
    weakness_line = ", ".join(_signal_text(item) for item in weaknesses) or "none covered"
    missing_line = ", ".join(missing[:6]) or "none"
    return (
        f"{rubric.display_name} scored {final_score:.2f}/100 ({grade}) at "
        f"{result.coverage:.0%} rubric coverage. Top strengths: {strength_line}. "
        f"Top weaknesses: {weakness_line}. Missing signals: {missing_line}. "
        f"{market_line}{core_line}{path_line} "
        "FACTS next step: verify the highest-impact missing inputs, then Analyze and Control the deal assumptions."
    )
