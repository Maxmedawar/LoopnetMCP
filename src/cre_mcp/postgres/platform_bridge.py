"""Run the platform authority stores against PostgreSQL without rewriting them.

The twelve stores in ``cre_mcp.platform`` hold the security semantics this
product is actually built on: refresh-family rotation, replay windows, grant
scope binding, append-only audit, single-writer admin mutation. They are also
written in SQLite's dialect. Rewriting several thousand lines of them by hand
to reach PostgreSQL would put every one of those semantics back on the table at
once, which is the opposite of what a launch needs.

So this module moves the dialect instead of the logic. It presents the exact
``sqlite3`` surface those stores use — ``execute`` returning a cursor,
``sqlite3.Row``-style rows, ``lastrowid``, ``total_changes``, the connection
context manager, and ``sqlite3.IntegrityError`` — over a psycopg connection,
and translates each statement on the way through.

What is translated, and why each one is safe:

``?`` -> ``%s``
    Scanned outside string literals and comments, so a ``?`` inside a quoted
    value is left alone. Literal ``%`` is doubled in the same pass, because
    psycopg parses the whole query for placeholders once parameters are bound.

``julianday(x)`` -> ``(x)::timestamptz``
    Every use is a comparison between two ``julianday`` values over columns
    holding ISO-8601 text. Casting both sides to ``timestamptz`` preserves the
    ordering exactly, which is the only property the comparisons rely on.

``datetime('now')`` -> ``to_char(now() at time zone 'utc', ...)``
    Reproduces SQLite's ``YYYY-MM-DD HH:MM:SS`` shape so the value round-trips
    through the same text columns. Any other ``datetime(...)`` argument raises
    rather than guessing.

``BEGIN IMMEDIATE`` -> ``pg_advisory_xact_lock``
    SQLite's ``BEGIN IMMEDIATE`` means "one writer at a time, starting now".
    A transaction-scoped advisory lock is that same guarantee, released on
    commit or rollback exactly as SQLite releases its write lock. Mapping it to
    a no-op would have quietly widened every check-then-write race the stores
    use it to close.

``PRAGMA`` and DDL -> skipped
    The hosted schema is owned by numbered migration ``0010``, not by whichever
    store opened a connection first. ``PRAGMA foreign_keys``/``busy_timeout``
    have no PostgreSQL equivalent to set per connection.

``CREATE TEMP TRIGGER admin_audit_callback_guard`` -> a transaction-local flag
    The one DDL statement that is not schema but a live security control:
    ``AdminControlStore._mutate`` installs it so a mutation callback cannot
    write its own audit row. Migration ``0010`` carries the permanent
    PostgreSQL trigger; this bridge translates the create/drop into the
    ``set_config`` calls that arm and disarm it, and tolerates the disarm
    running inside an already-failed transaction, which is exactly where the
    store's ``finally`` puts it.

The stores are not modified beyond routing ``_connect`` through
``cre_mcp.platform.dbapi``. With no backend installed they still open the same
SQLite file they always did.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any

import psycopg
from psycopg import pq
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_exact_group_session,
)

PLATFORM_SCHEMA = "medawarcre"

#: Transaction-scoped advisory lock standing in for SQLite's write lock.
PLATFORM_WRITE_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"medawarcre-platform-write-lock-v1").digest()[:8],
    byteorder="big",
    signed=True,
)

_ADMIN_GUARD_SETTING = "app.platform_admin_callback"
_ADMIN_GUARD_NAME = "admin_audit_callback_guard"

_SKIPPED_LEADING = frozenset(
    {
        "PRAGMA",
        "CREATE",
        "DROP",
        "ALTER",
        "REINDEX",
        "VACUUM",
        "ANALYZE",
        "ATTACH",
        "DETACH",
    }
)
_TRANSACTION_LEADING = frozenset(
    {"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE"}
)
_WRITE_LEADING = frozenset({"INSERT", "UPDATE", "DELETE"})

_INSERT_TARGET = re.compile(
    r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
_RETURNING = re.compile(r"\bRETURNING\b", re.IGNORECASE)
_DATETIME_NOW_ARG = re.compile(r"^\s*'now'\s*$", re.IGNORECASE)


class PlatformBridgeError(RuntimeError):
    """A statement this bridge refuses to guess at."""


class UnsafePlatformRoleError(RuntimeError):
    """The platform DSN can exceed the least-privilege application role."""


# --- statement scanning ------------------------------------------------------


def _spans(statement: str) -> list[tuple[int, int]]:
    """Return the [start, end) spans that are string literals or comments.

    Everything outside these spans is code the translator may rewrite.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        if char == "'":
            start = index
            index += 1
            while index < length:
                if statement[index] == "'":
                    if index + 1 < length and statement[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            spans.append((start, index))
            continue
        if char == '"':
            start = index
            index += 1
            while index < length and statement[index] != '"':
                index += 1
            index = min(index + 1, length)
            spans.append((start, index))
            continue
        if char == "-" and statement.startswith("--", index):
            start = index
            end = statement.find("\n", index)
            index = length if end == -1 else end
            spans.append((start, index))
            continue
        if char == "/" and statement.startswith("/*", index):
            start = index
            end = statement.find("*/", index + 2)
            index = length if end == -1 else end + 2
            spans.append((start, index))
            continue
        index += 1
    return spans


def _in_span(spans: Sequence[tuple[int, int]], position: int) -> bool:
    for start, end in spans:
        if start <= position < end:
            return True
        if start > position:
            break
    return False


def _leading_keyword(statement: str) -> str:
    """Return the first real keyword, ignoring leading whitespace/comments."""
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        if char.isspace():
            index += 1
            continue
        if statement.startswith("--", index):
            end = statement.find("\n", index)
            index = length if end == -1 else end + 1
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        break
    match = re.match(r"[A-Za-z_]+", statement[index:])
    return match.group(0).upper() if match else ""


def _match_call(statement: str, open_paren: int) -> int:
    """Return the index just past the ``)`` closing the call at ``open_paren``."""
    spans = _spans(statement)
    depth = 0
    index = open_paren
    while index < len(statement):
        if not _in_span(spans, index):
            if statement[index] == "(":
                depth += 1
            elif statement[index] == ")":
                depth -= 1
                if depth == 0:
                    return index + 1
        index += 1
    raise PlatformBridgeError("unbalanced parentheses in a platform statement")


def _rewrite_function(statement: str, name: str, build) -> str:
    """Rewrite every top-level call to ``name`` using ``build(inner)``."""
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){name}\s*\(", re.IGNORECASE)
    while True:
        spans = _spans(statement)
        found = None
        for match in pattern.finditer(statement):
            if not _in_span(spans, match.start()):
                found = match
                break
        if found is None:
            return statement
        open_paren = statement.index("(", found.end() - 1)
        close = _match_call(statement, open_paren)
        inner = statement[open_paren + 1 : close - 1]
        statement = statement[: found.start()] + build(inner) + statement[close:]


#: Identifiers SQLite accepts bare and PostgreSQL does not. The stores alias
#: joined tables as ``user`` and ``grant`` in twenty-three places; both are
#: PostgreSQL reserved words, so ``JOIN platform_users AS user`` is a syntax
#: error there and valid here. Quoting them in the translator keeps one rule in
#: one place instead of twenty-three edits to SQL that is already under test —
#: and it keeps working when the twenty-fourth is written.
_RESERVED_IDENTIFIERS = frozenset(
    {
        "all", "analyse", "analyze", "and", "any", "array", "as", "asc",
        "authorization", "both", "case", "cast", "check", "collate", "column",
        "constraint", "create", "current_date", "current_role", "current_time",
        "current_timestamp", "current_user", "default", "deferrable", "desc",
        "distinct", "do", "else", "end", "except", "false", "for", "foreign",
        "from", "grant", "group", "having", "in", "initially", "intersect",
        "into", "leading", "limit", "localtime", "localtimestamp", "not",
        "null", "offset", "on", "only", "or", "order", "placing", "primary",
        "references", "returning", "select", "session", "session_user", "some",
        "symmetric", "table", "then", "to", "trailing", "true", "union",
        "unique", "user", "using", "variadic", "when", "where", "window",
        "with",
    }
)


def _quote_reserved_identifiers(statement: str) -> str:
    """Double-quote reserved words used as an alias or a table qualifier."""
    alias = re.compile(r"(?<![A-Za-z0-9_])(AS\s+)([A-Za-z_]+)(?![A-Za-z0-9_.])",
                       re.IGNORECASE)
    qualifier = re.compile(r"(?<![A-Za-z0-9_.\"])([A-Za-z_]+)(\.)")

    def _rewrite(pattern: re.Pattern[str], build) -> None:
        nonlocal statement
        position = 0
        while True:
            spans = _spans(statement)
            match = None
            for candidate in pattern.finditer(statement, position):
                if not _in_span(spans, candidate.start()):
                    match = candidate
                    break
            if match is None:
                return
            replacement = build(match)
            if replacement is None:
                position = match.end()
                continue
            statement = (
                statement[: match.start()] + replacement + statement[match.end() :]
            )
            position = match.start() + len(replacement)

    _rewrite(
        alias,
        lambda match: (
            f'{match.group(1)}"{match.group(2)}"'
            if match.group(2).lower() in _RESERVED_IDENTIFIERS
            else None
        ),
    )
    _rewrite(
        qualifier,
        lambda match: (
            f'"{match.group(1)}".'
            if match.group(1).lower() in _RESERVED_IDENTIFIERS
            else None
        ),
    )
    return statement


def _translate_expressions(statement: str) -> str:
    statement = _quote_reserved_identifiers(statement)
    statement = _rewrite_function(
        statement, "julianday", lambda inner: f"(({inner})::timestamptz)"
    )

    def _datetime(inner: str) -> str:
        if _DATETIME_NOW_ARG.match(inner):
            return "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"
        raise PlatformBridgeError(
            "datetime() is translated only for the 'now' argument"
        )

    return _rewrite_function(statement, "datetime", _datetime)


def _convert_placeholders(statement: str) -> tuple[str, str]:
    """Return (bound_form, unbound_form).

    The bound form has ``?`` replaced by ``%s`` and every other ``%`` doubled,
    which is what psycopg requires once parameters are supplied. The unbound
    form leaves ``%`` alone, for statements executed with no parameters at all.
    """
    spans = _spans(statement)
    bound: list[str] = []
    unbound: list[str] = []
    for index, char in enumerate(statement):
        inside = _in_span(spans, index)
        if char == "?" and not inside:
            bound.append("%s")
            unbound.append("%s")
            continue
        if char == "%":
            bound.append("%%")
            unbound.append("%")
            continue
        bound.append(char)
        unbound.append(char)
    return "".join(bound), "".join(unbound)


@dataclass(frozen=True)
class Translated:
    """One translated statement and how the bridge must run it."""

    bound_sql: str
    unbound_sql: str
    kind: str  # "run" | "skip" | "lock" | "compat"
    insert_table: str | None = None
    wants_identity: bool = False


def translate(statement: str) -> Translated:
    """Translate one SQLite statement into its PostgreSQL execution plan."""
    keyword = _leading_keyword(statement)

    if keyword == "CREATE" and _ADMIN_GUARD_NAME in statement:
        return Translated(
            f"SELECT set_config('{_ADMIN_GUARD_SETTING}', 'on', true)",
            f"SELECT set_config('{_ADMIN_GUARD_SETTING}', 'on', true)",
            "compat",
        )
    if keyword == "DROP" and _ADMIN_GUARD_NAME in statement:
        return Translated(
            f"SELECT set_config('{_ADMIN_GUARD_SETTING}', 'off', true)",
            f"SELECT set_config('{_ADMIN_GUARD_SETTING}', 'off', true)",
            "compat",
        )
    if keyword in _SKIPPED_LEADING:
        return Translated("", "", "skip")
    if keyword in _TRANSACTION_LEADING:
        if keyword == "BEGIN" and re.search(
            r"\bIMMEDIATE\b|\bEXCLUSIVE\b", statement, re.IGNORECASE
        ):
            locking = f"SELECT pg_advisory_xact_lock({PLATFORM_WRITE_LOCK_ID})"
            return Translated(locking, locking, "lock")
        return Translated("", "", "skip")

    translated = _translate_expressions(statement)
    bound, unbound = _convert_placeholders(translated)

    insert_table = None
    wants_identity = False
    if keyword == "INSERT":
        match = _INSERT_TARGET.match(translated)
        if match is not None and _RETURNING.search(translated) is None:
            insert_table = match.group(1)
            wants_identity = True
    return Translated(bound, unbound, "run", insert_table, wants_identity)


# --- DB-API surface ----------------------------------------------------------


class BridgeRow(Mapping):
    """A row that answers to an index, a column name, and ``dict()``.

    ``sqlite3.Row`` supports all three and platform code uses all three.
    """

    __slots__ = ("_columns", "_values", "_index")

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._index = {name: position for position, name in enumerate(self._columns)}

    def keys(self) -> list[str]:  # sqlite3.Row.keys() returns a list
        return list(self._columns)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        if isinstance(key, slice):
            return self._values[key]
        try:
            return self._values[self._index[key]]
        except KeyError:
            raise IndexError(f"no such column: {key}") from None

    def __iter__(self) -> Iterator[Any]:
        # sqlite3.Row iterates its values, and dict(row) still works because
        # Mapping's keys() drives it.
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: object) -> bool:
        return key in self._index

    def __repr__(self) -> str:
        return f"BridgeRow({dict(zip(self._columns, self._values))!r})"


def _sqlite_error(error: psycopg.Error) -> sqlite3.Error:
    message = str(error).strip() or type(error).__name__
    if isinstance(error, psycopg.errors.IntegrityError):
        return sqlite3.IntegrityError(message)
    if isinstance(
        error, (psycopg.errors.OperationalError, psycopg.errors.InternalError)
    ):
        return sqlite3.OperationalError(message)
    return sqlite3.DatabaseError(message)


class BridgeCursor:
    """The subset of ``sqlite3.Cursor`` the platform stores actually use."""

    def __init__(self) -> None:
        self._rows: list[BridgeRow] = []
        self._position = 0
        self.lastrowid: int | None = None
        self.rowcount: int = -1
        self.description: Any = None

    def _load(self, cursor: psycopg.Cursor) -> None:
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        if cursor.description is None:
            return
        columns = [column.name for column in cursor.description]
        self._rows = [BridgeRow(columns, values) for values in cursor.fetchall()]

    def fetchone(self) -> BridgeRow | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self) -> list[BridgeRow]:
        rows = self._rows[self._position :]
        self._position = len(self._rows)
        return rows

    def fetchmany(self, size: int = 1) -> list[BridgeRow]:
        rows = self._rows[self._position : self._position + size]
        self._position += len(rows)
        return rows

    def __iter__(self) -> Iterator[BridgeRow]:
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def close(self) -> None:
        self._rows = []
        self._position = 0


class BridgeConnection:
    """A ``sqlite3.Connection`` work-alike backed by one psycopg connection."""

    def __init__(
        self,
        connection: psycopg.Connection,
        identity_tables: frozenset[str],
    ) -> None:
        self._connection = connection
        self._identity_tables = identity_tables
        self.total_changes = 0
        self.row_factory: Any = sqlite3.Row  # accepted and ignored
        self.is_platform_bridge = True

    # -- transaction control --------------------------------------------------

    def __enter__(self) -> "BridgeConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def commit(self) -> None:
        try:
            self._connection.commit()
        except psycopg.Error as error:
            raise _sqlite_error(error) from error

    def rollback(self) -> None:
        try:
            self._connection.rollback()
        except psycopg.Error as error:
            raise _sqlite_error(error) from error

    def close(self) -> None:
        # The pool owns the socket; the store's ``close`` must not return it
        # twice. Releasing happens in the backend's context manager.
        return None

    @property
    def in_failed_transaction(self) -> bool:
        return self._connection.info.transaction_status == pq.TransactionStatus.INERROR

    # -- statement execution --------------------------------------------------

    def execute(
        self, statement: str, parameters: Sequence[Any] | None = None
    ) -> BridgeCursor:
        plan = translate(statement)
        result = BridgeCursor()
        if plan.kind == "skip":
            return result
        if plan.kind == "compat" and self.in_failed_transaction:
            # The store disarms its guard from a ``finally`` that can run after
            # the very failure it is guarding against. Re-raising here would
            # replace the store's own exception with a transaction-state error.
            return result

        values = tuple(parameters) if parameters else ()
        sql_text = plan.bound_sql if values else plan.unbound_sql
        if plan.wants_identity and plan.insert_table in self._identity_tables:
            sql_text = f"{sql_text.rstrip().rstrip(';')} RETURNING id"

        try:
            with self._connection.cursor(row_factory=tuple_row) as cursor:
                cursor.execute(sql_text, values)
                if plan.wants_identity and plan.insert_table in self._identity_tables:
                    row = cursor.fetchone()
                    result.lastrowid = None if row is None else int(row[0])
                    result.rowcount = cursor.rowcount
                else:
                    result._load(cursor)
                if _leading_keyword(statement) in _WRITE_LEADING:
                    self.total_changes += max(cursor.rowcount, 0)
        except psycopg.Error as error:
            raise _sqlite_error(error) from error
        return result

    def executemany(
        self, statement: str, sequence: Sequence[Sequence[Any]]
    ) -> BridgeCursor:
        result = BridgeCursor()
        for parameters in sequence:
            result = self.execute(statement, parameters)
        return result

    def executescript(self, script: str) -> BridgeCursor:
        # Every caller of executescript is creating schema. Schema on this
        # backend is owned by migration 0010.
        return BridgeCursor()

    def cursor(self) -> "BridgeCursorProxy":
        return BridgeCursorProxy(self)


class BridgeCursorProxy:
    """``connection.cursor()`` for the few call sites that use it."""

    def __init__(self, connection: BridgeConnection) -> None:
        self._connection = connection
        self._last = BridgeCursor()

    def execute(
        self, statement: str, parameters: Sequence[Any] | None = None
    ) -> BridgeCursor:
        self._last = self._connection.execute(statement, parameters)
        return self._last

    def __getattr__(self, name: str) -> Any:
        return getattr(self._last, name)


# --- the backend -------------------------------------------------------------


class PostgresPlatformBackend:
    """Hand every platform store a PostgreSQL-backed connection.

    This keeps its own small pool rather than borrowing the certified runtime
    pool. That pool pins ``search_path`` to ``pg_catalog`` and requires a
    workspace authority context for every checkout, both correct for the
    request-scoped domain repositories and both wrong here: these stores run
    before a workspace exists, and they address their tables unqualified.
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 8,
        timeout: float = 30.0,
        application_name: str = "medawarcre-platform",
    ) -> None:
        if not dsn.strip():
            raise ValueError("a PostgreSQL DSN is required")
        self._dsn = dsn.strip()
        self._application_name = application_name
        self._identity_tables: frozenset[str] | None = None
        self._identity_lock = Lock()
        self._pool = ConnectionPool(
            self._dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=False,
            configure=self._configure,
            name="medawarcre-platform",
        )

    def _configure(self, connection: psycopg.Connection) -> None:
        # The same least-privilege assertion the certified runtime pool makes.
        # Without it a DSN that happens to log in as a superuser would run the
        # authority stores with every grant in migration 0010 bypassed, and
        # nothing downstream would notice: the queries would simply succeed.
        try:
            assert_exact_group_session(
                connection,
                "medawarcre_app",
                login_inherits=True,
                group_inherits=True,
            )
        except UnsafeDatabaseRoleError as error:
            raise UnsafePlatformRoleError(
                "platform database role violates the least-privilege contract"
            ) from error
        connection.execute(
            "SELECT set_config('search_path', %s, false), "
            "set_config('application_name', %s, false)",
            (f"{PLATFORM_SCHEMA}, pg_catalog", self._application_name),
        )
        connection.execute("SET TIME ZONE 'UTC'")
        connection.commit()

    def open(self, *, wait: bool = True) -> None:
        # Probe on a throwaway connection first. The pool swallows a configure
        # failure into a PoolTimeout after retrying, which turns "this DSN has
        # more privilege than the application role" — the exact thing worth
        # stopping for — into a thirty-second hang with the real reason only in
        # a log line.
        with psycopg.connect(self._dsn) as connection:
            self._configure(connection)
        self._pool.open(wait=wait)

    def close(self) -> None:
        self._pool.close()

    def _load_identity_tables(self) -> frozenset[str]:
        with self._identity_lock:
            if self._identity_tables is not None:
                return self._identity_tables
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT class.relname
                    FROM pg_class AS class
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = class.relnamespace
                    JOIN pg_attribute AS column_
                      ON column_.attrelid = class.oid
                    WHERE namespace.nspname = %s
                      AND class.relkind = 'r'
                      AND column_.attname = 'id'
                      AND column_.attnum > 0
                      AND NOT column_.attisdropped
                    """,
                    (PLATFORM_SCHEMA,),
                ).fetchall()
                connection.rollback()
            self._identity_tables = frozenset(str(row[0]) for row in rows)
            return self._identity_tables

    @contextmanager
    def connect(
        self, *, timeout: float = 30.0, transactional: bool = True
    ) -> Iterator[BridgeConnection]:
        identity_tables = self._load_identity_tables()
        with self._pool.connection(timeout=timeout) as raw:
            bridge = BridgeConnection(raw, identity_tables)
            try:
                if transactional:
                    with bridge:
                        yield bridge
                else:
                    yield bridge
                    bridge.commit()
            except BaseException:
                try:
                    raw.rollback()
                except psycopg.Error:
                    pass
                raise


__all__ = [
    "BridgeConnection",
    "BridgeCursor",
    "BridgeRow",
    "PLATFORM_SCHEMA",
    "PLATFORM_WRITE_LOCK_ID",
    "PlatformBridgeError",
    "UnsafePlatformRoleError",
    "PostgresPlatformBackend",
    "Translated",
    "translate",
]
