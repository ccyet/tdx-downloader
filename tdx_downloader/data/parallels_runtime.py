from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys

import pandas as pd

from tdx_downloader.data.manager import DataDownloadConfig, DataDownloadResult, DataManagementService, download_summary


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
        return download_with_parallels_cli(service, config, mode=mode)
    return service.download(config, mode=mode, progress_callback=progress_callback)


def download_with_parallels_cli(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
) -> DataDownloadResult:
    if mode == "smart":
        table = run_parallels_cli_table(parallels_prepare_command(service, config))
    elif mode == "force":
        frames = [
            force_cli_frame(
                run_parallels_cli_table(parallels_fetch_command(service, config, timeframe)),
                timeframe=timeframe,
                adjust=service.adjust,
            )
            for timeframe in config.timeframes
        ]
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        raise RuntimeError(f"未知下载方式：{mode}")
    return DataDownloadResult(table=table, summary=download_summary(table))


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
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    try:
        return pd.read_csv(io.StringIO(normalized), sep=r"\s{2,}", engine="python")
    except Exception as exc:
        raise RuntimeError(f"Parallels/Windows 任务已返回，但结果表解析失败：{exc}") from exc


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
    ]


def force_cli_frame(frame: pd.DataFrame, *, timeframe: str, adjust: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["stock_code", "timeframe", "adjust", "action", "rows_written", "new_rows"])
    result = frame.rename(columns={"symbol": "stock_code", "rows": "rows_written"}).copy()
    result["timeframe"] = timeframe
    result["adjust"] = adjust
    result["action"] = "fetched"
    return result
