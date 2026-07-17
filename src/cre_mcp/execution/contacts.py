"""Free-first broker, assessor-owner, and public business-registry contacts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from cre_mcp.config import CreConfig
from cre_mcp.enrichment.owner import entity_type as classify_entity
from cre_mcp.enrichment.owner import normalize_owner_name
from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import (
    BrokerContact,
    BusinessPrincipal,
    ContactInfo,
    RegisteredAgentContact,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SosEndpoint:
    """Public state business-search configuration and automation status."""

    state: str
    agency: str
    public_search_url: str
    adapter: str | None = None
    note: str | None = None


STATE_SOS_ENDPOINTS: dict[str, SosEndpoint] = {
    "TX": SosEndpoint(
        state="TX",
        agency="Texas Comptroller / Secretary of State public record",
        public_search_url="https://mycpa.cpa.state.tx.us/coa/",
        adapter="tx_comptroller_json",
        note="Stable official JSON search and detail responses confirmed live.",
    ),
    "AZ": SosEndpoint(
        state="AZ",
        agency="Arizona Corporation Commission",
        public_search_url="https://ecorpuatonline.azcc.gov/EntitySearch/Index",
        note="Public search is session-bound; no stable automated API was confirmed.",
    ),
    "NV": SosEndpoint(
        state="NV",
        agency="Nevada Secretary of State",
        public_search_url="https://esos.nv.gov/EntitySearch/OnlineEntitySearch",
        note="Public search presented an Incapsula automation challenge.",
    ),
    "FL": SosEndpoint(
        state="FL",
        agency="Florida Division of Corporations",
        public_search_url=(
            "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName"
        ),
        note="Public search presented a Cloudflare automation challenge.",
    ),
    "GA": SosEndpoint(
        state="GA",
        agency="Georgia Secretary of State",
        public_search_url="https://ecorp.sos.ga.gov/businesssearch",
        note="Public search presented a Cloudflare automation challenge.",
    ),
}

_TX_API = "https://comptroller.texas.gov/data-search/franchise-tax"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _address(data: dict[str, Any], prefix: str) -> str | None:
    pieces = [
        _text(data.get(f"{prefix}Street")),
        _text(data.get(f"{prefix}City")),
        _text(data.get(f"{prefix}State")),
        _text(data.get(f"{prefix}Zip")),
    ]
    return ", ".join(piece for piece in pieces if piece) or None


def _officer_address(row: dict[str, Any]) -> str | None:
    return ", ".join(
        piece
        for piece in (
            _text(row.get("AD_STR_POB_TX")),
            _text(row.get("CITY_NM")),
            _text(row.get("ST_CD")),
            _text(row.get("AD_ZP")),
        )
        if piece
    ) or None


def _normalize_match(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


class SosLookup:
    """Resolve registered agents through configured public state registries."""

    def __init__(self, fetch: FetchClient | None = None):
        self.fetch = fetch or get_fetch_client()

    async def registered_agent(
        self,
        state: str,
        entity_name: str,
    ) -> RegisteredAgentContact | None:
        endpoint = STATE_SOS_ENDPOINTS.get(state.upper())
        if endpoint is None:
            logger.info("No public business-search configuration for state %s", state)
            return None
        if endpoint.adapter != "tx_comptroller_json":
            logger.info(
                "%s business registry is a graceful automation gap: %s",
                state.upper(),
                endpoint.note,
            )
            return None
        return await self._texas_registered_agent(entity_name, endpoint)

    async def _texas_registered_agent(
        self,
        entity_name: str,
        endpoint: SosEndpoint,
    ) -> RegisteredAgentContact | None:
        search = await self.fetch.get_json(f"{_TX_API}?name={quote(entity_name)}")
        rows = search.get("data", []) if isinstance(search, dict) else []
        if not isinstance(rows, list):
            return None
        wanted = _normalize_match(entity_name)
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and _normalize_match(str(row.get("name", ""))) == wanted
        ]
        if not matches:
            return None
        taxpayer_id = _text(matches[0].get("taxpayerId"))
        if taxpayer_id is None:
            return None
        payload = await self.fetch.get_json(f"{_TX_API}/{quote(taxpayer_id)}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        agent_name = _text(data.get("registeredAgentName"))
        if agent_name is None:
            return None
        principals: list[BusinessPrincipal] = []
        seen: set[tuple[str, str | None]] = set()
        officers = data.get("officerInfo")
        if isinstance(officers, list):
            for row in officers:
                if not isinstance(row, dict) or not _text(row.get("AGNT_NM")):
                    continue
                name = str(row["AGNT_NM"]).strip()
                title = _text(row.get("AGNT_TITL_TX"))
                key = (name, title)
                if key in seen:
                    continue
                seen.add(key)
                principals.append(
                    BusinessPrincipal(
                        name=name,
                        title=title,
                        address=_officer_address(row),
                    )
                )
        return RegisteredAgentContact(
            name=agent_name,
            address=_address(data, "registeredOfficeAddress"),
            entity_name=_text(data.get("name")),
            state="TX",
            status=_text(data.get("sosRegistrationStatus")),
            principals=principals,
            source_url=endpoint.public_search_url,
        )


class SkiptraceProvider(Protocol):
    """Optional paid contact-data provider boundary."""

    @property
    def available(self) -> bool: ...

    async def lookup(self, ctx: DealContext) -> tuple[list[str], list[str]]: ...


class RealEstateApiSkiptraceProvider:
    """Optional RealEstateAPI v2 skip-trace adapter; never required."""

    endpoint = "https://api.realestateapi.com/v2/SkipTrace"

    def __init__(
        self,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
    ):
        self.config = config or CreConfig()
        self.fetch = fetch or get_fetch_client()

    @property
    def available(self) -> bool:
        return self.config.skiptrace_api_key is not None

    async def lookup(self, ctx: DealContext) -> tuple[list[str], list[str]]:
        key = self.config.skiptrace_api_key
        if key is None:
            raise ProviderUnavailableError("CRE_SKIPTRACE_API_KEY is not configured")
        body: dict[str, Any] = {
            "address": ctx.listing.address,
            "city": ctx.listing.city,
            "state": ctx.listing.state,
            "zip": ctx.listing.zip_code,
        }
        owner = ctx.parcel.owner_name if ctx.parcel else None
        if owner:
            body["last_name"] = owner
        payload = await self.fetch.post_json(
            self.endpoint,
            {key: value for key, value in body.items() if value},
            headers={"x-api-key": key.get_secret_value()},
        )
        return _skiptrace_contacts(payload)


def _skiptrace_contacts(payload: Any) -> tuple[list[str], list[str]]:
    """Tolerantly collect v2 phone/email results without depending on one schema."""
    phones: list[str] = []
    emails: list[str] = []

    def walk(value: Any, parent: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.casefold()
                if normalized in {"phone", "phone_number", "phonenumber"}:
                    if text := _text(item):
                        phones.append(text)
                elif normalized in {"email", "email_address", "emailaddress"}:
                    if text := _text(item):
                        emails.append(text)
                else:
                    walk(item, normalized)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent)
        elif parent in {"phones", "emails"}:
            if text := _text(value):
                (phones if parent == "phones" else emails).append(text)

    walk(payload)
    return _dedupe(phones), _dedupe(emails)


def _raw_contact(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if text := _text(raw.get(key)):
            return text
    return None


def _broker(ctx: DealContext) -> BrokerContact | None:
    listing = ctx.listing
    raw = listing.raw
    contact = BrokerContact(
        name=listing.broker_name
        or _raw_contact(raw, "brokerName", "broker_name", "contactName"),
        company=listing.broker_company
        or _raw_contact(raw, "brokerageName", "broker_company", "companyName"),
        phone=listing.broker_phone
        or _raw_contact(raw, "brokerPhone", "broker_phone", "phone"),
        email=_raw_contact(
            raw,
            "brokerEmail",
            "broker_email",
            "contactEmail",
            "email",
        ),
    )
    return contact if any((contact.name, contact.company, contact.phone, contact.email)) else None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result


async def find_contact(
    ctx: DealContext,
    *,
    sos: SosLookup | None = None,
    skiptrace: SkiptraceProvider | None = None,
    config: CreConfig | None = None,
) -> ContactInfo:
    """Assemble listing, assessor, registry, and optional paid contact facts."""
    broker = _broker(ctx)
    parcel = ctx.parcel
    owner_name = parcel.owner_name if parcel else None
    owner_mailing = parcel.owner_mailing_address if parcel else None
    owner_type = classify_entity(owner_name) if owner_name else None
    sources: list[str] = []
    phones: list[str] = []
    emails: list[str] = []
    if broker is not None:
        sources.append(f"{ctx.listing.source} listing broker")
        if broker.phone:
            phones.append(broker.phone)
        if broker.email:
            emails.append(broker.email)
    if owner_name or owner_mailing:
        sources.append("county assessor parcel record")

    agent: RegisteredAgentContact | None = None
    if owner_name and owner_type == "llc":
        endpoint = STATE_SOS_ENDPOINTS.get(ctx.listing.state.upper())
        try:
            agent = await (sos or SosLookup()).registered_agent(
                ctx.listing.state,
                normalize_owner_name(owner_name),
            )
        except Exception as exc:
            logger.warning(
                "Business-registry lookup failed for %s in %s: %s",
                owner_name,
                ctx.listing.state,
                exc,
            )
        if agent is not None and endpoint is not None:
            sources.append(endpoint.agency)

    selected_config = config or CreConfig()
    provider = skiptrace or RealEstateApiSkiptraceProvider(selected_config)
    skiptrace_available = provider.available
    if skiptrace_available:
        try:
            paid_phones, paid_emails = await provider.lookup(ctx)
            phones.extend(paid_phones)
            emails.extend(paid_emails)
            if paid_phones or paid_emails:
                sources.append("optional paid skip-trace provider")
        except ProviderUnavailableError:
            skiptrace_available = False
        except Exception as exc:
            logger.warning("Optional skip-trace lookup failed: %s", exc)

    return ContactInfo(
        broker=broker,
        owner_name=owner_name,
        owner_mailing=owner_mailing,
        entity_type=owner_type,
        registered_agent=agent,
        phones=_dedupe(phones),
        emails=_dedupe(emails),
        sources=sources,
        skiptrace_available=skiptrace_available,
        disclaimer=execution_guardrail(
            "confirm every name, phone, email, mailing address, and agency record "
            "before outreach; honor do-not-call, anti-spam, and solicitation rules."
        ),
    )


__all__ = [
    "RealEstateApiSkiptraceProvider",
    "STATE_SOS_ENDPOINTS",
    "SkiptraceProvider",
    "SosEndpoint",
    "SosLookup",
    "find_contact",
]
