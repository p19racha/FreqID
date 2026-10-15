# Copyright 2026 FreqID Authors. Apache-2.0 License.
# Hardened Multi-Stage Production Dockerfile for FreqID Server

# ==============================================================================
# Stage 1: Build Wheels & Dependencies
# ==============================================================================
FROM python:3.12.9-slim-bookworm AS builder

WORKDIR /build

# Install build toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy package sources
COPY core/ /build/core/
COPY backend/ /build/backend/

# Build isolated wheels with ONNX Runtime and PyTorch CPU
RUN pip install --no-cache-dir --upgrade pip wheel setuptools && \
    pip wheel --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu --wheel-dir /build/wheels "/build/core[all]" && \
    pip wheel --no-cache-dir --find-links /build/wheels --wheel-dir /build/wheels "/build/backend[all]"

# ==============================================================================
# Stage 2: Hardened Minimal Runtime Image
# ==============================================================================
FROM python:3.12.9-slim-bookworm AS runner

# OCI Standard Metadata Labels
LABEL org.opencontainers.image.title="freqid-server" \
      org.opencontainers.image.description="FreqID Privacy-Preserving Face Recognition Inference and Matching Server" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.vendor="FreqID Authors" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/p19racha/FreqID"

WORKDIR /app

# Create non-root system user with explicit UID/GID 10001 and no login shell
RUN groupadd -g 10001 freqid && \
    useradd -u 10001 -g freqid -d /app -s /sbin/nologin -M freqid

# Install wheels from builder
COPY --from=builder /build/wheels /app/wheels
RUN pip install --no-cache-dir /app/wheels/*.whl && \
    rm -rf /app/wheels /root/.cache

# Copy alembic migrations and configuration
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic/ /app/alembic/
COPY backend/scripts/ /app/scripts/

# Create designated volume mount points with strict ownership
RUN mkdir -p /app/models /run/secrets /tmp && \
    chown -R freqid:freqid /app /tmp && \
    chmod 755 /app && \
    chmod 1777 /tmp

# Environment variables for hardened runtime
ENV PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    TMPDIR="/tmp" \
    FREQID_SERVER_HOST="0.0.0.0" \
    FREQID_SERVER_PORT="8000" \
    FREQID_SERVER_MODEL_BACKEND="onnx" \
    FREQID_SERVER_DEVICE="cpu" \
    FREQID_SERVER_MODEL_PATH="/app/models/partialface_ir_18.onnx"

USER 10001:10001

EXPOSE 8000

# Native Python healthcheck (eliminates curl dependency and attack surface)
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').getcode() == 200 else 1)"

ENTRYPOINT ["freqid-server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
