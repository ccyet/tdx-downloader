from __future__ import annotations

import hashlib
from pathlib import Path
import time
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from tdx_downloader.data.catalog import (
    query_catalog,
    query_coverage_runs,
    query_market_data_part_symbols,
    refresh_coverage_runs,
    upsert_catalog_records,
    upsert_market_data_parts,
)
from tdx_downloader.data.inventory import inventory_local_data
from tdx_downloader.data.schema import (
    CANONICAL_COLUMNS,
    TIMEFRAME_DIR_NAMES,
    canonical_data_root,
    empty_bars,
    empty_download_result,
    normalize_bars,
    parse_time_window,
    resolve_timeframe_root,
    unique_symbols,
)

DATASET_READ_SYMBOL_THRESHOLD = 200
WRITE_PROGRESS_INTERVAL = 100
DELTA_DIR_SUFFIX = ".delta"
SHARED_DELTA_DIR_NAME = "_delta_parts"
CATALOG_QUERY_SYMBOL_CHUNK = 500


def _clear_fast_plan_cache() -> None:
    from tdx_downloader.data.repository import clear_fast_plan_cache

    clear_fast_plan_cache()


def resolve_daily_root(data_root: str | Path) -> Path:
    return canonical_data_root(data_root) / TIMEFRAME_DIR_NAMES["1d"]


def load_local_bars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    start_ts, end_ts = parse_time_window(start, end)
    normalized_symbols = unique_symbols(tuple(symbols))
    frames: list[pd.DataFrame] = []
    for symbol in normalized_symbols:
        path = root / f"{symbol}.parquet"
        delta_root = _delta_root_for_base_path(path)
        if not path.exists() and not delta_root.exists():
            continue
        frame = _read_symbol_window_with_deltas(path, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
        if not frame.empty:
            frames.append(frame)
    shared = _read_shared_delta_window(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=normalized_symbols,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if not shared.empty:
        frames.append(shared)
    if not frames:
        return empty_bars()
    return _combine_bar_frames(frames)


def load_daily_bars(
    *,
    data_root: str | Path,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    root = resolve_daily_root(data_root) / adjust
    start_ts, end_ts = parse_time_window(start, end)
    normalized_symbols = unique_symbols(tuple(symbols))
    shared = _read_shared_delta_window(
        data_root=data_root,
        timeframe="1d",
        adjust=adjust,
        symbols=normalized_symbols,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if len(normalized_symbols) >= DATASET_READ_SYMBOL_THRESHOLD:
        try:
            frame = _read_bars_dataset_window(
                root,
                symbols=normalized_symbols,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            if not frame.empty or not shared.empty:
                return _combine_bar_frames([frame, shared])
        except Exception:  # noqa: BLE001
            pass
    frames: list[pd.DataFrame] = []
    for symbol in normalized_symbols:
        path = root / f"{symbol}.parquet"
        delta_root = _delta_root_for_base_path(path)
        if not path.exists() and not delta_root.exists():
            continue
        frame = _read_symbol_window_with_deltas(path, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
        if not frame.empty:
            frames.append(frame)
    if not shared.empty:
        frames.append(shared)
    if not frames:
        return empty_bars()
    return _combine_bar_frames(frames)


def write_local_bars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    bars: pd.DataFrame,
    progress_callback=None,
    refresh_coverage: bool = True,
) -> pd.DataFrame:
    normalized = normalize_bars(bars)
    if normalized.empty:
        return empty_download_result()

    root = resolve_timeframe_root(data_root, timeframe) / adjust
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    groups = list(normalized.groupby("stock_code", sort=True))
    total_groups = len(groups)
    for index, (symbol, incoming) in enumerate(groups, start=1):
        path = root / f"{symbol}.parquet"
        previous_rows = 0
        action = "rewrite"
        if path.exists():
            unchanged = _unchanged_existing_rows(path, symbol=str(symbol), incoming=incoming)
            if unchanged is not None:
                action = "skip"
                rows.append(
                    {
                        "symbol": str(symbol),
                        "status": "success",
                        "rows": unchanged["rows"],
                        "new_rows": 0,
                        "path": str(path),
                        "start": unchanged["start"],
                        "end": unchanged["end"],
                        "message": "TDX 行情与本地 parquet 一致，已跳过重写。",
                    }
                )
                _emit_write_progress(
                    progress_callback,
                    timeframe=timeframe,
                    symbol=str(symbol),
                    index=index,
                    total=total_groups,
                    action=action,
                )
                continue
            appended = _append_tail_rows_if_possible(path, symbol=str(symbol), incoming=incoming)
            if appended is not None:
                action = "append"
                rows.append(appended)
                _emit_write_progress(
                    progress_callback,
                    timeframe=timeframe,
                    symbol=str(symbol),
                    index=index,
                    total=total_groups,
                    action=action,
                )
                continue
            appended_after_overlap = _append_new_tail_rows_after_overlap_if_possible(path, symbol=str(symbol), incoming=incoming)
            if appended_after_overlap is not None:
                action = "append_overlap"
                rows.append(appended_after_overlap)
                _emit_write_progress(
                    progress_callback,
                    timeframe=timeframe,
                    symbol=str(symbol),
                    index=index,
                    total=total_groups,
                    action=action,
                )
                continue
            previous = normalize_bars(pd.read_parquet(path), str(symbol))
            previous_rows = len(previous)
            merged = pd.concat([previous, incoming], ignore_index=True)
        else:
            merged = incoming.copy()
        merged = (
            merged[CANONICAL_COLUMNS]
            .drop_duplicates(subset=["stock_code", "date"], keep="last")
            .sort_values(["stock_code", "date"])
            .reset_index(drop=True)
        )
        merged.to_parquet(path, index=False)
        rows.append(
            {
                "symbol": str(symbol),
                "status": "success",
                "rows": int(len(merged)),
                "new_rows": int(max(len(merged) - previous_rows, 0)),
                "path": str(path),
                "start": merged["date"].min(),
                "end": merged["date"].max(),
                "message": "TDX 行情已写入本地 parquet。",
            }
        )
        _emit_write_progress(
            progress_callback,
            timeframe=timeframe,
            symbol=str(symbol),
            index=index,
            total=total_groups,
            action=action,
        )
    result = pd.DataFrame(rows)
    _refresh_written_catalog_records(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=tuple(str(symbol) for symbol in result["symbol"].dropna().astype(str).tolist()),
        refresh_coverage=refresh_coverage,
    )
    _clear_fast_plan_cache()
    return result


def append_delta_bars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    bars: pd.DataFrame,
    progress_callback=None,
    refresh_coverage: bool = False,
    fast_catalog_update: bool = True,
    estimate_existing_overlap: bool = True,
) -> pd.DataFrame:
    """Append incoming bars as immutable per-symbol delta parts.

    This is intended for Worker commits: it avoids reading and rewriting large
    historical parquet files in the hot path. Existing readers merge base and
    delta sidecars at query time.
    """
    normalized = normalize_bars(bars)
    if normalized.empty:
        return empty_download_result()

    root = resolve_timeframe_root(data_root, timeframe) / adjust
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    groups: list[tuple[str, pd.DataFrame]] = []
    for symbol, incoming in normalized.groupby("stock_code", sort=True):
        clean = (
            incoming.loc[:, CANONICAL_COLUMNS]
            .drop_duplicates(subset=["stock_code", "date"], keep="last")
            .sort_values(["stock_code", "date"])
            .reset_index(drop=True)
        )
        if not clean.empty:
            groups.append((str(symbol), clean))
    total_groups = len(groups)
    if not groups:
        return empty_download_result()
    existing_summary = _catalog_summary_for_delta_update(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=tuple(symbol for symbol, _ in groups),
    )
    coverage_by_symbol: dict[str, set[pd.Timestamp]] | None = None
    if estimate_existing_overlap:
        incoming_dates = pd.to_datetime(
            pd.concat([clean["date"] for _, clean in groups], ignore_index=True),
            errors="coerce",
        )
        incoming_dates = incoming_dates.dropna()
        coverage_by_symbol = _coverage_dates_by_symbol_from_catalog(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=tuple(symbol for symbol, _ in groups),
            start=pd.Timestamp(incoming_dates.min()) if not incoming_dates.empty else pd.NaT,
            end=pd.Timestamp(incoming_dates.max()) if not incoming_dates.empty else pd.NaT,
        )
    for index, (symbol_text, clean) in enumerate(groups, start=1):
        path = root / f"{symbol_text}.parquet"
        existing = existing_summary.get(symbol_text)
        if existing is None:
            existing = _parquet_file_summary(path, symbol=symbol_text)
        if estimate_existing_overlap:
            new_rows = _estimate_new_unique_rows(
                data_root=data_root,
                timeframe=timeframe,
                adjust=adjust,
                symbol=symbol_text,
                path=path,
                incoming=clean,
                covered_dates=None if coverage_by_symbol is None else coverage_by_symbol.get(symbol_text),
            )
        else:
            new_rows = len(_normalized_bar_dates(clean["date"], timeframe=timeframe))
        delta_path = _write_delta_part(path, clean)
        delta_stat = delta_path.stat()
        summary = _merge_delta_summary(
            existing,
            incoming_rows=new_rows,
            incoming_start=clean["date"].min(),
            incoming_end=clean["date"].max(),
        )
        rows.append(
            {
                "symbol": symbol_text,
                "status": "success",
                "rows": int(summary.get("rows", len(clean)) or len(clean)),
                "new_rows": int(new_rows),
                "path": str(path),
                "delta_path": str(delta_path),
                "delta_file_size_bytes": int(delta_stat.st_size),
                "start": summary.get("start", clean["date"].min()),
                "end": summary.get("end", clean["date"].max()),
                "delta_start": clean["date"].min(),
                "delta_end": clean["date"].max(),
                "message": f"TDX 行情已写入 delta 缓存：{delta_path.name}。",
            }
        )
        _emit_write_progress(
            progress_callback,
            timeframe=timeframe,
            symbol=symbol_text,
            index=index,
            total=total_groups,
            action="delta",
        )
    result = pd.DataFrame(rows)
    catalog_started_at = time.perf_counter()
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "worker_commit_catalog_start",
                "timeframe": timeframe,
                "symbol_count": int(len(result)),
                "message": f"开始更新本地缓存目录：{timeframe}，{len(result)} 只标的。",
            }
        )
    if fast_catalog_update:
        _upsert_catalog_records_from_write_result(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            result=result,
            refresh_coverage=refresh_coverage,
        )
    else:
        _refresh_written_catalog_records(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=tuple(str(symbol) for symbol in result["symbol"].dropna().astype(str).tolist()),
            refresh_coverage=refresh_coverage,
        )
    if progress_callback is not None:
        elapsed_ms = int((time.perf_counter() - catalog_started_at) * 1000)
        progress_callback(
            {
                "stage": "worker_commit_catalog_done",
                "timeframe": timeframe,
                "symbol_count": int(len(result)),
                "elapsed_ms": elapsed_ms,
                "message": f"本地缓存目录更新完成：{timeframe}，用时 {elapsed_ms}ms。",
            }
        )
    return result


def append_shared_delta_bars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    bars: pd.DataFrame,
    job_id: str = "",
    progress_callback=None,
    refresh_coverage: bool = False,
    estimate_existing_overlap: bool = False,
) -> pd.DataFrame:
    """Append incoming bars as immutable multi-symbol delta parts.

    Worker commits use this hot path. It writes one part per trade month instead
    of one parquet per symbol, then registers part-symbol metadata so reads can
    still filter by symbol and window.
    """
    normalized = normalize_bars(bars)
    if normalized.empty:
        return empty_download_result()

    normalized = (
        normalized.loc[:, CANONICAL_COLUMNS]
        .drop_duplicates(subset=["stock_code", "date"], keep="last")
        .sort_values(["stock_code", "date"])
        .reset_index(drop=True)
    )
    symbols = tuple(str(symbol) for symbol in normalized["stock_code"].dropna().astype(str).drop_duplicates().tolist())
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    root.mkdir(parents=True, exist_ok=True)
    existing_summary = _catalog_summary_for_delta_update(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=symbols,
    )

    coverage_by_symbol: dict[str, set[pd.Timestamp]] | None = None
    if estimate_existing_overlap:
        incoming_dates = pd.to_datetime(normalized["date"], errors="coerce").dropna()
        coverage_by_symbol = _coverage_dates_by_symbol_from_catalog(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbols=symbols,
            start=pd.Timestamp(incoming_dates.min()) if not incoming_dates.empty else pd.NaT,
            end=pd.Timestamp(incoming_dates.max()) if not incoming_dates.empty else pd.NaT,
        )

    commit_id = _safe_commit_id(job_id)
    commit_version = time.time_ns()
    created_at = pd.Timestamp.utcnow().isoformat()
    part_records: list[dict[str, object]] = []
    symbol_part_records: list[dict[str, object]] = []
    symbol_paths: dict[str, list[Path]] = {symbol: [] for symbol in symbols}
    normalized["_trade_month"] = pd.to_datetime(normalized["date"], errors="coerce").dt.strftime("%Y-%m")
    for trade_month, month_frame in normalized.groupby("_trade_month", sort=True):
        if not str(trade_month):
            continue
        clean = month_frame.drop(columns=["_trade_month"], errors="ignore").reset_index(drop=True)
        delta_path = _write_shared_delta_part(root, clean, trade_month=str(trade_month), commit_id=commit_id)
        stat = delta_path.stat()
        part_id = _shared_part_id(commit_id=commit_id, path=delta_path, timeframe=timeframe, adjust=adjust)
        part_records.append(
            {
                "part_id": part_id,
                "job_id": commit_id,
                "timeframe": timeframe,
                "adjust": adjust,
                "trade_month": str(trade_month),
                "path": str(delta_path),
                "rows": int(len(clean)),
                "min_at": pd.Timestamp(clean["date"].min()).isoformat(),
                "max_at": pd.Timestamp(clean["date"].max()).isoformat(),
                "file_size_bytes": int(stat.st_size),
                "sha256": _sha256_file(delta_path),
                "commit_version": commit_version,
                "state": "active",
                "created_at": created_at,
            }
        )
        for symbol, group in clean.groupby("stock_code", sort=True):
            symbol_text = str(symbol)
            symbol_paths.setdefault(symbol_text, []).append(delta_path)
            symbol_part_records.append(
                {
                    "part_id": part_id,
                    "stock_code": symbol_text,
                    "min_at": pd.Timestamp(group["date"].min()).isoformat(),
                    "max_at": pd.Timestamp(group["date"].max()).isoformat(),
                    "rows": int(len(group)),
                }
            )

    if part_records:
        upsert_market_data_parts(
            data_root=data_root,
            parts=pd.DataFrame(part_records),
            part_symbols=pd.DataFrame(symbol_part_records),
        )

    rows: list[dict[str, object]] = []
    total_groups = len(symbols)
    for index, (symbol_text, clean) in enumerate(normalized.drop(columns=["_trade_month"], errors="ignore").groupby("stock_code", sort=True), start=1):
        path = root / f"{symbol_text}.parquet"
        if estimate_existing_overlap:
            new_rows = _estimate_new_unique_rows(
                data_root=data_root,
                timeframe=timeframe,
                adjust=adjust,
                symbol=symbol_text,
                path=path,
                incoming=clean,
                covered_dates=None if coverage_by_symbol is None else coverage_by_symbol.get(symbol_text),
            )
        else:
            new_rows = len(_normalized_bar_dates(clean["date"], timeframe=timeframe))
        summary = _merge_delta_summary(
            existing_summary.get(symbol_text),
            incoming_rows=new_rows,
            incoming_start=clean["date"].min(),
            incoming_end=clean["date"].max(),
        )
        file_size_bytes, modified_at = _shared_file_state(symbol_paths.get(symbol_text, []))
        rows.append(
            {
                "symbol": symbol_text,
                "status": "success",
                "rows": int(summary.get("rows", len(clean)) or len(clean)),
                "new_rows": int(new_rows),
                "path": str(path),
                "delta_path": str(symbol_paths.get(symbol_text, [""])[0]),
                "delta_part_count": len(symbol_paths.get(symbol_text, [])),
                "file_size_bytes": file_size_bytes,
                "modified_at": modified_at,
                "start": summary.get("start", clean["date"].min()),
                "end": summary.get("end", clean["date"].max()),
                "delta_start": clean["date"].min(),
                "delta_end": clean["date"].max(),
                "message": f"TDX 行情已写入共享 delta 缓存：{len(symbol_paths.get(symbol_text, []))} 个 part。",
            }
        )
        _emit_write_progress(
            progress_callback,
            timeframe=timeframe,
            symbol=symbol_text,
            index=index,
            total=total_groups,
            action="shared_delta",
        )

    result = pd.DataFrame(rows)
    _upsert_catalog_records_from_write_result(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        result=result,
        refresh_coverage=refresh_coverage,
    )
    _clear_fast_plan_cache()
    return result


def _catalog_summary_for_delta_update(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}
    catalogs: list[pd.DataFrame] = []
    for chunk in _chunks(symbols, CATALOG_QUERY_SYMBOL_CHUNK):
        try:
            catalog = query_catalog(
                data_root=data_root,
                symbols=chunk,
                adjust=adjust,
                timeframes=(timeframe,),
                statuses=("cached",),
            )
        except Exception:  # noqa: BLE001
            continue
        if not catalog.empty:
            catalogs.append(catalog)
    if not catalogs:
        return {}
    catalog = pd.concat(catalogs, ignore_index=True)
    result: dict[str, dict[str, object]] = {}
    for row in catalog.itertuples(index=False):
        symbol = str(getattr(row, "stock_code", "") or "")
        if not symbol:
            continue
        result[symbol] = {
            "rows": int(getattr(row, "rows", 0) or 0),
            "start": _safe_timestamp(getattr(row, "start_at", pd.NaT)),
            "end": _safe_timestamp(getattr(row, "end_at", pd.NaT)),
        }
    return result


def _chunks(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _safe_timestamp(value: object) -> pd.Timestamp:
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def _merge_delta_summary(
    existing: dict[str, object] | None,
    *,
    incoming_rows: int,
    incoming_start: object,
    incoming_end: object,
) -> dict[str, object]:
    if not existing:
        return {"rows": int(incoming_rows), "start": incoming_start, "end": incoming_end}
    start_values = [pd.Timestamp(value) for value in (existing.get("start"), incoming_start) if not pd.isna(value)]
    end_values = [pd.Timestamp(value) for value in (existing.get("end"), incoming_end) if not pd.isna(value)]
    return {
        "rows": int(existing.get("rows", 0) or 0) + int(incoming_rows),
        "start": min(start_values) if start_values else pd.NaT,
        "end": max(end_values) if end_values else pd.NaT,
    }


def _estimate_new_unique_rows(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbol: str,
    path: Path,
    incoming: pd.DataFrame,
    covered_dates: set[pd.Timestamp] | None = None,
) -> int:
    dates = _normalized_bar_dates(incoming["date"], timeframe=timeframe)
    if not dates:
        return 0
    covered = covered_dates
    if covered is None:
        covered = _covered_dates_from_catalog(
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
            symbol=symbol,
            start=min(dates),
            end=max(dates),
        )
    if covered is None:
        covered = _existing_dates_from_parquet_identity(path, symbol=symbol, start=min(dates), end=max(dates), timeframe=timeframe)
    if not covered:
        return int(len(dates))
    return int(sum(1 for value in dates if value not in covered))


def _covered_dates_from_catalog(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> set[pd.Timestamp] | None:
    try:
        coverage = query_coverage_runs(
            data_root=data_root,
            symbols=(symbol,),
            adjust=adjust,
            timeframes=(timeframe,),
            start=start,
            end=end,
        )
    except Exception:  # noqa: BLE001
        return None
    if coverage.empty:
        return None
    covered: set[pd.Timestamp] = set()
    step = pd.Timedelta(days=1) if timeframe == "1d" else pd.Timedelta(minutes=int(str(timeframe).removesuffix("m")))
    for row in coverage.itertuples(index=False):
        run_start = _safe_timestamp(getattr(row, "start_at", pd.NaT))
        run_end = _safe_timestamp(getattr(row, "end_at", pd.NaT))
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        if timeframe == "1d":
            run_start = run_start.normalize()
            run_end = run_end.normalize()
        cursor = max(run_start, start)
        cursor = _ceil_to_step(cursor, base=run_start, step=step)
        final = min(run_end, end)
        while cursor <= final:
            covered.add(pd.Timestamp(cursor))
            cursor += step
    return covered


def _coverage_dates_by_symbol_from_catalog(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, set[pd.Timestamp]] | None:
    if not symbols or pd.isna(start) or pd.isna(end):
        return None
    try:
        coverage = query_coverage_runs(
            data_root=data_root,
            symbols=symbols,
            adjust=adjust,
            timeframes=(timeframe,),
            start=start,
            end=end,
        )
    except Exception:  # noqa: BLE001
        return None
    if coverage.empty:
        return None
    result: dict[str, set[pd.Timestamp]] = {}
    step = pd.Timedelta(days=1) if timeframe == "1d" else pd.Timedelta(minutes=int(str(timeframe).removesuffix("m")))
    for row in coverage.itertuples(index=False):
        symbol = str(getattr(row, "stock_code", "") or "")
        if symbol not in symbols:
            continue
        run_start = _safe_timestamp(getattr(row, "start_at", pd.NaT))
        run_end = _safe_timestamp(getattr(row, "end_at", pd.NaT))
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        if timeframe == "1d":
            run_start = run_start.normalize()
            run_end = run_end.normalize()
        cursor = max(run_start, start)
        cursor = _ceil_to_step(cursor, base=run_start, step=step)
        final = min(run_end, end)
        while cursor <= final:
            result.setdefault(symbol, set()).add(pd.Timestamp(cursor))
            cursor += step
    return result


def _existing_dates_from_parquet_identity(
    path: Path,
    *,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timeframe: str,
) -> set[pd.Timestamp]:
    frames: list[pd.DataFrame] = []
    for item_path in ([path] if path.exists() else []) + _delta_part_paths(path):
        if not item_path.exists():
            continue
        try:
            frame = pd.read_parquet(item_path, columns=["date", "stock_code"], filters=_date_window_filters(start, end))
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            frame = pd.read_parquet(item_path, columns=["date", "stock_code"])
        except Exception:  # noqa: BLE001
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return set()
    identity = pd.concat(frames, ignore_index=True)
    identity["stock_code"] = identity["stock_code"].map(lambda value: str(value).strip().upper())
    identity = identity.loc[identity["stock_code"].eq(symbol)]
    return set(_normalized_bar_dates(identity["date"], timeframe=timeframe))


def _normalized_bar_dates(values: pd.Series, *, timeframe: str) -> list[pd.Timestamp]:
    parsed = pd.to_datetime(values, errors="coerce").dropna()
    if timeframe == "1d":
        parsed = parsed.dt.normalize()
    else:
        parsed = parsed.dt.floor("min")
    return [pd.Timestamp(value) for value in parsed.drop_duplicates().sort_values(kind="mergesort").tolist()]


def _ceil_to_step(value: pd.Timestamp, *, base: pd.Timestamp, step: pd.Timedelta) -> pd.Timestamp:
    current = pd.Timestamp(value)
    if current <= base:
        return base
    delta_ns = current.value - base.value
    remainder = delta_ns % step.value
    return current if remainder == 0 else current + pd.Timedelta(step.value - remainder)


def compact_delta_sidecars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str] | None = None,
    progress_callback=None,
    refresh_coverage: bool = True,
) -> pd.DataFrame:
    """Merge delta sidecars back into the canonical per-symbol parquet files.

    Compaction is explicit/background maintenance. It must not run inside the
    download hot path, otherwise the commit path falls back to full-file rewrites.
    """
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    normalized_symbols = unique_symbols(tuple(symbols)) if symbols is not None else _discover_delta_symbols(root)
    if not normalized_symbols:
        return pd.DataFrame(columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "delta_parts", "delta_rows", "message"])

    rows: list[dict[str, object]] = []
    compacted_symbols: list[str] = []
    for index, symbol in enumerate(normalized_symbols, start=1):
        path = root / f"{symbol}.parquet"
        delta_paths = _delta_part_paths(path)
        if not delta_paths:
            summary = _parquet_file_summary(path, symbol=symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "status": "skipped",
                    "rows": int(summary.get("rows", 0) if summary else 0),
                    "new_rows": 0,
                    "path": str(path),
                    "start": summary.get("start", pd.NaT) if summary else pd.NaT,
                    "end": summary.get("end", pd.NaT) if summary else pd.NaT,
                    "delta_parts": 0,
                    "delta_rows": 0,
                    "message": "没有 delta 缓存需要压实。",
                }
            )
            continue
        delta_rows = _parquet_rows(delta_paths)
        frame = _read_symbol_all_with_deltas(path, symbol=symbol)
        if frame.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "skipped",
                    "rows": 0,
                    "new_rows": 0,
                    "path": str(path),
                    "start": pd.NaT,
                    "end": pd.NaT,
                    "delta_parts": len(delta_paths),
                    "delta_rows": delta_rows,
                    "message": "delta 缓存没有可用 K 线，已跳过。",
                }
            )
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.compact.tmp")
        try:
            frame.loc[:, CANONICAL_COLUMNS].to_parquet(tmp_path, index=False)
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        for delta_path in delta_paths:
            delta_path.unlink()
        delta_root = _delta_root_for_base_path(path)
        try:
            delta_root.rmdir()
        except OSError:
            pass
        compacted_symbols.append(symbol)
        rows.append(
            {
                "symbol": symbol,
                "status": "success",
                "rows": int(len(frame)),
                "new_rows": 0,
                "path": str(path),
                "start": frame["date"].min(),
                "end": frame["date"].max(),
                "delta_parts": len(delta_paths),
                "delta_rows": delta_rows,
                "message": f"已压实 {len(delta_paths)} 个 delta 缓存。",
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "delta_compact_progress",
                    "timeframe": timeframe,
                    "symbol": symbol,
                    "symbol_index": index,
                    "symbol_count": len(normalized_symbols),
                    "message": f"delta 压实 {timeframe}：{index}/{len(normalized_symbols)}，{symbol}。",
                }
            )

    result = pd.DataFrame(rows)
    if compacted_symbols:
        inventory = inventory_local_data(
            data_root=data_root,
            timeframes=(timeframe,),
            adjust=adjust,
            symbols=tuple(compacted_symbols),
        )
        upsert_catalog_records(data_root=data_root, inventory=inventory, refresh_coverage=False)
        if refresh_coverage:
            refresh_coverage_runs(
                data_root=data_root,
                adjust=adjust,
                timeframes=(timeframe,),
                symbols=tuple(compacted_symbols),
                inventory=inventory,
            )
        _clear_fast_plan_cache()
    return result


def delta_sidecar_summary(
    *,
    data_root: str | Path,
    adjust: str,
    timeframes: tuple[str, ...] | list[str] | None = None,
    part_threshold: int = 200,
    byte_threshold: int = 256 * 1024 * 1024,
) -> dict[str, object]:
    normalized_timeframes = tuple(timeframes or TIMEFRAME_DIR_NAMES.keys())
    compact_part_threshold = max(int(part_threshold), 1)
    compact_byte_threshold = max(int(byte_threshold), 1)
    by_timeframe: list[dict[str, object]] = []
    total_symbols = 0
    total_parts = 0
    total_bytes = 0
    for timeframe in normalized_timeframes:
        normalized_timeframe = str(timeframe)
        root = resolve_timeframe_root(data_root, normalized_timeframe) / adjust
        symbols = 0
        parts = 0
        bytes_total = 0
        newest_mtime = pd.NaT
        if root.exists():
            for delta_root in root.glob(f"*{DELTA_DIR_SUFFIX}"):
                if not delta_root.is_dir():
                    continue
                delta_parts = [part for part in delta_root.glob("*.parquet") if part.is_file()]
                if not delta_parts:
                    continue
                symbols += 1
                parts += len(delta_parts)
                for part in delta_parts:
                    stat = part.stat()
                    bytes_total += int(stat.st_size)
                    modified = pd.Timestamp(stat.st_mtime, unit="s")
                    newest_mtime = modified if pd.isna(newest_mtime) else max(newest_mtime, modified)
        total_symbols += symbols
        total_parts += parts
        total_bytes += bytes_total
        by_timeframe.append(
            {
                "timeframe": normalized_timeframe,
                "symbol_count": symbols,
                "part_count": parts,
                "file_size_bytes": bytes_total,
                "modified_at": newest_mtime,
                "needs_compaction": bool(parts >= compact_part_threshold or bytes_total >= compact_byte_threshold),
            }
        )
    return {
        "summary": {
            "symbol_count": total_symbols,
            "part_count": total_parts,
            "file_size_bytes": total_bytes,
            "needs_compaction": any(bool(row["needs_compaction"]) for row in by_timeframe),
            "part_threshold": compact_part_threshold,
            "byte_threshold": compact_byte_threshold,
        },
        "by_timeframe": by_timeframe,
    }


def _emit_write_progress(
    progress_callback,
    *,
    timeframe: str,
    symbol: str,
    index: int,
    total: int,
    action: str,
) -> None:
    if progress_callback is None:
        return
    if index == 1 or index == total or index % WRITE_PROGRESS_INTERVAL == 0:
        progress_callback(
            {
                "stage": "worker_commit_progress",
                "timeframe": timeframe,
                "symbol": symbol,
                "symbol_index": index,
                "symbol_count": total,
                "action": action,
                "message": f"提交本地缓存 {timeframe}：{index}/{total}，{symbol}，{action}。",
            }
        )


def _refresh_written_catalog_records(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
    refresh_coverage: bool,
) -> None:
    if not symbols:
        return
    inventory = inventory_local_data(
        data_root=data_root,
        timeframes=(timeframe,),
        adjust=adjust,
        symbols=list(symbols),
    )
    upsert_catalog_records(data_root=data_root, inventory=inventory, refresh_coverage=refresh_coverage)
    _clear_fast_plan_cache()


def _upsert_catalog_records_from_write_result(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    result: pd.DataFrame,
    refresh_coverage: bool,
) -> None:
    if result.empty:
        return
    rows: list[dict[str, object]] = []
    for item in result.itertuples(index=False):
        symbol = str(getattr(item, "symbol", "") or "")
        if not symbol:
            continue
        path = Path(str(getattr(item, "path", "") or ""))
        file_size_bytes = int(getattr(item, "file_size_bytes", 0) or 0)
        modified_at = getattr(item, "modified_at", pd.NaT)
        try:
            modified_missing = pd.isna(pd.Timestamp(modified_at))
        except (TypeError, ValueError):
            modified_missing = True
        if file_size_bytes <= 0 or modified_missing:
            file_size_bytes, modified_at = _file_state_with_deltas(path)
        rows.append(
            {
                "stock_code": symbol,
                "timeframe": timeframe,
                "adjust": adjust,
                "status": "cached",
                "exists": True,
                "rows": int(getattr(item, "rows", 0) or 0),
                "start": getattr(item, "start", pd.NaT),
                "end": getattr(item, "end", pd.NaT),
                "file_size_bytes": file_size_bytes,
                "modified_at": modified_at,
                "missing_columns": "",
                "path": str(path),
                "message": "本地 parquet 可用于读取；delta 提交已直接更新索引。",
            }
        )
    if not rows:
        return
    inventory = pd.DataFrame(rows)
    upsert_catalog_records(data_root=data_root, inventory=inventory, refresh_coverage=refresh_coverage)
    _clear_fast_plan_cache()


def _file_state_with_deltas(path: Path) -> tuple[int, pd.Timestamp]:
    paths = [path] if path.exists() else []
    paths.extend(_delta_part_paths(path))
    existing = [item for item in paths if item.exists()]
    if not existing:
        return 0, pd.NaT
    file_size = sum(int(item.stat().st_size) for item in existing)
    modified_at = max(pd.Timestamp(item.stat().st_mtime, unit="s") for item in existing)
    return int(file_size), modified_at


def _append_new_tail_rows_after_overlap_if_possible(path: Path, *, symbol: str, incoming: pd.DataFrame) -> dict[str, object] | None:
    summary = _parquet_file_summary(path, symbol=symbol)
    if summary is None:
        return None
    previous_end = pd.Timestamp(summary["end"])
    if pd.isna(previous_end):
        return None
    incoming_dates = pd.to_datetime(incoming["date"], errors="coerce")
    incoming_existing = incoming.loc[incoming_dates <= previous_end].copy()
    incoming_new = incoming.loc[incoming_dates > previous_end].copy()
    if incoming_existing.empty or incoming_new.empty:
        return None
    existing = _read_symbol_window_with_deltas(
        path,
        symbol=symbol,
        start_ts=pd.Timestamp(incoming_existing["date"].min()),
        end_ts=pd.Timestamp(incoming_existing["date"].max()),
    )
    existing_subset = existing.loc[existing["date"].isin(set(incoming_existing["date"]))].copy()
    if not _same_bars(existing_subset, incoming_existing):
        return None
    appended = _append_tail_rows_if_possible(path, symbol=symbol, incoming=incoming_new)
    if appended is None:
        return None
    appended["message"] = "TDX 行情已校验重叠窗口并追加新 K 线。"
    return appended


def _append_tail_rows_if_possible(path: Path, *, symbol: str, incoming: pd.DataFrame) -> dict[str, object] | None:
    summary = _parquet_file_summary(path, symbol=symbol)
    if summary is None:
        return None
    previous_end = pd.Timestamp(summary["end"])
    incoming_start = incoming["date"].min()
    if pd.isna(previous_end) or pd.isna(incoming_start) or pd.Timestamp(incoming_start) <= previous_end:
        return None
    try:
        delta_path = _write_delta_part(path, incoming)
    except Exception:  # noqa: BLE001
        return None
    start = summary["start"]
    end = incoming["date"].max()
    return {
        "symbol": symbol,
        "status": "success",
        "rows": int(summary["rows"]) + int(len(incoming)),
        "new_rows": int(len(incoming)),
        "path": str(path),
        "start": start,
        "end": end,
        "message": f"TDX 行情已追加写入 delta：{delta_path.name}。",
    }


def _unchanged_existing_rows(path: Path, *, symbol: str, incoming: pd.DataFrame) -> dict[str, object] | None:
    if incoming.empty:
        return None
    start_ts = incoming["date"].min()
    end_ts = incoming["date"].max()
    if pd.isna(start_ts) or pd.isna(end_ts):
        return None
    try:
        existing = _read_symbol_window_with_deltas(path, symbol=symbol, start_ts=pd.Timestamp(start_ts), end_ts=pd.Timestamp(end_ts))
    except Exception:  # noqa: BLE001
        return None
    if existing.empty:
        return None
    incoming_dates = set(pd.to_datetime(incoming["date"], errors="coerce").dropna())
    existing_subset = existing.loc[existing["date"].isin(incoming_dates)].copy()
    if not _same_bars(existing_subset, incoming):
        return None
    summary = _parquet_file_summary(path, symbol=symbol)
    if summary is None:
        return None
    return summary


def _same_bars(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    normalized_left = _comparable_bars(left)
    normalized_right = _comparable_bars(right)
    if len(normalized_left) != len(normalized_right):
        return False
    if normalized_left.empty and normalized_right.empty:
        return True
    return bool(normalized_left.equals(normalized_right))


def _comparable_bars(frame: pd.DataFrame) -> pd.DataFrame:
    result = normalize_bars(frame)
    for column in ("open", "high", "low", "close", "volume", "amount"):
        result[column] = pd.to_numeric(result[column], errors="coerce").round(8)
    return result.loc[:, CANONICAL_COLUMNS].sort_values(["stock_code", "date"]).reset_index(drop=True)


def _parquet_file_summary(path: Path, *, symbol: str) -> dict[str, object] | None:
    summaries: list[dict[str, object]] = []
    base_summary = _single_parquet_file_summary(path, symbol=symbol)
    if base_summary is not None:
        summaries.append(base_summary)
    for delta_path in _delta_part_paths(path):
        delta_summary = _single_parquet_file_summary(delta_path, symbol=symbol)
        if delta_summary is not None:
            summaries.append(delta_summary)
    if not summaries:
        return None
    valid = [summary for summary in summaries if int(summary.get("rows", 0) or 0) > 0]
    if not valid:
        return {"rows": 0, "start": pd.NaT, "end": pd.NaT}
    if _summary_ranges_overlap(valid):
        identity = _read_identity_with_deltas(path)
        if identity.empty:
            return {"rows": 0, "start": pd.NaT, "end": pd.NaT}
        identity = identity.loc[identity["stock_code"].map(lambda value: str(value).strip().upper()).eq(symbol)].copy()
        dates = _normalized_bar_dates(identity["date"], timeframe=_timeframe_from_path(path))
        return {"rows": len(dates), "start": min(dates) if dates else pd.NaT, "end": max(dates) if dates else pd.NaT}
    starts = [pd.Timestamp(summary["start"]) for summary in valid if not pd.isna(summary.get("start", pd.NaT))]
    ends = [pd.Timestamp(summary["end"]) for summary in valid if not pd.isna(summary.get("end", pd.NaT))]
    return {
        "rows": int(sum(int(summary.get("rows", 0) or 0) for summary in valid)),
        "start": min(starts) if starts else pd.NaT,
        "end": max(ends) if ends else pd.NaT,
    }


def _summary_ranges_overlap(summaries: list[dict[str, object]]) -> bool:
    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for summary in summaries:
        start = pd.Timestamp(summary.get("start", pd.NaT))
        end = pd.Timestamp(summary.get("end", pd.NaT))
        if pd.isna(start) or pd.isna(end):
            return True
        ranges.append((start, end))
    previous_end = pd.NaT
    for start, end in sorted(ranges, key=lambda item: (item[0], item[1])):
        if not pd.isna(previous_end) and start <= previous_end:
            return True
        previous_end = end
    return False


def _single_parquet_file_summary(path: Path, *, symbol: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        parquet_file = pq.ParquetFile(path)
    except Exception:  # noqa: BLE001
        return None
    metadata = parquet_file.metadata
    if metadata is None:
        return None
    rows = int(metadata.num_rows)
    if rows <= 0:
        return {"rows": 0, "start": pd.NaT, "end": pd.NaT}
    date_index = _schema_column_index(parquet_file, "date")
    symbol_index = _schema_column_index(parquet_file, "stock_code")
    if date_index is not None and symbol_index is not None:
        starts: list[pd.Timestamp] = []
        ends: list[pd.Timestamp] = []
        for row_group_index in range(metadata.num_row_groups):
            row_group = metadata.row_group(row_group_index)
            symbol_stats = row_group.column(symbol_index).statistics
            if not _row_group_symbol_matches(symbol_stats, symbol=symbol):
                starts = []
                break
            date_stats = row_group.column(date_index).statistics
            if date_stats is None or not date_stats.has_min_max or date_stats.null_count:
                starts = []
                break
            starts.append(pd.Timestamp(date_stats.min))
            ends.append(pd.Timestamp(date_stats.max))
        if starts and ends:
            return {"rows": rows, "start": min(starts), "end": max(ends)}
    try:
        dates = pd.read_parquet(path, columns=["date"])
    except Exception:  # noqa: BLE001
        return None
    parsed = pd.to_datetime(dates["date"], errors="coerce").dropna()
    if parsed.empty:
        return {"rows": rows, "start": pd.NaT, "end": pd.NaT}
    return {"rows": rows, "start": parsed.min(), "end": parsed.max()}


def _read_identity_with_deltas(path: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item_path in ([path] if path.exists() else []) + _delta_part_paths(path):
        try:
            frame = pd.read_parquet(item_path, columns=["date", "stock_code"])
        except Exception:  # noqa: BLE001
            continue
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "stock_code"])


def _timeframe_from_path(path: Path) -> str:
    parent_names = {parent.name for parent in path.parents}
    for timeframe, dirname in TIMEFRAME_DIR_NAMES.items():
        if dirname in parent_names:
            return timeframe
    return "1d"


def _schema_column_index(parquet_file: pq.ParquetFile, column: str) -> int | None:
    try:
        return parquet_file.schema.names.index(column)
    except ValueError:
        return None


def _row_group_symbol_matches(stats: object, *, symbol: str) -> bool:
    if stats is None or not getattr(stats, "has_min_max", False) or getattr(stats, "null_count", 0):
        return False
    return str(getattr(stats, "min", "")) == symbol and str(getattr(stats, "max", "")) == symbol


def _read_bars_parquet_window(
    path: Path,
    *,
    symbol: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    """按标准列和时间窗口读取 parquet，减少分钟线大文件的无效 IO。"""
    try:
        frame = pd.read_parquet(
            path,
            columns=list(CANONICAL_COLUMNS),
            filters=_date_window_filters(start_ts, end_ts),
        )
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
        if not _is_date_filter_type_mismatch(exc):
            raise
        frame = pd.read_parquet(path, columns=list(CANONICAL_COLUMNS))
    normalized = normalize_bars(frame, symbol)
    return normalized.loc[normalized["date"].between(start_ts, end_ts)].reset_index(drop=True)


def _read_symbol_window_with_deltas(
    path: Path,
    *,
    symbol: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if path.exists():
        base = _read_bars_parquet_window(path, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
        if not base.empty:
            frames.append(base)
    for delta_path in _delta_part_paths(path):
        delta = _read_bars_parquet_window(delta_path, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
        if not delta.empty:
            frames.append(delta)
    if not frames:
        return empty_bars()
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["stock_code", "date"], keep="last")
        .sort_values(["stock_code", "date"])
        .reset_index(drop=True)
    )


def _read_symbol_all_with_deltas(path: Path, *, symbol: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item_path in [path, *_delta_part_paths(path)]:
        if not item_path.exists():
            continue
        frame = normalize_bars(pd.read_parquet(item_path, columns=list(CANONICAL_COLUMNS)), symbol)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return empty_bars()
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["stock_code", "date"], keep="last")
        .sort_values(["stock_code", "date"])
        .reset_index(drop=True)
    )


def _read_shared_delta_window(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    requested = set(symbols)
    if not requested:
        return empty_bars()
    try:
        part_index = query_market_data_part_symbols(
            data_root=data_root,
            symbols=tuple(requested),
            adjust=adjust,
            timeframes=(timeframe,),
            start=start_ts,
            end=end_ts,
        )
    except Exception:  # noqa: BLE001
        return empty_bars()
    if part_index.empty:
        return empty_bars()
    frames: list[pd.DataFrame] = []
    for path_text, group in part_index.groupby("path", sort=False):
        part_path = Path(str(path_text))
        if not part_path.exists():
            continue
        group_symbols = tuple(
            str(symbol)
            for symbol in group["stock_code"].dropna().astype(str).drop_duplicates().tolist()
            if str(symbol) in requested
        )
        if not group_symbols:
            continue
        try:
            frame = pd.read_parquet(
                part_path,
                columns=list(CANONICAL_COLUMNS),
                filters=[
                    ("stock_code", "in", list(group_symbols)),
                    ("date", ">=", start_ts),
                    ("date", "<=", end_ts),
                ],
            )
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            frame = pd.read_parquet(part_path, columns=list(CANONICAL_COLUMNS))
        except Exception:  # noqa: BLE001
            continue
        if frame.empty:
            continue
        normalized = normalize_bars(frame)
        normalized = normalized.loc[
            normalized["stock_code"].isin(requested)
            & normalized["date"].between(start_ts, end_ts)
        ].copy()
        if normalized.empty:
            continue
        commit_versions = pd.to_numeric(group["commit_version"], errors="coerce").dropna()
        normalized["_commit_version"] = int(commit_versions.max()) if not commit_versions.empty else 0
        frames.append(normalized)
    if not frames:
        return empty_bars()
    return _combine_bar_frames(frames)


def _combine_bar_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    usable = [frame for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return empty_bars()
    prepared: list[pd.DataFrame] = []
    for frame in usable:
        item = normalize_bars(frame)
        if item.empty:
            continue
        commit_values = pd.to_numeric(frame.get("_commit_version", pd.Series([0])), errors="coerce").dropna()
        item["_commit_version"] = int(commit_values.max()) if not commit_values.empty else 0
        prepared.append(item)
    if not prepared:
        return empty_bars()
    combined = pd.concat(prepared, ignore_index=True)
    return (
        combined.sort_values(["stock_code", "date", "_commit_version"], kind="mergesort")
        .drop_duplicates(subset=["stock_code", "date"], keep="last")
        .loc[:, CANONICAL_COLUMNS]
        .sort_values(["stock_code", "date"], kind="mergesort")
        .reset_index(drop=True)
    )


def _delta_root_for_base_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}{DELTA_DIR_SUFFIX}")


def _delta_part_paths(path: Path) -> list[Path]:
    root = _delta_root_for_base_path(path)
    if not root.exists():
        return []
    return sorted((part for part in root.glob("*.parquet") if part.is_file()), key=lambda item: (item.stat().st_mtime_ns, item.name))


def _write_delta_part(path: Path, incoming: pd.DataFrame) -> Path:
    root = _delta_root_for_base_path(path)
    root.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(incoming["date"], errors="coerce").dropna()
    stamp = dates.max().strftime("%Y%m%dT%H%M%S") if not dates.empty else pd.Timestamp.utcnow().strftime("%Y%m%dT%H%M%S")
    delta_path = root / f"{stamp}-{uuid4().hex[:8]}.parquet"
    incoming.loc[:, CANONICAL_COLUMNS].reset_index(drop=True).to_parquet(delta_path, index=False)
    return delta_path


def _write_shared_delta_part(root: Path, incoming: pd.DataFrame, *, trade_month: str, commit_id: str) -> Path:
    delta_root = root / SHARED_DELTA_DIR_NAME / f"trade_month={trade_month}"
    delta_root.mkdir(parents=True, exist_ok=True)
    delta_path = delta_root / f"{commit_id}-{uuid4().hex[:8]}.parquet"
    incoming.loc[:, CANONICAL_COLUMNS].reset_index(drop=True).to_parquet(delta_path, index=False)
    return delta_path


def _safe_commit_id(value: str) -> str:
    text = "".join(character for character in str(value or "") if character.isalnum() or character in {"-", "_"})
    return text[:80] if text else f"commit-{time.time_ns()}"


def _shared_part_id(*, commit_id: str, path: Path, timeframe: str, adjust: str) -> str:
    payload = f"{commit_id}|{timeframe}|{adjust}|{path}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _shared_file_state(paths: list[Path]) -> tuple[int, pd.Timestamp]:
    existing = [path for path in paths if isinstance(path, Path) and path.exists()]
    if not existing:
        return 0, pd.NaT
    file_size = sum(int(path.stat().st_size) for path in existing)
    modified_at = max(pd.Timestamp(path.stat().st_mtime, unit="s") for path in existing)
    return int(file_size), modified_at


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discover_delta_symbols(root: Path) -> list[str]:
    if not root.exists():
        return []
    symbols = {
        symbol
        for delta_root in root.glob(f"*{DELTA_DIR_SUFFIX}")
        if delta_root.is_dir() and (symbol := delta_root.name[: -len(DELTA_DIR_SUFFIX)])
    }
    return sorted(symbols)


def _parquet_rows(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += int(pq.ParquetFile(path).metadata.num_rows)
        except Exception:  # noqa: BLE001
            continue
    return total


def _read_bars_dataset_window(
    root: Path,
    *,
    symbols: tuple[str, ...] | list[str],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    if not root.exists():
        return empty_bars()
    paths = [str(root / f"{symbol}.parquet") for symbol in symbols if (root / f"{symbol}.parquet").exists()]
    if not paths:
        return empty_bars()
    dataset = ds.dataset(paths, format="parquet")
    if sorted(set(CANONICAL_COLUMNS).difference(dataset.schema.names)):
        return empty_bars()
    table = dataset.to_table(
        columns=list(CANONICAL_COLUMNS),
        filter=(ds.field("date") >= start_ts) & (ds.field("date") <= end_ts),
    )
    frame = table.to_pandas()
    if frame.empty:
        return empty_bars()
    normalized = normalize_bars(frame)
    requested = set(symbols)
    result = normalized.loc[
        normalized["stock_code"].isin(requested) & normalized["date"].between(start_ts, end_ts)
    ].copy()
    if result.empty:
        return empty_bars()
    return result.sort_values(["stock_code", "date"]).reset_index(drop=True)


def _date_window_filters(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> list[tuple[str, str, pd.Timestamp]]:
    return [("date", ">=", start_ts), ("date", "<=", end_ts)]


def _is_date_filter_type_mismatch(exc: Exception) -> bool:
    message = str(exc).lower()
    return "timestamp" in message and "string" in message and ("greater_equal" in message or "less_equal" in message)
