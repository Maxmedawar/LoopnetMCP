"""Amendment-chain tests against the real SEC amendment specimen."""

from pathlib import Path

from cre_mcp.leases.amendments import apply_amendments
from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseDates, RentPeriod
from cre_mcp.leases.reader import read_lease

FIXTURES = Path(__file__).parents[1] / "fixtures" / "leases"


def _claim(value, quote="synthetic base"):
    return CitedClaim.stated(value, quote=quote, locator="Synthetic", confidence=1.0)


def test_real_amendment_overrides_synthetic_base_with_field_provenance():
    base = LeaseAbstract(
        dates=LeaseDates(
            commencement=_claim("2014-08-08"),
            expiration=_claim("2023-07-31"),
            term_months=_claim(108),
        ),
        rent_schedule=[RentPeriod(
            start=_claim("2022-08-01"),
            end=_claim("2023-07-31"),
            annual=_claim(250_000.0),
            monthly=_claim(20_833.33),
        )],
    )
    amendment = read_lease(FIXTURES / "office_lease_amendment_13th.htm").text

    effective = apply_amendments(base, [amendment])

    assert effective.dates.expiration.value == "2026-06-30"
    assert effective.dates.expiration.source == "amendment_1"
    assert effective.dates.commencement.value == "2023-08-01"
    assert effective.rent_schedule[0].annual.value == 263_358.96
    assert effective.rent_schedule[0].annual.source == "amendment_1"
    assert effective.amendment_count == 1
    # The input remains untouched.
    assert base.dates.expiration.value == "2023-07-31"
    assert base.dates.expiration.source == "base"


def test_missing_amendment_field_does_not_erase_base_claim():
    base = LeaseAbstract(dates=LeaseDates(expiration=_claim("2030-12-31")))

    effective = apply_amendments(base, ["This amendment changes the parking rules only."])

    assert effective.dates.expiration.value == "2030-12-31"
    assert effective.dates.expiration.source == "base"

