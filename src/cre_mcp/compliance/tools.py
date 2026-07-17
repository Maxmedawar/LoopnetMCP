"""Safe plain-function compliance boundaries for later MCP registration.

Nothing in this module registers a FastMCP tool.  Validation and persistence
exceptions are converted to the repository's ``{"error": ...}`` boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .calendar import compliance_calendar as _compliance_calendar
from .calendar import upcoming as _upcoming
from .energy_rules import energy_compliance as _energy_compliance
from .insurance_ops import record_claim as _record_claim
from .insurance_ops import record_policy as _record_policy
from .insurance_ops import renewal_radar as _renewal_radar
from .phase2 import phase2_scope as _phase2_scope
from .tax_appeal import build_appeal_package as _build_appeal_package
from .unpermitted import unpermitted_work_screen as _unpermitted_work_screen
from .utilities import retrofit_screen as _retrofit_screen
from .utilities import utility_anomalies as _utility_anomalies


def _safe(operation: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = call()
    except Exception as exc:
        message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        return {"error": message or f"{operation} failed"}
    return result if isinstance(result, dict) else {"error": f"{operation} result was not a dictionary"}


def build_appeal_package(
    assessment: Mapping[str, Any] | None,
    jurisdiction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble appeal evidence for professional review; never file an appeal."""

    return _safe(
        "build_appeal_package",
        lambda: _build_appeal_package(assessment, jurisdiction),
    )


def record_policy(
    asset: str | Mapping[str, Any] | None,
    carrier: str | None = None,
    line: str | None = None,
    premium_cents: int | None = None,
    expiry: date | datetime | str | None = None,
    claims: Sequence[Mapping[str, Any]] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one structured-input-v1 insurance policy."""

    return _safe(
        "record_policy",
        lambda: _record_policy(
            asset,
            carrier,
            line,
            premium_cents,
            expiry,
            claims,
            db_path=db_path,
        ),
    )


def record_claim(
    asset: str | None,
    carrier: str | None,
    line: str | None,
    claim: Mapping[str, Any] | None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one structured claim to a stored policy."""

    return _safe(
        "record_claim",
        lambda: _record_claim(asset, carrier, line, claim, db_path=db_path),
    )


def renewal_radar(
    days: int | None = 120,
    as_of: date | datetime | str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Surface policy renewals and convention-labeled claims signals."""

    horizon = 120 if days is None else days
    return _safe(
        "renewal_radar",
        lambda: _renewal_radar(horizon, as_of=as_of, db_path=db_path),
    )


def utility_anomalies(
    bills: Sequence[Mapping[str, Any]] | None,
    spike_threshold_pct: float | None = None,
    reconciliation_tolerance_pct: float | None = None,
) -> dict[str, Any]:
    """Screen supplied utility bills with exposed arithmetic conventions."""

    return _safe(
        "utility_anomalies",
        lambda: _utility_anomalies(
            bills,
            spike_threshold_pct,
            reconciliation_tolerance_pct,
        ),
    )


def retrofit_screen(
    usage: Mapping[str, Any] | int | float | None,
    measures: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return convention-labeled simple-payback ranges."""

    return _safe("retrofit_screen", lambda: _retrofit_screen(usage, measures))


def energy_compliance(
    jurisdiction: str | None,
    building: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a cited registry screen or an honest unknown/error boundary."""

    return _safe(
        "energy_compliance",
        lambda: _energy_compliance(jurisdiction, building),
    )


def compliance_calendar(
    asset: Mapping[str, Any] | None,
    db_path: str | Path | None = None,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Assemble and persist cited recurring obligations."""

    return _safe(
        "compliance_calendar",
        lambda: _compliance_calendar(asset, db_path, as_of),
    )


def upcoming(
    days: int | None = 90,
    db_path: str | Path | None = None,
    as_of: date | datetime | str | None = None,
    asset: str | None = None,
) -> dict[str, Any]:
    """Return obligations in an inclusive persisted-calendar window."""

    horizon = 90 if days is None else days
    return _safe(
        "upcoming",
        lambda: _upcoming(horizon, db_path, as_of, asset),
    )


def unpermitted_work_screen(
    observed_improvements: Sequence[Mapping[str, Any]] | None,
    permit_history: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Conservatively match observed work to supplied permit history."""

    return _safe(
        "unpermitted_work_screen",
        lambda: _unpermitted_work_screen(observed_improvements, permit_history),
    )


def phase2_scope(
    phase1_findings: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Organize REC-specific Phase II starting scopes for a licensed consultant."""

    return _safe("phase2_scope", lambda: _phase2_scope(phase1_findings))


__all__ = [
    "build_appeal_package",
    "compliance_calendar",
    "energy_compliance",
    "phase2_scope",
    "record_claim",
    "record_policy",
    "renewal_radar",
    "retrofit_screen",
    "unpermitted_work_screen",
    "upcoming",
    "utility_anomalies",
]
