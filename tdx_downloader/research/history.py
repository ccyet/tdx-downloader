from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tdx_downloader.data.schema import inclusive_end_timestamp, normalize_symbol
from tdx_downloader.research.features import FEATURE_COLUMNS, window_features
from tdx_downloader.research.scoring import fast_window_feature_arrays, prepare_research_bars
from tdx_downloader.research.similarity_algorithms import (
    BASELINE_ALGORITHM,
    build_algorithm_target,
    distance_for_close_matrix,
    ensure_algorithm_available,
)

EXPLICIT_WINDOW_MAX_END_GAP_DAYS = 10


@dataclass(frozen=True)
class HistorySearchConfig:
    symbol: str
    as_of: str | pd.Timestamp
    window_size: int
    forward_windows: tuple[int, ...] = (5, 20, 60)
    candidate_n: int = 100
    top_n: int = 10
    exclusion_bars: int = 20
    nearby_gap_days: int = 20
    path_weight: float = 0.7
    window_start: str | pd.Timestamp | None = None
    algorithm: str = BASELINE_ALGORITHM


@dataclass(frozen=True)
class HistorySearchResult:
    symbol: str
    as_of: pd.Timestamp
    window_size: int
    current_window: pd.DataFrame
    historical_windows: list[pd.DataFrame]
    historical_chart_windows: list[pd.DataFrame]
    results: pd.DataFrame


def search_history(bars: pd.DataFrame, config: HistorySearchConfig) -> HistorySearchResult:
    if config.window_start is None and config.window_size < 2:
        raise ValueError("window_size 至少需要 2。")
    if config.candidate_n < 1:
        raise ValueError("candidate_n 至少需要 1。")
    if config.top_n < 1:
        raise ValueError("top_n 至少需要 1。")
    if config.exclusion_bars < 0:
        raise ValueError("exclusion_bars 不能为负数。")
    if config.nearby_gap_days < 0:
        raise ValueError("nearby_gap_days 不能为负数。")
    if not 0 <= config.path_weight <= 1:
        raise ValueError("path_weight 必须在 0 到 1 之间。")
    if any(window <= 0 for window in config.forward_windows):
        raise ValueError("forward_windows 必须为正整数。")

    algorithm = ensure_algorithm_available(config.algorithm, mode="history")
    symbol = normalize_symbol(config.symbol)
    prepared = prepare_research_bars(bars)
    prepared = prepared.loc[prepared["stock_code"].map(normalize_symbol) == symbol].sort_values("date").reset_index(drop=True)
    if prepared.empty:
        raise ValueError(f"未找到 {symbol} 的本地行情。")

    as_of = inclusive_end_timestamp(config.as_of)
    available = prepared.loc[prepared["date"] <= as_of].copy()
    if available.empty:
        raise ValueError("as-of 之前没有本地行情。")

    current_window, current_start, as_of_index, window_size = _current_window(prepared, available, config)
    max_forward = max(config.forward_windows) if config.forward_windows else 0
    starts = _candidate_starts(
        as_of_index=as_of_index,
        current_start=current_start,
        window_size=window_size,
        max_forward=max_forward,
        exclusion_bars=config.exclusion_bars,
    )
    frame = _candidate_frame(
        prepared=prepared,
        symbol=symbol,
        starts=starts,
        window_size=window_size,
        current_window=current_window,
        forward_windows=config.forward_windows,
        algorithm=algorithm,
    )
    if not frame.empty:
        frame = _score_results(frame, window_features(current_window), path_weight=config.path_weight)
        frame = frame.sort_values(["综合相似度", "路径相似度"], ascending=False).head(config.candidate_n)
        frame = _filter_nearby_history_windows(frame, top_n=config.top_n, min_gap_days=config.nearby_gap_days).reset_index(
            drop=True
        )
    selected = pd.to_numeric(frame.get("_candidate_index", pd.Series(dtype=int)), errors="coerce").dropna().astype(int).tolist()
    windows = [
        prepared.iloc[starts[index] : starts[index] + window_size].reset_index(drop=True)
        for index in selected
        if 0 <= index < len(starts)
    ]
    chart_windows = [
        prepared.iloc[starts[index] : starts[index] + window_size + max_forward].reset_index(drop=True)
        for index in selected
        if 0 <= index < len(starts)
    ]
    frame = frame.drop(columns=["_candidate_index"], errors="ignore")
    return HistorySearchResult(
        symbol=symbol,
        as_of=as_of,
        window_size=window_size,
        current_window=current_window,
        historical_windows=windows,
        historical_chart_windows=chart_windows,
        results=frame.reset_index(drop=True),
    )


def explicit_window_end_coverage_error(window: pd.DataFrame, as_of: str | pd.Timestamp) -> str:
    if window.empty or "date" not in window.columns:
        return ""
    requested_end = pd.Timestamp(as_of).normalize()
    actual_end = pd.Timestamp(window["date"].max()).normalize()
    gap_days = int((requested_end - actual_end).days)
    if gap_days <= EXPLICIT_WINDOW_MAX_END_GAP_DAYS:
        return ""
    return (
        "本地行情未覆盖选定窗口结束："
        f"请求结束 {requested_end.strftime('%Y-%m-%d')}，"
        f"实际最后一根 K 线 {actual_end.strftime('%Y-%m-%d')}，"
        f"相差 {gap_days} 天。请先下载或更新数据。"
    )


def _current_window(
    prepared: pd.DataFrame,
    available: pd.DataFrame,
    config: HistorySearchConfig,
) -> tuple[pd.DataFrame, int, int, int]:
    if config.window_start is None:
        if len(available) < config.window_size:
            raise ValueError("as-of 之前数据不足，无法形成当前窗口。")
        as_of_index = int(available.index[-1])
        current_start = as_of_index - config.window_size + 1
        return prepared.iloc[current_start : as_of_index + 1].reset_index(drop=True), current_start, as_of_index, config.window_size

    start = pd.Timestamp(config.window_start)
    as_of = inclusive_end_timestamp(config.as_of)
    selected = prepared.loc[prepared["date"].between(start, as_of)]
    if len(selected) < 2:
        raise ValueError("选定区间内 K 线数量不足，至少需要 2 根。")
    if error := explicit_window_end_coverage_error(selected, config.as_of):
        raise ValueError(error)
    return selected.reset_index(drop=True), int(selected.index[0]), int(selected.index[-1]), int(len(selected))


def _candidate_starts(
    *,
    as_of_index: int,
    current_start: int,
    window_size: int,
    max_forward: int,
    exclusion_bars: int,
) -> np.ndarray:
    latest_end = current_start - exclusion_bars - 1
    latest_start = min(latest_end - window_size + 1, as_of_index - max_forward - window_size + 1)
    if latest_start < 0:
        return np.array([], dtype=int)
    return np.arange(latest_start + 1, dtype=int)


def _candidate_frame(
    *,
    prepared: pd.DataFrame,
    symbol: str,
    starts: np.ndarray,
    window_size: int,
    current_window: pd.DataFrame,
    forward_windows: tuple[int, ...],
    algorithm: str,
) -> pd.DataFrame:
    if len(starts) == 0:
        return pd.DataFrame()
    close = pd.to_numeric(prepared["close"], errors="coerce").to_numpy(dtype=float)
    amount = pd.to_numeric(prepared["amount"], errors="coerce").to_numpy(dtype=float)
    volume = pd.to_numeric(prepared["volume"], errors="coerce").to_numpy(dtype=float)
    liquidity = np.where(np.isfinite(amount), amount, volume)
    close_windows = np.lib.stride_tricks.sliding_window_view(close, window_size)[starts]
    distance_parts = distance_for_close_matrix(close_windows, build_algorithm_target(current_window, algorithm))
    features = fast_window_feature_arrays(close, liquidity, starts, window_size)
    target_features = window_features(current_window)
    ends = starts + window_size - 1
    frame = pd.DataFrame(
        {
            "_candidate_index": np.arange(len(starts)),
            "算法": algorithm,
            "symbol": symbol,
            "窗口开始": prepared["date"].iloc[starts].to_numpy(),
            "窗口结束": prepared["date"].iloc[ends].to_numpy(),
            "K线数量": window_size,
            "路径距离": distance_parts["路径距离"],
            "价格路径距离": distance_parts["价格路径距离"],
            "收益路径距离": distance_parts["收益路径距离"],
        }
    )
    for column in FEATURE_COLUMNS:
        frame[column] = features[column]
        frame[f"feature_diff::{column}"] = np.abs(features[column] - target_features[column])
    for horizon, values in _forward_returns(close, starts, window_size, forward_windows).items():
        frame[f"t_plus_{horizon}_return"] = values
        frame[f"后{horizon}根收益"] = values
    return frame


def _forward_returns(
    close: np.ndarray,
    starts: np.ndarray,
    window_size: int,
    forward_windows: tuple[int, ...],
) -> dict[int, np.ndarray]:
    ends = starts + window_size - 1
    base_close = close[ends]
    outcomes: dict[int, np.ndarray] = {}
    for horizon in forward_windows:
        returns = np.full(len(starts), np.nan, dtype=float)
        future_positions = ends + int(horizon)
        valid = (future_positions < len(close)) & (base_close != 0) & np.isfinite(base_close)
        returns[valid] = close[future_positions[valid]] / base_close[valid] - 1.0
        outcomes[int(horizon)] = returns
    return outcomes


def _score_results(frame: pd.DataFrame, target_features: dict[str, float], *, path_weight: float) -> pd.DataFrame:
    scored = frame.copy()
    diff_columns = []
    for column in FEATURE_COLUMNS:
        diff_column = f"feature_diff::{column}"
        if diff_column not in scored.columns:
            scored[diff_column] = np.abs(pd.to_numeric(scored[column], errors="coerce").fillna(0.0) - target_features[column])
        diff_columns.append(diff_column)
    scaled_diffs = []
    for column in diff_columns:
        values = pd.to_numeric(scored[column], errors="coerce").fillna(0.0)
        scale = float(values.median())
        if not np.isfinite(scale) or scale == 0:
            scale = float(values.mean())
        if not np.isfinite(scale) or scale == 0:
            scale = 1.0
        scaled_diffs.append(values / scale)
    scored["特征距离"] = pd.concat(scaled_diffs, axis=1).mean(axis=1).astype(float)
    scored["路径相似度"] = np.exp(-pd.to_numeric(scored["路径距离"], errors="coerce").fillna(0.0))
    scored["特征相似度"] = np.exp(-pd.to_numeric(scored["特征距离"], errors="coerce").fillna(0.0))
    scored["综合相似度"] = (
        scored["路径相似度"].astype(float) * path_weight
        + scored["特征相似度"].astype(float) * (1.0 - path_weight)
    )
    return scored.drop(columns=diff_columns, errors="ignore")


def _filter_nearby_history_windows(
    frame: pd.DataFrame,
    *,
    top_n: int,
    min_gap_days: int,
) -> pd.DataFrame:
    selected: list[pd.Series] = []
    for _, row in frame.iterrows():
        start = pd.Timestamp(row["窗口开始"])
        end = pd.Timestamp(row["窗口结束"])
        if any(
            _window_gap_days(
                start,
                end,
                pd.Timestamp(item["窗口开始"]),
                pd.Timestamp(item["窗口结束"]),
            )
            < min_gap_days
            for item in selected
        ):
            continue
        selected.append(row)
        if len(selected) >= top_n:
            break
    return pd.DataFrame(selected) if selected else frame.iloc[:0]


def _window_gap_days(
    left_start: pd.Timestamp,
    left_end: pd.Timestamp,
    right_start: pd.Timestamp,
    right_end: pd.Timestamp,
) -> int:
    if left_start <= right_end and right_start <= left_end:
        return 0
    if left_end < right_start:
        return int((right_start - left_end).days)
    return int((left_start - right_end).days)
