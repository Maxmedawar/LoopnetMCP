"""Cited estoppel mismatch and SNDA presence tests."""

from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseDates, RentPeriod
from cre_mcp.obligations.estoppels import EstoppelComparison, compare_estoppel
from cre_mcp.obligations.tools import compare_estoppel_to_lease


def _claim(value, quote):
    return CitedClaim.stated(
        value,
        quote=quote,
        locator="Synthetic Lease §3",
        confidence=1.0,
    )


def test_rent_mismatch_is_a_material_exception_with_lease_citation():
    lease = LeaseAbstract(
        dates=LeaseDates(expiration=_claim("2030-12-31", "Term expires December 31, 2030")),
        rent_schedule=[RentPeriod(monthly=_claim(1_000.0, "Monthly Base Rent is $1,000.00"))],
    )
    comparison = compare_estoppel(
        lease,
        {
            "rent": 1_100.0,
            "expiration": "2030-12-31",
            "options": [],
            "defaults_claimed": [],
            "amendments_listed": [],
        },
    )

    assert isinstance(comparison, list)
    assert isinstance(comparison, EstoppelComparison)
    rent = next(item for item in comparison if item.field == "rent")
    assert rent.severity == "material"
    assert rent.lease_quote == "Monthly Base Rent is $1,000.00"
    assert rent.lease_cite == "Synthetic Lease §3"
    assert comparison.snda.status == "unknown_not_supplied"


def test_mapping_terms_compare_and_tool_tracks_snda_fields():
    terms = {
        "rent": _claim(2_000.0, "Base Rent shall be $2,000 monthly"),
        "expiration": _claim("2032-06-30", "Lease expires June 30, 2032"),
        "options": _claim(["renew"], "Tenant has one renewal option"),
        "snda": _claim(True, "Tenant shall execute an SNDA"),
    }
    payload = compare_estoppel_to_lease(
        terms,
        {
            "rent": 2_000.0,
            "expiration": "2032-06-30",
            "options": ["renew"],
            "defaults_claimed": [],
            "amendments_listed": [],
            "snda_present": True,
        },
    )

    assert payload["exception_count"] == 0
    assert payload["snda"]["lease_reference_present"] is True
    assert payload["snda"]["estoppel_acknowledged"] is True
    assert payload["snda"]["status"] == "referenced_and_acknowledged"
    assert payload["honesty"]["lease_side_citation_required_for_every_exception"] is True
