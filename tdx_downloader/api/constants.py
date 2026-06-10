from __future__ import annotations

import os

from tdx_downloader.cli import DEFAULT_DATA_ROOT as CLI_DEFAULT_DATA_ROOT

DEFAULT_DATA_ROOT = os.getenv("TDX_DATA_ROOT", CLI_DEFAULT_DATA_ROOT)
DEFAULT_TDX_PATH = os.getenv(
    "TDX_TDX_PATH",
    os.getenv("TDX_TQCENTER_PATH", "/Volumes/[C] Windows 11/new_tdx64/PYPlugins"),
)
DEFAULT_ADJUST = "qfq"
DEFAULT_TIMEFRAMES = ("1d",)
DEFAULT_BATCH_SIZE = 100
MAX_TABLE_RECORDS = 500
TASK_HISTORY_LIMIT = 50
TASK_EVENT_LIMIT = 40
PICKER_LIQUIDITY_SORT_GROUPS = frozenset({"ETF列表", "板块指数"})
PICKER_LIQUIDITY_LOOKBACK_BARS = 20
ETF_API_CACHE_MAX_ENTRIES = 32
ETF_TRACKING_CACHE_TTL_SECONDS = 6 * 60 * 60
ETF_RETURNS_CACHE_TTL_SECONDS = 30 * 60

STAGE_LABELS = {
    "task_start": "任务启动",
    "local_task_start": "Windows 本地",
    "parallels_task_start": "Windows 调度",
    "parallels_command_start": "Windows 执行",
    "parallels_batch_retry_incomplete": "质量容错",
    "local_quality_gate_retry_incomplete": "质量容错",
    "parallels_command_done": "Windows 返回",
    "tdx_connection_check": "连接检查",
    "tdx_connection_ok": "连接成功",
    "tdx_connection_skipped": "未连接 TDX",
    "task_summary": "结果汇总",
    "catalog_refresh_start": "刷新索引",
    "catalog_refresh_done": "索引完成",
    "daily_sessions_start": "交易日锚点",
    "daily_sessions_done": "锚点完成",
    "audit_start": "审计缓存",
    "audit_done": "审计完成",
    "fetch_start": "请求 TDX",
    "tdx_request_start": "请求 TDX",
    "tdx_batch_start": "批次请求",
    "tdx_batch_done": "批次完成",
    "tdx_fallback_start": "5m 聚合补齐",
    "tdx_request_done": "请求完成",
    "write_start": "写入缓存",
    "write_done": "写入完成",
    "reaudit_start": "复核缓存",
    "reaudit_done": "复核完成",
    "fetch_skipped": "跳过下载",
    "prepare_done": "任务完成",
    "force_timeframe_start": "强制刷新",
    "force_timeframe_done": "刷新完成",
    "task_done": "任务完成",
    "task_failed": "任务失败",
}
