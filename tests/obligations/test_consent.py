"""Job 214 transfer-consent fatal-flaw screens."""

from cre_mcp.obligations.consent import screen_transfer_consents
from cre_mcp.obligations.tools import screen_transfer_consents as screen_tool


def test_absolute_sublet_prohibition_kills_master_lease_and_discloses_missing_loan_terms():
    lease = "Tenant shall not assign this Lease or sublet any portion of the Premises under any circumstances."
    screen = screen_transfer_consents(
        {"lease_text": lease, "intended": "master_lease"}
    )

    assert screen.assignment_subletting_standard == "prohibited"
    assert any(flag.code == "deal_killer_absolute_prohibition_master_lease" for flag in screen.fatal_flags)
    assert any("DEAL-KILLER" in flag.message for flag in screen.fatal_flags)
    assert screen.lease_assignment_subletting.quote in lease
    assert "loan_terms_missing_due_on_sale_and_transfer_review_not_performed" in screen.gaps
    assert any(requirement.who.startswith("Landlord") for requirement in screen.required_consents)


def test_reasonable_consent_and_structured_lender_trigger_require_both_consents():
    lease = (
        "Tenant shall not assign this Lease or sublet the Premises without Landlord's prior written "
        "consent, which consent shall not be unreasonably withheld, conditioned, or delayed."
    )
    screen = screen_transfer_consents(
        {
            "lease_text": lease,
            "loan_terms": {
                "due_on_sale": False,
                "transfer_provisions": "Lender approval is required before any lease, sublease, or transfer.",
            },
            "intended": "sublease",
        }
    )

    assert screen.assignment_subletting_standard == "consent_not_unreasonably_withheld"
    assert {item.who for item in screen.required_consents} == {
        "Landlord",
        "Lender / loan servicer",
    }
    assert all("CONVENTION" in item.timing_note for item in screen.required_consents)
    assert any(flag.code == "loan_transfer_trigger_requires_resolution" for flag in screen.fatal_flags)


def test_plain_consent_tool_is_json_friendly_and_honest():
    payload = screen_tool(
        lease_text="Tenant may assign or sublet without Landlord consent.",
        intended="sublease",
    )

    assert payload["assignment_subletting_standard"] == "free"
    assert payload["honesty"]["legal_review_required"] is True
    assert "loan_terms_missing_due_on_sale_and_transfer_review_not_performed" in payload["honesty"]["gaps"]
