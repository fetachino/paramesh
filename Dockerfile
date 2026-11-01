FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG TORCH_SOURCE=torch==2.15.0
RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir "$TORCH_SOURCE" --index-url https://download-r2.pytorch.org/whl/cpu
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install '.[train,storage,operations]' \
    && useradd --create-home --uid 10001 paramesh \
    && mkdir -p /app/state /checkpoints /cluster/coordinator /cluster/shard-0 /cluster/shard-1 /cluster/worker-0 /cluster/worker-1 \
    && chown -R 10001:10001 /app/state /checkpoints /cluster
COPY examples ./examples
COPY docs/evidence ./evidence
USER 10001
ENTRYPOINT ["paramesh"]
