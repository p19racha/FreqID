# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_template_transform.py: Tests for cancelable keyed orthogonal template protection R in O(512).
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.crypto.template_transform import (
    TemplateTransformer,
    generate_orthogonal_matrix,
)


@pytest.fixture
def key_provider():
    key = os.urandom(32)
    return EnvOrFileKeyProvider(default_key=key, default_key_id="tf_v1")


def test_orthogonal_matrix_properties():
    key = os.urandom(32)
    R = generate_orthogonal_matrix(key, dim=512)

    assert R.shape == (512, 512)
    assert R.dtype == np.float32

    # 1. R^T R == I
    identity_approx = R.T @ R
    diff = np.linalg.norm(identity_approx - np.eye(512, dtype=np.float32))
    assert diff < 1e-3, f"Orthogonality error too high: {diff}"

    # 2. Determinism: same key yields identical matrix
    R_again = generate_orthogonal_matrix(key, dim=512)
    assert np.array_equal(R, R_again)

    # 3. Different key yields different matrix
    key_other = os.urandom(32)
    R_other = generate_orthogonal_matrix(key_other, dim=512)
    assert not np.array_equal(R, R_other)


def test_exact_cosine_similarity_preservation(key_provider):
    transformer = TemplateTransformer(key_provider)

    # Generate 100 random pairs of normalized 512-D face embedding vectors
    rng = np.random.default_rng(42)
    max_cosine_error = 0.0

    for _ in range(100):
        u = rng.standard_normal(512).astype(np.float32)
        u /= np.linalg.norm(u)

        v = rng.standard_normal(512).astype(np.float32)
        v /= np.linalg.norm(v)

        # Baseline original cosine similarity
        orig_sim = float(np.dot(u, v))

        # Transformed embeddings
        u_prime = transformer.transform(u)
        v_prime = transformer.transform(v)

        # Transformed cosine similarity
        trans_sim = float(np.dot(u_prime, v_prime))

        err = abs(orig_sim - trans_sim)
        if err > max_cosine_error:
            max_cosine_error = err

    # Error must be below float32 numerical precision tolerance (< 1e-4)
    assert max_cosine_error < 1e-4, f"Cosine similarity altered! Max error: {max_cosine_error}"


def test_norm_preservation_and_invertibility(key_provider):
    transformer = TemplateTransformer(key_provider)
    rng = np.random.default_rng(123)

    for _ in range(20):
        x = rng.standard_normal(512).astype(np.float32)
        x /= np.linalg.norm(x)

        # Norm preservation
        y = transformer.transform(x)
        assert abs(np.linalg.norm(y) - 1.0) < 1e-5

        # Inversion with same key recovers original vector
        recovered_x = transformer.inverse_transform(y)
        inv_err = float(np.linalg.norm(recovered_x - x))
        assert inv_err < 1e-4, f"Failed to recover embedding: error {inv_err}"


def test_cross_key_unlinkability():
    """
    Tests that the same face embedding transformed with two distinct keys K1 and K2
    has an expected correlation of 0 with standard deviation ~ 1/sqrt(512) (~0.044).
    """
    k1 = EnvOrFileKeyProvider(default_key=os.urandom(32), default_key_id="system_A")
    k2 = EnvOrFileKeyProvider(default_key=os.urandom(32), default_key_id="system_B")

    tf1 = TemplateTransformer(k1)
    tf2 = TemplateTransformer(k2)

    rng = np.random.default_rng(999)
    cross_sims = []

    for _ in range(200):
        x = rng.standard_normal(512).astype(np.float32)
        x /= np.linalg.norm(x)

        y1 = tf1.transform(x)
        y2 = tf2.transform(x)

        cross_sims.append(float(np.dot(y1, y2)))

    mean_cross = float(np.mean(cross_sims))
    std_cross = float(np.std(cross_sims))

    # Expected mean is 0.0, std ~ 0.044
    assert abs(mean_cross) < 0.02, f"Cross-system mean correlation {mean_cross} biased away from 0!"
    assert abs(std_cross - (1.0 / np.sqrt(512))) < 0.02


def test_transformation_performance_budget(key_provider):
    transformer = TemplateTransformer(key_provider)
    # Prime cache
    _ = transformer.get_matrix()

    rng = np.random.default_rng(555)
    vectors = [rng.standard_normal(512).astype(np.float32) for _ in range(100)]
    for v in vectors:
        v /= np.linalg.norm(v)

    t0 = time.perf_counter()
    for v in vectors:
        _ = transformer.transform(v)
    elapsed = time.perf_counter() - t0

    latency_per_vec_ms = (elapsed / len(vectors)) * 1000.0
    print(f"Transform latency: {latency_per_vec_ms:.4f} ms per vector")
    # Budget from approved design: <= 2.0 ms. Typically takes ~0.02 ms.
    assert latency_per_vec_ms < 1.0


def test_envelope_v2_encryption_roundtrip(key_provider):
    from freqid_server.crypto.envelope import EncryptedTemplateRecord, TemplateEncryptor

    encryptor = TemplateEncryptor(key_provider)
    rng = np.random.default_rng(777)
    emb = rng.standard_normal(512).astype(np.float32)
    emb /= np.linalg.norm(emb)

    # 1. Encrypt with format_version=2 (orthogonal rotation + AES-256-GCM)
    rec_v2 = encryptor.encrypt(
        embedding=emb,
        user_id="user_v2",
        model_version="v1.0-ir18",
        format_version=2,
    )
    assert rec_v2.format_version == 2

    # 2. Decrypt with default (inverts R)
    decrypted = encryptor.decrypt(
        record=rec_v2,
        user_id="user_v2",
        model_version="v1.0-ir18",
    )
    assert np.allclose(emb, decrypted, atol=1e-4)

    # 3. Decrypt with keep_transformed=True (returns rotated vector Rx)
    rotated_in_ram = encryptor.decrypt(
        record=rec_v2,
        user_id="user_v2",
        model_version="v1.0-ir18",
        keep_transformed=True,
    )
    # Confirm it is not equal to original emb
    assert not np.allclose(emb, rotated_in_ram, atol=1e-2)
    # But cosine similarity between Rx and Ry equals <x, y>
    y = rng.standard_normal(512).astype(np.float32)
    y /= np.linalg.norm(y)
    Ry = encryptor.transformer.transform(y)
    assert abs(float(np.dot(emb, y)) - float(np.dot(rotated_in_ram, Ry))) < 1e-4

    # 4. Tampering format_version triggers AAD failure
    from cryptography.exceptions import InvalidTag
    tampered_rec = EncryptedTemplateRecord(
        encrypted_blob=rec_v2.encrypted_blob,
        wrapped_data_key=rec_v2.wrapped_data_key,
        nonce=rec_v2.nonce,
        key_id=rec_v2.key_id,
        format_version=1,  # Tampered format_version in AAD
    )
    with pytest.raises(InvalidTag):
        encryptor.decrypt(tampered_rec, user_id="user_v2", model_version="v1.0-ir18")

