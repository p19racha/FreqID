# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
main.py: FastAPI application factory, lifespan management, middleware wiring, and entry points.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from freqid_server.api import (
    routes_admin_auth,
    routes_admin_devices,
    routes_admin_system,
    routes_admin_users,
    routes_devices,
    routes_enroll,
    routes_health,
    routes_identify,
    routes_payload_key,
    routes_verify,
)
from freqid_server.audit.base import AuditSink
from freqid_server.audit.postgres import PostgresAuditSink
from freqid_server.auth.authenticator import UnifiedAuthenticator
from freqid_server.auth.base import RequestAuthenticator
from freqid_server.auth.lockout import LockoutManager
from freqid_server.config import ServerConfig, load_config
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.payload_envelope import ReplayDetector
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.errors import FreqIDServerError
from freqid_server.logging import configure_logging, logger
from freqid_server.middleware import NonceTracker, RateLimiter, SecurityMiddleware
from freqid_server.services.anomaly_detector import NearThresholdAnomalyDetector
from freqid_server.services.enrollment import EnrollmentService
from freqid_server.services.gallery import GalleryIndex
from freqid_server.services.inference import InferenceService
from freqid_server.services.matching import MatchingService
from freqid_server.storage.base import TemplateStore
from freqid_server.storage.memory import MemoryTemplateStore
from freqid_server.storage.postgres import PostgreSQLTemplateStore


def create_app(
    config: ServerConfig | None = None,
    store: TemplateStore | None = None,
    inference: InferenceService | None = None,
    audit_sink: AuditSink | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    authenticator: RequestAuthenticator | None = None,
) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    Supports dependency injection for testing and alternative runtime configurations.
    """
    active_config = config or load_config()
    configure_logging(active_config)

    # In-memory trackers
    nonce_tracker = NonceTracker(ttl_seconds=active_config.nonce_ttl_seconds)
    rate_limiter = RateLimiter(
        rate_limit_per_min=active_config.rate_limit_per_minute,
        max_failed_lockout=active_config.max_failed_attempts_lockout,
        lockout_sec=active_config.lockout_duration_seconds,
    )

    # Storage and audit wiring
    engine = None
    active_session_factory = session_factory
    active_store: TemplateStore
    active_audit: AuditSink | None = audit_sink
    active_key_provider: EnvOrFileKeyProvider | None = None

    if store is not None and hasattr(store, "encryptor") and store.encryptor is not None:
        active_key_provider = getattr(store.encryptor, "key_provider", None)

    if active_key_provider is None:
        def_k = (
            base64.b64decode(active_config.master_key) if active_config.master_key else b"\x00" * 32
        )
        active_key_provider = EnvOrFileKeyProvider(
            key_file_path=active_config.master_key_file or None,
            default_key=def_k,
            default_key_id=active_config.active_key_id,
        )

    if store is not None:
        active_store = store
    elif active_config.storage_backend == "postgres":
        engine = create_async_engine(
            active_config.database_url,
            pool_size=active_config.database_pool_size,
            max_overflow=active_config.database_max_overflow,
            pool_timeout=active_config.database_pool_timeout,
            pool_pre_ping=active_config.database_pool_pre_ping,
            echo=active_config.database_echo_sql,
        )
        active_session_factory = async_sessionmaker(engine, expire_on_commit=False)
        encryptor = TemplateEncryptor(key_provider=active_key_provider)
        active_store = PostgreSQLTemplateStore(
            session_factory=active_session_factory,
            encryptor=encryptor,
        )
        if active_audit is None:
            active_audit = PostgresAuditSink(
                session_factory=active_session_factory,
                enable_hash_chain=active_config.audit_enable_hash_chain,
            )
    else:
        active_store = MemoryTemplateStore(persistence_path=active_config.storage_path)

    gallery = GalleryIndex()

    # Authenticator and neural services
    lockout_manager = LockoutManager()
    if authenticator is not None:
        auth = authenticator
    else:
        auth = UnifiedAuthenticator(
            config=active_config,
            session_factory=active_session_factory,
            lockout_manager=lockout_manager,
        )
    active_inference = inference or InferenceService(active_config)
    matching = MatchingService(active_model_version=active_config.model_version)
    enrollment = EnrollmentService(
        config=active_config,
        inference_service=active_inference,
        store=active_store,
        gallery=gallery,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup
        logger.info(
            f"Starting FreqID Server v{active_config.model_version} on {active_config.host}:{active_config.port}"
        )
        active_inference.start()
        if active_audit is not None:
            await active_audit.start()
        await gallery.load_from_store(active_store)
        logger.info(f"FreqID Server readiness verified. Gallery size: {gallery.count} identities.")

        yield

        # Shutdown
        logger.info("Initiating FreqID Server graceful shutdown...")
        if active_audit is not None:
            await active_audit.shutdown()
        active_inference.shutdown()
        if engine is not None:
            await engine.dispose()
        logger.info("FreqID Server shutdown complete.")

    app = FastAPI(
        title="FreqID Server",
        description=(
            "Privacy-preserving face recognition server. Receives only partial-frequency "
            "representations (27-channel DCT) over TLS; raw spatial images are strictly prohibited."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Store references on app state for route dependency extraction
    app.state.config = active_config
    app.state.store = active_store
    app.state.audit_sink = active_audit
    app.state.gallery = gallery
    app.state.auth = auth
    app.state.authenticator = auth
    app.state.session_factory = active_session_factory
    app.state.lockout_manager = lockout_manager
    app.state.inference = active_inference
    app.state.matching = matching
    app.state.enrollment = enrollment
    app.state.rate_limiter = rate_limiter
    app.state.nonce_tracker = nonce_tracker
    app.state.key_provider = active_key_provider
    app.state.replay_detector = ReplayDetector(window_seconds=active_config.nonce_ttl_seconds)
    app.state.anomaly_detector = NearThresholdAnomalyDetector(
        threshold=active_config.decision_threshold,
        delta=0.05,
        max_clustering_events=5,
        window_seconds=300.0,
    )

    # 1. Wire CORS Middleware if configured
    if active_config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=active_config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 2. Wire Security Middleware
    app.add_middleware(
        SecurityMiddleware,
        config=active_config,
        nonce_tracker=nonce_tracker,
        rate_limiter=rate_limiter,
    )

    # 3. Register Global Exception Handlers
    @app.exception_handler(FreqIDServerError)
    async def freqid_server_error_handler(request: Request, exc: FreqIDServerError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        response_headers = {}
        if hasattr(exc, "retry_after") and exc.retry_after:
            response_headers["Retry-After"] = str(exc.retry_after)

        logger.warning(
            f"FreqIDServerError [{exc.error_code}]: {exc.message} (HTTP {exc.status_code}, req_id: {req_id})"
        )

        return JSONResponse(
            status_code=exc.status_code,
            headers=response_headers,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "request_id": req_id,
                },
                "detail": {
                    "error_code": exc.error_code,
                    "message": exc.message,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc.errors()),
                    "request_id": req_id,
                },
                "detail": str(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            f"Unhandled server error on {request.method} {request.url.path}: {exc} (req_id: {req_id})",
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred. Internal details redacted.",
                    "request_id": req_id,
                },
                "detail": "Internal server error.",
            },
        )

    # 4. Mount Routers
    app.include_router(routes_health.router)
    app.include_router(routes_verify.router)
    app.include_router(routes_identify.router)
    app.include_router(routes_enroll.router)
    app.include_router(routes_devices.router)
    app.include_router(routes_admin_auth.router)
    app.include_router(routes_admin_devices.router)
    app.include_router(routes_admin_users.router)
    app.include_router(routes_admin_system.router)
    app.include_router(routes_payload_key.router)

    return app


app = create_app()


def run_server() -> None:
    """Command-line entry point to run freqid-server with Uvicorn."""
    parser = argparse.ArgumentParser(description="FreqID Privacy-Preserving Inference Server")
    parser.add_argument("--host", type=str, default=None, help="Bind socket host (e.g. 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Bind socket port (e.g. 8000)")
    parser.add_argument(
        "--config", type=str, default=None, help="Path to server YAML configuration"
    )
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn live reload")
    args = parser.parse_args()

    cfg = load_config(config_path=args.config)
    host = args.host or cfg.host
    port = args.port or cfg.port

    uvicorn.run(
        "freqid_server.main:app",
        host=host,
        port=port,
        reload=args.reload,
        access_log=False,  # Logged by SecurityMiddleware
        workers=1,
    )


if __name__ == "__main__":
    run_server()
