"""Deterministic resource lifecycle coverage for the admin control store."""

from __future__ import annotations

import sqlite3

from cre_mcp.platform.admin import AdminControlStore


def test_repeated_store_construction_closes_every_sqlite_connection(
    tmp_path,
    monkeypatch,
):
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []
    closed: set[int] = set()

    class TrackingConnection(sqlite3.Connection):
        def close(self) -> None:
            closed.add(id(self))
            super().close()

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, factory=TrackingConnection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    try:
        for _ in range(5):
            AdminControlStore(tmp_path / "resource-lifecycle.db")
            assert {id(connection) for connection in opened} == closed
    finally:
        for connection in opened:
            if id(connection) not in closed:
                connection.close()
