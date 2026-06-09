from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from tdx_downloader.data.manager import shortcut_symbols

from .constants import (
    DEFAULT_ADJUST,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DATA_ROOT,
    DEFAULT_TDX_PATH,
    DEFAULT_TIMEFRAMES,
)


class DownloadPayload(BaseModel):
    data_root: str = DEFAULT_DATA_ROOT
    adjust: str = DEFAULT_ADJUST
    tdx_path: str = DEFAULT_TDX_PATH
    symbols: list[str] = Field(default_factory=lambda: list(shortcut_symbols("核心样例")))
    timeframes: list[str] = Field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))
    start: str = Field(default_factory=lambda: (date.today() - timedelta(days=20)).isoformat())
    end: str = Field(default_factory=lambda: date.today().isoformat())
    mode: str = "smart"
    batch_size: int = DEFAULT_BATCH_SIZE
    min_coverage_ratio: float | None = None
    strict_after_update: bool = True


class DirectoryPickerPayload(BaseModel):
    initial_directory: str = ""
    title: str = "选择文件夹"


class EtfReturnsPayload(BaseModel):
    data_root: str = DEFAULT_DATA_ROOT
    adjust: str = DEFAULT_ADJUST
    symbols: list[str] = Field(default_factory=list)
    end: str = Field(default_factory=lambda: date.today().isoformat())


class ResearchBasePayload(BaseModel):
    data_root: str = DEFAULT_DATA_ROOT
    adjust: str = DEFAULT_ADJUST
    timeframe: str = "1d"


class HistorySearchPayload(ResearchBasePayload):
    symbol: str
    as_of: str = Field(default_factory=lambda: date.today().isoformat())
    window_size: int = 20
    candidate_n: int = 100
    top_n: int = 10
    exclusion_bars: int = 20
    nearby_gap_days: int = 20
    path_weight: float = 0.7
    forward_windows: list[int] = Field(default_factory=lambda: [5, 20, 60])
    lookback_start: str = "1990-01-01"
    window_start: str | None = None
    algorithm: str = "baseline_price_feature"


class CrossSectionSearchPayload(ResearchBasePayload):
    target_symbol: str
    universe_symbols: list[str] = Field(default_factory=list)
    start: str
    end: str
    search_mode: str = "same_date"
    traversal_start: str | None = None
    traversal_end: str | None = None
    top_n: int = 20
    min_coverage: float = 0.8
    path_weight: float = 0.7
    exclusion_bars: int = 0
    forward_windows: list[int] = Field(default_factory=lambda: [3, 5, 10])
    date_tolerance_bars: int = 0


class ReviewSearchPayload(ResearchBasePayload):
    symbols: list[str] = Field(default_factory=list)
    start: str
    end: str
    benchmark_symbol: str = ""
    min_swing_return: float = 0.05
    min_segment_bars: int = 3
    max_segments: int = 6
    stock_names: dict[str, str] = Field(default_factory=dict)
    direction_by_symbol: dict[str, str] = Field(default_factory=dict)


class ReviewAIPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2
    timeout_seconds: int = 60
