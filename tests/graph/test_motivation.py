from __future__ import annotations

import asyncio

from cre_mcp.graph.motivation import (
    MotivationSignal,
    SellerPriority,
    TriggerType,
    score_motivation,
)
from cre_mcp.tools.motivation_tools import find_motivated_owners


def _signal(
    trigger_type: TriggerType,
    *,
    property_id: str = "property-1",
    severity: float = 0.1,
    freshness_days: int | None = 0,
) -> MotivationSignal:
    return MotivationSignal(
        property_id=property_id,
        owner_name="Example Owner LLC",
        trigger_type=trigger_type,
        evidence_source="county recorder",
        evidence_url="https://example.test/record/1",
        evidence_date="2026-07-14",
        severity=severity,
        freshness_days=freshness_days,
    )


def test_fresh_high_urgency_triggers_show_strong_engagement() -> None:
    result = score_motivation(
        [
            _signal(TriggerType.FORECLOSURE_NOTICE),
            _signal(TriggerType.SPECIAL_SERVICING),
        ]
    )

    assert result.engagement_probability > 0.8
    assert SellerPriority.DEBT_RELEASE in result.inferred_priorities
    assert SellerPriority.SPEED in result.inferred_priorities


def test_stale_weak_signals_remain_modest() -> None:
    result = score_motivation(
        [
            _signal(TriggerType.PRICE_CUT, freshness_days=900),
            _signal(TriggerType.LONG_VACANCY, freshness_days=900),
            _signal(TriggerType.PRICE_CUT, freshness_days=900),
            _signal(TriggerType.LONG_VACANCY, freshness_days=900),
        ]
    )

    assert result.engagement_probability < 0.6


def test_empty_signals_return_low_information_result() -> None:
    result = score_motivation([])

    assert result.engagement_probability < 0.2
    assert result.confidence < 0.2
    assert result.caveats


def test_probate_infers_confidentiality() -> None:
    result = score_motivation([_signal(TriggerType.PROBATE_ESTATE)])

    assert SellerPriority.CONFIDENTIALITY in result.inferred_priorities


def test_find_motivated_owners_ranks_descending() -> None:
    result = asyncio.run(
        find_motivated_owners(
            {
                "low": [
                    {
                        "trigger_type": "price_cut",
                        "evidence_source": "listing history",
                        "severity": 0.1,
                        "freshness_days": 900,
                    }
                ],
                "high": [
                    {
                        "trigger_type": "auction_scheduled",
                        "evidence_source": "county recorder",
                        "severity": 0.9,
                        "freshness_days": 1,
                    }
                ],
            }
        )
    )

    assert isinstance(result, list)
    assert [item["property_id"] for item in result] == ["high", "low"]
    assert result[0]["engagement_probability"] > result[1]["engagement_probability"]
