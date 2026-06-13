from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tdx_downloader import cli
from tdx_downloader.cli import DEFAULT_DATA_ROOT, _forward_args, _metadata_symbols_by_asset_type
from tdx_downloader.data import tdx_parallels
from tdx_downloader.data.tdx_parallels import (
    ParallelsTdxConfig,
    build_parallels_tdx_command,
    cleanup_parallels_runner,
    mac_path_to_parallels_shared_path,
    PARALLELS_RUNNER_DIR_NAME,
    resolve_windows_python,
    run_parallels_tdx_command,
    start_parallels_tdx_worker,
    write_parallels_runner,
)


class _Args:
    command = "prepare-data"
    symbols = "000001.SZ"
    timeframes = "5m"
    start = "2026-06-01"
    end = "2026-06-02"
    adjust = "qfq"
    data_root = DEFAULT_DATA_ROOT
    tdx_path = ""
    batch_size = 100
    min_coverage_ratio = None
    allow_incomplete_after_update = False


class _SymbolGroupsArgs:
    command = "symbol-groups"
    data_root = DEFAULT_DATA_ROOT
    tdx_path = "/Volumes/[C] Windows 11/new_tdx64/PYPlugins"
    output = "json"


def test_default_data_root_points_to_external_tdx_data_root() -> None:
    assert DEFAULT_DATA_ROOT == "/Volumes/ccOUT 1/tdx-data"


def test_mac_volume_path_maps_to_parallels_mac_volume_share() -> None:
    mapped = mac_path_to_parallels_shared_path("/Volumes/ccOUT 1/tdx-data")

    assert mapped == r"\\psf\ccOUT 1\tdx-data"


def test_parallels_mounted_windows_drive_path_maps_back_to_drive_letter() -> None:
    mapped = mac_path_to_parallels_shared_path("/Volumes/[C] Windows 11/new_tdx64/T0002/dlls")

    assert mapped == r"C:\new_tdx64\T0002\dlls"


def test_forward_args_maps_default_data_root_for_windows_side_cli() -> None:
    forwarded = _forward_args(_Args())

    assert "--data-root" in forwarded
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"


def test_forward_args_maps_selected_parallels_tdx_path_to_windows_drive() -> None:
    args = _Args()
    args.tdx_path = "/Volumes/[C] Windows 11/new_tdx64/T0002/dlls"

    forwarded = _forward_args(args)

    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\T0002\dlls"


def test_forward_args_maps_symbol_groups_paths_for_windows_cli() -> None:
    forwarded = _forward_args(_SymbolGroupsArgs())

    assert forwarded[:3] == ["symbol-groups", "--runtime", "local"]
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"
    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\PYPlugins"
    assert forwarded[-2:] == ["--output", "json"]


def test_forward_args_maps_symbol_metadata_paths_for_windows_cli() -> None:
    args = _SymbolGroupsArgs()
    args.command = "symbol-metadata"

    forwarded = _forward_args(args)

    assert forwarded[:3] == ["symbol-metadata", "--runtime", "local"]
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"
    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\PYPlugins"
    assert forwarded[-2:] == ["--output", "json"]


def test_forward_args_preserves_asset_type_symbol_resolution_for_windows_cli() -> None:
    args = _Args()
    args.symbols = ""
    args.asset_types = "stock,etf"

    forwarded = _forward_args(args)

    assert forwarded[forwarded.index("--asset-types") + 1] == "stock,etf"
    assert forwarded[forwarded.index("--symbols") + 1] == ""


def test_cli_asset_type_symbols_use_local_metadata(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n"
        "000001.SZ,平安银行\n"
        "510300.SH,沪深300ETF\n"
        "000300.SH,沪深300\n",
        encoding="utf-8",
    )

    symbols = _metadata_symbols_by_asset_type(data_root=str(tmp_path), tdx_path="", asset_types=("stock", "etf"))

    assert symbols == ("000001.SZ", "510300.SH")


def test_cli_exposes_local_maintenance_commands(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_delta_summary(**kwargs: object) -> dict[str, object]:
        calls.append(("summary", kwargs))
        return {"summary": {"part_count": 2}, "by_timeframe": [{"timeframe": "5m", "part_count": 2}]}

    def fake_delta_compact(**kwargs: object) -> pd.DataFrame:
        calls.append(("compact", kwargs))
        return pd.DataFrame({"symbol": ["000001.SZ"], "status": ["success"]})

    def fake_coverage_refresh(**kwargs: object) -> pd.DataFrame:
        calls.append(("coverage", kwargs))
        return pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["5m"]})

    def fake_catalog_maintain(**kwargs: object) -> dict[str, object]:
        calls.append(("maintain", kwargs))
        return {"summary": {"ok": True}}

    monkeypatch.setattr(cli, "delta_sidecar_summary", fake_delta_summary)
    monkeypatch.setattr(cli, "compact_delta_sidecars", fake_delta_compact)
    monkeypatch.setattr(cli, "refresh_coverage_runs", fake_coverage_refresh)
    monkeypatch.setattr(cli, "maintain_catalog", fake_catalog_maintain)

    cli.main(["delta-summary", "--data-root", str(tmp_path), "--timeframes", "5m", "--output", "json"])
    cli.main(["delta-compact", "--data-root", str(tmp_path), "--timeframes", "5m", "--skip-coverage-refresh"])
    cli.main(["coverage-refresh", "--data-root", str(tmp_path), "--timeframes", "5m", "--symbols", "000001.SZ"])
    cli.main(["catalog-maintain", "--data-root", str(tmp_path)])

    assert [name for name, _ in calls] == ["summary", "compact", "coverage", "maintain"]
    assert calls[0][1]["timeframes"] == ("5m",)
    assert calls[1][1]["refresh_coverage"] is False
    assert calls[2][1]["symbols"] == ("000001.SZ",)
    assert calls[3][1]["vacuum"] is False
    assert "part_count" in capsys.readouterr().out


def test_cli_daily_check_reports_plan_and_risks(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def fake_resolve_download_symbols(args, *, timeframes):  # type: ignore[no-untyped-def]
        return ("000001.SZ", "000002.SZ")

    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ", "000002.SZ"],
                    "timeframe": ["5m", "5m"],
                    "action": ["fetch", "cached"],
                    "missing_rows": [48, 0],
                    "coverage_status": ["coverage_partial", "coverage_ready"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", fake_resolve_download_symbols)
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    cli.main(
        [
            "daily-check",
            "--data-root",
            str(tmp_path),
            "--timeframes",
            "5m",
            "--start",
            "2026-06-12",
            "--end",
            "2026-06-12",
        ]
    )

    output = capsys.readouterr().out
    assert "plan_fetch" in output
    assert "risk_count" in output


def test_cli_daily_check_fails_when_worker_is_unavailable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(columns=["action", "timeframe", "missing_rows", "coverage_status"])

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ",))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": False, "error": "down"})

    try:
        cli.main(
            [
                "daily-check",
                "--data-root",
                str(tmp_path),
                "--timeframes",
                "5m",
                "--start",
                "2026-06-12",
                "--end",
                "2026-06-12",
                "--output",
                "json",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("daily-check should fail when worker is unavailable")


def test_cli_daily_check_can_fail_on_remaining_fetch(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ"],
                    "timeframe": ["5m"],
                    "action": ["fetch"],
                    "missing_rows": [48],
                    "coverage_status": ["coverage_partial"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ",))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    try:
        cli.main(
            [
                "daily-check",
                "--data-root",
                str(tmp_path),
                "--timeframes",
                "5m",
                "--start",
                "2026-06-12",
                "--end",
                "2026-06-12",
                "--fail-on-fetch",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("post-download daily-check should fail on remaining fetch")


def test_cli_daily_check_can_fail_on_large_fetch_plan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ", "000002.SZ"],
                    "timeframe": ["5m", "5m"],
                    "action": ["fetch", "fetch"],
                    "missing_rows": [48, 48],
                    "coverage_status": ["coverage_partial", "coverage_partial"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ", "000002.SZ"))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    try:
        cli.main(
            [
                "daily-check",
                "--data-root",
                str(tmp_path),
                "--symbols",
                "000001.SZ,000002.SZ",
                "--timeframes",
                "5m",
                "--start",
                "2026-06-12",
                "--end",
                "2026-06-12",
                "--plan-fetch-threshold",
                "1",
                "--fail-on-large-fetch-plan",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("daily-check should fail when large fetch plan gate is enabled")


def test_cli_daily_check_can_fail_on_large_missing_plan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "timeframe": ["5m", "5m", "5m"],
                    "action": ["fetch", "derive", "unresolved"],
                    "missing_rows": [800, 300, 900],
                    "coverage_status": ["coverage_partial", "coverage_partial", "provider_unresolved"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ", "000002.SZ", "000003.SZ"))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    result = cli._daily_check(
        type(
            "Args",
            (),
            {
                "data_root": str(tmp_path),
                "adjust": "qfq",
                "timeframes": "5m",
                "symbols": "000001.SZ,000002.SZ,000003.SZ",
                "asset_types": "",
                "start": "2026-06-12",
                "end": "2026-06-12",
                "tdx_path": "",
                "worker_url": "",
                "delta_part_threshold": 200,
                "delta_byte_threshold": 268435456,
                "plan_fetch_threshold": 5000,
                "plan_missing_threshold": 1000,
                "fail_on_fetch": False,
                "fail_on_large_fetch_plan": False,
                "fail_on_large_missing_plan": True,
                "fail_on_coverage_unknown": False,
                "fail_on_unresolved_provider_gap": False,
            },
        )()
    )

    assert result["ok"] is False
    assert result["plan"]["fetch_missing_rows"] == 1100
    assert any(risk["code"] == "large_missing_plan" for risk in result["risks"])


def test_resolve_download_symbols_cached_primary_uses_non_daily_cached_universe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    catalog_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def cached_symbols(self, *, asset_types, timeframes, tdx_path):  # type: ignore[no-untyped-def]
            calls.append((tuple(asset_types), tuple(timeframes)))
            return ("000001.SZ",)

    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(
        cli,
        "_catalog_cached_symbols_by_asset_type",
        lambda *, data_root, adjust, asset_types, timeframes: catalog_calls.append((tuple(asset_types), tuple(timeframes))) or (),
    )
    monkeypatch.setattr(
        cli,
        "_metadata_symbols_by_asset_type",
        lambda **_: (_ for _ in ()).throw(AssertionError("cached-primary must not use metadata universe")),
    )

    symbols = cli._resolve_download_symbols(
        type(
            "Args",
            (),
            {
                "symbols": "",
                "asset_types": "stock,etf,index",
                "symbol_source": "cached-primary",
                "data_root": "/tmp/data",
                "adjust": "qfq",
                "tdx_path": "",
                "symbol_limit": 0,
                "symbol_offset": 0,
                "symbol_shard_count": 1,
                "symbol_shard_index": 0,
            },
        )(),
        timeframes=("1d", "5m"),
    )

    assert symbols == ("000001.SZ",)
    assert catalog_calls == [(("stock", "etf", "index"), ("5m",))]
    assert calls == [(("stock", "etf", "index"), ("5m",))]


def test_resolve_download_symbols_cached_primary_uses_catalog_fast_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_service(*_: object, **__: object) -> object:
        raise AssertionError("cached-primary should use catalog fast path when available")

    monkeypatch.setattr(cli, "DataManagementService", fail_service)
    monkeypatch.setattr(
        cli,
        "_catalog_cached_symbols_by_asset_type",
        lambda *, data_root, adjust, asset_types, timeframes: ("000002.SZ", "000001.SZ"),
    )

    symbols = cli._resolve_download_symbols(
        type(
            "Args",
            (),
            {
                "symbols": "",
                "asset_types": "stock",
                "symbol_source": "cached-primary",
                "data_root": "/tmp/data",
                "adjust": "qfq",
                "tdx_path": "",
                "symbol_limit": 0,
                "symbol_offset": 0,
                "symbol_shard_count": 1,
                "symbol_shard_index": 0,
            },
        )(),
        timeframes=("1d", "5m"),
    )

    assert symbols == ("000002.SZ", "000001.SZ")


def test_resolve_download_symbols_supports_shard_and_limit() -> None:
    symbols = cli._resolve_download_symbols(
        type(
            "Args",
            (),
            {
                "symbols": "000001.SZ,000002.SZ,000003.SZ,000004.SZ,000005.SZ",
                "asset_types": "",
                "symbol_source": "auto",
                "symbol_limit": 2,
                "symbol_offset": 1,
                "symbol_shard_count": 2,
                "symbol_shard_index": 1,
            },
        )(),
        timeframes=("5m",),
    )

    assert symbols == ("000004.SZ",)


def test_cli_daily_check_reports_unresolved_provider_gap_without_fetch_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ"],
                    "timeframe": ["5m"],
                    "action": ["unresolved"],
                    "missing_rows": [1],
                    "coverage_status": ["provider_unresolved"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ",))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    result = cli._daily_check(
        type(
            "Args",
            (),
            {
                "data_root": str(tmp_path),
                "adjust": "qfq",
                "timeframes": "5m",
                "symbols": "000001.SZ",
                "asset_types": "",
                "start": "2026-06-12",
                "end": "2026-06-12",
                "tdx_path": "",
                "worker_url": "",
                "delta_part_threshold": 200,
                "delta_byte_threshold": 268435456,
                "plan_fetch_threshold": 5000,
                "plan_missing_threshold": 1000000,
                "fail_on_fetch": True,
                "fail_on_large_fetch_plan": False,
                "fail_on_large_missing_plan": False,
                "fail_on_coverage_unknown": False,
                "fail_on_unresolved_provider_gap": False,
            },
        )()
    )

    assert result["ok"] is True
    assert result["plan"]["fetch_count"] == 0


def test_cli_prepare_data_uses_worker_runtime_on_macos(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []

    class FakeService:
        def __init__(self, data_root: str | Path, *, adjust: str) -> None:
            self.data_root = Path(data_root)
            self.adjust = adjust

        def cached_symbols(self, **_: object) -> tuple[str, ...]:
            return ("000001.SZ",)

    class FakeResult:
        table = pd.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "timeframe": ["5m"],
                "action": ["fetched"],
            }
        )

    def fail_run_in_parallels(_: object) -> None:
        raise AssertionError("prepare-data should use worker runtime, not prlctl CLI forwarding")

    def fake_download_with_runtime(service: object, config: object, *, mode: str, progress_callback=None) -> FakeResult:  # type: ignore[no-untyped-def]
        calls.append({"service": service, "config": config, "mode": mode})
        return FakeResult()

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "_run_in_parallels", fail_run_in_parallels)
    monkeypatch.setattr(cli, "download_with_runtime", fake_download_with_runtime)

    cli.main(
        [
            "prepare-data",
            "--asset-types",
            "stock",
            "--symbol-source",
            "cached-primary",
            "--timeframes",
            "1d,5m",
            "--start",
            "2026-06-12",
            "--end",
            "2026-06-12",
            "--data-root",
            str(tmp_path),
            "--runtime",
            "auto",
        ]
    )

    assert calls
    assert calls[0]["mode"] == "smart"


def test_cli_daily_check_can_fail_on_unresolved_provider_gap(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeService:
        def __init__(self, data_root: str, *, adjust: str) -> None:
            self.data_root = data_root
            self.adjust = adjust

        def preview_download_plan(self, config):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                {
                    "stock_code": ["000001.SZ"],
                    "timeframe": ["5m"],
                    "action": ["unresolved"],
                    "missing_rows": [1],
                    "coverage_status": ["provider_unresolved"],
                }
            )

    monkeypatch.setattr(cli, "_resolve_download_symbols", lambda args, *, timeframes: ("000001.SZ",))
    monkeypatch.setattr(cli, "DataManagementService", FakeService)
    monkeypatch.setattr(cli, "delta_sidecar_summary", lambda **_: {"summary": {"part_count": 0, "file_size_bytes": 0}})
    monkeypatch.setattr(cli, "maintain_catalog", lambda **_: {"after": {"freelist_count": 0, "wal_size_bytes": 0}})
    monkeypatch.setattr(cli, "_worker_health_for_daily_check", lambda _: {"ok": True, "status": "ok"})

    try:
        cli.main(
            [
                "daily-check",
                "--data-root",
                str(tmp_path),
                "--symbols",
                "000001.SZ",
                "--timeframes",
                "5m",
                "--start",
                "2026-06-12",
                "--end",
                "2026-06-12",
                "--fail-on-unresolved-provider-gap",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("daily-check should fail on unresolved provider gaps when requested")


def test_parallels_command_runs_windows_cli_inside_repo() -> None:
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    command = build_parallels_tdx_command(
        config=config,
        cli_args=["tdx-doctor", "--runtime", "local"],
        command_path=r"\\psf\ccOUT 1\tdx-downloader\.tdx-parallels\runner.cmd",
    )

    assert command == [
        "prlctl",
        "exec",
        "Windows 11",
        "--current-user",
        "cmd",
        "/d",
        "/s",
        "/c",
        r'"\\psf\ccOUT 1\tdx-downloader\.tdx-parallels\runner.cmd"',
    ]


def test_start_worker_rejects_psf_repo_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_vm_start(*_: object, **__: object):
        raise AssertionError("shared repo should fail before VM startup")

    monkeypatch.setattr(tdx_parallels, "_ensure_parallels_vm_running", fail_vm_start)

    result = start_parallels_tdx_worker(
        config=ParallelsTdxConfig(
            vm_name="Windows 11",
            windows_python=r"C:\Python313\python.exe",
            windows_repo=r"\\psf\Home\tdx-downloader",
        )
    )

    assert result.returncode == 2
    assert "禁止用 \\\\psf 启动常驻 Worker" in result.stderr


def test_parallels_runner_payload_preserves_spaces_and_unicode(tmp_path: Path) -> None:
    cwd = tmp_path / "tdx repo"
    cwd.mkdir()
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\中文 repo\tdx-downloader",
    )

    files = write_parallels_runner(
        config=config,
        cli_args=[
            "symbol-groups",
            "--runtime",
            "local",
            "--data-root",
            r"\\psf\ccOUT 1\tdx-data",
            "--tdx-path",
            r"C:\new_tdx64\PYPlugins\user",
        ],
        cwd=cwd,
    )

    try:
        payload = json.loads(files.payload_path.read_text(encoding="utf-8"))
        command_text = files.command_path.read_text(encoding="utf-8")
    finally:
        cleanup_parallels_runner(files)

    assert payload["windows_repo"] == r"\\psf\ccOUT 1\中文 repo\tdx-downloader"
    assert payload["cli_args"][-1] == r"C:\new_tdx64\PYPlugins\user"
    assert str(files.runner_path).endswith(f"tdx repo/.tdx-parallels/{files.runner_path.name}")
    assert "chcp 65001" in command_text
    assert "PYTHONUTF8=1" in command_text
    assert r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe" in command_text
    assert not files.runner_path.exists()
    assert not files.payload_path.exists()
    assert not files.command_path.exists()


def test_run_parallels_tdx_command_starts_vm_before_exec(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"] and len(calls) == 1:
            return _Process(command, stdout=b"VM 'Windows 11' is suspended\n")
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:2] == ["prlctl", "start"]:
            return _Process(command)
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_probe_" in command[-1]:
            return _Process(command, stdout=b"C:\\ProgramData\\miniconda3\\python.exe\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_setup_" in command[-1]:
            return _Process(
                command,
                stdout=b"__TDX_WINDOWS_PYTHON__=C:\\Users\\Public\\venvs\\tdx-downloader\\Scripts\\python.exe\n",
            )
        if command[:2] == ["prlctl", "exec"]:
            return _Process(command, stdout=b"ok\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = run_parallels_tdx_command(config=config, cli_args=["tdx-doctor", "--runtime", "local"])

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert calls[0] == ["prlctl", "status", "Windows 11"]
    assert calls[1] == ["prlctl", "start", "Windows 11"]
    assert calls[2] == ["prlctl", "status", "Windows 11"]
    assert "tdx_python_probe_" in calls[3][-1]
    assert "tdx_python_setup_" in calls[4][-1]
    assert calls[5][:4] == ["prlctl", "exec", "Windows 11", "--current-user"]


def test_streaming_subprocess_collects_stdout_and_filters_progress(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeProcess:
        stdout = [b'[{"status":"ok"}]\n']
        stderr = [b'__TDX_PROGRESS__={"stage":"x"}\n', "warning\n".encode("utf-8")]

        def __init__(self, command: list[str], **_: object) -> None:
            self.command = command

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(tdx_parallels.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(*args, **kwargs))
    result = tdx_parallels._run_streaming_subprocess(["prlctl", "exec"])  # noqa: SLF001

    assert result.returncode == 0
    assert result.stdout == '[{"status":"ok"}]\n'
    assert result.stderr == "warning\n"


def test_run_parallels_tdx_command_waits_when_start_reports_resuming(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"] and len(calls) == 1:
            return _Process(command, stdout=b"VM 'Windows 11' is suspended\n")
        if command[:2] == ["prlctl", "start"]:
            return _Process(
                command,
                returncode=1,
                stderr=(
                    b'Failed to start the VM: Unable to complete the operation. '
                    b'This operation cannot be completed because "Windows 11" is in the "resuming" state. '
                    b"Starting the VM...\n"
                ),
            )
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_probe_" in command[-1]:
            return _Process(command, stdout=b"C:\\ProgramData\\miniconda3\\python.exe\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_setup_" in command[-1]:
            return _Process(
                command,
                stdout=b"__TDX_WINDOWS_PYTHON__=C:\\Users\\Public\\venvs\\tdx-downloader\\Scripts\\python.exe\n",
            )
        if command[:2] == ["prlctl", "exec"]:
            return _Process(command, stdout=b"ok\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.setattr(tdx_parallels.time, "sleep", lambda _: None)
    monkeypatch.chdir(tmp_path)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = run_parallels_tdx_command(config=config, cli_args=["symbol-groups", "--runtime", "local"])

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert calls[0] == ["prlctl", "status", "Windows 11"]
    assert calls[1] == ["prlctl", "start", "Windows 11"]
    assert calls[2] == ["prlctl", "status", "Windows 11"]
    assert "tdx_python_probe_" in calls[3][-1]
    assert "tdx_python_setup_" in calls[4][-1]
    assert calls[5][:4] == ["prlctl", "exec", "Windows 11", "--current-user"]


def test_resolve_windows_python_discovers_miniconda_when_default_missing(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_probe_" in command[-1]:
            return _Process(
                command,
                stdout=(
                    b"C:\\Users\\a1234\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe\n"
                    b"C:\\ProgramData\\miniconda3\\python.exe\n"
                ),
            )
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_setup_" in command[-1]:
            return _Process(
                command,
                stdout=b"__TDX_WINDOWS_PYTHON__=C:\\Users\\Public\\venvs\\tdx-downloader\\Scripts\\python.exe\n",
            )
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = resolve_windows_python(config)

    assert result.returncode == 0
    assert result.stdout == r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe"
    assert "tdx_python_probe_" in calls[0][-1]
    assert "tdx_python_setup_" in calls[1][-1]


def test_resolve_windows_python_reuses_cached_default_runtime(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cache_dir = tmp_path / PARALLELS_RUNNER_DIR_NAME
    cache_dir.mkdir()
    (cache_dir / "runtime-cache.json").write_text(
        json.dumps(
            {
                "vm_name": "Windows 11",
                "windows_repo": r"\\psf\ccOUT 1\tdx-downloader",
                "bootstrap_python": r"C:\ProgramData\miniconda3\python.exe",
                "windows_python": r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "if exist" in command[-1]:
            return _Process(command)
        raise AssertionError(command)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = resolve_windows_python(config)

    assert result.returncode == 0
    assert result.stdout == r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe"
    assert len(calls) == 1
    assert "tdx_python_probe_" not in calls[0][-1]
    assert "tdx_python_setup_" not in calls[0][-1]


def test_resolve_windows_python_keeps_explicit_python_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "if exist" in command[-1]:
            return _Process(command)
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"D:\Python\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = resolve_windows_python(config)

    assert result.returncode == 0
    assert result.stdout == r"D:\Python\python.exe"
    assert len(calls) == 1
    assert "where python" not in calls[0][-1]


def test_resolve_windows_python_reports_default_venv_setup_failure(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    def fake_run(command: list[str], **_: object) -> object:
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_probe_" in command[-1]:
            return _Process(command, stdout=b"C:\\ProgramData\\miniconda3\\python.exe\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "tdx_python_setup_" in command[-1]:
            return _Process(command, returncode=1, stderr=b"pip failed\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = resolve_windows_python(config)

    assert result.returncode == 1
    assert "Windows Python 环境初始化失败" in result.stderr
    assert r"C:\ProgramData\miniconda3\python.exe" in result.stderr
    assert "pip failed" in result.stderr


def test_run_parallels_tdx_command_reports_missing_windows_python(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "if exist" in command[-1]:
            return _Process(command, returncode=1)
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\missing-python\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = run_parallels_tdx_command(config=config, cli_args=["symbol-groups", "--runtime", "local"])

    assert result.returncode == 1
    assert "Windows Python 不可用" in result.stderr
    assert "TDX_PARALLELS_PYTHON" in result.stderr
    assert len(calls) == 2
    assert calls[0] == ["prlctl", "status", "Windows 11"]
    assert "if exist C:\\missing-python\\python.exe" in calls[1][-1]


def test_start_parallels_tdx_worker_uses_background_cmd(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"] and "if exist" in command[-1]:
            return _Process(command)
        if command[:2] == ["prlctl", "exec"]:
            return _Process(command, stdout=b"started\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"D:\Python\python.exe",
        windows_repo=r"C:\tdx-downloader-app",
        worker_scratch=r"C:\tdx_jobs",
    )

    result = start_parallels_tdx_worker(config=config, port=8765)

    assert result.returncode == 0
    command_files = list((tmp_path / PARALLELS_RUNNER_DIR_NAME).glob("*.cmd"))
    assert command_files
    text = command_files[-1].read_text(encoding="utf-8")
    assert 'start "tdx-worker" /min cmd.exe' in text
    assert "tdx-worker" in (tmp_path / PARALLELS_RUNNER_DIR_NAME).joinpath(command_files[-1].with_suffix(".json").name).read_text(encoding="utf-8")
    assert calls[-1][:4] == ["prlctl", "exec", "Windows 11", "--current-user"]


def test_home_path_still_maps_to_parallels_home_share() -> None:
    mapped = mac_path_to_parallels_shared_path("/Users/a1234/Desktop/project", home=Path("/Users/a1234"))

    assert mapped == r"\\psf\Home\Desktop\project"


class _Process:
    def __init__(
        self,
        args: list[str],
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
