# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_payload_key.py: Endpoint publishing server's active X25519 public key for application-layer payload sealing.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["Security & Key Management"])


class PayloadKeyResponse(BaseModel):
    key_id: str = Field(..., description="Active master key identifier")
    public_key_hex: str = Field(..., description="Raw X25519 public key in hexadecimal (32 bytes / 64 hex chars)")
    algorithm: str = Field(default="X25519-HKDF-AES256GCM", description="Key agreement and AEAD algorithm suite")
    format: str = Field(default="PF02", description="Application layer envelope format version")


@router.get(
    "/v1/payload-key",
    response_model=PayloadKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Active Server Payload Sealing Public Key",
    operation_id="get_payload_key",
)
async def get_payload_key(request: Request) -> PayloadKeyResponse:
    """
    Returns the server's active X25519 public key.
    Edge clients use this public key with ephemeral ECDH to seal PartialFace payloads in PF02 envelopes.
    """
    key_provider = getattr(request.app.state, "key_provider", None)
    if key_provider is None:
        # Fallback or retrieve from store / config
        store = getattr(request.app.state, "store", None)
        if store is not None and hasattr(store, "encryptor"):
            key_provider = store.encryptor.key_provider

    if key_provider is None:
        raise RuntimeError("No KeyProvider configured on application state.")

    current_id = key_provider.current_key_id()
    _, pub_bytes = key_provider.get_payload_keypair(current_id)

    return PayloadKeyResponse(
        key_id=current_id,
        public_key_hex=pub_bytes.hex(),
        algorithm="X25519-HKDF-AES256GCM",
        format="PF02",
    )
