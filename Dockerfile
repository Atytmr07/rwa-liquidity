# Runs the CLI against a public Ethereum node -- no API keys required for
# `report --demo` or a live `report` against the default RPC endpoint.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependencies first, so an application-only change doesn't invalidate the
# dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

ENTRYPOINT ["uv", "run", "rwa-liquidity"]
CMD ["report", "--demo"]
