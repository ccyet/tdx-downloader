from __future__ import annotations

from pathlib import Path

import pandas as pd

from tdx_downloader.data import parallels_runtime
from tdx_downloader.data.manager import DataDownloadConfig, DataDownloadResult
from tdx_downloader.data.parallels_runtime import (
    download_with_runtime,
    parse_cli_table,
    parallels_doctor_command,
    parallels_prepare_command,
    shortcut_symbol_groups_with_runtime,
)


def test_parse_cli_table_prefers_json_records_with_unc_paths() -> None:
    stdout = (
        "TQ数据接口初始化成功\n"
        '[{"stock_code":"510300.SH","timeframe":"1d","action":"cached",'
        '"rows_written":0,"path":"\\\\\\\\psf\\\\ccOUT 1\\\\tdx-data\\\\daily\\\\qfq\\\\510300.SH.parquet",'
        '"message":"覆盖和质量检查通过。"}]\n'
        "TQ数据连接已关闭\n"
    )

    frame = parse_cli_table(stdout)

    assert frame.loc[0, "stock_code"] == "510300.SH"
    assert frame.loc[0, "action"] == "cached"
    assert frame.loc[0, "rows_written"] == 0
    assert frame.loc[0, "path"] == r"\\psf\ccOUT 1\tdx-data\daily\qfq\510300.SH.parquet"


def test_runtime_skips_parallels_when_smart_plan_is_fully_cached(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class LocalCachedService:
        data_root = Path("/Volumes/ccOUT 1/tdx-data/daily")
        adjust = "qfq"

        def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            return pd.DataFrame({"stock_code": ["000001.SZ"], "action": ["cached"]})

        def download(
            self,
            config: DataDownloadConfig,
            *,
            mode: str,
            progress_callback,
        ) -> DataDownloadResult:
            progress_callback({"stage": "fetch_skipped", "timeframe": "1d", "reason": "local_ok"})
            return DataDownloadResult(
                table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["1d"], "action": ["cached"]}),
                summary={"row_count": 1.0, "fetched_count": 0.0, "cached_count": 1.0},
            )

    def fail_parallels(*_: object, **__: object) -> DataDownloadResult:
        raise AssertionError("cached smart plan must not connect to Parallels/TDX")

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "download_with_parallels_cli", fail_parallels)
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        LocalCachedService(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 0.0
    assert [event["stage"] for event in events] == ["tdx_connection_skipped", "fetch_skipped"]


def test_parallels_commands_request_json_output() -> None:
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data/daily")
        adjust = "qfq"

    config = DataDownloadConfig(
        symbols=("000001.SZ",),
        timeframes=("1d",),
        start="2026-06-01",
        end="2026-06-02",
        tqcenter_path="/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user",
    )

    prepare = parallels_prepare_command(Service(), config)  # type: ignore[arg-type]
    doctor = parallels_doctor_command(Service(), config)  # type: ignore[arg-type]

    assert "--output" in prepare
    assert prepare[prepare.index("--output") + 1] == "json"
    assert doctor[-2:] == ["--output", "json"]
    assert "--data-root" not in doctor


def test_symbol_groups_runtime_uses_parallels_when_local_dynamic_groups_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    def local_groups(*_: object, **__: object) -> list[dict[str, object]]:
        return [{"name": "核心样例", "symbols": ["000001.SZ"]}]

    def windows_records(command: list[str]) -> list[dict[str, object]]:
        commands.append(command)
        return [
            {"name": "核心样例", "symbols": ["000001.SZ"]},
            {"name": "板块指数", "symbols": ["880001.SH"]},
            {"name": "全A股票", "symbols": ["000001.SZ", "600000.SH"]},
        ]

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "shortcut_symbol_groups", local_groups)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_records", windows_records)

    groups = shortcut_symbol_groups_with_runtime(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
    )

    assert {group["name"] for group in groups} >= {"板块指数", "全A股票"}
    assert commands[0][2:6] == ["tdx_downloader.cli", "symbol-groups", "--runtime", "parallels"]
    assert commands[0][-2:] == ["--output", "json"]


def test_symbol_groups_parallels_timeout_is_explicit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def timeout_run(command: list[str], **_: object) -> object:
        raise parallels_runtime.subprocess.TimeoutExpired(command, timeout=12)

    monkeypatch.setattr(parallels_runtime.subprocess, "run", timeout_run)

    try:
        parallels_runtime.run_parallels_cli_records(["python", "-m", "tdx_downloader.cli", "symbol-groups"])
    except RuntimeError as exc:
        assert "快捷代码表超时" in str(exc)
    else:
        raise AssertionError("timeout should be surfaced")
