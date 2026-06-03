from __future__ import annotations

import numpy as np
import pandas as pd

from tdx_downloader.research.features import FEATURE_COLUMNS, normalized_close_path, window_features, z_normalize

RECENT_KLINE_COUNT = 2
RECENT_KLINE_WEIGHT = 3.0


def prepare_research_bars(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    if "symbol" in frame.columns and "stock_code" not in frame.columns:
        frame = frame.rename(columns={"symbol": "stock_code"})
    required = {"date", "stock_code", "close"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"行情数据缺少必要字段：{', '.join(missing)}。")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low", "volume", "amount"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "stock_code", "close"])
    return frame.sort_values(["stock_code", "date"]).reset_index(drop=True)


def path_distance(left: pd.DataFrame, right: pd.DataFrame) -> float:
    left_path = z_normalize(normalized_close_path(left))
    right_path = z_normalize(normalized_close_path(right))
    if len(left_path) != len(right_path):
        length = min(len(left_path), len(right_path))
        left_path = left_path[:length]
        right_path = right_path[:length]
    if len(left_path) == 0:
        return 0.0
    diff = left_path - right_path
    weights = _recent_weights(len(diff))
    return float(np.sqrt(np.sum(weights * diff * diff) / np.sum(weights)))


def path_distance_matrix(close_windows: np.ndarray, target_window: pd.DataFrame) -> np.ndarray:
    target = z_normalize(normalized_close_path(target_window))
    paths = _z_normalize_rows(_normalized_close_windows(close_windows))
    if paths.shape[1] != len(target):
        width = min(paths.shape[1], len(target))
        paths = paths[:, :width]
        target = target[:width]
    if paths.shape[1] == 0:
        return np.zeros(paths.shape[0], dtype=float)
    diff = paths - target
    weights = _recent_weights(paths.shape[1])
    return np.sqrt(np.sum(diff * diff * weights, axis=1) / np.sum(weights))


def score_frame(frame: pd.DataFrame, target_features: dict[str, float], *, path_weight: float) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    feature_diff = np.zeros(len(result), dtype=float)
    for column in FEATURE_COLUMNS:
        feature_diff += np.abs(pd.to_numeric(result[column], errors="coerce").fillna(0).to_numpy() - target_features[column])
    result["特征距离"] = feature_diff / max(len(FEATURE_COLUMNS), 1)
    path_distance_values = pd.to_numeric(result["路径距离"], errors="coerce").fillna(0)
    feature_distance_values = pd.to_numeric(result["特征距离"], errors="coerce").fillna(0)
    result["路径相似度"] = 1.0 / (1.0 + path_distance_values)
    result["特征相似度"] = 1.0 / (1.0 + feature_distance_values)
    result["综合相似度"] = result["路径相似度"] * path_weight + result["特征相似度"] * (1.0 - path_weight)
    return result


def fast_window_feature_arrays(close: np.ndarray, liquidity: np.ndarray, starts: np.ndarray, window_size: int) -> dict[str, np.ndarray]:
    close_windows = np.lib.stride_tricks.sliding_window_view(close, window_size)[starts]
    path_matrix = _normalized_close_windows(close_windows)
    returns = np.divide(
        close[1:],
        close[:-1],
        out=np.full(len(close) - 1, np.nan, dtype=float),
        where=(close[:-1] != 0) & np.isfinite(close[:-1]),
    ) - 1.0
    return_windows = np.lib.stride_tricks.sliding_window_view(returns, max(window_size - 1, 1))[starts]
    liquidity_windows = np.lib.stride_tricks.sliding_window_view(liquidity, window_size)[starts]
    x = np.arange(window_size, dtype=float)
    x_centered = x - x.mean()
    denominator = float(np.sum(x_centered**2)) or 1.0
    slopes = ((path_matrix - path_matrix.mean(axis=1, keepdims=True)) @ x_centered) / denominator
    total_liquidity = np.nansum(liquidity_windows, axis=1)
    down_liquidity = np.nansum(liquidity_windows[:, 1:] * (return_windows < 0), axis=1)
    down_share = np.divide(down_liquidity, total_liquidity, out=np.zeros_like(total_liquidity), where=total_liquidity != 0)
    return {
        "区间收益": np.divide(close_windows[:, -1], close_windows[:, 0], out=np.ones(len(close_windows)), where=close_windows[:, 0] != 0) - 1.0,
        "波动率": np.nanstd(return_windows, axis=1),
        "最大回撤": _max_drawdown_matrix(path_matrix),
        "趋势斜率": slopes,
        "下跌放量占比": down_share,
        "量价相关": np.zeros(len(close_windows), dtype=float),
        "成交规模": np.log1p(np.nanmean(liquidity_windows, axis=1)),
    }


def _normalized_close_windows(close_windows: np.ndarray) -> np.ndarray:
    close_windows = np.asarray(close_windows, dtype=float)
    first = close_windows[:, [0]]
    return np.divide(close_windows, first, out=np.zeros_like(close_windows), where=np.isfinite(first) & (first != 0)) * 100.0


def _z_normalize_rows(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    centered = values - np.nanmean(values, axis=1, keepdims=True)
    std = np.nanstd(values, axis=1, keepdims=True)
    return np.divide(centered, std, out=centered.copy(), where=np.isfinite(std) & (std != 0))


def _max_drawdown_matrix(path_matrix: np.ndarray) -> np.ndarray:
    running_max = np.maximum.accumulate(path_matrix, axis=1)
    drawdowns = path_matrix / np.where(running_max == 0, np.nan, running_max) - 1.0
    return np.nanmin(drawdowns, axis=1)


def _recent_weights(length: int) -> np.ndarray:
    weights = np.ones(length, dtype=float)
    if length:
        weights[-min(RECENT_KLINE_COUNT, length):] = RECENT_KLINE_WEIGHT
    return weights


def feature_dict(window: pd.DataFrame) -> dict[str, float]:
    return window_features(window)
