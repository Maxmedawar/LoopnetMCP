from __future__ import annotations

from cre_mcp.siteintel.dedup import (
    FUZZY_TOKEN_OVERLAP_THRESHOLD,
    dedupe_listings,
    normalize_address,
    normalize_zip5,
)


def _listing(source: str, source_id: str, address: str, **overrides: object):
    listing = {
        "source": source,
        "source_id": source_id,
        "address": address,
        "city": "Austin",
        "state": "TX",
        "zip": "78701",
    }
    listing.update(overrides)
    return listing


def test_normalization_preserves_suite_identity_and_normalizes_zip5():
    assert normalize_address("101 Main Street, Suite #200") == "101 main st ste 200"
    assert normalize_address("101 MAIN ST., STE. 200") == "101 main st ste 200"
    assert normalize_zip5("78701-1234") == "78701"


def test_same_full_address_in_different_formats_is_exact_duplicate():
    result = dedupe_listings(
        [
            _listing(
                "loopnet",
                "ln-1",
                "101 Main Street, Suite #200",
                zip="78701-1234",
            ),
            _listing("crexi", "cx-1", "101 MAIN ST., STE. 200"),
        ]
    )

    assert "error" not in result
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["tier"] == "duplicate"
    assert group["match_basis"] == "exact_normalized_address"
    assert len(group["members"]) == 2
    assert result["candidate_matches"] == []


def test_missing_zip_is_non_blocking_but_cannot_bridge_conflicting_zip5s():
    compatible = dedupe_listings(
        [
            _listing("loopnet", "ln-known", "101 Main Street", zip="78701"),
            _listing("crexi", "cx-missing", "101 Main St", zip=None),
        ]
    )

    assert len(compatible["groups"]) == 1
    assert compatible["groups"][0]["tier"] == "duplicate"
    assert len(compatible["groups"][0]["members"]) == 2

    conflicting = dedupe_listings(
        [
            _listing("loopnet", "ln-78701", "101 Main St", zip="78701"),
            _listing("crexi", "cx-missing", "101 Main Street", zip=None),
            _listing("broker", "br-78702", "101 MAIN ST", zip="78702-1111"),
        ]
    )

    assert len(conflicting["groups"]) == 3
    assert all(len(group["members"]) == 1 for group in conflicting["groups"])
    assert conflicting["candidate_matches"]


def test_directional_and_street_type_variants_exact_match_without_merging_suite():
    result = dedupe_listings(
        [
            _listing(
                "loopnet",
                "ln-congress",
                "4201 South Congress Avenue",
                price=2_400_000,
                seen_date="2026-02-10",
            ),
            _listing(
                "crexi",
                "cx-congress",
                "4201 S Congress Ave",
                price=2_250_000,
                seen_date="2026-01-05",
            ),
            _listing(
                "broker",
                "br-congress-200",
                "4201 South Congress Avenue Suite 200",
                price=1_100_000,
                seen_date="2026-03-01",
            ),
        ]
    )

    assert len(result["groups"]) == 2
    exact_group = next(
        group for group in result["groups"] if group["tier"] == "duplicate"
    )
    suite_group = next(group for group in result["groups"] if group is not exact_group)
    assert [member["source"] for member in exact_group["members"]] == [
        "loopnet",
        "crexi",
    ]
    assert [item["source"] for item in exact_group["price_history"]] == [
        "crexi",
        "loopnet",
    ]
    assert len(suite_group["members"]) == 1
    assert suite_group["canonical"]["source_id"] == "br-congress-200"
    assert suite_group["tier"] == "candidate"
    assert len(result["candidate_matches"]) == 1
    assert result["candidate_matches"][0]["match_basis"] == (
        "same_street_different_suite"
    )


def test_different_suites_are_candidates_and_are_never_merged():
    result = dedupe_listings(
        [
            _listing("loopnet", "ln-200", "101 Main St Ste 200"),
            _listing("crexi", "cx-201", "101 Main Street Suite 201"),
        ]
    )

    assert len(result["groups"]) == 2
    assert all(len(group["members"]) == 1 for group in result["groups"])
    assert all(group["tier"] == "candidate" for group in result["groups"])
    assert len(result["candidate_matches"]) == 1
    candidate = result["candidate_matches"][0]
    assert candidate["match_basis"] == "same_street_different_suite"
    assert candidate["score"] == 1.0
    assert candidate["requires_human_confirmation"] is True
    assert "never merged" in result["honesty"].casefold()


def test_fuzzy_token_overlap_at_threshold_is_candidate_not_duplicate():
    result = dedupe_listings(
        [
            _listing("loopnet", "ln-north", "750 North Harbor Street"),
            _listing("crexi", "cx-harbor", "750 Harbor St"),
            _listing("other", "other-1", "999 Other Road"),
        ]
    )

    assert result["fuzzy_threshold"] == FUZZY_TOKEN_OVERLAP_THRESHOLD
    assert len(result["groups"]) == 3
    assert all(len(group["members"]) == 1 for group in result["groups"])
    assert len(result["candidate_matches"]) == 1
    candidate = result["candidate_matches"][0]
    assert candidate["tier"] == "candidate"
    assert candidate["match_basis"] == "fuzzy_token_overlap"
    assert candidate["score"] == FUZZY_TOKEN_OVERLAP_THRESHOLD


def test_price_history_is_sorted_by_seen_date_across_sources():
    result = dedupe_listings(
        [
            _listing(
                "loopnet",
                "ln-1",
                "101 Main Street",
                price=1_200_000,
                seen_date="2026-03-15",
            ),
            _listing(
                "crexi",
                "cx-1",
                "101 Main St.",
                price=1_300_000,
                seen_date="2025-12-01",
            ),
            _listing(
                "broker",
                "br-1",
                "101 MAIN STREET",
                price=1_100_000,
                seen_date="2026-01-10",
            ),
        ]
    )

    history = result["groups"][0]["price_history"]
    assert [item["seen_date"] for item in history] == [
        "2025-12-01",
        "2026-01-10",
        "2026-03-15",
    ]
    assert [item["source"] for item in history] == [
        "crexi",
        "broker",
        "loopnet",
    ]


def test_invalid_input_uses_error_boundary():
    result = dedupe_listings([{"source": "loopnet"}])
    assert "error" in result
