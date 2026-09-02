# Constellation.Gate runtime image.
#
# deploy/docker-compose.yml and deploy/README_DEPLOY.md both said
# `docker compose up --build`, and the compose file pinned
# `image: constellation-gate:latest`, but no Dockerfile existed anywhere in
# the repository: nothing could build that image. This file is the build.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: constellation-node-sdk is a git+https dependency (see pyproject.toml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install .

RUN useradd --create-home --uid 10001 gate \
    && chown -R gate:gate /app
USER gate

EXPOSE 9000

CMD ["sh", "/app/scripts/entrypoint.sh"]
