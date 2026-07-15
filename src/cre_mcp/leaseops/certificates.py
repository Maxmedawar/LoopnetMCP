"""Durable lease-certificate records, expiry radar, and requirement gaps."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.books.store import BookStore


CERTIFICATE_KINDS = frozenset({"coi", "guaranty", "letter_of_credit", "deposit"})
CERTIFICATE_STATUSES = frozenset(
    {
        "active",
        "received",
        "pending",
        "expired",
        "released",
        "replaced",
        "cancelled",
        "canceled",
        "waived",
        "returned",
    }
)
TERMINAL_STATUSES = frozenset(
    {"expired", "released", "replaced", "cancelled", "canceled", "waived", "returned"}
)
ELIGIBILITY_CONVENTION = (
    "A record is eligible when its entered status is not a known terminal status "
    "and its expiry is null or on/after as_of. Certificate amounts are compared "
    "individually and are never summed to manufacture a required limit."
)

_CERTIFICATE_KEYS = frozenset(
    {"tenancy_or_deal", "kind", "party", "amount_cents", "expires", "status", "doc_ref"}
)
_REQUIREMENT_KEYS = frozenset(
    {
        "kind",
        "party",
        "amount_cents",
        "required_amount_cents",
        "coverage_limit_cents",
        "clause_quote",
        "locator",
        "citation",
        "doc_ref",
        "requirement",
    }
)
_CITATION_KEYS = frozenset({"quote", "clause_quote", "locator", "page", "cell", "source", "doc_ref"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lo_certificates (
    tenancy_or_deal TEXT NOT NULL,
    kind TEXT NOT NULL,
    party TEXT NOT NULL,
    amount_cents INTEGER,
    expires TEXT,
    status TEXT NOT NULL,
    doc_ref TEXT,
    CHECK(kind IN ('coi', 'guaranty', 'letter_of_credit', 'deposit')),
    CHECK(amount_cents IS NULL OR amount_cents >= 0)
);
CREATE INDEX IF NOT EXISTS idx_lo_certificates_radar
    ON lo_certificates(tenancy_or_deal, expires, kind, party);
"""


def _unknown(mapping: Mapping[str, Any], allowed: frozenset[str], *, path: str) -> None:
    extras = sorted(str(key) for key in mapping if key not in allowed)
    if extras:
        raise ValueError(f"unrecognized inputs at {path}: {', '.join(extras)}")


def _text(value: Any, *, name: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text" + (" or null" if nullable else ""))
    normalized = value.strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _kind(value: Any, *, name: str = "kind") -> str:
    normalized = _text(value, name=name).strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized not in CERTIFICATE_KINDS:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(CERTIFICATE_KINDS))}")
    return normalized


def _cents(value: Any, *, name: str, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of cents" + (" or null" if nullable else ""))
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _status(value: Any) -> str:
    normalized = _text(value, name="status").casefold()
    if normalized not in CERTIFICATE_STATUSES:
        raise ValueError(
            f"status must be one of: {', '.join(sorted(CERTIFICATE_STATUSES))}"
        )
    return normalized


def _day(value: Any, *, name: str, nullable: bool = False) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if nullable:
            return None
        raise ValueError(f"{name} must be an ISO date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO date" + (" or null" if nullable else ""))
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _days(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("days must be a non-negative integer")
    if value < 0:
        raise ValueError("days must be a non-negative integer")
    return value


def _row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["certificate_id"] = int(row["certificate_id"])
    return result


def _eligible(record: Mapping[str, Any], as_of: date) -> tuple[bool, str | None]:
    status = str(record.get("status") or "").casefold()
    if status in TERMINAL_STATUSES:
        return False, f"entered status is {status}"
    raw_expiry = record.get("expires")
    if raw_expiry is not None and date.fromisoformat(str(raw_expiry)) < as_of:
        return False, "recorded expiry is before as_of"
    return True, None


class CertificateStore:
    """Own only ``lo_certificates`` in the shared SQLite cache."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        # BookStore supplies the repository's established cache-path contract.
        self.db_path = BookStore(db_path).db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(_SCHEMA)
        return connection

    def record_certificate(
        self,
        tenancy_or_deal: str | Mapping[str, Any],
        kind: str | None = None,
        party: str | None = None,
        amount_cents: int | None = None,
        expires: date | datetime | str | None = None,
        status: str | None = None,
        doc_ref: str | None = None,
    ) -> dict[str, Any]:
        """Append one entered certificate record without inferring missing values."""

        if isinstance(tenancy_or_deal, Mapping):
            if any(value is not None for value in (kind, party, amount_cents, expires, status, doc_ref)):
                raise ValueError("pass either a certificate mapping or individual fields, not both")
            certificate = tenancy_or_deal
            _unknown(certificate, _CERTIFICATE_KEYS, path="certificate")
            tenancy_or_deal = certificate.get("tenancy_or_deal")
            kind = certificate.get("kind")
            party = certificate.get("party")
            amount_cents = certificate.get("amount_cents")
            expires = certificate.get("expires")
            status = certificate.get("status")
            doc_ref = certificate.get("doc_ref")

        normalized = {
            "tenancy_or_deal": _text(tenancy_or_deal, name="tenancy_or_deal"),
            "kind": _kind(kind),
            "party": _text(party, name="party"),
            "amount_cents": _cents(amount_cents, name="amount_cents", nullable=True),
            "expires": (
                parsed.isoformat()
                if (parsed := _day(expires, name="expires", nullable=True)) is not None
                else None
            ),
            "status": _status(status),
            "doc_ref": _text(doc_ref, name="doc_ref", nullable=True),
        }
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO lo_certificates(
                    tenancy_or_deal, kind, party, amount_cents, expires, status, doc_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(normalized[key] for key in (
                    "tenancy_or_deal", "kind", "party", "amount_cents", "expires", "status", "doc_ref"
                )),
            )
            row = connection.execute(
                "SELECT rowid AS certificate_id, * FROM lo_certificates WHERE rowid=?",
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("certificate insert did not produce a durable row")
        return _row(row)

    def list_certificates(self, tenancy_or_deal: str | None = None) -> list[dict[str, Any]]:
        normalized_id = _text(tenancy_or_deal, name="tenancy_or_deal", nullable=True)
        clause = "WHERE tenancy_or_deal=?" if normalized_id is not None else ""
        values = (normalized_id,) if normalized_id is not None else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT rowid AS certificate_id, * FROM lo_certificates {clause}
                ORDER BY tenancy_or_deal COLLATE NOCASE, kind, party COLLATE NOCASE,
                         expires IS NULL, expires, rowid
                """,
                values,
            ).fetchall()
        return [_row(row) for row in rows]

    def expire_radar(
        self,
        days: int = 90,
        *,
        as_of: date | datetime | str | None = None,
        tenancy_or_deal: str | None = None,
    ) -> dict[str, Any]:
        """Report expired, expiring, and undated records using an inclusive window."""

        horizon_days = _days(days)
        current = _day(as_of, name="as_of", nullable=True) or date.today()
        window_end = current + timedelta(days=horizon_days)
        records = self.list_certificates(tenancy_or_deal)
        expiring: list[dict[str, Any]] = []
        expired: list[dict[str, Any]] = []
        undated: list[dict[str, Any]] = []
        inactive: list[dict[str, Any]] = []
        for record in records:
            status = str(record["status"]).casefold()
            if status in TERMINAL_STATUSES and status != "expired":
                inactive.append({**record, "eligibility_reason": f"entered status is {status}"})
                continue
            if status == "expired" and record["expires"] is None:
                expired.append(
                    {
                        **record,
                        "days_to_expiry": None,
                        "expiry_basis": "entered status is expired; no expiry date was recorded",
                    }
                )
                continue
            if record["expires"] is None:
                undated.append({**record, "days_to_expiry": None})
                continue
            expiry = date.fromisoformat(str(record["expires"]))
            item = {**record, "days_to_expiry": (expiry - current).days}
            if expiry < current or status == "expired":
                expired.append(item)
            elif expiry <= window_end:
                expiring.append(item)

        expiring.sort(key=lambda item: (item["days_to_expiry"], item["party"].casefold(), item["certificate_id"]))
        expired.sort(
            key=lambda item: (
                item["days_to_expiry"] is None,
                -(item["days_to_expiry"] or 0),
                item["party"].casefold(),
                item["certificate_id"],
            )
        )
        undated.sort(key=lambda item: (item["party"].casefold(), item["certificate_id"]))
        inactive.sort(key=lambda item: (item["party"].casefold(), item["certificate_id"]))

        return {
            "as_of": current.isoformat(),
            "days": horizon_days,
            "window_end": window_end.isoformat(),
            "window_convention": "expires is between as_of and window_end, inclusive",
            "tenancy_or_deal": _text(tenancy_or_deal, name="tenancy_or_deal", nullable=True),
            "expiring_count": len(expiring),
            "expired_count": len(expired),
            "undated_count": len(undated),
            "expiring": expiring,
            "expired": expired,
            "undated": undated,
            "inactive": inactive,
            "eligibility_convention": ELIGIBILITY_CONVENTION,
        }

    def gaps_report(
        self,
        tenancy_or_deal: str,
        requirements: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        *,
        as_of: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Compare entered lease requirements with recorded certificates."""

        normalized_id = _text(tenancy_or_deal, name="tenancy_or_deal")
        current = _day(as_of, name="as_of", nullable=True) or date.today()
        if requirements is None:
            raw_requirements: list[Mapping[str, Any]] = []
        elif isinstance(requirements, Mapping):
            raw_requirements = [requirements]
        elif isinstance(requirements, Sequence) and not isinstance(requirements, (str, bytes, bytearray)):
            raw_requirements = list(requirements)
        else:
            raise TypeError("requirements must be a mapping, sequence of mappings, or null")

        normalized_requirements: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_requirements):
            if not isinstance(raw, Mapping):
                raise TypeError(f"requirements[{index}] must be a mapping")
            _unknown(raw, _REQUIREMENT_KEYS, path=f"requirements[{index}]")
            amount_values = [
                raw[key]
                for key in ("amount_cents", "required_amount_cents", "coverage_limit_cents")
                if key in raw and raw[key] is not None
            ]
            normalized_amounts = {
                _cents(value, name=f"requirements[{index}].amount_cents") for value in amount_values
            }
            if len(normalized_amounts) > 1:
                raise ValueError(f"requirements[{index}] contains conflicting amount limits")
            citation = raw.get("citation")
            if citation is not None:
                if not isinstance(citation, Mapping):
                    raise TypeError(f"requirements[{index}].citation must be a mapping or null")
                _unknown(citation, _CITATION_KEYS, path=f"requirements[{index}].citation")
            normalized_requirements.append(
                {
                    "kind": _kind(raw.get("kind"), name=f"requirements[{index}].kind"),
                    "party": _text(raw.get("party"), name=f"requirements[{index}].party", nullable=True),
                    "required_amount_cents": next(iter(normalized_amounts), None),
                    "requirement": _text(raw.get("requirement"), name=f"requirements[{index}].requirement", nullable=True),
                    "citation": dict(citation) if citation is not None else {
                        "quote": raw.get("clause_quote"),
                        "locator": raw.get("locator"),
                        "doc_ref": raw.get("doc_ref"),
                    },
                }
            )

        records = self.list_certificates(normalized_id)
        comparisons: list[dict[str, Any]] = []
        for requirement in normalized_requirements:
            candidates = [
                record
                for record in records
                if record["kind"] == requirement["kind"]
                and (
                    requirement["party"] is None
                    or str(record["party"]).casefold() == str(requirement["party"]).casefold()
                )
            ]
            eligible: list[dict[str, Any]] = []
            ineligible: list[dict[str, Any]] = []
            for candidate in candidates:
                is_eligible, reason = _eligible(candidate, current)
                (eligible if is_eligible else ineligible).append(
                    candidate if is_eligible else {**candidate, "eligibility_reason": reason}
                )
            required_amount = requirement["required_amount_cents"]
            satisfying = [
                candidate
                for candidate in eligible
                if required_amount is None
                or (
                    candidate["amount_cents"] is not None
                    and int(candidate["amount_cents"]) >= int(required_amount)
                )
            ]
            if satisfying:
                status = "satisfied"
                reason = "At least one eligible record meets the entered requirement."
            elif eligible:
                status = "insufficient_amount"
                reason = "Eligible records exist, but none records an amount at or above the entered requirement."
            elif candidates:
                status = "expired_or_inactive"
                reason = "Matching records exist, but none is eligible as of the report date."
            else:
                status = "missing"
                reason = "No recorded certificate matches the entered kind and party."
            comparisons.append(
                {
                    "status": status,
                    "requirement": requirement,
                    "reason": reason,
                    "satisfying_certificates": satisfying,
                    "eligible_certificates": eligible,
                    "ineligible_certificates": ineligible,
                }
            )

        return {
            "tenancy_or_deal": normalized_id,
            "as_of": current.isoformat(),
            "requirements": comparisons,
            "gaps": [item for item in comparisons if item["status"] != "satisfied"],
            "gap_count": sum(item["status"] != "satisfied" for item in comparisons),
            "recorded_certificate_count": len(records),
            "eligibility_convention": ELIGIBILITY_CONVENTION,
            "input_scope": "Requirements are caller-entered lease facts; this report does not infer omitted COI limits.",
        }


def record_certificate(
    tenancy_or_deal: str | Mapping[str, Any],
    kind: str | None = None,
    party: str | None = None,
    amount_cents: int | None = None,
    expires: date | datetime | str | None = None,
    status: str | None = None,
    doc_ref: str | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Module-level implementation helper for the plain tools boundary."""

    return CertificateStore(db_path).record_certificate(
        tenancy_or_deal, kind, party, amount_cents, expires, status, doc_ref
    )


def expire_radar(
    days: int = 90,
    tenancy_or_deal: str | None = None,
    *,
    as_of: date | datetime | str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return CertificateStore(db_path).expire_radar(
        days, as_of=as_of, tenancy_or_deal=tenancy_or_deal
    )


def certificate_gaps(
    tenancy_or_deal: str,
    requirements: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    as_of: date | datetime | str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return CertificateStore(db_path).gaps_report(
        tenancy_or_deal, requirements, as_of=as_of
    )


__all__ = [
    "CERTIFICATE_KINDS",
    "CERTIFICATE_STATUSES",
    "ELIGIBILITY_CONVENTION",
    "CertificateStore",
    "certificate_gaps",
    "expire_radar",
    "record_certificate",
]
