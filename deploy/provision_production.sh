#!/bin/zsh
# Provision the DURABLE PostgreSQL that private beta runs on, and apply every
# migration to it.
#
# This is not `local_staging.sh`. That one creates a disposable cluster and
# deletes it on exit, which is correct for proving the process starts and wrong
# for holding a customer's saved searches. This one creates a cluster that
# survives a reboot, in a directory you can back up.
#
# It is idempotent: run it again and it re-applies pending migrations without
# touching existing data.
#
# It does NOT install a launchd service, does NOT open a firewall port, and does
# NOT touch the running `secondbrain` tunnel or anything on port 8000
# (cre.anilo.ai). Starting on boot is a separate decision; see the note at the
# end.
set -e

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
DATA=${MEDAWARCRE_PGDATA:-$HOME/Library/Application Support/medawarcre/pgdata}
SOCK=${MEDAWARCRE_PGSOCK:-/tmp/medawarcre-pg}
PGPORT=${MEDAWARCRE_PGPORT:-54330}
DB=medawarcre

export LC_ALL=C
export LANG=C

INITDB=$(command -v initdb || echo /opt/homebrew/opt/postgresql@16/bin/initdb)
PGCTL=$(command -v pg_ctl || echo /opt/homebrew/opt/postgresql@16/bin/pg_ctl)
PSQL=$(command -v psql || echo /opt/homebrew/opt/postgresql@16/bin/psql)

mkdir -p "$SOCK"

if [ ! -f "$DATA/PG_VERSION" ]; then
  echo "--- initdb (first run) at $DATA"
  mkdir -p "$DATA"
  chmod 700 "$DATA"
  "$INITDB" -D "$DATA" -U postgres --auth-local=trust --auth-host=scram-sha-256 \
    -E UTF8 --locale=C >/dev/null
  FIRST_RUN=1
else
  echo "--- existing cluster at $DATA"
  FIRST_RUN=0
fi

if ! "$PGCTL" -D "$DATA" status >/dev/null 2>&1; then
  echo "--- starting cluster on $PGPORT (loopback socket only)"
  # listen_addresses='' means Unix socket only: PostgreSQL is not reachable
  # over TCP from anywhere, including this machine. Nothing should ever expose
  # the database, and this makes that structural rather than a firewall rule.
  "$PGCTL" -D "$DATA" \
    -o "-k $SOCK -p $PGPORT -c listen_addresses=''" \
    -l "$DATA/server.log" -w start
else
  echo "--- cluster already running"
fi

ADMIN="host=$SOCK port=$PGPORT dbname=postgres user=postgres"

if [ "$FIRST_RUN" = "1" ]; then
  echo "--- roles and database"
  "$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" \
    -f "$ROOT/deploy/postgres/bootstrap_roles.sql" >/dev/null
  "$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" \
    -c "CREATE DATABASE $DB OWNER medawarcre_migration" >/dev/null

  # One login per service role, each a member of exactly one group. Passwords
  # are generated here and printed ONCE; they are not stored by this script.
  # Put them in your secret store and inject them as the DSNs below.
  echo "--- service logins"
  for role in migration app admission oauth backup admin; do
    password=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)
    inherit="INHERIT TRUE"
    case "$role" in
      migration|admission|oauth) inherit="INHERIT FALSE" ;;
    esac
    "$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" -c "
      DROP ROLE IF EXISTS medawarcre_${role}_login;
      CREATE ROLE medawarcre_${role}_login LOGIN PASSWORD '${password}'
        $( [ "$inherit" = "INHERIT FALSE" ] && echo NOINHERIT );
      GRANT medawarcre_${role} TO medawarcre_${role}_login
        WITH ADMIN FALSE, ${inherit}, SET TRUE;
    " >/dev/null
    echo "    medawarcre_${role}_login  ${password}"
  done
  echo
  echo "    ^ Copy these into your secret store now. They are not saved here."
fi

export MEDAWARCRE_MIGRATION_DATABASE_URL="host=$SOCK port=$PGPORT dbname=$DB user=medawarcre_migration_login password=${MIGRATION_PASSWORD:-}"
if [ -z "${MIGRATION_PASSWORD:-}" ]; then
  # First run, or the caller did not supply it: use the local trust socket as
  # the cluster owner, which only works from this machine's filesystem.
  export MEDAWARCRE_MIGRATION_DATABASE_URL="host=$SOCK port=$PGPORT dbname=$DB user=postgres"
fi

echo "--- migrate"
PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" -m cre_mcp.postgres.cli migrate

echo
echo "Durable PostgreSQL is up."
echo "  data      $DATA"
echo "  socket    $SOCK"
echo "  port      $PGPORT (Unix socket only; no TCP listener)"
echo
echo "Back this up with deploy/DEPLOY.md's backup command, not with a file copy."
echo "To start it on boot, write a launchd plist for:"
echo "  $PGCTL -D \"$DATA\" -o \"-k $SOCK -p $PGPORT -c listen_addresses=''\" start"
echo "That is a deliberate decision, so this script does not make it for you."
