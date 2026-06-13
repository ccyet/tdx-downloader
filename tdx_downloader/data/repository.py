from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import logging
import time
from typing import Any

import pandas as pd

from tdx_downloader.data.audit import (
    AUDIT_COLUMNS,
    DATA_GAP_EPISODE_COLUMNS,
    LIMIT_FILTER_AUDIT_COLUMNS,
    _audit_window_for_timeframe,
    audit_local_data,
    data_gap_episodes,
    daily_sessions_by_symbol,
    limit_open_dates_in_window,
    limit_open_filter_audit,
)
from tdx_downloader.data.catalog import (
    catalog_path_for,
    clear_unresolved_gaps,
    query_catalog,
    query_coverage_keys,
    query_coverage_runs,
    query_unresolved_gaps,
    refresh_coverage_runs,
    upsert_partial_coverage_runs_from_bars,
    upsert_catalog_records,
    upsert_unresolved_gaps,
)
from tdx_downloader.data.filters import filter_limit_open_days
from tdx_downloader.data.inventory import (
    INVENTORY_COLUMNS,
    available_symbols,
    inventory_local_data,
)
from tdx_downloader.data.schema import (
    SUPPORTED_TIMEFRAMES,
    canonical_data_root,
    ensure_supported_timeframe,
    normalize_symbol,
    parse_time_window,
    resolve_timeframe_root,
    unique_symbols,
)
from tdx_downloader.data.summary import (
    DATA_AUDIT_SUMMARY_KEYS,
    DATA_INVENTORY_SUMMARY_KEYS,
    LIMIT_FILTER_SUMMARY_KEYS,
    normalize_min_coverage_ratio as _normalize_min_coverage_ratio,
    summarize_data_audit,
    summarize_data_inventory,
    summarize_data_management,
    summarize_limit_filter_audit,
)
from tdx_downloader.data.storage import load_daily_bars, load_local_bars, resolve_daily_root, write_local_bars
from tdx_downloader.data.symbols import load_symbol_metadata, resolve_symbol_names

ProgressCallback = Callable[[dict[str, object]], None]
_LOGGER = logging.getLogger(__name__)

__all__ = [
    "BacktestDataBundle",
    "DATA_AUDIT_SUMMARY_KEYS",
    "DATA_GAP_EPISODE_COLUMNS",
    "DATA_INVENTORY_SUMMARY_KEYS",
    "INVENTORY_COLUMNS",
    "LIMIT_FILTER_SUMMARY_KEYS",
    "MultiTimeframeBacktestDataBundle",
    "MarketDataRepository",
    "audit_local_data",
    "available_symbols",
    "data_gap_episodes",
    "inventory_local_data",
    "load_backtest_data",
    "load_daily_bars",
    "load_local_bars",
    "load_multi_timeframe_backtest_data",
    "load_symbol_metadata",
    "plan_tdx_backtest_data",
    "prepare_tdx_backtest_data",
    "resolve_daily_root",
    "resolve_symbol_names",
    "resolve_timeframe_root",
    "summarize_data_audit",
    "summarize_data_inventory",
    "summarize_data_management",
    "summarize_limit_filter_audit",
    "update_from_tdx",
    "write_local_bars",
]

PREPARE_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "action",
    "before_status",
    "after_status",
    "rows_written",
    "new_rows",
    "before_coverage_ratio",
    "after_coverage_ratio",
    "coverage_ratio",
    "before_missing_rows",
    "after_missing_rows",
    "missing_rows",
    "before_max_missing_gap_minutes",
    "after_max_missing_gap_minutes",
    "before_first_missing_at",
    "before_last_missing_at",
    "after_first_missing_at",
    "after_last_missing_at",
    "first_missing_at",
    "last_missing_at",
    "before_max_missing_gap_start_at",
    "before_max_missing_gap_end_at",
    "after_max_missing_gap_start_at",
    "after_max_missing_gap_end_at",
    "max_missing_gap_start_at",
    "max_missing_gap_end_at",
    "path",
    "message",
]

PLAN_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "action",
    "reason",
    "catalog_status",
    "coverage_status",
    "before_status",
    "rows_in_window",
    "expected_rows",
    "missing_rows",
    "coverage_ratio",
    "max_missing_gap_minutes",
    "first_missing_at",
    "last_missing_at",
    "max_missing_gap_start_at",
    "max_missing_gap_end_at",
    "path",
    "message",
]

UNLOADABLE_AUDIT_STATUSES = frozenset({"read_error", "missing_columns"})
DAILY_DEPENDENCY_FAILURE_STATUSES = frozenset({"read_error", "missing_columns", "quality_error"})
TDX_BOUNDARY_GAP_TOLERANCE = pd.Timedelta(days=7)
PLAN_PARALLEL_SYMBOL_THRESHOLD = 500
PLAN_PARALLEL_MAX_WORKERS = 4
PLAN_FAST_CACHE_TTL_SECONDS = 300
PLAN_FAST_CACHE_MAX_ENTRIES = 32
PLAN_FAST_SLOW_LOG_MS = 1000
PLAN_FAST_READ_TIMEOUT_SECONDS = 1.0
PLAN_AUDIT_MODES = frozenset({"fast", "strict"})
_PLAN_FAST_CACHE: dict[tuple[object, ...], tuple[float, pd.DataFrame]] = {}


def clear_fast_plan_cache() -> None:
    _PLAN_FAST_CACHE.clear()


@dataclass(frozen=True)
class FetchWindowGroup:
    symbols: tuple[str, ...]
    start: str
    end: str


@dataclass(frozen=True)
class _ExpectedCoverageWindow:
    timeframe: str
    minutes: int
    step: pd.Timedelta
    segments: tuple[tuple[pd.Timestamp, pd.Timestamp], ...]
    segments_by_day: dict[pd.Timestamp, tuple[tuple[pd.Timestamp, pd.Timestamp], ...]]
    expected_rows: int


@dataclass(frozen=True)
class BacktestDataBundle:
    """回测数据包；分钟线、日线、过滤日和数据审计结果一起返回。"""

    bars: pd.DataFrame
    daily_bars: pd.DataFrame
    filtered_limit_open_days: pd.DataFrame
    data_audit: pd.DataFrame
    data_gap_episodes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=DATA_GAP_EPISODE_COLUMNS))
    limit_filter_audit: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=LIMIT_FILTER_AUDIT_COLUMNS)
    )


@dataclass(frozen=True)
class MultiTimeframeBacktestDataBundle:
    """多周期回测数据包；一次请求返回每个周期独立 K 线和统一日线过滤信息。"""

    bars_by_timeframe: dict[str, pd.DataFrame]
    daily_bars: pd.DataFrame
    filtered_limit_open_days: pd.DataFrame
    data_audit: pd.DataFrame
    data_gap_episodes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=DATA_GAP_EPISODE_COLUMNS))
    limit_filter_audit: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=LIMIT_FILTER_AUDIT_COLUMNS)
    )


class MarketDataRepository:
    """本地行情仓库入口；统一读取分钟线、日线和写入 parquet。"""

    def __init__(self, data_root: str | Path, adjust: str = "qfq") -> None:
        self.data_root = canonical_data_root(data_root)
        self.adjust = adjust

    def available_symbols(self, timeframe: str) -> list[str]:
        return available_symbols(self.data_root, timeframe, self.adjust)

    def inventory(
        self,
        *,
        timeframes: tuple[str, ...] | list[str] = SUPPORTED_TIMEFRAMES,
        symbols: tuple[str, ...] | list[str] | None = None,
        existing_catalog: pd.DataFrame | None = None,
        fast_existing: bool = False,
    ) -> pd.DataFrame:
        return inventory_local_data(
            data_root=self.data_root,
            adjust=self.adjust,
            timeframes=timeframes,
            symbols=symbols,
            existing_catalog=existing_catalog,
            fast_existing=fast_existing,
        )

    def load_bars(
        self,
        *,
        timeframe: str,
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        return load_local_bars(
            data_root=self.data_root,
            timeframe=timeframe,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
        )

    def load_daily_bars(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        return load_daily_bars(
            data_root=self.data_root,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
        )

    def write_bars(self, *, timeframe: str, bars: pd.DataFrame) -> pd.DataFrame:
        return write_local_bars(data_root=self.data_root, timeframe=timeframe, adjust=self.adjust, bars=bars)

    def audit_bars(
        self,
        *,
        timeframe: str,
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        normalized_timeframe = ensure_supported_timeframe(timeframe)
        expected_sessions_by_symbol = (
            _expected_sessions_by_symbol_from_daily(
                data_root=self.data_root,
                adjust=self.adjust,
                symbols=unique_symbols(tuple(symbols)),
                start=start,
                end=end,
            )
            if normalized_timeframe != "1d"
            else None
        )
        return audit_local_data(
            data_root=self.data_root,
            timeframe=normalized_timeframe,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )

    def data_gap_episodes(
        self,
        *,
        timeframe: str,
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        normalized_timeframe = ensure_supported_timeframe(timeframe)
        expected_sessions_by_symbol = (
            _expected_sessions_by_symbol_from_daily(
                data_root=self.data_root,
                adjust=self.adjust,
                symbols=unique_symbols(tuple(symbols)),
                start=start,
                end=end,
            )
            if normalized_timeframe != "1d"
            else None
        )
        return data_gap_episodes(
            data_root=self.data_root,
            timeframe=normalized_timeframe,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )

    def update_from_tdx(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        timeframe: str,
        start: str,
        end: str,
        tqcenter_path: str = "",
        tq_client: Any | None = None,
        batch_size: int = 100,
        progress_callback: ProgressCallback | None = None,
    ) -> pd.DataFrame:
        return update_from_tdx(
            data_root=self.data_root,
            adjust=self.adjust,
            symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=end,
            tqcenter_path=tqcenter_path,
            tq_client=tq_client,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )

    def prepare_from_tdx(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        timeframes: tuple[str, ...] | list[str],
        start: str,
        end: str,
        tqcenter_path: str = "",
        tq_client: Any | None = None,
        batch_size: int = 100,
        progress_callback: ProgressCallback | None = None,
        min_coverage_ratio: float | None = None,
        strict_after_update: bool = True,
    ) -> pd.DataFrame:
        return prepare_tdx_backtest_data(
            data_root=self.data_root,
            adjust=self.adjust,
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
            tqcenter_path=tqcenter_path,
            tq_client=tq_client,
            batch_size=batch_size,
            progress_callback=progress_callback,
            min_coverage_ratio=min_coverage_ratio,
            strict_after_update=strict_after_update,
        )

    def plan_from_tdx(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        timeframes: tuple[str, ...] | list[str],
        start: str,
        end: str,
        min_coverage_ratio: float | None = None,
        audit_mode: str = "strict",
    ) -> pd.DataFrame:
        return plan_tdx_backtest_data(
            data_root=self.data_root,
            adjust=self.adjust,
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
            min_coverage_ratio=min_coverage_ratio,
            audit_mode=audit_mode,
        )

    def symbol_metadata(self, *, tdx_path: str | Path = "") -> pd.DataFrame:
        """返回股票代码和名称元数据；供 UI、统计展示和导出解释复用。"""
        return load_symbol_metadata(self.data_root, tdx_path=tdx_path)

    def symbol_names(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        tdx_path: str | Path = "",
    ) -> dict[str, str]:
        """返回指定股票的名称映射；本地 sidecar/TDX 优先，常用代码兜底。"""
        return resolve_symbol_names(symbols, data_root=self.data_root, tdx_path=tdx_path)

    def load_backtest_data(
        self,
        *,
        timeframe: str,
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        filter_limit_open: bool = True,
        daily_lookback_days: int = 10,
        strict_data_quality: bool = True,
        min_coverage_ratio: float | None = None,
    ) -> BacktestDataBundle:
        return load_backtest_data(
            data_root=self.data_root,
            timeframe=timeframe,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
            filter_limit_open=filter_limit_open,
            daily_lookback_days=daily_lookback_days,
            strict_data_quality=strict_data_quality,
            min_coverage_ratio=min_coverage_ratio,
        )

    def load_multi_timeframe_backtest_data(
        self,
        *,
        timeframes: tuple[str, ...] | list[str],
        symbols: tuple[str, ...] | list[str],
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        filter_limit_open: bool = True,
        daily_lookback_days: int = 10,
        strict_data_quality: bool = True,
        min_coverage_ratio: float | None = None,
    ) -> MultiTimeframeBacktestDataBundle:
        return load_multi_timeframe_backtest_data(
            data_root=self.data_root,
            timeframes=timeframes,
            adjust=self.adjust,
            symbols=symbols,
            start=start,
            end=end,
            filter_limit_open=filter_limit_open,
            daily_lookback_days=daily_lookback_days,
            strict_data_quality=strict_data_quality,
            min_coverage_ratio=min_coverage_ratio,
        )


def load_backtest_data(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    filter_limit_open: bool = True,
    daily_lookback_days: int = 10,
    strict_data_quality: bool = True,
    min_coverage_ratio: float | None = None,
) -> BacktestDataBundle:
    if daily_lookback_days < 1:
        raise ValueError("daily_lookback_days 至少需要 1。")
    min_coverage_ratio = _normalize_min_coverage_ratio(min_coverage_ratio)
    daily_start = pd.Timestamp(start).normalize() - pd.Timedelta(days=daily_lookback_days)
    daily, daily_audit = _load_daily_dependency_for_backtest(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        start=daily_start,
        end=end,
        strict_data_quality=strict_data_quality,
    )

    data_audit = audit_local_data(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
        expected_sessions_by_symbol=daily_sessions_by_symbol(daily, start=start, end=end),
    )
    gap_episodes = data_gap_episodes(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
        expected_sessions_by_symbol=daily_sessions_by_symbol(daily, start=start, end=end),
    )
    if strict_data_quality:
        _raise_for_failed_data_audit(data_audit, min_coverage_ratio=min_coverage_ratio)

    intraday_symbols = _symbols_safe_for_backtest_load(
        symbols=symbols,
        audit=data_audit,
        timeframe=timeframe,
        strict_data_quality=strict_data_quality,
    )
    intraday = load_local_bars(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=intraday_symbols,
        start=start,
        end=end,
    )
    intraday = _drop_zero_liquidity_bars(intraday)
    blocked = limit_open_dates_in_window(daily, start=start, end=end) if filter_limit_open and not daily.empty else pd.DataFrame()
    filter_audit = limit_open_filter_audit(
        daily,
        symbols=symbols,
        start=start,
        end=end,
        filter_enabled=filter_limit_open,
        blocked=blocked,
        daily_audit=daily_audit,
    )
    if strict_data_quality:
        _raise_for_failed_limit_filter_audit(filter_audit)
    if not filter_limit_open or intraday.empty or daily.empty:
        return BacktestDataBundle(
            bars=intraday,
            daily_bars=daily,
            filtered_limit_open_days=blocked,
            data_audit=data_audit,
            data_gap_episodes=gap_episodes,
            limit_filter_audit=filter_audit,
        )

    filtered = filter_limit_open_days(intraday, daily)
    return BacktestDataBundle(
        bars=filtered,
        daily_bars=daily,
        filtered_limit_open_days=blocked,
        data_audit=data_audit,
        data_gap_episodes=gap_episodes,
        limit_filter_audit=filter_audit,
    )


def load_multi_timeframe_backtest_data(
    *,
    data_root: str | Path,
    timeframes: tuple[str, ...] | list[str],
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    filter_limit_open: bool = True,
    daily_lookback_days: int = 10,
    strict_data_quality: bool = True,
    min_coverage_ratio: float | None = None,
) -> MultiTimeframeBacktestDataBundle:
    """一次加载多周期回测数据；每个周期独立审计，日线过滤信息统一复用。"""
    if daily_lookback_days < 1:
        raise ValueError("daily_lookback_days 至少需要 1。")
    min_coverage_ratio = _normalize_min_coverage_ratio(min_coverage_ratio)
    normalized_timeframes = _unique_timeframes(timeframes)
    if not normalized_timeframes:
        raise ValueError("timeframes 不能为空。")
    daily_start = pd.Timestamp(start).normalize() - pd.Timedelta(days=daily_lookback_days)
    daily, daily_audit = _load_daily_dependency_for_backtest(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        start=daily_start,
        end=end,
        strict_data_quality=strict_data_quality,
    )
    expected_sessions_by_symbol = daily_sessions_by_symbol(daily, start=start, end=end)

    audit_frames = [
        audit_local_data(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )
        for timeframe in normalized_timeframes
    ]
    data_audit = pd.concat(audit_frames, ignore_index=True) if audit_frames else pd.DataFrame(columns=AUDIT_COLUMNS)
    gap_frames = [
        data_gap_episodes(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )
        for timeframe in normalized_timeframes
    ]
    gap_frames = [frame for frame in gap_frames if not frame.empty]
    gap_episodes = (
        pd.concat(gap_frames, ignore_index=True) if gap_frames else pd.DataFrame(columns=DATA_GAP_EPISODE_COLUMNS)
    )
    if strict_data_quality:
        _raise_for_failed_data_audit(data_audit, min_coverage_ratio=min_coverage_ratio)

    blocked = limit_open_dates_in_window(daily, start=start, end=end) if filter_limit_open and not daily.empty else pd.DataFrame()
    filter_audit = limit_open_filter_audit(
        daily,
        symbols=symbols,
        start=start,
        end=end,
        filter_enabled=filter_limit_open,
        blocked=blocked,
        daily_audit=daily_audit,
    )
    if strict_data_quality:
        _raise_for_failed_limit_filter_audit(filter_audit)
    bars_by_timeframe: dict[str, pd.DataFrame] = {}
    for timeframe in normalized_timeframes:
        timeframe_symbols = _symbols_safe_for_backtest_load(
            symbols=symbols,
            audit=data_audit,
            timeframe=timeframe,
            strict_data_quality=strict_data_quality,
        )
        bars = load_local_bars(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=timeframe_symbols,
            start=start,
            end=end,
        )
        bars = _drop_zero_liquidity_bars(bars)
        if filter_limit_open and not bars.empty and not daily.empty:
            bars = filter_limit_open_days(bars, daily)
        bars_by_timeframe[timeframe] = bars

    return MultiTimeframeBacktestDataBundle(
        bars_by_timeframe=bars_by_timeframe,
        daily_bars=daily,
        filtered_limit_open_days=blocked,
        data_audit=data_audit,
        data_gap_episodes=gap_episodes,
        limit_filter_audit=filter_audit,
    )


def _unique_timeframes(timeframes: tuple[str, ...] | list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in timeframes:
        timeframe = ensure_supported_timeframe(item)
        if timeframe in seen:
            continue
        seen.add(timeframe)
        result.append(timeframe)
    return result


def _drop_zero_liquidity_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """回测数据包只向 detector 暴露有真实成交的 K，零流动性数量保留在审计表。"""
    if bars.empty or "volume" not in bars.columns or "amount" not in bars.columns:
        return bars
    tradable = bars["volume"].gt(0) & bars["amount"].gt(0)
    return bars.loc[tradable].reset_index(drop=True)


def _load_daily_dependency_for_backtest(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    strict_data_quality: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """先审计再读取日 K 依赖；损坏文件不能绕过审计直接让回测崩溃。"""
    daily_audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
    )
    if strict_data_quality:
        hard_failures = daily_audit.loc[
            daily_audit["status"].astype(str).isin(DAILY_DEPENDENCY_FAILURE_STATUSES)
        ]
        _raise_for_failed_data_audit(hard_failures)

    daily_symbols = _symbols_safe_for_backtest_load(
        symbols=symbols,
        audit=daily_audit,
        timeframe="1d",
        strict_data_quality=strict_data_quality,
    )
    daily = load_daily_bars(
        data_root=data_root,
        adjust=adjust,
        symbols=daily_symbols,
        start=start,
        end=end,
    )
    return daily, daily_audit


def _symbols_safe_for_backtest_load(
    *,
    symbols: tuple[str, ...] | list[str],
    audit: pd.DataFrame,
    timeframe: str,
    strict_data_quality: bool,
) -> list[str]:
    """非严格回测只跳过无法读取的文件；质量问题仍交给 normalize_bars 暴露到结果中。"""
    normalized_symbols = unique_symbols(tuple(symbols))
    if strict_data_quality or audit.empty or not {"stock_code", "timeframe", "status"}.issubset(audit.columns):
        return normalized_symbols
    unsafe_rows = audit.loc[
        audit["timeframe"].astype(str).eq(timeframe)
        & audit["status"].astype(str).isin(UNLOADABLE_AUDIT_STATUSES),
        "stock_code",
    ]
    unsafe_symbols = {normalize_symbol(symbol) for symbol in unsafe_rows}
    return [symbol for symbol in normalized_symbols if symbol not in unsafe_symbols]


def _raise_for_failed_data_audit(audit: pd.DataFrame, *, min_coverage_ratio: float | None = None) -> None:
    if audit.empty:
        return
    messages: list[str] = []
    failed = audit.loc[audit["status"] != "ok", ["stock_code", "timeframe", "status", "message"]]
    messages.extend(
        f"{row.stock_code}/{row.timeframe}={row.status}({row.message})"
        for row in failed.itertuples(index=False)
    )
    if min_coverage_ratio is not None:
        coverage_failed = audit.loc[
            (audit["expected_rows"] > 0) & (audit["coverage_ratio"] < min_coverage_ratio),
            ["stock_code", "timeframe", "coverage_ratio"],
        ]
        messages.extend(
            f"{row.stock_code}/{row.timeframe}=coverage_below_min("
            f"{_format_ratio(row.coverage_ratio)} < {_format_ratio(min_coverage_ratio)})"
            for row in coverage_failed.itertuples(index=False)
        )
    if messages:
        raise ValueError(f"本地行情数据未通过质量门禁：{'; '.join(messages)}")


def _raise_for_failed_limit_filter_audit(filter_audit: pd.DataFrame) -> None:
    """严格模式下要求日 K 过滤真实执行，避免涨停开盘日漏过滤。"""
    if filter_audit.empty:
        return
    enabled = filter_audit["filter_enabled"].astype(bool) if "filter_enabled" in filter_audit.columns else True
    failed = filter_audit.loc[
        enabled & ~filter_audit["status"].astype(str).isin({"ok"}),
        ["stock_code", "status", "message"],
    ]
    if failed.empty:
        return
    messages = [
        f"{row.stock_code}={row.status}({row.message})"
        for row in failed.itertuples(index=False)
    ]
    raise ValueError(f"日K一字涨停过滤未通过严格门禁：{'; '.join(messages)}")


def _format_ratio(value: float) -> str:
    return f"{float(value):.6g}"


def _emit_progress(callback: ProgressCallback | None, **payload: object) -> None:
    if callback is not None:
        callback(payload)


def update_from_tdx(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    timeframe: str,
    start: str,
    end: str,
    tqcenter_path: str = "",
    tq_client: Any | None = None,
    batch_size: int = 100,
    progress_callback: ProgressCallback | None = None,
) -> pd.DataFrame:
    from tdx_downloader.data.tdx import fetch_tdx_bars

    fetch_start, fetch_end = _tdx_fetch_window_for_timeframe(timeframe, start=start, end=end)
    _emit_progress(
        progress_callback,
        stage="fetch_start",
        timeframe=ensure_supported_timeframe(timeframe),
        symbol_count=len(unique_symbols(tuple(symbols))),
        start=fetch_start,
        end=fetch_end,
    )
    bars = fetch_tdx_bars(
        symbols=symbols,
        start=fetch_start,
        end=fetch_end,
        timeframe=timeframe,
        adjust=adjust,
        tqcenter_path=tqcenter_path,
        tq_client=tq_client,
        batch_size=batch_size,
        progress_callback=progress_callback,
    )
    _emit_progress(
        progress_callback,
        stage="write_start",
        timeframe=ensure_supported_timeframe(timeframe),
        rows=len(bars),
    )
    write_started_at = time.perf_counter()
    result = write_local_bars(data_root=data_root, timeframe=timeframe, adjust=adjust, bars=bars, refresh_coverage=False)
    partial_coverage = upsert_partial_coverage_runs_from_bars(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        bars=bars,
    )
    _emit_progress(
        progress_callback,
        stage="write_done",
        timeframe=ensure_supported_timeframe(timeframe),
        rows=int(result["rows"].sum()) if "rows" in result.columns else 0,
        new_rows=int(result["new_rows"].sum()) if "new_rows" in result.columns else 0,
        coverage_rows=int(len(partial_coverage)),
        write_ms=int((time.perf_counter() - write_started_at) * 1000),
    )
    return result


def _tdx_fetch_window_for_timeframe(timeframe: str, *, start: str, end: str) -> tuple[str, str]:
    """日 K 请求按自然日补齐，避免分钟回测的盘中时间过滤掉日线。"""
    start_ts, end_ts = parse_time_window(start, end)
    if ensure_supported_timeframe(timeframe) != "1d":
        return start, end
    return str(start_ts.date()), str(end_ts.date())


def plan_tdx_backtest_data(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    timeframes: tuple[str, ...] | list[str],
    start: str,
    end: str,
    min_coverage_ratio: float | None = None,
    audit_mode: str = "strict",
) -> pd.DataFrame:
    """生成 TDX 补齐计划；只审计本地数据，不触发 TDX 请求。"""
    normalized_mode = _normalize_plan_audit_mode(audit_mode)
    normalized_timeframes = _timeframes_with_daily_dependency(timeframes)
    if not normalized_timeframes:
        raise ValueError("timeframes 不能为空。")
    normalized_symbols = unique_symbols(tuple(symbols))
    min_coverage_ratio = _normalize_min_coverage_ratio(min_coverage_ratio)
    if normalized_mode == "fast":
        return _cached_fast_tdx_plan(
            data_root=data_root,
            adjust=adjust,
            symbols=normalized_symbols,
            timeframes=normalized_timeframes,
            start=start,
            end=end,
            min_coverage_ratio=min_coverage_ratio,
        )
    expected_sessions_by_symbol = _expected_sessions_by_symbol_from_daily(
        data_root=data_root,
        adjust=adjust,
        symbols=normalized_symbols,
        start=start,
        end=end,
    )

    rows: list[dict[str, object]] = []
    audits = _plan_audits_by_timeframe(
        data_root=data_root,
        adjust=adjust,
        symbols=normalized_symbols,
        timeframes=normalized_timeframes,
        start=start,
        end=end,
        expected_sessions_by_symbol=expected_sessions_by_symbol,
    )
    derived_targets_by_source = _derivable_targets_by_source(normalized_timeframes)
    derivable_targets = {target: source for source, targets in derived_targets_by_source.items() for target in targets}
    for timeframe in normalized_timeframes:
        source_timeframe = derivable_targets.get(timeframe)
        rows.extend(
            _tdx_plan_rows(
                audits[timeframe],
                min_coverage_ratio=min_coverage_ratio,
                derived_from=source_timeframe,
                source_audit=audits.get(source_timeframe) if source_timeframe else None,
            )
        )
    result = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    return _apply_unresolved_gaps_to_plan(
        result,
        data_root=data_root,
        adjust=adjust,
        symbols=normalized_symbols,
        timeframes=normalized_timeframes,
        start=start,
        end=end,
    )


def _normalize_plan_audit_mode(mode: str) -> str:
    normalized = str(mode or "strict").strip().lower()
    if normalized not in PLAN_AUDIT_MODES:
        allowed = "、".join(sorted(PLAN_AUDIT_MODES))
        raise ValueError(f"plan audit_mode 仅支持 {allowed}。")
    return normalized


def _cached_fast_tdx_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str,
    end: str,
    min_coverage_ratio: float | None,
) -> pd.DataFrame:
    started_at = time.perf_counter()
    coverage_started_at = time.perf_counter()
    coverage = _read_coverage_for_plan(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
    )
    coverage_ms = int((time.perf_counter() - coverage_started_at) * 1000)
    key = _fast_plan_cache_key(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
        min_coverage_ratio=min_coverage_ratio,
        coverage=coverage,
    )
    cached = _PLAN_FAST_CACHE.get(key)
    now = time.monotonic()
    if cached is not None:
        cached_at, cached_frame = cached
        if now - cached_at <= PLAN_FAST_CACHE_TTL_SECONDS:
            total_ms = int((time.perf_counter() - started_at) * 1000)
            _log_fast_plan_timing(
                "cache_hit",
                total_ms=total_ms,
                coverage_ms=coverage_ms,
                symbols=len(symbols),
                timeframes=timeframes,
                rows=len(cached_frame),
            )
            return cached_frame.copy()
    result = _fast_tdx_plan(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
        min_coverage_ratio=min_coverage_ratio,
        coverage=coverage,
        initial_coverage_ms=coverage_ms,
        started_at=started_at,
    )
    _PLAN_FAST_CACHE[key] = (now, result.copy())
    final_key = _fast_plan_cache_key(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
        min_coverage_ratio=min_coverage_ratio,
        coverage=coverage,
    )
    if final_key != key:
        _PLAN_FAST_CACHE[final_key] = (now, result.copy())
    if len(_PLAN_FAST_CACHE) > PLAN_FAST_CACHE_MAX_ENTRIES:
        oldest_key = min(_PLAN_FAST_CACHE, key=lambda item: _PLAN_FAST_CACHE[item][0])
        _PLAN_FAST_CACHE.pop(oldest_key, None)
    return result


def _fast_plan_cache_key(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str,
    end: str,
    min_coverage_ratio: float | None,
    coverage: pd.DataFrame | None = None,
) -> tuple[object, ...]:
    catalog_path = catalog_path_for(data_root)
    try:
        catalog_stat = catalog_path.stat()
        catalog_version = (int(catalog_stat.st_size), int(catalog_stat.st_mtime_ns))
    except FileNotFoundError:
        catalog_version = (0, 0)
    coverage_version = _coverage_version(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        coverage=coverage,
    )
    unresolved_version = _unresolved_version(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
    )
    return (
        str(canonical_data_root(data_root)),
        str(adjust),
        tuple(symbols),
        tuple(timeframes),
        str(start),
        str(end),
        None if min_coverage_ratio is None else round(float(min_coverage_ratio), 8),
        catalog_version,
        coverage_version,
        unresolved_version,
    )


def _coverage_version(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    coverage: pd.DataFrame | None = None,
) -> tuple[object, ...]:
    if coverage is None:
        coverage = query_coverage_runs(
            data_root=data_root,
            symbols=tuple(symbols),
            adjust=adjust,
            timeframes=tuple(timeframes),
        )
    if coverage.empty:
        return (0, 0, 0)
    file_size_total = int(pd.to_numeric(coverage["file_size_bytes"], errors="coerce").fillna(0).sum())
    mtime_max = int(pd.to_numeric(coverage["mtime_ns"], errors="coerce").fillna(0).max())
    row_count_total = int(pd.to_numeric(coverage.get("row_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    start_min = str(pd.to_datetime(coverage.get("start_at", pd.Series(dtype=object)), errors="coerce").min())
    end_max = str(pd.to_datetime(coverage.get("end_at", pd.Series(dtype=object)), errors="coerce").max())
    updated_max = str(pd.to_datetime(coverage.get("updated_at", pd.Series(dtype=object)), errors="coerce").max())
    return (int(len(coverage)), row_count_total, start_min, end_max, file_size_total, mtime_max, updated_max)


def _unresolved_version(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> tuple[object, ...]:
    query_start, query_end = _coverage_query_window_for_plan(timeframes=timeframes, start=start, end=end)
    unresolved = query_unresolved_gaps(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        start=query_start,
        end=query_end,
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )
    if unresolved.empty:
        return (0, 0, "")
    missing_rows = int(pd.to_numeric(unresolved.get("missing_rows", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    updated_max = str(pd.to_datetime(unresolved.get("updated_at", pd.Series(dtype=object)), errors="coerce").max())
    retry_total = int(pd.to_numeric(unresolved.get("retry_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    return (int(len(unresolved)), missing_rows, retry_total, updated_max)


def _fast_tdx_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str,
    end: str,
    min_coverage_ratio: float | None,
    coverage: pd.DataFrame | None = None,
    initial_coverage_ms: int | None = None,
    started_at: float | None = None,
) -> pd.DataFrame:
    started_at = time.perf_counter() if started_at is None else started_at
    catalog_started_at = time.perf_counter()
    catalog = _read_catalog_for_plan(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
    )
    catalog_ms = int((time.perf_counter() - catalog_started_at) * 1000)
    coverage_ms = initial_coverage_ms
    if coverage is None:
        coverage_started_at = time.perf_counter()
        coverage = _read_coverage_for_plan(
            data_root=data_root,
            adjust=adjust,
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
        )
        coverage_ms = int((time.perf_counter() - coverage_started_at) * 1000)
    plan_started_at = time.perf_counter()
    daily_sessions = _daily_sessions_from_catalog(
        coverage,
        symbols=symbols,
        start=start,
        end=end,
    )
    rows: list[dict[str, object]] = []
    derived_targets_by_source = _derivable_targets_by_source(timeframes)
    derivable_targets = {target: source for source, targets in derived_targets_by_source.items() for target in targets}
    audits_by_timeframe: dict[str, pd.DataFrame] = {}
    for timeframe in timeframes:
        audit = _fast_audit_from_metadata(
            catalog,
            coverage,
            data_root=data_root,
            adjust=adjust,
            symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=end,
            expected_sessions_by_symbol=daily_sessions,
        )
        audits_by_timeframe[timeframe] = audit
    for timeframe in timeframes:
        source_timeframe = derivable_targets.get(timeframe)
        rows.extend(
            _tdx_plan_rows(
                audits_by_timeframe[timeframe],
                min_coverage_ratio=min_coverage_ratio,
                derived_from=source_timeframe,
                source_audit=audits_by_timeframe.get(source_timeframe) if source_timeframe else None,
            )
        )
    result = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    result = _apply_unresolved_gaps_to_plan(
        result,
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
    )
    plan_ms = int((time.perf_counter() - plan_started_at) * 1000)
    total_ms = int((time.perf_counter() - started_at) * 1000)
    _log_fast_plan_timing(
        "computed",
        total_ms=total_ms,
        coverage_ms=0 if coverage_ms is None else int(coverage_ms),
        catalog_ms=catalog_ms,
        plan_ms=plan_ms,
        symbols=len(symbols),
        timeframes=timeframes,
        rows=len(result),
    )
    return result


def _fresh_coverage_for_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    coverage_start, coverage_end = _coverage_query_window_for_plan(timeframes=timeframes, start=start, end=end)
    refresh_coverage_runs(
        data_root=data_root,
        adjust=adjust,
        symbols=tuple(symbols),
        timeframes=tuple(timeframes),
    )
    return query_coverage_runs(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        start=coverage_start,
        end=coverage_end,
    )


def _read_coverage_for_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    coverage_start, coverage_end = _coverage_query_window_for_plan(timeframes=timeframes, start=start, end=end)
    return query_coverage_runs(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        start=coverage_start,
        end=coverage_end,
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )


def _coverage_query_window_for_plan(
    *,
    timeframes: list[str],
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if start is None or end is None:
        return None, None
    windows = []
    for timeframe in timeframes:
        windows.append(_audit_window_for_timeframe(timeframe, start=start, end=end))
    if not windows:
        return pd.Timestamp(start), pd.Timestamp(end)
    return min(item[0] for item in windows), max(item[1] for item in windows)


def _log_fast_plan_timing(stage: str, **values: object) -> None:
    total_ms = int(values.get("total_ms", 0) or 0)
    log = _LOGGER.warning if total_ms >= PLAN_FAST_SLOW_LOG_MS else _LOGGER.info
    log("fast_tdx_plan %s %s", stage, values)


def _apply_unresolved_gaps_to_plan(
    plan: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    if plan.empty:
        return plan
    query_start, query_end = _coverage_query_window_for_plan(timeframes=timeframes, start=start, end=end)
    unresolved = query_unresolved_gaps(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        start=query_start,
        end=query_end,
        statuses=("provider_no_data", "provider_partial_gap", "provider_unresolved"),
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )
    if unresolved.empty:
        return plan
    unresolved_by_key: dict[tuple[str, str, str], list[object]] = {}
    for row in unresolved.itertuples(index=False):
        key = (str(row.stock_code), str(row.timeframe), str(row.adjust))
        unresolved_by_key.setdefault(key, []).append(row)
    result = plan.copy()
    for index, row in result.iterrows():
        if str(row.get("action", "")) != "fetch":
            continue
        key = (str(row.get("stock_code", "")), str(row.get("timeframe", "")), str(row.get("adjust", "")))
        matches = _matching_unresolved_gap_records(row, unresolved_by_key.get(key, []))
        if not matches:
            continue
        latest = max(matches, key=lambda item: str(getattr(item, "updated_at", "")))
        result.at[index, "action"] = "unresolved"
        result.at[index, "reason"] = str(getattr(latest, "status", "provider_unresolved") or "provider_unresolved")
        result.at[index, "coverage_status"] = "provider_unresolved"
        retry_count = int(getattr(latest, "retry_count", 0) or 0)
        last_seen = str(getattr(latest, "last_seen_at", "") or "")
        result.at[index, "message"] = (
            f"该缺口已真实请求 TDX 后仍未补齐，暂不自动重复抓取；"
            f"状态 {getattr(latest, 'status', 'provider_unresolved')}，重试 {retry_count} 次，最近 {last_seen}。"
        )
    return result


def _apply_unresolved_gaps_to_prepare_result(
    result: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    if result.empty:
        return result
    query_start, query_end = _coverage_query_window_for_plan(timeframes=timeframes, start=start, end=end)
    unresolved = query_unresolved_gaps(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        start=query_start,
        end=query_end,
        statuses=("provider_no_data", "provider_partial_gap", "provider_unresolved"),
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )
    if unresolved.empty:
        return result
    unresolved_by_key: dict[tuple[str, str, str], list[object]] = {}
    for row in unresolved.itertuples(index=False):
        key = (str(row.stock_code), str(row.timeframe), str(row.adjust))
        unresolved_by_key.setdefault(key, []).append(row)
    prepared = result.copy()
    for index, row in prepared.iterrows():
        if str(row.get("action", "")) == "fetched":
            continue
        key = (str(row.get("stock_code", "")), str(row.get("timeframe", "")), str(row.get("adjust", "")))
        matches = _matching_unresolved_gap_records(row, unresolved_by_key.get(key, []))
        if not matches:
            continue
        latest = max(matches, key=lambda item: str(getattr(item, "updated_at", "")))
        status = str(getattr(latest, "status", "provider_unresolved") or "provider_unresolved")
        retry_count = int(getattr(latest, "retry_count", 0) or 0)
        last_seen = str(getattr(latest, "last_seen_at", "") or "")
        prepared.at[index, "action"] = "unresolved"
        prepared.at[index, "after_status"] = status
        prepared.at[index, "message"] = (
            f"该缺口已真实请求 TDX 后仍未补齐，暂不自动重复抓取；"
            f"状态 {status}，重试 {retry_count} 次，最近 {last_seen}。"
        )
    return prepared


def _matching_unresolved_gap_records(plan_row: object, records: list[object]) -> list[object]:
    if not records:
        return []
    first_missing = _optional_timestamp(_row_value(plan_row, "first_missing_at"))
    last_missing = _optional_timestamp(_row_value(plan_row, "last_missing_at"))
    if pd.isna(first_missing) or pd.isna(last_missing):
        first_missing = _optional_timestamp(_row_value(plan_row, "requested_start"))
        last_missing = _optional_timestamp(_row_value(plan_row, "requested_end"))
    if pd.isna(first_missing) or pd.isna(last_missing):
        return []
    result: list[object] = []
    for record in records:
        start_at = _optional_timestamp(getattr(record, "start_at", pd.NaT))
        end_at = _optional_timestamp(getattr(record, "end_at", pd.NaT))
        if pd.isna(start_at) or pd.isna(end_at):
            continue
        if end_at >= first_missing and start_at <= last_missing:
            result.append(record)
    return result


def _row_value(row: object, column: str) -> object:
    if hasattr(row, "get"):
        return row.get(column, pd.NaT)  # type: ignore[call-arg]
    return getattr(row, column, pd.NaT)


def _fresh_catalog_for_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
) -> pd.DataFrame:
    catalog = query_catalog(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        data_kinds=("price",),
        indicators=("ohlcv",),
    )
    catalog = _filter_plan_catalog(catalog, adjust=adjust, symbols=symbols)
    missing = _missing_or_stale_catalog_records(
        catalog,
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=timeframes,
    )
    if missing:
        refreshed = inventory_local_data(
            data_root=data_root,
            adjust=adjust,
            timeframes=tuple(sorted({timeframe for _, timeframe in missing}, key=SUPPORTED_TIMEFRAMES.index)),
            symbols=tuple(sorted({symbol for symbol, _ in missing})),
        )
        upsert_catalog_records(data_root=data_root, inventory=refreshed)
        catalog = query_catalog(
            data_root=data_root,
            symbols=tuple(symbols),
            adjust=adjust,
            timeframes=tuple(timeframes),
            data_kinds=("price",),
            indicators=("ohlcv",),
        )
        catalog = _filter_plan_catalog(catalog, adjust=adjust, symbols=symbols)
    return catalog


def _read_catalog_for_plan(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
) -> pd.DataFrame:
    catalog = query_catalog(
        data_root=data_root,
        symbols=tuple(symbols),
        adjust=adjust,
        timeframes=tuple(timeframes),
        data_kinds=("price",),
        indicators=("ohlcv",),
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )
    return _filter_plan_catalog(catalog, adjust=adjust, symbols=symbols)


def _filter_plan_catalog(
    catalog: pd.DataFrame,
    *,
    adjust: str,
    symbols: list[str],
) -> pd.DataFrame:
    if catalog.empty:
        return pd.DataFrame(columns=catalog.columns)
    result = catalog.copy()
    result["stock_code"] = result["stock_code"].map(normalize_symbol)
    result = result.loc[
        result["stock_code"].isin(set(symbols))
        & result["adjust"].astype(str).eq(str(adjust))
        & result["data_kind"].astype(str).eq("price")
        & result["indicator"].astype(str).eq("ohlcv")
    ].copy()
    if result.empty:
        return result
    result["_status_rank"] = result["status"].astype(str).map(lambda value: 0 if value == "cached" else 1)
    result = (
        result.sort_values(["stock_code", "timeframe", "_status_rank", "modified_at"], kind="mergesort")
        .drop_duplicates(subset=["stock_code", "timeframe"], keep="first")
        .drop(columns=["_status_rank"])
        .reset_index(drop=True)
    )
    return result


def _missing_or_stale_catalog_records(
    catalog: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
) -> list[tuple[str, str]]:
    by_key = {
        (str(row.stock_code), str(row.timeframe)): row
        for row in catalog.itertuples(index=False)
    } if not catalog.empty else {}
    missing: list[tuple[str, str]] = []
    for timeframe in timeframes:
        root = resolve_timeframe_root(data_root, timeframe) / adjust
        for symbol in symbols:
            key = (symbol, timeframe)
            row = by_key.get(key)
            path = root / f"{symbol}.parquet"
            if row is None:
                if path.exists():
                    missing.append(key)
                continue
            if _catalog_record_is_stale(row, path):
                missing.append(key)
    return missing


def _catalog_record_is_stale(row: object, path: Path) -> bool:
    if not path.exists():
        try:
            catalog_size = int(getattr(row, "file_size_bytes", 0) or 0)
        except (TypeError, ValueError):
            catalog_size = 0
        return str(getattr(row, "status", "")) == "cached" and catalog_size <= 0
    try:
        stat = path.stat()
    except OSError:
        return False
    try:
        catalog_size = int(getattr(row, "file_size_bytes", 0) or 0)
    except (TypeError, ValueError):
        catalog_size = 0
    if catalog_size != int(stat.st_size):
        return True
    modified_at = _optional_timestamp(getattr(row, "modified_at", pd.NaT))
    if pd.isna(modified_at):
        return True
    stat_modified_at = pd.Timestamp.fromtimestamp(stat.st_mtime)
    return abs((modified_at - stat_modified_at).total_seconds()) > 1.0


def _daily_sessions_from_catalog(
    coverage: pd.DataFrame,
    *,
    symbols: list[str],
    start: str,
    end: str,
) -> dict[str, list[pd.Timestamp]]:
    """Return only local daily sessions outside the default business-day calendar.

    The fast planner always builds a base business-day calendar for the requested
    window. Expanding every daily coverage run back into the same business days
    is pure overhead for full-market previews, so this helper only contributes
    exceptional non-business dates if they exist in local data.
    """
    if coverage.empty:
        return {}
    daily = coverage.loc[coverage["timeframe"].astype(str).eq("1d")].copy()
    if daily.empty:
        return {}
    start_day = pd.Timestamp(start).normalize()
    end_day = pd.Timestamp(end).normalize()
    symbol_filter = set(symbols)
    sessions: dict[str, set[pd.Timestamp]] = {}
    for row in daily.itertuples(index=False):
        symbol = str(getattr(row, "stock_code", ""))
        if symbol not in symbol_filter:
            continue
        run_start = _optional_timestamp(getattr(row, "start_at", pd.NaT))
        run_end = _optional_timestamp(getattr(row, "end_at", pd.NaT))
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        session_start = max(start_day, run_start.normalize())
        session_end = min(end_day, run_end.normalize())
        if session_start > session_end:
            continue
        if session_start == session_end and session_start.weekday() >= 5:
            sessions.setdefault(symbol, set()).add(session_start)
    return {symbol: sorted(values) for symbol, values in sessions.items()}


def _fast_audit_from_metadata(
    catalog: pd.DataFrame,
    coverage: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframe: str,
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
) -> pd.DataFrame:
    start_ts, end_ts = _audit_window_for_timeframe(timeframe, start=start, end=end)
    by_symbol = {
        str(row.stock_code): row
        for row in catalog.loc[catalog["timeframe"].astype(str).eq(timeframe)].itertuples(index=False)
    } if not catalog.empty else {}
    coverage_by_symbol = _coverage_runs_by_symbol(coverage, timeframe=timeframe)
    coverage_keys = _read_coverage_keys_for_fast_audit(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframe=timeframe,
        coverage=coverage,
    )
    expected_cache: dict[object, object] = {}
    rows = [
        _fast_audit_row_from_metadata(
            row=by_symbol.get(symbol),
            coverage_runs=coverage_by_symbol.get(symbol, []),
            coverage_index_exists=(symbol, timeframe) in coverage_keys,
            data_root=data_root,
            symbol=symbol,
            timeframe=timeframe,
            adjust=adjust,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions=expected_sessions_by_symbol.get(symbol),
            expected_cache=expected_cache,
        )
        for symbol in symbols
    ]
    return pd.DataFrame(rows)


def _coverage_runs_by_symbol(coverage: pd.DataFrame, *, timeframe: str) -> dict[str, list[object]]:
    if coverage.empty:
        return {}
    result: dict[str, list[object]] = {}
    scoped = coverage.loc[coverage["timeframe"].astype(str).eq(timeframe)].copy()
    for row in scoped.itertuples(index=False):
        result.setdefault(str(getattr(row, "stock_code", "")), []).append(row)
    return result


def _read_coverage_keys_for_fast_audit(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframe: str,
    coverage: pd.DataFrame,
) -> set[tuple[str, str]]:
    keys = {
        (str(getattr(row, "stock_code", "")), str(getattr(row, "timeframe", "")))
        for row in coverage.loc[coverage["timeframe"].astype(str).eq(timeframe)].itertuples(index=False)
    } if not coverage.empty else set()
    if len(keys) >= len(set(symbols)):
        return keys
    try:
        keys.update(
            query_coverage_keys(
                data_root=data_root,
                symbols=tuple(symbols),
                adjust=adjust,
                timeframes=(timeframe,),
                read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
            )
        )
    except Exception:  # noqa: BLE001
        return keys
    return keys


def _fast_audit_row_from_metadata(
    *,
    row: object | None,
    coverage_runs: list[object],
    coverage_index_exists: bool,
    data_root: str | Path,
    symbol: str,
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: list[pd.Timestamp] | None,
    expected_cache: dict[object, object],
) -> dict[str, object]:
    path = (
        str(getattr(row, "path", ""))
        if row is not None
        else str(resolve_timeframe_root(data_root, timeframe) / adjust / f"{symbol}.parquet")
    )
    base = {
        "stock_code": symbol,
        "timeframe": timeframe,
        "adjust": adjust,
        "exists": row is not None and str(getattr(row, "status", "")) != "missing_file",
        "requested_start": start_ts,
        "requested_end": end_ts,
        "path": path,
    }
    if row is None:
        return _fast_audit_record(base, status="missing_index", message="本地文件索引缺失；预览未扫描 parquet 数据文件。")

    status = str(getattr(row, "status", ""))
    rows_total = _safe_int(getattr(row, "rows", 0))
    missing_columns = str(getattr(row, "missing_columns", ""))
    if status != "cached":
        return _fast_audit_record(
            base,
            status=status or "missing_file",
            rows_total=rows_total,
            missing_columns=missing_columns,
            message=str(getattr(row, "message", "")),
        )
    if not coverage_runs:
        if ensure_supported_timeframe(timeframe) != "1d":
            coverage = _coverage_runs_window_coverage(
                timeframe=timeframe,
                start_ts=start_ts,
                end_ts=end_ts,
                coverage_runs=[],
                expected_sessions=expected_sessions,
                expected_cache=expected_cache,
            )
            local_start = _optional_timestamp(getattr(row, "start_at", pd.NaT))
            local_end = _optional_timestamp(getattr(row, "end_at", pd.NaT))
            if not pd.isna(local_start):
                coverage["start"] = local_start
            if not pd.isna(local_end):
                coverage["end"] = local_end
            if coverage_index_exists:
                return _fast_audit_record(
                    base,
                    status="no_window_data",
                    rows_total=rows_total,
                    missing_columns=missing_columns,
                    **coverage,
                    message="本地覆盖索引已建立，但请求窗口内无 K 线；将按窗口补齐或由低周期派生。",
                )
            return _fast_audit_record(
                base,
                status="coverage_unknown",
                rows_total=rows_total,
                missing_columns=missing_columns,
                **coverage,
                message="分钟线精准覆盖索引缺失；不能确认窗口内 K 线完整，将按请求窗口补齐。",
            )
        fallback_runs = _catalog_boundary_coverage_runs(row)
        coverage = _coverage_runs_window_coverage(
            timeframe=timeframe,
            start_ts=start_ts,
            end_ts=end_ts,
            coverage_runs=fallback_runs,
            expected_sessions=expected_sessions,
            expected_cache=expected_cache,
        )
        if fallback_runs and coverage["rows_in_window"] > 0:
            return _fast_audit_record(
                base,
                status="ok",
                rows_total=rows_total,
                missing_columns=missing_columns,
                **coverage,
                message="本地精准覆盖索引缺失；已按 catalog 起止边界粗略判断，建议后台刷新覆盖索引。",
            )
        return _fast_audit_record(
            base,
            status="no_window_data",
            rows_total=rows_total,
            missing_columns=missing_columns,
            **coverage,
            message="本地覆盖索引为空，将按请求窗口补齐。",
        )

    coverage = _coverage_runs_window_coverage(
        timeframe=timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        coverage_runs=coverage_runs,
        expected_sessions=expected_sessions,
        expected_cache=expected_cache,
    )
    if coverage["rows_in_window"] <= 0:
        return _fast_audit_record(
            base,
            status="no_window_data",
            rows_total=rows_total,
            **coverage,
            message="请求窗口内无数据。",
        )
    return _fast_audit_record(
        base,
        status="ok",
        rows_total=rows_total,
        **coverage,
        message="metadata-only 预览：已按本地索引判断覆盖范围，未读取 parquet 数据页。",
    )


def _catalog_boundary_coverage_runs(row: object | None) -> list[object]:
    if row is None:
        return []
    start_at = _optional_timestamp(getattr(row, "start_at", pd.NaT))
    end_at = _optional_timestamp(getattr(row, "end_at", pd.NaT))
    if pd.isna(start_at) or pd.isna(end_at):
        return []
    return [row]


def _coverage_runs_window_coverage(
    *,
    timeframe: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    coverage_runs: list[object],
    expected_sessions: list[pd.Timestamp] | None,
    expected_cache: dict[object, object],
) -> dict[str, object]:
    window = _expected_coverage_window(
        timeframe=timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
        expected_cache=expected_cache,
    )
    if window.expected_rows <= 0:
        return {
            "rows_in_window": 0,
            "expected_rows": 0,
            "missing_rows": 0,
            "coverage_ratio": 0.0,
            "max_missing_gap_minutes": 0,
            "first_missing_at": pd.NaT,
            "last_missing_at": pd.NaT,
            "max_missing_gap_start_at": pd.NaT,
            "max_missing_gap_end_at": pd.NaT,
            "start": pd.NaT,
            "end": pd.NaT,
            "expected_timestamps": [],
            "missing_timestamps": [],
            "missing_windows": (),
        }
    available_rows, available_start, available_end, missing_windows = _coverage_window_diff(
        window,
        coverage_runs=coverage_runs,
    )
    missing_rows = max(int(window.expected_rows) - int(available_rows), 0)
    missing_summary = _missing_windows_summary(missing_windows, minutes=window.minutes)
    return {
        "rows_in_window": int(available_rows),
        "expected_rows": int(window.expected_rows),
        "missing_rows": int(missing_rows),
        "coverage_ratio": round(available_rows / window.expected_rows, 12),
        "start": available_start,
        "end": available_end,
        "expected_timestamps": [],
        "missing_timestamps": [],
        "missing_windows": missing_windows,
        **missing_summary,
    }


def _expected_coverage_window(
    *,
    timeframe: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: list[pd.Timestamp] | None,
    expected_cache: dict[object, object],
) -> _ExpectedCoverageWindow:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    sessions_key = _coverage_sessions_key(start_ts=start_ts, end_ts=end_ts, expected_sessions=expected_sessions)
    cache_key = ("coverage_window", normalized_timeframe, sessions_key)
    cached = expected_cache.get(cache_key)
    if isinstance(cached, _ExpectedCoverageWindow):
        return cached
    session_dates = _task_trading_session_dates(start_ts=start_ts, end_ts=end_ts, expected_sessions=expected_sessions)
    if normalized_timeframe == "1d":
        step = pd.Timedelta(days=1)
        segments = tuple((session, session) for session in session_dates)
        expected_rows = len(segments)
    else:
        minutes = int(normalized_timeframe.removesuffix("m"))
        step = pd.Timedelta(minutes=minutes)
        segments = tuple(
            segment
            for session in session_dates
            for segment in _intraday_expected_segments(session, minutes=minutes, start_ts=start_ts, end_ts=end_ts)
        )
        expected_rows = sum(_segment_row_count(start, end, step=step) for start, end in segments)
    minutes = 1440 if normalized_timeframe == "1d" else int(normalized_timeframe.removesuffix("m"))
    segments_by_day: dict[pd.Timestamp, tuple[tuple[pd.Timestamp, pd.Timestamp], ...]] = {}
    for start, end in segments:
        day = start.normalize()
        segments_by_day.setdefault(day, ())
        segments_by_day[day] = (*segments_by_day[day], (start, end))
    window = _ExpectedCoverageWindow(
        timeframe=normalized_timeframe,
        minutes=minutes,
        step=step,
        segments=segments,
        segments_by_day=segments_by_day,
        expected_rows=int(expected_rows),
    )
    expected_cache[cache_key] = window
    return window


def _coverage_sessions_key(
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: list[pd.Timestamp] | None,
) -> tuple[pd.Timestamp, ...]:
    if not expected_sessions:
        return (pd.Timestamp(start_ts), pd.Timestamp(end_ts))
    session_dates = pd.to_datetime(list(expected_sessions), errors="coerce")
    normalized = tuple(pd.Timestamp(item).normalize() for item in session_dates if not pd.isna(item))
    return (pd.Timestamp(start_ts), pd.Timestamp(end_ts), *normalized)


def _task_trading_session_dates(
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: list[pd.Timestamp] | None,
) -> tuple[pd.Timestamp, ...]:
    start_day = start_ts.normalize()
    end_day = end_ts.normalize()
    task_sessions = [pd.Timestamp(item).normalize() for item in pd.bdate_range(start_day, end_day)]
    if expected_sessions:
        task_sessions.extend(
            pd.Timestamp(item).normalize()
            for item in pd.to_datetime(list(expected_sessions), errors="coerce")
            if not pd.isna(item)
        )
    return tuple(sorted(set(task_sessions)))


def _intraday_expected_segments(
    session: pd.Timestamp,
    *,
    minutes: int,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
    step = pd.Timedelta(minutes=minutes)
    segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start_label, end_label in (("09:30", "11:30"), ("13:00", "15:00")):
        segment_base = pd.Timestamp(f"{session.date()} {start_label}")
        segment_start = segment_base + step
        segment_end = pd.Timestamp(f"{session.date()} {end_label}")
        segment_start = max(segment_start, start_ts)
        segment_end = min(segment_end, end_ts)
        aligned_start = _ceil_to_expected_bar(segment_start, base=segment_base, minutes=minutes)
        if aligned_start <= segment_end:
            segments.append((aligned_start, segment_end))
    return tuple(segments)


def _ceil_to_expected_bar(value: pd.Timestamp, *, base: pd.Timestamp, minutes: int) -> pd.Timestamp:
    step_ns = pd.Timedelta(minutes=minutes).value
    delta_ns = pd.Timestamp(value).value - base.value
    if delta_ns <= 0:
        return base + pd.Timedelta(minutes=minutes)
    remainder = delta_ns % step_ns
    return pd.Timestamp(value) if remainder == 0 else pd.Timestamp(value) + pd.Timedelta(step_ns - remainder)


def _coverage_window_diff(
    window: _ExpectedCoverageWindow,
    *,
    coverage_runs: list[object],
) -> tuple[int, pd.Timestamp, pd.Timestamp, tuple[tuple[pd.Timestamp, pd.Timestamp, int], ...]]:
    available_segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    expected_segments = window.segments
    if not expected_segments:
        return 0, pd.NaT, pd.NaT, ()
    run_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for run in coverage_runs:
        run_start = _optional_timestamp(getattr(run, "start_at", pd.NaT))
        run_end = _optional_timestamp(getattr(run, "end_at", pd.NaT))
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        if window.timeframe == "1d":
            run_start = run_start.normalize()
            run_end = run_end.normalize()
        if run_start <= expected_segments[-1][1] and run_end >= expected_segments[0][0]:
            run_intervals.append((run_start, run_end))
    if not run_intervals:
        missing_windows = _missing_windows_from_available(window, ())
        return 0, pd.NaT, pd.NaT, missing_windows
    expected_index = 0
    for run_start, run_end in sorted(run_intervals, key=lambda item: (item[0], item[1])):
        while expected_index < len(expected_segments) and expected_segments[expected_index][1] < run_start:
            expected_index += 1
        check_index = expected_index
        while check_index < len(expected_segments):
            expected_start, expected_end = expected_segments[check_index]
            if expected_start > run_end:
                break
            overlap_start = max(expected_start, run_start)
            overlap_end = min(expected_end, run_end)
            overlap_start = _ceil_segment_start(overlap_start, expected_start=expected_start, step=window.step)
            if overlap_start <= overlap_end:
                available_segments.append((overlap_start, overlap_end))
            check_index += 1
    merged_available = _merge_segments(available_segments)
    available_rows = sum(_segment_row_count(start, end, step=window.step) for start, end in merged_available)
    missing_windows = _missing_windows_from_available(window, merged_available)
    available_start = merged_available[0][0] if merged_available else pd.NaT
    available_end = merged_available[-1][1] if merged_available else pd.NaT
    return int(available_rows), available_start, available_end, missing_windows


def _ceil_segment_start(value: pd.Timestamp, *, expected_start: pd.Timestamp, step: pd.Timedelta) -> pd.Timestamp:
    current = pd.Timestamp(value)
    if current <= expected_start:
        return expected_start
    delta_ns = current.value - expected_start.value
    step_ns = step.value
    remainder = delta_ns % step_ns
    return current if remainder == 0 else current + pd.Timedelta(step_ns - remainder)


def _segment_row_count(start: pd.Timestamp, end: pd.Timestamp, *, step: pd.Timedelta) -> int:
    if start > end:
        return 0
    return int(((end.value - start.value) // step.value) + 1)


def _merge_segments(
    segments: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
    if not segments:
        return ()
    ordered = sorted(segments, key=lambda item: (item[0], item[1]))
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _missing_windows_from_available(
    window: _ExpectedCoverageWindow,
    available: tuple[tuple[pd.Timestamp, pd.Timestamp], ...],
) -> tuple[tuple[pd.Timestamp, pd.Timestamp, int], ...]:
    missing: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    available_index = 0
    for expected_start, expected_end in window.segments:
        cursor = expected_start
        while available_index < len(available) and available[available_index][1] < expected_start:
            available_index += 1
        check_index = available_index
        while check_index < len(available):
            available_start, available_end = available[check_index]
            if available_start > expected_end:
                break
            if available_start > cursor:
                gap_end = min(expected_end, available_start - window.step)
                _append_missing_window(missing, cursor, gap_end, window=window)
            if available_end >= cursor:
                cursor = available_end + window.step
                shifted_lunch_previous = available_end.normalize() + pd.Timedelta(hours=11, minutes=30 - window.minutes)
                if available_end == shifted_lunch_previous:
                    cursor = available_end.normalize() + pd.Timedelta(hours=13, minutes=window.minutes)
            if cursor > expected_end:
                break
            check_index += 1
        if cursor <= expected_end:
            _append_missing_window(missing, cursor, expected_end, window=window)
    return tuple(missing)


def _append_missing_window(
    missing: list[tuple[pd.Timestamp, pd.Timestamp, int]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    window: _ExpectedCoverageWindow,
) -> None:
    if start > end:
        return
    row_count = _segment_row_count(start, end, step=window.step)
    if not missing:
        missing.append((start, end, row_count))
        return
    previous_start, previous_end, previous_rows = missing[-1]
    if _coverage_timestamps_are_adjacent(previous_end, start, window=window):
        missing[-1] = (previous_start, end, previous_rows + row_count)
    else:
        missing.append((start, end, row_count))


def _coverage_timestamps_are_adjacent(
    previous: pd.Timestamp,
    current: pd.Timestamp,
    *,
    window: _ExpectedCoverageWindow,
) -> bool:
    if window.timeframe == "1d":
        previous_day = previous.normalize()
        current_day = current.normalize()
        if current_day <= previous_day:
            return False
        gap_days = (current_day - previous_day).days
        if gap_days == 1:
            return previous_day.weekday() < 4
        if gap_days == 3:
            return previous_day.weekday() == 4 and current_day.weekday() == 0
        return False
    if current - previous == window.step:
        return True
    lunch_shifted_previous = current.normalize() + pd.Timedelta(hours=11, minutes=30 - window.minutes)
    lunch_shifted_current = current.normalize() + pd.Timedelta(hours=13)
    if previous == lunch_shifted_previous and current == lunch_shifted_current:
        return True
    afternoon_first = current.normalize() + pd.Timedelta(hours=13, minutes=window.minutes)
    return bool(previous.strftime("%H:%M") == "11:30" and current == afternoon_first)


def _missing_windows_summary(
    missing_windows: tuple[tuple[pd.Timestamp, pd.Timestamp, int], ...],
    *,
    minutes: int,
) -> dict[str, object]:
    if not missing_windows:
        return {
            "max_missing_gap_minutes": 0,
            "first_missing_at": pd.NaT,
            "last_missing_at": pd.NaT,
            "max_missing_gap_start_at": pd.NaT,
            "max_missing_gap_end_at": pd.NaT,
        }
    max_gap = max(missing_windows, key=lambda item: item[2])
    return {
        "max_missing_gap_minutes": int(max_gap[2] * minutes),
        "first_missing_at": missing_windows[0][0],
        "last_missing_at": missing_windows[-1][1],
        "max_missing_gap_start_at": max_gap[0],
        "max_missing_gap_end_at": max_gap[1],
    }


def _fast_audit_record(base: dict[str, object], **overrides: object) -> dict[str, object]:
    record = {
        **base,
        "status": "",
        "rows_total": 0,
        "rows_in_window": 0,
        "expected_rows": 0,
        "missing_rows": 0,
        "coverage_ratio": 0.0,
        "max_missing_gap_minutes": 0,
        "first_missing_at": pd.NaT,
        "last_missing_at": pd.NaT,
        "max_missing_gap_start_at": pd.NaT,
        "max_missing_gap_end_at": pd.NaT,
        "start": pd.NaT,
        "end": pd.NaT,
        "invalid_date_rows": 0,
        "invalid_symbol_rows": 0,
        "duplicate_rows": 0,
        "null_ohlc_rows": 0,
        "non_positive_price_rows": 0,
        "inconsistent_ohlc_rows": 0,
        "null_volume_amount_rows": 0,
        "zero_volume_amount_rows": 0,
        "negative_volume_amount_rows": 0,
        "missing_columns": "",
        "message": "",
        "expected_timestamps": [],
        "missing_timestamps": [],
        "missing_windows": (),
    }
    record.update(overrides)
    return record


def _safe_int(value: object) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _plan_audits_by_timeframe(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
) -> dict[str, pd.DataFrame]:
    def audit_timeframe(timeframe: str) -> tuple[str, pd.DataFrame]:
        return timeframe, audit_local_data(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )

    if len(timeframes) <= 1 or len(symbols) < PLAN_PARALLEL_SYMBOL_THRESHOLD:
        return dict(audit_timeframe(timeframe) for timeframe in timeframes)
    max_workers = min(len(timeframes), PLAN_PARALLEL_MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tdx-plan") as executor:
        return dict(executor.map(audit_timeframe, timeframes))


def prepare_tdx_backtest_data(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    timeframes: tuple[str, ...] | list[str],
    start: str,
    end: str,
    tqcenter_path: str = "",
    tq_client: Any | None = None,
    batch_size: int = 100,
    progress_callback: ProgressCallback | None = None,
    min_coverage_ratio: float | None = None,
    strict_after_update: bool = True,
) -> pd.DataFrame:
    """按审计结果补齐 TDX K 线；只请求缺失、坏数据或覆盖不足的标的周期。"""
    normalized_timeframes = _timeframes_with_daily_dependency(timeframes)
    if not normalized_timeframes:
        raise ValueError("timeframes 不能为空。")
    normalized_symbols = unique_symbols(tuple(symbols))
    min_coverage_ratio = _normalize_min_coverage_ratio(min_coverage_ratio)
    processing_timeframes = (["1d"] if "1d" in normalized_timeframes else []) + [
        timeframe for timeframe in normalized_timeframes if timeframe != "1d"
    ]
    expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
        data_root=data_root,
        adjust=adjust,
        symbols=normalized_symbols,
        timeframes=processing_timeframes,
        start=start,
        end=end,
        progress_callback=progress_callback,
        refresh_index=False,
    )
    derived_targets_by_source = _derivable_targets_by_source(processing_timeframes)
    source_timeframes = [
        timeframe
        for timeframe in processing_timeframes
        if timeframe not in {target for targets in derived_targets_by_source.values() for target in targets}
    ]

    before_audits: dict[str, pd.DataFrame] = {}
    after_audits: dict[str, pd.DataFrame] = {}
    write_summaries: dict[str, pd.DataFrame] = {}
    fetch_symbols_by_timeframe: dict[str, list[str]] = {}

    for step_index, timeframe in enumerate(source_timeframes, start=1):
        _emit_progress(
            progress_callback,
            stage="audit_start",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
        )
        before = _fast_prepare_audit(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=normalized_symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
            refresh_index=False,
        )
        before = _bootstrap_unknown_coverage_for_download(
            before,
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
            progress_callback=progress_callback,
        )
        before_audits[timeframe] = before
        _emit_progress(
            progress_callback,
            stage="audit_done",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
            row_count=len(before),
        )
        fetch_groups = _fetch_window_groups_from_audit(
            before,
            min_coverage_ratio=min_coverage_ratio,
            max_symbols_per_group=batch_size,
            data_root=data_root,
            adjust=adjust,
            start=start,
            end=end,
        )
        fetch_symbols = list(dict.fromkeys(symbol for group in fetch_groups for symbol in group.symbols))
        fetch_symbols_by_timeframe[timeframe] = fetch_symbols
        if fetch_symbols:
            write_summaries[timeframe] = _update_fetch_window_groups_from_tdx(
                data_root=data_root,
                adjust=adjust,
                timeframe=timeframe,
                groups=fetch_groups,
                tqcenter_path=tqcenter_path,
                tq_client=tq_client,
                batch_size=batch_size,
                progress_callback=progress_callback,
            )
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                before_audits[target_timeframe] = _fast_prepare_audit(
                    data_root=data_root,
                    timeframe=target_timeframe,
                    adjust=adjust,
                    symbols=normalized_symbols,
                    start=start,
                    end=end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    refresh_index=False,
                )
                target_symbols = _symbols_requiring_update(
                    before_audits[target_timeframe],
                    min_coverage_ratio=min_coverage_ratio,
                )
                derive_symbols = tuple(dict.fromkeys([*fetch_symbols, *target_symbols]))
                write_summaries[target_timeframe] = _derive_timeframe_from_local_source(
                    data_root=data_root,
                    adjust=adjust,
                    source_timeframe=timeframe,
                    target_timeframe=target_timeframe,
                    symbols=derive_symbols,
                    start=start,
                    end=end,
                    progress_callback=progress_callback,
                )
                fetch_symbols_by_timeframe[target_timeframe] = list(derive_symbols)
            _emit_progress(
                progress_callback,
                stage="reaudit_start",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(source_timeframes),
            )
            after_audits[timeframe] = _merge_partial_after_audit(
                before=before,
                partial=_post_update_audit(
                    data_root=data_root,
                    timeframe=timeframe,
                    adjust=adjust,
                    symbols=fetch_symbols if strict_after_update else normalized_symbols,
                    start=start,
                    end=end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    strict=strict_after_update,
                ),
            )
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                after_audits[target_timeframe] = _merge_partial_after_audit(
                    before=before_audits[target_timeframe],
                    partial=_post_update_audit(
                        data_root=data_root,
                        timeframe=target_timeframe,
                        adjust=adjust,
                        symbols=fetch_symbols_by_timeframe[target_timeframe] if strict_after_update else normalized_symbols,
                        start=start,
                        end=end,
                        expected_sessions_by_symbol=expected_sessions_by_symbol,
                        strict=strict_after_update,
                    ),
                )
            _emit_progress(
                progress_callback,
                stage="reaudit_done",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(source_timeframes),
                row_count=len(after_audits[timeframe]),
            )
        else:
            write_summaries[timeframe] = pd.DataFrame()
            after_audits[timeframe] = before
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                before_audits[target_timeframe] = _fast_prepare_audit(
                    data_root=data_root,
                    timeframe=target_timeframe,
                    adjust=adjust,
                    symbols=normalized_symbols,
                    start=start,
                    end=end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    refresh_index=False,
                )
                derive_symbols = tuple(
                    _symbols_requiring_update(
                        before_audits[target_timeframe],
                        min_coverage_ratio=min_coverage_ratio,
                    )
                )
                if derive_symbols:
                    write_summaries[target_timeframe] = _derive_timeframe_from_local_source(
                        data_root=data_root,
                        adjust=adjust,
                        source_timeframe=timeframe,
                        target_timeframe=target_timeframe,
                        symbols=derive_symbols,
                        start=start,
                        end=end,
                        progress_callback=progress_callback,
                    )
                    after_audits[target_timeframe] = _merge_partial_after_audit(
                        before=before_audits[target_timeframe],
                        partial=_post_update_audit(
                            data_root=data_root,
                            timeframe=target_timeframe,
                            adjust=adjust,
                            symbols=list(derive_symbols) if strict_after_update else normalized_symbols,
                            start=start,
                            end=end,
                            expected_sessions_by_symbol=expected_sessions_by_symbol,
                            strict=strict_after_update,
                        ),
                    )
                    fetch_symbols_by_timeframe[target_timeframe] = list(derive_symbols)
                else:
                    write_summaries[target_timeframe] = pd.DataFrame()
                    after_audits[target_timeframe] = before_audits[target_timeframe]
                    fetch_symbols_by_timeframe[target_timeframe] = []
            _emit_progress(
                progress_callback,
                stage="fetch_skipped",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(source_timeframes),
                reason="local_ok",
            )
        if timeframe == "1d":
            expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
                data_root=data_root,
                adjust=adjust,
                symbols=normalized_symbols,
                timeframes=processing_timeframes,
                start=start,
                end=end,
                progress_callback=progress_callback,
                refresh_index=False,
            )

    after_all = pd.concat(after_audits.values(), ignore_index=True) if after_audits else pd.DataFrame(columns=AUDIT_COLUMNS)
    _record_unresolved_gaps_after_fetch(
        data_root=data_root,
        adjust=adjust,
        before_audits=before_audits,
        after_audits=after_audits,
        write_summaries=write_summaries,
        fetched_symbols_by_timeframe=fetch_symbols_by_timeframe,
    )
    if strict_after_update:
        _raise_for_failed_data_audit(after_all, min_coverage_ratio=min_coverage_ratio)

    rows: list[dict[str, object]] = []
    for timeframe in normalized_timeframes:
        rows.extend(
            _prepare_summary_rows(
                before=before_audits[timeframe],
                after=after_audits[timeframe],
                write_summary=write_summaries[timeframe],
                fetched_symbols=set(fetch_symbols_by_timeframe[timeframe]),
                min_coverage_ratio=min_coverage_ratio,
            )
        )
    result = pd.DataFrame(rows, columns=PREPARE_COLUMNS)
    result = _apply_unresolved_gaps_to_prepare_result(
        result,
        data_root=data_root,
        adjust=adjust,
        symbols=normalized_symbols,
        timeframes=normalized_timeframes,
        start=start,
        end=end,
    )
    _emit_progress(
        progress_callback,
        stage="prepare_done",
        row_count=len(result),
        fetched_count=int(result["action"].eq("fetched").sum()) if "action" in result.columns else 0,
    )
    return result


def _timeframes_with_daily_dependency(timeframes: tuple[str, ...] | list[str]) -> list[str]:
    """TDX 回测数据准备自动带上日 K；日 K 是分钟覆盖锚点和涨停开盘过滤依赖。"""
    normalized = _unique_timeframes(timeframes)
    if not normalized:
        return normalized
    if any(timeframe != "1d" for timeframe in normalized) and "1d" not in normalized:
        return ["1d", *normalized]
    return normalized


def _derivable_targets_by_source(timeframes: list[str]) -> dict[str, tuple[str, ...]]:
    if "5m" not in timeframes:
        return {}
    targets = tuple(timeframe for timeframe in timeframes if timeframe in {"15m", "30m", "60m"})
    return {"5m": targets} if targets else {}


def _fast_expected_sessions_by_symbol(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    timeframes: list[str],
    start: str,
    end: str,
    progress_callback: ProgressCallback | None = None,
    refresh_index: bool = True,
) -> dict[str, list[pd.Timestamp]]:
    _emit_progress(
        progress_callback,
        stage="daily_sessions_start",
        timeframe="1d",
        symbol_count=len(symbols),
        message="开始读取日 K 覆盖索引，补充特殊交易日锚点。",
    )
    coverage_query = _fresh_coverage_for_plan if refresh_index else _read_coverage_for_plan
    coverage = coverage_query(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=list(dict.fromkeys(["1d", *timeframes])),
        start=start,
        end=end,
    )
    sessions = _daily_sessions_from_catalog(coverage, symbols=symbols, start=start, end=end)
    _emit_progress(
        progress_callback,
        stage="daily_sessions_done",
        timeframe="1d",
        symbol_count=len(symbols),
        exceptional_symbol_count=len(sessions),
        row_count=sum(len(items) for items in sessions.values()),
        message=f"交易日锚点已建立：默认工作日历 + {len(sessions)} 个标的的特殊交易日。",
    )
    return sessions


def _fast_prepare_audit(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: list[str],
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
    refresh_index: bool = True,
) -> pd.DataFrame:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    catalog_query = _fresh_catalog_for_plan if refresh_index else _read_catalog_for_plan
    coverage_query = _fresh_coverage_for_plan if refresh_index else _read_coverage_for_plan
    catalog = catalog_query(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=[normalized_timeframe],
    )
    coverage = coverage_query(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframes=[normalized_timeframe],
        start=start,
        end=end,
    )
    return _fast_audit_from_metadata(
        catalog,
        coverage,
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        timeframe=normalized_timeframe,
        start=start,
        end=end,
        expected_sessions_by_symbol=expected_sessions_by_symbol,
    )


def _bootstrap_unknown_coverage_for_download(
    audit: pd.DataFrame,
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
    progress_callback: ProgressCallback | None,
) -> pd.DataFrame:
    if audit.empty or "status" not in audit.columns:
        return audit
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    if normalized_timeframe == "1d":
        return audit
    unknown_symbols = tuple(
        str(row.stock_code)
        for row in audit.loc[audit["status"].astype(str).eq("coverage_unknown")].itertuples(index=False)
        if str(getattr(row, "stock_code", ""))
    )
    if not unknown_symbols:
        return audit
    started_at = time.perf_counter()
    _emit_progress(
        progress_callback,
        stage="coverage_bootstrap_start",
        timeframe=normalized_timeframe,
        symbol_count=len(unknown_symbols),
        message=f"分钟线覆盖索引缺失，开始为 {normalized_timeframe} 初始化 {len(unknown_symbols)} 个标的。",
    )
    refresh_coverage_runs(
        data_root=data_root,
        adjust=adjust,
        timeframes=(normalized_timeframe,),
        symbols=unknown_symbols,
    )
    refreshed = _fast_prepare_audit(
        data_root=data_root,
        timeframe=normalized_timeframe,
        adjust=adjust,
        symbols=list(unknown_symbols),
        start=start,
        end=end,
        expected_sessions_by_symbol=expected_sessions_by_symbol,
        refresh_index=False,
    )
    _emit_progress(
        progress_callback,
        stage="coverage_bootstrap_done",
        timeframe=normalized_timeframe,
        symbol_count=len(unknown_symbols),
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        message=f"分钟线覆盖索引初始化完成：{normalized_timeframe}，{len(unknown_symbols)} 个标的。",
    )
    if refreshed.empty:
        return audit
    return _merge_partial_after_audit(before=audit, partial=refreshed)


def _post_update_audit(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: list[str],
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
    strict: bool,
) -> pd.DataFrame:
    if strict:
        strict_audit = audit_local_data(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=symbols,
            start=start,
            end=end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
        )
        return strict_audit
    return _fast_prepare_audit(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
        expected_sessions_by_symbol=expected_sessions_by_symbol,
        refresh_index=False,
    )


def _merge_partial_after_audit(*, before: pd.DataFrame, partial: pd.DataFrame) -> pd.DataFrame:
    if before.empty or partial.empty:
        return before if partial.empty else partial
    key = ["stock_code", "timeframe", "adjust"]
    before_ordered = before.copy()
    before_ordered["_merge_order"] = range(len(before_ordered))
    partial_ordered = partial.copy()
    partial_ordered["_is_partial_update"] = True
    merged = pd.concat([before_ordered, partial_ordered], ignore_index=True, sort=False)
    merged["_is_partial_update"] = merged["_is_partial_update"].notna() & merged["_is_partial_update"].astype(object).eq(True)
    merged["_merge_order"] = pd.to_numeric(merged["_merge_order"], errors="coerce")
    merged["_merge_order"] = merged.groupby(key, sort=False)["_merge_order"].transform("min")
    result = (
        merged.sort_values(["_merge_order", "_is_partial_update"], kind="mergesort")
        .drop_duplicates(subset=key, keep="last")
        .sort_values("_merge_order", kind="mergesort")
        .drop(columns=["_merge_order", "_is_partial_update"], errors="ignore")
    )
    return result.loc[:, AUDIT_COLUMNS].reset_index(drop=True)


def _derive_timeframe_from_local_source(
    *,
    data_root: str | Path,
    adjust: str,
    source_timeframe: str,
    target_timeframe: str,
    symbols: tuple[str, ...],
    start: str,
    end: str,
    progress_callback: ProgressCallback | None,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    from tdx_downloader.data.tdx import aggregate_5m_bars_to_timeframe

    _emit_progress(
        progress_callback,
        stage="derive_start",
        timeframe=target_timeframe,
        source_timeframe=source_timeframe,
        symbol_count=len(symbols),
    )
    source_bars = load_local_bars(
        data_root=data_root,
        timeframe=source_timeframe,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
    )
    derived = aggregate_5m_bars_to_timeframe(source_bars, timeframe=target_timeframe, start=start, end=end)
    result = write_local_bars(
        data_root=data_root,
        timeframe=target_timeframe,
        adjust=adjust,
        bars=derived,
        refresh_coverage=False,
    )
    partial_coverage = upsert_partial_coverage_runs_from_bars(
        data_root=data_root,
        timeframe=target_timeframe,
        adjust=adjust,
        bars=derived,
    )
    _emit_progress(
        progress_callback,
        stage="derive_done",
        timeframe=target_timeframe,
        source_timeframe=source_timeframe,
        rows=len(derived),
        coverage_rows=int(len(partial_coverage)),
    )
    return result


def _symbols_requiring_update(audit: pd.DataFrame, *, min_coverage_ratio: float | None) -> list[str]:
    if audit.empty:
        return []
    result: list[str] = []
    for row in audit.itertuples(index=False):
        if _audit_row_requires_tdx_update(row, min_coverage_ratio=min_coverage_ratio):
            symbol = str(getattr(row, "stock_code", "") or "")
            if symbol:
                result.append(symbol)
    return list(dict.fromkeys(result))


def _expected_sessions_by_symbol_from_daily(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: list[str],
    start: str,
    end: str,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, list[pd.Timestamp]]:
    start_day = pd.Timestamp(start).normalize()
    end_day = pd.Timestamp(end).normalize()
    _emit_progress(
        progress_callback,
        stage="daily_sessions_start",
        timeframe="1d",
        symbol_count=len(symbols),
        message="开始读取日 K 缓存，建立交易日覆盖锚点。",
    )
    daily = load_daily_bars(
        data_root=data_root,
        adjust=adjust,
        symbols=tuple(symbols),
        start=start_day,
        end=end_day,
    )
    sessions = daily_sessions_by_symbol(daily, start=start, end=end)
    _emit_progress(
        progress_callback,
        stage="daily_sessions_done",
        timeframe="1d",
        symbol_count=len(sessions),
        row_count=len(daily),
        message=f"交易日覆盖锚点已建立：{len(sessions)} 个标的，{len(daily)} 行日 K。",
    )
    return sessions


def _tdx_plan_rows(
    audit: pd.DataFrame,
    *,
    min_coverage_ratio: float | None,
    derived_from: str | None = None,
    source_audit: pd.DataFrame | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    source_by_symbol = _audit_rows_by_symbol(source_audit)
    for row in audit.itertuples(index=False):
        requires_fetch = _audit_row_requires_tdx_update(row, min_coverage_ratio=min_coverage_ratio)
        source_row = source_by_symbol.get(str(row.stock_code)) if derived_from else None
        source_requires_fetch = (
            _audit_row_requires_tdx_update(source_row, min_coverage_ratio=min_coverage_ratio)
            if source_row is not None
            else False
        )
        reason = _summary_before_status(row, min_coverage_ratio=min_coverage_ratio) if requires_fetch else "local_ok"
        action = "fetch" if requires_fetch else "cached"
        message = _tdx_plan_message(row, reason=reason)
        if derived_from and requires_fetch:
            action = "derive"
            reason = "derived_from_source" if source_requires_fetch else "derive_from_cached_source"
            message = _derived_plan_message(
                row,
                source_timeframe=derived_from,
                source_requires_fetch=source_requires_fetch,
            )
        rows.append(
            {
                "stock_code": str(row.stock_code),
                "timeframe": str(row.timeframe),
                "adjust": str(row.adjust),
                "action": action,
                "reason": reason,
                "catalog_status": _plan_catalog_status(row),
                "coverage_status": _plan_coverage_status(row, min_coverage_ratio=min_coverage_ratio),
                "before_status": _summary_before_status(row, min_coverage_ratio=min_coverage_ratio),
                "rows_in_window": int(row.rows_in_window),
                "expected_rows": int(row.expected_rows),
                "missing_rows": int(row.missing_rows),
                "coverage_ratio": float(row.coverage_ratio),
                "max_missing_gap_minutes": int(row.max_missing_gap_minutes),
                "first_missing_at": getattr(row, "first_missing_at"),
                "last_missing_at": getattr(row, "last_missing_at"),
                "max_missing_gap_start_at": getattr(row, "max_missing_gap_start_at"),
                "max_missing_gap_end_at": getattr(row, "max_missing_gap_end_at"),
                "path": str(row.path),
                "message": message,
            }
        )
    return rows


def _audit_rows_by_symbol(audit: pd.DataFrame | None) -> dict[str, object]:
    if audit is None or audit.empty:
        return {}
    return {str(row.stock_code): row for row in audit.itertuples(index=False)}


def _derived_plan_message(row: object, *, source_timeframe: str, source_requires_fetch: bool) -> str:
    target_timeframe = str(getattr(row, "timeframe", ""))
    target_status = _summary_before_status(row, min_coverage_ratio=None)
    if source_requires_fetch:
        return (
            f"{target_timeframe} 将由 {source_timeframe} 补齐后本地聚合生成；"
            f"不会单独请求 TDX。当前高周期状态：{target_status}。"
        )
    return (
        f"{target_timeframe} 将直接由本地 {source_timeframe} 聚合生成；"
        f"不会单独请求 TDX。当前高周期状态：{target_status}。"
    )


def _plan_catalog_status(row: object) -> str:
    status = str(getattr(row, "status", ""))
    if status in {"missing_index", "missing_file", "read_error", "missing_columns", "quality_error"}:
        return status
    return "cached" if bool(getattr(row, "exists", False)) else "missing_file"


def _plan_coverage_status(row: object, *, min_coverage_ratio: float | None) -> str:
    status = str(getattr(row, "status", ""))
    expected_rows = _audit_expected_rows(row)
    if status in {"missing_index", "missing_file"}:
        return "coverage_missing_index"
    if status == "coverage_unknown":
        return "coverage_unknown"
    if status != "ok":
        return "coverage_unavailable"
    if expected_rows <= 0:
        return "coverage_unknown"
    if _audit_row_has_missing_bars(row) or _audit_row_has_boundary_coverage_gap(row):
        return "coverage_partial"
    if min_coverage_ratio is not None and float(getattr(row, "coverage_ratio")) < float(min_coverage_ratio):
        return "coverage_below_min"
    return "coverage_ready"


def _audit_row_requires_tdx_update(row: object, *, min_coverage_ratio: float | None) -> bool:
    status = str(getattr(row, "status"))
    if status != "ok":
        return True
    if _audit_row_has_missing_bars(row):
        return True
    if _audit_row_has_boundary_coverage_gap(row):
        return True
    if min_coverage_ratio is None:
        return False
    expected_rows = int(getattr(row, "expected_rows"))
    coverage_ratio = float(getattr(row, "coverage_ratio"))
    return expected_rows > 0 and coverage_ratio < min_coverage_ratio


def _summary_before_status(row: object, *, min_coverage_ratio: float | None) -> str:
    status = str(getattr(row, "status"))
    if status != "ok":
        return status
    if _audit_row_has_missing_bars(row):
        return "coverage_gap"
    if _audit_row_has_boundary_coverage_gap(row):
        return "coverage_gap"
    if _audit_row_requires_tdx_update(row, min_coverage_ratio=min_coverage_ratio):
        return "coverage_below_min"
    return status


def _tdx_plan_message(row: object, *, reason: str) -> str:
    if reason != "coverage_gap":
        return str(getattr(row, "message", ""))
    missing_rows = _audit_missing_rows(row)
    if missing_rows > 0:
        first_missing = _format_optional_timestamp(getattr(row, "first_missing_at", pd.NaT))
        last_missing = _format_optional_timestamp(getattr(row, "last_missing_at", pd.NaT))
        return f"本地缓存缺失 {missing_rows} 根 K，缺口 {first_missing} 至 {last_missing}，将按缺口窗口补齐。"
    start = _format_optional_date(getattr(row, "start", pd.NaT))
    end = _format_optional_date(getattr(row, "end", pd.NaT))
    requested_start = _format_optional_date(getattr(row, "requested_start", pd.NaT))
    requested_end = _format_optional_date(getattr(row, "requested_end", pd.NaT))
    return f"本地缓存仅覆盖 {start} 至 {end}，未覆盖请求窗口 {requested_start} 至 {requested_end}，将请求 TDX 补齐。"


def _fetch_window_groups_from_audit(
    audit: pd.DataFrame,
    *,
    min_coverage_ratio: float | None,
    gap_episodes: pd.DataFrame | None = None,
    max_symbols_per_group: int | None = None,
    data_root: str | Path | None = None,
    adjust: str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> list[FetchWindowGroup]:
    episode_windows = _gap_episode_windows_by_symbol(gap_episodes)
    unresolved_by_key = _unresolved_records_for_audit_filter(
        audit,
        data_root=data_root,
        adjust=adjust,
        start=start,
        end=end,
    )
    groups: dict[tuple[str, str], list[str]] = {}
    for row in audit.itertuples(index=False):
        if not _audit_row_requires_tdx_update(row, min_coverage_ratio=min_coverage_ratio):
            continue
        key = (str(row.stock_code), str(row.timeframe), str(row.adjust))
        if _matching_unresolved_gap_records(row, unresolved_by_key.get(key, [])):
            continue
        symbol = str(row.stock_code)
        if str(getattr(row, "status", "")) == "coverage_unknown":
            windows = (_fetch_window_for_audit_row(row, min_coverage_ratio=min_coverage_ratio),)
        else:
            windows = episode_windows.get(symbol) or _fast_gap_windows_for_audit_row(row) or (
                _fetch_window_for_audit_row(row, min_coverage_ratio=min_coverage_ratio),
            )
        for start, end in windows:
            groups.setdefault((start, end), []).append(symbol)
    result: list[FetchWindowGroup] = []
    chunk_size = int(max_symbols_per_group or 0)
    for (start, end), symbols in groups.items():
        if chunk_size <= 0 or len(symbols) <= chunk_size:
            result.append(FetchWindowGroup(symbols=tuple(symbols), start=start, end=end))
            continue
        for index in range(0, len(symbols), chunk_size):
            result.append(FetchWindowGroup(symbols=tuple(symbols[index : index + chunk_size]), start=start, end=end))
    return result


def _unresolved_records_for_audit_filter(
    audit: pd.DataFrame,
    *,
    data_root: str | Path | None,
    adjust: str | None,
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> dict[tuple[str, str, str], list[object]]:
    if audit.empty or data_root is None or adjust is None:
        return {}
    symbols = tuple(str(value) for value in audit["stock_code"].dropna().astype(str).unique()) if "stock_code" in audit.columns else ()
    timeframes = tuple(str(value) for value in audit["timeframe"].dropna().astype(str).unique()) if "timeframe" in audit.columns else ()
    if not symbols or not timeframes:
        return {}
    query_start, query_end = _coverage_query_window_for_plan(
        timeframes=list(timeframes),
        start=start or pd.NaT,
        end=end or pd.NaT,
    )
    unresolved = query_unresolved_gaps(
        data_root=data_root,
        symbols=symbols,
        adjust=adjust,
        timeframes=timeframes,
        start=query_start,
        end=query_end,
        statuses=("provider_no_data", "provider_partial_gap", "provider_unresolved"),
        read_timeout_seconds=PLAN_FAST_READ_TIMEOUT_SECONDS,
    )
    result: dict[tuple[str, str, str], list[object]] = {}
    for row in unresolved.itertuples(index=False):
        key = (str(row.stock_code), str(row.timeframe), str(row.adjust))
        result.setdefault(key, []).append(row)
    return result


def _fast_gap_windows_for_audit_row(row: object) -> tuple[tuple[str, str], ...]:
    missing_windows = getattr(row, "missing_windows", None)
    if isinstance(missing_windows, (list, tuple)) and missing_windows:
        timeframe = str(getattr(row, "timeframe", ""))
        return tuple(
            (
                _fetch_window_label(timeframe, pd.Timestamp(start), is_end=False),
                _fetch_window_label(timeframe, pd.Timestamp(end), is_end=True),
            )
            for start, end, _rows in missing_windows
        )
    expected = getattr(row, "expected_timestamps", None)
    missing = getattr(row, "missing_timestamps", None)
    if not expected or not missing:
        return ()
    missing_set = {pd.Timestamp(item) for item in missing}
    timeframe = str(getattr(row, "timeframe", ""))
    minutes = 1440 if ensure_supported_timeframe(timeframe) == "1d" else int(timeframe.removesuffix("m"))
    windows: list[tuple[str, str]] = []
    gap_start = pd.NaT
    gap_end = pd.NaT
    missing_rows = 0
    for timestamp in expected:
        current = pd.Timestamp(timestamp)
        if current in missing_set:
            if missing_rows == 0:
                gap_start = current
            missing_rows += 1
            gap_end = current
            continue
        if missing_rows:
            windows.append(
                (
                    _fetch_window_label(timeframe, pd.Timestamp(gap_start), is_end=False),
                    _fetch_window_label(timeframe, pd.Timestamp(gap_end), is_end=True),
                )
            )
            gap_start = pd.NaT
            gap_end = pd.NaT
            missing_rows = 0
    if missing_rows:
        windows.append(
            (
                _fetch_window_label(timeframe, pd.Timestamp(gap_start), is_end=False),
                _fetch_window_label(timeframe, pd.Timestamp(gap_end), is_end=True),
            )
        )
    return tuple(windows)


def _split_gap_episodes_for_audit(
    audit: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    start: str,
    end: str,
    expected_sessions_by_symbol: dict[str, list[pd.Timestamp]],
) -> pd.DataFrame:
    split_symbols = [
        str(row.stock_code)
        for row in audit.itertuples(index=False)
        if str(getattr(row, "status", "")) == "ok" and _audit_row_has_multiple_missing_episodes(row)
    ]
    if not split_symbols:
        return pd.DataFrame(columns=DATA_GAP_EPISODE_COLUMNS)
    return data_gap_episodes(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=tuple(split_symbols),
        start=start,
        end=end,
        expected_sessions_by_symbol=expected_sessions_by_symbol,
    )


def _gap_episode_windows_by_symbol(gap_episodes: pd.DataFrame | None) -> dict[str, tuple[tuple[str, str], ...]]:
    if gap_episodes is None or gap_episodes.empty:
        return {}
    windows: dict[str, list[tuple[str, str]]] = {}
    for row in gap_episodes.itertuples(index=False):
        if str(getattr(row, "status", "")) != "missing_bars":
            continue
        symbol = str(getattr(row, "stock_code", ""))
        timeframe = str(getattr(row, "timeframe", ""))
        start_at = _optional_timestamp(getattr(row, "start_at", pd.NaT))
        end_at = _optional_timestamp(getattr(row, "end_at", pd.NaT))
        if not symbol or pd.isna(start_at) or pd.isna(end_at):
            continue
        windows.setdefault(symbol, []).append(
            (
                _fetch_window_label(timeframe, start_at, is_end=False),
                _fetch_window_label(timeframe, end_at, is_end=True),
            )
        )
    return {symbol: tuple(symbol_windows) for symbol, symbol_windows in windows.items()}


def _fetch_window_for_audit_row(row: object, *, min_coverage_ratio: float | None) -> tuple[str, str]:
    timeframe = str(getattr(row, "timeframe", ""))
    requested_start = _optional_timestamp(getattr(row, "requested_start", pd.NaT))
    requested_end = _optional_timestamp(getattr(row, "requested_end", pd.NaT))
    full_window = (
        _fetch_window_label(timeframe, requested_start, is_end=False),
        _fetch_window_label(timeframe, requested_end, is_end=True),
    )
    status = str(getattr(row, "status", ""))
    if status == "coverage_unknown":
        boundary_window = _tail_fetch_window_from_catalog_boundary(
            row,
            timeframe=timeframe,
            requested_start=requested_start,
            requested_end=requested_end,
        )
        return boundary_window or full_window
    if status != "ok":
        return full_window
    first_missing = _optional_timestamp(getattr(row, "first_missing_at", pd.NaT))
    last_missing = _optional_timestamp(getattr(row, "last_missing_at", pd.NaT))
    if not pd.isna(first_missing) and not pd.isna(last_missing):
        return (
            _fetch_window_label(timeframe, first_missing, is_end=False),
            _fetch_window_label(timeframe, last_missing, is_end=True),
        )
    return full_window


def _tail_fetch_window_from_catalog_boundary(
    row: object,
    *,
    timeframe: str,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
) -> tuple[str, str] | None:
    if ensure_supported_timeframe(timeframe) == "1d":
        return None
    local_start = _optional_timestamp(getattr(row, "start", pd.NaT))
    local_end = _optional_timestamp(getattr(row, "end", pd.NaT))
    if any(pd.isna(value) for value in (requested_start, requested_end, local_start, local_end)):
        return None
    if local_end >= requested_end:
        return None
    if local_start > requested_start + TDX_BOUNDARY_GAP_TOLERANCE:
        return None
    minutes = int(ensure_supported_timeframe(timeframe).removesuffix("m"))
    fetch_start = _next_intraday_fetch_start(
        max(requested_start, local_end + pd.Timedelta(minutes=minutes)),
        timeframe=timeframe,
        requested_end=requested_end,
    )
    if fetch_start > requested_end:
        return None
    return (
        _fetch_window_label(timeframe, fetch_start, is_end=False),
        _fetch_window_label(timeframe, requested_end, is_end=True),
    )


def _next_intraday_fetch_start(value: pd.Timestamp, *, timeframe: str, requested_end: pd.Timestamp) -> pd.Timestamp:
    minutes = int(ensure_supported_timeframe(timeframe).removesuffix("m"))
    current = pd.Timestamp(value)
    end = pd.Timestamp(requested_end)
    while current.normalize() <= end.normalize():
        day = current.normalize()
        if day.weekday() >= 5:
            current = (day + pd.offsets.BDay(1)).normalize() + pd.Timedelta(hours=9, minutes=30 + minutes)
            continue
        for start_label, end_label in (("09:30", "11:30"), ("13:00", "15:00")):
            session_start = pd.Timestamp(f"{day.date()} {start_label}")
            session_end = pd.Timestamp(f"{day.date()} {end_label}")
            first_bar = session_start + pd.Timedelta(minutes=minutes)
            candidate = max(current, first_bar)
            candidate = _ceil_to_expected_bar(candidate, base=session_start, minutes=minutes)
            if candidate <= session_end:
                return candidate
        current = (day + pd.Timedelta(days=1)) + pd.Timedelta(hours=9, minutes=30 + minutes)
    return current


def _fetch_window_label(timeframe: str, value: pd.Timestamp, *, is_end: bool) -> str:
    if pd.isna(value):
        return ""
    if ensure_supported_timeframe(timeframe) == "1d":
        return str(value.normalize().date())
    timestamp = value
    if is_end:
        timestamp = _missing_bar_fetch_end(str(timeframe), timestamp)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _missing_bar_fetch_end(timeframe: str, value: pd.Timestamp) -> pd.Timestamp:
    normalized = ensure_supported_timeframe(timeframe)
    if normalized == "1d":
        return value
    minutes = int(normalized.removesuffix("m"))
    return value + pd.Timedelta(minutes=minutes)


def _update_fetch_window_groups_from_tdx(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    groups: list[FetchWindowGroup],
    tqcenter_path: str,
    tq_client: Any | None,
    batch_size: int,
    progress_callback: ProgressCallback | None,
) -> pd.DataFrame:
    summaries: list[pd.DataFrame] = []
    for group in groups:
        summaries.append(
            update_from_tdx(
                data_root=data_root,
                adjust=adjust,
                symbols=group.symbols,
                timeframe=timeframe,
                start=group.start,
                end=group.end,
                tqcenter_path=tqcenter_path,
                tq_client=tq_client,
                batch_size=batch_size,
                progress_callback=progress_callback,
            )
        )
    if not summaries:
        return pd.DataFrame()
    merged = pd.concat(summaries, ignore_index=True)
    if merged.empty or "symbol" not in merged.columns:
        return merged
    aggregations: dict[str, object] = {
        "status": "last",
        "rows": "max",
        "new_rows": "sum",
        "path": "last",
        "start": "min",
        "end": "max",
        "message": "last",
    }
    return merged.groupby("symbol", as_index=False, sort=False).agg(aggregations)


def _audit_row_has_boundary_coverage_gap(row: object) -> bool:
    """已有缓存只覆盖请求窗口的近端时，不能用本地窗口内日期自证完整。"""
    if _audit_expected_rows(row) > 0 and _audit_missing_rows(row) <= 0:
        try:
            if float(getattr(row, "coverage_ratio", 0.0)) >= 1.0:
                return False
        except (TypeError, ValueError):
            pass
    rows_in_window = int(getattr(row, "rows_in_window", 0))
    if rows_in_window <= 0:
        return False
    start = _optional_timestamp(getattr(row, "start", pd.NaT))
    end = _optional_timestamp(getattr(row, "end", pd.NaT))
    requested_start = _optional_timestamp(getattr(row, "requested_start", pd.NaT))
    requested_end = _optional_timestamp(getattr(row, "requested_end", pd.NaT))
    if any(pd.isna(value) for value in (start, end, requested_start, requested_end)):
        return False
    end_gap = _audit_row_has_requested_end_gap(
        row,
        end=end,
        requested_end=requested_end,
    )
    return bool(
        start > requested_start + TDX_BOUNDARY_GAP_TOLERANCE
        or end_gap
    )


def _record_unresolved_gaps_after_fetch(
    *,
    data_root: str | Path,
    adjust: str,
    before_audits: dict[str, pd.DataFrame],
    after_audits: dict[str, pd.DataFrame],
    write_summaries: dict[str, pd.DataFrame],
    fetched_symbols_by_timeframe: dict[str, list[str]],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    clear_symbols_by_timeframe: dict[str, list[str]] = {}
    for timeframe, fetched_symbols in fetched_symbols_by_timeframe.items():
        fetched = set(fetched_symbols)
        if not fetched:
            continue
        after = after_audits.get(timeframe, pd.DataFrame())
        before = before_audits.get(timeframe, pd.DataFrame())
        write_summary = write_summaries.get(timeframe, pd.DataFrame())
        write_rows = _write_new_rows_by_symbol(write_summary)
        before_by_symbol = {str(row.stock_code): row for row in before.itertuples(index=False)} if not before.empty else {}
        for row in after.itertuples(index=False):
            symbol = str(getattr(row, "stock_code", "") or "")
            if symbol not in fetched:
                continue
            if _audit_row_requires_tdx_update(row, min_coverage_ratio=None):
                before_row = before_by_symbol.get(symbol, row)
                records.extend(
                    _unresolved_gap_records_from_audit_row(
                        row,
                        before_row=before_row,
                        last_fetch_rows=int(write_rows.get(symbol, 0)),
                    )
                )
            else:
                clear_symbols_by_timeframe.setdefault(timeframe, []).append(symbol)
    for timeframe, symbols in clear_symbols_by_timeframe.items():
        clear_unresolved_gaps(
            data_root=data_root,
            symbols=symbols,
            adjust=adjust,
            timeframes=(timeframe,),
            start=_clear_window_start(after_audits.get(timeframe, pd.DataFrame())),
            end=_clear_window_end(after_audits.get(timeframe, pd.DataFrame())),
        )
    if not records:
        return pd.DataFrame()
    return upsert_unresolved_gaps(data_root=data_root, records=pd.DataFrame(records))


def _write_new_rows_by_symbol(write_summary: pd.DataFrame) -> dict[str, int]:
    if write_summary.empty:
        return {}
    result: dict[str, int] = {}
    for row in write_summary.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "") or "")
        if not symbol:
            continue
        result[symbol] = result.get(symbol, 0) + _safe_int(getattr(row, "new_rows", 0))
    return result


def _unresolved_gap_records_from_audit_row(
    row: object,
    *,
    before_row: object,
    last_fetch_rows: int,
) -> list[dict[str, object]]:
    symbol = str(getattr(row, "stock_code", "") or "")
    timeframe = ensure_supported_timeframe(str(getattr(row, "timeframe", "")))
    adjust = str(getattr(row, "adjust", "") or "")
    if not symbol or not adjust:
        return []
    status = "provider_no_data" if int(last_fetch_rows) <= 0 else "provider_partial_gap"
    windows = _fast_gap_windows_for_audit_row(row)
    if not windows:
        first_missing = _optional_timestamp(getattr(row, "first_missing_at", pd.NaT))
        last_missing = _optional_timestamp(getattr(row, "last_missing_at", pd.NaT))
        if pd.isna(first_missing) or pd.isna(last_missing):
            first_missing = _optional_timestamp(getattr(row, "requested_start", pd.NaT))
            last_missing = _optional_timestamp(getattr(row, "requested_end", pd.NaT))
        if pd.isna(first_missing) or pd.isna(last_missing):
            return []
        windows = (
            (
                _fetch_window_label(timeframe, first_missing, is_end=False),
                _fetch_window_label(timeframe, last_missing, is_end=True),
            ),
        )
    missing_rows = max(_audit_missing_rows(row), 1)
    before_missing = _audit_missing_rows(before_row)
    message = (
        f"真实请求 TDX 后仍存在缺口：下载前缺 {before_missing} 根，"
        f"下载后缺 {missing_rows} 根，本次写入 {int(last_fetch_rows)} 根。"
    )
    return [
        {
            "stock_code": symbol,
            "timeframe": timeframe,
            "adjust": adjust,
            "start_at": pd.Timestamp(start),
            "end_at": pd.Timestamp(end),
            "missing_rows": missing_rows,
            "status": status,
            "last_fetch_rows": int(last_fetch_rows),
            "message": message,
        }
        for start, end in windows
    ]


def _clear_window_start(audit: pd.DataFrame) -> pd.Timestamp:
    if audit.empty or "requested_start" not in audit.columns:
        return pd.Timestamp("1900-01-01")
    value = pd.to_datetime(audit["requested_start"], errors="coerce").min()
    return pd.Timestamp("1900-01-01") if pd.isna(value) else pd.Timestamp(value)


def _clear_window_end(audit: pd.DataFrame) -> pd.Timestamp:
    if audit.empty or "requested_end" not in audit.columns:
        return pd.Timestamp("2100-01-01")
    value = pd.to_datetime(audit["requested_end"], errors="coerce").max()
    return pd.Timestamp("2100-01-01") if pd.isna(value) else pd.Timestamp(value)


def _audit_row_has_missing_bars(row: object) -> bool:
    return _audit_expected_rows(row) > 0 and _audit_missing_rows(row) > 0


def _audit_row_has_multiple_missing_episodes(row: object) -> bool:
    missing_rows = _audit_missing_rows(row)
    if missing_rows <= 1:
        return False
    try:
        max_missing_gap_minutes = int(getattr(row, "max_missing_gap_minutes", 0))
    except (TypeError, ValueError):
        return False
    if max_missing_gap_minutes <= 0:
        return False
    timeframe = ensure_supported_timeframe(str(getattr(row, "timeframe", "")))
    minutes = 1440 if timeframe == "1d" else int(timeframe.removesuffix("m"))
    return max_missing_gap_minutes < missing_rows * minutes


def _audit_expected_rows(row: object) -> int:
    try:
        return int(getattr(row, "expected_rows", 0))
    except (TypeError, ValueError):
        return 0


def _audit_missing_rows(row: object) -> int:
    try:
        return int(getattr(row, "missing_rows", 0))
    except (TypeError, ValueError):
        return 0


def _audit_row_has_requested_end_gap(row: object, *, end: pd.Timestamp, requested_end: pd.Timestamp) -> bool:
    timeframe = ensure_supported_timeframe(str(getattr(row, "timeframe", "")))
    if timeframe == "1d":
        return bool(end.normalize() < requested_end.normalize())
    return bool(end < requested_end)


def _optional_timestamp(value: object) -> pd.Timestamp:
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def _format_optional_date(value: object) -> str:
    timestamp = _optional_timestamp(value)
    if pd.isna(timestamp):
        return "-"
    return str(timestamp.date())


def _format_optional_timestamp(value: object) -> str:
    timestamp = _optional_timestamp(value)
    if pd.isna(timestamp):
        return "-"
    if timestamp == timestamp.normalize():
        return str(timestamp.date())
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _prepare_summary_rows(
    *,
    before: pd.DataFrame,
    after: pd.DataFrame,
    write_summary: pd.DataFrame,
    fetched_symbols: set[str],
    min_coverage_ratio: float | None,
) -> list[dict[str, object]]:
    after_by_symbol = {str(row.stock_code): row for row in after.itertuples(index=False)}
    write_by_symbol = {
        str(row.symbol): row
        for row in write_summary.itertuples(index=False)
    } if not write_summary.empty else {}

    rows: list[dict[str, object]] = []
    for before_row in before.itertuples(index=False):
        symbol = str(before_row.stock_code)
        after_row = after_by_symbol.get(symbol, before_row)
        write_row = write_by_symbol.get(symbol)
        fetched = symbol in fetched_symbols
        after_status = str(after_row.status)
        message = str(after_row.message)
        rows_written = int(getattr(write_row, "new_rows", 0)) if write_row is not None else 0
        if fetched and _audit_row_requires_tdx_update(after_row, min_coverage_ratio=min_coverage_ratio):
            after_status = "provider_no_data" if rows_written <= 0 else "provider_partial_gap"
            message = (
                f"真实请求 TDX 后仍存在缺口："
                f"下载前缺 {_audit_missing_rows(before_row)} 根，"
                f"下载后缺 {_audit_missing_rows(after_row)} 根，本次写入 {rows_written} 根。"
            )
        rows.append(
            {
                "stock_code": symbol,
                "timeframe": str(before_row.timeframe),
                "adjust": str(before_row.adjust),
                "action": "fetched" if fetched else "cached",
                "before_status": _summary_before_status(before_row, min_coverage_ratio=min_coverage_ratio),
                "after_status": after_status,
                "rows_written": rows_written,
                "new_rows": rows_written,
                "before_coverage_ratio": float(before_row.coverage_ratio),
                "after_coverage_ratio": float(after_row.coverage_ratio),
                "coverage_ratio": float(after_row.coverage_ratio),
                "before_missing_rows": int(before_row.missing_rows),
                "after_missing_rows": int(after_row.missing_rows),
                "missing_rows": int(after_row.missing_rows),
                "before_max_missing_gap_minutes": int(before_row.max_missing_gap_minutes),
                "after_max_missing_gap_minutes": int(after_row.max_missing_gap_minutes),
                "before_first_missing_at": getattr(before_row, "first_missing_at"),
                "before_last_missing_at": getattr(before_row, "last_missing_at"),
                "after_first_missing_at": getattr(after_row, "first_missing_at"),
                "after_last_missing_at": getattr(after_row, "last_missing_at"),
                "first_missing_at": getattr(after_row, "first_missing_at"),
                "last_missing_at": getattr(after_row, "last_missing_at"),
                "before_max_missing_gap_start_at": getattr(before_row, "max_missing_gap_start_at"),
                "before_max_missing_gap_end_at": getattr(before_row, "max_missing_gap_end_at"),
                "after_max_missing_gap_start_at": getattr(after_row, "max_missing_gap_start_at"),
                "after_max_missing_gap_end_at": getattr(after_row, "max_missing_gap_end_at"),
                "max_missing_gap_start_at": getattr(after_row, "max_missing_gap_start_at"),
                "max_missing_gap_end_at": getattr(after_row, "max_missing_gap_end_at"),
                "path": str(after_row.path),
                "message": message,
            }
        )
    return rows
