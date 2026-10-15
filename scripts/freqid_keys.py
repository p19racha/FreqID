#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
freqid_keys.py: Helper script pointing directly to freqid_server.cli_keys.
"""

import sys
from pathlib import Path

# Add backend/src to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend" / "src"))

from freqid_server.cli_keys import main

if __name__ == "__main__":
    main()
