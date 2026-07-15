"""Unknown check-size honesty and legacy buyer-table migration contracts."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.disposition import tools


def test_unknown_check_size_persists_and_matches_as_explicit_unknown(
    disposition_db,
):
    recorded = tools.record_buyer("Test LLC", "syndicator")

    assert "error" not in recorded
    assert recorded["check_size_min"] is None
    assert recorded["check_size_max"] is None

    with sqlite3.connect(disposition_db) as connection:
        stored = connection.execute(
            """
            SELECT check_size_min, check_size_max
            FROM disp_buyers
            WHERE buyer_id = ?
            """,
            (recorded["buyer_id"],),
        ).fetchone()
    assert stored == (None, None)

    result = tools.match_buyers(
        {"price": 5_000_000, "type": "industrial", "market": "Phoenix"}
    )

    assert "error" not in result
    match = result["matches"][0]
    assert match["buyer_id"] == recorded["buyer_id"]
    assert match["check_size_fit"] == "fit_unknown"
    assert match["fit_status"] == "fit_unknown"
    assert match["fit_score"] < match["fit_score_max"]
    unknown_size_credit = result["fit_rubric"][
        "unknown_check_size_neutral_credit"
    ]
    unknown_preference_credit = result["fit_rubric"][
        "unrecorded_preference_neutral_credit"
    ]
    assert 0 <= unknown_size_credit < result["fit_rubric"]["check_size"]
    assert match["fit_score"] == pytest.approx(
        unknown_size_credit + (2 * unknown_preference_credit)
    )
    size_reasons = [
        reason.casefold()
        for reason in match["fit_reasons"]
        if "check size" in reason.casefold() or "check-size" in reason.casefold()
    ]
    assert size_reasons
    assert any("unknown" in reason for reason in size_reasons)
    assert not any("no-fit" in reason or "perfect-fit" in reason for reason in size_reasons)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [(1_000_000, None), (None, 9_000_000)],
)
def test_one_sided_check_size_remains_unknown_for_matching(
    disposition_db,
    minimum,
    maximum,
):
    recorded = tools.record_buyer(
        "Partially Known Capital",
        "private",
        check_size_min=minimum,
        check_size_max=maximum,
        geographies=["Phoenix"],
        asset_types=["industrial"],
    )
    assert "error" not in recorded

    result = tools.match_buyers(
        {"price": 5_000_000, "type": "industrial", "market": "Phoenix"}
    )

    assert "error" not in result
    match = result["matches"][0]
    assert match["check_size_fit"] == "fit_unknown"
    assert match["fit_status"] == "fit_unknown"
    assert match["fit_score"] < match["fit_score_max"]
    assert any(
        "unknown" in reason.casefold()
        for reason in match["fit_reasons"]
        if "check size" in reason.casefold() or "check-size" in reason.casefold()
    )


@pytest.mark.parametrize(
    ("minimum", "maximum", "field", "message"),
    [
        ("not-a-number", None, "check_size_min", "must be numeric"),
        (None, "not-a-number", "check_size_max", "must be numeric"),
        (True, None, "check_size_min", "must be numeric"),
        (None, float("nan"), "check_size_max", "must be finite"),
    ],
)
def test_provided_garbage_check_size_still_returns_error_envelope(
    disposition_db,
    minimum,
    maximum,
    field,
    message,
):
    result = tools.record_buyer(
        "Garbage Size LLC",
        "private",
        check_size_min=minimum,
        check_size_max=maximum,
    )

    assert result == {"error": f"{field} {message}"}


def test_legacy_not_null_buyer_table_migrates_without_touching_other_tables(
    disposition_db,
):
    with sqlite3.connect(disposition_db) as connection:
        connection.executescript(
            """
            CREATE TABLE disp_buyers (
                buyer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                check_size_min REAL NOT NULL,
                check_size_max REAL NOT NULL,
                geographies TEXT NOT NULL DEFAULT '[]',
                asset_types TEXT NOT NULL DEFAULT '[]',
                financing_style TEXT,
                source TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                CHECK(type IN (
                    'institutional', 'private', '1031', 'owner_user', 'syndicator'
                )),
                CHECK(check_size_min >= 0),
                CHECK(check_size_max >= check_size_min)
            );
            CREATE INDEX idx_disp_buyers_type_size
                ON disp_buyers(type, check_size_min, check_size_max);
            CREATE TABLE dataroom_sentinel (
                sentinel_id INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            );
            INSERT INTO disp_buyers(
                buyer_id, name, type, check_size_min, check_size_max,
                geographies, asset_types, financing_style, source, notes, created_at
            ) VALUES (
                'legacy-buyer', 'Legacy Capital', 'institutional', 1000000, 9000000,
                '["Phoenix"]', '["industrial"]', 'cash', 'legacy-import',
                'must survive migration', '2026-07-01T12:00:00+00:00'
            );
            INSERT INTO dataroom_sentinel(sentinel_id, payload)
            VALUES (7, 'must remain untouched');
            """
        )
        sentinel_schema_before = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'dataroom_sentinel'
            """
        ).fetchone()

    matched = tools.match_buyers(
        {"price": 5_000_000, "type": "industrial", "market": "Phoenix"}
    )
    assert "error" not in matched
    legacy = next(
        buyer for buyer in matched["matches"] if buyer["buyer_id"] == "legacy-buyer"
    )
    assert legacy["name"] == "Legacy Capital"
    assert legacy["check_size_min"] == 1_000_000
    assert legacy["check_size_max"] == 9_000_000

    with sqlite3.connect(disposition_db) as connection:
        buyer_columns = {
            row[1]: {"type": row[2], "notnull": row[3]}
            for row in connection.execute("PRAGMA table_info(disp_buyers)")
        }
        buyer_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(disp_buyers)")
        }
        buyer_table_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'disp_buyers'
            """
        ).fetchone()[0]
        size_index_columns = [
            row[2]
            for row in connection.execute(
                "PRAGMA index_info(idx_disp_buyers_type_size)"
            )
        ]
        legacy_row = connection.execute(
            """
            SELECT buyer_id, name, check_size_min, check_size_max, notes
            FROM disp_buyers
            WHERE buyer_id = 'legacy-buyer'
            """
        ).fetchone()
        sentinel_schema = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'dataroom_sentinel'
            """
        ).fetchone()
        sentinel_row = connection.execute(
            "SELECT sentinel_id, payload FROM dataroom_sentinel"
        ).fetchone()

        invalid_insert = """
            INSERT INTO disp_buyers(
                buyer_id, name, type, check_size_min, check_size_max,
                geographies, asset_types, created_at
            ) VALUES (?, 'Invalid Buyer', 'private', ?, ?, '[]', '[]', ?)
        """
        for buyer_id, minimum, maximum in (
            ("negative-minimum", -1, None),
            ("negative-maximum", None, -1),
            ("reversed-range", 9_000_000, 1_000_000),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    invalid_insert,
                    (buyer_id, minimum, maximum, "2026-07-14T12:00:00+00:00"),
                )

    assert buyer_columns["check_size_min"]["notnull"] == 0
    assert buyer_columns["check_size_max"]["notnull"] == 0
    assert "idx_disp_buyers_type_size" in buyer_indexes
    assert size_index_columns == ["type", "check_size_min", "check_size_max"]
    normalized_sql = " ".join(buyer_table_sql.casefold().split())
    assert "check_size_min is null or check_size_min >= 0" in normalized_sql
    assert "check_size_max is null or check_size_max >= 0" in normalized_sql
    assert (
        "check_size_max is null or check_size_min is null "
        "or check_size_max >= check_size_min"
    ) in normalized_sql
    assert legacy_row == (
        "legacy-buyer",
        "Legacy Capital",
        1_000_000.0,
        9_000_000.0,
        "must survive migration",
    )
    assert sentinel_schema == sentinel_schema_before
    assert sentinel_row == (7, "must remain untouched")
