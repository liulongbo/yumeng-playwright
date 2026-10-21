# syntax=docker/dockerfile:1.7
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS builder
ARG UV_BOOTSTRAP_INDEX_URL=https://pypi.org/simple
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ARG UV_LOCK_REGISTRY_URL=https://pypi.org/simple
ARG UV_LOCK_FILES_URL=https://files.pythonhosted.org/
RUN python -m pip install --no-cache-dir --index-url "${UV_BOOTSTRAP_INDEX_URL}" uv==0.13.0
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_CONCURRENT_DOWNLOADS=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
COPY pyproject.toml uv.lock README.md ./
RUN sed -i \
      -e "s#https://pypi.org/simple#${UV_LOCK_REGISTRY_URL}#g" \
      -e "s#https://files.pythonhosted.org/#${UV_LOCK_FILES_URL}#g" \
      uv.lock
COPY backend ./backend
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    XINGTU_PROJECT_ROOT=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system xingtu && useradd --system --gid xingtu --home /app xingtu
WORKDIR /app
COPY --from=builder --chown=xingtu:xingtu /app/.venv /app/.venv
COPY --chown=xingtu:xingtu contracts /app/contracts
COPY --chown=xingtu:xingtu migrations /app/migrations
USER xingtu
CMD ["xingtu-api"]
