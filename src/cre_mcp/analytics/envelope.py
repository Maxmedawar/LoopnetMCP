"""Pure buildable-envelope arithmetic on user-supplied zoning controls."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any


CODE_CAVEAT = (
    "code values must come from the adopted code — see zoning_code_link. "
    "Confirm overlays, measurement rules, exceptions, easements, fire access, "
    "open-space, loading, landscaping, and entitlement conditions with the jurisdiction."
)
DEFAULT_FLOOR_TO_FLOOR_FT = Decimal("12")
DEFAULT_PARKING_SPACE_LAND_SF = Decimal("325")


def _decimal(
    value: Any,
    label: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{label} must be a finite {qualifier} number")
    return result


def _optional_decimal(
    value: Any,
    label: str,
    *,
    allow_zero: bool = True,
) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value, label, allow_zero=allow_zero)


def _json_number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def zoning_envelope(code_params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Calculate a dimensional envelope without looking up or interpreting code.

    ``parking_ratio`` is treated as required spaces per 1,000 square feet of
    modeled GBA.  Surface parking land take uses an exposed gross-area-per-space
    convention (stall plus circulation), not a surveyed layout.  ``side`` is
    applied to both sides of the lot.
    """

    try:
        if code_params is None or not isinstance(code_params, Mapping):
            raise ValueError("code_params must be a mapping")

        top_fields = {
            "far",
            "max_height_ft",
            "setbacks",
            "parking_ratio",
            "lot",
            "zoning_code_link",
            "floor_to_floor_ft",
            "parking_space_land_sf",
        }
        unrecognized = [
            f"code_params.{key}" for key in code_params if key not in top_fields
        ]

        lot = code_params.get("lot")
        if not isinstance(lot, Mapping):
            raise ValueError("code_params.lot must be a mapping")
        unrecognized.extend(
            f"code_params.lot.{key}" for key in lot if key not in {"sf", "width", "depth"}
        )
        lot_sf = _decimal(lot.get("sf"), "code_params.lot.sf", allow_zero=False)
        lot_width = _decimal(
            lot.get("width"), "code_params.lot.width", allow_zero=False
        )
        lot_depth = _decimal(
            lot.get("depth"), "code_params.lot.depth", allow_zero=False
        )

        setbacks = code_params.get("setbacks")
        if not isinstance(setbacks, Mapping):
            raise ValueError("code_params.setbacks must be a mapping")
        unrecognized.extend(
            f"code_params.setbacks.{key}"
            for key in setbacks
            if key not in {"front", "side", "rear"}
        )
        front = _decimal(setbacks.get("front"), "code_params.setbacks.front")
        side = _decimal(setbacks.get("side"), "code_params.setbacks.side")
        rear = _decimal(setbacks.get("rear"), "code_params.setbacks.rear")

        far = _optional_decimal(code_params.get("far"), "code_params.far")
        max_height = _optional_decimal(
            code_params.get("max_height_ft"), "code_params.max_height_ft"
        )
        parking_ratio = _optional_decimal(
            code_params.get("parking_ratio"), "code_params.parking_ratio"
        )
        floor_to_floor = (
            DEFAULT_FLOOR_TO_FLOOR_FT
            if code_params.get("floor_to_floor_ft") in (None, "")
            else _decimal(
                code_params.get("floor_to_floor_ft"),
                "code_params.floor_to_floor_ft",
                allow_zero=False,
            )
        )
        parking_space_land = (
            DEFAULT_PARKING_SPACE_LAND_SF
            if code_params.get("parking_space_land_sf") in (None, "")
            else _decimal(
                code_params.get("parking_space_land_sf"),
                "code_params.parking_space_land_sf",
                allow_zero=False,
            )
        )

        buildable_width = max(Decimal("0"), lot_width - side * Decimal("2"))
        buildable_depth = max(Decimal("0"), lot_depth - front - rear)
        footprint = buildable_width * buildable_depth
        dimensioned_lot_sf = lot_width * lot_depth

        far_capped_gba = None if far is None else lot_sf * far
        height_floors = (
            None
            if max_height is None
            else int(
                (max_height / floor_to_floor).to_integral_value(rounding=ROUND_FLOOR)
            )
        )
        height_capped_gba = (
            None if height_floors is None else footprint * Decimal(height_floors)
        )
        caps = [cap for cap in (far_capped_gba, height_capped_gba) if cap is not None]
        modeled_gba = min(caps) if caps else None
        if far_capped_gba is not None and height_capped_gba is not None:
            binding_control = (
                "FAR"
                if far_capped_gba < height_capped_gba
                else "HEIGHT"
                if height_capped_gba < far_capped_gba
                else "FAR_AND_HEIGHT"
            )
        elif far_capped_gba is not None:
            binding_control = "FAR_ONLY_MODELED"
        elif height_capped_gba is not None:
            binding_control = "HEIGHT_ONLY_MODELED"
        else:
            binding_control = "UNKNOWN_NO_GBA_CONTROL_SUPPLIED"

        parking_spaces_raw = (
            None
            if parking_ratio is None or modeled_gba is None
            else modeled_gba / Decimal("1000") * parking_ratio
        )
        parking_spaces = (
            None
            if parking_spaces_raw is None
            else int(parking_spaces_raw.to_integral_value(rounding=ROUND_CEILING))
        )
        parking_land_take = (
            None
            if parking_spaces is None
            else Decimal(parking_spaces) * parking_space_land
        )

        warnings: list[str] = []
        if dimensioned_lot_sf != lot_sf:
            warnings.append(
                "lot.sf differs from lot.width × lot.depth; supplied lot.sf was used for FAR "
                "and dimensions were used for the setback footprint."
            )
        if buildable_width == 0 or buildable_depth == 0:
            warnings.append("Supplied setbacks leave no positive buildable footprint.")
        if far is None:
            warnings.append("far was not supplied; no FAR cap was applied.")
        if max_height is None:
            warnings.append("max_height_ft was not supplied; no height cap was applied.")
        if parking_ratio is None:
            warnings.append("parking_ratio was not supplied; parking land take is unknown.")
        elif modeled_gba is None:
            warnings.append("parking land take cannot be calculated without modeled GBA.")
        if parking_land_take is not None and parking_land_take > lot_sf:
            warnings.append(
                "The convention-based surface parking land take exceeds supplied lot area; "
                "structured, shared, reduced, or off-site parking may change feasibility."
            )

        zoning_code_link = code_params.get("zoning_code_link")
        if zoning_code_link is not None and not isinstance(zoning_code_link, str):
            raise ValueError("code_params.zoning_code_link must be a string or null")

        return {
            "status": "STRUCTURED_CODE_CALCULATOR",
            "lot": {
                "supplied_sf": _json_number(lot_sf),
                "width_ft": _json_number(lot_width),
                "depth_ft": _json_number(lot_depth),
                "dimensioned_sf": _json_number(dimensioned_lot_sf),
            },
            "setbacks_ft": {
                "front": _json_number(front),
                "side_each": _json_number(side),
                "rear": _json_number(rear),
            },
            "buildable_width_ft": _json_number(buildable_width),
            "buildable_depth_ft": _json_number(buildable_depth),
            "footprint_after_setbacks_sf": _json_number(footprint),
            "buildable_footprint_sf": _json_number(footprint),
            "far": _json_number(far),
            "far_capped_gba_sf": _json_number(far_capped_gba),
            "max_height_ft": _json_number(max_height),
            "height_implied_floors": height_floors,
            "height_capped_gba_sf": _json_number(height_capped_gba),
            "modeled_gba_sf": _json_number(modeled_gba),
            "binding_control": binding_control,
            "parking_implied_land_take_sf": _json_number(parking_land_take),
            "parking": {
                "ratio_spaces_per_1,000_gba_sf": _json_number(parking_ratio),
                "required_spaces_raw": _json_number(parking_spaces_raw),
                "required_spaces_rounded_up": parking_spaces,
                "land_sf_per_space_convention": _json_number(parking_space_land),
                "implied_surface_land_take_sf": _json_number(parking_land_take),
            },
            "parking_implied_land_take_sf": _json_number(parking_land_take),
            "conventions": {
                "floor_to_floor_ft": _json_number(floor_to_floor),
                "floor_count_rounding": "round down to whole floors",
                "parking_space_land_sf": _json_number(parking_space_land),
                "parking_count_rounding": "round up to whole spaces",
                "side_setback_application": "applied once to each side",
            },
            "zoning_code_link": zoning_code_link,
            "unrecognized_inputs": sorted(set(unrecognized)),
            "warnings": warnings,
            "caveat": CODE_CAVEAT,
        }
    except Exception as exc:
        result: dict[str, Any] = {"error": f"zoning_envelope: {exc}"}
        if "unrecognized" in locals() and unrecognized:
            result["unrecognized_inputs"] = sorted(set(unrecognized))
        return result


__all__ = ["CODE_CAVEAT", "zoning_envelope"]
