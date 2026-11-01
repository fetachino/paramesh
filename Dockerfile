FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG TORCH_SOURCE=torch==2.15.0
RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir "$TORCH_SOURCE" --index-url https://download-r2.pytorch.org/whl/cpu
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[train]' \
    && useradd --create-home --uid 10001 paramesh \
    && mkdir /app/state && chown 10001:10001 /app/state
COPY examples ./examples
USER 10001
ENTRYPOINT ["paramesh"]
