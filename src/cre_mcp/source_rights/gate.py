"""One fail-closed decision path for hosted source access."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from cre_mcp.access.context import current_context, current_runtime_config
from cre_mcp.source_rights.models import SourceKind, SourceRightsRecord
from cre_mcp.source_rights.registry import (
    SourceRightsRegistryError,
    get_rights_registry,
)

if TYPE_CHECKING:
    from cre_mcp.config import CreConfig


class SourceRightsDeniedError(RuntimeError):
    """An external-source operation has no current hosted authorization."""


_authorized_sources: ContextVar[dict[str, SourceRightsRecord] | None] = ContextVar(
    "cre_authorized_source_rights",
    default=None,
)


@contextmanager
def collect_authorized_sources():
    """Collect rights records successfully exercised by one tool request."""
    records: dict[str, SourceRightsRecord] = {}
    token = _authorized_sources.set(records)
    try:
        yield records
    finally:
        _authorized_sources.reset(token)


def _record_authorized_source(record: SourceRightsRecord | None) -> None:
    records = _authorized_sources.get()
    if records is not None and record is not None:
        records.setdefault(record.source_id, record)


def is_hosted_execution(config: "CreConfig | None" = None) -> bool:
    context = current_context()
    if context is not None:
        return not context.trusted
    if config is not None:
        return config.transport != "stdio"
    # Missing context is not proof of trusted-local execution. Background jobs
    # and worker threads must fail closed if server context propagation is lost.
    return True


def _registry_path(config: "CreConfig | None") -> str | Path | None:
    return getattr(config, "source_rights_registry_path", None) if config else None


def _deny(reason: str) -> SourceRightsDeniedError:
    return SourceRightsDeniedError(f"source-rights denied: {reason}")


def _explicit_runtime_config(config: "CreConfig | None") -> "CreConfig | None":
    runtime = current_runtime_config()
    if runtime is not None:
        return runtime
    if config is not None:
        return config
    if current_context() is None:
        return None
    from cre_mcp.config import CreConfig

    return CreConfig()


def _require_runtime_proof(config: "CreConfig | None") -> None:
    if current_context() is None and config is None:
        raise _deny("external egress requires explicit trusted-local or hosted runtime proof")


def _require_enabled(
    record: SourceRightsRecord | None,
    *,
    config: "CreConfig | None",
    operation: str,
) -> None:
    resolved = _explicit_runtime_config(config)
    if record is None:
        source_id = "unclassified.network"
    elif record.source_kind in {SourceKind.EMBEDDED, SourceKind.LINK_ONLY}:
        return
    else:
        source_id = record.source_id
    enabled = bool(
        resolved is not None
        and resolved.source_rights_enabled.get(source_id) is True
    )
    if not enabled:
        raise _deny(f"{operation} ({source_id}) is not explicitly enabled")


def _require_hosted_record(record: SourceRightsRecord | None, operation: str) -> SourceRightsRecord:
    if record is None:
        raise _deny(f"unclassified {operation}")
    if record.trusted_local_only:
        raise _deny(f"{record.source_id} is trusted-local-only")
    if not record.hosted_cloud_allowed:
        raise _deny(
            f"{record.source_id} is {record.rights_state.value} and not approved for hosted cloud"
        )
    return record


def require_source(
    source_or_adapter: str,
    *,
    config: "CreConfig | None" = None,
) -> SourceRightsRecord | None:
    config = _explicit_runtime_config(config)
    _require_runtime_proof(config)
    try:
        registry = get_rights_registry(_registry_path(config))
        record = registry.for_adapter(source_or_adapter)
    except SourceRightsRegistryError:
        raise _deny("registry unavailable or ambiguous") from None
    operation = f"source adapter {source_or_adapter!r}"
    _require_enabled(record, config=config, operation=operation)
    if record is not None and record.source_kind in {
        SourceKind.EMBEDDED,
        SourceKind.LINK_ONLY,
    }:
        source_kind = record.source_kind.value.replace("_", "-")
        raise _deny(
            f"{record.source_id} is {source_kind} and does not authorize an adapter"
        )
    if not is_hosted_execution(config):
        _record_authorized_source(record)
        return record
    authorized = _require_hosted_record(record, operation)
    _record_authorized_source(authorized)
    return authorized


def require_url(
    url: str,
    *,
    method: str = "GET",
    config: "CreConfig | None" = None,
) -> SourceRightsRecord | None:
    config = _explicit_runtime_config(config)
    _require_runtime_proof(config)
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise _deny("invalid URL") from None
    scheme = parsed.scheme.casefold()
    expected_port = 443 if scheme == "https" else 80
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != expected_port)
    ):
        raise _deny("invalid URL")
    try:
        registry = get_rights_registry(_registry_path(config))
        record = registry.for_url(url)
    except SourceRightsRegistryError:
        raise _deny(
            "registry unavailable or URL classification is ambiguous"
        ) from None
    if record is None and registry.has_registered_host(url):
        raise _deny("unclassified URL route on a registered host")
    _require_enabled(record, config=config, operation="URL or host")
    if is_hosted_execution(config):
        record = _require_hosted_record(record, "URL or host")
    if record is None:
        return None
    if record.source_kind not in {SourceKind.AUTOMATED, SourceKind.DIRECT_ADAPTER}:
        source_kind = record.source_kind.value.replace("_", "-")
        raise _deny(
            f"{record.source_id} is {source_kind} and does not "
            "authorize automated fetch"
        )
    normalized_method = method.strip().upper()
    if normalized_method not in record.methods:
        raise _deny(f"{record.source_id} does not authorize HTTP {normalized_method}")
    _record_authorized_source(record)
    return record


__all__ = [
    "SourceRightsDeniedError",
    "collect_authorized_sources",
    "is_hosted_execution",
    "require_source",
    "require_url",
]
