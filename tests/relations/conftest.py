"""Fixtures shared by relationship-intelligence tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cre_mcp.models.listings import Listing


@pytest.fixture
def listing_factory() -> Callable[..., Listing]:
    def make(
        source_id: str,
        *,
        name: str | None = None,
        city: str = "Austin",
        state: str = "TX",
        property_type: str = "retail",
        broker_name: str | None = None,
        broker_company: str | None = None,
    ) -> Listing:
        return Listing(
            source="crexi",
            source_id=source_id,
            name=name or f"Deal {source_id}",
            address=f"{source_id} Congress Avenue",
            city=city,
            state=state,
            property_type=property_type,
            listing_type="for-sale",
            broker_name=broker_name,
            broker_company=broker_company,
            url=f"https://example.test/{source_id}",
        )

    return make
