from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from tdx_downloader.data.parallels_runtime import should_use_parallels_runtime

from ..task_store import _now_text


def register_health_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
            "time": _now_text(),
        }
