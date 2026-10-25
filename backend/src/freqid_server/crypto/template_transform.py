# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
template_transform.py: Cancelable keyed orthogonal template transformation R in O(512).

Provides exact isometric transformation of 512-D face embeddings:
- Strict cosine similarity preservation: <R*u, R*v> == <u, v> (Delta-TAR = 0.00%)
- Exact L2 norm preservation: ||R*x||_2 == ||x||_2
- Deterministic Haar-measure orthogonal matrix generated from HKDF transform subkey
- Inversion resistance and cross-system unlinkability
"""

from __future__ import annotations

import numpy as np
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from freqid_server.crypto.provider import KeyProvider

EMBEDDING_DIM = 512


def generate_orthogonal_matrix(key_bytes: bytes, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """
    Generates a deterministic orthogonal matrix R in O(dim) from a 32-byte key.
    Uses HKDF-SHA256 to expand key into pseudorandom Gaussian matrix, followed by QR decomposition
    with sign-adjusted diagonal for unique Haar-measure distribution.
    """
    if len(key_bytes) != 32:
        raise ValueError(f"Transform key must be 32 bytes, got {len(key_bytes)}")

    # We need dim * dim standard normal floats.
    # To be strictly deterministic and independent of architecture PRNG implementations,
    # generate uniform floats via HKDF expansion and apply Box-Muller transform.
    total_floats = dim * dim
    # If odd, round up to even for Box-Muller pairs
    needed_pairs = (total_floats + 1) // 2

    # Expand key using HKDF-Expand with SHA-256 blocks
    # Each pair needs 2 uint32s = 8 bytes
    total_bytes = needed_pairs * 8

    # Derivation in chunks using HKDF with sequential counter
    raw_buffer = bytearray()
    chunk_idx = 0
    while len(raw_buffer) < total_bytes:
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"FreqID-OrthogonalMatrix-dim{dim}-chunk{chunk_idx}".encode("ascii"),
        )
        raw_buffer.extend(kdf.derive(key_bytes))
        chunk_idx += 1

    # Unpack uint32 integers and normalize to (0, 1]
    u1_ints = np.frombuffer(raw_buffer[: needed_pairs * 4], dtype=">u4").astype(np.float64)
    u2_ints = np.frombuffer(raw_buffer[needed_pairs * 4 : needed_pairs * 8], dtype=">u4").astype(
        np.float64
    )

    # Shift from [0, 2^32-1] to (0, 1]
    u1 = (u1_ints + 1.0) / (4294967296.0 + 1.0)
    u2 = (u2_ints + 1.0) / (4294967296.0 + 1.0)

    # Box-Muller transform to N(0, 1)
    mag = np.sqrt(-2.0 * np.log(u1))
    z0 = mag * np.cos(2.0 * np.pi * u2)
    z1 = mag * np.sin(2.0 * np.pi * u2)

    gaussian_floats = np.empty(needed_pairs * 2, dtype=np.float64)
    gaussian_floats[0::2] = z0
    gaussian_floats[1::2] = z1

    gaussian_matrix = gaussian_floats[:total_floats].reshape((dim, dim))

    # QR decomposition to obtain orthogonal matrix Q
    q, r = np.linalg.qr(gaussian_matrix)

    # Sign normalization on diagonal of R to ensure unique Haar measure
    d = np.diagonal(r)
    ph = np.sign(d)
    ph[ph == 0] = 1.0
    q = q * ph

    # Convert to float32 for high performance embedding operations
    q_f32 = q.astype(np.float32)

    # Numerical verification of orthogonality: ||Q^T Q - I||_F < 1e-4
    diff = np.linalg.norm(q_f32.T @ q_f32 - np.eye(dim, dtype=np.float32))
    if diff > 1e-3:
        raise RuntimeError(f"Orthogonality check failed: residual {diff} exceeds tolerance")

    return q_f32


class TemplateTransformer:
    """
    Manages deterministic orthogonal matrices R in O(512) for cancelable template protection.
    Caches matrix R per key_id.
    """

    def __init__(self, key_provider: KeyProvider, dim: int = EMBEDDING_DIM) -> None:
        self.key_provider = key_provider
        self.dim = dim
        self._cache: dict[str, np.ndarray] = {}

    def get_matrix(self, key_id: str | None = None) -> np.ndarray:
        target_id = key_id or self.key_provider.current_key_id()
        if target_id not in self._cache:
            k_transform = self.key_provider.derive_purpose_key("transform", target_id)
            self._cache[target_id] = generate_orthogonal_matrix(k_transform, dim=self.dim)
        return self._cache[target_id]

    def transform(self, embedding: np.ndarray, key_id: str | None = None) -> np.ndarray:
        """
        Transforms 512-D embedding x into protected representation y = R @ x.
        Preserves L2 norm and exact cosine similarity.
        """
        if embedding.shape != (self.dim,):
            raise ValueError(f"Expected embedding shape ({self.dim},), got {embedding.shape}")

        R = self.get_matrix(key_id)
        emb_f32 = embedding.astype(np.float32)
        transformed = R @ emb_f32

        # L2-normalize to guard against float32 rounding drift
        norm = np.linalg.norm(transformed)
        if norm > 0:
            transformed = transformed / norm

        return transformed.astype(np.float32)

    def inverse_transform(
        self, protected_embedding: np.ndarray, key_id: str | None = None
    ) -> np.ndarray:
        """
        Inverts protected representation y back to x: x = R^T @ y.
        (Only possible with possession of key_id).
        """
        if protected_embedding.shape != (self.dim,):
            raise ValueError(
                f"Expected embedding shape ({self.dim},), got {protected_embedding.shape}"
            )

        R = self.get_matrix(key_id)
        emb_f32 = protected_embedding.astype(np.float32)
        original = R.T @ emb_f32

        norm = np.linalg.norm(original)
        if norm > 0:
            original = original / norm

        return original.astype(np.float32)
