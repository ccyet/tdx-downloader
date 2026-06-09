from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from tdx_downloader.data.manager import DataManagementService, normalize_timeframes
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.research.history import HistorySearchConfig, search_history

from ..schemas import HistorySearchPayload
from ..serialization import _records


def register_research_history_routes(app: FastAPI) -> None:
    @app.post("/api/research/history")
    def research_history(payload: HistorySearchPayload) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframes([payload.timeframe])[0]
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=[payload.symbol],
                start=payload.lookback_start,
                end=payload.as_of,
            )
            result = search_history(
                bars,
                HistorySearchConfig(
                    symbol=payload.symbol,
                    as_of=payload.as_of,
                    window_size=payload.window_size,
                    forward_windows=tuple(payload.forward_windows),
                    candidate_n=payload.candidate_n,
                    top_n=payload.top_n,
                    exclusion_bars=payload.exclusion_bars,
                    nearby_gap_days=payload.nearby_gap_days,
                    path_weight=payload.path_weight,
                    window_start=payload.window_start,
                    algorithm=payload.algorithm,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stock_names = _history_stock_names(payload, result.symbol)
        stock_name = stock_names.get(result.symbol, "")
        result_rows = result.results.copy()
        if not result_rows.empty and "股票" not in result_rows.columns:
            result_rows.insert(1, "股票", stock_name)
        return {
            "summary": {
                "symbol": result.symbol,
                "stock_name": stock_name,
                "timeframe": timeframe,
                "as_of": result.as_of,
                "window_start": result.current_window["date"].iloc[0] if not result.current_window.empty else None,
                "window_size": result.window_size,
                "match_count": len(result.results),
                "algorithm": payload.algorithm,
            },
            "current_window": _records(result.current_window),
            "historical_windows": [_records(window) for window in result.historical_windows],
            "historical_chart_windows": [_records(window) for window in result.historical_chart_windows],
            "results": _records(result_rows),
        }


def _history_stock_names(payload: HistorySearchPayload, symbol: str) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    return service.repository.symbol_names(symbols=(symbol,))
