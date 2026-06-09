from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from ..ai_client import _call_review_ai
from ..schemas import ReviewAIPayload


def register_review_ai_routes(app: FastAPI) -> None:
    @app.post("/api/research/review-ai")
    def research_review_ai(payload: ReviewAIPayload) -> dict[str, Any]:
        try:
            return _call_review_ai(payload)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
