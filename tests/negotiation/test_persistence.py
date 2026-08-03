"""SQLite isolation, lifecycle, credibility, and append-only approval tests."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.negotiation import approvals, commitments


def _config(tmp_path) -> CreConfig:
    return CreConfig(cache_db_path=tmp_path / "negotiation.db")


def test_commitment_lifecycle_and_open_filter(tmp_path) -> None:
    config = _config(tmp_path)
    kept = commitments.record_commitment_note(
        "deal-1",
        "Seller will deliver the rent roll",
        "them",
        due="2026-07-20",
        config=config,
    )
    broken = commitments.record_commitment_note(
        "deal-1",
        "Seller will provide estoppels",
        "them",
        due="2026-07-21",
        config=config,
    )
    superseded = commitments.record_commitment_note(
        "deal-1",
        "We will close on July 31",
        "us",
        config=config,
    )
    still_open = commitments.record_commitment_note(
        "deal-1",
        "Broker will confirm access",
        "them",
        config=config,
    )

    commitments.update_commitment_status(kept["id"], "kept", config=config)
    commitments.update_commitment_status(broken["id"], "broken", config=config)
    commitments.update_commitment_status(
        superseded["id"], "superseded", config=config
    )

    all_rows = commitments.list_commitments("deal-1", config=config)
    assert {row["status"] for row in all_rows} == {
        "open",
        "kept",
        "broken",
        "superseded",
    }
    open_rows = commitments.open_commitments("deal-1", config=config)
    assert [row["id"] for row in open_rows] == [still_open["id"]]
    assert all(row["status"] == "open" for row in open_rows)


def test_broken_counter_is_labeled_credibility_input_not_proven_character(tmp_path) -> None:
    config = _config(tmp_path)
    one = commitments.record_commitment_note(
        "deal-cred", "Seller will send title exceptions", "them", config=config
    )
    two = commitments.record_commitment_note(
        "deal-cred", "Seller will deliver leases", "them", config=config
    )
    ours = commitments.record_commitment_note(
        "deal-cred", "We will return comments", "us", config=config
    )
    commitments.update_commitment_status(one["id"], "broken", config=config)
    commitments.update_commitment_status(two["id"], "broken", config=config)
    commitments.update_commitment_status(ours["id"], "broken", config=config)

    signal = commitments.broken_commitment_counter("deal-cred", config=config)

    assert signal["counterparty_broken_commitments"] == 2
    assert signal["broken_commitments"] == 3
    annotation = str(signal).casefold()
    assert "counterparty_track_record" in annotation
    assert "credib" in annotation
    assert "inference" in annotation or "input" in annotation


def test_commitment_enums_and_identifiers_are_validated(tmp_path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ValueError):
        commitments.record_commitment_note("", "Will deliver", "them", config=config)
    with pytest.raises(ValueError):
        commitments.record_commitment_note("deal", "", "them", config=config)
    with pytest.raises(ValueError):
        commitments.record_commitment_note("deal", "Will deliver", "broker", config=config)

    record = commitments.record_commitment_note(
        "deal", "Will deliver", "them", config=config
    )
    with pytest.raises(ValueError):
        commitments.update_commitment_status(record["id"], "maybe", config=config)


@pytest.mark.parametrize("source", ["note", "call", "email"])
def test_commitment_source_vocabulary_round_trips(tmp_path, source: str) -> None:
    config = _config(tmp_path)
    row = commitments.record_commitment_note(
        "deal-source",
        f"Promise captured from {source}",
        "them",
        source=source,
        config=config,
    )

    assert row["source"] == source


def test_negotiation_tables_are_owned_and_do_not_damage_existing_tables(tmp_path) -> None:
    config = _config(tmp_path)
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('preserve-me')")

    commitments.record_commitment_note(
        "deal", "Seller will send survey", "them", config=config
    )
    approvals.record_term_approval(
        "deal",
        "deposit",
        50_000,
        75_000,
        "Investment Committee",
        "Improved closing certainty",
        config=config,
    )

    with sqlite3.connect(config.cache_db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"sentinel", "neg_commitments", "neg_approvals"} <= tables
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserve-me"


def test_approval_log_records_who_accepted_each_nonstandard_term_and_why(tmp_path) -> None:
    config = _config(tmp_path)
    first = approvals.record_term_approval(
        "deal-approval",
        "deposit",
        50_000,
        75_000,
        "A. Acquisitions",
        "Seller accepted our financing contingency",
        config=config,
    )
    second = approvals.record_term_approval(
        "deal-approval",
        "dd_days",
        30,
        21,
        "Investment Committee",
        "Third-party reports are already complete",
        config=config,
    )

    rows = approvals.list_approvals("deal-approval", config=config)
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["standard_value"] == 50_000
    assert rows[0]["approved_value"] == 75_000
    assert rows[0]["approved_by"] == "A. Acquisitions"
    assert rows[0]["why"] == "Seller accepted our financing contingency"
    assert rows[0]["at"]
    assert rows[1]["approved_by"] == "Investment Committee"
    assert rows[1]["why"] == "Third-party reports are already complete"


def test_approval_log_has_no_mutation_api_and_rejects_raw_update_or_delete(tmp_path) -> None:
    config = _config(tmp_path)
    row = approvals.record_term_approval(
        "deal-append-only",
        "closing_days",
        45,
        30,
        "Investment Committee",
        "Quarter-end requirement",
        config=config,
    )

    assert not hasattr(approvals, "update_approval")
    assert not hasattr(approvals, "delete_approval")
    with sqlite3.connect(config.cache_db_path) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "UPDATE neg_approvals SET why='rewritten history' WHERE id=?",
                (row["id"],),
            )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM neg_approvals WHERE id=?", (row["id"],))

    persisted = approvals.list_approvals("deal-append-only", config=config)
    assert persisted[0]["why"] == "Quarter-end requirement"
