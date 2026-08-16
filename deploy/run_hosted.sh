#!/bin/zsh
# Run the hosted MedawarCRE MCP process against the DURABLE database, with
# secrets injected from files rather than from this script.
#
#   zsh deploy/run_hosted.sh            # run until Ctrl-C
#   zsh deploy/run_hosted.sh --check    # start, probe, stop, report
#
# Two files are read, neither of which is in the repository:
#
#   ~/Library/Application Support/medawarcre/database.env
#       written by provision_production.sh; the six service DSNs.
#
#   ~/Library/Application Support/medawarcre/providers.env
#       yours to create; the four provider credentials. A template is written
#       for you on first run if it is missing.
#
# Both must be mode 0600. This script refuses to read a file that anyone else
# on the machine can read, because a secret whose file is world-readable has
# already leaked whether or not anything read it yet.
set -e

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
SUPPORT=${MEDAWARCRE_SUPPORT_DIR:-$HOME/Library/Application Support/medawarcre}
DB_ENV="$SUPPORT/database.env"
PROVIDER_ENV="$SUPPORT/providers.env"
PORT=${CRE_HTTP_PORT:-8791}
MODE=${1:-run}

_require_private() {
  local path="$1"
  [ -f "$path" ] || return 1
  local mode
  # Absolute path: this runs in contexts with a minimal PATH where a bare
  # `stat` is not found, and an empty mode then compares unequal to 600 and
  # refuses a file that was perfectly fine.
  mode=$(/usr/bin/stat -f '%Lp' "$path")
  if [ "$mode" != "600" ]; then
    echo "REFUSED: $path is mode $mode; it must be 600" >&2
    echo "  chmod 600 '$path'" >&2
    exit 1
  fi
}

if ! _require_private "$DB_ENV"; then
  echo "REFUSED: $DB_ENV is missing." >&2
  echo "  Run: zsh deploy/provision_production.sh" >&2
  exit 1
fi

if [ ! -f "$PROVIDER_ENV" ]; then
  umask 077
  cat > "$PROVIDER_ENV" <<'TEMPLATE'
# MedawarCRE provider credentials. Mode 0600.
#
# Fill these in from each provider's own dashboard. Do not paste them into a
# chat, a commit, a shell command, or a log. The process refuses to start
# without them and names the missing variables before it opens a connection.
#
# Clerk — Backend API key. Until this is real, nobody can sign in.
CRE_CLERK_SECRET_KEY=
# Stripe — TEST-mode secret key. A live key (sk_live_...) is refused by config.
CRE_STRIPE_API_KEY=
# Stripe — webhook signing secret for the endpoint you point at /v1/webhooks/stripe
CRE_STRIPE_WEBHOOK_SECRET=
# Skool — signing secret for the relay that posts membership events
CRE_SKOOL_WEBHOOK_SECRET=
TEMPLATE
  chmod 600 "$PROVIDER_ENV"
  echo "Wrote a template to $PROVIDER_ENV (mode 0600)."
  echo "Fill in the four values, then run this again."
  exit 1
fi
_require_private "$PROVIDER_ENV"

set -a
. "$DB_ENV"
. "$PROVIDER_ENV"
set +a

missing=()
for name in CRE_CLERK_SECRET_KEY CRE_STRIPE_API_KEY CRE_STRIPE_WEBHOOK_SECRET \
            CRE_SKOOL_WEBHOOK_SECRET; do
  [ -n "${(P)name}" ] || missing+=("$name")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "REFUSED: these are empty in $PROVIDER_ENV:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo >&2
  echo "The process would start and then be unable to authenticate anyone." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src"
export CRE_HTTP_HOST=127.0.0.1
export CRE_HTTP_PORT=$PORT
# Loopback only. The tunnel is the sole intended path in; binding 0.0.0.0 would
# make the service reachable from the local network as well.
export CRE_CACHE_DB_PATH="$SUPPORT/must-not-be-created.db"

if [ "$MODE" = "--check" ]; then
  echo "--- start, probe, stop"
  "$ROOT/.venv/bin/python" -m cre_mcp --http > "$SUPPORT/run.log" 2>&1 &
  PID=$!
  trap '[ -n "$PID" ] && kill "$PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT/mcp" 2>/dev/null && break
    sleep 0.5
  done
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -X POST \
    "http://127.0.0.1:$PORT/mcp" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}')
  echo "    unauthenticated initialize -> HTTP $STATUS"
  [ "$STATUS" = "401" ] || { echo "FAIL: expected 401"; tail -20 "$SUPPORT/run.log"; exit 1; }
  [ -e "$CRE_CACHE_DB_PATH" ] && { echo "FAIL: local state file created"; exit 1; }
  echo "    no local state file"
  echo
  echo "Healthy on http://127.0.0.1:$PORT/mcp against the durable database."
  exit 0
fi

echo "Serving on http://127.0.0.1:$PORT/mcp — Ctrl-C to stop."
exec "$ROOT/.venv/bin/python" -m cre_mcp --http
