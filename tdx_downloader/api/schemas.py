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


class MarketRegimePayload(ResearchBasePayload):
    benchmark_symbol: str = "000300.SH"
    symbols: list[str] = Field(default_factory=list)
    universe_groups: list[str] = Field(default_factory=list)
    tdx_path: str = DEFAULT_TDX_PATH
    start: str
    end: str
    forward_windows: list[int] = Field(default_factory=lambda: [3, 5, 10])
    benchmark_rally_60_threshold: float = 0.08
    benchmark_pullback_20_threshold: float = Field(default=-0.03, le=0.0)
    pullback_20_threshold: float = -0.06
    pullback_60_threshold: float = -0.10
    liquidity_high_percentile: float = Field(default=0.80, ge=0.0, le=1.0)
    liquidity_mid_percentile: float = Field(default=0.35, ge=0.0, le=1.0)
    liquidity_low_percentile: float = Field(default=0.20, ge=0.0, le=1.0)
    volatility_high_percentile: float = Field(default=0.80, ge=0.0, le=1.0)
    volatility_low_percentile: float = Field(default=0.20, ge=0.0, le=1.0)
    high_position_drawdown_threshold: float = Field(default=-0.10, le=0.0)
    high_position_return_percentile: float = Field(default=0.80, ge=0.0, le=1.0)
    leader_return_5d_threshold: float = 0.03
    stress_ma20_break_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    stress_return_5d_threshold: float = 0.0
    cash_stress_score_threshold: float = Field(default=0.62, ge=0.0, le=1.0)
    cash_preference_proxy_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    risk_expansion_breadth_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    risk_contraction_breadth_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    risk_release_breadth_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    high_liquidity_selloff_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    concentration_top_n: int = Field(default=20, ge=1, le=500)
    daily_report_days: int = Field(default=20, ge=1, le=120)
    flow_candidate_limit: int = Field(default=30, ge=1, le=200)
    risk_timeline_days: int = Field(default=60, ge=5, le=180)


class ReviewAIPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2
    timeout_seconds: int = 60


class AICommandPayload(ResearchBasePayload):
    text: str = ""
    current_view: str = ""
    research_tab: str = ""
    tdx_path: str = DEFAULT_TDX_PATH
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.0
    timeout_seconds: int = 30


class AIStockAgentPayload(ResearchBasePayload):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt: str = ""
    skill_prompt: str = ""
    symbols: list[str] = Field(default_factory=list)
    start: str = Field(default_factory=lambda: (date.today() - timedelta(days=60)).isoformat())
    end: str = Field(default_factory=lambda: date.today().isoformat())
    temperature: float = 0.2
    timeout_seconds: int = 60
    max_symbols: int = Field(default=20, ge=1, le=50)
    max_rows: int = Field(default=240, ge=20, le=1000)
