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

COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
COPY scripts ./scripts

# requirements.lock pins every resolved dependency (regenerate with
# `uv pip compile pyproject.toml --python-version 3.12 -o requirements.lock`);
# the package itself is then installed without re-resolving.
RUN python -m pip install --no-deps -r requirements.lock \
    && python -m pip install --no-deps . \
    && useradd --create-home --uid 10001 gate \
    && chown -R gate:gate /app
USER gate

EXPOSE 9000

CMD ["sh", "/app/scripts/entrypoint.sh"]
