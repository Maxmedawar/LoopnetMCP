"""Hosted raw-payload and credential sanitizers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence, Set
from typing import Any, Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from cre_mcp.models.listings import Listing, ListingRef

GENERIC_CREDENTIAL_NAMES = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "app_token",
        "authorization",
        "client_secret",
        "key",
        "password",
        "secret",
        "token",
    }
)

# ``key`` is also a common normalized business field (for example a scoring
# signal identifier). Treat it as a credential in URLs, cache inputs, and
# source-scoped metadata, but do not erase it from unrelated output objects.
_UNAMBIGUOUS_OUTPUT_CREDENTIAL_NAMES = GENERIC_CREDENTIAL_NAMES - {"key"}
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+", flags=re.IGNORECASE)
_AUTHORIZATION_IN_TEXT = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;]+"
)
_CREDENTIAL_ASSIGNMENT_IN_TEXT = re.compile(
    r"(?i)\b(access_token|api[-_]?key|apikey|app_token|client_secret|"
    r"password|secret|token|x-api-key)\s*[:=]\s*[^\s,;&]+"
)


def credential_name(value: object) -> bool:
    return str(value).strip().casefold() in GENERIC_CREDENTIAL_NAMES


def _normalized_secrets(secret_values: Sequence[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            text
            for item in secret_values
            if (text := str(item).strip())
        )
    )


def _contains_secret(value: object, secrets: tuple[str, ...]) -> bool:
    if not secrets:
        return False
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    elif value is None or isinstance(value, (bool, int, float)):
        text = str(value)
    else:
        return False
    return any(secret in text for secret in secrets)


def redact_url(
    url: str,
    extra_names: tuple[str, ...] = (),
    *,
    secret_values: Sequence[object] = (),
) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return "[invalid-url]"
    names = GENERIC_CREDENTIAL_NAMES | {
        item.strip().casefold() for item in extra_names if item.strip()
    }
    secrets = _normalized_secrets(secret_values)
    try:
        decoded_path = unquote(parsed.path)
    except (TypeError, ValueError):
        decoded_path = parsed.path
    if any(
        _contains_secret(component, secrets)
        for component in (parsed.scheme, host, parsed.path, decoded_path)
    ):
        return "[redacted-url]"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.strip().casefold() not in names
        and not _contains_secret(key, secrets)
        and not _contains_secret(value, secrets)
    ]
    if host is None:
        netloc = ""
    else:
        netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
        if port is not None:
            netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), ""))


def _redact_recursive(
    value: Any,
    *,
    secrets: tuple[str, ...],
    max_depth: int,
    depth: int,
    active: set[int],
    cache_mode: bool,
) -> Any:
    if depth >= max_depth:
        return "[max-depth]"
    if isinstance(value, str):
        return "[redacted]" if _contains_secret(value, secrets) else value
    if isinstance(value, bytes):
        if _contains_secret(value, secrets):
            return "[redacted]"
        return {
            "type": "bytes",
            "length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)

    object_id = id(value)
    if object_id in active:
        return "[circular]"

    if isinstance(value, Mapping):
        active.add(object_id)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if credential_name(key_text) or _contains_secret(key_text, secrets):
                    continue
                if cache_mode and _contains_secret(item, secrets):
                    continue
                result[key_text] = _redact_recursive(
                    item,
                    secrets=secrets,
                    max_depth=max_depth,
                    depth=depth + 1,
                    active=active,
                    cache_mode=cache_mode,
                )
            return result
        finally:
            active.remove(object_id)

    if isinstance(value, (list, tuple)):
        active.add(object_id)
        try:
            items = [
                _redact_recursive(
                    item,
                    secrets=secrets,
                    max_depth=max_depth,
                    depth=depth + 1,
                    active=active,
                    cache_mode=cache_mode,
                )
                for item in value
                if not (cache_mode and _contains_secret(item, secrets))
            ]
            return tuple(items) if isinstance(value, tuple) and not cache_mode else items
        finally:
            active.remove(object_id)

    if isinstance(value, (Set, frozenset)):
        active.add(object_id)
        try:
            items = [
                _redact_recursive(
                    item,
                    secrets=secrets,
                    max_depth=max_depth,
                    depth=depth + 1,
                    active=active,
                    cache_mode=cache_mode,
                )
                for item in value
                if not (cache_mode and _contains_secret(item, secrets))
            ]
            return sorted(items, key=lambda item: repr(item))
        finally:
            active.remove(object_id)

    # Never include arbitrary-object reprs in output or cache metadata. They can
    # contain credentials even when their field names do not look sensitive.
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def redact_credentials(
    value: Any,
    *,
    secret_values: Sequence[object] = (),
    max_depth: int = 32,
) -> Any:
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    return _redact_recursive(
        value,
        secrets=_normalized_secrets(secret_values),
        max_depth=max_depth,
        depth=0,
        active=set(),
        cache_mode=False,
    )


def canonicalize_for_cache(
    value: Any,
    *,
    secret_values: Sequence[object] = (),
    max_depth: int = 32,
) -> Any:
    """Return bounded JSON-compatible metadata with credential-bearing fields gone."""
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    return _redact_recursive(
        value,
        secrets=_normalized_secrets(secret_values),
        max_depth=max_depth,
        depth=0,
        active=set(),
        cache_mode=True,
    )


def hosted_context_active() -> bool:
    from cre_mcp.access.context import current_context

    context = current_context()
    return context is None or not context.trusted


def _effective_config(config: object | None = None) -> object | None:
    if config is not None:
        return config
    try:
        from cre_mcp.access.context import current_runtime_config

        runtime = current_runtime_config()
        if runtime is not None:
            return runtime
    except (ImportError, RuntimeError):
        pass
    try:
        from cre_mcp.config import CreConfig

        # Sanitization is used inside denial and logging paths. Do not let those
        # paths discover or inspect a dotenv file after rejecting user input.
        # Process environment values are still loaded, including configured
        # secrets that must be removed from diagnostics.
        return CreConfig(_env_file=None)
    except Exception:
        return None


def _configured_secret_values(config: object | None = None) -> tuple[str, ...]:
    selected = _effective_config(config)
    if selected is None:
        return ()
    values: list[str] = []
    fields = getattr(type(selected), "model_fields", {})
    for name in fields:
        value = getattr(selected, name, None)
        reveal = getattr(value, "get_secret_value", None)
        if not callable(reveal):
            continue
        try:
            secret = str(reveal()).strip()
        except Exception:
            continue
        if secret:
            values.append(secret)
    return tuple(dict.fromkeys(values))


def _rights_registry(
    *,
    config: object | None = None,
    registry: object | None = None,
) -> object | None:
    if registry is not None:
        return registry
    selected = _effective_config(config)
    path = getattr(selected, "source_rights_registry_path", None)
    try:
        from cre_mcp.source_rights.registry import get_rights_registry

        return get_rights_registry(path)
    except Exception:
        return None


def _registry_record(
    *,
    source: object | None = None,
    url: str | None = None,
    config: object | None = None,
    registry: object | None = None,
) -> object | None:
    selected = _rights_registry(config=config, registry=registry)
    if selected is None:
        return None
    try:
        source_record = (
            selected.for_adapter(str(source)) if source is not None else None
        )
        url_record = selected.for_url(url) if url else None
        if source is not None and url:
            if source_record is None or url_record is None:
                return None
            if source_record.source_id != url_record.source_id:
                return None
            return source_record
        return source_record or url_record
    except Exception:
        return None


def _registry_credential_names(
    *,
    source: object | None = None,
    url: str | None = None,
    config: object | None = None,
    registry: object | None = None,
) -> tuple[str, ...]:
    """Resolve provider-specific query credentials without weakening fail-safe output."""
    record = _registry_record(
        source=source,
        url=url,
        config=config,
        registry=registry,
    )
    return record.query_credentials if record is not None else ()


def _output_url_credential_names(
    url: str,
    *,
    source: object | None = None,
    config: object | None = None,
    registry: object | None = None,
    inherited: Sequence[str] = (),
) -> tuple[str, ...]:
    """Return provider credentials, dropping every query key if classification fails."""
    record = _registry_record(
        source=source,
        url=url,
        config=config,
        registry=registry,
    )
    names = list(inherited)
    if record is not None:
        names.extend(record.query_credentials)
    else:
        try:
            names.extend(key for key, _ in parse_qsl(urlsplit(url).query))
        except (TypeError, ValueError):
            pass
    return tuple(dict.fromkeys(str(name) for name in names if str(name).strip()))


def _all_registry_credential_names(
    *,
    config: object | None = None,
    registry: object | None = None,
) -> tuple[str, ...]:
    selected = _rights_registry(config=config, registry=registry)
    if selected is None:
        return ()
    try:
        records = selected.records
    except Exception:
        return ()
    return tuple(
        dict.fromkeys(
            credential
            for record in records
            for credential in (getattr(record, "query_credentials", ()) or ())
        )
    )


def _redact_message_credentials(
    value: object,
    *,
    secret_values: Sequence[object] = (),
    credential_names: Sequence[str] = (),
) -> str:
    text = _AUTHORIZATION_IN_TEXT.sub(r"\1[redacted]", str(value))
    text = _CREDENTIAL_ASSIGNMENT_IN_TEXT.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        text,
    )
    for name in dict.fromkeys(credential_names):
        if not str(name).strip():
            continue
        assignment = re.compile(
            rf"(?i)(?<![\w-])({re.escape(str(name))})\s*[:=]\s*[^\s,;&]+"
        )
        text = assignment.sub(
            lambda match: f"{match.group(1)}=[redacted]",
            text,
        )
    for secret in _normalized_secrets(secret_values):
        text = text.replace(secret, "[redacted]")
    return text


def safe_source_reference(
    value: object,
    *,
    source: object | None = None,
    config: object | None = None,
    registry: object | None = None,
) -> str:
    """Return a log-safe listing/document reference while preserving bare IDs."""
    text = str(value)
    if not text.casefold().startswith(("http://", "https://")):
        text = _URL_IN_TEXT.sub(
            lambda match: safe_source_reference(
                match.group(0),
                source=source,
                config=config,
                registry=registry,
            ),
            text,
        )
        return _redact_message_credentials(
            text,
            secret_values=_configured_secret_values(config),
            credential_names=_all_registry_credential_names(
                config=config,
                registry=registry,
            ),
        )
    return redact_url(
        text,
        _output_url_credential_names(
            text,
            source=source,
            config=config,
            registry=registry,
        ),
        secret_values=_configured_secret_values(config),
    )


def safe_error_message(
    value: object,
    *,
    source: object | None = None,
    config: object | None = None,
    registry: object | None = None,
) -> str:
    """Redact credential-bearing URLs embedded in an exception message."""
    text = str(value)
    text = _URL_IN_TEXT.sub(
        lambda match: safe_source_reference(
            match.group(0),
            source=source,
            config=config,
            registry=registry,
        ),
        text,
    )
    return _redact_message_credentials(
        text,
        secret_values=_configured_secret_values(config),
        credential_names=_all_registry_credential_names(
            config=config,
            registry=registry,
        ),
    )


def _raw_allowed(record: object | None, purpose: Literal["output", "storage"]) -> bool:
    if record is None:
        return False
    field = "raw_output_allowed" if purpose == "output" else "raw_storage_allowed"
    return getattr(record, field, False) is True


def _delivery_metadata(record: object) -> dict[str, Any] | None:
    disclosures = getattr(record, "disclosures", None)
    attribution = list(getattr(disclosures, "attribution", ()))
    disclaimer = list(getattr(disclosures, "disclaimer", ()))
    if not attribution and not disclaimer:
        return None
    verified = getattr(record, "evidence_verified_on", None)
    state = getattr(record, "rights_state", None)
    return {
        "source_id": getattr(record, "source_id", ""),
        "rights_state": getattr(state, "value", str(state or "")),
        "evidence_urls": list(getattr(record, "official_evidence_urls", ())),
        "evidence_verified_on": verified.isoformat() if verified is not None else None,
        "attribution": attribution,
        "disclaimer": disclaimer,
        "delivery_proven": bool(getattr(disclosures, "delivery_proven", False)),
    }


def sanitize_listing(
    listing: Listing,
    *,
    purpose: Literal["output", "storage"] = "output",
    config: object | None = None,
    registry: object | None = None,
) -> Listing:
    """Strip source-native payloads and credential-bearing URLs in hosted use."""
    if not hosted_context_active():
        return listing
    if purpose not in {"output", "storage"}:
        raise ValueError("purpose must be 'output' or 'storage'")
    selected_registry = _rights_registry(config=config, registry=registry)
    record = _registry_record(
        source=listing.source,
        url=listing.url,
        config=config,
        registry=selected_registry,
    )
    credential_names = _output_url_credential_names(
        listing.url,
        source=listing.source,
        config=config,
        registry=selected_registry,
    )
    secrets = _configured_secret_values(config)
    raw_container = sanitize_payload(
        {"source": listing.source, "raw": listing.raw},
        purpose=purpose,
        config=config,
        registry=selected_registry,
    )
    sanitized_raw = (
        raw_container.get("raw", {})
        if isinstance(raw_container, Mapping)
        else {}
    )
    refs = [
        ListingRef(
            source=ref.source,
            source_id=safe_source_reference(
                ref.source_id,
                source=ref.source,
                config=config,
                registry=selected_registry,
            ),
            url=(
                redact_url(
                    ref.url,
                    _output_url_credential_names(
                        ref.url,
                        source=ref.source,
                        config=config,
                        registry=selected_registry,
                    ),
                    secret_values=secrets,
                )
                if ref.url
                else None
            ),
        )
        for ref in listing.refs
    ]
    return listing.model_copy(
        update={
            "raw": sanitized_raw,
            "source_id": safe_source_reference(
                listing.source_id,
                source=listing.source,
                config=config,
                registry=selected_registry,
            ),
            "url": redact_url(
                listing.url,
                credential_names,
                secret_values=secrets,
            ),
            "image_url": (
                redact_url(
                    listing.image_url,
                    _output_url_credential_names(
                        listing.image_url,
                        source=listing.source,
                        config=config,
                        registry=selected_registry,
                        inherited=credential_names,
                    ),
                    secret_values=secrets,
                )
                if listing.image_url
                else None
            ),
            "images": [
                redact_url(
                    url,
                    _output_url_credential_names(
                        url,
                        source=listing.source,
                        config=config,
                        registry=selected_registry,
                        inherited=credential_names,
                    ),
                    secret_values=secrets,
                )
                for url in listing.images
            ],
            "refs": refs,
        }
    )


def _sanitize_payload_recursive(
    value: Any,
    *,
    depth: int,
    max_depth: int,
    active: set[int],
    credential_names: tuple[str, ...] = (),
    record: object | None = None,
    purpose: Literal["output", "storage"] = "output",
    config: object | None = None,
    registry: object | None = None,
    secret_values: tuple[str, ...] = (),
    attach_metadata: bool = False,
) -> Any:
    if depth >= max_depth:
        return "[max-depth]"
    if isinstance(value, str):
        if value.casefold().startswith(("http://", "https://")):
            url_credential_names = tuple(
                dict.fromkeys(
                    (
                        *credential_names,
                        *_output_url_credential_names(
                            value,
                            config=config,
                            registry=registry,
                        ),
                    )
                )
            )
            return redact_url(
                value,
                url_credential_names,
                secret_values=secret_values,
            )
        return safe_error_message(value, config=config, registry=registry)
    if isinstance(value, bytes):
        if _contains_secret(value, secret_values):
            return "[redacted]"
        return {
            "type": "bytes",
            "length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if value is None or isinstance(value, (bool, int)):
        return "[redacted]" if _contains_secret(value, secret_values) else value
    if isinstance(value, float):
        if _contains_secret(value, secret_values):
            return "[redacted]"
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in active:
            return "[circular]"
        active.add(object_id)
        sanitized: dict[str, Any] = {}
        try:
            source = value.get("source")
            declared_source = source is not None
            scoped_record = record
            if declared_source:
                scoped_record = _registry_record(
                    source=source,
                    url=value.get("url") if isinstance(value.get("url"), str) else None,
                    config=config,
                    registry=registry,
                )
            elif scoped_record is None and isinstance(value.get("url"), str):
                scoped_record = _registry_record(
                    url=value.get("url"),
                    config=config,
                    registry=registry,
                )
            scoped_credential_names = tuple(
                dict.fromkeys(
                    (
                        *credential_names,
                        *(getattr(scoped_record, "query_credentials", ()) or ()),
                    )
                )
            )
            scoped_normalized = {
                item.strip().casefold() for item in scoped_credential_names
            }
            for key, item in value.items():
                key_text = safe_error_message(
                    key,
                    source=source,
                    config=config,
                    registry=registry,
                )
                normalized = str(key).strip().casefold()
                raw_forbidden = (
                    normalized == "raw" and not _raw_allowed(scoped_record, purpose)
                )
                if raw_forbidden:
                    continue
                if (
                    normalized == "source_rights"
                    or normalized in _UNAMBIGUOUS_OUTPUT_CREDENTIAL_NAMES
                    or normalized in scoped_normalized
                ):
                    continue
                if key_text in sanitized:
                    continue
                if isinstance(item, str) and normalized == "source_id":
                    sanitized[key_text] = safe_source_reference(
                        item,
                        source=source,
                        config=config,
                        registry=registry,
                    )
                elif (
                    isinstance(item, str)
                    and normalized in {"deal_id", "dedupe_key", "listing_key"}
                    and "http" in item.casefold()
                ):
                    sanitized[key_text] = safe_error_message(
                        item,
                        source=source,
                        config=config,
                        registry=registry,
                    )
                elif isinstance(item, str) and normalized.endswith("url"):
                    url_credential_names = tuple(
                        dict.fromkeys(
                            (
                                *scoped_credential_names,
                                *_output_url_credential_names(
                                    item,
                                    source=source,
                                    config=config,
                                    registry=registry,
                                    inherited=scoped_credential_names,
                                ),
                            )
                        )
                    )
                    sanitized[key_text] = redact_url(
                        item,
                        url_credential_names,
                        secret_values=secret_values,
                    )
                else:
                    sanitized[key_text] = _sanitize_payload_recursive(
                        item,
                        depth=depth + 1,
                        max_depth=max_depth,
                        active=active,
                        credential_names=scoped_credential_names,
                        record=scoped_record,
                        purpose=purpose,
                        config=config,
                        registry=registry,
                        secret_values=secret_values,
                    )
            if purpose == "output" and (declared_source or attach_metadata):
                metadata = (
                    _delivery_metadata(scoped_record)
                    if scoped_record is not None
                    else None
                )
                if metadata is not None:
                    sanitized["source_rights"] = metadata
            return sanitized
        finally:
            active.remove(object_id)
    if isinstance(value, list):
        object_id = id(value)
        if object_id in active:
            return "[circular]"
        active.add(object_id)
        try:
            return [
                _sanitize_payload_recursive(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    active=active,
                    credential_names=credential_names,
                    record=record,
                    purpose=purpose,
                    config=config,
                    registry=registry,
                    secret_values=secret_values,
                )
                for item in value
            ]
        finally:
            active.remove(object_id)
    if isinstance(value, tuple):
        object_id = id(value)
        if object_id in active:
            return "[circular]"
        active.add(object_id)
        try:
            return tuple(
                _sanitize_payload_recursive(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    active=active,
                    credential_names=credential_names,
                    record=record,
                    purpose=purpose,
                    config=config,
                    registry=registry,
                    secret_values=secret_values,
                )
                for item in value
            )
        finally:
            active.remove(object_id)
    if isinstance(value, (Set, frozenset)):
        object_id = id(value)
        if object_id in active:
            return "[circular]"
        active.add(object_id)
        try:
            items = [
                _sanitize_payload_recursive(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    active=active,
                    credential_names=credential_names,
                    record=record,
                    purpose=purpose,
                    config=config,
                    registry=registry,
                    secret_values=secret_values,
                )
                for item in value
            ]
            return sorted(items, key=lambda item: repr(item))
        finally:
            active.remove(object_id)
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def sanitize_payload(
    value: Any,
    *,
    max_depth: int = 32,
    purpose: Literal["output", "storage"] = "output",
    source: object | None = None,
    config: object | None = None,
    registry: object | None = None,
) -> Any:
    """Recursively remove raw payloads and credential fields for hosted output."""
    if not hosted_context_active():
        return value
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    if purpose not in {"output", "storage"}:
        raise ValueError("purpose must be 'output' or 'storage'")
    selected_registry = _rights_registry(config=config, registry=registry)
    initial_record = _registry_record(
        source=source,
        config=config,
        registry=selected_registry,
    )
    initial_credentials = tuple(
        getattr(initial_record, "query_credentials", ()) or ()
    )
    return _sanitize_payload_recursive(
        value,
        depth=0,
        max_depth=max_depth,
        active=set(),
        credential_names=initial_credentials,
        record=initial_record,
        purpose=purpose,
        config=config,
        registry=selected_registry,
        secret_values=_configured_secret_values(config),
        attach_metadata=source is not None,
    )


def attach_source_disclosures(
    value: Any,
    records: Sequence[object],
) -> Any:
    """Attach every disclosure required by sources exercised in this request.

    Internal tools frequently normalize one tool's result into another Pydantic
    model. That transformation may legitimately discard provenance fields, but
    it must never discard delivery requirements. The request middleware calls
    this after sanitization using records collected at each successful source
    gate.
    """
    if not hosted_context_active() or not isinstance(value, Mapping):
        return value

    metadata_by_source: dict[str, dict[str, Any]] = {}
    existing = value.get("source_rights")
    if isinstance(existing, Mapping):
        source_id = str(existing.get("source_id") or "").strip()
        if source_id:
            metadata_by_source[source_id] = dict(existing)
        existing_sources = existing.get("sources")
        if isinstance(existing_sources, list):
            for item in existing_sources:
                if not isinstance(item, Mapping):
                    continue
                item_source = str(item.get("source_id") or "").strip()
                if item_source:
                    metadata_by_source[item_source] = dict(item)

    for record in records:
        metadata = _delivery_metadata(record)
        if metadata is not None and metadata["source_id"]:
            metadata_by_source[metadata["source_id"]] = metadata

    if not metadata_by_source:
        return value

    sanitized = dict(value)
    ordered = [metadata_by_source[key] for key in sorted(metadata_by_source)]
    if len(ordered) == 1:
        sanitized["source_rights"] = ordered[0]
        return sanitized

    sanitized["source_rights"] = {
        "source_ids": [item["source_id"] for item in ordered],
        "sources": ordered,
        "evidence_urls": list(
            dict.fromkeys(
                url
                for item in ordered
                for url in item.get("evidence_urls", [])
            )
        ),
        "attribution": list(
            dict.fromkeys(
                text
                for item in ordered
                for text in item.get("attribution", [])
            )
        ),
        "disclaimer": list(
            dict.fromkeys(
                text
                for item in ordered
                for text in item.get("disclaimer", [])
            )
        ),
        "delivery_proven": all(
            bool(item.get("delivery_proven")) for item in ordered
        ),
    }
    return sanitized


def sanitize_tool_result(
    result: Any,
    *,
    authorized_records: Sequence[object] = (),
    config: object | None = None,
    registry: object | None = None,
) -> Any:
    """Sanitize the final FastMCP result at the universal delivery boundary."""
    if not hosted_context_active():
        return result

    # Keep FastMCP optional for non-server consumers of the sanitization module.
    try:
        from fastmcp.tools.tool import ToolResult
    except ImportError:
        ToolResult = None  # type: ignore[assignment,misc]

    if ToolResult is not None and isinstance(result, ToolResult):
        sanitized_meta = sanitize_payload(
            result.meta,
            config=config,
            registry=registry,
        ) if result.meta is not None else None
        if not isinstance(sanitized_meta, dict):
            sanitized_meta = None

        if result.structured_content is not None:
            structured = sanitize_payload(
                result.structured_content,
                config=config,
                registry=registry,
            )
            structured = attach_source_disclosures(
                structured,
                authorized_records,
            )
            if not isinstance(structured, dict):
                structured = {"result": structured}
            return ToolResult(
                structured_content=structured,
                meta=sanitized_meta,
            )

        content_payload: list[Any] = []
        for block in result.content:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                try:
                    content_payload.append(json.loads(text))
                except (TypeError, ValueError, json.JSONDecodeError):
                    content_payload.append(
                        safe_error_message(
                            text,
                            config=config,
                            registry=registry,
                        )
                    )
                continue
            dump = getattr(block, "model_dump", None)
            content_payload.append(
                dump(mode="json") if callable(dump) else {"type": str(type(block))}
            )
        content = sanitize_payload(
            content_payload,
            config=config,
            registry=registry,
        )
        return ToolResult(content=content, meta=sanitized_meta)

    sanitized = sanitize_payload(
        result,
        config=config,
        registry=registry,
    )
    return attach_source_disclosures(sanitized, authorized_records)


__all__ = [
    "GENERIC_CREDENTIAL_NAMES",
    "attach_source_disclosures",
    "canonicalize_for_cache",
    "credential_name",
    "hosted_context_active",
    "redact_credentials",
    "redact_url",
    "safe_error_message",
    "safe_source_reference",
    "sanitize_listing",
    "sanitize_payload",
    "sanitize_tool_result",
]
