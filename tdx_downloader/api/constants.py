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
TASK_EVENT_LIMIT = 300
PICKER_LIQUIDITY_SORT_GROUPS = frozenset({"ETF列表", "板块指数"})
PICKER_LIQUIDITY_LOOKBACK_BARS = 20
ETF_API_CACHE_MAX_ENTRIES = 32
ETF_TRACKING_CACHE_TTL_SECONDS = 6 * 60 * 60
ETF_RETURNS_CACHE_TTL_SECONDS = 30 * 60
PRICE_BARS_DEFAULT_LIMIT = 5000
PRICE_BARS_MAX_LIMIT = 50000
PRICE_SYMBOLS_DEFAULT_LIMIT = 5000
PRICE_SYMBOLS_MAX_LIMIT = 50000
AI_STOCK_AGENT_DEFAULT_MAX_CHARTS = 3
AI_STOCK_AGENT_MAX_CHARTS = 12
AI_STOCK_AGENT_MAX_CHART_CANDLES = 180

STAGE_LABELS = {
    "task_start": "任务启动",
    "local_task_start": "Windows 本地",
    "parallels_task_start": "Windows 调度",
    "parallels_vm_check_start": "VM 检查",
    "parallels_vm_check_done": "VM 就绪",
    "parallels_vm_check_failed": "VM 失败",
    "parallels_python_check_start": "Python 检查",
    "parallels_python_check_done": "Python 就绪",
    "parallels_python_check_failed": "Python 失败",
    "parallels_runner_start": "Windows 进程",
    "parallels_runner_done": "Windows 进程完成",
    "parallels_runner_failed": "Windows 进程失败",
    "parallels_command_start": "Windows 执行",
    "worker_health_start": "Worker 检查",
    "worker_health_ok": "Worker 就绪",
    "worker_start": "启动 Worker",
    "worker_job_submit": "提交 Worker",
    "worker_job_submitted": "Worker 已提交",
    "worker_job_queued": "Worker 排队",
    "worker_job_start": "Worker 执行",
    "worker_job_done": "Worker 完成",
    "worker_job_failed": "Worker 失败",
    "worker_fallback": "Worker 回退",
    "worker_fetch_window_start": "Worker 取数",
    "worker_fetch_window_done": "Worker 取数完成",
    "worker_force_fetch_start": "Worker 强制刷新",
    "worker_force_fetch_done": "Worker 强制完成",
    "worker_commit_part_read_start": "读取 part",
    "worker_commit_start": "提交缓存",
    "worker_commit_progress": "提交进度",
    "worker_commit_delta_done": "delta 完成",
    "worker_commit_coverage": "覆盖增量",
    "worker_commit_done": "缓存完成",
    "coverage_refresh_start": "覆盖索引",
    "coverage_refresh_progress": "覆盖进度",
    "coverage_refresh_done": "覆盖完成",
    "catalog_maintain_start": "维护索引",
    "catalog_maintain_done": "维护完成",
    "parallels_batch_retry_incomplete": "质量容错",
    "parallels_fetch_window_start": "Windows 取数",
    "parallels_fetch_window_done": "Windows 取数完成",
    "local_quality_gate_retry_incomplete": "质量容错",
    "parallels_command_done": "Windows 返回",
    "tdx_connection_check": "连接检查",
    "tdx_connection_ok": "连接成功",
    "tdx_connection_skipped": "未连接 TDX",
    "tdx_connection_cached": "连接缓存",
    "tdx_doctor_start": "TDX 诊断",
    "tdx_doctor_done": "诊断完成",
    "preflight_plan_start": "快速预检",
    "preflight_plan_done": "预检完成",
    "task_summary": "结果汇总",
    "catalog_refresh_start": "刷新索引",
    "catalog_refresh_done": "索引完成",
    "daily_sessions_start": "交易日锚点",
    "daily_sessions_done": "锚点完成",
    "audit_start": "审计缓存",
    "audit_done": "审计完成",
    "fetch_start": "请求 TDX",
    "tdx_request_start": "读取 TDX",
    "tdx_refresh_start": "触发刷新",
    "tdx_refresh_done": "刷新完成",
    "tdx_refresh_skipped": "刷新跳过",
    "tdx_batch_start": "读取批次",
    "tdx_batch_done": "读取完成",
    "tdx_no_rows": "TDX 空返回",
    "tdx_fallback_start": "5m 聚合补齐",
    "tdx_request_done": "读取完成",
    "write_start": "写入缓存",
    "write_done": "写入完成",
    "reaudit_start": "复核缓存",
    "reaudit_done": "复核完成",
    "fetch_skipped": "跳过下载",
    "prepare_done": "任务完成",
    "force_timeframe_start": "强制刷新",
    "force_timeframe_done": "刷新完成",
    "task_pause_requested": "请求暂停",
    "task_paused": "任务暂停",
    "task_resume_requested": "请求继续",
    "task_resumed": "任务继续",
    "task_cancel_requested": "请求终止",
    "task_cancelled": "任务终止",
    "task_done": "任务完成",
    "task_failed": "任务失败",
}
