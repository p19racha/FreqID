# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
envelope.py: Envelope encryption engine for biometric templates using AES-256-GCM.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from freqid_server.crypto.provider import KeyProvider
from freqid_server.crypto.template_transform import TemplateTransformer


@dataclass(frozen=True)
class EncryptedTemplateRecord:
    encrypted_blob: bytes
    wrapped_data_key: bytes
    nonce: bytes
    key_id: str
    format_version: int = 1


class TemplateEncryptor:
    """
    Encrypts and decrypts 512-D biometric embeddings with AES-256-GCM envelope encryption.
    Binds ciphertext to user_id and model_version via Authenticated Associated Data (AAD).
    Optionally applies cancelable keyed orthogonal rotation R in O(512) for format_version >= 2.
    """

    def __init__(self, key_provider: KeyProvider) -> None:
        self.key_provider = key_provider
        self.transformer = TemplateTransformer(key_provider)

    @staticmethod
    def build_aad(user_id: str, model_version: str, format_version: int = 1) -> bytes:
        return f"user_id={user_id}:model_version={model_version}:format={format_version}".encode()

    def encrypt(
        self,
        embedding: np.ndarray,
        user_id: str,
        model_version: str,
        format_version: int = 1,
    ) -> EncryptedTemplateRecord:
        """
        Encrypts a 512-D float32 embedding vector.
        Generates ephemeral 256-bit DEK, encrypts with AES-256-GCM, and wraps DEK with master KEK.
        If format_version >= 2, rotates vector with keyed orthogonal matrix R in O(512).
        """
        if embedding.shape != (512,):
            raise ValueError(f"Expected embedding shape (512,), got {embedding.shape}")

        active_key_id = self.key_provider.current_key_id()

        # Apply cancelable keyed orthogonal rotation if format_version >= 2
        if format_version >= 2:
            norm_emb = self.transformer.transform(embedding, key_id=active_key_id)
        else:
            norm_emb = embedding.astype(np.float32)

        raw_bytes = norm_emb.tobytes()

        # 1. Generate ephemeral DEK and GCM nonce
        dek = secrets.token_bytes(32)
        nonce = os.urandom(12)

        # 2. Authenticated Additional Data binding
        aad = self.build_aad(
            user_id=user_id, model_version=model_version, format_version=format_version
        )

        # 3. Encrypt embedding vector with DEK
        aesgcm = AESGCM(dek)
        ciphertext = aesgcm.encrypt(nonce, raw_bytes, aad)

        # 4. Wrap DEK with active master key
        wrapped_dek = self.key_provider.wrap_key(dek, key_id=active_key_id)

        return EncryptedTemplateRecord(
            encrypted_blob=ciphertext,
            wrapped_data_key=wrapped_dek,
            nonce=nonce,
            key_id=active_key_id,
            format_version=format_version,
        )

    def decrypt(
        self,
        record: EncryptedTemplateRecord,
        user_id: str,
        model_version: str,
        keep_transformed: bool = False,
    ) -> np.ndarray:
        """
        Decrypts an encrypted template record.
        Unwraps DEK with recorded master key, verifies AAD, and unpacks 512-D float32 array.
        If format_version >= 2 and keep_transformed is False, inverts orthogonal rotation.
        """
        # 1. Unwrap DEK using the key_id stored in the record
        dek = self.key_provider.unwrap_key(record.wrapped_data_key, key_id=record.key_id)

        # 2. Reconstruct AAD
        aad = self.build_aad(
            user_id=user_id,
            model_version=model_version,
            format_version=record.format_version,
        )

        # 3. Decrypt ciphertext with DEK
        aesgcm = AESGCM(dek)
        plaintext = aesgcm.decrypt(record.nonce, record.encrypted_blob, aad)

        # 4. Unpack 512-D float32 array
        emb = np.frombuffer(plaintext, dtype=np.float32).copy()
        if emb.shape != (512,):
            raise ValueError(f"Decrypted buffer unexpected shape: {emb.shape}")

        if record.format_version >= 2 and not keep_transformed:
            return self.transformer.inverse_transform(emb, key_id=record.key_id)

        return emb
