"""Load and resolve the canonical source-rights catalog."""

from __future__ import annotations

import json
import posixpath
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from cre_mcp.source_rights.models import SourceRightsCatalog, SourceRightsRecord

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("registry.json")


def _canonical_path(value: str) -> str | None:
    """Model the path normalization an HTTP origin or proxy can perform."""
    decoded = value or "/"
    for _ in range(4):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        return None
    if "\x00" in decoded or "\\" in decoded:
        return None
    trailing_slash = decoded.endswith("/")
    normalized = posixpath.normpath("/" + decoded.lstrip("/"))
    if trailing_slash and normalized != "/":
        normalized += "/"
    return normalized


def _path_matches(path: str, prefix: str) -> bool:
    canonical_path = _canonical_path(path)
    canonical_prefix = _canonical_path(prefix)
    if canonical_path is None or canonical_prefix is None:
        return False
    if canonical_prefix == "/":
        return True
    if canonical_prefix.endswith("/"):
        return canonical_path.startswith(canonical_prefix)
    return canonical_path == canonical_prefix or canonical_path.startswith(
        canonical_prefix + "/"
    )


def _has_safe_authority(url: str) -> bool:
    """Return whether a registry URL uses credential-free default HTTP ports."""
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if scheme == "https":
        return port in {None, 443}
    if scheme == "http":
        return port in {None, 80}
    return False


class SourceRightsRegistryError(ValueError):
    """The rights catalog is invalid or cannot classify an operation."""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class SourceRightsRegistry:
    """Immutable strict registry with URL and adapter-name resolution."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_REGISTRY_PATH).expanduser().resolve()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceRightsRegistryError(
                f"source-rights registry could not be loaded: {self.path}"
            ) from exc
        if not isinstance(raw, dict):
            raise SourceRightsRegistryError("source-rights registry root must be an object")
        unexpected_root_keys = set(raw) - {"schema_version", "defaults", "sources"}
        if unexpected_root_keys:
            raise SourceRightsRegistryError(
                "source-rights registry has unexpected root keys: "
                + ", ".join(sorted(unexpected_root_keys))
            )
        if raw.get("schema_version") != 1:
            raise SourceRightsRegistryError(
                "source-rights registry schema version must be 1"
            )
        defaults = raw.get("defaults")
        entries = raw.get("sources")
        if not isinstance(defaults, dict) or not isinstance(entries, list):
            raise SourceRightsRegistryError(
                "source-rights registry requires object defaults and list sources"
            )
        if any(not isinstance(item, dict) for item in entries):
            raise SourceRightsRegistryError(
                "source-rights registry source entries must be objects"
            )
        materialized = [_deep_merge(defaults, item) for item in entries]
        try:
            self.catalog = SourceRightsCatalog.model_validate(
                {"schema_version": raw.get("schema_version"), "sources": materialized}
            )
        except Exception as exc:
            raise SourceRightsRegistryError("source-rights registry schema is invalid") from exc

        self._by_id: dict[str, SourceRightsRecord] = {}
        self._by_adapter: dict[str, SourceRightsRecord] = {}
        self._known_hosts: set[str] = set()
        path_owners: dict[str, list[SourceRightsRecord]] = {}
        url_owners: dict[tuple[str, str, str], str] = {}
        for record in self.catalog.sources:
            if record.source_id in self._by_id:
                raise SourceRightsRegistryError(
                    f"duplicate source-rights source_id: {record.source_id}"
                )
            adapter_owner = self._by_adapter.get(record.source_id)
            if adapter_owner is not None:
                raise SourceRightsRegistryError(
                    "source-rights source_id collides with another record's "
                    f"adapter name: {record.source_id}"
                )
            self._by_id[record.source_id] = record
            for adapter_name in record.adapter_names:
                key = adapter_name.strip().casefold()
                if key in self._by_adapter:
                    raise SourceRightsRegistryError(
                        f"duplicate source-rights adapter name: {key}"
                    )
                source_owner = self._by_id.get(key)
                if source_owner is not None and source_owner is not record:
                    raise SourceRightsRegistryError(
                        "source-rights adapter name collides with another record's "
                        f"source_id: {key}"
                    )
                self._by_adapter[key] = record
            for adapter_path in record.adapter_paths:
                key = adapter_path.strip().casefold()
                path_owners.setdefault(key, []).append(record)
            for rule in record.url_rules:
                self._known_hosts.add(rule.host)
                canonical_prefix = _canonical_path(rule.path_prefix)
                if canonical_prefix is None:
                    raise SourceRightsRegistryError(
                        "source-rights URL rule has an invalid path prefix: "
                        f"{rule.host}{rule.path_prefix}"
                    )
                for scheme in rule.schemes:
                    key = (scheme, rule.host, canonical_prefix)
                    prior = url_owners.get(key)
                    if prior is not None:
                        raise SourceRightsRegistryError(
                            "duplicate source-rights URL rule "
                            f"{scheme}://{rule.host}{canonical_prefix}: "
                            f"{prior}, {record.source_id}"
                        )
                    url_owners[key] = record.source_id

        # Inventory-only module paths may legitimately appear on several
        # records. Only an exact path with one owner can authorize an adapter;
        # ambiguous module-level paths remain deliberately unresolvable.
        for key, owners in path_owners.items():
            resolved = {record.source_id: record for record in owners}
            if len(resolved) != 1:
                continue
            record = next(iter(resolved.values()))
            adapter_owner = self._by_adapter.get(key)
            source_owner = self._by_id.get(key)
            if adapter_owner is not None and adapter_owner is not record:
                raise SourceRightsRegistryError(
                    f"adapter path collides with adapter name: {key}"
                )
            if source_owner is not None and source_owner is not record:
                raise SourceRightsRegistryError(
                    f"adapter path collides with source_id: {key}"
                )
            self._by_adapter[key] = record

    @property
    def records(self) -> tuple[SourceRightsRecord, ...]:
        return self.catalog.sources

    def get(self, source_id: str) -> SourceRightsRecord | None:
        return self._by_id.get(source_id.strip().casefold())

    def for_adapter(self, adapter_name: str) -> SourceRightsRecord | None:
        key = adapter_name.strip().casefold()
        return self._by_adapter.get(key) or self._by_id.get(key)

    def for_url(self, url: str) -> SourceRightsRecord | None:
        if not _has_safe_authority(url):
            return None
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").casefold().rstrip(".")
        path = parsed.path or "/"
        if not scheme or not host:
            return None

        matches: list[tuple[int, SourceRightsRecord]] = []
        for record in self.catalog.sources:
            for rule in record.url_rules:
                if (
                    host == rule.host
                    and scheme in rule.schemes
                    and _path_matches(path, rule.path_prefix)
                ):
                    canonical_prefix = _canonical_path(rule.path_prefix)
                    if canonical_prefix is None:
                        raise SourceRightsRegistryError(
                            "source-rights registry contains an invalid URL rule"
                        )
                    matches.append((len(canonical_prefix), record))
        if not matches:
            return None
        longest = max(score for score, _ in matches)
        resolved = {
            record.source_id: record
            for score, record in matches
            if score == longest
        }
        if len(resolved) != 1:
            ids = ", ".join(sorted(resolved))
            raise SourceRightsRegistryError(
                f"ambiguous source-rights URL classification: {ids}"
            )
        return next(iter(resolved.values()))

    def has_registered_host(self, url: str) -> bool:
        """Return whether the URL targets any host owned by the registry."""
        try:
            host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        except (TypeError, ValueError):
            return False
        return bool(host and host in self._known_hosts)

    def delivery_metadata(self, source_id: str) -> dict[str, Any]:
        record = self.get(source_id)
        if record is None:
            raise SourceRightsRegistryError(f"unknown source-rights source_id: {source_id}")
        return {
            "source_id": record.source_id,
            "rights_state": record.rights_state.value,
            "evidence_urls": list(record.official_evidence_urls),
            "evidence_verified_on": (
                record.evidence_verified_on.isoformat()
                if record.evidence_verified_on is not None
                else None
            ),
            "attribution": list(record.disclosures.attribution),
            "disclaimer": list(record.disclosures.disclaimer),
            "delivery_proven": record.disclosures.delivery_proven,
        }


@lru_cache(maxsize=8)
def _cached_registry(path: str) -> SourceRightsRegistry:
    return SourceRightsRegistry(path)


def get_rights_registry(path: str | Path | None = None) -> SourceRightsRegistry:
    resolved = str(Path(path or DEFAULT_REGISTRY_PATH).expanduser().resolve())
    return _cached_registry(resolved)


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "SourceRightsRegistry",
    "SourceRightsRegistryError",
    "get_rights_registry",
]
