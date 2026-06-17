from __future__ import annotations

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import pandas as pd

from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataDownloadResult,
    DataManagementService,
    download_summary,
    shortcut_symbol_groups,
)
from tdx_downloader.data.repository import (
    PREPARE_COLUMNS,
    _bootstrap_unknown_coverage_for_download,
    _fast_expected_sessions_by_symbol,
    _fast_prepare_audit,
    _fetch_window_groups_from_audit,
    _raise_for_failed_data_audit,
    _apply_unresolved_gaps_to_prepare_result,
    _merge_partial_after_audit,
    _post_update_audit,
    _prepare_summary_rows,
    _record_unresolved_gaps_after_fetch,
    _derive_timeframe_from_local_source,
    _symbols_requiring_update,
    _timeframes_with_daily_dependency,
)
from tdx_downloader.data.schema import normalize_symbol
from tdx_downloader.data.symbols import SYMBOL_METADATA_COLUMNS, load_symbol_metadata, save_symbol_metadata_cache
from tdx_downloader.data.tdx import (
    DEFAULT_ETF_TRACKING_INDEX_SYMBOLS,
    ETF_TRACKING_COLUMNS,
    fetch_tdx_etf_tracking_info,
)
from tdx_downloader.data.tdx_parallels import (
    PARALLELS_PROGRESS_ENV_VAR,
    PARALLELS_PROGRESS_PREFIX,
    mac_path_to_parallels_shared_path,
    start_parallels_tdx_worker,
)
from tdx_downloader.data.tdx_worker import commit_worker_manifest
from tdx_downloader.data.tdx_worker_client import TdxWorkerClient, WorkerJobFailed, WorkerUnavailable

DYNAMIC_SYMBOL_GROUP_NAMES = frozenset({"ETF列表", "板块指数", "全A股票"})
DYNAMIC_SYMBOL_GROUP_TARGETS = {
    "etf": frozenset({"ETF列表"}),
    "index": frozenset({"板块指数"}),
    "stock": frozenset({"全A股票"}),
}
PARALLELS_SYMBOL_GROUP_TIMEOUT_SECONDS = 45
PARALLELS_SYMBOL_METADATA_TIMEOUT_SECONDS = 30
PARALLELS_ETF_TRACKING_TIMEOUT_SECONDS = 60
QUALITY_GATE_ERROR_MARKER = "本地行情数据未通过质量门禁"
PARALLELS_COMMAND_POLL_SECONDS = 0.5
TDX_DOCTOR_CACHE_TTL_SECONDS = 600
WORKER_CLI_FALLBACK_ENV_VAR = "TDX_WORKER_ALLOW_CLI_FALLBACK"
_DOCTOR_CACHE: dict[tuple[object, ...], tuple[float, pd.DataFrame]] = {}


def should_use_parallels_runtime() -> bool:
    return sys.platform == "darwin"


def download_with_runtime(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
    cancel_check=None,
) -> DataDownloadResult:
    if should_use_parallels_runtime():
        _raise_if_cancelled(cancel_check)
        if mode == "smart" and not plan_requires_runtime_action(
            service,
            config,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        ):
            _emit_progress(
                progress_callback,
                stage="tdx_connection_skipped",
                message="快速预检查未生成下载窗口，跳过 Windows 通达信；随后执行本地结果汇总。",
            )
            return _download_locally_with_quality_retry(
                service,
                config,
                mode=mode,
                progress_callback=progress_callback,
            )
        return download_with_parallels_cli(
            service,
            config,
            mode=mode,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    _raise_if_cancelled(cancel_check)
    return _download_locally_with_quality_retry(
        service,
        config,
        mode=mode,
        progress_callback=progress_callback,
    )


def _download_locally_with_quality_retry(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
) -> DataDownloadResult:
    try:
        return service.download(config, mode=mode, progress_callback=progress_callback)
    except (RuntimeError, ValueError) as exc:
        if not _is_quality_gate_error(exc) or not config.strict_after_update:
            raise
        _emit_progress(
            progress_callback,
            stage="local_quality_gate_retry_incomplete",
            message=f"本地质量门禁未完全通过，已保留失败项并继续后续结果：{exc}",
            error=str(exc),
        )
        return service.download(
            replace(config, strict_after_update=False),
            mode=mode,
            progress_callback=progress_callback,
        )


def shortcut_symbol_groups_with_runtime(
    data_root: str | Path,
    tdx_path: str | Path,
    *,
    target: str = "",
) -> list[dict[str, object]]:
    groups = shortcut_symbol_groups(data_root=data_root, tdx_path=tdx_path)
    required_groups = _required_dynamic_symbol_groups(target)
    if not should_use_parallels_runtime() or _has_dynamic_symbol_groups(groups, required_groups):
        return groups
    records = run_parallels_cli_records(parallels_symbol_groups_command(data_root, tdx_path))
    return _normalize_symbol_group_records(records)


def symbol_metadata_with_runtime(
    data_root: str | Path,
    tdx_path: str | Path,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    if force_refresh:
        return refresh_symbol_metadata_with_runtime(data_root, tdx_path)
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    if not should_use_parallels_runtime() or not metadata.empty:
        return metadata
    records = run_parallels_cli_records(
        parallels_symbol_metadata_command(data_root, tdx_path),
        timeout=PARALLELS_SYMBOL_METADATA_TIMEOUT_SECONDS,
    )
    refreshed = _normalize_symbol_metadata_records(records)
    save_symbol_metadata_cache(data_root=data_root, tdx_path=tdx_path, metadata=refreshed)
    return refreshed


def refresh_symbol_metadata_with_runtime(data_root: str | Path, tdx_path: str | Path) -> pd.DataFrame:
    if not should_use_parallels_runtime():
        refreshed = load_symbol_metadata(data_root, tdx_path=tdx_path, force_refresh=True)
        if not str(tdx_path).strip():
            save_symbol_metadata_cache(data_root=data_root, tdx_path=tdx_path, metadata=refreshed)
        return refreshed
    records = run_parallels_cli_records(
        parallels_symbol_metadata_command(data_root, tdx_path),
        timeout=PARALLELS_SYMBOL_METADATA_TIMEOUT_SECONDS,
    )
    refreshed = _normalize_symbol_metadata_records(records)
    save_symbol_metadata_cache(data_root=data_root, tdx_path=tdx_path, metadata=refreshed)
    return refreshed


def etf_tracking_with_runtime(
    data_root: str | Path,
    tdx_path: str | Path,
    *,
    index_symbols: tuple[str, ...] | list[str] = DEFAULT_ETF_TRACKING_INDEX_SYMBOLS,
) -> pd.DataFrame:
    if not should_use_parallels_runtime():
        return fetch_tdx_etf_tracking_info(index_symbols=index_symbols, tqcenter_path=str(tdx_path))
    records = run_parallels_cli_records(
        parallels_etf_tracking_command(data_root, tdx_path, index_symbols=index_symbols),
        timeout=PARALLELS_ETF_TRACKING_TIMEOUT_SECONDS,
    )
    return _normalize_etf_tracking_records(records)


def plan_requires_runtime_action(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
    cancel_check=None,
) -> bool:
    """快速判断 smart 任务是否需要下载或本地派生；不能用 strict plan 扫 parquet 数据页。"""
    _raise_if_cancelled(cancel_check)
    started_at = time.perf_counter()
    _emit_progress(
        progress_callback,
        stage="preflight_plan_start",
        message="开始快速判断是否需要下载或派生数据。",
        symbol_count=len(config.symbols),
        timeframe_count=len(config.timeframes),
    )
    preview = getattr(service, "preview_download_plan", None)
    table = preview(config) if callable(preview) else service.download_plan(config)
    _raise_if_cancelled(cancel_check)
    if table.empty or "action" not in table.columns:
        _emit_progress(
            progress_callback,
            stage="preflight_plan_done",
            message="快速预检查完成：无可执行计划。",
            row_count=0,
            fetch_count=0,
            cached_count=0,
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return False
    action = table["action"].fillna("").astype(str)
    fetch_count = int(action.eq("fetch").sum())
    derive_count = int(action.eq("derive").sum())
    unresolved_count = int(action.eq("unresolved").sum())
    cached_count = int(action.eq("cached").sum())
    action_count = fetch_count + derive_count
    _emit_progress(
        progress_callback,
        stage="preflight_plan_done",
        message=f"快速预检查完成：{fetch_count} 项需要连接 TDX，{derive_count} 项本地派生，{unresolved_count} 项已知供应商缺口，{cached_count} 项已缓存。",
        row_count=int(len(table)),
        fetch_count=fetch_count,
        derive_count=derive_count,
        unresolved_count=unresolved_count,
        cached_count=cached_count,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
    )
    return action_count > 0


def plan_requires_tdx_fetch(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
    cancel_check=None,
) -> bool:
    return plan_requires_runtime_action(
        service,
        config,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def download_with_parallels_cli(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
    cancel_check=None,
) -> DataDownloadResult:
    try:
        return download_with_worker(
            service,
            config,
            mode=mode,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    except WorkerUnavailable as exc:
        if not _worker_cli_fallback_enabled():
            raise RuntimeError(
                "Windows Worker 不可用，已禁止自动回退 prlctl exec。"
                f"请修复 TDX_WORKER_URL/端口转发/Windows Worker 后重试；原始错误：{exc}"
            ) from exc
        _emit_progress(
            progress_callback,
            stage="worker_fallback",
            message=f"Windows Worker 不可用，回退 prlctl exec：{exc}",
            error=str(exc),
        )
    except WorkerJobFailed as exc:
        raise RuntimeError(f"Windows Worker 任务失败：{exc}") from exc
    verify_parallels_tdx_connection(service, config, progress_callback=progress_callback, cancel_check=cancel_check)
    if mode == "smart":
        table = _download_smart_with_parallels_fetch(
            service,
            config,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    elif mode == "force":
        frames = []
        step_count = len(config.timeframes)
        for timeframe in config.timeframes:
            _raise_if_cancelled(cancel_check)
            step_index = config.timeframes.index(timeframe) + 1
            _emit_progress(
                progress_callback,
                stage="parallels_command_start",
                message=f"开始执行强制刷新：{timeframe} 第 {step_index}/{step_count} 步。",
                timeframe=timeframe,
                step_index=step_index,
                step_count=step_count,
                symbol_count=len(config.symbols),
            )
            frames.append(
                force_cli_frame(
                    run_parallels_cli_table(
                        parallels_fetch_command(service, config, timeframe),
                        cancel_check=cancel_check,
                        progress_callback=progress_callback,
                    ),
                    timeframe=timeframe,
                    adjust=service.adjust,
                )
            )
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        raise RuntimeError(f"未知下载方式：{mode}")
    summary = download_summary(table)
    _emit_progress(
        progress_callback,
        stage="parallels_command_done",
        message=f"Windows 侧任务返回：{int(summary.get('fetched_count', 0))} 项 fetch，写入 {int(summary.get('rows_written', 0))} 行。",
    )
    return DataDownloadResult(table=table, summary=summary)


def _download_smart_with_parallels_fetch(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
    cancel_check=None,
) -> pd.DataFrame:
    """Mac 侧计算缺口窗口，Windows 侧只执行 TDX fetch。

    旧 fallback 会让 Windows 运行 prepare-data，并通过 \\psf 共享目录扫描 Mac parquet/SQLite。
    这在全市场任务下会卡在覆盖索引阶段。这里保留原 smart 语义，但把元数据审计固定在 Mac 本机执行。
    """
    _raise_if_cancelled(cancel_check)
    normalized_timeframes = _timeframes_without_implicit_daily(list(config.timeframes))
    normalized_symbols = list(config.symbols)
    processing_timeframes = _source_timeframe_order(normalized_timeframes)
    derived_targets_by_source = _worker_derivable_targets_by_source(processing_timeframes)
    derived_targets = {target for targets in derived_targets_by_source.values() for target in targets}
    source_timeframes = [timeframe for timeframe in processing_timeframes if timeframe not in derived_targets]

    _emit_progress(
        progress_callback,
        stage="parallels_command_start",
        message=f"开始执行智能补齐：Mac 侧计算缺口，Windows 侧只取数；{len(normalized_symbols)} 只，{len(source_timeframes)} 个源周期。",
        symbol_count=len(normalized_symbols),
        timeframe_count=len(source_timeframes),
    )
    expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
        data_root=service.data_root,
        adjust=service.adjust,
        symbols=normalized_symbols,
        timeframes=processing_timeframes,
        start=config.start,
        end=config.end,
        progress_callback=progress_callback,
        refresh_index=False,
    )

    before_audits: dict[str, pd.DataFrame] = {}
    after_audits: dict[str, pd.DataFrame] = {}
    write_summaries: dict[str, pd.DataFrame] = {}
    fetch_symbols_by_timeframe: dict[str, list[str]] = {}

    for step_index, timeframe in enumerate(source_timeframes, start=1):
        _raise_if_cancelled(cancel_check)
        _emit_progress(
            progress_callback,
            stage="audit_start",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
            message=f"Mac 侧审计 {timeframe} 覆盖索引。",
        )
        before = _fast_prepare_audit(
            data_root=service.data_root,
            timeframe=timeframe,
            adjust=service.adjust,
            symbols=normalized_symbols,
            start=config.start,
            end=config.end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
            refresh_index=False,
        )
        before_audits[timeframe] = before
        groups = _fetch_window_groups_from_audit(
            before,
            min_coverage_ratio=config.min_coverage_ratio,
            max_symbols_per_group=config.batch_size,
            data_root=service.data_root,
            adjust=service.adjust,
            start=config.start,
            end=config.end,
        )
        fetch_symbols = list(dict.fromkeys(symbol for group in groups for symbol in group.symbols))
        fetch_symbols_by_timeframe[timeframe] = fetch_symbols
        _emit_progress(
            progress_callback,
            stage="audit_done",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
            row_count=len(before),
            fetch_window_count=len(groups),
            fetch_symbol_count=len(fetch_symbols),
            message=f"Mac 侧审计完成：{timeframe} 生成 {len(groups)} 个缺口窗口，涉及 {len(fetch_symbols)} 只。",
        )

        if fetch_symbols:
            write_summaries[timeframe] = _fetch_window_groups_via_parallels_cli(
                service=service,
                config=config,
                timeframe=timeframe,
                groups=groups,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                before_audits[target_timeframe] = _fast_prepare_audit(
                    data_root=service.data_root,
                    timeframe=target_timeframe,
                    adjust=service.adjust,
                    symbols=normalized_symbols,
                    start=config.start,
                    end=config.end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    refresh_index=False,
                )
                target_symbols = _symbols_requiring_update(
                    before_audits[target_timeframe],
                    min_coverage_ratio=config.min_coverage_ratio,
                )
                derive_symbols = tuple(dict.fromkeys([*fetch_symbols, *target_symbols]))
                write_summaries[target_timeframe] = _derive_timeframe_from_local_source(
                    data_root=service.data_root,
                    adjust=service.adjust,
                    source_timeframe=timeframe,
                    target_timeframe=target_timeframe,
                    symbols=derive_symbols,
                    start=config.start,
                    end=config.end,
                    progress_callback=progress_callback,
                )
                fetch_symbols_by_timeframe[target_timeframe] = list(derive_symbols)

            _emit_progress(
                progress_callback,
                stage="reaudit_start",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(source_timeframes),
                message=f"复核 {timeframe} 缺口写入结果。",
            )
            after_audits[timeframe] = _merge_partial_after_audit(
                before=before,
                partial=_post_update_audit(
                    data_root=service.data_root,
                    timeframe=timeframe,
                    adjust=service.adjust,
                    symbols=fetch_symbols if config.strict_after_update else normalized_symbols,
                    start=config.start,
                    end=config.end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    strict=config.strict_after_update,
                ),
            )
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                after_audits[target_timeframe] = _merge_partial_after_audit(
                    before=before_audits[target_timeframe],
                    partial=_post_update_audit(
                        data_root=service.data_root,
                        timeframe=target_timeframe,
                        adjust=service.adjust,
                        symbols=fetch_symbols_by_timeframe[target_timeframe] if config.strict_after_update else normalized_symbols,
                        start=config.start,
                        end=config.end,
                        expected_sessions_by_symbol=expected_sessions_by_symbol,
                        strict=config.strict_after_update,
                    ),
                )
            _emit_progress(
                progress_callback,
                stage="reaudit_done",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(source_timeframes),
                row_count=len(after_audits[timeframe]),
                message=f"{timeframe} 复核完成。",
            )
        else:
            write_summaries[timeframe] = pd.DataFrame()
            after_audits[timeframe] = before
            for target_timeframe in derived_targets_by_source.get(timeframe, ()):
                before_audits[target_timeframe] = _fast_prepare_audit(
                    data_root=service.data_root,
                    timeframe=target_timeframe,
                    adjust=service.adjust,
                    symbols=normalized_symbols,
                    start=config.start,
                    end=config.end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    refresh_index=False,
                )
                derive_symbols = tuple(
                    _symbols_requiring_update(
                        before_audits[target_timeframe],
                        min_coverage_ratio=config.min_coverage_ratio,
                    )
                )
                if derive_symbols:
                    write_summaries[target_timeframe] = _derive_timeframe_from_local_source(
                        data_root=service.data_root,
                        adjust=service.adjust,
                        source_timeframe=timeframe,
                        target_timeframe=target_timeframe,
                        symbols=derive_symbols,
                        start=config.start,
                        end=config.end,
                        progress_callback=progress_callback,
                    )
                    after_audits[target_timeframe] = _merge_partial_after_audit(
                        before=before_audits[target_timeframe],
                        partial=_post_update_audit(
                            data_root=service.data_root,
                            timeframe=target_timeframe,
                            adjust=service.adjust,
                            symbols=list(derive_symbols) if config.strict_after_update else normalized_symbols,
                            start=config.start,
                            end=config.end,
                            expected_sessions_by_symbol=expected_sessions_by_symbol,
                            strict=config.strict_after_update,
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
                message=f"{timeframe} 本地覆盖完整，跳过 Windows 取数。",
            )

        if timeframe == "1d":
            expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
                data_root=service.data_root,
                adjust=service.adjust,
                symbols=normalized_symbols,
                timeframes=processing_timeframes,
                start=config.start,
                end=config.end,
                progress_callback=progress_callback,
                refresh_index=False,
            )

    after_all = pd.concat(after_audits.values(), ignore_index=True) if after_audits else pd.DataFrame()
    _record_unresolved_gaps_after_fetch(
        data_root=service.data_root,
        adjust=service.adjust,
        before_audits=before_audits,
        after_audits=after_audits,
        write_summaries=write_summaries,
        fetched_symbols_by_timeframe=fetch_symbols_by_timeframe,
    )
    if config.strict_after_update:
        _raise_for_failed_data_audit(after_all, min_coverage_ratio=config.min_coverage_ratio)

    rows: list[dict[str, object]] = []
    for timeframe in normalized_timeframes:
        before = before_audits.get(timeframe)
        after = after_audits.get(timeframe)
        if before is None or after is None:
            continue
        rows.extend(
            _prepare_summary_rows(
                before=before,
                after=after,
                write_summary=write_summaries.get(timeframe, pd.DataFrame()),
                fetched_symbols=set(fetch_symbols_by_timeframe.get(timeframe, [])),
                min_coverage_ratio=config.min_coverage_ratio,
            )
        )
    result = pd.DataFrame(rows, columns=PREPARE_COLUMNS)
    _emit_progress(
        progress_callback,
        stage="prepare_done",
        row_count=len(result),
        fetched_count=int(result["action"].eq("fetched").sum()) if "action" in result.columns else 0,
        message="智能补齐完成。",
    )
    return result


def _fetch_window_groups_via_parallels_cli(
    *,
    service: DataManagementService,
    config: DataDownloadConfig,
    timeframe: str,
    groups: list[object],
    progress_callback=None,
    cancel_check=None,
) -> pd.DataFrame:
    summaries: list[pd.DataFrame] = []
    total_symbols = sum(len(getattr(group, "symbols", ())) for group in groups)
    for index, group in enumerate(groups, start=1):
        _raise_if_cancelled(cancel_check)
        symbols = tuple(getattr(group, "symbols", ()))
        start = str(getattr(group, "start", config.start))
        end = str(getattr(group, "end", config.end))
        _emit_progress(
            progress_callback,
            stage="parallels_fetch_window_start",
            timeframe=timeframe,
            batch_index=index,
            batch_count=len(groups),
            symbol_count=len(symbols),
            total_symbol_count=total_symbols,
            start=start,
            end=end,
            message=f"Windows 取数 {timeframe}：窗口 {index}/{len(groups)}，{len(symbols)} 只，{start} 至 {end}。",
        )
        window_config = replace(config, symbols=symbols, timeframes=(timeframe,), start=start, end=end)
        frame = run_parallels_cli_table(
            parallels_fetch_command(service, window_config, timeframe),
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        summaries.append(_write_summary_from_fetch_frame(frame))
        _emit_progress(
            progress_callback,
            stage="parallels_fetch_window_done",
            timeframe=timeframe,
            batch_index=index,
            batch_count=len(groups),
            row_count=len(frame),
            message=f"Windows 取数完成 {timeframe}：窗口 {index}/{len(groups)}。",
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


def _write_summary_from_fetch_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "symbol" not in result.columns and "stock_code" in result.columns:
        result = result.rename(columns={"stock_code": "symbol"})
    if "rows" not in result.columns and "rows_written" in result.columns:
        result = result.rename(columns={"rows_written": "rows"})
    for column in ("status", "rows", "new_rows", "path", "start", "end", "message"):
        if column not in result.columns:
            result[column] = 0 if column in {"rows", "new_rows"} else ""
    return result.loc[:, ["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"]]


def download_with_worker(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
    cancel_check=None,
) -> DataDownloadResult:
    _raise_if_cancelled(cancel_check)
    client = TdxWorkerClient()
    if mode == "smart":
        payload, before_audits = _worker_smart_payload(service, config, progress_callback=progress_callback)
        if not payload["groups_by_timeframe"] and not payload.get("derive_targets_by_timeframe"):
            table = _worker_prepare_table(
                service=service,
                config=config,
                before_audits=before_audits,
                committed=pd.DataFrame(),
                requested_symbols_by_timeframe={},
            )
            failures = _worker_local_prepare_failures(table)
            if not failures.empty:
                samples = "; ".join(
                    f"{row.stock_code}/{row.timeframe}={row.after_status}({row.message})"
                    for row in failures.head(10).itertuples(index=False)
                )
                raise RuntimeError(
                    "Worker 计划为空，但本地结果仍有未覆盖缺口；"
                    f"请刷新覆盖索引或清理过期 provider gap 记录。样例：{samples}"
                )
            summary = download_summary(table)
            unresolved_count = int(table["action"].astype(str).eq("unresolved").sum()) if "action" in table.columns else 0
            cached_count = int(table["action"].astype(str).eq("cached").sum()) if "action" in table.columns else 0
            _emit_progress(
                progress_callback,
                stage="tdx_connection_skipped",
                message=(
                    "Worker 计划无可执行下载窗口："
                    f"{cached_count} 项本地已缓存，{unresolved_count} 项为已知供应商缺口。"
                ),
                cached_count=cached_count,
                unresolved_count=unresolved_count,
            )
            return DataDownloadResult(table=table, summary=summary)
        if payload["groups_by_timeframe"]:
            job_payload = _base_worker_payload(service, config, mode="fetch-windows")
            job_payload.update(payload)
        else:
            job_payload = {}
    elif mode == "force":
        before_audits = {}
        job_payload = _base_worker_payload(service, config, mode="force")
    else:
        raise RuntimeError(f"未知下载方式：{mode}")

    job_id = ""
    job_result: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    if job_payload:
        started_at = time.perf_counter()
        _emit_progress(progress_callback, stage="worker_health_start", message="检查 Windows Worker。")
        try:
            health = client.health()
        except WorkerUnavailable:
            _emit_progress(progress_callback, stage="worker_start", message="Windows Worker 未响应，尝试通过 prlctl exec 启动。")
            start_result = start_parallels_tdx_worker()
            if start_result.returncode != 0:
                detail = "\n".join(part for part in (start_result.stderr.strip(), start_result.stdout.strip()) if part).strip()
                raise WorkerUnavailable(f"Worker 启动失败：{detail}")
            health = _wait_for_worker_health(client)
        _emit_progress(
            progress_callback,
            stage="worker_health_ok",
            message=f"Windows Worker 可用：{health.get('python', '')}",
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            worker_url=client.base_url,
        )
        _emit_progress(
            progress_callback,
            stage="worker_job_submit",
            message=f"提交 Windows Worker 任务：{len(config.symbols)} 只，{len(config.timeframes)} 个周期。",
            mode=mode,
        )
        submitted = client.submit(job_payload)
        job_id = str(submitted.get("job_id") or "")
        if not job_id:
            raise WorkerUnavailable("Worker 未返回 job_id。")
        _emit_progress(progress_callback, stage="worker_job_submitted", message=f"Worker job 已提交：{job_id}", job_id=job_id)
        job_result = client.wait(job_id, progress_callback=progress_callback, cancel_check=cancel_check)
        worker_result = client.fetch_manifest_and_parts(job_id)
        manifest = worker_result.manifest
    if mode == "force":
        committed = commit_worker_manifest(
            data_root=service.data_root,
            manifest=manifest,
            part_loader=lambda name: worker_result.part_dir / name,
            progress_callback=progress_callback,
        )
        table = _force_table_from_manifest_records(manifest, committed, service.adjust)
    else:
        if job_payload:
            committed = commit_worker_manifest(
                data_root=service.data_root,
                manifest=manifest,
                part_loader=lambda name: worker_result.part_dir / name,
                progress_callback=progress_callback,
            )
        else:
            committed = pd.DataFrame()
        committed = _derive_worker_targets_after_commit(
            service=service,
            config=config,
            committed=committed,
            derive_targets_by_timeframe=payload.get("derive_targets_by_timeframe"),
            progress_callback=progress_callback,
        )
        table = _worker_prepare_table(
            service=service,
            config=config,
            before_audits=before_audits,
            committed=committed,
            requested_symbols_by_timeframe=_requested_symbols_by_timeframe(job_payload),
        )
    summary = download_summary(table)
    _emit_progress(
        progress_callback,
        stage="worker_job_done",
        message=f"Windows Worker 返回：{int(summary.get('fetched_count', 0))} 项 fetch，写入 {int(summary.get('rows_written', 0))} 行。",
        job_id=job_id,
        worker_status=job_result.get("status"),
    )
    return DataDownloadResult(table=table, summary=summary)


def _wait_for_worker_health(client: TdxWorkerClient) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return client.health()
        except WorkerUnavailable as exc:
            last_error = str(exc)
            time.sleep(1)
    raise WorkerUnavailable(f"Worker 启动后仍不可用：{last_error}")


def verify_parallels_tdx_connection(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
    cancel_check=None,
) -> pd.DataFrame:
    _raise_if_cancelled(cancel_check)
    started_at = time.perf_counter()
    cache_key = _doctor_cache_key(service, config)
    cached = _doctor_cache_get(cache_key)
    if cached is not None:
        _emit_progress(
            progress_callback,
            stage="tdx_connection_cached",
            message="TDX 连接检查命中缓存，跳过重复 doctor。",
            elapsed_ms=0,
        )
        return cached.copy()
    _emit_progress(
        progress_callback,
        stage="tdx_connection_check",
        message="确认通达信真实可连接中",
    )
    command = parallels_doctor_command(service, config)
    try:
        diagnosis = run_parallels_cli_table(
            command,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except RuntimeError as exc:
        _emit_progress(
            progress_callback,
            stage="tdx_connection_check_failed",
            message=str(exc),
            command="tdx-doctor",
        )
        raise
    if diagnosis.empty or "status" not in diagnosis.columns:
        _emit_progress(
            progress_callback,
            stage="tdx_connection_check_failed",
            message=(
                "TDX 连接检查返回了空诊断表。"
                f" columns={list(diagnosis.columns)} rows={len(diagnosis)}"
            ),
            command="tdx-doctor",
        )
        raise RuntimeError("TDX 连接检查未返回有效诊断结果。")
    failing = diagnosis.loc[diagnosis["status"].astype(str).isin({"init_error", "request_error", "invalid_symbols"})]
    if not failing.empty:
        message = str(failing.iloc[0].get("message", "TDX 连接检查失败。"))
        raise RuntimeError(f"TDX 连接检查失败：{message}")
    first = diagnosis.iloc[0]
    _emit_progress(
        progress_callback,
        stage="tdx_connection_ok",
        timeframe=str(first.get("timeframe", "")),
        message=(
            f"TDX 连接已验证：{first.get('timeframe', '')} "
            f"{first.get('status', '')}，样本 {int(float(first.get('rows') or 0))} 行。"
        ),
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
    )
    _doctor_cache_put(cache_key, diagnosis)
    return diagnosis


def _base_worker_payload(service: DataManagementService, config: DataDownloadConfig, *, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "data_root": mac_path_to_parallels_shared_path(str(service.data_root)),
        "adjust": service.adjust,
        "tdx_path": mac_path_to_parallels_shared_path(config.tqcenter_path),
        "symbols": list(config.symbols),
        "timeframes": list(config.timeframes),
        "start": config.start,
        "end": config.end,
        "batch_size": config.batch_size,
        "min_coverage_ratio": config.min_coverage_ratio,
        "strict_after_update": config.strict_after_update,
    }


def _worker_smart_payload(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    normalized_timeframes = _timeframes_without_implicit_daily(list(config.timeframes))
    normalized_symbols = list(config.symbols)
    processing_timeframes = _source_timeframe_order(normalized_timeframes)
    expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
        data_root=service.data_root,
        adjust=service.adjust,
        symbols=normalized_symbols,
        timeframes=processing_timeframes,
        start=config.start,
        end=config.end,
        progress_callback=progress_callback,
        refresh_index=False,
    )
    derived_targets_by_source = _worker_derivable_targets_by_source(processing_timeframes)
    source_timeframes = [
        timeframe
        for timeframe in processing_timeframes
        if timeframe not in {target for targets in derived_targets_by_source.values() for target in targets}
    ]
    before_audits: dict[str, pd.DataFrame] = {}
    groups_by_timeframe: dict[str, list[dict[str, Any]]] = {}
    derive_targets_by_timeframe: dict[str, list[str]] = {}
    for step_index, timeframe in enumerate(source_timeframes, start=1):
        _emit_progress(
            progress_callback,
            stage="audit_start",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
        )
        before = _fast_prepare_audit(
            data_root=service.data_root,
            timeframe=timeframe,
            adjust=service.adjust,
            symbols=normalized_symbols,
            start=config.start,
            end=config.end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
            refresh_index=False,
        )
        before = _bootstrap_unknown_coverage_for_download(
            before,
            data_root=service.data_root,
            timeframe=timeframe,
            adjust=service.adjust,
            start=config.start,
            end=config.end,
            expected_sessions_by_symbol=expected_sessions_by_symbol,
            progress_callback=progress_callback,
        )
        before_audits[timeframe] = before
        for target_timeframe in derived_targets_by_source.get(timeframe, ()):
            before_audits[target_timeframe] = _fast_prepare_audit(
                data_root=service.data_root,
                timeframe=target_timeframe,
                adjust=service.adjust,
                symbols=normalized_symbols,
                start=config.start,
                end=config.end,
                expected_sessions_by_symbol=expected_sessions_by_symbol,
                refresh_index=False,
            )
        groups = _fetch_window_groups_from_audit(
            before,
            min_coverage_ratio=config.min_coverage_ratio,
            max_symbols_per_group=config.batch_size,
            data_root=service.data_root,
            adjust=service.adjust,
            start=config.start,
            end=config.end,
        )
        fetch_symbols = list(dict.fromkeys(symbol for group in groups for symbol in group.symbols))
        if groups:
            groups_by_timeframe[timeframe] = [
                {"symbols": list(group.symbols), "start": group.start, "end": group.end}
                for group in groups
            ]
        for target_timeframe in derived_targets_by_source.get(timeframe, ()):
            target_symbols = _symbols_requiring_update(
                before_audits[target_timeframe],
                min_coverage_ratio=config.min_coverage_ratio,
            )
            derive_symbols = list(dict.fromkeys([*fetch_symbols, *target_symbols]))
            if derive_symbols:
                derive_targets_by_timeframe[target_timeframe] = derive_symbols
        _emit_progress(
            progress_callback,
            stage="audit_done",
            timeframe=timeframe,
            step_index=step_index,
            step_count=len(source_timeframes),
            row_count=len(before),
        )
    return {"groups_by_timeframe": groups_by_timeframe, "derive_targets_by_timeframe": derive_targets_by_timeframe}, before_audits


def _worker_prepare_table(
    *,
    service: DataManagementService,
    config: DataDownloadConfig,
    before_audits: dict[str, pd.DataFrame],
    committed: pd.DataFrame,
    requested_symbols_by_timeframe: dict[str, set[str]] | None = None,
) -> pd.DataFrame:
    normalized_timeframes = _timeframes_with_daily_dependency(list(config.timeframes))
    expected_sessions_by_symbol = _fast_expected_sessions_by_symbol(
        data_root=service.data_root,
        adjust=service.adjust,
        symbols=list(config.symbols),
        timeframes=normalized_timeframes,
        start=config.start,
        end=config.end,
        refresh_index=False,
    )
    after_audits: dict[str, pd.DataFrame] = {}
    fetched_symbols_by_timeframe = _fetched_symbols_by_timeframe(committed)
    for timeframe, symbols in (requested_symbols_by_timeframe or {}).items():
        fetched_symbols_by_timeframe.setdefault(timeframe, set()).update(symbols)
    for timeframe, before in before_audits.items():
        fetched_symbols = fetched_symbols_by_timeframe.get(timeframe, set())
        if fetched_symbols:
            after_audits[timeframe] = _merge_partial_after_audit(
                before=before,
                partial=_post_update_audit(
                    data_root=service.data_root,
                    timeframe=timeframe,
                    adjust=service.adjust,
                    symbols=list(fetched_symbols) if config.strict_after_update else list(config.symbols),
                    start=config.start,
                    end=config.end,
                    expected_sessions_by_symbol=expected_sessions_by_symbol,
                    strict=config.strict_after_update,
                ),
            )
        else:
            after_audits[timeframe] = before
    _record_unresolved_gaps_after_fetch(
        data_root=service.data_root,
        adjust=service.adjust,
        before_audits=before_audits,
        after_audits=after_audits,
        write_summaries={
            timeframe: _write_summary_for_timeframe(committed, timeframe)
            for timeframe in before_audits
        },
        fetched_symbols_by_timeframe={
            timeframe: list(symbols)
            for timeframe, symbols in fetched_symbols_by_timeframe.items()
        },
    )
    rows: list[dict[str, object]] = []
    for timeframe in normalized_timeframes:
        before = before_audits.get(timeframe)
        after = after_audits.get(timeframe)
        if before is None or after is None:
            continue
        rows.extend(
            _prepare_summary_rows(
                before=before,
                after=after,
                write_summary=_write_summary_for_timeframe(committed, timeframe),
                fetched_symbols=fetched_symbols_by_timeframe.get(timeframe, set()),
                min_coverage_ratio=config.min_coverage_ratio,
            )
        )
    result = pd.DataFrame(rows, columns=PREPARE_COLUMNS)
    return _apply_unresolved_gaps_to_prepare_result(
        result,
        data_root=service.data_root,
        adjust=service.adjust,
        symbols=list(config.symbols),
        timeframes=normalized_timeframes,
        start=config.start,
        end=config.end,
    )


def _worker_local_prepare_failures(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty or not {"action", "after_status", "missing_rows"}.issubset(table.columns):
        return pd.DataFrame()
    action = table["action"].fillna("").astype(str)
    after_status = table["after_status"].fillna("").astype(str)
    missing_rows = pd.to_numeric(table["missing_rows"], errors="coerce").fillna(0)
    failed = table.loc[
        action.ne("unresolved")
        & (
            after_status.ne("ok")
            | missing_rows.gt(0)
        )
    ].copy()
    return failed


def _derive_worker_targets_after_commit(
    *,
    service: DataManagementService,
    config: DataDownloadConfig,
    committed: pd.DataFrame,
    derive_targets_by_timeframe: dict[str, list[str]] | None = None,
    progress_callback=None,
) -> pd.DataFrame:
    normalized_timeframes = _timeframes_with_daily_dependency(list(config.timeframes))
    targets = _worker_derivable_targets_by_source(normalized_timeframes).get("5m", ())
    if not targets:
        return committed
    if committed.empty and not derive_targets_by_timeframe:
        return committed
    if not committed.empty and ("timeframe" not in committed.columns or "symbol" not in committed.columns):
        return committed
    frames = [committed]
    for target_timeframe in targets:
        requested_symbols = (derive_targets_by_timeframe or {}).get(target_timeframe, [])
        fetched_source_symbols = (
            committed.loc[committed["timeframe"].astype(str).eq("5m"), "symbol"].dropna().astype(str).tolist()
            if not committed.empty
            else []
        )
        source_symbols = tuple(sorted(set([*requested_symbols, *fetched_source_symbols])))
        if not source_symbols:
            continue
        derived = _derive_timeframe_from_local_source(
            data_root=service.data_root,
            adjust=service.adjust,
            source_timeframe="5m",
            target_timeframe=target_timeframe,
            symbols=source_symbols,
            start=config.start,
            end=config.end,
            progress_callback=progress_callback,
        )
        if not derived.empty:
            derived = derived.copy()
            derived["timeframe"] = target_timeframe
            derived["adjust"] = service.adjust
            frames.append(derived)
    return pd.concat(frames, ignore_index=True)


def _force_table_from_manifest_records(manifest: dict[str, Any], committed: pd.DataFrame, adjust: str) -> pd.DataFrame:
    del manifest
    frames = []
    for timeframe in sorted(set(committed.get("timeframe", pd.Series(dtype=str)).dropna().astype(str))):
        frames.append(force_cli_frame(_write_summary_for_timeframe(committed, timeframe), timeframe=timeframe, adjust=adjust))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_summary_for_timeframe(committed: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if committed.empty or "timeframe" not in committed.columns:
        return pd.DataFrame()
    frame = committed.loc[committed["timeframe"].astype(str).eq(str(timeframe))].copy()
    if frame.empty:
        return pd.DataFrame()
    return frame.drop(columns=["timeframe", "adjust"], errors="ignore")


def _fetched_symbols_by_timeframe(committed: pd.DataFrame) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    if committed.empty or "timeframe" not in committed.columns:
        return result
    for row in committed.itertuples(index=False):
        timeframe = str(getattr(row, "timeframe", ""))
        symbol = str(getattr(row, "symbol", ""))
        if timeframe and symbol:
            result.setdefault(timeframe, set()).add(symbol)
    return result


def _requested_symbols_by_timeframe(payload: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    groups_by_timeframe = payload.get("groups_by_timeframe") if isinstance(payload, dict) else {}
    if not isinstance(groups_by_timeframe, dict):
        return result
    for timeframe, groups in groups_by_timeframe.items():
        if not isinstance(groups, list):
            continue
        symbols = result.setdefault(str(timeframe), set())
        for group in groups:
            if not isinstance(group, dict):
                continue
            symbols.update(str(item) for item in (group.get("symbols") or []) if str(item).strip())
    return result


def _worker_derivable_targets_by_source(timeframes: list[str]) -> dict[str, tuple[str, ...]]:
    if "5m" not in timeframes:
        return {}
    targets = tuple(timeframe for timeframe in timeframes if timeframe in {"15m", "30m", "60m"})
    return {"5m": targets} if targets else {}


def _timeframes_without_implicit_daily(timeframes: list[str]) -> list[str]:
    return list(dict.fromkeys(str(timeframe) for timeframe in timeframes if str(timeframe)))


def _source_timeframe_order(timeframes: list[str]) -> list[str]:
    requested = _timeframes_without_implicit_daily(timeframes)
    return [timeframe for timeframe in requested if timeframe != "1d"] + [timeframe for timeframe in requested if timeframe == "1d"]


def _worker_cli_fallback_enabled() -> bool:
    return os.getenv(WORKER_CLI_FALLBACK_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}


def _doctor_cache_key(service: DataManagementService, config: DataDownloadConfig) -> tuple[object, ...]:
    symbol = config.symbols[0] if config.symbols else ""
    return (str(service.adjust), str(config.tqcenter_path), tuple(config.timeframes), str(symbol), str(config.start), str(config.end))


def _doctor_cache_get(key: tuple[object, ...]) -> pd.DataFrame | None:
    cached = _DOCTOR_CACHE.get(key)
    if cached is None:
        return None
    cached_at, frame = cached
    if time.time() - cached_at > TDX_DOCTOR_CACHE_TTL_SECONDS:
        _DOCTOR_CACHE.pop(key, None)
        return None
    return frame


def _doctor_cache_put(key: tuple[object, ...], frame: pd.DataFrame) -> None:
    _DOCTOR_CACHE[key] = (time.time(), frame.copy())


def run_parallels_cli_table(command: list[str], *, cancel_check=None, progress_callback=None) -> pd.DataFrame:
    try:
        result = _run_cancellable_command(
            command,
            cwd=Path(__file__).resolve().parents[2],
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 Parallels/Windows 通达信任务：{exc}") from exc
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
        raise RuntimeError(f"通达信调用失败：{clean_parallels_cli_error(detail)}")
    try:
        return parse_cli_table(result.stdout)
    except RuntimeError as exc:
        detail = _cli_output_excerpt(stdout=result.stdout, stderr=result.stderr)
        raise RuntimeError(f"{exc}；原始输出：{detail}") from exc


def _cli_output_excerpt(*, stdout: str, stderr: str, limit: int = 1200) -> str:
    parts = []
    if stdout.strip():
        parts.append(f"stdout={stdout.strip()}")
    if stderr.strip():
        parts.append(f"stderr={stderr.strip()}")
    text = " | ".join(parts).strip()
    if not text:
        return "stdout/stderr 均为空"
    return text[:limit]


def _run_cancellable_command(
    command: list[str],
    *,
    cwd: Path,
    cancel_check=None,
    progress_callback=None,
) -> subprocess.CompletedProcess[str]:
    _raise_if_cancelled(cancel_check)
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=cwd,
        env={**os.environ, PARALLELS_PROGRESS_ENV_VAR: "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stderr_queue: queue.Queue[str | None] = queue.Queue()
    stdout_thread = threading.Thread(target=_collect_text_stream, args=(getattr(process, "stdout", None), stdout_lines), daemon=True)
    stderr_thread = threading.Thread(target=_queue_text_stream, args=(getattr(process, "stderr", None), stderr_queue), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    while process.poll() is None:
        _drain_progress_queue(stderr_queue, progress_callback, stderr_lines)
        try:
            _raise_if_cancelled(cancel_check)
        except BaseException:
            _terminate_process(process)
            raise
        time.sleep(PARALLELS_COMMAND_POLL_SECONDS)
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    _drain_progress_queue(stderr_queue, progress_callback, stderr_lines)
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    return subprocess.CompletedProcess(args=command, returncode=int(process.returncode or 0), stdout=stdout, stderr=stderr)


def _collect_text_stream(stream: Any, sink: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        sink.append(str(line))


def _queue_text_stream(stream: Any, sink: queue.Queue[str | None]) -> None:
    if stream is None:
        sink.put(None)
        return
    for line in stream:
        sink.put(str(line))
    sink.put(None)


def _drain_progress_queue(
    stream_queue: queue.Queue[str | None],
    progress_callback,
    stderr_lines: list[str],
) -> None:
    while True:
        try:
            line = stream_queue.get_nowait()
        except queue.Empty:
            return
        if line is None:
            continue
        if _handle_progress_line(line, progress_callback):
            continue
        stderr_lines.append(line)


def _handle_progress_line(line: str, progress_callback) -> bool:
    text = str(line).strip()
    if not text.startswith(PARALLELS_PROGRESS_PREFIX):
        return False
    try:
        payload = json.loads(text.removeprefix(PARALLELS_PROGRESS_PREFIX))
    except json.JSONDecodeError:
        return True
    if isinstance(payload, dict):
        _emit_progress(progress_callback, **payload)
    return True


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
    else:
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        process.kill()
    process.wait(timeout=5)


def _raise_if_cancelled(cancel_check) -> None:
    if cancel_check is None:
        return
    cancel_check()


def run_parallels_cli_records(command: list[str], *, timeout: int = PARALLELS_SYMBOL_GROUP_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("读取 Windows 通达信快捷代码表超时，请确认 Parallels 与 Windows 通达信已启动。") from exc
    except OSError as exc:
        raise RuntimeError(f"无法启动 Parallels/Windows 通达信任务：{exc}") from exc
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
        raise RuntimeError(f"通达信调用失败：{clean_parallels_cli_error(detail)}")
    records = extract_json_records(result.stdout)
    if records is None:
        raise RuntimeError("Parallels/Windows 通达信任务已返回，但 JSON 结果解析失败。")
    return records


def clean_parallels_cli_error(detail: str) -> str:
    text = detail.strip()
    if not text:
        return "未返回错误详情"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    quality_line = next((line for line in reversed(lines) if "本地行情数据未通过质量门禁" in line), "")
    if quality_line:
        message = quality_line.split("ValueError:", 1)[-1].strip()
        return (
            f"{message}\n"
            "Windows 通达信没有返回当前窗口所需数据。若选择分钟周期，请先在 Windows 通达信内下载对应日期的分钟 K 线，"
            "或改用 1d / 已存在的分钟数据日期范围。"
        )
    exception_line = next(
        (
            line
            for line in reversed(lines)
            if line.startswith(("RuntimeError:", "ValueError:", "ModuleNotFoundError:", "ImportError:"))
        ),
        "",
    )
    if exception_line:
        return exception_line.split(":", 1)[-1].strip()
    return text.replace("Traceback (most recent call last):", "").strip()


def parse_cli_table(stdout: str) -> pd.DataFrame:
    text = stdout.strip()
    if not text:
        return pd.DataFrame()
    records = extract_json_records(text)
    if records is not None:
        return pd.DataFrame(records)
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    try:
        return pd.read_csv(io.StringIO(normalized), sep=r"\s{2,}", engine="python")
    except Exception as exc:
        raise RuntimeError(f"Parallels/Windows 任务已返回，但结果表解析失败：{exc}") from exc


def extract_json_records(text: str) -> list[dict[str, Any]] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "[":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return [record for record in payload if isinstance(record, dict)]
    return None


def parallels_doctor_command(service: DataManagementService, config: DataDownloadConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        "tdx-doctor",
        "--runtime",
        "parallels",
        "--symbols",
        config.symbols[0],
        "--timeframes",
        ",".join(config.timeframes),
        "--start",
        config.start,
        "--end",
        config.end,
        "--adjust",
        service.adjust,
        "--tdx-path",
        config.tqcenter_path,
        "--output",
        "json",
    ]


def parallels_symbol_groups_command(data_root: str | Path, tdx_path: str | Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        "symbol-groups",
        "--runtime",
        "parallels",
        "--data-root",
        str(data_root),
        "--tdx-path",
        str(tdx_path),
        "--output",
        "json",
    ]


def parallels_symbol_metadata_command(data_root: str | Path, tdx_path: str | Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        "symbol-metadata",
        "--runtime",
        "parallels",
        "--data-root",
        str(data_root),
        "--tdx-path",
        str(tdx_path),
        "--output",
        "json",
    ]


def parallels_etf_tracking_command(
    data_root: str | Path,
    tdx_path: str | Path,
    *,
    index_symbols: tuple[str, ...] | list[str],
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        "etf-tracking",
        "--runtime",
        "parallels",
        "--data-root",
        str(data_root),
        "--tdx-path",
        str(tdx_path),
        "--index-symbols",
        ",".join(index_symbols),
        "--output",
        "json",
    ]


def parallels_prepare_command(service: DataManagementService, config: DataDownloadConfig) -> list[str]:
    command = parallels_base_command(service, config, "prepare-data")
    command.extend(["--timeframes", ",".join(config.timeframes)])
    if config.min_coverage_ratio is not None:
        command.extend(["--min-coverage-ratio", str(config.min_coverage_ratio)])
    if not config.strict_after_update:
        command.append("--allow-incomplete-after-update")
    return command


def parallels_fetch_command(service: DataManagementService, config: DataDownloadConfig, timeframe: str) -> list[str]:
    command = parallels_base_command(service, config, "fetch")
    command.extend(["--timeframe", timeframe])
    return command


def parallels_base_command(
    service: DataManagementService,
    config: DataDownloadConfig,
    command: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        command,
        "--runtime",
        "parallels",
        "--symbols",
        ",".join(config.symbols),
        "--start",
        config.start,
        "--end",
        config.end,
        "--adjust",
        service.adjust,
        "--data-root",
        str(service.data_root),
        "--tdx-path",
        config.tqcenter_path,
        "--batch-size",
        str(config.batch_size),
        "--output",
        "json",
    ]


def force_cli_frame(frame: pd.DataFrame, *, timeframe: str, adjust: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["stock_code", "timeframe", "adjust", "action", "rows_written", "new_rows"])
    result = frame.rename(columns={"symbol": "stock_code"}).copy()
    result["rows_written"] = pd.to_numeric(result.get("new_rows", 0), errors="coerce").fillna(0).astype(int)
    result["timeframe"] = timeframe
    result["adjust"] = adjust
    result["action"] = "fetched"
    return result


def _normalize_etf_tracking_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=ETF_TRACKING_COLUMNS)
    frame = pd.DataFrame(records)
    for column in ETF_TRACKING_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame["tracking_symbol"] = frame["tracking_symbol"].map(normalize_symbol)
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["stock_name"] = frame["stock_name"].fillna("").astype(str).str.strip()
    for column in ("now_price", "pre_close", "iopv", "shares", "market_value"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.loc[frame["tracking_symbol"].ne("") & frame["stock_code"].ne(""), ETF_TRACKING_COLUMNS]
        .drop_duplicates(subset=["tracking_symbol", "stock_code"], keep="first")
        .reset_index(drop=True)
    )


def _emit_progress(callback, **payload: object) -> None:
    if callback is not None:
        callback(payload)


def _is_quality_gate_error(error: Exception) -> bool:
    return QUALITY_GATE_ERROR_MARKER in str(error)


def _required_dynamic_symbol_groups(target: str) -> frozenset[str]:
    normalized = str(target or "").strip().lower()
    if not normalized:
        return DYNAMIC_SYMBOL_GROUP_NAMES
    try:
        return DYNAMIC_SYMBOL_GROUP_TARGETS[normalized]
    except KeyError as exc:
        raise RuntimeError(f"未知快捷代码刷新目标：{target}") from exc


def _has_dynamic_symbol_groups(groups: list[dict[str, object]], required_groups: frozenset[str]) -> bool:
    names = {str(group.get("name", "")) for group in groups if group.get("symbols")}
    return required_groups.issubset(names)


def _normalize_symbol_group_records(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for record in records:
        name = str(record.get("name", "")).strip()
        symbols = record.get("symbols", [])
        if not name:
            continue
        if isinstance(symbols, str):
            normalized_symbols = [item.strip() for item in symbols.replace("\n", ",").split(",") if item.strip()]
        elif isinstance(symbols, list):
            normalized_symbols = [str(item).strip() for item in symbols if str(item).strip()]
        else:
            normalized_symbols = []
        groups.append({"name": name, "symbols": normalized_symbols})
    return groups


def _normalize_symbol_metadata_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=pd.Index(SYMBOL_METADATA_COLUMNS))
    frame = pd.DataFrame(records)
    if "stock_code" not in frame.columns or "stock_name" not in frame.columns:
        raise RuntimeError("Parallels/Windows 代码名称表缺少 stock_code 或 stock_name 字段。")
    for column in SYMBOL_METADATA_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    result = frame.loc[:, SYMBOL_METADATA_COLUMNS].copy()
    result["stock_code"] = result["stock_code"].map(normalize_symbol)
    result["stock_name"] = result["stock_name"].fillna("").astype(str).str.strip()
    return (
        result.loc[result["stock_code"].ne("") & result["stock_name"].ne("")]
        .drop_duplicates(subset=["stock_code"], keep="first")
        .sort_values("stock_code", kind="mergesort")
        .reset_index(drop=True)
    )
