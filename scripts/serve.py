#!/usr/bin/env python3
"""Run the local ShowMe workspace on loopback only."""
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if __name__ == "__main__":
    uvicorn.run("showme.app:create_app", factory=True, host="127.0.0.1", port=8765,
                access_log=False, log_level="warning")
