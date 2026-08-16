#!/bin/zsh
# Bring up private staging on this machine: a disposable PostgreSQL cluster,
# all migrations, and the real hosted MedawarCRE MCP process on 127.0.0.1:8791.
#
# This is the step that must pass before anything is pointed at Cloudflare. It
# is not a test harness -- it runs `python -m cre_mcp --http`, the same command
# the Dockerfile's CMD runs, through the same fail-closed persistence builder.
#
# Everything it creates lives under $WORK and is removed on exit. It binds one
# loopback listener on 8791 and nothing else. It does not touch port 8000, the
# running cloudflared tunnel, or any existing database.
#
# Usage:  zsh deploy/local_staging.sh
#         zsh deploy/local_staging.sh --hold     # leave it running until Ctrl-C
set -e

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
WORK=${WORK:-${TMPDIR:-/tmp}/medawarcre-staging}
PORT=${CRE_HTTP_PORT:-8791}
PGPORT=${PGPORT:-54329}
# The Unix socket path has a hard 103-byte limit, which a nested temp directory
# blows through on macOS. Keep this short and outside $WORK.
SOCK=${SOCK:-/tmp/mcre-stg-sock}

rm -rf "$WORK" "$SOCK"
mkdir -p "$WORK/pgdata" "$SOCK"

# Pinned for the same reason tests/postgres/conftest.py pins it: with LC_ALL
# unset, macOS makes the postmaster multithreaded during start-up and pg_ctl
# refuses to start the cluster.
export LC_ALL=C
export LANG=C

INITDB=$(command -v initdb || echo /opt/homebrew/opt/postgresql@16/bin/initdb)
PGCTL=$(command -v pg_ctl || echo /opt/homebrew/opt/postgresql@16/bin/pg_ctl)
PSQL=$(command -v psql || echo /opt/homebrew/opt/postgresql@16/bin/psql)

echo "--- initdb"
"$INITDB" -D "$WORK/pgdata" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null

echo "--- start cluster on $PGPORT"
"$PGCTL" -D "$WORK/pgdata" \
  -o "-F -k $SOCK -p $PGPORT -c listen_addresses=''" \
  -l "$WORK/pg.log" -w start

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  sleep 1
  "$PGCTL" -D "$WORK/pgdata" -m immediate -w stop >/dev/null 2>&1 || true
  rm -rf "$SOCK"
}
trap cleanup EXIT

DSN_BASE="host=$SOCK port=$PGPORT dbname=medawarcre_staging"
ADMIN="host=$SOCK port=$PGPORT dbname=postgres user=postgres"

echo "--- roles and database"
"$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" \
  -f "$ROOT/deploy/postgres/bootstrap_roles.sql" >/dev/null
"$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" \
  -c 'CREATE DATABASE medawarcre_staging OWNER medawarcre_migration' >/dev/null

# One login per service role, each a member of exactly one group. This mirrors
# what a real deployment injects: the application connection cannot migrate,
# the migration connection cannot serve requests, and admission and OAuth each
# reach only their own narrow function set.
"$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" -c "
CREATE ROLE staging_migration LOGIN NOINHERIT;
GRANT medawarcre_migration TO staging_migration WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
CREATE ROLE staging_app LOGIN;
GRANT medawarcre_app TO staging_app WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
CREATE ROLE staging_admission LOGIN NOINHERIT;
GRANT medawarcre_admission TO staging_admission WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
CREATE ROLE staging_oauth LOGIN NOINHERIT;
GRANT medawarcre_oauth TO staging_oauth WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
CREATE ROLE staging_backup LOGIN;
GRANT medawarcre_backup TO staging_backup WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
" >/dev/null

export MEDAWARCRE_MIGRATION_DATABASE_URL="$DSN_BASE user=staging_migration"
export MEDAWARCRE_DATABASE_URL="$DSN_BASE user=staging_app"
export MEDAWARCRE_APP_DATABASE_URL="$DSN_BASE user=staging_app"
export MEDAWARCRE_ADMISSION_DATABASE_URL="$DSN_BASE user=staging_admission"
export MEDAWARCRE_OAUTH_DATABASE_URL="$DSN_BASE user=staging_oauth"
export MEDAWARCRE_BACKUP_DATABASE_URL="$DSN_BASE user=staging_backup"

# Disposable placeholders so the production-secret preflight passes. Real
# secrets are injected at runtime by the deployment's managed store and never
# live in a file. Nothing here reaches a real provider: Clerk and Stripe are
# only contacted when a request needs them, and no staging request does.
export CRE_CLERK_SECRET_KEY="sk_test_local_staging_placeholder"
export CRE_STRIPE_API_KEY="sk_test_localstagingplaceholder"
export CRE_STRIPE_WEBHOOK_SECRET="whsec_local_staging_placeholder"
export CRE_SKOOL_WEBHOOK_SECRET="whsec_skool_local_staging_placeholder"

export PYTHONPATH="$ROOT/src"
export CRE_HTTP_HOST=127.0.0.1
export CRE_HTTP_PORT=$PORT
export CRE_CACHE_DB_PATH="$WORK/must-not-be-created.db"

echo "--- migrate"
"$ROOT/.venv/bin/python" -m cre_mcp.postgres.cli migrate

echo "--- start hosted MCP on 127.0.0.1:$PORT"
"$ROOT/.venv/bin/python" -m cre_mcp --http > "$WORK/server.log" 2>&1 &
SERVER_PID=$!

for attempt in $(seq 1 40); do
  curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT/mcp" 2>/dev/null && break
  sleep 0.5
done

echo "--- probe: an unauthenticated initialize must be refused, not served"
STATUS=$(curl -s -o "$WORK/probe.json" -w '%{http_code}' -m 5 \
  -X POST "http://127.0.0.1:$PORT/mcp" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"staging-probe","version":"1"}}}')
echo "    HTTP $STATUS"
[ "$STATUS" = "401" ] || { echo "FAIL: expected 401, got $STATUS"; exit 1; }

echo "--- probe: the hosted path created no local state file"
[ -e "$CRE_CACHE_DB_PATH" ] && { echo "FAIL: $CRE_CACHE_DB_PATH exists"; exit 1; }
echo "    OK"

echo
echo "Private staging is healthy on http://127.0.0.1:$PORT/mcp"
echo "Point the Cloudflare tunnel at that address; see deploy/cloudflared-config.example.yml."

if [ "$1" = "--hold" ]; then
  echo "Holding. Ctrl-C to stop."
  wait "$SERVER_PID"
fi
