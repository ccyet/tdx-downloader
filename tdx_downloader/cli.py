from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from tdx_downloader.data.catalog import infer_asset_type, maintain_catalog, query_catalog, refresh_coverage_runs
from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataManagementService,
    normalize_symbol_tuple,
    shortcut_symbol_groups,
)
from tdx_downloader.data.parallels_runtime import download_with_runtime
from tdx_downloader.data.repository import MarketDataRepository
from tdx_downloader.data.schema import normalize_symbol
from tdx_downloader.data.storage import compact_delta_sidecars, delta_sidecar_summary
from tdx_downloader.data.symbols import load_symbol_metadata
from tdx_downloader.data.tdx import DEFAULT_ETF_TRACKING_INDEX_SYMBOLS, diagnose_tdx_source, fetch_tdx_etf_tracking_info
from tdx_downloader.data.tdx_parallels import (
    ParallelsTdxConfig,
    PARALLELS_PROGRESS_ENV_VAR,
    PARALLELS_PROGRESS_PREFIX,
    default_parallels_tdx_config,
    mac_path_to_parallels_shared_path,
    run_parallels_tdx_command,
)
from tdx_downloader.data.tdx_worker import DEFAULT_WORKER_HOST, DEFAULT_WORKER_PORT, DEFAULT_WORKER_SCRATCH, run_worker
from tdx_downloader.data.tdx_worker_client import TdxWorkerClient, WorkerUnavailable
from tdx_downloader.data.trading_calendar import save_trading_days

DEFAULT_DATA_ROOT = "/Volumes/ccOUT 1/tdx-data"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TDX Downloader data toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("tdx-doctor", help="diagnose tqcenter import and sample K-line requests")
    doctor_parser.add_argument("--symbols", required=True)
    doctor_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    doctor_parser.add_argument("--start", required=True)
    doctor_parser.add_argument("--end", required=True)
    doctor_parser.add_argument("--adjust", default="qfq")
    doctor_parser.add_argument("--tdx-path", default="")
    doctor_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(doctor_parser)

    fetch_parser = subparsers.add_parser("fetch", help="force fetch one timeframe from TDX")
    fetch_parser.add_argument("--symbols", default="")
    fetch_parser.add_argument(
        "--asset-types",
        default="",
        help="resolve symbols from local metadata/catalog, e.g. stock,etf,index",
    )
    fetch_parser.add_argument("--symbol-source", choices=["auto", "metadata", "cached", "cached-primary"], default="auto")
    _add_symbol_slice_args(fetch_parser)
    fetch_parser.add_argument("--timeframe", required=True, choices=["1d", "1m", "5m", "15m", "30m", "60m"])
    fetch_parser.add_argument("--start", required=True)
    fetch_parser.add_argument("--end", required=True)
    fetch_parser.add_argument("--adjust", default="qfq")
    fetch_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    fetch_parser.add_argument("--tdx-path", default="")
    fetch_parser.add_argument("--batch-size", type=int, default=100)
    fetch_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(fetch_parser)

    prepare_parser = subparsers.add_parser("prepare-data", help="audit local cache and fetch only missing/bad bars")
    prepare_parser.add_argument("--symbols", default="")
    prepare_parser.add_argument(
        "--asset-types",
        default="",
        help="resolve symbols from local metadata/catalog, e.g. stock,etf,index",
    )
    prepare_parser.add_argument("--symbol-source", choices=["auto", "metadata", "cached", "cached-primary"], default="auto")
    _add_symbol_slice_args(prepare_parser)
    prepare_parser.add_argument("--timeframes", required=True)
    prepare_parser.add_argument("--start", required=True)
    prepare_parser.add_argument("--end", required=True)
    prepare_parser.add_argument("--adjust", default="qfq")
    prepare_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    prepare_parser.add_argument("--tdx-path", default="")
    prepare_parser.add_argument("--batch-size", type=int, default=100)
    prepare_parser.add_argument("--min-coverage-ratio", type=float, default=None)
    prepare_parser.add_argument("--allow-incomplete-after-update", action="store_true")
    prepare_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(prepare_parser)

    plan_parser = subparsers.add_parser("plan-data", help="audit local cache and print the fetch plan")
    plan_parser.add_argument("--symbols", default="")
    plan_parser.add_argument(
        "--asset-types",
        default="",
        help="resolve symbols from local metadata/catalog, e.g. stock,etf,index",
    )
    plan_parser.add_argument("--symbol-source", choices=["auto", "metadata", "cached", "cached-primary"], default="auto")
    _add_symbol_slice_args(plan_parser)
    plan_parser.add_argument("--timeframes", required=True)
    plan_parser.add_argument("--start", required=True)
    plan_parser.add_argument("--end", required=True)
    plan_parser.add_argument("--adjust", default="qfq")
    plan_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    plan_parser.add_argument("--tdx-path", default="")
    plan_parser.add_argument("--min-coverage-ratio", type=float, default=None)

    inventory_parser = subparsers.add_parser("inventory-data", help="list local parquet cache inventory")
    inventory_parser.add_argument("--symbols", default="")
    inventory_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    inventory_parser.add_argument("--adjust", default="qfq")
    inventory_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)

    delta_summary_parser = subparsers.add_parser("delta-summary", help="summarize append-only delta sidecars")
    delta_summary_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    delta_summary_parser.add_argument("--adjust", default="qfq")
    delta_summary_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    delta_summary_parser.add_argument("--part-threshold", type=int, default=200)
    delta_summary_parser.add_argument("--byte-threshold", type=int, default=268435456)
    delta_summary_parser.add_argument("--output", choices=["table", "json"], default="table")

    delta_compact_parser = subparsers.add_parser("delta-compact", help="merge delta sidecars into base parquet files")
    delta_compact_parser.add_argument("--symbols", default="")
    delta_compact_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    delta_compact_parser.add_argument("--adjust", default="qfq")
    delta_compact_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    delta_compact_parser.add_argument("--skip-coverage-refresh", action="store_true")
    delta_compact_parser.add_argument("--output", choices=["table", "json"], default="table")

    coverage_refresh_parser = subparsers.add_parser("coverage-refresh", help="refresh precise K-line coverage runs")
    coverage_refresh_parser.add_argument("--symbols", default="")
    coverage_refresh_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    coverage_refresh_parser.add_argument("--adjust", default="qfq")
    coverage_refresh_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    coverage_refresh_parser.add_argument("--output", choices=["table", "json"], default="table")

    catalog_maintain_parser = subparsers.add_parser("catalog-maintain", help="run SQLite catalog maintenance")
    catalog_maintain_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    catalog_maintain_parser.add_argument("--vacuum", action="store_true")
    catalog_maintain_parser.add_argument("--output", choices=["table", "json"], default="table")

    daily_check_parser = subparsers.add_parser("daily-check", help="preflight daily update risk without downloading")
    daily_check_parser.add_argument("--symbols", default="")
    daily_check_parser.add_argument(
        "--asset-types",
        default="stock,etf,index",
        help="resolve symbols from local metadata/catalog, e.g. stock,etf,index",
    )
    daily_check_parser.add_argument("--symbol-source", choices=["auto", "metadata", "cached", "cached-primary"], default="auto")
    _add_symbol_slice_args(daily_check_parser)
    daily_check_parser.add_argument("--timeframes", default="1d,5m")
    daily_check_parser.add_argument("--start", required=True)
    daily_check_parser.add_argument("--end", required=True)
    daily_check_parser.add_argument("--adjust", default="qfq")
    daily_check_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    daily_check_parser.add_argument("--tdx-path", default="")
    daily_check_parser.add_argument("--worker-url", default="")
    daily_check_parser.add_argument("--delta-part-threshold", type=int, default=200)
    daily_check_parser.add_argument("--delta-byte-threshold", type=int, default=268435456)
    daily_check_parser.add_argument("--plan-fetch-threshold", type=int, default=5000)
    daily_check_parser.add_argument("--plan-missing-threshold", type=int, default=400000)
    daily_check_parser.add_argument("--fail-on-fetch", action="store_true")
    daily_check_parser.add_argument("--fail-on-large-fetch-plan", action="store_true")
    daily_check_parser.add_argument("--fail-on-large-missing-plan", action="store_true")
    daily_check_parser.add_argument("--fail-on-coverage-unknown", action="store_true")
    daily_check_parser.add_argument("--fail-on-unresolved-provider-gap", action="store_true")
    daily_check_parser.add_argument("--output", choices=["table", "json"], default="table")

    trading_calendar_parser = subparsers.add_parser("trading-calendar-sync", help="sync A-share trading calendar from Fuyao/THS")
    trading_calendar_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    trading_calendar_parser.add_argument("--api-key", default="")
    trading_calendar_parser.add_argument("--skip-without-key", action="store_true")
    trading_calendar_parser.add_argument("--output", choices=["table", "json"], default="table")

    trading_calendar_import_parser = subparsers.add_parser("trading-calendar-import", help="import A-share trading calendar from local dates")
    trading_calendar_import_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    trading_calendar_import_parser.add_argument("--days", default="", help="comma/space/newline separated dates, e.g. 2026-06-12,20260615")
    trading_calendar_import_parser.add_argument("--file", default="", help="local text/json file containing trading dates")
    trading_calendar_import_parser.add_argument("--source", default="manual")
    trading_calendar_import_parser.add_argument("--output", choices=["table", "json"], default="table")

    groups_parser = subparsers.add_parser("symbol-groups", help="list shortcut symbol groups from local TDX metadata")
    groups_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    groups_parser.add_argument("--tdx-path", default="")
    groups_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(groups_parser)

    metadata_parser = subparsers.add_parser("symbol-metadata", help="list symbol names from local TDX metadata")
    metadata_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    metadata_parser.add_argument("--tdx-path", default="")
    metadata_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(metadata_parser)

    etf_tracking_parser = subparsers.add_parser("etf-tracking", help="list ETFs tracking given TDX index symbols")
    etf_tracking_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    etf_tracking_parser.add_argument("--tdx-path", default="")
    etf_tracking_parser.add_argument("--index-symbols", default=",".join(DEFAULT_ETF_TRACKING_INDEX_SYMBOLS))
    etf_tracking_parser.add_argument("--output", choices=["table", "json"], default="table")
    _add_runtime_args(etf_tracking_parser)

    indicator_formulas_parser = subparsers.add_parser("indicator-formulas", help="list registered indicator formulas")
    indicator_formulas_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    indicator_formulas_parser.add_argument("--output", choices=["table", "json"], default="table")

    indicator_import_parser = subparsers.add_parser("indicator-import-tdx", help="import TDX indicator formula text")
    indicator_import_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    indicator_import_parser.add_argument("--file", required=True)
    indicator_import_parser.add_argument("--formula-id-prefix", default="")
    indicator_import_parser.add_argument("--output", choices=["table", "json"], default="table")

    indicator_compute_parser = subparsers.add_parser("indicator-compute", help="compute and cache indicators")
    indicator_compute_parser.add_argument("--symbols", default="")
    indicator_compute_parser.add_argument("--formula-ids", required=True)
    indicator_compute_parser.add_argument("--timeframe", default="1d", choices=["1d", "1m", "5m", "15m", "30m", "60m"])
    indicator_compute_parser.add_argument("--start", required=True)
    indicator_compute_parser.add_argument("--end", required=True)
    indicator_compute_parser.add_argument("--adjust", default="qfq")
    indicator_compute_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    indicator_compute_parser.add_argument("--force", action="store_true")
    indicator_compute_parser.add_argument("--output", choices=["table", "json"], default="table")

    worker_parser = subparsers.add_parser("tdx-worker", help="run the persistent Windows TDX worker service")
    worker_parser.add_argument("--host", default=DEFAULT_WORKER_HOST)
    worker_parser.add_argument("--port", type=int, default=DEFAULT_WORKER_PORT)
    worker_parser.add_argument("--scratch-root", default=DEFAULT_WORKER_SCRATCH)

    args = parser.parse_args(argv)
    parallels_commands = {"tdx-doctor", "symbol-groups", "symbol-metadata", "etf-tracking"}
    if args.command in parallels_commands and _resolve_runtime(args.runtime) == "parallels":
        _run_in_parallels(args)
        return

    if args.command == "symbol-groups":
        _print_symbol_groups(
            shortcut_symbol_groups(data_root=args.data_root, tdx_path=args.tdx_path),
            args.output,
        )
        return

    if args.command == "symbol-metadata":
        _print_frame(load_symbol_metadata(args.data_root, tdx_path=args.tdx_path), args.output)
        return

    if args.command == "etf-tracking":
        _print_frame(
            fetch_tdx_etf_tracking_info(
                index_symbols=_split_csv(args.index_symbols),
                tqcenter_path=args.tdx_path,
            ),
            args.output,
        )
        return

    if args.command == "indicator-formulas":
        service = DataManagementService(args.data_root)
        _print_frame(service.list_indicator_formulas(), args.output)
        return

    if args.command == "tdx-worker":
        run_worker(host=args.host, port=int(args.port), scratch_root=args.scratch_root)
        return

    if args.command == "indicator-import-tdx":
        service = DataManagementService(args.data_root)
        formulas = service.import_tdx_indicator_formulas(
            Path(args.file).expanduser().read_text(encoding="utf-8"),
            formula_id_prefix=args.formula_id_prefix,
        )
        _print_frame(_objects_frame([formula.__dict__ for formula in formulas]), args.output)
        return

    if args.command == "tdx-doctor":
        symbols = _split_csv(args.symbols)
        progress = _progress_callback()
        if progress is not None:
            progress(
                {
                    "stage": "tdx_doctor_start",
                    "message": "开始 Windows 侧 TDX 连接诊断。",
                    "symbol_count": len(symbols),
                    "timeframe_count": len(_split_csv(args.timeframes)),
                }
            )
        result = diagnose_tdx_source(
            symbols=symbols,
            timeframes=_split_csv(args.timeframes),
            start=args.start,
            end=args.end,
            adjust=args.adjust,
            tqcenter_path=args.tdx_path,
        )
        if progress is not None:
            progress(
                {
                    "stage": "tdx_doctor_done",
                    "message": "Windows 侧 TDX 连接诊断完成。",
                    "row_count": len(result),
                }
            )
        _print_frame(result, args.output)
        return

    if args.command == "delta-summary":
        result = delta_sidecar_summary(
            data_root=args.data_root,
            adjust=args.adjust,
            timeframes=_split_csv(args.timeframes),
            part_threshold=int(args.part_threshold),
            byte_threshold=int(args.byte_threshold),
        )
        _print_mapping(result, args.output)
        return

    if args.command == "delta-compact":
        frames = []
        symbols = _split_csv(args.symbols)
        for timeframe in _split_csv(args.timeframes):
            result = compact_delta_sidecars(
                data_root=args.data_root,
                timeframe=timeframe,
                adjust=args.adjust,
                symbols=symbols or None,
                refresh_coverage=not bool(args.skip_coverage_refresh),
            )
            if not result.empty:
                result = result.copy()
                result["timeframe"] = timeframe
                result["adjust"] = args.adjust
                frames.append(result)
        _print_frame(_concat_frames(frames), args.output)
        return

    if args.command == "coverage-refresh":
        result = refresh_coverage_runs(
            data_root=args.data_root,
            adjust=args.adjust,
            timeframes=_split_csv(args.timeframes),
            symbols=_split_csv(args.symbols) or None,
        )
        _print_frame(result, args.output)
        return

    if args.command == "catalog-maintain":
        result = maintain_catalog(data_root=args.data_root, vacuum=bool(args.vacuum))
        _print_mapping(result, args.output)
        return

    if args.command == "daily-check":
        result = _daily_check(args)
        _print_daily_check(result, args.output)
        if not bool(result.get("ok")):
            raise SystemExit(2)
        return

    if args.command == "trading-calendar-sync":
        result = _sync_trading_calendar(args)
        _print_mapping(result, args.output)
        if not bool(result.get("ok")):
            raise SystemExit(2)
        return

    if args.command == "trading-calendar-import":
        result = _import_trading_calendar(args)
        _print_mapping(result, args.output)
        if not bool(result.get("ok")):
            raise SystemExit(2)
        return

    repo = MarketDataRepository(Path(args.data_root), adjust=args.adjust)
    if args.command == "inventory-data":
        symbols = _split_csv(args.symbols)
        result = repo.inventory(timeframes=_split_csv(args.timeframes), symbols=symbols or None)
        print(result.to_string(index=False))
        return

    if args.command == "fetch":
        progress = _progress_callback()
        symbols = _resolve_download_symbols(args, timeframes=(args.timeframe,))
        if _resolve_runtime(args.runtime) == "parallels":
            service = DataManagementService(Path(args.data_root), adjust=args.adjust)
            config = DataDownloadConfig(
                symbols=normalize_symbol_tuple(symbols),
                timeframes=(args.timeframe,),
                start=args.start,
                end=args.end,
                tqcenter_path=args.tdx_path,
                batch_size=max(int(args.batch_size), 1),
            )
            result = download_with_runtime(service, config, mode="force", progress_callback=progress)
            _print_frame(result.table, args.output)
            return
        result = repo.update_from_tdx(
            symbols=symbols,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            tqcenter_path=args.tdx_path,
            batch_size=max(int(args.batch_size), 1),
            progress_callback=progress,
        )
        _print_frame(result, args.output)
        return

    if args.command == "indicator-compute":
        service = DataManagementService(Path(args.data_root), adjust=args.adjust)
        symbols = _split_csv(args.symbols)
        if not symbols:
            raise SystemExit("请提供 --symbols。")
        result = service.compute_indicators(
            symbols=symbols,
            formula_ids=_split_csv(args.formula_ids),
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            force=bool(args.force),
        )
        _print_frame(result, args.output)
        return

    service = DataManagementService(Path(args.data_root), adjust=args.adjust)
    timeframes = _split_csv(args.timeframes)
    symbols = _resolve_download_symbols(args, timeframes=timeframes)
    config = DataDownloadConfig(
        symbols=normalize_symbol_tuple(symbols),
        timeframes=timeframes,
        start=args.start,
        end=args.end,
        tqcenter_path=getattr(args, "tdx_path", ""),
        batch_size=max(int(getattr(args, "batch_size", 100)), 1),
        min_coverage_ratio=args.min_coverage_ratio,
        strict_after_update=not bool(getattr(args, "allow_incomplete_after_update", False)),
    )
    if args.command == "prepare-data":
        if _resolve_runtime(args.runtime) == "parallels":
            result = download_with_runtime(service, config, mode="smart", progress_callback=_progress_callback())
        else:
            result = service.download(config, mode="smart", progress_callback=_progress_callback())
        _print_frame(result.table, args.output)
        return
    if args.command == "plan-data":
        print(service.download_plan(config).to_string(index=False))
        return

    raise SystemExit(f"unknown command: {args.command}")


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime",
        choices=["auto", "local", "parallels"],
        default="auto",
        help="TDX runtime; macOS auto dispatches to Parallels, Windows/Linux use local.",
    )
    parser.add_argument("--parallels-vm", default="")
    parser.add_argument("--windows-python", default="")
    parser.add_argument("--windows-repo", default="")


def _add_symbol_slice_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol-limit", type=int, default=0)
    parser.add_argument("--symbol-offset", type=int, default=0)
    parser.add_argument("--symbol-shard-count", type=int, default=1)
    parser.add_argument("--symbol-shard-index", type=int, default=0)


def _resolve_runtime(runtime: str) -> str:
    if runtime == "auto":
        return "parallels" if sys.platform == "darwin" else "local"
    return runtime


def _run_in_parallels(args: argparse.Namespace) -> None:
    default = default_parallels_tdx_config(cwd=Path.cwd())
    config = ParallelsTdxConfig(
        vm_name=args.parallels_vm or default.vm_name,
        windows_python=args.windows_python or default.windows_python,
        windows_repo=args.windows_repo or default.windows_repo,
    )
    result = run_parallels_tdx_command(config=config, cli_args=_forward_args(args))
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _forward_args(args: argparse.Namespace) -> list[str]:
    forwarded = [args.command, "--runtime", "local"]
    for name in (
        "symbols",
        "timeframes",
        "timeframe",
        "start",
        "end",
        "adjust",
        "data_root",
        "tdx_path",
        "index_symbols",
        "asset_types",
        "symbol_source",
        "symbol_limit",
        "symbol_offset",
        "symbol_shard_count",
        "symbol_shard_index",
        "output",
    ):
        if not hasattr(args, name):
            continue
        value = str(getattr(args, name))
        if name in {"data_root", "tdx_path"}:
            value = mac_path_to_parallels_shared_path(value)
        forwarded.extend([f"--{name.replace('_', '-')}", value])
    if hasattr(args, "batch_size"):
        forwarded.extend(["--batch-size", str(args.batch_size)])
    if getattr(args, "min_coverage_ratio", None) is not None:
        forwarded.extend(["--min-coverage-ratio", str(args.min_coverage_ratio)])
    if getattr(args, "allow_incomplete_after_update", False):
        forwarded.append("--allow-incomplete-after-update")
    return forwarded


def _resolve_download_symbols(args: argparse.Namespace, *, timeframes: tuple[str, ...]) -> tuple[str, ...]:
    explicit = _split_csv(getattr(args, "symbols", ""))
    if explicit:
        return _slice_symbols(explicit, args)
    asset_types = _split_csv(getattr(args, "asset_types", ""))
    if not asset_types:
        raise SystemExit("请提供 --symbols，或使用 --asset-types 从本地代码表/缓存自动选择标的。")
    symbol_source = str(getattr(args, "symbol_source", "auto") or "auto")
    if symbol_source in {"cached", "cached-primary"}:
        symbols = _cached_symbols_by_asset_type(args, asset_types=asset_types, timeframes=timeframes, primary_only=symbol_source == "cached-primary")
        if symbols:
            return _slice_symbols(symbols, args)
        raise SystemExit(f"未从本地缓存中找到资产类型：{','.join(asset_types)}")
    if symbol_source in {"auto", "metadata"}:
        symbols = _metadata_symbols_by_asset_type(
            data_root=getattr(args, "data_root", DEFAULT_DATA_ROOT),
            tdx_path=getattr(args, "tdx_path", ""),
            asset_types=asset_types,
        )
        if symbols:
            return _slice_symbols(symbols, args)
        if symbol_source == "metadata":
            raise SystemExit(f"未从本地代码表中找到资产类型：{','.join(asset_types)}")
    symbols = _cached_symbols_by_asset_type(args, asset_types=asset_types, timeframes=timeframes, primary_only=False)
    if symbols:
        return _slice_symbols(symbols, args)
    return _raise_no_symbols(asset_types)


def _slice_symbols(symbols: tuple[str, ...], args: argparse.Namespace) -> tuple[str, ...]:
    shard_count = max(int(getattr(args, "symbol_shard_count", 1) or 1), 1)
    shard_index = int(getattr(args, "symbol_shard_index", 0) or 0)
    if shard_index < 0 or shard_index >= shard_count:
        raise SystemExit(f"--symbol-shard-index 必须在 0 到 {shard_count - 1} 之间。")
    result = tuple(symbols[index] for index in range(shard_index, len(symbols), shard_count))
    offset = max(int(getattr(args, "symbol_offset", 0) or 0), 0)
    limit = int(getattr(args, "symbol_limit", 0) or 0)
    if offset:
        result = result[offset:]
    if limit > 0:
        result = result[:limit]
    if not result:
        raise SystemExit("分片/限量后没有可更新标的。")
    return result


def _cached_symbols_by_asset_type(
    args: argparse.Namespace,
    *,
    asset_types: tuple[str, ...],
    timeframes: tuple[str, ...],
    primary_only: bool,
) -> tuple[str, ...]:
    requested_timeframes = _primary_cached_timeframes(timeframes) if primary_only else timeframes
    symbols = _catalog_cached_symbols_by_asset_type(
        data_root=getattr(args, "data_root", DEFAULT_DATA_ROOT),
        adjust=getattr(args, "adjust", "qfq"),
        asset_types=asset_types,
        timeframes=requested_timeframes,
    )
    if symbols:
        return symbols
    service = DataManagementService(
        getattr(args, "data_root", DEFAULT_DATA_ROOT),
        adjust=getattr(args, "adjust", "qfq"),
    )
    return service.cached_symbols(asset_types=asset_types, timeframes=requested_timeframes, tdx_path=getattr(args, "tdx_path", ""))


def _catalog_cached_symbols_by_asset_type(
    *,
    data_root: str,
    adjust: str,
    asset_types: tuple[str, ...],
    timeframes: tuple[str, ...],
) -> tuple[str, ...]:
    catalog = query_catalog(
        data_root=data_root,
        adjust=adjust,
        asset_types=asset_types,
        timeframes=timeframes,
        data_kinds=("price",),
        indicators=("ohlcv",),
        statuses=("cached",),
        read_timeout_seconds=2,
    )
    if catalog.empty or "stock_code" not in catalog.columns:
        return ()
    return tuple(sorted(catalog["stock_code"].dropna().astype(str).map(normalize_symbol).drop_duplicates().tolist()))


def _primary_cached_timeframes(timeframes: tuple[str, ...]) -> tuple[str, ...]:
    non_daily = tuple(timeframe for timeframe in timeframes if str(timeframe) != "1d")
    return non_daily or timeframes


def _raise_no_symbols(asset_types: tuple[str, ...]) -> tuple[str, ...]:
    raise SystemExit(f"未从本地代码表或缓存中找到资产类型：{','.join(asset_types)}")


def _metadata_symbols_by_asset_type(
    *,
    data_root: str,
    tdx_path: str,
    asset_types: tuple[str, ...],
) -> tuple[str, ...]:
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    if metadata.empty:
        return ()
    allowed = {str(item).strip().lower() for item in asset_types if str(item).strip()}
    symbols: list[str] = []
    for row in metadata.itertuples(index=False):
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        if not symbol:
            continue
        name = str(getattr(row, "stock_name", "") or "")
        if infer_asset_type(symbol, name).lower() in allowed:
            symbols.append(symbol)
    return tuple(dict.fromkeys(symbols))


def _daily_check(args: argparse.Namespace) -> dict[str, object]:
    started_at = time.perf_counter()
    timings: dict[str, int] = {}
    service = DataManagementService(args.data_root, adjust=args.adjust)
    timeframes = _split_csv(args.timeframes)
    resolve_started_at = time.perf_counter()
    symbols = _resolve_download_symbols(args, timeframes=timeframes)
    timings["resolve_symbols_ms"] = int((time.perf_counter() - resolve_started_at) * 1000)
    config = DataDownloadConfig(
        symbols=normalize_symbol_tuple(symbols),
        timeframes=timeframes,
        start=args.start,
        end=args.end,
        tqcenter_path=getattr(args, "tdx_path", ""),
        batch_size=100,
        min_coverage_ratio=None,
        strict_after_update=False,
    )
    risks: list[dict[str, object]] = []
    worker_started_at = time.perf_counter()
    worker = _worker_health_for_daily_check(str(getattr(args, "worker_url", "") or ""))
    timings["worker_health_ms"] = int((time.perf_counter() - worker_started_at) * 1000)
    if not bool(worker.get("ok")):
        risks.append({"level": "error", "code": "worker_unavailable", "message": worker.get("error", "Windows Worker 不可用。")})

    delta_started_at = time.perf_counter()
    delta = delta_sidecar_summary(
        data_root=args.data_root,
        adjust=args.adjust,
        timeframes=timeframes,
        part_threshold=int(args.delta_part_threshold),
        byte_threshold=int(args.delta_byte_threshold),
    )
    timings["delta_summary_ms"] = int((time.perf_counter() - delta_started_at) * 1000)
    delta_summary = delta.get("summary", {}) if isinstance(delta, dict) else {}
    delta_parts = int(delta_summary.get("part_count", 0) or 0) if isinstance(delta_summary, dict) else 0
    delta_bytes = int(delta_summary.get("file_size_bytes", 0) or 0) if isinstance(delta_summary, dict) else 0
    needs_compaction = bool(delta_summary.get("needs_compaction")) if isinstance(delta_summary, dict) else False
    if needs_compaction or delta_parts >= int(args.delta_part_threshold) or delta_bytes >= int(args.delta_byte_threshold):
        risks.append(
            {
                "level": "warn",
                "code": "delta_compaction_due",
                "message": f"delta 缓存达到维护阈值：{delta_parts} parts / {delta_bytes} bytes。",
            }
        )

    catalog_started_at = time.perf_counter()
    catalog = maintain_catalog(data_root=args.data_root, vacuum=False)
    timings["catalog_maintain_ms"] = int((time.perf_counter() - catalog_started_at) * 1000)
    catalog_after = catalog.get("after", {}) if isinstance(catalog, dict) else {}
    if isinstance(catalog_after, dict):
        freelist = int(catalog_after.get("freelist_count", 0) or 0)
        wal_size = int(catalog_after.get("wal_size_bytes", 0) or 0)
        if freelist > 1000 or wal_size > 64 * 1024 * 1024:
            risks.append(
                {
                    "level": "warn",
                    "code": "catalog_maintenance_due",
                    "message": f"SQLite catalog 需要维护：freelist={freelist}，wal={wal_size} bytes。",
                }
            )

    plan_started_at = time.perf_counter()
    plan = service.preview_download_plan(config)
    plan_ms = int((time.perf_counter() - plan_started_at) * 1000)
    timings["preview_plan_ms"] = plan_ms
    plan_summary = _summarize_daily_plan(plan)
    fetch_count = int(plan_summary.get("fetch_count", 0) or 0)
    fetch_missing_rows = int(plan_summary.get("fetch_missing_rows", 0) or 0)
    unresolved_count = int(plan_summary.get("unresolved_count", 0) or 0)
    unknown_count = int(plan_summary.get("coverage_unknown_count", 0) or 0)
    if unknown_count:
        risks.append(
            {
                "level": "error" if bool(args.fail_on_coverage_unknown) else "warn",
                "code": "coverage_unknown",
                "message": f"预览计划中有 {unknown_count} 项覆盖状态未知，建议先刷新 coverage。",
            }
        )
    if fetch_count and bool(args.fail_on_fetch):
        risks.append(
            {
                "level": "error",
                "code": "remaining_fetch_plan",
                "message": f"下载后仍有 {fetch_count} 项需要 fetch，验收失败。",
            }
        )
    if unresolved_count:
        risks.append(
            {
                "level": "error" if bool(getattr(args, "fail_on_unresolved_provider_gap", False)) else "warn",
                "code": "unresolved_provider_gap",
                "message": f"有 {unresolved_count} 项缺口已真实请求后仍未补齐，已停止自动重复抓取。",
            }
        )
    if fetch_count >= int(args.plan_fetch_threshold):
        risks.append(
            {
                "level": "error" if bool(getattr(args, "fail_on_large_fetch_plan", False)) else "warn",
                "code": "large_fetch_plan",
                "message": f"预览计划需要 fetch {fetch_count} 项，超过阈值 {int(args.plan_fetch_threshold)}。",
            }
        )
    if fetch_missing_rows >= int(args.plan_missing_threshold):
        risks.append(
            {
                "level": "error" if bool(getattr(args, "fail_on_large_missing_plan", False)) else "warn",
                "code": "large_missing_plan",
                "message": f"预览计划待抓缺口 {fetch_missing_rows} 根 K，超过阈值 {int(args.plan_missing_threshold)}。",
            }
        )
    if plan_ms > 10_000:
        risks.append({"level": "warn", "code": "slow_preview", "message": f"预览计划耗时 {plan_ms}ms。"})

    return {
        "ok": not any(str(item.get("level")) == "error" for item in risks),
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        "data_root": str(args.data_root),
        "timeframes": list(timeframes),
        "symbol_count": len(config.symbols),
        "window": {"start": args.start, "end": args.end},
        "worker": worker,
        "delta": delta,
        "catalog": catalog,
        "timings": timings,
        "plan": {"elapsed_ms": plan_ms, **plan_summary},
        "risks": risks,
    }


def _worker_health_for_daily_check(worker_url: str) -> dict[str, object]:
    try:
        health = TdxWorkerClient(worker_url or None, timeout_seconds=2).health()
        return {"ok": True, **health}
    except WorkerUnavailable as exc:
        return {"ok": False, "error": str(exc)}


def _sync_trading_calendar(args: argparse.Namespace) -> dict[str, object]:
    from tdx_downloader.api.fuyao_client import FuyaoAPIError, fetch_trading_days, has_fuyao_api_key, normalize_trading_days

    if bool(getattr(args, "skip_without_key", False)) and not str(getattr(args, "api_key", "") or "").strip() and not has_fuyao_api_key():
        offline = _sync_trading_calendar_from_akshare(args)
        if bool(offline.get("ok")):
            offline["fallback_reason"] = "missing_api_key"
            offline["message"] = "未配置 FUYAO_API_KEY/AICUBES_API_KEY/THS_API_KEY，已用本机 AkShare 交易日历生成本地日历。"
            return offline
        return {
            "ok": True,
            "skipped": True,
            "source": "fuyao",
            "reason": "missing_api_key",
            "fallback_error": offline.get("message", ""),
            "message": "未配置 FUYAO_API_KEY/AICUBES_API_KEY/THS_API_KEY，且本机 AkShare 交易日历不可用，已跳过交易日历同步。",
        }
    try:
        payload = normalize_trading_days(fetch_trading_days(api_key=str(getattr(args, "api_key", "") or "")))
        path = save_trading_days(data_root=args.data_root, days=list(payload.get("days", [])), source="fuyao")
    except (FuyaoAPIError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "skipped": False,
            "source": "fuyao",
            "message": str(exc),
        }
    days = list(payload.get("days", []))
    return {
        "ok": True,
        "skipped": False,
        "source": "fuyao",
        "raw_count": int(payload.get("raw_count") or 0),
        "day_count": len(days),
        "first_day": days[0] if days else "",
        "last_day": days[-1] if days else "",
        "path": str(path),
    }


def _sync_trading_calendar_from_akshare(args: argparse.Namespace) -> dict[str, object]:
    try:
        import akshare as ak

        frame = ak.tool_trade_date_hist_sina()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "skipped": True,
            "source": "akshare",
            "message": f"AkShare 交易日历不可用：{exc}",
        }
    if frame is None or frame.empty or "trade_date" not in frame.columns:
        return {
            "ok": False,
            "skipped": True,
            "source": "akshare",
            "message": "AkShare 交易日历返回为空或缺少 trade_date 列。",
        }
    days = [str(value)[:10] for value in frame["trade_date"].dropna().tolist()]
    path = save_trading_days(data_root=args.data_root, days=days, source="akshare-sina")
    normalized_days = sorted({day for day in days if day})
    return {
        "ok": True,
        "skipped": False,
        "source": "akshare-sina",
        "raw_count": len(frame),
        "day_count": len(normalized_days),
        "first_day": normalized_days[0] if normalized_days else "",
        "last_day": normalized_days[-1] if normalized_days else "",
        "path": str(path),
    }


def _import_trading_calendar(args: argparse.Namespace) -> dict[str, object]:
    import json
    import re

    raw_items: list[object] = []
    days_text = str(getattr(args, "days", "") or "")
    if days_text.strip():
        raw_items.extend(re.split(r"[\s,;，；]+", days_text.strip()))
    file_text = str(getattr(args, "file", "") or "")
    if file_text.strip():
        path = Path(file_text).expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "source": getattr(args, "source", "manual"), "message": f"读取交易日历文件失败：{exc}"}
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            raw_items.extend(re.split(r"[\s,;，；]+", content.strip()))
        else:
            if isinstance(payload, dict):
                value = payload.get("days") or payload.get("trading_days") or payload.get("dates") or []
                raw_items.extend(value if isinstance(value, list) else [value])
            elif isinstance(payload, list):
                raw_items.extend(payload)
            else:
                raw_items.append(payload)
    normalized_days = _normalize_import_days(raw_items)
    if not normalized_days:
        return {"ok": False, "source": getattr(args, "source", "manual"), "message": "没有可导入的交易日期。"}
    path = save_trading_days(data_root=args.data_root, days=normalized_days, source=str(getattr(args, "source", "manual") or "manual"))
    return {
        "ok": True,
        "source": str(getattr(args, "source", "manual") or "manual"),
        "day_count": len(normalized_days),
        "first_day": normalized_days[0],
        "last_day": normalized_days[-1],
        "path": str(path),
    }


def _normalize_import_days(values: list[object]) -> list[str]:
    from datetime import datetime

    days: set[str] = set()
    for value in values:
        text = str(value or "").strip().strip('"').strip("'")
        if not text:
            continue
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                days.add(datetime.strptime(text, fmt).date().isoformat())
                break
            except ValueError:
                continue
    return sorted(days)


def _summarize_daily_plan(plan) -> dict[str, object]:
    import pandas as pd

    if plan.empty:
        return {
            "row_count": 0,
            "fetch_count": 0,
            "cached_count": 0,
            "derive_count": 0,
            "unresolved_count": 0,
            "missing_rows": 0,
            "fetch_missing_rows": 0,
            "coverage_unknown_count": 0,
            "by_timeframe": [],
            "unresolved_items": [],
        }
    action = plan["action"].fillna("").astype(str) if "action" in plan.columns else pd.Series([""] * len(plan))
    coverage = plan["coverage_status"].fillna("").astype(str) if "coverage_status" in plan.columns else pd.Series([""] * len(plan))
    missing = pd.to_numeric(plan.get("missing_rows", pd.Series([0] * len(plan))), errors="coerce").fillna(0)
    fetch_missing = missing.loc[action.eq("fetch") | action.eq("derive")]
    by_timeframe: list[dict[str, object]] = []
    if "timeframe" in plan.columns:
        frame = plan.assign(_action=action, _missing=missing, _coverage=coverage)
        for timeframe, grouped in frame.groupby("timeframe", sort=False):
            executable = grouped["_action"].isin({"fetch", "derive"})
            by_timeframe.append(
                {
                    "timeframe": str(timeframe),
                    "row_count": int(len(grouped)),
                    "fetch_count": int(grouped["_action"].eq("fetch").sum()),
                    "cached_count": int(grouped["_action"].eq("cached").sum()),
                    "derive_count": int(grouped["_action"].eq("derive").sum()),
                    "unresolved_count": int(grouped["_action"].eq("unresolved").sum()),
                    "missing_rows": int(pd.to_numeric(grouped["_missing"], errors="coerce").fillna(0).sum()),
                    "fetch_missing_rows": int(
                        pd.to_numeric(grouped.loc[executable, "_missing"], errors="coerce").fillna(0).sum()
                    ),
                    "coverage_unknown_count": int(grouped["_coverage"].eq("coverage_unknown").sum()),
                }
            )
    unresolved_items = _daily_plan_unresolved_items(plan=plan, action=action)
    return {
        "row_count": int(len(plan)),
        "fetch_count": int(action.eq("fetch").sum()),
        "cached_count": int(action.eq("cached").sum()),
        "derive_count": int(action.eq("derive").sum()),
        "unresolved_count": int(action.eq("unresolved").sum()),
        "missing_rows": int(missing.sum()),
        "fetch_missing_rows": int(fetch_missing.sum()),
        "coverage_unknown_count": int(coverage.eq("coverage_unknown").sum()),
        "by_timeframe": by_timeframe,
        "unresolved_items": unresolved_items,
    }


def _daily_plan_unresolved_items(*, plan, action, limit: int = 12) -> list[dict[str, object]]:
    import pandas as pd

    if plan.empty or "action" not in plan.columns:
        return []
    unresolved = plan.loc[action.eq("unresolved")].copy()
    if unresolved.empty:
        return []
    unresolved["_missing"] = pd.to_numeric(unresolved.get("missing_rows", pd.Series(dtype=float)), errors="coerce").fillna(0)
    sort_columns = [column for column in ("timeframe", "_missing", "stock_code") if column in unresolved.columns]
    if sort_columns:
        ascending = [True if column != "_missing" else False for column in sort_columns]
        unresolved = unresolved.sort_values(sort_columns, ascending=ascending)
    rows: list[dict[str, object]] = []
    for row in unresolved.head(limit).to_dict("records"):
        rows.append(
            {
                "stock_code": str(row.get("stock_code") or ""),
                "timeframe": str(row.get("timeframe") or ""),
                "adjust": str(row.get("adjust") or ""),
                "reason": str(row.get("reason") or ""),
                "coverage_status": str(row.get("coverage_status") or ""),
                "missing_rows": int(float(row.get("missing_rows") or 0)),
                "first_missing_at": str(row.get("first_missing_at") or ""),
                "last_missing_at": str(row.get("last_missing_at") or ""),
                "message": str(row.get("message") or ""),
            }
        )
    return rows


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _print_frame(frame, output: str) -> None:
    if output == "json":
        payload = frame.astype(object).where(frame.notna(), None).to_dict("records")
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return
    print(frame.to_string(index=False))


def _print_mapping(payload: dict[str, object], output: str) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return
    import pandas as pd

    summary = payload.get("summary")
    if isinstance(summary, dict):
        print(pd.DataFrame([summary]).to_string(index=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, default=str))
    rows = payload.get("by_timeframe")
    if isinstance(rows, list) and rows:
        print(pd.DataFrame(rows).to_string(index=False))


def _print_daily_check(payload: dict[str, object], output: str) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return
    import pandas as pd

    summary = {
        "ok": payload.get("ok"),
        "elapsed_ms": payload.get("elapsed_ms"),
        "symbol_count": payload.get("symbol_count"),
        "timeframes": ",".join(str(item) for item in payload.get("timeframes", []) or []),
        "plan_fetch": (payload.get("plan") or {}).get("fetch_count") if isinstance(payload.get("plan"), dict) else None,
        "plan_missing_rows": (payload.get("plan") or {}).get("missing_rows") if isinstance(payload.get("plan"), dict) else None,
        "plan_fetch_missing_rows": (payload.get("plan") or {}).get("fetch_missing_rows") if isinstance(payload.get("plan"), dict) else None,
        "risk_count": len(payload.get("risks", []) or []),
    }
    print(pd.DataFrame([summary]).to_string(index=False))
    risks = payload.get("risks", [])
    if isinstance(risks, list) and risks:
        print(pd.DataFrame(risks).to_string(index=False))


def _concat_frames(frames: list[object]):
    import pandas as pd

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _objects_frame(records: list[dict[str, object]]):
    import pandas as pd

    return pd.DataFrame(records)


def _print_symbol_groups(groups: list[dict[str, object]], output: str) -> None:
    if output == "json":
        print(json.dumps(groups, ensure_ascii=False, default=str))
        return
    rows = [{"name": group.get("name", ""), "count": len(group.get("symbols", []))} for group in groups]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def _progress_callback():
    if os.getenv(PARALLELS_PROGRESS_ENV_VAR, "").strip() != "1":
        return None

    def emit(event: dict[str, object]) -> None:
        print(
            PARALLELS_PROGRESS_PREFIX + json.dumps(event, ensure_ascii=False, default=str),
            file=sys.stderr,
            flush=True,
        )

    return emit


if __name__ == "__main__":
    main()
