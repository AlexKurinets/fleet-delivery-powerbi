FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencies first, against a stub package, so code edits don't reinstall them.
COPY pyproject.toml ./
RUN mkdir -p src/fleetbi && touch src/fleetbi/__init__.py && pip install -e ".[dev]"

COPY sql ./sql
COPY src ./src
COPY tests ./tests
