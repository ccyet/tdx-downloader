from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from tdx_downloader.data.catalog import query_market_data_part_symbols
from tdx_downloader.data.schema import (
    CANONICAL_COLUMNS,
    SUPPORTED_TIMEFRAMES,
    ensure_supported_timeframe,
    normalize_symbol,
    resolve_timeframe_root,
    unique_symbols,
)


INVENTORY_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "status",
    "exists",
    "rows",
    "start",
    "end",
    "file_size_bytes",
    "modified_at",
    "missing_columns",
    "path",
    "message",
]


def available_symbols(data_root: str | Path, timeframe: str, adjust: str = "qfq") -> list[str]:
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    if not root.exists():
        return []
    return sorted(set(_parquet_file_symbols(root)) | set(_delta_sidecar_symbols(root)))


def inventory_local_data(
    *,
    data_root: str | Path,
    adjust: str = "qfq",
    timeframes: tuple[str, ...] | list[str] = SUPPORTED_TIMEFRAMES,
    symbols: tuple[str, ...] | list[str] | None = None,
    existing_catalog: pd.DataFrame | None = None,
    fast_existing: bool = False,
) -> pd.DataFrame:
    """列出本地 parquet 缓存库存；用于回测前确认哪些周期和标的已经落地。"""
    normalized_timeframes = _unique_timeframes(list(timeframes))
    if not normalized_timeframes:
        raise ValueError("timeframes 不能为空。")
    normalized_symbols = (
        unique_symbols(tuple(symbols))
        if symbols is not None
        else _discover_inventory_symbols(data_root=data_root, adjust=adjust, timeframes=normalized_timeframes)
    )
    if not normalized_symbols:
        return pd.DataFrame(columns=INVENTORY_COLUMNS)

    symbol_pairs = (
        [(timeframe, symbol) for timeframe in normalized_timeframes for symbol in normalized_symbols]
        if symbols is not None
        else _discover_inventory_symbol_pairs(data_root=data_root, adjust=adjust, timeframes=normalized_timeframes)
    )
    existing_by_key = _existing_inventory_records(existing_catalog) if fast_existing else {}
    roots = {timeframe: resolve_timeframe_root(data_root, timeframe) / adjust for timeframe in normalized_timeframes}
    rows = [
        _inventory_symbol_file_from_path(
            path=(Path(str(existing["path"])) if existing and str(existing.get("path", "")) else roots[timeframe] / f"{symbol}.parquet"),
            timeframe=timeframe,
            adjust=adjust,
            symbol=symbol,
            existing=existing,
        )
        for timeframe, symbol in symbol_pairs
        for existing in (existing_by_key.get((symbol, timeframe, str(adjust))),)
    ]
    frame = pd.DataFrame(rows, columns=INVENTORY_COLUMNS)
    order = {timeframe: index for index, timeframe in enumerate(SUPPORTED_TIMEFRAMES)}
    frame["_timeframe_order"] = frame["timeframe"].map(order).fillna(len(order)).astype(int)
    return (
        frame.sort_values(["_timeframe_order", "stock_code"], kind="mergesort")
        .drop(columns=["_timeframe_order"])
        .reset_index(drop=True)
    )


def _unique_timeframes(timeframes: tuple[str, ...] | list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in timeframes:
        timeframe = ensure_supported_timeframe(item)
        if timeframe in seen:
            continue
        seen.add(timeframe)
        result.append(timeframe)
    return result


def _discover_inventory_symbols(
    *,
    data_root: str | Path,
    adjust: str,
    timeframes: list[str],
) -> list[str]:
    """未指定代码时按已存在的 parquet 文件反推标的清单。"""
    seen: set[str] = set()
    symbols: list[str] = []
    for timeframe in timeframes:
        root = resolve_timeframe_root(data_root, timeframe) / adjust
        symbols_for_timeframe = set(_shared_delta_symbols(data_root=data_root, adjust=adjust, timeframe=timeframe))
        if root.exists():
            symbols_for_timeframe.update(_parquet_file_symbols(root))
            symbols_for_timeframe.update(_delta_sidecar_symbols(root))
        for symbol in sorted(symbols_for_timeframe):
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return sorted(symbols)


def _discover_inventory_symbol_pairs(
    *,
    data_root: str | Path,
    adjust: str,
    timeframes: list[str],
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for timeframe in timeframes:
        root = resolve_timeframe_root(data_root, timeframe) / adjust
        symbols = set(_shared_delta_symbols(data_root=data_root, adjust=adjust, timeframe=timeframe))
        if root.exists():
            symbols.update(_parquet_file_symbols(root))
            symbols.update(_delta_sidecar_symbols(root))
        pairs.extend((timeframe, symbol) for symbol in symbols)
    return pairs


def _parquet_file_symbols(root: Path) -> list[str]:
    return sorted({symbol for path in root.glob("*.parquet") if path.is_file() and (symbol := normalize_symbol(path.stem))})


def _delta_sidecar_symbols(root: Path) -> list[str]:
    return sorted(
        {
            symbol
            for path in root.glob("*.delta")
            if path.is_dir() and (symbol := normalize_symbol(path.name.removesuffix(".delta")))
        }
    )


def _shared_delta_symbols(*, data_root: str | Path, adjust: str, timeframe: str) -> list[str]:
    try:
        parts = query_market_data_part_symbols(data_root=data_root, adjust=adjust, timeframes=(timeframe,))
    except Exception:  # noqa: BLE001
        return []
    if parts.empty or "stock_code" not in parts.columns:
        return []
    return sorted({symbol for value in parts["stock_code"].dropna().astype(str) if (symbol := normalize_symbol(value))})


def _inventory_symbol_file(
    *,
    root: Path,
    timeframe: str,
    adjust: str,
    symbol: str,
    existing: dict[str, object] | None = None,
) -> dict[str, object]:
    path = root / f"{symbol}.parquet"
    return _inventory_symbol_file_from_path(path=path, timeframe=timeframe, adjust=adjust, symbol=symbol, existing=existing)


def _inventory_symbol_file_from_path(
    *,
    path: Path,
    timeframe: str,
    adjust: str,
    symbol: str,
    existing: dict[str, object] | None = None,
) -> dict[str, object]:
    file_size_bytes, modified_at = _inventory_file_state(path)
    delta_paths = _delta_part_paths(path)
    shared_summary = _shared_delta_inventory_summary(path=path, timeframe=timeframe, adjust=adjust, symbol=symbol)
    if shared_summary is not None:
        shared_size = int(shared_summary.get("file_size_bytes", 0) or 0)
        shared_modified = shared_summary.get("modified_at", pd.NaT)
        if shared_size > file_size_bytes:
            file_size_bytes = shared_size
        shared_modified_ts = _naive_timestamp(shared_modified)
        modified_at_ts = _naive_timestamp(modified_at)
        if not pd.isna(shared_modified_ts):
            modified_at = shared_modified_ts if pd.isna(modified_at_ts) else max(modified_at_ts, shared_modified_ts)
    exists = path.exists() or bool(delta_paths) or shared_summary is not None
    base = {
        "stock_code": symbol,
        "timeframe": ensure_supported_timeframe(timeframe),
        "adjust": adjust,
        "exists": exists,
        "file_size_bytes": file_size_bytes,
        "modified_at": modified_at,
        "path": str(path),
    }
    if not exists:
        return _inventory_record(base, status="missing_file", message="本地 parquet 不存在。")
    if existing is not None and _existing_inventory_record_is_current(existing, base):
        return {**existing, "exists": True, "path": str(path)}
    if shared_summary is not None and not path.exists() and not delta_paths:
        return _inventory_record(
            base,
            status="cached",
            rows=shared_summary["rows"],
            start=shared_summary["start"],
            end=shared_summary["end"],
            message="本地共享 delta part 可用于读取；库存扫描复用 part-symbol 索引。",
        )
    schema_path = path if path.exists() else delta_paths[0]
    try:
        parquet_file = pq.ParquetFile(schema_path)
    except Exception as exc:  # noqa: BLE001
        return _inventory_record(base, status="read_error", message=f"parquet 元数据读取失败：{exc}")

    missing_columns = sorted(set(CANONICAL_COLUMNS).difference(parquet_file.schema.names))
    if missing_columns:
        return _inventory_record(
            base,
            status="missing_columns",
            rows=_parquet_num_rows(parquet_file),
            missing_columns=",".join(missing_columns),
            message=f"缺少标准行情字段：{', '.join(missing_columns)}。",
        )
    fast_summary = _metadata_identity_summary_with_deltas(path, symbol=symbol)
    if fast_summary is not None:
        return _inventory_record(
            base,
            status="cached",
            rows=fast_summary["rows"],
            start=fast_summary["start"],
            end=fast_summary["end"],
            message="本地 parquet 可用于读取；库存扫描已使用 parquet 元数据快速确认。",
        )
    try:
        identity = _read_identity_with_deltas(path)
    except Exception as exc:  # noqa: BLE001
        return _inventory_record(base, status="read_error", message=f"parquet 关键列读取失败：{exc}")
    valid_identity = _valid_inventory_identity(identity)
    if valid_identity.empty:
        return _inventory_record(base, status="no_valid_rows", message="文件存在，但没有可用标准 K 线。")
    return _inventory_record(
        base,
        status="cached",
        rows=int(len(valid_identity)),
        start=valid_identity["date"].min(),
        end=valid_identity["date"].max(),
        message="本地 parquet 可用于读取；回测前仍建议执行覆盖率审计。",
    )


def _existing_inventory_records(catalog: pd.DataFrame | None) -> dict[tuple[str, str, str], dict[str, object]]:
    if catalog is None or catalog.empty:
        return {}
    required = {"stock_code", "timeframe", "adjust", "status", "rows", "start_at", "end_at", "file_size_bytes", "modified_at", "path", "message"}
    if not required.issubset(catalog.columns):
        return {}
    result: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in catalog.itertuples(index=False):
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        timeframe = str(getattr(row, "timeframe", "") or "")
        adjust = str(getattr(row, "adjust", "") or "")
        if not symbol or not timeframe or not adjust:
            continue
        result[(symbol, timeframe, adjust)] = {
            "stock_code": symbol,
            "timeframe": timeframe,
            "adjust": adjust,
            "status": str(getattr(row, "status", "") or ""),
            "exists": True,
            "rows": int(getattr(row, "rows", 0) or 0),
            "start": getattr(row, "start_at", pd.NaT),
            "end": getattr(row, "end_at", pd.NaT),
            "file_size_bytes": int(getattr(row, "file_size_bytes", 0) or 0),
            "modified_at": getattr(row, "modified_at", pd.NaT),
            "modified_at_epoch": _timestamp_epoch(getattr(row, "modified_at", pd.NaT)),
            "missing_columns": "",
            "path": str(getattr(row, "path", "") or ""),
            "message": str(getattr(row, "message", "") or "本地 parquet 可用于读取；库存扫描复用未变化的 SQLite 索引。"),
        }
    return result


def _existing_inventory_record_is_current(existing: dict[str, object], base: dict[str, object]) -> bool:
    if str(existing.get("status", "")) != "cached":
        return False
    try:
        old_size = int(existing.get("file_size_bytes", 0) or 0)
        new_size = int(base.get("file_size_bytes", 0) or 0)
    except (TypeError, ValueError):
        return False
    if old_size != new_size:
        return False
    old_epoch = existing.get("modified_at_epoch")
    new_epoch = _timestamp_epoch(base.get("modified_at", pd.NaT))
    if old_epoch is None or new_epoch is None:
        return False
    return abs(float(old_epoch) - float(new_epoch)) <= 1.0


def _timestamp_epoch(value: object) -> float | None:
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return float(value.timestamp())
    try:
        return float(pd.Timestamp(value).timestamp())
    except (TypeError, ValueError):
        return None


def _naive_timestamp(value: object) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(timestamp):
        return pd.NaT
    if timestamp.tzinfo is not None:
        return timestamp.tz_convert(None)
    return timestamp


def _inventory_file_state(path: Path) -> tuple[int, pd.Timestamp]:
    paths = [path] if path.exists() else []
    paths.extend(_delta_part_paths(path))
    if not paths:
        return 0, pd.NaT
    size = sum(int(item.stat().st_size) for item in paths if item.exists())
    modified = max(pd.Timestamp.fromtimestamp(item.stat().st_mtime) for item in paths if item.exists())
    return int(size), modified


def _shared_delta_inventory_summary(
    *,
    path: Path,
    timeframe: str,
    adjust: str,
    symbol: str,
) -> dict[str, object] | None:
    try:
        parts = query_market_data_part_symbols(
            data_root=_data_root_from_symbol_path(path, timeframe=timeframe, adjust=adjust),
            symbols=(symbol,),
            adjust=adjust,
            timeframes=(timeframe,),
        )
    except Exception:  # noqa: BLE001
        return None
    if parts.empty:
        return None
    starts = pd.to_datetime(parts["min_at"], errors="coerce").dropna()
    ends = pd.to_datetime(parts["max_at"], errors="coerce").dropna()
    if starts.empty or ends.empty:
        return None
    return {
        "rows": int(pd.to_numeric(parts["rows"], errors="coerce").fillna(0).sum()),
        "start": starts.min(),
        "end": ends.max(),
        "file_size_bytes": int(pd.to_numeric(parts["file_size_bytes"], errors="coerce").fillna(0).drop_duplicates().sum()),
        "modified_at": pd.to_datetime(parts["created_at"], errors="coerce").dropna().max(),
    }


def _data_root_from_symbol_path(path: Path, *, timeframe: str, adjust: str) -> Path:
    timeframe_root = resolve_timeframe_root(".", timeframe)
    dirname = timeframe_root.name
    parts = list(path.parts)
    if len(parts) >= 3 and parts[-2] == adjust and parts[-3] == dirname:
        return Path(*parts[:-3])
    return path.parent.parent.parent


def _parquet_num_rows(parquet_file: pq.ParquetFile) -> int:
    metadata = parquet_file.metadata
    return int(metadata.num_rows) if metadata is not None else 0


def _metadata_identity_summary_with_deltas(
    path: Path,
    *,
    symbol: str,
) -> dict[str, object] | None:
    summaries: list[dict[str, object]] = []
    paths = [path] if path.exists() else []
    paths.extend(_delta_part_paths(path))
    for item_path in paths:
        try:
            parquet_file = pq.ParquetFile(item_path)
        except Exception:  # noqa: BLE001
            return None
        summary = _metadata_identity_summary(parquet_file, symbol=symbol)
        if summary is not None:
            summaries.append(summary)
    if not summaries:
        return None
    if _summary_ranges_overlap(summaries):
        return None
    starts = [pd.Timestamp(summary["start"]) for summary in summaries if not pd.isna(summary.get("start", pd.NaT))]
    ends = [pd.Timestamp(summary["end"]) for summary in summaries if not pd.isna(summary.get("end", pd.NaT))]
    return {
        "rows": int(sum(int(summary.get("rows", 0) or 0) for summary in summaries)),
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


def _metadata_identity_summary(parquet_file: pq.ParquetFile, *, symbol: str) -> dict[str, object] | None:
    """标准缓存文件用 parquet 统计信息取行数和窗口，避免库存扫描读整列。"""
    metadata = parquet_file.metadata
    if metadata is None or metadata.num_rows <= 0:
        return None
    if normalize_symbol(symbol) != symbol:
        return None
    date_index = _schema_column_index(parquet_file, "date")
    symbol_index = _schema_column_index(parquet_file, "stock_code")
    if date_index is None or symbol_index is None:
        return None

    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        if not _row_group_symbol_matches(row_group.column(symbol_index).statistics, symbol=symbol):
            return None
        stats = row_group.column(date_index).statistics
        if stats is None or not stats.has_min_max or stats.null_count:
            return None
        starts.append(pd.Timestamp(stats.min))
        ends.append(pd.Timestamp(stats.max))
    if not starts or not ends:
        return None
    return {"rows": int(metadata.num_rows), "start": min(starts), "end": max(ends)}


def _delta_part_paths(path: Path) -> list[Path]:
    root = path.with_name(f"{path.stem}.delta")
    if not root.exists():
        return []
    return sorted(part for part in root.glob("*.parquet") if part.is_file())


def _read_identity_with_deltas(path: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item_path in ([path] if path.exists() else []) + _delta_part_paths(path):
        identity = pd.read_parquet(item_path, columns=["date", "stock_code"])
        if not identity.empty:
            frames.append(identity)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "stock_code"])


def _schema_column_index(parquet_file: pq.ParquetFile, column: str) -> int | None:
    try:
        return parquet_file.schema.names.index(column)
    except ValueError:
        return None


def _row_group_symbol_matches(stats: object, *, symbol: str) -> bool:
    if stats is None or not getattr(stats, "has_min_max", False) or getattr(stats, "null_count", 0):
        return False
    return normalize_symbol(getattr(stats, "min", "")) == symbol and normalize_symbol(getattr(stats, "max", "")) == symbol


def _valid_inventory_identity(identity: pd.DataFrame) -> pd.DataFrame:
    """库存扫描只需要代码和日期；完整 OHLC 质量交给 audit-data。"""
    result = identity.loc[:, ["date", "stock_code"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["stock_code"] = result["stock_code"].map(normalize_symbol).replace("", pd.NA)
    result = result.dropna(subset=["date", "stock_code"])
    return result.drop_duplicates(subset=["stock_code", "date"], keep="last").sort_values(
        ["stock_code", "date"],
        kind="mergesort",
    )


def _inventory_record(base: dict[str, object], **overrides: object) -> dict[str, object]:
    record = {
        **base,
        "status": "",
        "rows": 0,
        "start": pd.NaT,
        "end": pd.NaT,
        "missing_columns": "",
        "message": "",
    }
    record.update(overrides)
    return record
