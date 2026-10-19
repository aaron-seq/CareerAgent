# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements/locks/runtime-py311.txt ./requirements/locks/runtime-py311.txt

# Install Python dependencies
RUN --mount=type=secret,id=pip_ca_bundle \
    if [ -f /run/secrets/pip_ca_bundle ]; then export PIP_CERT=/run/secrets/pip_ca_bundle; fi; \
    python -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
        -r requirements/locks/runtime-py311.txt

RUN useradd --create-home --uid 1000 careeragent

# Secrets and local data are excluded by .dockerignore.
COPY --chown=careeragent:careeragent . .

# Create data directory
RUN mkdir -p careeragent_data && chown -R careeragent:careeragent /app
USER careeragent

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run application
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
