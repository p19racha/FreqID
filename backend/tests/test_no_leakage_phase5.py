# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_no_leakage_phase5.py: Architectural invariant tests verifying zero data leakage.
Tests:
  - Database schema scan: No column stores raw images, pixel data, or PartialFacePayloads.
  - Audit table scan: No column stores exact floating-point similarity values.
  - AST / Import isolation scan: Server packages strictly forbid raw image transforms.
  - Log and exception redaction: Secrets, DEKs, and embeddings never leak into logs or exceptions.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from freqid_server.config import ServerConfig
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider

ADMIN_DB_URL = os.environ.get(
    "FREQID_TEST_ADMIN_DB_URL",
    "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
)

FORBIDDEN_COLUMN_PATTERNS = [
    "image",
    "crop",
    "pixel",
    "raw_frame",
    "spatial",
    "payload",
    "partial_face",
    "dct",
    "frequency_bytes",
]

FORBIDDEN_IMPORTS = {
    "cv2",
    "PIL",
    "PIL.Image",
    "torchvision",
    "insightface",
    "facenet_pytorch",
    "freqid_core.transform",
}


@pytest.mark.asyncio
async def test_database_schema_has_no_raw_image_or_payload_columns():
    """Queries PostgreSQL information_schema to verify zero biometric leakage columns."""
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    async with admin_engine.connect() as conn:
        res = await conn.execute(
            text(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
                """
            )
        )
        columns = res.all()

    await admin_engine.dispose()
    assert len(columns) > 0, "No tables found in public schema."

    for tbl, col, dtype in columns:
        col_lower = col.lower()
        if tbl == "device_heartbeats" and col_lower == "queued_payloads":
            assert dtype in ("integer", "bigint", "smallint"), (
                "queued_payloads must be an integer count"
            )
            continue
        for forbidden in FORBIDDEN_COLUMN_PATTERNS:
            assert forbidden not in col_lower, (
                f"Forbidden column '{col}' ({dtype}) in table '{tbl}' matches pattern '{forbidden}'! "
                f"Raw spatial images, crops, and payloads must NEVER be persisted in the database."
            )

    # Specific check: audit_events must NOT have float similarity score column
    audit_cols = [col.lower() for tbl, col, _ in columns if tbl == "audit_events"]
    assert "score" not in audit_cols
    assert "similarity" not in audit_cols
    assert "score_bucket" in audit_cols, "Audit table must store coarse score buckets only."


def test_server_ast_contains_no_forbidden_transforms_or_image_libraries():
    """Scans all Python ASTs in freqid_server to verify raw image transform isolation."""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "freqid_server"
    assert src_dir.is_dir()

    violating_files: list[str] = []

    for py_file in src_dir.rglob("*.py"):
        with open(py_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS:
                        violating_files.append(f"{py_file}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in FORBIDDEN_IMPORTS or any(
                    module.startswith(f"{f}.") for f in FORBIDDEN_IMPORTS
                ):
                    violating_files.append(f"{py_file}: from {module} import ...")

    assert not violating_files, (
        f"Server code must NEVER import image processing or raw transform libraries: {violating_files}"
    )


def test_production_config_strictly_disables_sql_echo():
    """SQL echo must be disabled in default and production configuration to prevent parameter leakage."""
    cfg = ServerConfig()
    assert cfg.database_echo_sql is False


def test_key_provider_and_envelope_string_representation_redaction():
    """Ensures repr() and str() of crypto components never leak raw key bytes or secrets."""
    raw_key = b"01234567890123456789012345678901"
    provider = EnvOrFileKeyProvider(default_key=raw_key, default_key_id="test_key_01")
    encryptor = TemplateEncryptor(provider)

    provider_repr = repr(provider)
    encryptor_repr = repr(encryptor)

    # Master key bytes must not appear in string representations
    assert "0123456789" not in provider_repr
    assert "0123456789" not in encryptor_repr
    assert raw_key.hex() not in provider_repr
    assert raw_key.hex() not in encryptor_repr


def test_crypto_exception_does_not_leak_key_bytes():
    """Invalid unwrapping must not print the raw key or ciphertext in error message."""
    raw_key = b"01234567890123456789012345678901"
    provider = EnvOrFileKeyProvider(default_key=raw_key, default_key_id="test_key_01")

    bogus_wrapped_dek = b"invalid_wrapped_bytes_of_length_40______"
    with pytest.raises(ValueError) as exc_info:
        provider.unwrap_key(bogus_wrapped_dek, "test_key_01")

    err_msg = str(exc_info.value)
    assert "0123456789" not in err_msg
    assert raw_key.hex() not in err_msg
    assert "invalid_wrapped_bytes" not in err_msg
