# Cutting over to medawarcre.com

Written 2026-08-16 after inspecting this machine. Everything below was verified
by command, not assumed.

## What is already true

| | |
| --- | --- |
| `cloudflared` | installed, `2026.6.0`, authenticated (`~/.cloudflared/cert.pem`) |
| `medawarcre.com` | live in your Cloudflare account (`addilyn`/`hunts.ns.cloudflare.com`) |
| apex `medawarcre.com` | proxied, resolves to `172.67.153.118` / `104.21.3.65`, **times out** — a DNS record with no working origin |
| `mcp.medawarcre.com` | does not exist — free |
| running tunnel | `secondbrain`, 4 live connections, serving `2f2e23db.anilo.ai` → `:8788` and `cre.anilo.ai` → `:8000` |
| `tandem-headscale` | exists, no connections |

Two consequences.

**Use a dedicated tunnel, not `secondbrain`.** Adding an ingress rule to the
running one means editing its config and restarting it, which drops
`cre.anilo.ai` and `2f2e23db.anilo.ai` while it reconnects. A second tunnel is
its own process, its own credentials, and cannot affect the first.

**Use `mcp.medawarcre.com`, not the apex.** The apex is claimed and proxied
already, and the customer surface eventually wants a browser-facing root for
sign-in. Putting an MCP endpoint there forecloses that and would collide with
whatever record is on it now.

## The two things that actually block a working deployment

The ingress is the easy part. Neither of these is.

### 1. A durable database

`deploy/local_staging.sh` creates a disposable cluster and deletes it on exit.
That is correct for proving the process starts and wrong for holding a
customer's saved searches. Run this once:

```
zsh deploy/provision_production.sh
```

It creates a cluster under `~/Library/Application Support/medawarcre/pgdata`
that survives a reboot, applies migrations `0001`–`0014`, and prints one
generated password per service login **once**. Put those in your secret store
immediately; the script does not save them.

The cluster listens on a Unix socket only — `listen_addresses=''` — so
PostgreSQL is not reachable over TCP from anywhere, including this machine.
That is structural rather than a firewall rule.

It does not install a launchd service. Starting on boot is a real decision and
the command to do it is printed at the end.

### 2. Real provider credentials

The process refuses to start without these, by design, and reports the missing
*names* before it opens a connection:

| Variable | What it is |
| --- | --- |
| `CRE_CLERK_SECRET_KEY` | Clerk backend key. Until this is real, nobody can sign in. |
| `CRE_STRIPE_API_KEY` | Stripe **test-mode** key. A live key is refused. |
| `CRE_STRIPE_WEBHOOK_SECRET` | Stripe signing secret |
| `CRE_SKOOL_WEBHOOK_SECRET` | Skool relay signing secret |
| `MEDAWARCRE_DATABASE_URL` and five siblings | from step 1 |

**Do not paste these into a chat, a file in this repo, or a shell command that
lands in history.** Put them in your secret store and inject them into the
process environment.

Until they are real, the endpoint would be publicly reachable and unable to
authenticate anyone. It fails closed — a `401` on every request — but a public
hostname that can only refuse is worse than no hostname.

## The cutover, once both are done

Each of these changes your Cloudflare account, so run them yourself.

```
# 1. A dedicated tunnel. Does not touch `secondbrain`.
cloudflared tunnel create medawarcre

# 2. Point the new subdomain at it. Not the apex.
cloudflared tunnel route dns medawarcre mcp.medawarcre.com

# 3. Write its config, using the UUID that step 1 printed.
cat > ~/.cloudflared/medawarcre.yml <<'YAML'
tunnel: <TUNNEL_UUID>
credentials-file: /Users/maxmedawar/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: mcp.medawarcre.com
    service: http://127.0.0.1:8791
  - service: http_status:404
YAML

# 4. Start the hosted process first, then the tunnel.
zsh deploy/local_staging.sh --hold      # or the production runner, once secrets are injected
cloudflared tunnel --config ~/.cloudflared/medawarcre.yml run medawarcre
```

Port **8791** deliberately. `8000` is `cre.anilo.ai` on the live tunnel and must
not be taken.

## What must not get an ingress rule

PostgreSQL. The Operations Console. The internal opportunity index. The only
thing that belongs on a public hostname is the customer MCP endpoint and the
sign-in screens it needs. The `http_status:404` catch-all above is what stops a
second hostname reaching this service by accident.

## Before you point a real customer at it

`docs/launch/PRODUCTION_READINESS.md` lists what is proven and what is not. The
three that are unproven against a real provider — Clerk in an actual browser,
Stripe against a real test account, and the Skool relay — are exactly the three
a first customer exercises in their first five minutes.

Bringing the hostname up is reversible. `cloudflared tunnel route dns` can be
repointed and the tunnel deleted. Admitting a real customer to an unproven
sign-in flow is not, because they experience it once.
