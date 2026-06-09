from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
import pandas as pd

from tdx_downloader.data.manager import DataManagementService, normalize_symbol_tuple, normalize_timeframes
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.research.review import (
    ReviewConfig,
    analyze_price_review,
    build_comparison_stats,
    rank_review_results,
    render_multi_review_text,
    render_multi_video_script_text,
)
from tdx_downloader.research.review_ai import build_multi_review_ai_evidence, build_review_ai_messages

from ..schemas import ReviewSearchPayload
from ..serialization import _json_dict, _records


def register_research_review_routes(app: FastAPI) -> None:
    @app.post("/api/research/review")
    def research_review(payload: ReviewSearchPayload) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframes([payload.timeframe])[0]
            symbols = normalize_symbol_tuple(payload.symbols)
            if not symbols:
                raise ValueError("多股复盘至少需要 1 个标的代码。")
            benchmark_symbols = normalize_symbol_tuple([payload.benchmark_symbol]) if payload.benchmark_symbol else ()
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=[*symbols, *benchmark_symbols],
                start=payload.start,
                end=payload.end,
            )
            results = [
                analyze_price_review(
                    bars,
                    ReviewConfig(
                        symbol=symbol,
                        start=payload.start,
                        end=payload.end,
                        min_swing_return=payload.min_swing_return,
                        min_segment_bars=payload.min_segment_bars,
                        max_segments=payload.max_segments,
                    ),
                )
                for symbol in symbols
            ]
            comparisons = _review_comparisons(results, bars, benchmark_symbols[0] if benchmark_symbols else "")
            stock_names = _review_stock_names(payload, symbols)
            ranking = rank_review_results(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            warnings = [warning for result in results for warning in result.warnings]
            evidence = build_multi_review_ai_evidence(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
                warnings=warnings,
            )
            messages = build_review_ai_messages(evidence)
            review_text = render_multi_review_text(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            video_script_text = render_multi_video_script_text(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": {
                "timeframe": timeframe,
                "start": payload.start,
                "end": payload.end,
                "symbol_count": len(symbols),
                "ranked_count": len(ranking),
            },
            "ranking": _records(ranking),
            "comparisons": _records(comparisons),
            "reviews": [
                {
                    "symbol": result.symbol,
                    "start": result.start,
                    "end": result.end,
                    "overview": _json_dict(result.overview),
                    "warnings": list(result.warnings),
                    "main_segments": _records(result.main_segments),
                    "candles": _review_candles(result.window),
                }
                for result in results
            ],
            "ai": {
                "evidence": _json_dict(evidence),
                "messages": [_json_dict(message) for message in messages],
            },
            "text": {
                "review": review_text,
                "video_script": video_script_text,
            },
        }


def _review_comparisons(results: list[Any], bars: pd.DataFrame, benchmark_symbol: str) -> pd.DataFrame:
    if not benchmark_symbol:
        return pd.DataFrame()
    benchmark = bars.loc[bars["stock_code"] == benchmark_symbol].copy()
    rows: list[dict[str, object]] = []
    for result in results:
        if result.window.empty:
            continue
        rows.append({"代码": result.symbol, **build_comparison_stats(result.window, benchmark, benchmark_symbol)})
    return pd.DataFrame(rows)


def _review_stock_names(payload: ReviewSearchPayload, symbols: tuple[str, ...]) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    resolved = service.repository.symbol_names(symbols=symbols)
    explicit = {
        normalize_symbol_tuple([symbol])[0]: str(name).strip()
        for symbol, name in payload.stock_names.items()
        if str(name).strip()
    }
    return {**resolved, **explicit}


def _review_candles(window: pd.DataFrame, *, include_symbol: bool = False) -> list[dict[str, Any]]:
    if window.empty:
        return []
    columns = ["date", "open", "high", "low", "close", "volume", "amount"]
    if include_symbol:
        columns.insert(1, "stock_code")
    present = [column for column in columns if column in window.columns]
    return _records(window[present], limit=None)
