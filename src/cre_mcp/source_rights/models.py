"""Strict models for the packaged source-rights registry."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RightsState(str, Enum):
    PROHIBITED = "PROHIBITED"
    CONDITIONAL = "CONDITIONAL"
    CONTRACT_REQUIRED = "CONTRACT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class SourceKind(str, Enum):
    AUTOMATED = "automated"
    DIRECT_ADAPTER = "direct_adapter"
    EXTERNAL_DOCUMENT = "external_document"
    LINK_ONLY = "link_only"
    EMBEDDED = "embedded"


class EvidenceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"


class UrlRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str
    path_prefix: str = "/"
    schemes: tuple[str, ...] = ("https",)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        host = value.strip().casefold().rstrip(".")
        if not host or "://" in host or "/" in host:
            raise ValueError("URL-rule host must be a bare hostname")
        return host

    @field_validator("path_prefix")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        path = value.strip() or "/"
        if not path.startswith("/"):
            raise ValueError("URL-rule path_prefix must begin with '/'")
        return path

    @field_validator("schemes")
    @classmethod
    def validate_schemes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if not normalized or any(item not in {"http", "https"} for item in normalized):
            raise ValueError("URL-rule schemes must contain only http/https")
        return normalized


class RightsAllowances(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commercial_display: bool = False
    derived_analytics: bool = False
    ai_ml_use: bool = False
    raw_retention: bool = False
    redistribution: bool = False


class DisclosureRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attribution: tuple[str, ...] = ()
    disclaimer: tuple[str, ...] = ()
    delivery_proven: bool = False


class OperatingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delay_seconds: float = Field(ge=0, allow_inf_nan=False)
    max_concurrency: int = Field(ge=1)
    memory_cache_ttl_seconds: int = Field(ge=0)
    persistent_cache_ttl_seconds: int = Field(ge=0)
    raw_retention_ttl_seconds: int = Field(ge=0)


class SourceRightsRecord(BaseModel):
    """One fully materialized source decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_kind: SourceKind
    owner: str
    dataset: str
    method: str
    methods: tuple[str, ...]
    enabled_by_default: bool = False
    rights_state: RightsState
    hosted_cloud_allowed: bool = False
    trusted_local_only: bool = True
    official_evidence_urls: tuple[str, ...] = ()
    evidence_verified_on: date | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.PENDING
    signed_contract_required: bool = False
    contract_proof_present: bool = False
    required_proofs: tuple[str, ...] = ()
    allowances: RightsAllowances
    disclosures: DisclosureRequirements
    robots_policy: str
    api_policy: str
    operating_policy: OperatingPolicy
    query_credentials: tuple[str, ...] = ()
    raw_storage_allowed: bool = False
    raw_output_allowed: bool = False
    adapter_names: tuple[str, ...] = ()
    adapter_paths: tuple[str, ...] = ()
    url_rules: tuple[UrlRule, ...] = ()
    egress_managed_by: str | None = None
    notes: str = ""

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        normalized = value.strip().casefold()
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
        if not normalized or any(char not in allowed for char in normalized):
            raise ValueError("source_id must be a stable lowercase identifier")
        return normalized

    @field_validator("methods")
    @classmethod
    def normalize_methods(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip().upper() for item in value))
        if not normalized or any(not item.isalpha() for item in normalized):
            raise ValueError("methods must contain nonblank HTTP method names")
        return normalized

    @field_validator("owner", "dataset", "method", "robots_policy", "api_policy")
    @classmethod
    def nonblank_critical_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("critical source-rights strings cannot be blank")
        return normalized

    @field_validator("official_evidence_urls")
    @classmethod
    def validate_evidence_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw_url in value:
            url = raw_url.strip()
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(
                    "official evidence URLs must be credential-free absolute HTTPS URLs"
                )
            normalized.append(url)
        if len(set(normalized)) != len(normalized):
            raise ValueError("official evidence URLs cannot contain duplicates")
        return tuple(normalized)

    @field_validator("query_credentials")
    @classmethod
    def normalize_credentials(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip().casefold() for item in value if item.strip()))

    @field_validator("adapter_names", "adapter_paths")
    @classmethod
    def normalize_adapter_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("adapter references cannot contain blank values")
        if len(set(item.casefold() for item in normalized)) != len(normalized):
            raise ValueError("adapter references cannot contain duplicates")
        return normalized

    @model_validator(mode="after")
    def fail_closed_hosted_record(self) -> "SourceRightsRecord":
        if self.enabled_by_default:
            raise ValueError("sources may not be enabled by default")
        if self.hosted_cloud_allowed and self.trusted_local_only:
            raise ValueError(
                "a hosted-cloud source cannot also be marked trusted-local-only"
            )
        if self.raw_output_allowed and not self.allowances.redistribution:
            raise ValueError("raw output requires redistribution allowance")
        if self.raw_storage_allowed and not self.allowances.raw_retention:
            raise ValueError("raw storage requires raw-retention allowance")
        cache_ttls = (
            self.operating_policy.memory_cache_ttl_seconds,
            self.operating_policy.persistent_cache_ttl_seconds,
        )
        if any(ttl > 0 for ttl in cache_ttls) and not self.raw_storage_allowed:
            raise ValueError("raw response caching requires raw-storage allowance")
        if any(
            ttl > self.operating_policy.raw_retention_ttl_seconds
            for ttl in cache_ttls
        ):
            raise ValueError("cache TTL cannot exceed the raw-retention TTL")
        if (
            self.operating_policy.raw_retention_ttl_seconds > 0
            and not self.raw_storage_allowed
        ):
            raise ValueError("raw-retention TTL requires raw-storage allowance")
        if self.evidence_status is EvidenceStatus.APPROVED and (
            self.evidence_verified_on is None or not self.official_evidence_urls
        ):
            raise ValueError("approved evidence requires a date and official URLs")
        if self.source_kind in {SourceKind.AUTOMATED, SourceKind.DIRECT_ADAPTER}:
            if not self.adapter_paths:
                raise ValueError("network sources require at least one adapter path")
            if not self.url_rules and not (self.egress_managed_by or "").strip():
                raise ValueError(
                    "network sources require URL rules or an explicit egress delegate"
                )
        if self.source_kind in {
            SourceKind.EXTERNAL_DOCUMENT,
            SourceKind.EMBEDDED,
            SourceKind.LINK_ONLY,
        }:
            if self.url_rules:
                if self.source_kind is not SourceKind.LINK_ONLY:
                    raise ValueError(
                        "external-document and embedded records cannot authorize "
                        "URL egress"
                    )
            if (self.egress_managed_by or "").strip():
                raise ValueError(
                    "non-network records cannot delegate URL egress"
                )
        if self.hosted_cloud_allowed:
            if self.rights_state in {RightsState.PROHIBITED, RightsState.UNKNOWN}:
                raise ValueError("prohibited/unknown sources cannot be hosted")
            if (
                self.evidence_status is not EvidenceStatus.APPROVED
                or self.evidence_verified_on is None
            ):
                raise ValueError("hosted sources require approved dated evidence")
            if self.signed_contract_required and not self.contract_proof_present:
                raise ValueError("hosted contract sources require contract proof")
            if self.required_proofs:
                raise ValueError("hosted sources cannot have outstanding proof items")
            if (
                self.disclosures.attribution or self.disclosures.disclaimer
            ) and not self.disclosures.delivery_proven:
                raise ValueError("hosted conditional disclosures require delivery proof")
        return self


class SourceRightsCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    sources: tuple[SourceRightsRecord, ...] = Field(min_length=1)


__all__ = [
    "DisclosureRequirements",
    "EvidenceStatus",
    "OperatingPolicy",
    "RightsAllowances",
    "RightsState",
    "SourceKind",
    "SourceRightsCatalog",
    "SourceRightsRecord",
    "UrlRule",
]
