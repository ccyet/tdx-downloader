from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataDownloadResult,
    DataManagementService,
    download_summary,
    shortcut_symbol_groups,
)
from tdx_downloader.data.schema import normalize_symbol
from tdx_downloader.data.symbols import SYMBOL_METADATA_COLUMNS, load_symbol_metadata

DYNAMIC_SYMBOL_GROUP_NAMES = frozenset({"ETF列表", "板块指数", "全A股票"})
DYNAMIC_SYMBOL_GROUP_TARGETS = {
    "etf": frozenset({"ETF列表"}),
    "index": frozenset({"板块指数"}),
    "stock": frozenset({"全A股票"}),
}
PARALLELS_SYMBOL_GROUP_TIMEOUT_SECONDS = 12
PARALLELS_SYMBOL_METADATA_TIMEOUT_SECONDS = 30
QUALITY_GATE_ERROR_MARKER = "本地行情数据未通过质量门禁"


def should_use_parallels_runtime() -> bool:
    return sys.platform == "darwin"


def download_with_runtime(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
) -> DataDownloadResult:
    if should_use_parallels_runtime():
        if mode == "smart" and not plan_requires_tdx_fetch(service, config):
            _emit_progress(
                progress_callback,
                stage="tdx_connection_skipped",
                message="本地缓存已覆盖当前任务，无需连接 Windows 通达信。",
            )
            return service.download(config, mode=mode, progress_callback=progress_callback)
        return download_with_parallels_cli(service, config, mode=mode, progress_callback=progress_callback)
    return service.download(config, mode=mode, progress_callback=progress_callback)


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


def symbol_metadata_with_runtime(data_root: str | Path, tdx_path: str | Path) -> pd.DataFrame:
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    if not should_use_parallels_runtime() or not metadata.empty:
        return metadata
    records = run_parallels_cli_records(
        parallels_symbol_metadata_command(data_root, tdx_path),
        timeout=PARALLELS_SYMBOL_METADATA_TIMEOUT_SECONDS,
    )
    return _normalize_symbol_metadata_records(records)


def plan_requires_tdx_fetch(service: DataManagementService, config: DataDownloadConfig) -> bool:
    table = service.download_plan(config)
    if table.empty or "action" not in table.columns:
        return False
    return bool(table["action"].fillna("").astype(str).eq("fetch").any())


def download_with_parallels_cli(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
    progress_callback=None,
) -> DataDownloadResult:
    verify_parallels_tdx_connection(service, config, progress_callback=progress_callback)
    if mode == "smart":
        frames: list[pd.DataFrame] = []
        batches = _symbol_batches(config)
        for batch_index, batch_config in enumerate(batches, start=1):
            _emit_progress(
                progress_callback,
                stage="parallels_command_start",
                message=f"Windows 侧开始执行智能补齐：第 {batch_index}/{len(batches)} 批。",
                batch_index=batch_index,
                batch_count=len(batches),
                symbol_count=len(batch_config.symbols),
            )
            try:
                frames.append(run_parallels_cli_table(parallels_prepare_command(service, batch_config)))
            except RuntimeError as exc:
                if not _is_quality_gate_error(exc) or not batch_config.strict_after_update:
                    raise
                _emit_progress(
                    progress_callback,
                    stage="parallels_batch_retry_incomplete",
                    message=(
                        f"第 {batch_index}/{len(batches)} 批未完全通过质量门禁，"
                        "已按容错模式保留失败项并继续后续批次。"
                    ),
                    batch_index=batch_index,
                    batch_count=len(batches),
                    symbol_count=len(batch_config.symbols),
                    error=str(exc),
                )
                tolerant_config = replace(batch_config, strict_after_update=False)
                frames.append(run_parallels_cli_table(parallels_prepare_command(service, tolerant_config)))
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    elif mode == "force":
        frames = []
        batches = _symbol_batches(config)
        step_count = len(config.timeframes) * len(batches)
        step_index = 0
        for timeframe in config.timeframes:
            for batch_config in batches:
                step_index += 1
                _emit_progress(
                    progress_callback,
                    stage="parallels_command_start",
                    message=f"Windows 侧开始执行强制刷新：{timeframe} 第 {step_index}/{step_count} 步。",
                    timeframe=timeframe,
                    step_index=step_index,
                    step_count=step_count,
                    symbol_count=len(batch_config.symbols),
                )
                frames.append(
                    force_cli_frame(
                        run_parallels_cli_table(parallels_fetch_command(service, batch_config, timeframe)),
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


def verify_parallels_tdx_connection(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    progress_callback=None,
) -> pd.DataFrame:
    _emit_progress(
        progress_callback,
        stage="tdx_connection_check",
        message="Windows 侧初始化 tqcenter 并发起样本请求，确认通达信真实可连接。",
    )
    diagnosis = run_parallels_cli_table(parallels_doctor_command(service, config))
    if diagnosis.empty or "status" not in diagnosis.columns:
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
    )
    return diagnosis


def run_parallels_cli_table(command: list[str]) -> pd.DataFrame:
    try:
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 Parallels/Windows 通达信任务：{exc}") from exc
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
        raise RuntimeError(f"Parallels/Windows 通达信任务失败：{clean_parallels_cli_error(detail)}")
    return parse_cli_table(result.stdout)


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
        raise RuntimeError(f"Parallels/Windows 通达信任务失败：{clean_parallels_cli_error(detail)}")
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
    result = frame.rename(columns={"symbol": "stock_code", "rows": "rows_written"}).copy()
    result["timeframe"] = timeframe
    result["adjust"] = adjust
    result["action"] = "fetched"
    return result


def _symbol_batches(config: DataDownloadConfig) -> list[DataDownloadConfig]:
    batch_size = max(int(config.batch_size or 1), 1)
    symbols = list(config.symbols)
    return [
        DataDownloadConfig(
            symbols=tuple(symbols[index : index + batch_size]),
            timeframes=config.timeframes,
            start=config.start,
            end=config.end,
            tqcenter_path=config.tqcenter_path,
            batch_size=config.batch_size,
            min_coverage_ratio=config.min_coverage_ratio,
            strict_after_update=config.strict_after_update,
        )
        for index in range(0, len(symbols), batch_size)
    ]


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
