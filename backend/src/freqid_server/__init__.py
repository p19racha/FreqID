# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
freqid_server: Privacy-preserving face recognition inference and matching server.
"""

__version__ = "0.1.0"

from freqid_server.main import create_app

__all__ = ["__version__", "create_app"]
