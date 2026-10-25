# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
app.py: FastAPI mock server implementing the Phase 4 draft API contract.

TEST DOUBLE ONLY:
This mock server exists to validate the edge client SDK (Phase 3) during development
and automated testing. It is NOT the production backend server (which will be built in Phase 4).
"""

from __future__ import annotations

import os

import freqid_core as fq
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from freqid_core.embedder import Embedder
from freqid_core.errors import InvalidPayloadError, ShapeMismatchError

app = FastAPI(
    title="FreqID Mock Server",
    description="Test double implementing the Phase 4 draft API contract",
    version="0.1.0",
)

# In-memory template gallery: user_id -> 512-D normalized embedding vector
GALLERY: dict[str, np.ndarray] = {}
SEEN_NONCES: set[str] = set()

# Optional model embedder for end-to-end testing
CKPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "research",
        "outputs",
        "checkpoints",
        "partialface_ir_18.onnx",
    )
)

_EMBEDDER: Embedder | None = None


def get_embedder() -> Embedder | None:
    global _EMBEDDER
    if _EMBEDDER is None and os.path.exists(CKPT_PATH):
        try:
            _EMBEDDER = Embedder.from_checkpoint(CKPT_PATH, backend="onnx", device="cpu")
        except Exception:  # noqa: BLE001
            _EMBEDDER = None
    return _EMBEDDER


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "freqid-mock-server"}


@app.post("/api/v1/auth/verify")
async def verify_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
    x_claimed_identity: str | None = Header(None, alias="X-Claimed-Identity"),
) -> JSONResponse:
    if not x_device_id:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MISSING_HEADER", "message": "X-Device-ID header is required"},
        )
    if not x_claimed_identity:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "MISSING_HEADER",
                "message": "X-Claimed-Identity header is required",
            },
        )
    if not x_nonce:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MISSING_HEADER", "message": "X-Nonce header is required"},
        )

    # Replay protection check
    if x_nonce in SEEN_NONCES:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "REPLAY_DETECTED", "message": "Nonce has already been consumed"},
        )
    SEEN_NONCES.add(x_nonce)

    body = await request.body()
    try:
        payload = fq.PartialFacePayload.from_bytes(body)
    except (InvalidPayloadError, ShapeMismatchError) as e:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_PAYLOAD", "message": str(e)},
        )

    embedder = get_embedder()
    if embedder is not None:
        emb = embedder.embed(payload)
    else:
        # Synthetic fallback if weights not found
        emb = np.random.randn(512).astype(np.float32)
        emb = emb / np.linalg.norm(emb)

    # Check against in-memory gallery
    is_match = False
    similarity = 0.0
    threshold = 0.35

    if x_claimed_identity in GALLERY:
        ref_emb = GALLERY[x_claimed_identity]
        similarity, is_match = fq.verify(emb, ref_emb, threshold=threshold)
    else:
        # If identity not enrolled, return not matched
        is_match = False
        similarity = -0.1

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "request_id": x_request_id or "",
            "is_match": bool(is_match),
            "similarity": float(similarity),
            "threshold": threshold,
            "claimed_identity": x_claimed_identity,
            "verified_identity": x_claimed_identity if is_match else None,
            "device_id": x_device_id,
        },
    )


@app.post("/api/v1/auth/identify")
async def identify_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
    x_top_k: int = Header(5, alias="X-Top-K"),
) -> JSONResponse:
    if not x_device_id or not x_nonce:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MISSING_HEADER", "message": "Required headers missing"},
        )

    if x_nonce in SEEN_NONCES:
        raise HTTPException(
            status_code=400, detail={"error_code": "REPLAY_DETECTED", "message": "Nonce consumed"}
        )
    SEEN_NONCES.add(x_nonce)

    body = await request.body()
    try:
        payload = fq.PartialFacePayload.from_bytes(body)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail={"error_code": "INVALID_PAYLOAD", "message": str(e)}
        )

    embedder = get_embedder()
    if embedder is not None:
        emb = embedder.embed(payload)
    else:
        emb = np.random.randn(512).astype(np.float32)
        emb = emb / np.linalg.norm(emb)

    if not GALLERY:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "request_id": x_request_id or "",
                "is_match": False,
                "top_candidate": None,
                "candidates": [],
            },
        )

    gallery_ids = list(GALLERY.keys())
    gallery_embs = np.stack(list(GALLERY.values()), axis=0)

    results = fq.identify(emb, gallery_embs, gallery_ids, threshold=0.35, top_k=x_top_k)
    candidates = [
        {
            "user_id": r.target_id,
            "similarity": float(r.similarity),
            "rank": r.rank,
            "is_match": r.is_match,
        }
        for r in results
    ]
    top_candidate = candidates[0] if candidates and candidates[0]["is_match"] else None

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "request_id": x_request_id or "",
            "is_match": top_candidate is not None,
            "top_candidate": top_candidate,
            "candidates": candidates,
        },
    )


@app.post("/api/v1/enroll/frames")
async def enroll_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    x_payload_count: str | None = Header(None, alias="X-Payload-Count"),
) -> JSONResponse:
    if not x_device_id or not x_user_id:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MISSING_HEADER", "message": "Required headers missing"},
        )

    body = await request.body()
    # Parse framed payloads: 4-byte length prefix
    offset = 0
    payloads = []
    while offset < len(body):
        if offset + 4 > len(body):
            break
        p_len = int.from_bytes(body[offset : offset + 4], byteorder="big")
        offset += 4
        p_bytes = body[offset : offset + p_len]
        offset += p_len
        payloads.append(fq.PartialFacePayload.from_bytes(p_bytes))

    if not payloads:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "EMPTY_PAYLOADS", "message": "No valid payloads received"},
        )

    embedder = get_embedder()
    embs = []
    for p in payloads:
        if embedder is not None:
            e = embedder.embed(p)
        else:
            e = np.random.randn(512).astype(np.float32)
            e = e / np.linalg.norm(e)
        embs.append(e)

    # Average and normalize enrolled template
    avg_emb = np.mean(embs, axis=0)
    avg_emb = avg_emb / np.linalg.norm(avg_emb)
    GALLERY[x_user_id] = avg_emb

    return JSONResponse(
        status_code=201,
        content={
            "status": "enrolled",
            "user_id": x_user_id,
            "template_id": f"tmpl_{x_user_id}",
            "frames_processed": len(payloads),
            "quality_score": 0.95,
        },
    )
