# Deploy MedawarCRE MCP over HTTP with Cloudflare

This repository now contains the hosting artifacts; the actual host, Cloudflare account,
tunnel credentials, DNS hostname, Access policy, and production secrets are Max's steps.
Local execution remains stdio by default. The container opts into FastMCP Streamable HTTP at
`/mcp` on port `8000`.

## 1. Prepare server-only secrets

Create a file on the deployment host, outside the repository, and restrict it to its owner:

```bash
install -m 600 /dev/null /secure/path/cre-mcp.env
```

Put only the required `CRE_*` values in that file. API keys remain on the server; do not copy
them into Claude's MCP configuration or commit the file. `docker run --env-file` injects the
values into the container environment—it does not bake them into the image.

Optional paid integrations remain off unless their keys are set. A residential proxy can also
be enabled explicitly:

```dotenv
# Optional, pay-per-GB, OFF by default. Keep any proxy credentials server-side.
CRE_PROXY_URL=https://user:password@residential-proxy.example:443
```

LoopNet, Crexi, and Auction.com are more likely to block datacenter IPs through
Akamai/Cloudflare/Imperva. The proxy is therefore recommended for reliable hosted scraping,
but it is never required or auto-enabled. Confirm the provider's terms and cost controls first.
Government, county, market, and other non-scraper policies do not use this proxy.

## 2. Build and run the image

From the repository root on the host:

```bash
docker build -t medawar-cre-mcp:latest .
docker network create cre-mcp-net
docker run -d \
  --name cre-mcp \
  --restart unless-stopped \
  --init \
  --shm-size=1g \
  --network cre-mcp-net \
  --env-file /secure/path/cre-mcp.env \
  -v cre-mcp-cache:/home/cremcp/.cache/cre_mcp \
  medawar-cre-mcp:latest
docker logs -f cre-mcp
```

The image installs system Chromium and sets `CRE_BROWSER_PATH=/usr/bin/chromium`, preserving
nodriver challenge fallback. The named volume persists the SQLite cache, deal pipeline, due-
diligence state, exchange records, and outcomes across container replacements.

For a host-run tunnel instead of a cloudflared container, publish the origin only on loopback:

```bash
docker run -d \
  --name cre-mcp \
  --restart unless-stopped \
  --init \
  --shm-size=1g \
  --env-file /secure/path/cre-mcp.env \
  -v cre-mcp-cache:/home/cremcp/.cache/cre_mcp \
  -p 127.0.0.1:8000:8000 \
  medawar-cre-mcp:latest
```

Do not expose port 8000 publicly. Cloudflare should be the only public ingress.

## 3. Create the Cloudflare Tunnel

Install `cloudflared`, authenticate the deployment host, and create a named tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create medawar-cre
cloudflared tunnel route dns medawar-cre mcp.example.com
```

Copy `deploy/cloudflared-config.example.yml` to `~/.cloudflared/config.yml` for a host-run
tunnel or `/secure/path/cloudflared/config.yml` for the container-run tunnel. Replace the
tunnel UUID, credentials path, and hostname, then validate the selected config:

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://mcp.example.com/mcp
```

To use the example's `http://cre-mcp:8000` origin, run cloudflared on the shared network after
placing `config.yml` and the tunnel credential JSON in `/secure/path/cloudflared`:

```bash
docker run -d \
  --name cloudflared \
  --restart unless-stopped \
  --network cre-mcp-net \
  -v /secure/path/cloudflared:/etc/cloudflared:ro \
  cloudflare/cloudflared:latest \
  tunnel --config /etc/cloudflared/config.yml run medawar-cre
```

If cloudflared runs directly on the host instead, change the origin to
`http://localhost:8000`, use the loopback-published app command above, and run
`cloudflared tunnel run medawar-cre`. Keep the final `http_status:404` catch-all ingress rule.

## 4. Protect the MCP hostname with Cloudflare Access

In Cloudflare Zero Trust, create a self-hosted Access application for `mcp.example.com` and an
Allow policy restricted to Max's identity. Enable Managed OAuth for the MCP/CLI login flow, or
use a narrowly scoped Access service token for non-interactive clients. Do not leave the tunnel
hostname publicly callable merely because the origin itself is hidden.

If a service token is used, configure Cloudflare Access and the client together; never place its
secret in this repository. Cloudflare Access is the authentication gate for this artifact—the
application does not claim that an unauthenticated public HTTP endpoint is safe.

## 5. Connect Claude Code from Max's MacBook

After the tunnel and Access policy are live:

```bash
claude mcp add --transport http medawar-cre https://mcp.example.com/mcp
```

Open `/mcp` in Claude Code and complete the Cloudflare Access login in the browser. The MacBook
stores only the remote connection/auth session; CRE provider keys remain server-side.

## Verification and operations

- Confirm `https://mcp.example.com/mcp` is denied before Access authentication.
- Confirm Claude Code can list all 45 tools after login.
- Exercise one keyless market tool and one scraper tool; verify proxy usage/cost separately if
  `CRE_PROXY_URL` is enabled.
- Monitor container restarts, tunnel health, scraper blocking, proxy spend, cache volume, and
  the existing uncalibrated-score disclosure.
- Rotate API, proxy, tunnel, and Access credentials without rebuilding the image.

Cloudflare Tunnel is available without an upfront hosting fee. Cloudflare Containers is a
usage-based, pure-Cloudflare alternative if Max prefers Cloudflare to run the image instead of a
tunnel plus a separate Docker host. A Worker alone is not equivalent here because the browser
fallback requires a real Chromium-capable container.

## Responsibility boundary

The codebase is deployable, but Max must provision the host or Cloudflare Container, tunnel and
DNS, credentials, server-side secrets, Access policy, optional proxy, and MacBook Claude login.
Optional ATTOM/Regrid/RentCast/skiptrace/proxy services remain paid and off unless configured.
Before any real securities raise, a securities attorney must review and sign off. Deal scores
remain `UNCALIBRATED` screening signals until enough representative realized outcomes accrue and
the calibration gate passes.
