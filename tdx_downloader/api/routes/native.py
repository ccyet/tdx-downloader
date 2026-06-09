from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from ..native_picker import _open_native_directory_dialog
from ..schemas import DirectoryPickerPayload


def register_native_routes(app: FastAPI) -> None:
    @app.post("/api/pick-directory")
    def pick_directory(payload: DirectoryPickerPayload) -> dict[str, Any]:
        try:
            selected = _open_native_directory_dialog(payload.initial_directory, payload.title)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(selected) if selected is not None else None, "cancelled": selected is None}
