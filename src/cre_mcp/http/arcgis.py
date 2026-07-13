"""Source-agnostic ArcGIS FeatureServer query helper."""

import json
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import get_fetch_client

_PAGE_SIZE = 2_000


async def arcgis_query(
    feature_server_url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    geometry: Any = None,
    return_geometry: bool = False,
    out_sr: int | None = None,
    result_offset: int = 0,
    result_count: int | None = None,
) -> list[dict]:
    """Return attributes from an ArcGIS layer, following transfer-limit pages."""
    base_url = feature_server_url.rstrip("/")
    if not base_url.casefold().endswith("/query"):
        base_url = f"{base_url}/query"

    attributes: list[dict] = []
    offset = max(0, result_offset)
    while True:
        remaining = None if result_count is None else result_count - len(attributes)
        if remaining is not None and remaining <= 0:
            break
        page_size = _PAGE_SIZE if remaining is None else min(_PAGE_SIZE, remaining)
        params: dict[str, str | int] = {
            "f": "json",
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        if geometry is not None:
            params["geometry"] = (
                geometry if isinstance(geometry, str) else json.dumps(geometry)
            )
            params["spatialRel"] = "esriSpatialRelIntersects"
            if isinstance(geometry, dict):
                spatial_reference = geometry.get("spatialReference")
                if isinstance(spatial_reference, dict):
                    wkid = spatial_reference.get("wkid")
                    if wkid is not None:
                        params["inSR"] = str(wkid)
                if {"xmin", "ymin", "xmax", "ymax"} <= geometry.keys():
                    params["geometryType"] = "esriGeometryEnvelope"
                elif {"x", "y"} <= geometry.keys():
                    params["geometryType"] = "esriGeometryPoint"
        if out_sr is not None:
            params["outSR"] = str(out_sr)
        payload = await get_fetch_client().get_json(
            f"{base_url}?{urlencode(params)}"
        )
        if not isinstance(payload, dict):
            raise FetchClientError("ArcGIS response must be a JSON object")
        if payload.get("error"):
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise FetchClientError(f"ArcGIS query failed: {message}")
        features = payload.get("features")
        if not isinstance(features, list):
            return attributes
        page: list[dict] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            item = feature.get("attributes")
            if isinstance(item, dict):
                if return_geometry and isinstance(feature.get("geometry"), dict):
                    item = {**item, "_geometry": feature["geometry"]}
                page.append(item)
        attributes.extend(page)
        if not payload.get("exceededTransferLimit") or not features:
            break
        offset += len(features)
    return attributes


__all__ = ["arcgis_query"]
