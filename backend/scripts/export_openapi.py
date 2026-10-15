#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
export_openapi.py: Generates and exports OpenAPI specification for freqid-server.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from freqid_server.main import create_app


def export_openapi() -> None:
    app = create_app()
    openapi_schema = app.openapi()

    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "openapi.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)

    print(f"OpenAPI specification successfully exported to: {out_path}")
    print(f"Routes mapped: {len(openapi_schema.get('paths', {}))} paths")


if __name__ == "__main__":
    export_openapi()
