FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

ARG UV_VERSION=0.13.1
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

RUN groupadd --system mediaengine \
    && useradd --system --gid mediaengine --home-dir /app mediaengine

COPY --chown=mediaengine:mediaengine . .

USER mediaengine

CMD [".venv/bin/python", "-V"]
