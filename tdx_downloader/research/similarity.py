from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from tdx_downloader.data.schema import inclusive_end_timestamp, normalize_symbol, unique_symbols
from tdx_downloader.research.scoring import (
    fast_window_feature_arrays,
    feature_dict,
    path_distance,
    path_distance_matrix,
    prepare_research_bars,
    score_frame,
)

FORWARD_RETURN_WINDOWS = (3, 5, 10)


@dataclass(frozen=True)
class CrossSectionSearchConfig:
    target_symbol: str
    universe_symbols: tuple[str, ...]
    start: str | pd.Timestamp
    end: str | pd.Timestamp
    top_n: int = 20
    min_coverage: float = 0.8
    path_weight: float = 0.7
    forward_windows: tuple[int, ...] = FORWARD_RETURN_WINDOWS
    date_tolerance_bars: int = 0


@dataclass(frozen=True)
class CrossSectionSearchResult:
    target_symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    window_size: int
    results: pd.DataFrame
    skipped: pd.DataFrame


@dataclass(frozen=True)
class CrossSectionWindowTraversalConfig:
    target_symbol: str
    universe_symbols: tuple[str, ...]
    target_start: str | pd.Timestamp
    target_end: str | pd.Timestamp
    traversal_start: str | pd.Timestamp
    traversal_end: str | pd.Timestamp
    top_n: int = 100
    min_coverage: float = 1.0
    path_weight: float = 0.7
    exclusion_bars: int = 0
    forward_windows: tuple[int, ...] = FORWARD_RETURN_WINDOWS


@dataclass(frozen=True)
class CrossSectionWindowTraversalResult:
    target_symbol: str
    target_start: pd.Timestamp
    target_end: pd.Timestamp
    traversal_start: pd.Timestamp
    traversal_end: pd.Timestamp
    window_size: int
    results: pd.DataFrame
    skipped: pd.DataFrame


def search_cross_section(bars: pd.DataFrame, config: CrossSectionSearchConfig) -> CrossSectionSearchResult:
    if config.top_n < 1:
        raise ValueError("top_n 至少需要 1。")
    if not 0 < config.min_coverage <= 1:
        raise ValueError("min_coverage 必须在 0 到 1 之间。")
    if not 0 <= config.path_weight <= 1:
        raise ValueError("path_weight 必须在 0 到 1 之间。")
    if config.date_tolerance_bars < 0:
        raise ValueError("date_tolerance_bars 不能为负数。")
    prepared = prepare_research_bars(bars)
    target_symbol = normalize_symbol(config.target_symbol)
    start = pd.Timestamp(config.start)
    end = inclusive_end_timestamp(config.end)
    bars_by_symbol = {symbol: frame.sort_values("date").reset_index(drop=True) for symbol, frame in prepared.groupby("stock_code")}
    target_bars = bars_by_symbol.get(target_symbol)
    if target_bars is None:
        raise ValueError(f"目标标的 {target_symbol} 没有本地行情。")
    target_window = target_bars.loc[target_bars["date"].between(start, end)].reset_index(drop=True)
    if target_window.empty:
        raise ValueError(f"目标标的 {target_symbol} 在所选区间没有行情数据。")
    target_length = len(target_window)
    minimum_rows = max(2, math.ceil(target_length * config.min_coverage))
    target_features = feature_dict(target_window)
    rows: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for symbol in unique_symbols(list(config.universe_symbols)):
        if symbol == target_symbol:
            continue
        symbol_bars = bars_by_symbol.get(symbol)
        if symbol_bars is None or symbol_bars.empty:
            skipped.append({"symbol": symbol, "原因": "没有本地行情"})
            continue
        candidate, offset, distance = _best_candidate_window(symbol_bars, start, end, target_window, config.date_tolerance_bars)
        if candidate is None or len(candidate) < minimum_rows:
            skipped.append({"symbol": symbol, "原因": f"区间数据不足：{0 if candidate is None else len(candidate)} / {target_length}"})
            continue
        features = feature_dict(candidate)
        row: dict[str, object] = {
            "symbol": symbol,
            "区间开始": candidate["date"].min(),
            "区间结束": candidate["date"].max(),
            "K线数量": int(len(candidate)),
            "日期偏移": int(offset),
            "覆盖率": float(len(candidate) / target_length),
            "路径距离": float(distance),
        }
        row.update(features)
        row.update(_forward_returns(symbol_bars, candidate["date"].max(), config.forward_windows))
        rows.append(row)
    result_frame = pd.DataFrame(rows)
    if not result_frame.empty:
        result_frame = score_frame(result_frame, target_features, path_weight=config.path_weight)
        result_frame = result_frame.sort_values(["综合相似度", "路径相似度"], ascending=False).head(config.top_n).reset_index(drop=True)
    return CrossSectionSearchResult(
        target_symbol=target_symbol,
        start=start,
        end=end,
        window_size=target_length,
        results=result_frame,
        skipped=pd.DataFrame(skipped, columns=["symbol", "原因"]),
    )


def search_cross_section_window_traversal(
    bars: pd.DataFrame,
    config: CrossSectionWindowTraversalConfig,
) -> CrossSectionWindowTraversalResult:
    if config.top_n < 1:
        raise ValueError("top_n 至少需要 1。")
    if not 0 < config.min_coverage <= 1:
        raise ValueError("min_coverage 必须在 0 到 1 之间。")
    if not 0 <= config.path_weight <= 1:
        raise ValueError("path_weight 必须在 0 到 1 之间。")
    if config.exclusion_bars < 0:
        raise ValueError("exclusion_bars 不能为负数。")
    if any(window <= 0 for window in config.forward_windows):
        raise ValueError("forward_windows 必须为正整数。")
    prepared = prepare_research_bars(bars)
    target_symbol = normalize_symbol(config.target_symbol)
    target_start = pd.Timestamp(config.target_start)
    target_end = inclusive_end_timestamp(config.target_end)
    traversal_start = pd.Timestamp(config.traversal_start)
    traversal_end = inclusive_end_timestamp(config.traversal_end)
    if target_start > target_end:
        raise ValueError("目标区间开始不能晚于结束。")
    if traversal_start > traversal_end:
        raise ValueError("搜索区间开始不能晚于结束。")

    bars_by_symbol = {symbol: frame.sort_values("date").reset_index(drop=True) for symbol, frame in prepared.groupby("stock_code")}
    target_bars = bars_by_symbol.get(target_symbol)
    if target_bars is None or target_bars.empty:
        raise ValueError(f"目标标的 {target_symbol} 没有本地行情。")
    target_window = target_bars.loc[target_bars["date"].between(target_start, target_end)].reset_index(drop=True)
    if target_window.empty:
        raise ValueError(f"目标标的 {target_symbol} 在所选区间没有行情数据。")

    target_length = len(target_window)
    minimum_rows = max(2, math.ceil(target_length * config.min_coverage))
    if target_length < minimum_rows:
        raise ValueError(f"目标窗口 K 线不足：{target_length} / {minimum_rows}。")
    target_features = feature_dict(target_window)

    frames: list[pd.DataFrame] = []
    skipped: list[dict[str, str]] = []
    for symbol in unique_symbols(list(config.universe_symbols)):
        symbol_bars = bars_by_symbol.get(symbol)
        if symbol_bars is None or symbol_bars.empty:
            skipped.append({"symbol": symbol, "原因": "没有本地行情"})
            continue
        symbol_frame = _traversal_candidate_frame(
            symbol_bars,
            symbol=symbol,
            traversal_start=traversal_start,
            traversal_end=traversal_end,
            target_window=target_window,
            target_features=target_features,
            forward_windows=config.forward_windows,
        )
        if symbol_frame.empty:
            skipped.append({"symbol": symbol, "原因": f"搜索区间内没有足够 {target_length} 根K线的候选窗口"})
            continue
        frames.append(symbol_frame)

    result_frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not result_frame.empty:
        result_frame = score_frame(result_frame, target_features, path_weight=config.path_weight)
        result_frame = result_frame.sort_values(["综合相似度", "路径相似度"], ascending=False)
        if config.exclusion_bars > 0:
            result_frame = _filter_nearby_traversal_windows(
                result_frame,
                top_n=config.top_n,
                exclusion_bars=config.exclusion_bars,
            )
        else:
            result_frame = result_frame.head(config.top_n)
        result_frame = result_frame.drop(columns=["_candidate_start", "_candidate_end"], errors="ignore").reset_index(drop=True)
    return CrossSectionWindowTraversalResult(
        target_symbol=target_symbol,
        target_start=target_start,
        target_end=target_end,
        traversal_start=traversal_start,
        traversal_end=traversal_end,
        window_size=target_length,
        results=result_frame,
        skipped=pd.DataFrame(skipped, columns=["symbol", "原因"]),
    )


def _traversal_candidate_frame(
    symbol_bars: pd.DataFrame,
    *,
    symbol: str,
    traversal_start: pd.Timestamp,
    traversal_end: pd.Timestamp,
    target_window: pd.DataFrame,
    target_features: dict[str, float],
    forward_windows: tuple[int, ...],
) -> pd.DataFrame:
    target_length = len(target_window)
    if len(symbol_bars) < target_length:
        return pd.DataFrame()
    dates = symbol_bars["date"].to_numpy(dtype="datetime64[ns]", copy=False)
    starts = np.flatnonzero((dates >= traversal_start.to_datetime64()) & (dates <= traversal_end.to_datetime64()))
    if len(starts) == 0:
        return pd.DataFrame()
    starts = starts[starts + target_length <= len(symbol_bars)]
    if len(starts) == 0:
        return pd.DataFrame()
    ends = starts + target_length - 1
    starts = starts[dates[ends] <= traversal_end.to_datetime64()]
    if len(starts) == 0:
        return pd.DataFrame()
    ends = starts + target_length - 1

    close = pd.to_numeric(symbol_bars["close"], errors="coerce").to_numpy(dtype=float)
    amount = pd.to_numeric(symbol_bars["amount"], errors="coerce").to_numpy(dtype=float)
    volume = pd.to_numeric(symbol_bars["volume"], errors="coerce").to_numpy(dtype=float)
    liquidity = np.where(np.isfinite(amount), amount, volume)
    close_windows = np.lib.stride_tricks.sliding_window_view(close, target_length)[starts]
    distances = path_distance_matrix(close_windows, target_window)
    features = fast_window_feature_arrays(close, liquidity, starts=starts, window_size=target_length)
    frame = pd.DataFrame(
        {
            "_candidate_start": starts.astype(int),
            "_candidate_end": ends.astype(int),
            "symbol": symbol,
            "区间开始": symbol_bars["date"].iloc[starts].to_numpy(),
            "区间结束": symbol_bars["date"].iloc[ends].to_numpy(),
            "K线数量": target_length,
            "遍历偏移": (starts - int(starts[0])).astype(int),
            "覆盖率": 1.0,
            "路径距离": distances,
        }
    )
    for column in target_features:
        if column in features:
            frame[column] = features[column]
    for column, values in _forward_return_arrays(close, starts, target_length, forward_windows).items():
        frame[column] = values
    return frame


def _filter_nearby_traversal_windows(
    frame: pd.DataFrame,
    *,
    top_n: int,
    exclusion_bars: int,
) -> pd.DataFrame:
    selected: list[pd.Series] = []
    selected_windows_by_symbol: dict[str, list[tuple[int, int]]] = {}
    for _, row in frame.iterrows():
        symbol = normalize_symbol(row["symbol"])
        start = int(row["_candidate_start"])
        end = int(row["_candidate_end"])
        windows = selected_windows_by_symbol.setdefault(symbol, [])
        if any(_window_gap_bars(start, end, selected_start, selected_end) < exclusion_bars for selected_start, selected_end in windows):
            continue
        selected.append(row)
        windows.append((start, end))
        if len(selected) >= top_n:
            break
    return pd.DataFrame(selected) if selected else frame.iloc[:0]


def _window_gap_bars(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    if left_start <= right_end and right_start <= left_end:
        return 0
    if left_end < right_start:
        return int(right_start - left_end - 1)
    return int(left_start - right_end - 1)


def _best_candidate_window(
    symbol_bars: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    target_window: pd.DataFrame,
    tolerance: int,
) -> tuple[pd.DataFrame | None, int, float]:
    direct = symbol_bars.loc[symbol_bars["date"].between(start, end)].reset_index(drop=True)
    if tolerance <= 0 or len(symbol_bars) < len(target_window):
        return direct, 0, path_distance(direct, target_window) if len(direct) else float("inf")
    dates = symbol_bars["date"].to_numpy(dtype="datetime64[ns]", copy=False)
    start_positions = np.flatnonzero(dates >= start.to_datetime64())
    if len(start_positions) == 0:
        return direct, 0, path_distance(direct, target_window) if len(direct) else float("inf")
    center = int(start_positions[0])
    lower = max(0, center - tolerance)
    upper = min(len(symbol_bars) - len(target_window), center + tolerance)
    if upper < lower:
        return direct, 0, path_distance(direct, target_window) if len(direct) else float("inf")
    starts = np.arange(lower, upper + 1, dtype=int)
    close = pd.to_numeric(symbol_bars["close"], errors="coerce").to_numpy(dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(close, len(target_window))[starts]
    distances = path_distance_matrix(windows, target_window)
    best_index = int(np.nanargmin(distances))
    best_start = int(starts[best_index])
    best = symbol_bars.iloc[best_start : best_start + len(target_window)].reset_index(drop=True)
    return best, best_start - center, float(distances[best_index])


def _forward_returns(symbol_bars: pd.DataFrame, end_date: pd.Timestamp, windows: tuple[int, ...]) -> dict[str, float]:
    ordered = symbol_bars.sort_values("date").reset_index(drop=True)
    positions = ordered.index[ordered["date"] <= end_date].tolist()
    if not positions:
        return {f"后{window}根收益": float("nan") for window in windows}
    end_position = int(positions[-1])
    close = pd.to_numeric(ordered["close"], errors="coerce").to_numpy(dtype=float)
    out: dict[str, float] = {}
    for window in windows:
        future = end_position + int(window)
        out[f"后{window}根收益"] = float(close[future] / close[end_position] - 1.0) if future < len(close) else float("nan")
    return out


def _forward_return_arrays(close: np.ndarray, starts: np.ndarray, window_size: int, windows: tuple[int, ...]) -> dict[str, np.ndarray]:
    outcomes: dict[str, np.ndarray] = {}
    ends = starts + window_size - 1
    base_close = close[ends]
    for window in windows:
        values = np.full(len(starts), np.nan, dtype=float)
        valid = (ends + int(window) < len(close)) & (base_close != 0) & np.isfinite(base_close)
        if valid.any():
            values[valid] = close[ends[valid] + int(window)] / base_close[valid] - 1.0
        outcomes[f"后{window}根收益"] = values
    return outcomes
