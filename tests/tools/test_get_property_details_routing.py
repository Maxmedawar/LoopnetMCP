"""get_property_details must route to the correct source (bug: always LoopNet)."""

import pytest

from cre_mcp.models.listings import Listing
from cre_mcp.tools import listing_tools


class _FakeSource:
    def __init__(self, captured):
        self._captured = captured

    async def get_detail(self, ref):
        self._captured["source"] = ref.source
        self._captured["source_id"] = ref.source_id
        self._captured["url"] = ref.url
        return Listing(
            source=ref.source, source_id=ref.source_id, name="X",
            address="1 Main", city="Austin", state="TX", url=ref.url or "http://x",
        )


@pytest.fixture
def captured(monkeypatch):
    box: dict = {}
    monkeypatch.setattr(listing_tools.registry, "get", lambda name: _FakeSource(box))
    return box


@pytest.mark.asyncio
async def test_source_prefixed_id_routes_to_crexi(captured):
    await listing_tools.get_property_details("crexi:2335936")
    assert captured["source"] == "crexi"
    assert captured["source_id"] == "2335936"
    assert "loopnet.com" not in (captured["url"] or "")


@pytest.mark.asyncio
async def test_crexi_url_infers_source_and_id(captured):
    await listing_tools.get_property_details("https://www.crexi.com/properties/2335936")
    assert captured["source"] == "crexi"
    assert captured["source_id"] == "2335936"


@pytest.mark.asyncio
async def test_explicit_source_param_for_bare_id(captured):
    await listing_tools.get_property_details("2335936", source="crexi")
    assert captured["source"] == "crexi"
    assert captured["source_id"] == "2335936"


@pytest.mark.asyncio
async def test_bare_id_still_defaults_to_loopnet(captured):
    await listing_tools.get_property_details("12345678")
    assert captured["source"] == "loopnet"
    assert "loopnet.com" in (captured["url"] or "")
