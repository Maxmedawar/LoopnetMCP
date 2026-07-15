"""Construction closeout gap register and warranty-calendar handoff."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


CLOSEOUT_TYPES = (
    "warranty",
    "as_built",
    "o_and_m",
    "permit_final",
    "lien_release",
)

_TYPE_ALIASES = {
    "warranty": "warranty",
    "warranties": "warranty",
    "as_built": "as_built",
    "as_builts": "as_built",
    "asbuilt": "as_built",
    "o_and_m": "o_and_m",
    "o&m": "o_and_m",
    "operations_and_maintenance": "o_and_m",
    "permit_final": "permit_final",
    "final_permit": "permit_final",
    "final_inspection": "permit_final",
    "lien_release": "lien_release",
    "lien_waiver": "lien_release",
}


def _type(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    key = value.strip().casefold().replace("-", "_").replace(" ", "_")
    normalized = _TYPE_ALIASES.get(key)
    if normalized is None:
        raise ValueError(f"{field} must be one of {list(CLOSEOUT_TYPES)}")
    return normalized


def _date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)")


def _review_flags(item_type: str) -> dict[str, bool]:
    return {
        "gc_review_required": True,
        "architect_review_required": item_type
        in {"warranty", "as_built", "o_and_m", "permit_final"},
        "engineer_review_required": item_type in {"as_built", "o_and_m", "permit_final"},
        "inspector_review_required": item_type == "permit_final",
    }


def closeout_register(
    items: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return receipt gaps and warranty expirations for calendar handoff."""

    try:
        if items is None or isinstance(items, (str, bytes, bytearray)) or not isinstance(
            items, Sequence
        ):
            raise ValueError("items must be a list of objects")

        register: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        warranty_calendar: list[dict[str, Any]] = []
        warranties_missing_expiration: list[dict[str, Any]] = []
        observed_types: set[str] = set()

        for index, raw in enumerate(items):
            if not isinstance(raw, Mapping):
                raise ValueError(f"items[{index}] must be an object")
            item_type = _type(raw.get("type"), f"items[{index}].type")
            item_raw = raw.get("item")
            if not isinstance(item_raw, str) or not item_raw.strip():
                raise ValueError(f"items[{index}].item is required")
            if not isinstance(raw.get("received"), bool):
                raise ValueError(f"items[{index}].received must be boolean")
            received = raw["received"]
            expires = (
                _date(raw["expires"], f"items[{index}].expires")
                if raw.get("expires") is not None
                else None
            )
            observed_types.add(item_type)
            flags = _review_flags(item_type)
            row = {
                "index": index,
                "type": item_type,
                "item": item_raw.strip(),
                "received": received,
                "expires": expires.isoformat() if expires is not None else None,
                "basis_tag": "caller-stated closeout register; document content not verified",
                **flags,
            }
            register.append(row)
            if not received:
                gaps.append(
                    {
                        **row,
                        "gap": "not_received",
                        "severity": (
                            "critical"
                            if item_type in {"permit_final", "lien_release"}
                            else "open"
                        ),
                    }
                )

            if item_type == "warranty":
                if expires is None:
                    warranties_missing_expiration.append(
                        {
                            **row,
                            "gap": "warranty_expiration_not_supplied",
                        }
                    )
                elif received:
                    warranty_calendar.append(
                        {
                            "title": f"Warranty expires: {item_raw.strip()}",
                            "item": item_raw.strip(),
                            "expires": expires.isoformat(),
                            "date": expires.isoformat(),
                            "source_item_index": index,
                            "type": "warranty_expiration",
                            "basis_tag": "caller-stated received warranty expiration",
                            **flags,
                        }
                    )

        missing_types = [item_type for item_type in CLOSEOUT_TYPES if item_type not in observed_types]
        register_complete = not gaps and not missing_types and not warranties_missing_expiration
        return {
            "report_type": "construction_closeout_register",
            "register": register,
            "gaps": gaps,
            "gap_items": [item["item"] for item in gaps],
            "missing_required_types": missing_types,
            "warranty_calendar_handoff": warranty_calendar,
            "warranties_missing_expiration": warranties_missing_expiration,
            "closeout_complete": register_complete,
            "counts": {
                "items": len(register),
                "received": sum(1 for item in register if item["received"]),
                "not_received": len(gaps),
                "warranty_calendar_events": len(warranty_calendar),
            },
            "review_flags": {
                "gc_review_required": True,
                "architect_review_required": True,
                "engineer_review_required": True,
                "inspector_review_required": True,
            },
            "honesty": (
                "Receipt status and expiration dates are caller-stated. GC, architect, "
                "engineer, and inspector review flags identify handoff responsibility; "
                "this register does not authenticate documents or establish final approval."
            ),
        }
    except Exception as exc:
        return {"error": f"closeout_register: {exc}"}


__all__ = ["CLOSEOUT_TYPES", "closeout_register"]
