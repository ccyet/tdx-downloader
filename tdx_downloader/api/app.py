from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import register_routes


def create_app() -> FastAPI:
    app = FastAPI(title="TDX Downloader API", version="0.2.0")
    cors_origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routes(app)
    _mount_static_frontend(app)
    return app


def _cors_origins() -> list[str]:
    raw = os.getenv("TDX_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://127.0.0.1:5173", "http://localhost:5173"]


def _mount_static_frontend(app: FastAPI) -> None:
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")


def main() -> None:
    import uvicorn

    host = os.getenv("TDX_API_HOST", "127.0.0.1")
    port = int(os.getenv("TDX_API_PORT", "8622"))
    reload = os.getenv("TDX_API_RELOAD", "1").strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run("tdx_downloader.api.app:app", host=host, port=port, reload=reload)


app = create_app()
