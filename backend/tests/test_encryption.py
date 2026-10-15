# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_encryption.py: Unit tests for envelope encryption engine, KeyProvider, and key rotation.
Tests:
  - Round-trip encrypt & decrypt of 512-D biometric embeddings
  - AAD binding protection (user_id and model_version spoofing prevention)
  - Wrong key rejection
  - POSIX 0600 secret file permission validation
  - In-place key rotation preserving ciphertext blobs
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile

import numpy as np
import pytest
from cryptography.exceptions import InvalidTag

from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider

KEY_V1 = b"01234567890123456789012345678901"
KEY_V2 = b"abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture
def encryptor_v1() -> TemplateEncryptor:
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V1,
        default_key_id="key_v1",
        secondary_keys={"key_v2": KEY_V2},
    )
    return TemplateEncryptor(provider)


def test_roundtrip_encryption_decryption(encryptor_v1: TemplateEncryptor):
    rng = np.random.RandomState(42)
    original_emb = rng.randn(512).astype(np.float32)
    original_emb = original_emb / np.linalg.norm(original_emb)

    record = encryptor_v1.encrypt(
        embedding=original_emb,
        user_id="alice",
        model_version="v1.0-ir18",
    )

    assert record.key_id == "key_v1"
    assert len(record.nonce) == 12
    # RFC 3394 AES Key Wrap adds 8 bytes to a 32-byte key -> 40 bytes
    assert len(record.wrapped_data_key) == 40
    # AES-256-GCM adds 16-byte tag to 2048 bytes embedding -> 2064 bytes
    assert len(record.encrypted_blob) == 2048 + 16
    assert record.format_version == 1

    decrypted_emb = encryptor_v1.decrypt(
        record=record,
        user_id="alice",
        model_version="v1.0-ir18",
    )

    assert decrypted_emb.shape == (512,)
    assert decrypted_emb.dtype == np.float32
    assert np.allclose(original_emb, decrypted_emb, atol=1e-7)


def test_aad_binding_tampering_rejected(encryptor_v1: TemplateEncryptor):
    """Proves that copying an encrypted blob to another user or model version fails decryption."""
    rng = np.random.RandomState(43)
    emb = rng.randn(512).astype(np.float32)

    record = encryptor_v1.encrypt(
        embedding=emb,
        user_id="victim_alice",
        model_version="v1.0-ir18",
    )

    # 1. Attacker attempts to assign Alice's blob to Bob
    with pytest.raises(InvalidTag):
        encryptor_v1.decrypt(
            record=record,
            user_id="attacker_bob",
            model_version="v1.0-ir18",
        )

    # 2. Attacker attempts to claim it belongs to a different model version
    with pytest.raises(InvalidTag):
        encryptor_v1.decrypt(
            record=record,
            user_id="victim_alice",
            model_version="v2.0-ir50",
        )


def test_wrong_key_rejection():
    """Decryption fails when the master key is incorrect."""
    provider_1 = EnvOrFileKeyProvider(default_key=KEY_V1, default_key_id="key_v1")
    enc_1 = TemplateEncryptor(provider_1)

    provider_wrong = EnvOrFileKeyProvider(default_key=KEY_V2, default_key_id="key_v1")
    enc_wrong = TemplateEncryptor(provider_wrong)

    emb = np.zeros(512, dtype=np.float32)
    record = enc_1.encrypt(embedding=emb, user_id="charlie", model_version="v1.0-ir18")

    with pytest.raises(ValueError, match="Failed to unwrap DEK"):
        enc_wrong.decrypt(record=record, user_id="charlie", model_version="v1.0-ir18")


def test_invalid_embedding_shape_rejected(encryptor_v1: TemplateEncryptor):
    invalid_emb = np.zeros(256, dtype=np.float32)
    with pytest.raises(ValueError, match="Expected embedding shape \\(512,\\)"):
        encryptor_v1.encrypt(invalid_emb, user_id="user", model_version="v1.0-ir18")


def test_posix_permissions_enforcement():
    """KeyProvider must refuse world-readable or group-readable key files."""
    b64_key = base64.b64encode(KEY_V1).decode("utf-8")

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(b64_key)
        temp_path = f.name

    try:
        # Insecure permissions: 0644 (readable by others)
        os.chmod(temp_path, 0o644)
        with pytest.raises(PermissionError, match=r"(?i)insecure permissions"):
            EnvOrFileKeyProvider(key_file_path=temp_path)

        # Secure permissions: 0600 (owner only)
        os.chmod(temp_path, 0o600)
        provider = EnvOrFileKeyProvider(key_file_path=temp_path)
        assert provider.get_key("key_v1") == KEY_V1
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_key_rotation_rewraps_without_decrypting_blob():
    """
    Demonstrates zero-biometric-decryption key rotation:
    The 2048-byte biometric ciphertext blob is untouched (same SHA-256 hash),
    while the 32-byte DEK is re-wrapped with key_v2.
    """
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V1,
        default_key_id="key_v1",
        secondary_keys={"key_v2": KEY_V2},
    )
    encryptor = TemplateEncryptor(provider)

    rng = np.random.RandomState(44)
    original_emb = rng.randn(512).astype(np.float32)
    record = encryptor.encrypt(original_emb, user_id="rot_user", model_version="v1.0-ir18")

    blob_hash_before = hashlib.sha256(record.encrypted_blob).hexdigest()

    # Rotate: unwrap DEK with key_v1, wrap with key_v2
    raw_dek = provider.unwrap_key(record.wrapped_data_key, "key_v1")
    new_wrapped_dek = provider.wrap_key(raw_dek, "key_v2")

    from freqid_server.crypto.envelope import EncryptedTemplateRecord

    rotated_record = EncryptedTemplateRecord(
        encrypted_blob=record.encrypted_blob,  # Untouched ciphertext
        wrapped_data_key=new_wrapped_dek,
        nonce=record.nonce,
        key_id="key_v2",
        format_version=record.format_version,
    )

    blob_hash_after = hashlib.sha256(rotated_record.encrypted_blob).hexdigest()
    assert blob_hash_before == blob_hash_after  # Biometric ciphertext blob unmodified!
    assert record.wrapped_data_key != rotated_record.wrapped_data_key

    # Decrypt with key_v2
    decrypted_rotated = encryptor.decrypt(
        rotated_record, user_id="rot_user", model_version="v1.0-ir18"
    )
    assert np.allclose(original_emb, decrypted_rotated, atol=1e-7)
