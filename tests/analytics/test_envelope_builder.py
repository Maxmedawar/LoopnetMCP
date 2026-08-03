"""Hand calculations and defensive boundaries for the zoning envelope."""

from cre_mcp.analytics.envelope import zoning_envelope


def test_setbacks_reduce_footprint_exactly_and_caps_gba() -> None:
    result = zoning_envelope(
        {
            "lot": {"sf": 20_000, "width": 100, "depth": 200},
            "setbacks": {"front": 20, "side": 5, "rear": 10},
            "far": 1.5,
            "max_height_ft": 48,
            "parking_ratio": 2,
            "zoning_code_link": "https://codes.example.test/adopted-zone",
        }
    )

    assert result["buildable_width_ft"] == 90
    assert result["buildable_depth_ft"] == 170
    assert result["footprint_after_setbacks_sf"] == 15_300
    assert result["far_capped_gba_sf"] == 30_000
    assert result["height_implied_floors"] == 4
    assert result["height_capped_gba_sf"] == 61_200
    assert result["modeled_gba_sf"] == 30_000
    assert result["binding_control"] == "FAR"
    assert result["parking"]["required_spaces_rounded_up"] == 60
    assert result["parking"]["implied_surface_land_take_sf"] == 19_500
    assert result["conventions"]["floor_to_floor_ft"] == 12
    assert result["caveat"].startswith(
        "code values must come from the adopted code — see zoning_code_link"
    )


def test_nullable_controls_stay_unknown_and_nested_typos_are_visible() -> None:
    result = zoning_envelope(
        {
            "lot": {"sf": 10_000, "width": 100, "depth": 100, "sff": 99_999},
            "setbacks": {"front": 0, "side": 0, "rear": 0, "frnot": 50},
            "far": None,
            "max_height_ft": None,
            "parking_ratio": None,
            "mystery_overlay": "ignored only with visibility",
        }
    )

    assert result["footprint_after_setbacks_sf"] == 10_000
    assert result["modeled_gba_sf"] is None
    assert result["parking"]["implied_surface_land_take_sf"] is None
    assert result["unrecognized_inputs"] == [
        "code_params.lot.sff",
        "code_params.mystery_overlay",
        "code_params.setbacks.frnot",
    ]
    assert any("far was not supplied" in note for note in result["warnings"])


def test_invalid_structured_code_is_contained_at_boundary() -> None:
    result = zoning_envelope(None)
    assert result == {"error": "zoning_envelope: code_params must be a mapping"}

    missing_setbacks = zoning_envelope(
        {"lot": {"sf": 10_000, "width": 100, "depth": 100}}
    )
    assert missing_setbacks["error"].startswith("zoning_envelope:")
    assert "setbacks" in missing_setbacks["error"]
