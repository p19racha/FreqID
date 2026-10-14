# FreqID Mock Server (Test Double)

This directory contains a lightweight FastAPI application implementing the draft API contract for FreqID Phase 4:
- `POST /api/v1/auth/verify`: 1:1 biometric verification
- `POST /api/v1/auth/identify`: 1:N biometric identification
- `POST /api/v1/enroll/frames`: Multi-capture enrollment
- `GET /health`: Healthcheck

## Purpose
This server is a **test double** built specifically to test and validate `freqid-client` (Phase 3). It runs locally in memory and is NOT the production backend (which will be built in Phase 4).
