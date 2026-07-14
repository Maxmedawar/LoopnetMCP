FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CRE_TRANSPORT=http \
    CRE_HTTP_HOST=0.0.0.0 \
    CRE_HTTP_PORT=8000 \
    CRE_BROWSER_PATH=/usr/bin/chromium \
    CRE_CACHE_DB_PATH=/home/cremcp/.cache/cre_mcp/cache.db

# Chromium pulls its remaining runtime dependencies. The explicit libraries are
# the headless/nodriver-critical set on the current Debian slim (Trixie) base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        fonts-liberation \
        libasound2t64 \
        libatk-bridge2.0-0t64 \
        libatk1.0-0t64 \
        libatspi2.0-0t64 \
        libcups2t64 \
        libgbm1 \
        libgtk-3-0t64 \
        libnss3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 cremcp \
    && mkdir -p /app /home/cremcp/.cache/cre_mcp \
    && chown -R cremcp:cremcp /app /home/cremcp/.cache

WORKDIR /app
COPY --chown=cremcp:cremcp pyproject.toml ./
COPY --chown=cremcp:cremcp src ./src
RUN pip install -e .

USER cremcp

EXPOSE 8000

CMD ["python", "-m", "cre_mcp", "--http"]
