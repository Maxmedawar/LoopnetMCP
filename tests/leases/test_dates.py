"""Critical-date horizon and severity proofs."""

from cre_mcp.leases.dates import critical_dates
from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseDates, LeaseOption, RentPeriod


def _claim(value):
    return CitedClaim.stated(value, quote=str(value), locator="Synthetic", confidence=1.0)


def test_expiration_option_window_notice_and_rent_step_calendar():
    lease = LeaseAbstract(
        dates=LeaseDates(
            commencement=_claim("2025-01-01"),
            expiration=_claim("2026-12-31"),
        ),
        options=[LeaseOption(
            option_type=_claim("renew"),
            exercise_window=_claim(
                "not more than twelve (12) months nor less than six (6) months prior to expiration"
            ),
            notice_deadline_rule=_claim(
                "not more than twelve (12) months nor less than six (6) months prior to expiration"
            ),
        )],
        rent_schedule=[
            RentPeriod(start=_claim("2025-01-01"), end=_claim("2025-12-31"), monthly=_claim(1000.0)),
            RentPeriod(start=_claim("2026-01-01"), end=_claim("2026-12-31"), monthly=_claim(1100.0)),
        ],
    )

    result = critical_dates(lease, "2025-12-31")
    by_event = {item["event"]: item for item in result["dates"]}

    assert by_event["renew_exercise_window_open"]["date"] == "2025-12-31"
    assert by_event["renew_exercise_window_close"]["date"] == "2026-06-30"
    assert by_event["renew_notice_deadline"]["severity"] == "value_destroying"
    assert by_event["rent_step"]["severity"] == "informational"
    assert any(item["event"] == "rent_step" for item in result["horizons"]["90"])


def test_conditional_expiration_is_unresolved_not_guessed():
    lease = LeaseAbstract(dates=LeaseDates(
        expiration=_claim("the date ten years after the rent commencement date")
    ))

    result = critical_dates(lease, "2025-01-01")

    assert not result["dates"]
    assert result["unresolved"][0]["event"] == "lease_expiration"

