"""Request and response mapping for Crexi's listing API."""

import html
import logging
import re
from typing import Any

from cre_mcp.models import Listing, ListingRef, ListingType, PropertyType
from cre_mcp.sources.base import SearchQuery
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)

CREXI_PROPERTY_TYPE_MAP: dict[PropertyType, list[str]] = {
    PropertyType.OFFICE: ["Office"],
    PropertyType.RETAIL: ["Retail"],
    PropertyType.INDUSTRIAL: ["Industrial"],
    PropertyType.MULTIFAMILY: ["Multifamily"],
    PropertyType.LAND: ["Land"],
    PropertyType.HOSPITALITY: ["Hospitality"],
    PropertyType.SPECIAL_PURPOSE: ["Special Purpose"],
    PropertyType.HEALTH_CARE: ["Health Care"],
}

# Crexi calls its sale and lease search platforms "Sales" and "Lease".
CREXI_LISTING_TYPE_MAP: dict[ListingType, list[str]] = {
    ListingType.FOR_SALE: ["Sales"],
    ListingType.FOR_LEASE: ["Lease"],
}

_SEARCH_PAGE_SIZE = 60
_ACTIVE_SALE_STATUSES = [
    "On-Market",
    "Auction",
    "Highest & Best",
    "Call For Offers",
]
_KNOWN_ASSET_KEYS = {
    "activatedOn",
    "askingPrice",
    "brokerName",
    "brokerOfRecordLicense",
    "brokerOfRecordName",
    "brokerTeamLogoUrl",
    "brokerageName",
    "capRate",
    "description",
    "details",
    "fullBrokerageAddress",
    "hasFlyer",
    "hasOM",
    "hasVideo",
    "hasVirtualTour",
    "id",
    "investmentHighlights",
    "investmentType",
    "isInOpportunityZone",
    "isNew",
    "locations",
    "marketingDescription",
    "name",
    "noi",
    "numberOfGalleryItems",
    "numberOfImages",
    "numberOfUnits",
    "pricePerAcreLand",
    "showCountdownAsDate",
    "squareFootage",
    "status",
    "stories",
    "subtypes",
    "summaryDetails",
    "thumbnailUrl",
    "types",
    "units",
    "updatedOn",
    "urlSlug",
    "userIsAssetOwner",
    "yearBuilt",
}
_KNOWN_UNIVERSAL_KEYS = {
    "address",
    "auction",
    "brokers",
    "constructionYear",
    "description",
    "documentType",
    "financials",
    "gallery",
    "hasCrexiFlyer",
    "id",
    "investmentType",
    "listingAttributes",
    "lotAttributes",
    "matchedLeaseIds",
    "matches",
    "propertyAttributes",
    "propertyName",
    "propertyPrice",
    "recordType",
    "tenancy",
    "updatedOn",
    "urlSlug",
}


def _plain_filter(values: list[Any]) -> dict[str, Any]:
    return {
        "mode": "Include",
        "structuredValues": values,
        "type": "Plain",
        "values": [],
    }


def _range_filter(minimum: int | None, maximum: int | None) -> dict[str, Any]:
    bounds = {
        key: value
        for key, value in (("min", minimum), ("max", maximum))
        if value is not None
    }
    return _plain_filter([bounds])


def build_search_body(query: SearchQuery) -> dict[str, Any]:
    """Map normalized criteria to Crexi's live universal-search payload."""
    filters: dict[str, Any] = {
        "address": _plain_filter([query.location]),
    }
    if query.listing_type == ListingType.FOR_SALE:
        filters["searchAttributes.status"] = _plain_filter(
            _ACTIVE_SALE_STATUSES
        )
    if query.property_type is not None:
        filters["propertyAttributes.type"] = _plain_filter(
            CREXI_PROPERTY_TYPE_MAP[query.property_type]
        )
    if query.price_min is not None or query.price_max is not None:
        filters["propertyPrice.total"] = _range_filter(
            query.price_min,
            query.price_max,
        )
    if query.size_min is not None or query.size_max is not None:
        filters["propertyAttributes.buildingSqft"] = _range_filter(
            query.size_min,
            query.size_max,
        )

    body: dict[str, Any] = {
        "excludeFilters": [],
        "excludeSort": [],
        "filters": filters,
        "from": (max(query.page, 1) - 1) * _SEARCH_PAGE_SIZE,
        "ids": [],
        "searchTypes": CREXI_LISTING_TYPE_MAP[query.listing_type],
        "size": _SEARCH_PAGE_SIZE,
        "sorting": {"searchAttributes.crexiSearchRank": "Descending"},
    }
    return body


def build_id_search_body(source_id: str) -> dict[str, Any]:
    """Build the live universal-search request used to recover listing-broker data."""
    normalized = source_id.removeprefix("sales-")
    return {
        "excludeFilters": [],
        "excludeSort": [],
        "filters": {},
        "from": 0,
        "ids": [f"sales-{normalized}"],
        "searchTypes": ["Sales"],
        "size": 1,
        "sorting": {"searchAttributes.crexiSearchRank": "Descending"},
    }


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?[\d,.]+", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None else None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _summary_details(asset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    raw_details = asset.get("summaryDetails")
    if not isinstance(raw_details, list):
        return details
    for item in raw_details:
        if isinstance(item, dict) and item.get("key"):
            details[str(item["key"]).lower()] = item
    return details


def _coalesce(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _summary_value(
    details: dict[str, dict[str, Any]],
    key: str,
) -> Any:
    item = details.get(key.lower(), {})
    return item.get("value")


def _summary_display(
    details: dict[str, dict[str, Any]],
    key: str,
) -> str | None:
    item = details.get(key.lower(), {})
    return _as_text(item.get("display"))


def _plain_text(value: Any) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip() or None


def _highlights(value: Any) -> list[str]:
    text = _as_text(value)
    if text is None:
        return []
    list_items = re.findall(r"<li[^>]*>(.*?)</li>", text, flags=re.I | re.S)
    if list_items:
        return [item for raw in list_items if (item := _plain_text(raw))]
    plain = _plain_text(text)
    return [plain] if plain else []


def _format_money(value: float | None) -> str | None:
    if value is None:
        return None
    return f"${value:,.0f}"


def _format_number(value: float | None, suffix: str) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f} {suffix}"


def _format_percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:g}%"


def _map_legacy_asset(asset: dict[str, Any]) -> Listing:
    """Map the still-live legacy asset/search and asset-detail shapes."""
    unknown_keys = sorted(set(asset) - _KNOWN_ASSET_KEYS)
    if unknown_keys:
        logger.debug(
            "Crexi asset schema has unrecognized keys: %s",
            safe_error_message(unknown_keys, source="crexi"),
        )

    locations = asset.get("locations")
    location = locations[0] if isinstance(locations, list) and locations else {}
    if not isinstance(location, dict):
        location = {}
    state_value = location.get("state")
    if isinstance(state_value, dict):
        state = _as_text(state_value.get("code") or state_value.get("name"))
    else:
        state = _as_text(state_value)

    details = _summary_details(asset)
    types = _list_of_text(
        _coalesce(asset.get("types"), _summary_value(details, "PropertyType"))
    )
    subtypes = _list_of_text(
        _coalesce(asset.get("subtypes"), _summary_value(details, "SubType"))
    )
    source_id = _as_text(asset.get("id")) or _as_text(asset.get("urlSlug")) or "unknown"
    slug = _as_text(asset.get("urlSlug"))
    url = f"https://www.crexi.com/properties/{source_id}"
    if slug:
        url = f"{url}/{slug}"

    price_usd = _as_float(
        _coalesce(asset.get("askingPrice"), _summary_value(details, "AskingPrice"))
    )
    size_sqft = _as_float(
        _coalesce(asset.get("squareFootage"), _summary_value(details, "SquareFootage"))
    )
    cap_rate = _as_float(
        _coalesce(asset.get("capRate"), _summary_value(details, "CapRate"))
    )
    noi_usd = _as_float(
        _coalesce(asset.get("noi"), _summary_value(details, "Noi"))
    )
    units = _as_int(
        _coalesce(
            asset.get("units"),
            asset.get("numberOfUnits"),
            _summary_value(details, "Units"),
        )
    )
    year_built = _as_int(
        _coalesce(asset.get("yearBuilt"), _summary_value(details, "YearBuilt"))
    )
    stories = _as_int(
        _coalesce(asset.get("stories"), _summary_value(details, "Stories"))
    )
    lot_size = _summary_display(details, "LotSize")
    if lot_size:
        lot_size = f"{lot_size} acres"

    image_url = _as_text(asset.get("thumbnailUrl"))
    description = _plain_text(
        asset.get("marketingDescription") or asset.get("description")
    )
    name = _as_text(asset.get("name")) or _as_text(location.get("address")) or "Unknown"
    address = _as_text(location.get("address")) or ""
    city = _as_text(location.get("city")) or ""

    return Listing(
        source="crexi",
        source_id=source_id,
        refs=[ListingRef(source="crexi", source_id=source_id, url=url)],
        name=name,
        address=address,
        city=city,
        state=state or "",
        zip_code=_as_text(location.get("zip")),
        property_type=", ".join(types) or None,
        property_subtype=", ".join(subtypes) or None,
        listing_type=ListingType.FOR_SALE.value,
        price=_summary_display(details, "AskingPrice") or _format_money(price_usd),
        price_per_sqft=_summary_display(details, "PriceSqFt"),
        cap_rate=_summary_display(details, "CapRate") or _format_percent(cap_rate),
        noi=_summary_display(details, "Noi") or _format_money(noi_usd),
        size_sqft=_summary_display(details, "SquareFootage")
        or _format_number(size_sqft, "SF"),
        lot_size=lot_size,
        year_built=str(year_built) if year_built is not None else None,
        zoning=_summary_display(details, "PermittedZoning"),
        parking=_summary_display(details, "ParkingSpots"),
        stories=stories,
        units=units,
        description=description,
        highlights=_highlights(asset.get("investmentHighlights")),
        images=[image_url] if image_url else [],
        image_url=image_url,
        broker_name=_as_text(
            _coalesce(asset.get("brokerName"), asset.get("brokerOfRecordName"))
        ),
        broker_company=_as_text(asset.get("brokerageName")),
        url=url,
        last_updated=_as_text(asset.get("updatedOn")),
        price_usd=price_usd,
        size_sqft_num=size_sqft,
        cap_rate_pct=cap_rate,
        noi_usd=noi_usd,
        year_built_int=year_built,
        lat=_as_float(location.get("latitude")),
        lon=_as_float(location.get("longitude")),
        raw=asset,
    )


def _universal_source_id(value: Any) -> str:
    source_id = _as_text(value) or "unknown"
    prefix, separator, remainder = source_id.partition("-")
    if separator and prefix.lower() in {"sales", "lease"} and remainder:
        return remainder
    return source_id


def _map_universal_asset(asset: dict[str, Any]) -> Listing:
    """Map the current ``universal-search/v2`` item shape."""
    unknown_keys = sorted(set(asset) - _KNOWN_UNIVERSAL_KEYS)
    if unknown_keys:
        logger.debug(
            "Crexi universal-search schema has unrecognized keys: %s",
            safe_error_message(unknown_keys, source="crexi"),
        )

    addresses = asset.get("address")
    address_data = addresses[0] if isinstance(addresses, list) and addresses else {}
    if not isinstance(address_data, dict):
        address_data = {}
    coordinate = address_data.get("location")
    if not isinstance(coordinate, dict):
        coordinate = {}

    price_data = asset.get("propertyPrice")
    if not isinstance(price_data, dict):
        price_data = {}
    financials = asset.get("financials")
    if not isinstance(financials, dict):
        financials = {}
    attributes = asset.get("propertyAttributes")
    if not isinstance(attributes, dict):
        attributes = {}
    construction = asset.get("constructionYear")
    if not isinstance(construction, dict):
        construction = {}
    lot = asset.get("lotAttributes")
    if not isinstance(lot, dict):
        lot = {}
    gallery = asset.get("gallery")
    if not isinstance(gallery, dict):
        gallery = {}
    listing_attributes = asset.get("listingAttributes")
    if not isinstance(listing_attributes, dict):
        listing_attributes = {}

    brokers = asset.get("brokers")
    broker = brokers[0] if isinstance(brokers, list) and brokers else {}
    if not isinstance(broker, dict):
        broker = {}

    source_id = _universal_source_id(asset.get("id"))
    slug = _as_text(asset.get("urlSlug"))
    document_type = (_as_text(asset.get("documentType")) or "Sales").lower()
    listing_type = (
        ListingType.FOR_LEASE.value
        if document_type == "lease"
        else ListingType.FOR_SALE.value
    )
    route_prefix = "lease/properties" if listing_type == "for-lease" else "properties"
    url = f"https://www.crexi.com/{route_prefix}/{source_id}"
    if slug:
        url = f"{url}/{slug}"

    price_usd = _as_float(price_data.get("total"))
    price_per_sqft = _as_float(price_data.get("perSqft"))
    size_sqft = _as_float(attributes.get("buildingSqft"))
    cap_rate = _as_float(financials.get("capRatePercent"))
    noi_usd = _as_float(financials.get("netOperatingIncome"))
    year_built = _as_int(construction.get("built"))
    units = _as_int(
        _coalesce(
            attributes.get("unitsCount"),
            attributes.get("keysCount"),
        )
    )
    images = _list_of_text(gallery.get("thumbnailUrls"))

    lot_size: str | None = None
    lot_acres = _as_float(lot.get("sizeAcre"))
    lot_sqft = _as_float(lot.get("sizeSqft"))
    if lot_acres is not None:
        lot_size = f"{lot_acres:g} acres"
    elif lot_sqft is not None:
        lot_size = _format_number(lot_sqft, "SF")

    property_type = _as_text(attributes.get("type"))
    property_subtype = _as_text(attributes.get("subType"))
    name = (
        _as_text(asset.get("propertyName"))
        or _as_text(address_data.get("streetAddress"))
        or "Unknown"
    )

    return Listing(
        source="crexi",
        source_id=source_id,
        refs=[ListingRef(source="crexi", source_id=source_id, url=url)],
        name=name,
        address=_as_text(address_data.get("streetAddress")) or "",
        city=_as_text(address_data.get("city")) or "",
        state=_as_text(address_data.get("stateCode")) or "",
        zip_code=_as_text(address_data.get("zip")),
        property_type=property_type,
        property_subtype=property_subtype,
        listing_type=listing_type,
        price=_format_money(price_usd),
        price_per_sqft=(
            f"${price_per_sqft:,.2f}"
            if price_per_sqft is not None
            else None
        ),
        cap_rate=_format_percent(cap_rate),
        noi=_format_money(noi_usd),
        size_sqft=_format_number(size_sqft, "SF"),
        lot_size=lot_size,
        year_built=str(year_built) if year_built is not None else None,
        building_class=_as_text(attributes.get("classType")),
        stories=_as_int(attributes.get("storiesCount")),
        units=units,
        description=_plain_text(asset.get("description")),
        images=images,
        image_url=images[0] if images else None,
        broker_name=_as_text(broker.get("name")),
        broker_company=_as_text(broker.get("brokerage")),
        url=url,
        last_updated=_as_text(
            listing_attributes.get("dateUpdated") or asset.get("updatedOn")
        ),
        price_usd=price_usd,
        size_sqft_num=size_sqft,
        cap_rate_pct=cap_rate,
        noi_usd=noi_usd,
        year_built_int=year_built,
        lat=_as_float(coordinate.get("lat")),
        lon=_as_float(coordinate.get("lon")),
        raw=asset,
    )


def map_asset(asset: dict[str, Any]) -> Listing:
    """Tolerantly map current search items and legacy detail assets."""
    if "propertyName" in asset or "documentType" in asset:
        return _map_universal_asset(asset)
    return _map_legacy_asset(asset)
