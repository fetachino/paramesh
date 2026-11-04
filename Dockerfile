FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ARG SOURCE_COMMIT=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_DIRTY=unknown
LABEL org.opencontainers.image.source="https://github.com/fetachino/paramesh" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source-dirty="${SOURCE_DIRTY}"
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH" UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --extra train --extra storage --extra operations
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --extra train --extra storage --extra operations \
    && useradd --create-home --uid 10001 paramesh \
    && mkdir -p /app/state /checkpoints /cluster/coordinator /cluster/shard-0 /cluster/shard-1 /cluster/worker-0 /cluster/worker-1 \
    && chown -R 10001:10001 /app/state /checkpoints /cluster
COPY examples ./examples
COPY docs/evidence ./evidence
USER 10001
ENTRYPOINT ["paramesh"]
