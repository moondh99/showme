"""Explicit configuration for one persistent HTTPS service; no provider secrets."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def public_origin(value):
    if not value:
        return None
    origin = urlsplit(value)
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in ("", "/") or origin.query or origin.fragment
            or "*" in origin.netloc):
        raise ValueError("SHOWME_PUBLIC_ORIGIN must be an exact HTTPS origin.")
    return origin


def hosted_settings(env):
    origin = public_origin(env.get("SHOWME_PUBLIC_ORIGIN", ""))
    if origin is None:
        raise ValueError("Set SHOWME_PUBLIC_ORIGIN before starting the hosted service.")
    if len(env.get("SHOWME_AUTHOR_PASSWORD", "").strip()) < 12:
        raise ValueError("Set a SHOWME_AUTHOR_PASSWORD with at least 12 characters.")
    directory = Path(env.get("SHOWME_DATA_DIR", ""))
    if not directory.is_absolute():
        raise ValueError("SHOWME_DATA_DIR must name an absolute persistent directory.")
    if not env.get("MODEL_API_KEY", "").strip():
        raise ValueError("Set MODEL_API_KEY in the hosting service's secret settings.")
    limit = int(env.get("SHOWME_AI_DAILY_LIMIT", "40"))
    if limit < 1:
        raise ValueError("SHOWME_AI_DAILY_LIMIT must be a positive request count.")
    return {"directory": directory, "daily_limit": limit}


def create_hosted_app():
    settings = hosted_settings(os.environ)
    os.environ.setdefault("SHOWME_AI_DAILY_LIMIT", str(settings["daily_limit"]))
    from .app import ROOT, create_app
    app = create_app(data_dir=settings["directory"])
    if os.getenv("SHOWME_SEED_DEMO", "1") == "1":
        from .demo import seed_demo
        for scenario in ("storage-tags", "storage-tags-en"):
            seed_demo(app.state.store, ROOT / "public/demo/reception-setup", scenario=scenario)
    return app
