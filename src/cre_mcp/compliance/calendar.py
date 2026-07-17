"""Cited recurring-obligation calendar backed by one owned SQLite table."""

from __future__ import annotations

import calendar as month_calendar
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


CALENDAR_DISCLAIMER = (
    "Planning calendar only; confirm every date, applicability threshold, and "
    "inspection requirement with the taxing authority, licensing body, local "
    "AHJ, and qualified code professional."
)

# These are planning conventions, not a claim that property-tax administration
# is uniform within a state.  Each entry says exactly where local variation is
# still material.
PROPERTY_TAX_REGISTRY: dict[str, dict[str, Any]] = {
    "CA": {
        "installments": ((11, 1, "first installment"), (2, 1, "second installment")),
        "source_label": "California Revenue and Taxation Code §§2605 and 2705",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?division=1.&chapter=1.&part=5.&lawCode=RTC&title=",
        "last_verified": "2025-02-15",
        "notes": (
            "Secured-tax installments are due November 1 and February 1; "
            "county corrections, supplemental assessments, and delinquency "
            "dates require county verification."
        ),
    },
    "TX": {
        "installments": ((1, 31, "annual planning cutoff"),),
        "source_label": "Texas Tax Code §31.02",
        "source_url": "https://statutes.capitol.texas.gov/Docs/TX/htm/TX.31.htm#31.02",
        "last_verified": "2025-02-15",
        "notes": (
            "Taxes are due on receipt and generally become delinquent February 1; "
            "January 31 is used only as a payment-planning cutoff. Verify the bill."
        ),
    },
    "DC": {
        "installments": ((3, 31, "first half"), (9, 15, "second half")),
        "source_label": "District of Columbia Office of Tax and Revenue real-property tax calendar",
        "source_url": "https://otr.cfo.dc.gov/page/real-property-tax-database-search",
        "last_verified": "2025-02-15",
        "notes": "Planning dates are March 31 and September 15; verify the current OTR bill.",
    },
    "MA": {
        "installments": (
            (8, 1, "quarter 1"),
            (11, 1, "quarter 2"),
            (2, 1, "quarter 3"),
            (5, 1, "quarter 4"),
        ),
        "source_label": "Massachusetts General Laws c.59 §57C (local quarterly-payment adoption)",
        "source_url": "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIX/Chapter59/Section57C",
        "last_verified": "2025-02-15",
        "notes": (
            "Quarterly dates apply only where the municipality adopted the quarterly "
            "system; municipality and actual bill control."
        ),
    },
}

SYSTEM_REGISTRY: dict[str, dict[str, Any]] = {
    "elevator": {
        "aliases": ("elevator", "lift"),
        "obligation": "Elevator periodic inspection",
        "cadence": "annual convention",
        "months": 12,
        "source_label": "MODEL CONVENTION — annual; ASME A17.1 §8.11 framework, local AHJ frequency controls",
        "source_url": "https://www.asme.org/codes-standards/find-codes-standards/a17-1-safety-code-for-elevators-and-escalators",
        "last_verified": "2025-02-15",
    },
    "backflow": {
        "aliases": ("backflow", "backflow preventer", "cross connection"),
        "obligation": "Backflow-prevention assembly test",
        "cadence": "annual convention",
        "months": 12,
        "source_label": "MODEL CONVENTION — annual backflow test; local water authority rule controls",
        "source_url": "https://www.epa.gov/dwreginfo/cross-connection-control-manual",
        "last_verified": "2025-02-15",
    },
    "fire_alarm": {
        "aliases": ("fire alarm", "alarm"),
        "obligation": "Fire-alarm system test",
        "cadence": "annual convention",
        "months": 12,
        "source_label": "NFPA 72 periodic testing framework (Table 14.4.3.2); adopted edition and AHJ control",
        "source_url": "https://www.nfpa.org/codes-and-standards/nfpa-72-standard-development/72",
        "last_verified": "2025-02-15",
    },
    "sprinkler": {
        "aliases": ("sprinkler", "fire sprinkler", "wet sprinkler"),
        "obligation": "Sprinkler internal inspection",
        "cadence": "every 5 years convention",
        "months": 60,
        "source_label": "NFPA 25 five-year internal inspection convention; adopted edition and AHJ control",
        "source_url": "https://www.nfpa.org/codes-and-standards/nfpa-25-standard-development/25",
        "last_verified": "2025-02-15",
    },
}


def _day(value: Any, label: str, *, default: date | None = None) -> date | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _next_occurrence(as_of: date, month: int, day: int) -> date:
    candidate = date(as_of.year, month, day)
    return candidate if candidate >= as_of else date(as_of.year + 1, month, day)


def _add_months(value: date, months: int) -> date:
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _asset_id(asset: Mapping[str, Any]) -> str:
    for key in ("asset_id", "asset", "id", "name", "address"):
        value = _text(asset.get(key))
        if value is not None:
            return value
    parts = [_text(asset.get(key)) for key in ("city", "state", "type")]
    identifier = "|".join(part for part in parts if part)
    if not identifier:
        raise ValueError("asset needs asset_id, asset, name, address, or jurisdiction/type fields")
    return identifier


def _systems(asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = asset.get("systems")
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    if not isinstance(raw, Sequence):
        raise TypeError("asset.systems must be a sequence")
    rows: list[dict[str, Any]] = []
    for value in raw:
        if isinstance(value, Mapping):
            rows.append(dict(value))
        else:
            rows.append({"system": str(value)})
    return rows


def _system_rule(value: Any) -> tuple[str, dict[str, Any]] | None:
    normalized = str(value or "").strip().casefold().replace("-", " ").replace("_", " ")
    for key, rule in SYSTEM_REGISTRY.items():
        if any(alias in normalized for alias in rule["aliases"]):
            return key, rule
    return None


def _due_from_input(row: Mapping[str, Any], months: int) -> date | None:
    direct = _day(row.get("next_due", row.get("due_date", row.get("expiry"))), "next_due")
    if direct is not None:
        return direct
    prior = _day(
        row.get("last_inspection", row.get("last_tested", row.get("last_completed"))),
        "last inspection",
    )
    return _add_months(prior, months) if prior is not None else None


class ComplianceCalendarStore:
    """Persist only assembled compliance rows in ``comp_calendar``."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if isinstance(db_path, CreConfig):
            resolved = db_path.cache_db_path
        else:
            resolved = db_path or (config or CreConfig()).cache_db_path
        self.db_path = Path(resolved).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS comp_calendar (
                asset_id TEXT NOT NULL,
                obligation_key TEXT NOT NULL,
                category TEXT NOT NULL,
                obligation TEXT NOT NULL,
                due_date TEXT,
                cadence TEXT NOT NULL,
                source_label TEXT NOT NULL,
                source_url TEXT,
                source_last_verified TEXT,
                status TEXT NOT NULL,
                notes TEXT NOT NULL,
                PRIMARY KEY(asset_id, obligation_key)
            );
            CREATE INDEX IF NOT EXISTS idx_comp_calendar_due
                ON comp_calendar(due_date, asset_id, obligation_key);
            """
        )
        return connection

    @staticmethod
    def _row(
        asset_id: str,
        obligation_key: str,
        category: str,
        obligation: str,
        due: date | None,
        cadence: str,
        source_label: str,
        source_url: str | None,
        source_last_verified: str | None,
        notes: str,
    ) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "asset": asset_id,
            "obligation_key": obligation_key,
            "category": category,
            "obligation": obligation,
            "due_date": due.isoformat() if due is not None else None,
            "cadence": cadence,
            "source_label": source_label,
            "source_url": source_url,
            "source_last_verified": source_last_verified,
            "status": "SCHEDULED" if due is not None else "DATE_INPUT_REQUIRED",
            "notes": notes,
        }

    def compliance_calendar(
        self,
        asset: Mapping[str, Any] | None,
        *,
        as_of: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(asset, Mapping):
            raise TypeError("asset must be a mapping")
        current = _day(as_of, "as_of", default=date.today())
        assert current is not None
        identifier = _asset_id(asset)
        state = str(asset.get("state") or "").strip().upper()
        obligations: list[dict[str, Any]] = []
        unknowns: list[dict[str, str]] = []

        tax_rule = PROPERTY_TAX_REGISTRY.get(state)
        if tax_rule is None:
            unknowns.append(
                {
                    "category": "property_tax",
                    "status": "UNKNOWN",
                    "reason": f"No state planning convention is registered for {state or 'unspecified state'}; obtain the actual tax bill.",
                }
            )
        else:
            for month, day_number, installment in tax_rule["installments"]:
                obligations.append(
                    self._row(
                        identifier,
                        f"property_tax:{state}:{month:02d}-{day_number:02d}",
                        "property_tax",
                        f"Property tax — {installment}",
                        _next_occurrence(current, month, day_number),
                        "annual",
                        str(tax_rule["source_label"]),
                        str(tax_rule["source_url"]),
                        str(tax_rule["last_verified"]),
                        str(tax_rule["notes"]),
                    )
                )

        seen_systems: set[str] = set()
        for system in _systems(asset):
            resolved = _system_rule(
                system.get("system", system.get("type", system.get("name")))
            )
            if resolved is None:
                unknowns.append(
                    {
                        "category": "inspection",
                        "status": "UNKNOWN",
                        "reason": f"No inspection convention is registered for {system.get('system', system.get('type', system.get('name', 'unspecified system')))}.",
                    }
                )
                continue
            key, rule = resolved
            if key in seen_systems:
                continue
            seen_systems.add(key)
            due = _due_from_input(system, int(rule["months"]))
            obligations.append(
                self._row(
                    identifier,
                    f"inspection:{key}",
                    "inspection",
                    str(rule["obligation"]),
                    due,
                    str(rule["cadence"]),
                    str(rule["source_label"]),
                    str(rule["source_url"]),
                    str(rule["last_verified"]),
                    (
                        "No completion date was supplied; enter the last inspection or next due date. "
                        if due is None
                        else "Date calculated from caller-supplied inspection history or next_due. "
                    )
                    + "Verify applicability and frequency with the local AHJ.",
                )
            )

        raw_licenses = asset.get("licenses", [])
        if isinstance(raw_licenses, Mapping):
            raw_licenses = [raw_licenses]
        if raw_licenses is None:
            raw_licenses = []
        if isinstance(raw_licenses, (str, bytes)) or not isinstance(raw_licenses, Sequence):
            raise TypeError("asset.licenses must be a sequence")
        for index, license_row in enumerate(raw_licenses):
            if not isinstance(license_row, Mapping):
                raise TypeError("each asset license must be a mapping")
            name = _text(license_row.get("name", license_row.get("license"))) or f"License {index + 1}"
            due = _day(
                license_row.get("next_due", license_row.get("expiry", license_row.get("due_date"))),
                f"license {name} due date",
            )
            source = _text(license_row.get("source_label", license_row.get("source")))
            obligations.append(
                self._row(
                    identifier,
                    f"license:{index}:{name.casefold()}",
                    "license",
                    f"{name} renewal",
                    due,
                    _text(license_row.get("cadence")) or "caller-supplied renewal cycle",
                    source or "INPUT RECORD — licensing authority source not supplied",
                    _text(license_row.get("source_url")),
                    _text(license_row.get("last_verified")),
                    "Caller-supplied license record; verify with the issuing authority.",
                )
            )

        with self._connect() as connection:
            connection.execute("DELETE FROM comp_calendar WHERE asset_id=?", (identifier,))
            for row in obligations:
                connection.execute(
                    """
                    INSERT INTO comp_calendar(
                        asset_id, obligation_key, category, obligation, due_date,
                        cadence, source_label, source_url, source_last_verified,
                        status, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["asset_id"],
                        row["obligation_key"],
                        row["category"],
                        row["obligation"],
                        row["due_date"],
                        row["cadence"],
                        row["source_label"],
                        row["source_url"],
                        row["source_last_verified"],
                        row["status"],
                        row["notes"],
                    ),
                )
        return {
            "asset_id": identifier,
            "as_of": current.isoformat(),
            "obligations": obligations,
            "unknowns": unknowns,
            "disclaimer": CALENDAR_DISCLAIMER,
        }

    def upcoming(
        self,
        days: int | None = 90,
        *,
        as_of: date | datetime | str | None = None,
        asset: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError("days must be a non-negative integer")
        current = _day(as_of, "as_of", default=date.today())
        assert current is not None
        through = current + timedelta(days=days)
        params: list[Any] = [current.isoformat(), through.isoformat()]
        where = "due_date >= ? AND due_date <= ?"
        if asset is not None:
            where += " AND asset_id = ?"
            params.append(str(asset))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM comp_calendar WHERE {where} ORDER BY due_date, asset_id, obligation_key",
                params,
            ).fetchall()
        obligations = []
        for stored in rows:
            row = dict(stored)
            row["asset"] = row["asset_id"]
            obligations.append(row)
        return {
            "as_of": current.isoformat(),
            "through": through.isoformat(),
            "days": days,
            "obligations": obligations,
            "disclaimer": CALENDAR_DISCLAIMER,
        }


def compliance_calendar(
    asset: Mapping[str, Any] | None,
    db_path: str | Path | CreConfig | None = None,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Assemble and persist cited recurring obligations for one asset."""

    return ComplianceCalendarStore(db_path).compliance_calendar(asset, as_of=as_of)


def upcoming(
    days: int | None = 90,
    db_path: str | Path | CreConfig | None = None,
    as_of: date | datetime | str | None = None,
    asset: str | None = None,
) -> dict[str, Any]:
    """Return persisted obligations due inclusively inside the look-ahead window."""

    try:
        return ComplianceCalendarStore(db_path).upcoming(days, as_of=as_of, asset=asset)
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "CALENDAR_DISCLAIMER",
    "PROPERTY_TAX_REGISTRY",
    "SYSTEM_REGISTRY",
    "ComplianceCalendarStore",
    "compliance_calendar",
    "upcoming",
]
