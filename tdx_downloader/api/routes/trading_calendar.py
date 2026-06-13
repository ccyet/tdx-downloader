from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException

from tdx_downloader.data.trading_calendar import save_trading_days

from ..constants import DEFAULT_DATA_ROOT
from ..fuyao_client import FuyaoAPIError, fetch_trading_days, normalize_trading_days


def register_trading_calendar_routes(app: FastAPI) -> None:
    @app.get("/api/trading-calendar")
    def trading_calendar(x_fuyao_api_key: str = Header(default="")) -> dict[str, Any]:
        try:
            payload = normalize_trading_days(fetch_trading_days(api_key=x_fuyao_api_key))
            save_trading_days(data_root=DEFAULT_DATA_ROOT, days=list(payload.get("days", [])), source="fuyao")
        except (FuyaoAPIError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"source": "fuyao", **payload}
