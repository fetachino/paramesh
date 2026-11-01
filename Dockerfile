FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir '.[train]' \
    && useradd --create-home --uid 10001 paramesh
COPY examples ./examples
USER 10001
ENTRYPOINT ["paramesh"]
