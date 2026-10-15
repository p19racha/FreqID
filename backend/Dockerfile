# Copyright 2026 FreqID Authors. Apache-2.0 License.
# Production multi-stage Dockerfile for FreqID Inference & Matching Server

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install packages into wheels
COPY core/ /app/core/
COPY backend/ /app/backend/

RUN pip install --no-cache-dir --upgrade pip wheel setuptools && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels /app/core && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels /app/backend

# Final Runtime Image
FROM python:3.12-slim AS runner

WORKDIR /app

# Install runtime utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user
RUN useradd -m -u 1000 -s /bin/bash freqid

# Install wheels
COPY --from=builder /app/wheels /app/wheels
RUN pip install --no-cache-dir /app/wheels/*.whl && \
    rm -rf /app/wheels

# Copy model checkpoints and default configs
COPY research/outputs/checkpoints/ /app/research/outputs/checkpoints/
RUN chown -R freqid:freqid /app

USER freqid

EXPOSE 8000

ENV FREQID_SERVER_HOST="0.0.0.0" \
    FREQID_SERVER_PORT="8000" \
    FREQID_SERVER_MODEL_PATH="/app/research/outputs/checkpoints/partialface_ir_18.onnx" \
    FREQID_SERVER_MODEL_BACKEND="onnx" \
    FREQID_SERVER_DEVICE="cpu"

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["freqid-server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
