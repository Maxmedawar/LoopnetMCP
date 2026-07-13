from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from cre_mcp.http.arcgis import arcgis_query


@pytest.mark.asyncio
async def test_arcgis_query_builds_query_and_follows_pages():
    client = Mock()
    client.get_json = AsyncMock(
        side_effect=[
            {
                "features": [
                    {"attributes": {"OBJECTID": 1}},
                    {"attributes": {"OBJECTID": 2}},
                ],
                "exceededTransferLimit": True,
            },
            {
                "features": [{"attributes": {"OBJECTID": 3}}],
                "exceededTransferLimit": False,
            },
        ]
    )
    with patch("cre_mcp.http.arcgis.get_fetch_client", return_value=client):
        result = await arcgis_query(
            "https://services.arcgis.com/example/FeatureServer/0",
            where="STATE='TX'",
            out_fields="OBJECTID,STATE",
            geometry={"xmin": -100, "ymin": 30, "xmax": -99, "ymax": 31},
        )

    assert result == [{"OBJECTID": 1}, {"OBJECTID": 2}, {"OBJECTID": 3}]
    first = parse_qs(urlparse(client.get_json.await_args_list[0].args[0]).query)
    second = parse_qs(urlparse(client.get_json.await_args_list[1].args[0]).query)
    assert first["f"] == ["json"]
    assert first["where"] == ["STATE='TX'"]
    assert first["outFields"] == ["OBJECTID,STATE"]
    assert first["returnGeometry"] == ["false"]
    assert "xmin" in first["geometry"][0]
    assert first["geometryType"] == ["esriGeometryEnvelope"]
    assert second["resultOffset"] == ["2"]


@pytest.mark.asyncio
async def test_arcgis_query_honors_requested_count():
    client = Mock()
    client.get_json = AsyncMock(
        return_value={
            "features": [{"attributes": {"OBJECTID": 1}}],
            "exceededTransferLimit": True,
        }
    )
    with patch("cre_mcp.http.arcgis.get_fetch_client", return_value=client):
        result = await arcgis_query(
            "https://services.arcgis.com/example/FeatureServer/0/query",
            result_count=1,
        )
    assert result == [{"OBJECTID": 1}]
    assert client.get_json.await_count == 1
