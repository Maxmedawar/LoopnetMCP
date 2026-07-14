"""Regulation D preliminary action-gate tests."""

import pytest

from cre_mcp.capital.exemption import check_solicitation


def test_506b_blocks_public_solicitation():
    result = check_solicitation("506b", "advertise_publicly")

    assert result.allowed is False
    assert "general/public solicitation" in result.why
    assert "Rule 506(b)" in result.rule
    assert "securities attorney" in result.guardrail


def test_506b_blocks_new_non_accredited_purchaser():
    result = check_solicitation(
        "506(b)",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": False,
            "relationship": "new",
            "non_accredited_count": 0,
        },
    )

    assert result.allowed is False
    assert "non-accredited" in result.why
    assert "pre-existing" in result.why
    assert any("Rule 502(b)" in item for item in result.remediation)


def test_506b_blocks_thirty_sixth_non_accredited_but_not_formal_verification():
    over_limit = check_solicitation(
        "506b",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": False,
            "relationship": "preexisting",
            "non_accredited_count": 35,
        },
    )
    accredited = check_solicitation(
        "506b",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": True,
            "accreditation_verified": False,
            "relationship": "preexisting",
        },
    )

    assert over_limit.allowed is False
    assert "35" in over_limit.why
    assert accredited.allowed is True
    assert "checked box alone" in " ".join(accredited.remediation)


def test_506c_allows_publicity_but_blocks_unverified_or_non_accredited_sales():
    publicity = check_solicitation("506c", "advertise_publicly")
    unverified = check_solicitation(
        "506c",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": True,
            "accreditation_verified": False,
        },
    )
    non_accredited = check_solicitation(
        "506c",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": False,
            "accreditation_verified": False,
        },
    )

    assert publicity.allowed is True
    assert unverified.allowed is False
    assert "self-certification alone" in unverified.why
    assert non_accredited.allowed is False
    assert "only to accredited investors" in non_accredited.why


@pytest.mark.parametrize("mode", ["506b", "506c"])
@pytest.mark.parametrize(
    "action",
    [
        "launch_the_moon_campaign",
        "do_not_advertise",
        "review_accept_verified_accredited",
        "accept_verified_accredited_then_launch_rocket",
    ],
)
def test_unrecognized_action_defaults_to_blocked_with_exact_counsel_gate(mode, action):
    result = check_solicitation(mode, action)

    assert result.allowed is False
    assert (
        "Not explicitly permitted — treat as prohibited until a securities attorney confirms"
        in result.why
    )
    assert "securities attorney" in result.guardrail


@pytest.mark.parametrize(
    "action",
    [
        "accept_unverified_accredited",
        "accept an unverified accredited investor",
        "accept_unverified_accredited_investor",
        "accept self-certified accredited investor",
        "close subscription for accredited investor pending verification",
        "onboard an accredited investor with unknown verification",
    ],
)
def test_506c_natural_language_unverified_acceptance_is_always_blocked(action):
    result = check_solicitation("506c", action)

    assert result.allowed is False
    assert "not been verified" in result.why
    assert "self-certification alone" in result.why


def test_506c_known_good_publicity_and_verified_purchaser_actions_are_allowlisted():
    publicity = check_solicitation(
        "506c",
        {
            "action": "advertise",
            "all_investors_accredited": True,
            "all_accreditation_verified": True,
        },
    )
    purchaser = check_solicitation("506c", "onboard_verified_accredited_investor")

    assert publicity.allowed is True
    assert purchaser.allowed is True
    assert "Explicitly recognized" in publicity.why
    assert "verified" in purchaser.why


@pytest.mark.parametrize("mode", ["506b", "506c"])
def test_known_draft_preparation_is_explicitly_allowlisted_but_still_gated(mode):
    result = check_solicitation(mode, "prepare_private_draft")

    assert result.allowed is True
    assert "does not authorize" in result.why
    assert "securities attorney" in result.guardrail


def test_bad_mode_and_unknown_purchaser_are_blocked():
    with pytest.raises(ValueError, match="506b or 506c"):
        check_solicitation("reg-a", "advertise")

    result = check_solicitation(
        "506b",
        {"action": "accept_money", "accepting_money": True},
    )
    assert result.allowed is False
    assert "unknown" in result.why
