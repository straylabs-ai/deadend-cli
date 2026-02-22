# Minimal Dockerfile: install app from workspace and start HTTP server
# Build: docker build -t deadend-http .
# Run:   docker run -p 8000:8000 -v /var/run/docker.sock:/var/run/docker.sock deadend-http
#        If you get "Permission denied" on the socket, add the host docker group:
#        docker run -p 8000:8000 -v /var/run/docker.sock:/var/run/docker.sock \
#          --group-add $(stat -c '%g' /var/run/docker.sock) deadend-http

FROM python:3.12-slim

WORKDIR /app

# Install git so uv-dynamic-versioning can compute versions during build
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace (root + CLI package and members). .git is required for dynamic versioning.
COPY pyproject.toml uv.lock ./
COPY deadend_cli ./deadend_cli
COPY .git ./.git

# Install app and dependencies (no dev deps)
RUN uv sync --frozen --no-dev

# Server listens on 0.0.0.0 so it's reachable from outside the container
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["deadend-http-server", "--host", "0.0.0.0", "--port", "8000"]
