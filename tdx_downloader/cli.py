from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tdx_downloader.data.manager import DataDownloadConfig, DataManagementService, normalize_symbol_tuple
from tdx_downloader.data.repository import MarketDataRepository
from tdx_downloader.data.tdx import diagnose_tdx_source
from tdx_downloader.data.tdx_parallels import (
    ParallelsTdxConfig,
    default_parallels_tdx_config,
    mac_path_to_parallels_shared_path,
    run_parallels_tdx_command,
)

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
    fetch_parser.add_argument("--symbols", required=True)
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
    prepare_parser.add_argument("--symbols", required=True)
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
    plan_parser.add_argument("--symbols", required=True)
    plan_parser.add_argument("--timeframes", required=True)
    plan_parser.add_argument("--start", required=True)
    plan_parser.add_argument("--end", required=True)
    plan_parser.add_argument("--adjust", default="qfq")
    plan_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    plan_parser.add_argument("--min-coverage-ratio", type=float, default=None)

    inventory_parser = subparsers.add_parser("inventory-data", help="list local parquet cache inventory")
    inventory_parser.add_argument("--symbols", default="")
    inventory_parser.add_argument("--timeframes", default="1d,1m,5m,15m,30m,60m")
    inventory_parser.add_argument("--adjust", default="qfq")
    inventory_parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)

    args = parser.parse_args(argv)
    if args.command in {"tdx-doctor", "fetch", "prepare-data"} and _resolve_runtime(args.runtime) == "parallels":
        _run_in_parallels(args)
        return

    symbols = _split_csv(args.symbols)
    if args.command == "tdx-doctor":
        result = diagnose_tdx_source(
            symbols=symbols,
            timeframes=_split_csv(args.timeframes),
            start=args.start,
            end=args.end,
            adjust=args.adjust,
            tqcenter_path=args.tdx_path,
        )
        _print_frame(result, args.output)
        return

    repo = MarketDataRepository(Path(args.data_root), adjust=args.adjust)
    if args.command == "inventory-data":
        result = repo.inventory(timeframes=_split_csv(args.timeframes), symbols=symbols or None)
        print(result.to_string(index=False))
        return

    if args.command == "fetch":
        result = repo.update_from_tdx(
            symbols=symbols,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            tqcenter_path=args.tdx_path,
            batch_size=max(int(args.batch_size), 1),
        )
        _print_frame(result, args.output)
        return

    service = DataManagementService(Path(args.data_root), adjust=args.adjust)
    config = DataDownloadConfig(
        symbols=normalize_symbol_tuple(symbols),
        timeframes=_split_csv(args.timeframes),
        start=args.start,
        end=args.end,
        tqcenter_path=getattr(args, "tdx_path", ""),
        batch_size=max(int(getattr(args, "batch_size", 100)), 1),
        min_coverage_ratio=args.min_coverage_ratio,
        strict_after_update=not bool(getattr(args, "allow_incomplete_after_update", False)),
    )
    if args.command == "prepare-data":
        result = service.download(config, mode="smart")
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
    for name in ("symbols", "timeframes", "timeframe", "start", "end", "adjust", "data_root", "tdx_path", "output"):
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


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _print_frame(frame, output: str) -> None:
    if output == "json":
        payload = frame.astype(object).where(frame.notna(), None).to_dict("records")
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
