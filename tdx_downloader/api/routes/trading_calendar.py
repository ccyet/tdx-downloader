from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException

from ..fuyao_client import FuyaoAPIError, fetch_trading_days, normalize_trading_days


def register_trading_calendar_routes(app: FastAPI) -> None:
    @app.get("/api/trading-calendar")
    def trading_calendar(x_fuyao_api_key: str = Header(default="")) -> dict[str, Any]:
        try:
            payload = normalize_trading_days(fetch_trading_days(api_key=x_fuyao_api_key))
        except (FuyaoAPIError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"source": "fuyao", **payload}
