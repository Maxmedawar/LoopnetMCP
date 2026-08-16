"""Report the hosted readiness gate against the injected app DSN.

`build_postgres_hosted_persistence` runs this check before it binds a socket and
refuses to start if it fails. Running it during provisioning turns "the service
will not start and I do not know why" into a named code at the moment the
schema was created.
"""

from __future__ import annotations

import sys

from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.health import check_readiness
from cre_mcp.postgres.migrations import load_migrations
from cre_mcp.postgres.pool import PostgresDatabase


def main() -> int:
    try:
        settings = PostgresSettings.from_env()
    except (TypeError, ValueError) as error:
        print(f"    configuration invalid ({type(error).__name__})")
        return 1
    database = PostgresDatabase(settings)
    try:
        database.open(wait=True)
        readiness = check_readiness(database, expected=load_migrations())
    except Exception as error:
        # Never chained and never printed with the DSN: psycopg echoes the
        # connection string it could not parse, password included.
        print(f"    unavailable ({type(error).__name__})")
        return 1
    finally:
        database.close()
    print(f"    ok={readiness.ok} code={readiness.code}")
    if not readiness.ok:
        for field in ("missing_tables", "unexpected_tables", "missing_rls"):
            values = getattr(readiness, field, ())
            if values:
                print(f"    {field}: {list(values)[:8]}")
        if getattr(readiness, "schema_drift", False):
            print("    schema_drift: the catalog fingerprint differs from the pinned one")
    return 0 if readiness.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
