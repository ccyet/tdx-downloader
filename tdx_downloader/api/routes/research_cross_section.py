from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
import pandas as pd

from tdx_downloader.data.manager import DataManagementService, normalize_symbol_tuple, normalize_timeframes
from tdx_downloader.data.schema import inclusive_end_timestamp, normalize_symbol
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.research.similarity import (
    CrossSectionSearchConfig,
    CrossSectionWindowTraversalConfig,
    search_cross_section,
    search_cross_section_window_traversal,
)

from ..schemas import CrossSectionSearchPayload
from ..serialization import _json_value, _records


CROSS_SECTION_CHART_CONTEXT_BARS = 20
CROSS_SECTION_CHART_CONTEXT_DAYS = CROSS_SECTION_CHART_CONTEXT_BARS * 2 + 7


def register_research_cross_section_routes(app: FastAPI) -> None:
    @app.post("/api/research/cross-section")
    def research_cross_section(payload: CrossSectionSearchPayload) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframes([payload.timeframe])[0]
            symbols = normalize_symbol_tuple([payload.target_symbol, *payload.universe_symbols])
            if len(symbols) < 2:
                raise ValueError("横截面相似至少需要目标标的和 1 个候选标的。")
            search_mode = _cross_section_search_mode(payload.search_mode)
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=symbols,
                start=_cross_section_payload_read_start(payload, search_mode),
                end=_cross_section_payload_read_end(payload, search_mode),
            )
            if search_mode == "traversal":
                traversal_start = payload.traversal_start or payload.start
                traversal_end = payload.traversal_end or payload.end
                result = search_cross_section_window_traversal(
                    bars,
                    CrossSectionWindowTraversalConfig(
                        target_symbol=payload.target_symbol,
                        universe_symbols=tuple(payload.universe_symbols),
                        target_start=payload.start,
                        target_end=payload.end,
                        traversal_start=traversal_start,
                        traversal_end=traversal_end,
                        top_n=payload.top_n,
                        min_coverage=payload.min_coverage,
                        path_weight=payload.path_weight,
                        exclusion_bars=payload.exclusion_bars,
                        forward_windows=tuple(payload.forward_windows),
                    ),
                )
            else:
                result = search_cross_section(
                    bars,
                    CrossSectionSearchConfig(
                        target_symbol=payload.target_symbol,
                        universe_symbols=tuple(payload.universe_symbols),
                        start=payload.start,
                        end=payload.end,
                        top_n=payload.top_n,
                        min_coverage=payload.min_coverage,
                        path_weight=payload.path_weight,
                        forward_windows=tuple(payload.forward_windows),
                        date_tolerance_bars=payload.date_tolerance_bars,
                    ),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stock_names = _cross_section_stock_names(payload, symbols)
        stock_name = stock_names.get(result.target_symbol, "")
        result_rows = result.results.copy()
        if not result_rows.empty and "股票" not in result_rows.columns:
            result_rows.insert(1, "股票", result_rows["symbol"].map(lambda value: stock_names.get(normalize_symbol(value), "")))
        summary = {
            "target_symbol": result.target_symbol,
            "stock_name": stock_name,
            "timeframe": timeframe,
            "start": result.start if hasattr(result, "start") else result.target_start,
            "end": result.end if hasattr(result, "end") else result.target_end,
            "target_start": result.start if hasattr(result, "start") else result.target_start,
            "target_end": result.end if hasattr(result, "end") else result.target_end,
            "window_size": result.window_size,
            "match_count": len(result.results),
            "skipped_count": len(result.skipped),
            "search_mode": search_mode,
        }
        if search_mode == "traversal":
            summary.update(
                {
                    "traversal_start": result.traversal_start,
                    "traversal_end": result.traversal_end,
                    "candidate_start": result.traversal_start,
                    "candidate_end": result.traversal_end,
                }
            )
        else:
            summary.update(
                {
                    "candidate_start": summary["start"],
                    "candidate_end": summary["end"],
                }
            )
        return {
            "summary": summary,
            "results": _records(result_rows),
            "skipped": _records(result.skipped),
            "target_window": _symbol_window_candles(bars, result.target_symbol, summary["start"], summary["end"]),
            "target_chart_window": _symbol_chart_candles(bars, result.target_symbol, summary["start"], summary["end"]),
            "target_segments": [_chart_window_segment(summary["start"], summary["end"])],
            "candidate_windows": _cross_section_candidate_windows(bars, result_rows, stock_names=stock_names),
        }


def _cross_section_search_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"same_date", "same", "cross", "同区间"}:
        return "same_date"
    if normalized in {"traversal", "window_traversal", "search_interval", "指定区间", "窗口遍历"}:
        return "traversal"
    raise ValueError("横截面搜索模式仅支持 same_date 或 traversal。")


def _cross_section_payload_read_start(payload: CrossSectionSearchPayload, search_mode: str) -> str:
    if search_mode == "traversal":
        values = [pd.Timestamp(payload.start), pd.Timestamp(payload.traversal_start or payload.start)]
        return _cross_section_read_start(min(values).date().isoformat(), payload.date_tolerance_bars)
    return _cross_section_read_start(payload.start, payload.date_tolerance_bars)


def _cross_section_payload_read_end(payload: CrossSectionSearchPayload, search_mode: str) -> str:
    if search_mode == "traversal":
        end = max(pd.Timestamp(payload.end), pd.Timestamp(payload.traversal_end or payload.end))
        return _cross_section_read_end(end.date().isoformat(), tuple(payload.forward_windows))
    return _cross_section_read_end(payload.end, tuple(payload.forward_windows))


def _cross_section_read_start(start: str, tolerance_bars: int) -> str:
    padding_days = max(CROSS_SECTION_CHART_CONTEXT_DAYS, int(tolerance_bars) * 5 + 7)
    return (pd.Timestamp(start) - pd.Timedelta(days=padding_days)).date().isoformat()


def _cross_section_read_end(end: str, forward_windows: tuple[int, ...]) -> str:
    max_forward = max(forward_windows) if forward_windows else 0
    padding_days = max(CROSS_SECTION_CHART_CONTEXT_DAYS, int(max_forward) * 5 + 7)
    return (pd.Timestamp(end) + pd.Timedelta(days=padding_days)).date().isoformat()


def _cross_section_stock_names(payload: CrossSectionSearchPayload, symbols: tuple[str, ...]) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    return service.repository.symbol_names(symbols=symbols)


def _symbol_window_candles(
    bars: pd.DataFrame,
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> list[dict[str, Any]]:
    if bars.empty:
        return []
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    normalized_symbol = normalize_symbol(symbol)
    window = frame.loc[
        (frame["stock_code"] == normalized_symbol)
        & frame["date"].between(pd.Timestamp(start), inclusive_end_timestamp(end))
    ].sort_values("date")
    return _review_candles(window, include_symbol=True)


def _symbol_chart_candles(
    bars: pd.DataFrame,
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    context_bars: int = CROSS_SECTION_CHART_CONTEXT_BARS,
) -> list[dict[str, Any]]:
    if bars.empty:
        return []
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    symbol_frame = frame.loc[frame["stock_code"] == normalize_symbol(symbol)].sort_values("date").reset_index(drop=True)
    if symbol_frame.empty:
        return []
    start_ts = pd.Timestamp(start)
    end_ts = inclusive_end_timestamp(end)
    window_positions = symbol_frame.index[symbol_frame["date"].between(start_ts, end_ts)].to_list()
    if not window_positions:
        return []
    left = max(0, int(window_positions[0]) - int(context_bars))
    right = min(len(symbol_frame), int(window_positions[-1]) + int(context_bars) + 1)
    return _review_candles(symbol_frame.iloc[left:right], include_symbol=True)


def _cross_section_candidate_windows(
    bars: pd.DataFrame,
    results: pd.DataFrame,
    *,
    stock_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if results.empty:
        return []
    name_map = stock_names or {}
    rows: list[dict[str, Any]] = []
    for index, row in results.reset_index(drop=True).iterrows():
        symbol = normalize_symbol(row.get("symbol", ""))
        if not symbol:
            continue
        start = row.get("区间开始")
        end = row.get("区间结束")
        rows.append(
            {
                "rank": index + 1,
                "symbol": symbol,
                "name": name_map.get(symbol, ""),
                "start": _json_value(start),
                "end": _json_value(end),
                "candles": _symbol_window_candles(bars, symbol, pd.Timestamp(start), pd.Timestamp(end)),
                "chart_candles": _symbol_chart_candles(bars, symbol, pd.Timestamp(start), pd.Timestamp(end)),
                "segments": [_chart_window_segment(start, end)],
            }
        )
    return rows


def _chart_window_segment(start: Any, end: Any) -> dict[str, str]:
    return {
        "start": pd.Timestamp(start).date().isoformat(),
        "end": pd.Timestamp(end).date().isoformat(),
        "direction": "对标窗口",
    }


def _review_candles(window: pd.DataFrame, *, include_symbol: bool = False) -> list[dict[str, Any]]:
    if window.empty:
        return []
    columns = ["date", "open", "high", "low", "close", "volume", "amount"]
    if include_symbol:
        columns.insert(1, "stock_code")
    present = [column for column in columns if column in window.columns]
    return _records(window[present], limit=None)
