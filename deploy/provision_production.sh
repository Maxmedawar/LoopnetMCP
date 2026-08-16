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
ENV_FILE=${MEDAWARCRE_ENV_FILE:-$HOME/Library/Application Support/medawarcre/database.env}
PGPORT=${MEDAWARCRE_PGPORT:-54330}
DB=medawarcre

export LC_ALL=C
export LANG=C

# The environment variable each service role's DSN is injected as.
_dsn_var() {
  case "$1" in
    migration) echo MEDAWARCRE_MIGRATION_DATABASE_URL ;;
    app)       echo MEDAWARCRE_DATABASE_URL ;;
    admission) echo MEDAWARCRE_ADMISSION_DATABASE_URL ;;
    oauth)     echo MEDAWARCRE_OAUTH_DATABASE_URL ;;
    backup)    echo MEDAWARCRE_BACKUP_DATABASE_URL ;;
    admin)     echo MEDAWARCRE_WORKER_DATABASE_URL ;;
  esac
}

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

  # One login per service role, each a member of exactly one group.
  #
  # The passwords are written to a mode-0600 file and NEVER to stdout. The
  # first version of this script echoed them, which put six live credentials
  # into terminal scrollback, shell transcript and any log capturing this
  # run -- the exact thing deploy/DEPLOY.md's secret rules forbid, in the
  # script whose job is to establish them.
  echo "--- service logins"
  umask 077
  : > "$ENV_FILE"
  {
    echo "# MedawarCRE service DSNs. Generated $(date -u +%Y-%m-%dT%H:%M:%SZ)."
    echo "# Mode 0600. Move these into your managed secret store; this file is"
    echo "# a bootstrap artifact, not the production source of truth."
  } >> "$ENV_FILE"
  for role in migration app admission oauth backup admin; do
    password=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)
    inherit="INHERIT TRUE"
    noinherit=""
    case "$role" in
      migration|admission|oauth) inherit="INHERIT FALSE"; noinherit="NOINHERIT" ;;
    esac
    "$PSQL" --no-psqlrc -v ON_ERROR_STOP=1 -d "$ADMIN" -c "
      DROP ROLE IF EXISTS medawarcre_${role}_login;
      CREATE ROLE medawarcre_${role}_login LOGIN PASSWORD '${password}' ${noinherit};
      GRANT medawarcre_${role} TO medawarcre_${role}_login
        WITH ADMIN FALSE, ${inherit}, SET TRUE;
    " >/dev/null
    printf '%s="host=%s port=%s dbname=%s user=medawarcre_%s_login password=%s"\n' \
      "$(_dsn_var "$role")" "$SOCK" "$PGPORT" "$DB" "$role" "$password" >> "$ENV_FILE"
    unset password
    echo "    medawarcre_${role}_login  written"
  done
  chmod 600 "$ENV_FILE"
  echo
  echo "    Six DSNs written to $ENV_FILE (mode 0600). Nothing was printed."
fi

# Migrate as the dedicated migration login. `postgres` is a superuser and
# `assert_migration_session` refuses it -- the same exact-group check that
# refuses a superuser DSN everywhere else in this codebase. Using it here fails
# with `migration_failed` and no explanation, which is how the first run of
# this script failed.
set -a
. "$ENV_FILE"
set +a

echo "--- migrate"
PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" -m cre_mcp.postgres.cli migrate

# The same readiness gate `build_postgres_hosted_persistence` runs before it
# binds a socket. Checking it here means a schema problem surfaces during
# provisioning rather than as a refusal to start at cutover.
echo "--- readiness"
PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" "$ROOT/deploy/_readiness.py"

echo
echo "Durable PostgreSQL is up."
echo "  data      $DATA"
echo "  DSNs      $ENV_FILE (mode 0600)"
echo "  socket    $SOCK"
echo "  port      $PGPORT (Unix socket only; no TCP listener)"
echo
echo "Back this up with deploy/DEPLOY.md's backup command, not with a file copy."
echo "To start it on boot, write a launchd plist for:"
echo "  $PGCTL -D \"$DATA\" -o \"-k $SOCK -p $PGPORT -c listen_addresses=''\" start"
echo "That is a deliberate decision, so this script does not make it for you."
