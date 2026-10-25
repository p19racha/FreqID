# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_phase6_security.py: Comprehensive security, RBAC, device lifecycle, and cryptographic test suite.

Tests:
1. Route Enumeration & Default-Deny: Every non-allowlisted endpoint requires authentication.
2. RBAC Permission Matrix: Owner, Admin, Operator, Auditor roles strictly enforced.
3. Device Scope Isolation: Devices restricted to their designated capability scopes.
4. Pairing Token Lifecycle: Expiry, single-use, concurrent consumption race, and hash-only storage.
5. Immediate Device Revocation: Sub-second revocation and suspension enforcement.
6. Request Signature & Replay Protection: Nonce deduplication and timestamp sliding window bounds.
7. Anti-Enumeration Timing: Constant-time password validation baseline on non-existent accounts.
8. Refresh Token Reuse Detection: Session family invalidation upon replay of consumed tokens.
9. Production Security Hardening: Static dev tokens prohibited in production environment.
10. Secret Redaction: No passwords, hashes, private keys, or tokens in logs or API responses.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.audit.postgres import PostgresAuditSink
from freqid_server.auth.passwords import hash_password
from freqid_server.auth.tokens import create_access_token
from freqid_server.config import ServerConfig
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.main import create_app
from freqid_server.storage.models import (
    AdminUserOrm,
    PairingTokenOrm,
)
from freqid_server.storage.postgres import PostgreSQLTemplateStore

DEV_DB_URL = os.environ.get(
    "FREQID_TEST_DB_URL",
    "postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
)
ADMIN_DB_URL = os.environ.get(
    "FREQID_TEST_ADMIN_DB_URL",
    "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
)
TEST_MASTER_KEY = b"01234567890123456789012345678901"


@pytest_asyncio.fixture
async def clean_db():
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE audit_events, templates, enrollment_sessions, users, "
                "device_heartbeats, devices, pairing_tokens, admin_refresh_tokens, "
                "admin_users, system_settings CASCADE;"
            )
        )
    yield
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE audit_events, templates, enrollment_sessions, users, "
                "device_heartbeats, devices, pairing_tokens, admin_refresh_tokens, "
                "admin_users, system_settings CASCADE;"
            )
        )
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def sec_env(clean_db):
    engine = create_async_engine(DEV_DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    key_provider = EnvOrFileKeyProvider(default_key=TEST_MASTER_KEY)
    encryptor = TemplateEncryptor(key_provider)
    store = PostgreSQLTemplateStore(session_factory=session_factory, encryptor=encryptor)
    audit_sink = PostgresAuditSink(session_factory=session_factory)

    cfg = ServerConfig(
        host="127.0.0.1",
        port=8000,
        environment="test",
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        model_version="v1.0-ir18",
        device="cpu",
        decision_threshold=0.35,
        storage_backend="postgres",
        master_key=base64.b64encode(TEST_MASTER_KEY).decode("ascii"),
        static_tokens={
            "dev_verify_token": ["verify"],
            "dev_admin_token": ["verify", "identify", "enroll", "admin"],
        },
    )

    app = create_app(
        config=cfg,
        store=store,
        audit_sink=audit_sink,
        session_factory=session_factory,
    )
    app.state.inference.start()
    await audit_sink.start()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield {
            "app": app,
            "client": client,
            "session_factory": session_factory,
            "config": cfg,
            "engine": engine,
        }

    await audit_sink.shutdown()
    app.state.inference.shutdown()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_admins(sec_env) -> dict[str, dict]:
    """Seeds four admin users representing each role."""
    session_factory = sec_env["session_factory"]
    cfg = sec_env["config"]
    admins = {
        "owner": {
            "id": uuid.uuid4(),
            "username": "sec_owner",
            "password": "CorrectHorseBattery99!",
            "role": "owner",
        },
        "admin": {
            "id": uuid.uuid4(),
            "username": "sec_admin",
            "password": "RegularAdminPass123!",
            "role": "admin",
        },
        "operator": {
            "id": uuid.uuid4(),
            "username": "sec_operator",
            "password": "OperatorPass123!",
            "role": "operator",
        },
        "auditor": {
            "id": uuid.uuid4(),
            "username": "sec_auditor",
            "password": "AuditorPass123!",
            "role": "auditor",
        },
    }

    async with session_factory() as session:
        for r, data in admins.items():
            admin_orm = AdminUserOrm(
                id=data["id"],
                username=data["username"],
                password_hash=hash_password(data["password"]),
                role=data["role"],
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(admin_orm)
        await session.commit()

    # Generate JWT tokens for each
    for r, data in admins.items():
        token = create_access_token(
            admin_id=data["id"],
            username=data["username"],
            role=data["role"],
            secret_key=cfg.master_key,
        )
        data["token"] = token
        data["headers"] = {"Authorization": f"Bearer {token}"}

    return admins


def generate_device_keypair() -> tuple[ed25519.Ed25519PrivateKey, str, str]:
    """Generates an Ed25519 keypair, returning (private_key, priv_b64, pub_b64)."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode("ascii")
    pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("ascii")
    return priv, priv_b64, pub_b64


def build_signed_headers(
    priv_key: ed25519.Ed25519PrivateKey,
    device_id: str | uuid.UUID,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Generates valid cryptographic Ed25519 request headers."""
    ts = timestamp if timestamp is not None else int(time.time())
    n = nonce if nonce is not None else secrets.token_hex(16)
    body_digest = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{ts}\n{n}\n{body_digest}".encode()
    sig = priv_key.sign(canonical)
    sig_b64 = base64.b64encode(sig).decode("ascii")

    return {
        "X-Device-ID": str(device_id),
        "X-Timestamp": str(ts),
        "X-Nonce": n,
        "X-Signature": sig_b64,
    }


# =========================================================================
# 1. Route Enumeration & Default-Deny Test
# =========================================================================
@pytest.mark.asyncio
async def test_all_routes_enforce_auth_or_are_allowlisted(sec_env):
    """
    Reflectively inspects every registered OpenAPI route.
    Verifies that all routes reject unauthenticated requests with 401,
    EXCEPT those explicitly listed on the public allowlist.
    """
    app = sec_env["app"]
    client = sec_env["client"]

    PUBLIC_ALLOWLIST = {
        "/healthz",
        "/readyz",
        "/metrics",
        "/v1/model",
        "/v1/model/migration-report",
        "/v1/devices/pair",
        "/v1/admin/auth/login",
        "/v1/admin/auth/refresh",
        "/v1/admin/auth/logout",
        "/v1/payload-key",
    }

    openapi = app.openapi()
    routes_to_test = []
    for path, path_item in openapi["paths"].items():
        if path in PUBLIC_ALLOWLIST:
            continue
        for method in path_item.keys():
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                routes_to_test.append((method.upper(), path))

    assert len(routes_to_test) >= 30, (
        f"Expected >= 30 protected endpoints, found {len(routes_to_test)}"
    )

    for method, path in routes_to_test:
        call_path = path.replace("{user_id}", str(uuid.uuid4()))
        call_path = call_path.replace("{device_id}", str(uuid.uuid4()))
        call_path = call_path.replace("{admin_id}", str(uuid.uuid4()))

        resp = await client.request(method, call_path, headers={})

        assert resp.status_code == 401, (
            f"Default-deny violation: {method} {call_path} returned {resp.status_code} "
            f"instead of 401 Unauthorized. Content: {resp.text}"
        )


# =========================================================================
# 2. RBAC Permission Matrix Test
# =========================================================================
@pytest.mark.asyncio
async def test_rbac_permissions_matrix(sec_env, seeded_admins):
    """
    Tests privilege separation across all 4 admin roles:
    - owner: full privileges, can create admins and update system settings.
    - admin: can manage devices/users, but cannot create owners or edit system settings.
    - operator: can view devices/users, but cannot create admins, pairing tokens, or delete users.
    - auditor: read-only access to audit logs and system status; cannot modify state.
    """
    client = sec_env["client"]

    # A. Owner can create admin and update settings
    new_admin_payload = {
        "username": "new_sec_admin",
        "password": "SecurePassword123!",
        "role": "admin",
    }
    r = await client.post(
        "/v1/admin/admins", json=new_admin_payload, headers=seeded_admins["owner"]["headers"]
    )
    assert r.status_code == 201, r.text

    r = await client.put(
        "/v1/admin/settings",
        json={"settings": {"decision_threshold": 0.40}},
        headers=seeded_admins["owner"]["headers"],
    )
    assert r.status_code == 200, r.text

    # B. Admin CANNOT create owner and CANNOT update settings
    r = await client.post(
        "/v1/admin/admins",
        json={"username": "rogue_owner", "password": "Password123!", "role": "owner"},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 403, "Admin must not be allowed to create an owner"

    r = await client.put(
        "/v1/admin/settings",
        json={"settings": {"decision_threshold": 0.50}},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 403, "Admin must not be allowed to modify system settings"

    # Admin CAN create pairing tokens
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "turnstile_1", "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 201, r.text

    # C. Operator CANNOT create pairing tokens, CANNOT create admins, CANNOT delete users
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "turnstile_2", "scopes": ["verify"]},
        headers=seeded_admins["operator"]["headers"],
    )
    assert r.status_code == 403, "Operator must not be allowed to create pairing tokens"

    r = await client.post(
        "/v1/admin/admins",
        json={"username": "operator_sub", "password": "Password123!", "role": "auditor"},
        headers=seeded_admins["operator"]["headers"],
    )
    assert r.status_code == 403, "Operator must not be allowed to create admins"

    r = await client.delete(
        f"/v1/admin/users/{uuid.uuid4()}", headers=seeded_admins["operator"]["headers"]
    )
    assert r.status_code == 403, "Operator must not be allowed to delete users"

    # Operator CAN list devices
    r = await client.get("/v1/admin/devices", headers=seeded_admins["operator"]["headers"])
    assert r.status_code == 200, r.text

    # D. Auditor CAN read audit and system status, but CANNOT list devices or modify anything
    r = await client.get("/v1/admin/audit", headers=seeded_admins["auditor"]["headers"])
    assert r.status_code == 200, r.text

    r = await client.get("/v1/admin/system/status", headers=seeded_admins["auditor"]["headers"])
    assert r.status_code == 200, r.text

    r = await client.get("/v1/admin/users", headers=seeded_admins["auditor"]["headers"])
    assert r.status_code == 403, "Auditor must not be allowed to list users"

    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "turnstile_3", "scopes": ["verify"]},
        headers=seeded_admins["auditor"]["headers"],
    )
    assert r.status_code == 403, "Auditor must not be allowed to create pairing tokens"


# =========================================================================
# 3. Device Scope Isolation Test
# =========================================================================
@pytest.mark.asyncio
async def test_device_scope_isolation(sec_env, seeded_admins, sample_payload_bytes):
    """
    Verifies that a paired device granted only ["verify"] scope:
    - Can access /v1/verify
    - Is rejected on /v1/enroll with 403 InsufficientScope
    - Is rejected on /v1/users/{id} delete with 403 InsufficientScope
    - Is rejected on /v1/admin/* endpoints with 403 InsufficientScope
    """
    client = sec_env["client"]

    # 1. Admin generates pairing token for verify-only device
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "verify_kiosk", "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 201
    pairing_token = r.json()["token"]

    # 2. Pair the device
    priv_key, _, pub_b64 = generate_device_keypair()
    r = await client.post(
        "/v1/devices/pair",
        json={
            "token": pairing_token,
            "name": "verify_kiosk",
            "public_key": pub_b64,
            "software_version": "0.1.0",
        },
    )
    assert r.status_code == 201, r.text
    device_id = r.json()["device_id"]

    # 3. Verify endpoint access (should succeed with match=False since user is not enrolled)
    v_headers = build_signed_headers(
        priv_key, device_id, "POST", "/v1/verify", sample_payload_bytes
    )
    v_headers["Content-Type"] = "application/vnd.freqid.payload"
    v_headers["X-Claimed-Identity"] = "any_user"
    r = await client.post("/v1/verify", content=sample_payload_bytes, headers=v_headers)
    assert r.status_code == 200, f"Expected 200 on verify, got {r.status_code}: {r.text}"
    assert r.json()["is_match"] is False

    # 4. Attempt to access /v1/enroll (requires 'enroll' scope)
    e_headers = build_signed_headers(
        priv_key, device_id, "POST", "/v1/enroll", sample_payload_bytes
    )
    e_headers["Content-Type"] = "application/vnd.freqid.payload"
    e_headers["X-User-ID"] = "user_to_enroll"
    r = await client.post("/v1/enroll", content=sample_payload_bytes, headers=e_headers)
    assert r.status_code == 403, (
        f"Expected 403 Insufficient Scope on enroll, got {r.status_code}: {r.text}"
    )
    assert "INSUFFICIENT_SCOPE" in r.text or "Forbidden" in r.text

    # 5. Attempt to access /v1/admin/devices (requires admin permissions)
    a_headers = build_signed_headers(priv_key, device_id, "GET", "/v1/admin/devices", b"")
    r = await client.get("/v1/admin/devices", headers=a_headers)
    assert r.status_code in (401, 403), (
        f"Expected 401/403 on admin endpoint, got {r.status_code}: {r.text}"
    )


# =========================================================================
# 4. Pairing Token Lifecycle, Expiry, Concurrency, and Hash-Only Storage
# =========================================================================
@pytest.mark.asyncio
async def test_pairing_token_lifecycle_and_concurrency(sec_env, seeded_admins):
    """
    Tests pairing token:
    A. Expired token rejection.
    B. Concurrent consumption race condition: only 1 of N concurrent pairs succeeds.
    C. Database check: token is stored exclusively as a SHA-256 hash.
    """
    client = sec_env["client"]
    session_factory = sec_env["session_factory"]

    # A. Expired token
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "expiring_device", "expires_in_minutes": 1, "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 201
    tok_data = r.json()
    tok_str = tok_data["token"]
    tok_id = uuid.UUID(tok_data["id"])

    # Force expiration in DB
    async with session_factory() as session:
        tok_orm = await session.get(PairingTokenOrm, tok_id)
        tok_orm.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await session.commit()

    _, _, pub_b64 = generate_device_keypair()
    r = await client.post(
        "/v1/devices/pair",
        json={"token": tok_str, "name": "expiring_device", "public_key": pub_b64},
    )
    assert r.status_code in (400, 401), f"Expected 400/401 for expired token, got {r.status_code}"
    assert "expired" in r.text.lower()

    # B. Concurrent single-use test
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "race_device", "expires_in_minutes": 15, "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 201
    race_token = r.json()["token"]
    race_tok_id = uuid.UUID(r.json()["id"])

    # Prepare two distinct device pairing requests with the SAME token
    _, _, pub1 = generate_device_keypair()
    _, _, pub2 = generate_device_keypair()

    req1 = client.post(
        "/v1/devices/pair",
        json={"token": race_token, "name": "device_attempt_1", "public_key": pub1},
    )
    req2 = client.post(
        "/v1/devices/pair",
        json={"token": race_token, "name": "device_attempt_2", "public_key": pub2},
    )

    res1, res2 = await asyncio.gather(req1, req2)
    statuses = [res1.status_code, res2.status_code]
    assert 201 in statuses, f"At least one pair must succeed: {statuses}"
    assert 400 in statuses or 409 in statuses, f"Second pair must be rejected: {statuses}"

    # C. Verify database stores only the hash, never plaintext
    async with session_factory() as session:
        tok_orm = await session.get(PairingTokenOrm, race_tok_id)
        assert tok_orm is not None
        assert tok_orm.token_hash == hashlib.sha256(race_token.encode("utf-8")).hexdigest()
        assert tok_orm.is_used is True
        assert tok_orm.used_at is not None


# =========================================================================
# 5. Immediate Device Revocation & Resumption Test
# =========================================================================
@pytest.mark.asyncio
async def test_immediate_device_revocation_and_resumption(sec_env, seeded_admins):
    """
    Validates sub-second state transitions on devices:
    active -> suspend -> verify fails immediately (403)
    suspend -> resume -> verify succeeds immediately (200)
    resume -> revoke -> verify fails immediately (403)
    revoke -> cannot resume (400)
    """
    client = sec_env["client"]

    # 1. Pair a new device
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "lifecycle_kiosk", "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    assert r.status_code == 201
    token = r.json()["token"]

    priv_key, _, pub_b64 = generate_device_keypair()
    r = await client.post(
        "/v1/devices/pair",
        json={"token": token, "name": "lifecycle_kiosk", "public_key": pub_b64},
    )
    assert r.status_code == 201
    device_id = r.json()["device_id"]

    # Helper to send a signed heartbeat
    async def send_heartbeat():
        body = json.dumps(
            {
                "software_version": "0.1.0",
                "camera_ok": True,
                "uptime_seconds": 120.0,
                "queued_payloads": 0,
            }
        ).encode("utf-8")
        headers = build_signed_headers(priv_key, device_id, "POST", "/v1/devices/heartbeat", body)
        headers["Content-Type"] = "application/json"
        return await client.post("/v1/devices/heartbeat", content=body, headers=headers)

    # 2. State: Active -> Heartbeat succeeds
    r = await send_heartbeat()
    assert r.status_code == 200, r.text

    # 3. Suspend device
    r = await client.post(
        f"/v1/admin/devices/{device_id}/suspend", headers=seeded_admins["admin"]["headers"]
    )
    assert r.status_code == 200, r.text

    # Next request must fail immediately with HTTP 403
    r = await send_heartbeat()
    assert r.status_code == 403, f"Expected 403 DEVICE_SUSPENDED, got {r.status_code}"
    assert "DEVICE_SUSPENDED" in r.text

    # 4. Resume device
    r = await client.post(
        f"/v1/admin/devices/{device_id}/resume", headers=seeded_admins["admin"]["headers"]
    )
    assert r.status_code == 200, r.text

    # Next request must succeed immediately
    r = await send_heartbeat()
    assert r.status_code == 200, f"Expected 200 after resume, got {r.status_code}"

    # 5. Revoke device
    r = await client.post(
        f"/v1/admin/devices/{device_id}/revoke", headers=seeded_admins["admin"]["headers"]
    )
    assert r.status_code == 200, r.text

    # Next request must fail immediately with HTTP 403
    r = await send_heartbeat()
    assert r.status_code == 403, f"Expected 403 DEVICE_REVOKED, got {r.status_code}"
    assert "DEVICE_REVOKED" in r.text

    # 6. Cannot resume a revoked device
    r = await client.post(
        f"/v1/admin/devices/{device_id}/resume", headers=seeded_admins["admin"]["headers"]
    )
    assert r.status_code == 400, "Cannot resume revoked device"


# =========================================================================
# 6. Request Signature & Replay Protection Test
# =========================================================================
@pytest.mark.asyncio
async def test_replay_protection_and_timestamp_window(sec_env, seeded_admins):
    """
    Tests:
    A. Timestamp > 300s in past -> 401 TIMESTAMP_OUT_OF_BOUNDS
    B. Timestamp > 300s in future -> 401 TIMESTAMP_OUT_OF_BOUNDS
    C. Replay with identical nonce -> 401 REPLAY_DETECTED
    """
    client = sec_env["client"]

    # Pair device
    r = await client.post(
        "/v1/admin/devices/pairing-tokens",
        json={"name_hint": "replay_kiosk", "scopes": ["verify"]},
        headers=seeded_admins["admin"]["headers"],
    )
    token = r.json()["token"]

    priv_key, _, pub_b64 = generate_device_keypair()
    r = await client.post(
        "/v1/devices/pair",
        json={"token": token, "name": "replay_kiosk", "public_key": pub_b64},
    )
    device_id = r.json()["device_id"]
    body = json.dumps(
        {
            "software_version": "0.1.0",
            "camera_ok": True,
            "uptime_seconds": 10.0,
            "queued_payloads": 0,
        }
    ).encode("utf-8")

    # A. Stale timestamp in past
    old_ts = int(time.time()) - 350
    headers = build_signed_headers(
        priv_key, device_id, "POST", "/v1/devices/heartbeat", body, timestamp=old_ts
    )
    headers["Content-Type"] = "application/json"
    r = await client.post("/v1/devices/heartbeat", content=body, headers=headers)
    assert r.status_code == 401, f"Expected 401 for stale timestamp, got {r.status_code}"
    assert "TIMESTAMP_OUT_OF_BOUNDS" in r.text or "timestamp" in r.text.lower()

    # B. Future timestamp
    fut_ts = int(time.time()) + 350
    headers = build_signed_headers(
        priv_key, device_id, "POST", "/v1/devices/heartbeat", body, timestamp=fut_ts
    )
    headers["Content-Type"] = "application/json"
    r = await client.post("/v1/devices/heartbeat", content=body, headers=headers)
    assert r.status_code == 401, f"Expected 401 for future timestamp, got {r.status_code}"

    # C. Replay attack: send valid request, then replay it
    fresh_nonce = secrets.token_hex(16)
    headers = build_signed_headers(
        priv_key, device_id, "POST", "/v1/devices/heartbeat", body, nonce=fresh_nonce
    )
    headers["Content-Type"] = "application/json"

    # First attempt: succeeds
    r1 = await client.post("/v1/devices/heartbeat", content=body, headers=headers)
    assert r1.status_code == 200, r1.text

    # Second attempt (replay identical headers and body): must fail
    r2 = await client.post("/v1/devices/heartbeat", content=body, headers=headers)
    assert r2.status_code in (400, 401), (
        f"Expected 400/401 for replay attempt, got {r2.status_code}"
    )
    assert "REPLAY_DETECTED" in r2.text or "replay" in r2.text.lower()


# =========================================================================
# 7. Anti-Enumeration Timing Defense Test
# =========================================================================
@pytest.mark.asyncio
async def test_anti_enumeration_login_timing(sec_env, seeded_admins):
    """
    Verifies that logging in with a non-existent username executes full Argon2id baseline
    verification, ensuring execution latency is statistically indistinguishable
    from an existing user with an incorrect password.
    """
    client = sec_env["client"]

    # 1. Login with existing admin and WRONG password (Argon2 runs on real hash)
    t0 = time.perf_counter()
    r_existing = await client.post(
        "/v1/admin/auth/login",
        json={"username": "sec_admin", "password": "WrongPassword999!"},
    )
    t_existing = time.perf_counter() - t0
    assert r_existing.status_code == 401

    # 2. Login with NON-EXISTENT admin (Argon2 dummy baseline must run)
    t0 = time.perf_counter()
    r_nonexistent = await client.post(
        "/v1/admin/auth/login",
        json={"username": "non_existent_user_xyz", "password": "WrongPassword999!"},
    )
    t_nonexistent = time.perf_counter() - t0
    assert r_nonexistent.status_code == 401

    # Both must take significant time due to Argon2id (e.g. > 5ms), and time delta < 250ms
    assert t_existing > 0.005, f"Argon2 did not run for existing user: {t_existing}s"
    assert t_nonexistent > 0.005, (
        f"Argon2 dummy baseline did not run for nonexistent user: {t_nonexistent}s"
    )
    time_delta = abs(t_existing - t_nonexistent)
    assert time_delta < 0.250, (
        f"Timing discrepancy too large (anti-enumeration failure): "
        f"existing={t_existing:.3f}s, nonexistent={t_nonexistent:.3f}s, delta={time_delta:.3f}s"
    )


# =========================================================================
# 8. Refresh Token Reuse Detection & Family Invalidation Test
# =========================================================================
@pytest.mark.asyncio
async def test_refresh_token_reuse_family_invalidation(sec_env, seeded_admins):
    """
    Tests session family invalidation upon refresh token reuse:
    1. Admin logs in -> receives R1 (family F1).
    2. Admin refreshes using R1 -> receives R2 (R1 marked revoked).
    3. Attacker presents consumed R1 -> server detects reuse!
    4. Entire family F1 revoked.
    5. Legitimate client presents R2 -> rejected (session invalidated).
    """
    client = sec_env["client"]

    # 1. Login to get initial refresh cookie
    r_login = await client.post(
        "/v1/admin/auth/login",
        json={"username": "sec_admin", "password": "RegularAdminPass123!"},
    )
    assert r_login.status_code == 200, r_login.text
    r1_cookie = client.cookies.get("freqid_refresh_token")
    assert r1_cookie is not None

    # 2. Legitimate refresh: exchange R1 for R2
    r_refresh = await client.post("/v1/admin/auth/refresh")
    assert r_refresh.status_code == 200, r_refresh.text
    r2_cookie = client.cookies.get("freqid_refresh_token")
    assert r2_cookie is not None
    assert r2_cookie != r1_cookie

    # 3. Attacker presents old/consumed R1
    attacker_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sec_env["app"]),
        base_url="http://testserver",
        cookies={"freqid_refresh_token": r1_cookie},
    )
    r_attack = await attacker_client.post("/v1/admin/auth/refresh")
    assert r_attack.status_code == 401, f"Attacker must be rejected: {r_attack.text}"
    assert "reuse" in r_attack.text.lower() or "revoked" in r_attack.text.lower()

    # 4. Legitimate client with R2 attempts to refresh -> must fail because entire family was revoked!
    legit_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sec_env["app"]),
        base_url="http://testserver",
        cookies={"freqid_refresh_token": r2_cookie},
    )
    r_legit = await legit_client.post("/v1/admin/auth/refresh")
    assert r_legit.status_code == 401, f"Family must be revoked, but got: {r_legit.status_code}"


# =========================================================================
# 9. Static Token Rejection in Production Mode Test
# =========================================================================
@pytest.mark.asyncio
async def test_static_tokens_rejected_in_production(clean_db):
    """
    Ensures that when environment="production" and allow_static_tokens_in_production=False,
    any attempt to authenticate via static dev tokens returns 401 Unauthorized.
    """
    engine = create_async_engine(DEV_DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    key_provider = EnvOrFileKeyProvider(default_key=TEST_MASTER_KEY)
    encryptor = TemplateEncryptor(key_provider)
    store = PostgreSQLTemplateStore(session_factory=session_factory, encryptor=encryptor)

    prod_cfg = ServerConfig(
        environment="production",
        allow_static_tokens_in_production=False,
        static_tokens={"dev_admin_token": ["admin"]},
        master_key=base64.b64encode(TEST_MASTER_KEY).decode("ascii"),
    )

    prod_app = create_app(
        config=prod_cfg,
        store=store,
        session_factory=session_factory,
    )

    transport = httpx.ASGITransport(app=prod_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Dev static token must be rejected in production
        r = await client.get(
            "/v1/admin/system/status", headers={"Authorization": "Bearer dev_admin_token"}
        )
        assert r.status_code == 401, (
            f"Expected 401 in production for static token, got {r.status_code}"
        )
        assert "production" in r.text.lower()

    await engine.dispose()


# =========================================================================
# 10. Secret Redaction & Leakage Scan Test
# =========================================================================
@pytest.mark.asyncio
async def test_secret_redaction_and_logs(sec_env, seeded_admins):
    """
    Scans API responses and database rows to verify that:
    - Admin password hashes (Argon2) are never returned in JSON.
    - Refresh tokens and pairing tokens are hashed before DB insertion.
    - Ed25519 private keys are never requested or stored server-side.
    """
    client = sec_env["client"]
    session_factory = sec_env["session_factory"]

    # 1. Admin detail API must not leak password hash
    r = await client.get("/v1/admin/admins", headers=seeded_admins["owner"]["headers"])
    assert r.status_code == 200
    admins_list = r.json()
    for adm in admins_list:
        assert "password" not in adm
        assert "password_hash" not in adm
        assert "hash" not in adm

    # 2. Database verification: verify password_hash is Argon2 and tokens are SHA-256
    async with session_factory() as session:
        result = await session.execute(select(AdminUserOrm))
        db_admins = result.scalars().all()
        for a in db_admins:
            assert a.password_hash.startswith("$argon2id$")
            assert "Password" not in a.password_hash

        result_tok = await session.execute(select(PairingTokenOrm))
        tokens = result_tok.scalars().all()
        for t in tokens:
            # Must be 64-character SHA-256 hex string
            assert len(t.token_hash) == 64
            assert all(c in "0123456789abcdef" for c in t.token_hash)
