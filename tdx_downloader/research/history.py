from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tdx_downloader.data.schema import inclusive_end_timestamp, normalize_symbol
from tdx_downloader.research.scoring import (
    fast_window_feature_arrays,
    feature_dict,
    path_distance_matrix,
    prepare_research_bars,
    score_frame,
)


@dataclass(frozen=True)
class HistorySearchConfig:
    symbol: str
    as_of: str | pd.Timestamp
    window_size: int
    forward_windows: tuple[int, ...] = (5, 20, 60)
    top_n: int = 10
    exclusion_bars: int = 20
    path_weight: float = 0.7
    window_start: str | pd.Timestamp | None = None


@dataclass(frozen=True)
class HistorySearchResult:
    symbol: str
    as_of: pd.Timestamp
    window_size: int
    current_window: pd.DataFrame
    historical_windows: list[pd.DataFrame]
    results: pd.DataFrame


def search_history(bars: pd.DataFrame, config: HistorySearchConfig) -> HistorySearchResult:
    if config.window_start is None and config.window_size < 2:
        raise ValueError("window_size 至少需要 2。")
    if config.top_n < 1:
        raise ValueError("top_n 至少需要 1。")
    if config.exclusion_bars < 0:
        raise ValueError("exclusion_bars 不能为负数。")
    if not 0 <= config.path_weight <= 1:
        raise ValueError("path_weight 必须在 0 到 1 之间。")
    if any(window <= 0 for window in config.forward_windows):
        raise ValueError("forward_windows 必须为正整数。")

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
    )
    if not frame.empty:
        frame = score_frame(frame, feature_dict(current_window), path_weight=config.path_weight)
        frame = frame.sort_values(["综合相似度", "路径相似度"], ascending=False).head(config.top_n).reset_index(drop=True)
    selected = pd.to_numeric(frame.get("_candidate_index", pd.Series(dtype=int)), errors="coerce").dropna().astype(int).tolist()
    windows = [
        prepared.iloc[starts[index] : starts[index] + window_size].reset_index(drop=True)
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
        results=frame,
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
) -> pd.DataFrame:
    if len(starts) == 0:
        return pd.DataFrame()
    close = pd.to_numeric(prepared["close"], errors="coerce").to_numpy(dtype=float)
    amount = pd.to_numeric(prepared["amount"], errors="coerce").to_numpy(dtype=float)
    volume = pd.to_numeric(prepared["volume"], errors="coerce").to_numpy(dtype=float)
    liquidity = np.where(np.isfinite(amount), amount, volume)
    close_windows = np.lib.stride_tricks.sliding_window_view(close, window_size)[starts]
    ends = starts + window_size - 1
    frame = pd.DataFrame(
        {
            "_candidate_index": np.arange(len(starts)),
            "symbol": symbol,
            "窗口开始": prepared["date"].iloc[starts].to_numpy(),
            "窗口结束": prepared["date"].iloc[ends].to_numpy(),
            "K线数量": window_size,
            "路径距离": path_distance_matrix(close_windows, current_window),
        }
    )
    for column, values in fast_window_feature_arrays(close, liquidity, starts, window_size).items():
        frame[column] = values
    for horizon in forward_windows:
        frame[f"后{horizon}根收益"] = _forward_return(close, starts, window_size, horizon)
    return frame


def _forward_return(close: np.ndarray, starts: np.ndarray, window_size: int, horizon: int) -> np.ndarray:
    end_positions = starts + window_size - 1
    future_positions = end_positions + horizon
    values = np.full(len(starts), np.nan, dtype=float)
    valid = future_positions < len(close)
    values[valid] = close[future_positions[valid]] / close[end_positions[valid]] - 1.0
    return values
