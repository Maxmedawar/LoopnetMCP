"""Nearest official state-DOT annual average daily traffic lookup."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from cre_mcp.cache.sqlite import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models.market import MetricValue

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6_371_008.8
_METERS_PER_DEGREE_LAT = 111_320.0
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class AadtConfig:
    """Observed ArcGIS layer schema for one state DOT."""

    arcgis_url: str
    aadt_field: str
    route_field: str
    year_field: str | None = None
    year: int | None = None
    where: str = "1=1"
    lat_field: str | None = None
    lon_field: str | None = None


# Every layer below was queried successfully on 2026-07-13. The field names are
# deliberately data, because DOT schemas and publication years change independently.
STATE_AADT_ENDPOINTS: dict[str, AadtConfig] = {
    "NC": AadtConfig(
        arcgis_url=(
            "https://services.arcgis.com/NuWFvHYDMVmmxMeM/arcgis/rest/services/"
            "NCDOT__2024_AADT_Stations_published_September_2025/FeatureServer/0"
        ),
        aadt_field="AADT_2024",
        route_field="Route",
        year=2024,
        where="AADT_2024 IS NOT NULL AND AADT_2024 <> ''",
    ),
    "AZ": AadtConfig(
        arcgis_url=(
            "https://services6.arcgis.com/clPWQMwZfdWn4MQZ/arcgis/rest/services/"
            "ADOT_2024_Average_Annual_Daily_Traffic_(AADT)/FeatureServer/0"
        ),
        aadt_field="AADT",
        route_field="RouteId",
        year_field="SubmittalYear",
    ),
    "CO": AadtConfig(
        arcgis_url=(
            "https://dtdapps.codot.gov/server/rest/services/"
            "Webapps/open_data_sde/FeatureServer/13"
        ),
        aadt_field="AADT",
        route_field="ROUTE",
        year_field="AADTYR",
    ),
    "TX": AadtConfig(
        arcgis_url=(
            "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/"
            "TxDOT_AADT_Annuals_(Public_View)/FeatureServer/0"
        ),
        aadt_field="AADT_RPT_QTY",
        route_field="ON_ROAD",
        year_field="AADT_RPT_YEAR",
    ),
    "FL": AadtConfig(
        arcgis_url="https://gis.fdot.gov/arcgis/rest/services/RCI_Layers/FeatureServer/0",
        aadt_field="AADT",
        route_field="ROADWAY",
        year_field="YEAR_",
    ),
    "CA": AadtConfig(
        arcgis_url=(
            "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/"
            "CHhighway/Traffic_AADT/FeatureServer/0"
        ),
        aadt_field="AHEAD_AADT",
        route_field="RTE",
        year=2023,
        where="AHEAD_AADT IS NOT NULL AND AHEAD_AADT <> ''",
    ),
    "NV": AadtConfig(
        arcgis_url=(
            "https://services9.arcgis.com/eNX73FDxjlKFtCtH/arcgis/rest/services/"
            "NDOT_FY2025_Streetlight_AADT_LOTTR/FeatureServer/1"
        ),
        aadt_field="TRINA_Avg_AADT",
        route_field="RouteNameFull",
        year=2025,
        where="TRINA_Avg_AADT IS NOT NULL",
    ),
    "GA": AadtConfig(
        arcgis_url=(
            "https://services2.arcgis.com/IxVN2oUE9EYLSnPE/arcgis/rest/services/"
            "GDOT_AADT/FeatureServer/1"
        ),
        aadt_field="aadt",
        route_field="description",
        where="aadt IS NOT NULL",
        lat_field="lat",
        lon_field="lng",
    ),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _point_distance_m(lat: float, lon: float, y: float, x: float) -> float:
    lat1 = math.radians(lat)
    lat2 = math.radians(y)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(x - lon)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


def _segment_distance_m(
    lat: float,
    lon: float,
    start: list[float],
    end: list[float],
) -> float:
    """Approximate a short WGS84 segment in a local metric plane."""
    scale_x = _METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))
    ax = (start[0] - lon) * scale_x
    ay = (start[1] - lat) * _METERS_PER_DEGREE_LAT
    bx = (end[0] - lon) * scale_x
    by = (end[1] - lat) * _METERS_PER_DEGREE_LAT
    dx = bx - ax
    dy = by - ay
    denominator = dx * dx + dy * dy
    if denominator <= 0:
        return math.hypot(ax, ay)
    fraction = max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
    return math.hypot(ax + fraction * dx, ay + fraction * dy)


def _geometry_distance_m(lat: float, lon: float, geometry: Any) -> float | None:
    if not isinstance(geometry, dict):
        return None
    x = _number(geometry.get("x"))
    y = _number(geometry.get("y"))
    if x is not None and y is not None:
        return _point_distance_m(lat, lon, y, x)
    paths = geometry.get("paths")
    distances: list[float] = []
    if isinstance(paths, list):
        for path in paths:
            if not isinstance(path, list):
                continue
            points = [point for point in path if isinstance(point, list) and len(point) >= 2]
            for point in points:
                distances.append(_point_distance_m(lat, lon, point[1], point[0]))
            for start, end in zip(points, points[1:], strict=False):
                distances.append(_segment_distance_m(lat, lon, start, end))
    return min(distances) if distances else None


class TrafficProvider:
    """Select a state layer and return the closest AADT observation in range."""

    def __init__(
        self,
        state: str,
        *,
        cache: SQLiteCache | None = None,
        endpoints: dict[str, AadtConfig] | None = None,
        config: CreConfig | None = None,
    ):
        self.state = state.upper().strip()
        self.endpoints = endpoints or STATE_AADT_ENDPOINTS
        config = config or CreConfig()
        self.cache = cache or SQLiteCache(
            config.cache_db_path,
            ttl_seconds=_CACHE_TTL_SECONDS,
        )

    async def nearest_aadt(
        self,
        lat: float,
        lon: float,
        *,
        radius_m: int = 250,
    ) -> MetricValue | None:
        """Return the nearest official AADT count, or None when unavailable."""
        endpoint = self.endpoints.get(self.state)
        if endpoint is None or radius_m <= 0:
            return None
        cache_key = (
            f"traffic:v1:{self.state}:{lat:.5f}:{lon:.5f}:{int(radius_m)}"
        )
        cached = await self.cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("found") is False:
            return None
        if isinstance(cached, dict) and isinstance(cached.get("metric"), dict):
            return MetricValue.model_validate(cached["metric"])

        latitude_delta = radius_m / _METERS_PER_DEGREE_LAT
        longitude_scale = max(
            _METERS_PER_DEGREE_LAT * abs(math.cos(math.radians(lat))),
            1.0,
        )
        longitude_delta = radius_m / longitude_scale
        geometry = {
            "xmin": lon - longitude_delta,
            "ymin": lat - latitude_delta,
            "xmax": lon + longitude_delta,
            "ymax": lat + latitude_delta,
            "spatialReference": {"wkid": 4326},
        }
        fields = [endpoint.aadt_field, endpoint.route_field]
        if endpoint.year_field:
            fields.append(endpoint.year_field)
        if endpoint.lat_field:
            fields.append(endpoint.lat_field)
        if endpoint.lon_field:
            fields.append(endpoint.lon_field)
        where = endpoint.where
        query_geometry: dict[str, Any] | None = geometry
        return_geometry = True
        if endpoint.lat_field and endpoint.lon_field:
            where = (
                f"({where}) AND {endpoint.lat_field} >= {geometry['ymin']} AND "
                f"{endpoint.lat_field} <= {geometry['ymax']} AND "
                f"{endpoint.lon_field} >= {geometry['xmin']} AND "
                f"{endpoint.lon_field} <= {geometry['xmax']}"
            )
            query_geometry = None
            return_geometry = False
        features = await arcgis_query(
            endpoint.arcgis_url,
            where=where,
            out_fields=",".join(fields),
            geometry=query_geometry,
            return_geometry=return_geometry,
            out_sr=4326,
            result_count=500,
        )
        candidates: list[tuple[float, dict[str, Any]]] = []
        for feature in features:
            aadt = _number(feature.get(endpoint.aadt_field))
            feature_geometry = feature.get("_geometry")
            if (
                feature_geometry is None
                and endpoint.lat_field
                and endpoint.lon_field
            ):
                feature_geometry = {
                    "x": feature.get(endpoint.lon_field),
                    "y": feature.get(endpoint.lat_field),
                }
            distance = _geometry_distance_m(lat, lon, feature_geometry)
            if aadt is None or aadt < 0 or distance is None or distance > radius_m:
                continue
            candidates.append((distance, feature))
        if not candidates:
            await self.cache.set(cache_key, {"found": False})
            return None

        _, nearest = min(candidates, key=lambda item: item[0])
        aadt = _number(nearest.get(endpoint.aadt_field))
        year_value = (
            nearest.get(endpoint.year_field) if endpoint.year_field else endpoint.year
        )
        route = nearest.get(endpoint.route_field)
        source = f"{self.state} DOT AADT"
        if route not in (None, ""):
            source = f"{source} ({route})"
        metric = MetricValue(
            value=aadt,
            unit="vehicles/day",
            as_of=str(year_value) if year_value not in (None, "") else None,
            source=source,
        )
        await self.cache.set(
            cache_key,
            {"found": True, "metric": metric.model_dump(mode="json")},
        )
        return metric


async def nearest_aadt(
    lat: float,
    lon: float,
    *,
    state: str,
    radius_m: int = 250,
) -> MetricValue | None:
    """Convenience wrapper around the state-selected provider."""
    try:
        return await TrafficProvider(state).nearest_aadt(
            lat,
            lon,
            radius_m=radius_m,
        )
    except Exception as exc:
        logger.warning("Traffic enrichment unavailable for %s: %s", state, exc)
        return None


__all__ = ["AadtConfig", "STATE_AADT_ENDPOINTS", "TrafficProvider", "nearest_aadt"]
