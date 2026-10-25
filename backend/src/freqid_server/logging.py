# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
logging.py: Structured logging engine with strict biometric data redaction rules.

CRITICAL PRIVACY INVARIANT (Hard Rule 4):
Server logs must NEVER contain raw payload bytes, floating-point embedding vectors,
or raw similarity arrays. Only request IDs, sizes, status codes, timings, and decisions
are permitted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any


class BiometricRedactionFilter(logging.Filter):
    """
    Log filter that intercepts and scrubs accidental biometric data leakage.
    Scans formatted messages for floating-point vectors or hex byte sequences.
    """

    # Matches floating point arrays like [0.1234, -0.5678, ...] or comma-separated float strings
    FLOAT_VECTOR_REGEX = re.compile(r"\[(?:\s*-?\d+\.\d+[\s,]*){4,}\]")
    # Matches byte reprs like b'...' (16+ chars) or escape sequences
    BYTES_LITERAL_REGEX = re.compile(r"b['\"][^'\"]{16,}['\"]")
    HEX_BYTES_REGEX = re.compile(r"(?:\\x[0-9a-fA-F]{2}){4,}")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.FLOAT_VECTOR_REGEX.sub("[REDACTED_BIOMETRIC_VECTOR]", record.msg)
            record.msg = self.BYTES_LITERAL_REGEX.sub("[REDACTED_BINARY_PAYLOAD]", record.msg)
            record.msg = self.HEX_BYTES_REGEX.sub("[REDACTED_BINARY_PAYLOAD]", record.msg)
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach request context if available
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "device_id"):
            log_entry["device_id"] = record.device_id
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "decision"):
            log_entry["decision"] = record.decision

        return json.dumps(log_entry)


def setup_logging(level: int = logging.INFO, json_format: bool = False) -> logging.Logger:
    """Configures root and freqid_server loggers with redaction filter."""
    logger = logging.getLogger("freqid_server")
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.addFilter(BiometricRedactionFilter())

        if json_format:
            handler.setFormatter(StructuredJsonFormatter())
        else:
            fmt = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
            handler.setFormatter(logging.Formatter(fmt))

        logger.addHandler(handler)

    return logger


def configure_logging(config: Any = None) -> logging.Logger:
    """Configures server logging based on server configuration."""
    json_format = False
    level = logging.INFO
    if config and getattr(config, "environment", "") == "production":
        json_format = True
    return setup_logging(level=level, json_format=json_format)


logger = setup_logging()
