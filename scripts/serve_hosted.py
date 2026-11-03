#!/usr/bin/env python3
"""Run one hosted instance against its persistent data volume."""
import os
from pathlib import Path
import sys

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    from showme.deployment import hosted_settings
    hosted_settings(os.environ)  # Fail before binding if required configuration is absent.
    uvicorn.run("showme.deployment:create_hosted_app", factory=True, host="0.0.0.0",
                port=int(os.getenv("PORT", "8000")), workers=1,
                proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
                access_log=False, log_level="warning")
