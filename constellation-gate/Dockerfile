# Constellation.Gate runtime image.
#
# deploy/docker-compose.yml and deploy/README_DEPLOY.md both said
# `docker compose up --build`, and the compose file pinned
# `image: constellation-gate:latest`, but no Dockerfile existed anywhere in
# the repository: nothing could build that image. This file is the build.
#
# Supply chain: the base image is pinned by digest (python:3.12-slim at the
# time of pinning); every dependency, the SDK included (as the GitHub source
# archive of its release commit), is installed from requirements.lock with
# `--require-hashes`. Regenerate the lock with `bash scripts/lock_requirements.sh`.
# The package runs from /app/src on PYTHONPATH; nothing is pip-installed from
# the tree.
FROM python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: constellation-node-sdk is a git+https dependency (see pyproject.toml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --require-hashes --no-deps -r requirements.lock \
    && useradd --create-home --uid 10001 gate

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
RUN chown -R gate:gate /app
USER gate

EXPOSE 9000

CMD ["sh", "/app/scripts/entrypoint.sh"]
