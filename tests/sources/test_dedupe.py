"""Tests for listing identity normalization and merge behavior."""

from cre_mcp.models import Listing, ListingRef
from cre_mcp.sources.dedupe import dedupe_key, merge_listings, normalize_address


def _listing(source: str, source_id: str, **overrides) -> Listing:
    values = {
        "source": source,
        "source_id": source_id,
        "refs": [
            ListingRef(
                source=source,
                source_id=source_id,
                url=f"https://{source}.example/{source_id}",
            )
        ],
        "name": "Downtown Office Tower",
        "address": "101 Main St",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201-1234",
        "url": f"https://{source}.example/{source_id}",
    }
    values.update(overrides)
    return Listing(**values)


def test_normalize_address_strips_suite_punctuation_and_abbreviates():
    assert normalize_address("101 Main Street, Suite #200") == "101 MAIN ST"
    assert normalize_address("101 Main St. STE 200") == "101 MAIN ST"
    assert normalize_address("101 Main Street, Ste. #200") == "101 MAIN ST"


def test_dedupe_key_uses_zip5_and_falls_back_to_name():
    listing = _listing("loopnet", "1")
    assert dedupe_key(listing) == "101 MAIN ST|DALLAS|TX|75201"

    no_address = listing.model_copy(update={"address": "", "zip_code": None})
    assert dedupe_key(no_address) == "DOWNTOWN OFFICE TOWER|DALLAS|TX"


def test_merge_uses_more_complete_listing_and_fills_gaps():
    sparse = _listing("crexi", "cx-1")
    complete = _listing(
        "loopnet",
        "ln-1",
        price="$2,000,000",
        size_sqft="10,000 SF",
        broker_company="CBRE",
    )

    merged = merge_listings(sparse, complete)

    assert merged.source == "loopnet"
    assert merged.price == "$2,000,000"
    assert merged.size_sqft == "10,000 SF"
    assert {ref.source for ref in merged.refs} == {"crexi", "loopnet"}
    assert merged.also_listed_on == ["crexi"]


def test_merge_prefers_crexi_when_completeness_is_tied():
    loopnet = _listing("loopnet", "ln-1", broker_name="LoopNet Broker")
    crexi = _listing("crexi", "cx-1", broker_name="Crexi Broker")

    merged = merge_listings(loopnet, crexi)

    assert merged.source == "crexi"
    assert merged.broker_name == "Crexi Broker"
    assert merged.also_listed_on == ["loopnet"]
