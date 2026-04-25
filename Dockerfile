# --- Stage 1: Build app venv and verified Bitwarden CLI ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ARG TARGETARCH
ARG BW_CLI_VERSION=2026.4.1
ARG BW_CLI_SHA256_AMD64=2172dc63f821fcbd4b4ce65e7106f1ebab26b6cb16c9c8a5b28230dcc6f8a774
ARG BW_CLI_SHA256_ARM64=c405867e5e2df08f82e1893561094fb7e5ef7caf957ba5ded9fbe870b2ef4380

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) bw_arch="linux"; bw_sha="${BW_CLI_SHA256_AMD64}" ;; \
      arm64) bw_arch="linux-arm64"; bw_sha="${BW_CLI_SHA256_ARM64}" ;; \
      *) echo "Unsupported Docker architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
      "https://github.com/bitwarden/clients/releases/download/cli-v${BW_CLI_VERSION}/bw-${bw_arch}-${BW_CLI_VERSION}.zip" \
      -o /tmp/bw.zip; \
    echo "${bw_sha}  /tmp/bw.zip" | sha256sum -c -; \
    unzip -q /tmp/bw.zip -d /usr/local/bin; \
    chmod 0755 /usr/local/bin/bw; \
    rm -f /tmp/bw.zip

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev

# --- Stage 2: Runtime ---
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="BW-Proxy" \
      org.opencontainers.image.description="Sovereign security-hardened blind hub for Bitwarden & AI" \
      org.opencontainers.image.version="2.4.0" \
      org.opencontainers.image.authors="KAMDEM Ivann (KpihX)" \
      org.opencontainers.image.source="https://github.com/KpihX/bw-proxy"

WORKDIR /app

# Install runtime dependencies. 
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/bw /usr/local/bin/bw
COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml /app/
COPY src /app/src

ENV PYTHONUNBUFFERED=1
ENV BW_PROXY_DATA="/data"
ENV HOME="/data"
ENV PYTHONPATH="/app/src"
ENV PATH="/opt/venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

RUN groupadd --gid 1000 bwproxy \
    && useradd --uid 1000 --gid 1000 --home-dir /data --shell /usr/sbin/nologin bwproxy \
    && mkdir -p /data \
    && chown -R bwproxy:bwproxy /data \
    && chmod 0700 /data

USER bwproxy:bwproxy
VOLUME [ "/data" ]
ENTRYPOINT [ "python", "-m", "bw_proxy.main" ]
CMD [ "serve" ]
