from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
import pandas as pd

from tdx_downloader.data.manager import normalize_symbol_tuple, normalize_timeframes, shortcut_symbol_groups
from tdx_downloader.data.parallels_runtime import shortcut_symbol_groups_with_runtime, symbol_metadata_with_runtime
from tdx_downloader.data.storage import load_daily_bars
from tdx_downloader.research.market_regime import MarketRegimeConfig, run_market_regime_research

from ..schemas import MarketRegimePayload
from ..serialization import _json_value


MARKET_REGIME_FEATURE_LOOKBACK_DAYS = 420
MARKET_REGIME_FORWARD_PADDING_DAYS = 35


def register_research_market_regime_routes(app: FastAPI) -> None:
    @app.post("/api/research/market-regime")
    def research_market_regime(payload: MarketRegimePayload) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframes([payload.timeframe])[0]
            if timeframe != "1d":
                raise ValueError("市场风险偏好研究第一版仅支持日线 1d。")
            benchmark_symbols = normalize_symbol_tuple([payload.benchmark_symbol])
            if not benchmark_symbols:
                raise ValueError("市场风险偏好研究需要基准指数代码。")
            benchmark_symbol = benchmark_symbols[0]
            symbols = _market_regime_symbols(payload)
            if not symbols:
                raise ValueError("市场风险偏好研究至少需要 1 个研究标的。")
            forward_windows = _market_regime_forward_windows(payload.forward_windows)
            bars = load_daily_bars(
                data_root=payload.data_root,
                adjust=payload.adjust,
                symbols=normalize_symbol_tuple([benchmark_symbol, *symbols]),
                start=_market_regime_read_start(payload.start),
                end=_market_regime_read_end(payload.end, forward_windows),
            )
            result = run_market_regime_research(
                bars,
                MarketRegimeConfig(
                    benchmark_symbol=benchmark_symbol,
                    symbols=symbols,
                    start=payload.start,
                    end=payload.end,
                    forward_windows=forward_windows,
                    benchmark_rally_60_threshold=payload.benchmark_rally_60_threshold,
                    benchmark_pullback_20_threshold=payload.benchmark_pullback_20_threshold,
                    pullback_20_threshold=payload.pullback_20_threshold,
                    pullback_60_threshold=payload.pullback_60_threshold,
                    liquidity_high_percentile=payload.liquidity_high_percentile,
                    liquidity_mid_percentile=payload.liquidity_mid_percentile,
                    liquidity_low_percentile=payload.liquidity_low_percentile,
                    volatility_high_percentile=payload.volatility_high_percentile,
                    volatility_low_percentile=payload.volatility_low_percentile,
                    high_position_drawdown_threshold=payload.high_position_drawdown_threshold,
                    high_position_return_percentile=payload.high_position_return_percentile,
                    leader_return_5d_threshold=payload.leader_return_5d_threshold,
                    stress_ma20_break_threshold=payload.stress_ma20_break_threshold,
                    stress_return_5d_threshold=payload.stress_return_5d_threshold,
                    cash_stress_score_threshold=payload.cash_stress_score_threshold,
                    cash_preference_proxy_threshold=payload.cash_preference_proxy_threshold,
                    risk_expansion_breadth_threshold=payload.risk_expansion_breadth_threshold,
                    risk_contraction_breadth_threshold=payload.risk_contraction_breadth_threshold,
                    risk_release_breadth_threshold=payload.risk_release_breadth_threshold,
                    high_liquidity_selloff_threshold=payload.high_liquidity_selloff_threshold,
                    concentration_top_n=payload.concentration_top_n,
                    daily_report_days=payload.daily_report_days,
                    flow_candidate_limit=payload.flow_candidate_limit,
                    risk_timeline_days=payload.risk_timeline_days,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = result.get("summary")
        if isinstance(summary, dict):
            summary["timeframe"] = timeframe
        return _json_value(result)


def _market_regime_symbols(payload: MarketRegimePayload) -> tuple[str, ...]:
    explicit = list(normalize_symbol_tuple(payload.symbols))
    requested_groups = [str(group).strip() for group in payload.universe_groups if str(group).strip()]
    if not requested_groups:
        return tuple(explicit)
    group_symbols = _market_regime_group_symbols(
        data_root=payload.data_root,
        tdx_path=payload.tdx_path,
        groups=requested_groups,
    )
    return normalize_symbol_tuple([*explicit, *group_symbols])


def _market_regime_group_symbols(*, data_root: str, tdx_path: str, groups: list[str]) -> list[str]:
    try:
        metadata = symbol_metadata_with_runtime(data_root, tdx_path)
        available_groups = shortcut_symbol_groups(
            metadata=metadata,
            include_catalog_universe=not _has_non_catalog_symbol_metadata(metadata),
        )
        if _missing_requested_groups(available_groups, groups):
            runtime_groups: list[dict[str, object]] = []
            targets = _runtime_targets(groups)
            if targets:
                for target in targets:
                    runtime_groups.extend(shortcut_symbol_groups_with_runtime(data_root, tdx_path, target=target))
            else:
                runtime_groups = shortcut_symbol_groups_with_runtime(data_root, tdx_path)
            available_groups = _merge_shortcut_groups(available_groups, runtime_groups)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    symbols: list[str] = []
    for group in available_groups:
        name = str(group.get("name", "")).strip()
        if name in groups:
            symbols.extend(group.get("symbols", []) or [])
    return symbols


def _has_non_catalog_symbol_metadata(metadata: pd.DataFrame) -> bool:
    if metadata.empty or "source" not in metadata.columns:
        return bool(len(metadata))
    sources = metadata["source"].fillna("").astype(str).str.strip().str.lower()
    return bool((sources.ne("") & sources.ne("catalog")).any())


def _missing_requested_groups(available_groups: list[dict[str, object]], requested_groups: list[str]) -> bool:
    group_by_name = {str(group.get("name", "")).strip(): group for group in available_groups}
    return any(not group_by_name.get(name, {}).get("symbols") for name in requested_groups)


def _runtime_targets(groups: list[str]) -> list[str]:
    targets: list[str] = []
    if "ETF列表" in groups:
        targets.append("etf")
    if "板块指数" in groups:
        targets.append("index")
    return targets


def _merge_shortcut_groups(*group_sets: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for group_set in group_sets:
        for group in group_set:
            name = str(group.get("name", "")).strip()
            if not name:
                continue
            existing = merged.get(name, {"name": name, "symbols": []})
            symbols = normalize_symbol_tuple([*(existing.get("symbols", []) or []), *(group.get("symbols", []) or [])])
            existing["symbols"] = list(symbols)
            merged[name] = existing
    return list(merged.values())


def _market_regime_forward_windows(values: list[int]) -> tuple[int, ...]:
    windows = tuple(sorted({int(value) for value in values if int(value) > 0}))
    if not windows:
        raise ValueError("市场风险偏好研究至少需要 1 个前瞻窗口。")
    return windows


def _market_regime_read_start(start: str) -> str:
    return (pd.Timestamp(start) - pd.Timedelta(days=MARKET_REGIME_FEATURE_LOOKBACK_DAYS)).date().isoformat()


def _market_regime_read_end(end: str, forward_windows: tuple[int, ...]) -> str:
    max_forward = max(forward_windows) if forward_windows else 0
    padding_days = max(MARKET_REGIME_FORWARD_PADDING_DAYS, int(max_forward) * 5 + 7)
    return (pd.Timestamp(end) + pd.Timedelta(days=padding_days)).date().isoformat()
