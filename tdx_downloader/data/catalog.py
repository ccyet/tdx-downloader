from __future__ import annotations

from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3

import pandas as pd

from tdx_downloader.data.schema import (
    canonical_data_root,
    ensure_supported_timeframe,
    inclusive_end_timestamp,
    normalize_bars,
    normalize_symbol,
    resolve_timeframe_root,
)

CATALOG_FILE_NAME = "market_data_catalog.sqlite"
CATALOG_READ_TIMEOUT_SECONDS = 15
CATALOG_WRITE_TIMEOUT_SECONDS = 30
CATALOG_READ_BUSY_TIMEOUT_MS = CATALOG_READ_TIMEOUT_SECONDS * 1000
CATALOG_WRITE_BUSY_TIMEOUT_MS = CATALOG_WRITE_TIMEOUT_SECONDS * 1000
CATALOG_CORRUPT_MARKER = "corrupt"
_LOGGER = logging.getLogger(__name__)
CATALOG_COLUMNS = [
    "cache_key",
    "stock_code",
    "stock_name",
    "asset_type",
    "data_kind",
    "indicator",
    "timeframe",
    "adjust",
    "storage_format",
    "status",
    "rows",
    "start_at",
    "end_at",
    "file_size_bytes",
    "modified_at",
    "path",
    "message",
]
COVERAGE_RUN_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "start_at",
    "end_at",
    "row_count",
    "file_size_bytes",
    "mtime_ns",
    "path",
    "updated_at",
]
PART_COLUMNS = [
    "part_id",
    "job_id",
    "timeframe",
    "adjust",
    "trade_month",
    "path",
    "rows",
    "min_at",
    "max_at",
    "file_size_bytes",
    "sha256",
    "commit_version",
    "state",
    "created_at",
]
PART_SYMBOL_COLUMNS = [
    "part_id",
    "stock_code",
    "min_at",
    "max_at",
    "rows",
]
UNRESOLVED_GAP_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "start_at",
    "end_at",
    "missing_rows",
    "status",
    "first_seen_at",
    "last_seen_at",
    "retry_count",
    "last_fetch_rows",
    "message",
    "updated_at",
]
ASSET_TYPE_LABELS = {
    "stock": "个股",
    "index": "指数",
    "etf": "ETF",
    "other": "其他",
}
DATA_KIND_LABELS = {"price": "价格成交", "indicator": "技术指标"}
INDICATOR_LABELS = {"ohlcv": "原始OHLCV"}


class CatalogDatabaseBusy(RuntimeError):
    """Raised when catalog metadata is temporarily locked by another writer."""


class CatalogDatabaseCorrupt(RuntimeError):
    """Raised when catalog metadata cannot be recovered from a malformed SQLite file."""


def catalog_path_for(data_root: str | Path) -> Path:
    root = _catalog_root(data_root)
    return root / "metadata" / CATALOG_FILE_NAME


def enrich_inventory_for_catalog(inventory: pd.DataFrame, *, symbol_metadata: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = inventory.copy()
    if frame.empty:
        return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
    name_by_symbol = _symbol_name_map(symbol_metadata)
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["stock_name"] = frame["stock_code"].map(lambda symbol: name_by_symbol.get(symbol, ""))
    frame["asset_type"] = [
        infer_asset_type(symbol, name)
        for symbol, name in zip(frame["stock_code"], frame["stock_name"], strict=False)
    ]
    if "data_kind" not in frame.columns:
        frame["data_kind"] = "price"
    else:
        frame["data_kind"] = frame["data_kind"].fillna("price").astype(str).replace("", "price")
    if "indicator" not in frame.columns:
        frame["indicator"] = "ohlcv"
    else:
        frame["indicator"] = frame["indicator"].fillna("ohlcv").astype(str).replace("", "ohlcv")
    if "storage_format" not in frame.columns:
        frame["storage_format"] = "parquet"
    else:
        frame["storage_format"] = frame["storage_format"].fillna("parquet").astype(str).replace("", "parquet")
    frame["start_at"] = frame.get("start", pd.Series([pd.NaT] * len(frame))).map(_timestamp_text)
    frame["end_at"] = frame.get("end", pd.Series([pd.NaT] * len(frame))).map(_timestamp_text)
    frame["modified_at"] = frame.get("modified_at", pd.Series([pd.NaT] * len(frame))).map(_timestamp_text)
    frame["cache_key"] = [
        "|".join(
            [
                str(row.stock_code),
                str(row.asset_type),
                str(row.data_kind),
                str(row.indicator),
                str(row.timeframe),
                str(row.adjust),
                str(row.path),
            ]
        )
        for row in frame.itertuples(index=False)
    ]
    for column in CATALOG_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame.loc[:, CATALOG_COLUMNS].reset_index(drop=True)


def build_catalog(
    *,
    data_root: str | Path,
    inventory: pd.DataFrame,
    symbol_metadata: pd.DataFrame | None = None,
    refresh_coverage: bool = True,
) -> Path:
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = enrich_inventory_for_catalog(inventory, symbol_metadata=symbol_metadata)
    try:
        with closing(connect_catalog(path, read_only=False)) as connection:
            _init_catalog(connection)
            connection.execute("DELETE FROM market_data_files")
            if refresh_coverage:
                connection.execute("DELETE FROM market_data_coverage_runs")
            if not records.empty:
                records.to_sql("market_data_files", connection, if_exists="append", index=False)
            connection.commit()
    except sqlite3.OperationalError as exc:
        if _is_catalog_locked_error(exc):
            raise CatalogDatabaseBusy(f"catalog database is locked: {path}") from exc
        raise
    if refresh_coverage:
        refresh_coverage_runs(data_root=data_root, inventory=records)
    return path


def upsert_catalog_records(
    *,
    data_root: str | Path,
    inventory: pd.DataFrame,
    symbol_metadata: pd.DataFrame | None = None,
    refresh_coverage: bool = True,
) -> Path:
    """增量写入本地行情索引；供 parquet 写入后同步刷新 metadata。"""
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = enrich_inventory_for_catalog(inventory, symbol_metadata=symbol_metadata)
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        if not records.empty:
            records = _fill_existing_catalog_names(connection, records)
            normalized = records.where(pd.notna(records), "")
            columns = list(CATALOG_COLUMNS)
            placeholders = ",".join("?" for _ in columns)
            column_sql = ",".join(columns)
            sql = f"INSERT OR REPLACE INTO market_data_files ({column_sql}) VALUES ({placeholders})"
            connection.executemany(
                sql,
                [tuple(row[column] for column in columns) for row in normalized.to_dict("records")],
            )
        connection.commit()
    if refresh_coverage:
        refresh_coverage_runs(data_root=data_root, inventory=records)
    return path


def query_catalog(
    *,
    data_root: str | Path,
    symbols: Sequence[str] | None = None,
    adjust: str | None = None,
    asset_types: Sequence[str] | None = None,
    timeframes: Sequence[str] | None = None,
    indicators: Sequence[str] | None = None,
    data_kinds: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    read_timeout_seconds: float | None = None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
    where: list[str] = []
    params: list[object] = []
    symbol_values = tuple(normalize_symbol(value) for value in _sequence_values(symbols) if normalize_symbol(value))
    if symbol_values:
        placeholders = ",".join("?" for _ in symbol_values)
        where.append(f"stock_code IN ({placeholders})")
        params.extend(symbol_values)
    if adjust:
        where.append("adjust = ?")
        params.append(str(adjust))
    for column, values in (
        ("asset_type", asset_types),
        ("timeframe", timeframes),
        ("indicator", indicators),
        ("data_kind", data_kinds),
        ("status", statuses),
    ):
        values_tuple = tuple(str(value) for value in _sequence_values(values) if str(value))
        if not values_tuple:
            continue
        placeholders = ",".join("?" for _ in values_tuple)
        where.append(f"{column} IN ({placeholders})")
        params.extend(values_tuple)
    sql = "SELECT * FROM market_data_files"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY asset_type, timeframe, stock_code"
    for attempt in range(2):
        try:
            with closing(connect_catalog(path, read_only=True, timeout_seconds=read_timeout_seconds)) as connection:
                if not _catalog_table_exists(connection, "market_data_files"):
                    return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
                return pd.read_sql_query(sql, connection, params=params)
        except (sqlite3.DatabaseError, pd.errors.DatabaseError) as exc:
            if _is_missing_table_error(exc):
                return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
            raise
    return pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))


def query_coverage_runs(
    *,
    data_root: str | Path,
    symbols: Sequence[str] | None = None,
    adjust: str | None = None,
    timeframes: Sequence[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    read_timeout_seconds: float | None = None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    where: list[str] = []
    params: list[object] = []
    symbol_values = tuple(normalize_symbol(value) for value in _sequence_values(symbols) if normalize_symbol(value))
    if symbol_values:
        placeholders = ",".join("?" for _ in symbol_values)
        where.append(f"stock_code IN ({placeholders})")
        params.extend(symbol_values)
    if adjust is not None:
        where.append("adjust = ?")
        params.append(str(adjust))
    timeframe_values = tuple(ensure_supported_timeframe(value) for value in _sequence_values(timeframes) if str(value))
    if timeframe_values:
        placeholders = ",".join("?" for _ in timeframe_values)
        where.append(f"timeframe IN ({placeholders})")
        params.extend(timeframe_values)
    if start is not None:
        start_ts = pd.Timestamp(start)
        if not pd.isna(start_ts):
            where.append("end_at >= ?")
            params.append(start_ts.isoformat())
    if end is not None:
        end_ts = _inclusive_catalog_end_timestamp(end)
        if not pd.isna(end_ts):
            where.append("start_at <= ?")
            params.append(end_ts.isoformat())
    sql = "SELECT * FROM market_data_coverage_runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timeframe, stock_code, start_at"
    for attempt in range(2):
        try:
            with closing(connect_catalog(path, read_only=True, timeout_seconds=read_timeout_seconds)) as connection:
                if not _catalog_table_exists(connection, "market_data_coverage_runs"):
                    return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
                return pd.read_sql_query(sql, connection, params=params)
        except (sqlite3.DatabaseError, pd.errors.DatabaseError) as exc:
            if _is_missing_table_error(exc):
                return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog coverage database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
            raise
    return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))


def query_coverage_keys(
    *,
    data_root: str | Path,
    symbols: Sequence[str] | None = None,
    adjust: str | None = None,
    timeframes: Sequence[str] | None = None,
    read_timeout_seconds: float | None = None,
) -> set[tuple[str, str]]:
    path = catalog_path_for(data_root)
    if not path.exists():
        return set()
    where: list[str] = []
    params: list[object] = []
    symbol_values = tuple(normalize_symbol(value) for value in _sequence_values(symbols) if normalize_symbol(value))
    if symbol_values:
        placeholders = ",".join("?" for _ in symbol_values)
        where.append(f"stock_code IN ({placeholders})")
        params.extend(symbol_values)
    if adjust is not None:
        where.append("adjust = ?")
        params.append(str(adjust))
    timeframe_values = tuple(ensure_supported_timeframe(value) for value in _sequence_values(timeframes) if str(value))
    if timeframe_values:
        placeholders = ",".join("?" for _ in timeframe_values)
        where.append(f"timeframe IN ({placeholders})")
        params.extend(timeframe_values)
    sql = "SELECT DISTINCT stock_code, timeframe FROM market_data_coverage_runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    for attempt in range(2):
        try:
            with closing(connect_catalog(path, read_only=True, timeout_seconds=read_timeout_seconds)) as connection:
                if not _catalog_table_exists(connection, "market_data_coverage_runs"):
                    return set()
                rows = connection.execute(sql, params).fetchall()
                return {(normalize_symbol(row[0]), str(row[1])) for row in rows}
        except sqlite3.DatabaseError as exc:
            if _is_missing_table_error(exc):
                return set()
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog coverage database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                return set()
            raise
    return set()


def upsert_market_data_parts(
    *,
    data_root: str | Path,
    parts: pd.DataFrame,
    part_symbols: pd.DataFrame,
) -> None:
    """Register immutable delta parts for fast Worker commits."""
    if parts.empty:
        return
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_parts = parts.copy()
    normalized_part_symbols = part_symbols.copy()
    for column in PART_COLUMNS:
        if column not in normalized_parts.columns:
            normalized_parts[column] = ""
    for column in PART_SYMBOL_COLUMNS:
        if column not in normalized_part_symbols.columns:
            normalized_part_symbols[column] = ""
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        part_columns = list(PART_COLUMNS)
        part_sql = (
            f"INSERT OR REPLACE INTO market_data_parts ({','.join(part_columns)}) "
            f"VALUES ({','.join('?' for _ in part_columns)})"
        )
        connection.executemany(
            part_sql,
            [
                tuple(row[column] for column in part_columns)
                for row in normalized_parts.loc[:, part_columns].where(pd.notna(normalized_parts), "").to_dict("records")
            ],
        )
        if not normalized_part_symbols.empty:
            symbol_columns = list(PART_SYMBOL_COLUMNS)
            symbol_sql = (
                f"INSERT OR REPLACE INTO market_data_part_symbols ({','.join(symbol_columns)}) "
                f"VALUES ({','.join('?' for _ in symbol_columns)})"
            )
            connection.executemany(
                symbol_sql,
                [
                    tuple(row[column] for column in symbol_columns)
                    for row in normalized_part_symbols.loc[:, symbol_columns]
                    .where(pd.notna(normalized_part_symbols), "")
                    .to_dict("records")
                ],
            )
        connection.commit()


def query_market_data_part_symbols(
    *,
    data_root: str | Path,
    symbols: Sequence[str] | None = None,
    adjust: str | None = None,
    timeframes: Sequence[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    read_timeout_seconds: float | None = None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    columns = [
        "part_id",
        "job_id",
        "timeframe",
        "adjust",
        "trade_month",
        "path",
        "part_rows",
        "part_min_at",
        "part_max_at",
        "file_size_bytes",
        "sha256",
        "commit_version",
        "state",
        "created_at",
        "stock_code",
        "min_at",
        "max_at",
        "rows",
    ]
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(columns))
    where = ["p.state = 'active'"]
    params: list[object] = []
    symbol_values = tuple(normalize_symbol(value) for value in _sequence_values(symbols) if normalize_symbol(value))
    if symbol_values:
        placeholders = ",".join("?" for _ in symbol_values)
        where.append(f"ps.stock_code IN ({placeholders})")
        params.extend(symbol_values)
    if adjust is not None:
        where.append("p.adjust = ?")
        params.append(str(adjust))
    timeframe_values = tuple(ensure_supported_timeframe(value) for value in _sequence_values(timeframes) if str(value))
    if timeframe_values:
        placeholders = ",".join("?" for _ in timeframe_values)
        where.append(f"p.timeframe IN ({placeholders})")
        params.extend(timeframe_values)
    if start is not None:
        start_ts = pd.Timestamp(start)
        if not pd.isna(start_ts):
            where.append("ps.max_at >= ?")
            params.append(start_ts.isoformat())
    if end is not None:
        end_ts = _inclusive_catalog_end_timestamp(end)
        if not pd.isna(end_ts):
            where.append("ps.min_at <= ?")
            params.append(end_ts.isoformat())
    sql = f"""
        SELECT
            p.part_id,
            p.job_id,
            p.timeframe,
            p.adjust,
            p.trade_month,
            p.path,
            p.rows AS part_rows,
            p.min_at AS part_min_at,
            p.max_at AS part_max_at,
            p.file_size_bytes,
            p.sha256,
            p.commit_version,
            p.state,
            p.created_at,
            ps.stock_code,
            ps.min_at,
            ps.max_at,
            ps.rows
        FROM market_data_part_symbols ps
        JOIN market_data_parts p ON p.part_id = ps.part_id
        WHERE {" AND ".join(where)}
        ORDER BY p.commit_version, p.part_id, ps.stock_code
    """
    for attempt in range(2):
        try:
            with closing(connect_catalog(path, read_only=True, timeout_seconds=read_timeout_seconds)) as connection:
                if not _catalog_table_exists(connection, "market_data_parts") or not _catalog_table_exists(
                    connection,
                    "market_data_part_symbols",
                ):
                    return pd.DataFrame(columns=pd.Index(columns))
                return pd.read_sql_query(sql, connection, params=params)
        except (sqlite3.DatabaseError, pd.errors.DatabaseError) as exc:
            if _is_missing_table_error(exc):
                return pd.DataFrame(columns=pd.Index(columns))
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog part database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                return pd.DataFrame(columns=pd.Index(columns))
            raise
    return pd.DataFrame(columns=pd.Index(columns))


def query_unresolved_gaps(
    *,
    data_root: str | Path,
    symbols: Sequence[str] | None = None,
    adjust: str | None = None,
    timeframes: Sequence[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    statuses: Sequence[str] | None = None,
    read_timeout_seconds: float | None = None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
    where: list[str] = []
    params: list[object] = []
    symbol_values = tuple(normalize_symbol(value) for value in _sequence_values(symbols) if normalize_symbol(value))
    if symbol_values:
        placeholders = ",".join("?" for _ in symbol_values)
        where.append(f"stock_code IN ({placeholders})")
        params.extend(symbol_values)
    if adjust is not None:
        where.append("adjust = ?")
        params.append(str(adjust))
    timeframe_values = tuple(ensure_supported_timeframe(value) for value in _sequence_values(timeframes) if str(value))
    if timeframe_values:
        placeholders = ",".join("?" for _ in timeframe_values)
        where.append(f"timeframe IN ({placeholders})")
        params.extend(timeframe_values)
    status_values = tuple(str(value) for value in _sequence_values(statuses) if str(value))
    if status_values:
        placeholders = ",".join("?" for _ in status_values)
        where.append(f"status IN ({placeholders})")
        params.extend(status_values)
    if start is not None:
        start_ts = pd.Timestamp(start)
        if not pd.isna(start_ts):
            where.append("end_at >= ?")
            params.append(start_ts.isoformat())
    if end is not None:
        end_ts = _inclusive_catalog_end_timestamp(end)
        if not pd.isna(end_ts):
            where.append("start_at <= ?")
            params.append(end_ts.isoformat())
    sql = "SELECT * FROM market_data_unresolved_gaps"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timeframe, stock_code, start_at"
    for attempt in range(2):
        try:
            with closing(connect_catalog(path, read_only=True, timeout_seconds=read_timeout_seconds)) as connection:
                if not _catalog_table_exists(connection, "market_data_unresolved_gaps"):
                    return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
                return pd.read_sql_query(sql, connection, params=params)
        except (sqlite3.DatabaseError, pd.errors.DatabaseError) as exc:
            if _is_missing_table_error(exc):
                return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog unresolved gap database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
            raise
    return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))


def upsert_unresolved_gaps(
    *,
    data_root: str | Path,
    records: pd.DataFrame,
) -> pd.DataFrame:
    if records.empty:
        return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
    prepared = _prepare_unresolved_gap_records(records)
    if prepared.empty:
        return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    updated_rows: list[dict[str, object]] = []
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        columns = list(UNRESOLVED_GAP_COLUMNS)
        existing = _query_unresolved_gap_records_for_keys(connection, prepared)
        now_text = datetime.now(timezone.utc).isoformat()
        for row in prepared.to_dict("records"):
            key = (
                str(row["stock_code"]),
                str(row["timeframe"]),
                str(row["adjust"]),
                str(row["start_at"]),
                str(row["end_at"]),
            )
            current = existing.get(key, {})
            first_seen = str(current.get("first_seen_at") or row.get("first_seen_at") or now_text)
            retry_count = int(current.get("retry_count", 0) or 0) + 1
            merged = {column: row.get(column, "") for column in columns}
            merged["first_seen_at"] = first_seen
            merged["last_seen_at"] = now_text
            merged["retry_count"] = retry_count
            merged["updated_at"] = now_text
            updated_rows.append(merged)
        placeholders = ",".join("?" for _ in columns)
        column_sql = ",".join(columns)
        sql = f"INSERT OR REPLACE INTO market_data_unresolved_gaps ({column_sql}) VALUES ({placeholders})"
        connection.executemany(sql, [tuple(row[column] for column in columns) for row in updated_rows])
        connection.commit()
    return pd.DataFrame(updated_rows, columns=pd.Index(UNRESOLVED_GAP_COLUMNS))


def clear_unresolved_gaps(
    *,
    data_root: str | Path,
    symbols: Sequence[str],
    adjust: str,
    timeframes: Sequence[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> None:
    symbol_values = tuple(normalize_symbol(value) for value in symbols if normalize_symbol(value))
    timeframe_values = tuple(ensure_supported_timeframe(value) for value in timeframes if str(value))
    if not symbol_values or not timeframe_values:
        return
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        symbol_placeholders = ",".join("?" for _ in symbol_values)
        timeframe_placeholders = ",".join("?" for _ in timeframe_values)
        connection.execute(
            f"""
            DELETE FROM market_data_unresolved_gaps
            WHERE stock_code IN ({symbol_placeholders})
              AND timeframe IN ({timeframe_placeholders})
              AND adjust = ?
              AND end_at >= ?
              AND start_at <= ?
            """,
            [*symbol_values, *timeframe_values, str(adjust), start_ts.isoformat(), end_ts.isoformat()],
        )
        connection.commit()


def maintain_catalog(*, data_root: str | Path, vacuum: bool = True) -> dict[str, object]:
    """Run explicit SQLite maintenance for the local metadata catalog."""
    path = catalog_path_for(data_root)
    before = _catalog_storage_stats(path)
    if not path.exists():
        return {"path": str(path), "exists": False, "before": before, "after": before}
    stale_parts_marked_missing = 0
    with closing(connect_catalog(path, read_only=False, timeout_seconds=CATALOG_WRITE_TIMEOUT_SECONDS)) as connection:
        _init_catalog(connection)
        stale_parts_marked_missing = _mark_missing_market_data_parts(connection)
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if vacuum:
            connection.execute("VACUUM")
        connection.commit()
    after = _catalog_storage_stats(path)
    return {
        "path": str(path),
        "exists": True,
        "vacuum": bool(vacuum),
        "stale_parts_marked_missing": int(stale_parts_marked_missing),
        "before": before,
        "after": after,
    }


def refresh_coverage_runs(
    *,
    data_root: str | Path,
    adjust: str | None = None,
    timeframes: Sequence[str] | None = None,
    symbols: Sequence[str] | None = None,
    inventory: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Refresh precise local K-line coverage runs without reading OHLCV data pages."""
    return _refresh_coverage_runs_with_recovery(
        data_root=data_root,
        adjust=adjust,
        timeframes=timeframes,
        symbols=symbols,
        inventory=inventory,
    )


def upsert_partial_coverage_runs_from_bars(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    bars: pd.DataFrame,
    merge_existing: bool = True,
) -> pd.DataFrame:
    """Record coverage from incoming bars without scanning existing parquet files.

    The stat fields are intentionally set to zero so a later explicit
    refresh_coverage_runs call still treats the file as stale and can rebuild
    precise full-file coverage.
    """
    normalized = normalize_bars(bars)
    if normalized.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    identity = normalized.loc[:, ["date", "stock_code"]]
    return _upsert_partial_coverage_runs_from_identity_frame(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        identity=identity,
        merge_existing=merge_existing,
    )


def upsert_partial_coverage_runs_from_identity(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    identity: pd.DataFrame,
    merge_existing: bool = True,
) -> pd.DataFrame:
    """Record coverage from a trusted ``date``/``stock_code`` identity table."""
    prepared = _normalize_coverage_identity(identity)
    if prepared.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    return _upsert_partial_coverage_runs_from_identity_frame(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        identity=prepared,
        merge_existing=merge_existing,
    )


def coverage_run_records_from_identity(
    *,
    identity: pd.DataFrame,
    timeframe: str,
    adjust: str,
    path: str | Path,
    file_size: int = 0,
    mtime_ns: int = 0,
    updated_at: str | None = None,
) -> pd.DataFrame:
    """Build precise coverage runs from a trusted date/stock_code table."""
    prepared = _normalize_coverage_identity(identity)
    if prepared.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    updated_text = updated_at or datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    for symbol, group in prepared.groupby("stock_code", sort=True):
        records.extend(
            _coverage_run_records_from_dates(
                dates=group["date"],
                symbol=normalize_symbol(symbol),
                timeframe=normalized_timeframe,
                adjust=str(adjust),
                file_size=int(file_size),
                mtime_ns=int(mtime_ns),
                path=Path(path),
                updated_at=updated_text,
            )
        )
    return pd.DataFrame(records, columns=pd.Index(COVERAGE_RUN_COLUMNS))


def upsert_partial_coverage_runs_from_records(
    *,
    data_root: str | Path,
    records: pd.DataFrame,
    merge_existing: bool = True,
) -> pd.DataFrame:
    """Record precomputed coverage runs without rereading parquet identity columns."""
    prepared = _normalize_coverage_run_records(records)
    if prepared.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    records_by_key: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in prepared.to_dict("records"):
        key = (str(row["stock_code"]), str(row["timeframe"]), str(row["adjust"]))
        records_by_key.setdefault(key, []).append(row)
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        if merge_existing:
            current_by_key = _query_coverage_records_for_windows(connection, records_by_key=records_by_key)
            merged_records: list[dict[str, object]] = []
            for key, incoming_records in records_by_key.items():
                symbol, item_timeframe, item_adjust = key
                item_path = Path(str(incoming_records[0].get("path") or ""))
                updated_at = str(incoming_records[0].get("updated_at") or datetime.now(timezone.utc).isoformat())
                merged_records.extend(
                    _missing_incoming_coverage_records(
                        current_records=current_by_key.get(key, []),
                        incoming_records=incoming_records,
                        symbol=symbol,
                        timeframe=item_timeframe,
                        adjust=item_adjust,
                        path=item_path,
                        updated_at=updated_at,
                    )
                )
        else:
            merged_records = prepared.to_dict("records")
        _insert_coverage_runs(connection, records=merged_records, replace=False)
        connection.commit()
    return pd.DataFrame(merged_records, columns=pd.Index(COVERAGE_RUN_COLUMNS))


def _upsert_partial_coverage_runs_from_identity_frame(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    identity: pd.DataFrame,
    merge_existing: bool,
) -> pd.DataFrame:
    if identity.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    root = resolve_timeframe_root(data_root, normalized_timeframe) / str(adjust)
    updated_at = datetime.now(timezone.utc).isoformat()
    records_by_key: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for symbol, group in identity.groupby("stock_code", sort=True):
        normalized_symbol = normalize_symbol(symbol)
        key = (normalized_symbol, normalized_timeframe, str(adjust))
        records_by_key[key] = _coverage_run_records_from_dates(
            dates=group["date"],
            symbol=normalized_symbol,
            timeframe=normalized_timeframe,
            adjust=str(adjust),
            file_size=0,
            mtime_ns=0,
            path=root / f"{normalized_symbol}.parquet",
            updated_at=updated_at,
        )
    records = [record for items in records_by_key.values() for record in items]
    if not records:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        if merge_existing:
            current_by_key = _query_coverage_records_for_windows(connection, records_by_key=records_by_key)
            merged_records: list[dict[str, object]] = []
            for key, incoming_records in records_by_key.items():
                symbol, item_timeframe, item_adjust = key
                missing_records = _missing_incoming_coverage_records(
                    current_records=current_by_key.get(key, []),
                    incoming_records=incoming_records,
                    symbol=symbol,
                    timeframe=item_timeframe,
                    adjust=item_adjust,
                    path=root / f"{symbol}.parquet",
                    updated_at=updated_at,
                )
                merged_records.extend(missing_records)
        else:
            merged_records = records
        _insert_coverage_runs(connection, records=merged_records, replace=False)
        connection.commit()
    return pd.DataFrame(merged_records, columns=pd.Index(COVERAGE_RUN_COLUMNS))


def _normalize_coverage_run_records(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    frame = records.copy()
    now_text = datetime.now(timezone.utc).isoformat()
    for column in COVERAGE_RUN_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol).replace("", pd.NA)
    frame["timeframe"] = frame["timeframe"].map(lambda value: ensure_supported_timeframe(value) if str(value) else "")
    frame["adjust"] = frame["adjust"].fillna("").astype(str)
    frame["start_at"] = pd.to_datetime(frame["start_at"], errors="coerce").map(_timestamp_text)
    frame["end_at"] = pd.to_datetime(frame["end_at"], errors="coerce").map(_timestamp_text)
    frame["row_count"] = pd.to_numeric(frame["row_count"], errors="coerce").fillna(0).astype(int)
    frame["file_size_bytes"] = pd.to_numeric(frame["file_size_bytes"], errors="coerce").fillna(0).astype(int)
    frame["mtime_ns"] = pd.to_numeric(frame["mtime_ns"], errors="coerce").fillna(0).astype(int)
    frame["path"] = frame["path"].fillna("").astype(str)
    frame["updated_at"] = frame["updated_at"].fillna("").astype(str).replace("", now_text)
    frame = frame.loc[
        frame["stock_code"].notna()
        & frame["timeframe"].astype(bool)
        & frame["adjust"].astype(bool)
        & frame["start_at"].astype(bool)
        & frame["end_at"].astype(bool)
        & frame["row_count"].gt(0)
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    return frame.loc[:, COVERAGE_RUN_COLUMNS].reset_index(drop=True)


def _normalize_coverage_identity(identity: pd.DataFrame) -> pd.DataFrame:
    if identity.empty or "date" not in identity.columns:
        return pd.DataFrame(columns=pd.Index(["date", "stock_code"]))
    frame = identity.copy()
    if "stock_code" not in frame.columns and "symbol" in frame.columns:
        frame = frame.rename(columns={"symbol": "stock_code"})
    if "stock_code" not in frame.columns:
        return pd.DataFrame(columns=pd.Index(["date", "stock_code"]))
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol).replace("", pd.NA)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "stock_code"])
    if frame.empty:
        return pd.DataFrame(columns=pd.Index(["date", "stock_code"]))
    return frame.loc[:, ["date", "stock_code"]].drop_duplicates(subset=["stock_code", "date"]).reset_index(drop=True)


def _refresh_coverage_runs_with_recovery(
    *,
    data_root: str | Path,
    adjust: str | None,
    timeframes: Sequence[str] | None,
    symbols: Sequence[str] | None,
    inventory: pd.DataFrame | None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    for attempt in range(2):
        try:
            return _refresh_coverage_runs_once(
                data_root=data_root,
                adjust=adjust,
                timeframes=timeframes,
                symbols=symbols,
                inventory=inventory,
            )
        except sqlite3.DatabaseError as exc:
            if _is_catalog_locked_error(exc):
                raise CatalogDatabaseBusy(f"catalog coverage database is locked: {path}") from exc
            if _is_catalog_corrupt_error(exc) and attempt == 0:
                _recover_corrupt_catalog(path, exc)
                continue
            raise
    raise CatalogDatabaseCorrupt(f"catalog coverage database could not be recovered: {path}")


def _refresh_coverage_runs_once(
    *,
    data_root: str | Path,
    adjust: str | None,
    timeframes: Sequence[str] | None,
    symbols: Sequence[str] | None,
    inventory: pd.DataFrame | None,
) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    targets = _coverage_refresh_targets(
        data_root=data_root,
        adjust=adjust,
        timeframes=timeframes,
        symbols=symbols,
        inventory=inventory,
    )
    if not targets:
        return pd.DataFrame(columns=pd.Index(COVERAGE_RUN_COLUMNS))
    with closing(connect_catalog(path, read_only=False)) as connection:
        _init_catalog(connection)
        existing = _existing_coverage_file_state(connection, targets=targets)
        changed: list[tuple[str, str, str]] = []
        for symbol, timeframe, item_adjust, item_path in targets:
            key = (symbol, timeframe, item_adjust)
            shared_paths = _shared_part_paths_for_key(
                connection,
                symbol=symbol,
                timeframe=timeframe,
                adjust=item_adjust,
            )
            if not item_path.exists() and not shared_paths:
                _delete_coverage_runs(connection, symbol=symbol, timeframe=timeframe, adjust=item_adjust)
                changed.append(key)
                continue
            try:
                file_size, mtime_ns = _coverage_file_state(item_path, extra_paths=shared_paths)
            except OSError:
                continue
            current = existing.get(key)
            if current == (str(item_path), file_size, mtime_ns):
                continue
            records = _coverage_run_records_for_file(
                path=item_path,
                symbol=symbol,
                timeframe=timeframe,
                adjust=item_adjust,
                file_size=file_size,
                mtime_ns=mtime_ns,
                extra_paths=shared_paths,
            )
            _replace_coverage_runs(
                connection,
                symbol=symbol,
                timeframe=timeframe,
                adjust=item_adjust,
                records=records,
            )
            changed.append(key)
        connection.commit()
        if not changed:
            return query_coverage_runs(data_root=data_root, symbols=symbols, adjust=adjust, timeframes=timeframes)
    return query_coverage_runs(data_root=data_root, symbols=symbols, adjust=adjust, timeframes=timeframes)


def infer_asset_type(symbol: object, stock_name: object = "") -> str:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return "other"
    code, exchange = normalized.split(".", 1)
    name = str(stock_name or "").upper()
    if (exchange == "SH" and code.startswith(("000", "880"))) or (exchange == "SZ" and code.startswith("399")):
        return "index"
    if "ETF" in name or "LOF" in name or "基金" in name or _looks_like_etf_code(code):
        return "etf"
    if code.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689")):
        return "stock"
    if exchange == "BJ" and code.startswith(("430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "920")):
        return "stock"
    return "other"


def asset_type_label(value: object) -> str:
    return ASSET_TYPE_LABELS.get(str(value), str(value))


def data_kind_label(value: object) -> str:
    return DATA_KIND_LABELS.get(str(value), str(value))


def indicator_label(value: object) -> str:
    return INDICATOR_LABELS.get(str(value), str(value))


def _inclusive_catalog_end_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    """Catalog windows use inclusive interval overlap semantics."""
    return inclusive_end_timestamp(value) if isinstance(value, str) else pd.Timestamp(value)


def _mark_missing_market_data_parts(connection: sqlite3.Connection) -> int:
    if not _catalog_table_exists(connection, "market_data_parts"):
        return 0
    rows = connection.execute("SELECT part_id, path FROM market_data_parts WHERE state = 'active'").fetchall()
    missing_ids = [str(part_id) for part_id, path in rows if str(part_id) and not Path(str(path)).exists()]
    if not missing_ids:
        return 0
    connection.executemany(
        "UPDATE market_data_parts SET state = 'missing' WHERE part_id = ?",
        [(part_id,) for part_id in missing_ids],
    )
    return len(missing_ids)


def connect_catalog(
    path: str | Path,
    *,
    read_only: bool,
    timeout_seconds: float | None = None,
) -> sqlite3.Connection:
    timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else CATALOG_READ_TIMEOUT_SECONDS if read_only else CATALOG_WRITE_TIMEOUT_SECONDS
    )
    busy_timeout = int(max(timeout, 0.0) * 1000)
    connection = sqlite3.connect(Path(path), timeout=timeout, isolation_level=None if read_only else "")
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout}")
    if not read_only:
        _configure_catalog_writer(connection)
    if read_only:
        connection.execute("PRAGMA query_only = ON")
    return connection


def _configure_catalog_writer(connection: sqlite3.Connection) -> None:
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA temp_store=MEMORY",
        "PRAGMA mmap_size=1073741824",
        "PRAGMA wal_autocheckpoint=1000",
    ):
        try:
            connection.execute(pragma)
        except sqlite3.DatabaseError as exc:
            _LOGGER.warning("failed to apply SQLite pragma %s: %s", pragma, exc)


def _catalog_storage_stats(path: Path) -> dict[str, object]:
    stats: dict[str, object] = {
        "file_size_bytes": int(path.stat().st_size) if path.exists() else 0,
        "wal_size_bytes": int(Path(f"{path}-wal").stat().st_size) if Path(f"{path}-wal").exists() else 0,
        "shm_size_bytes": int(Path(f"{path}-shm").stat().st_size) if Path(f"{path}-shm").exists() else 0,
        "page_count": 0,
        "page_size": 0,
        "freelist_count": 0,
    }
    if not path.exists():
        return stats
    try:
        with closing(connect_catalog(path, read_only=True, timeout_seconds=CATALOG_READ_TIMEOUT_SECONDS)) as connection:
            stats["page_count"] = int(connection.execute("PRAGMA page_count").fetchone()[0])
            stats["page_size"] = int(connection.execute("PRAGMA page_size").fetchone()[0])
            stats["freelist_count"] = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        stats["error"] = str(exc)
    return stats


def _init_catalog(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_files (
            cache_key TEXT PRIMARY KEY,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            data_kind TEXT NOT NULL,
            indicator TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            storage_format TEXT NOT NULL,
            status TEXT NOT NULL,
            rows INTEGER NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            modified_at TEXT NOT NULL,
            path TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_lookup "
        "ON market_data_files(asset_type, data_kind, indicator, timeframe, adjust, stock_code, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_window "
        "ON market_data_files(stock_code, timeframe, start_at, end_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_status "
        "ON market_data_files(status, asset_type, timeframe)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_filter_order "
        "ON market_data_files(asset_type, timeframe, data_kind, indicator, status, stock_code)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_symbol_adjust "
        "ON market_data_files(stock_code, adjust, timeframe, status)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_coverage_runs (
            stock_code TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            path TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (stock_code, timeframe, adjust, start_at, end_at)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_coverage_lookup "
        "ON market_data_coverage_runs(stock_code, timeframe, adjust, start_at, end_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_coverage_file_state "
        "ON market_data_coverage_runs(stock_code, timeframe, adjust, path, file_size_bytes, mtime_ns)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_parts (
            part_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            trade_month TEXT NOT NULL,
            path TEXT NOT NULL,
            rows INTEGER NOT NULL,
            min_at TEXT NOT NULL,
            max_at TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            commit_version INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_parts_lookup "
        "ON market_data_parts(timeframe, adjust, trade_month, min_at, max_at, state)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_part_symbols (
            part_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            min_at TEXT NOT NULL,
            max_at TEXT NOT NULL,
            rows INTEGER NOT NULL,
            PRIMARY KEY (part_id, stock_code)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_part_symbols_lookup "
        "ON market_data_part_symbols(stock_code, min_at, max_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_unresolved_gaps (
            stock_code TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            missing_rows INTEGER NOT NULL,
            status TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            retry_count INTEGER NOT NULL,
            last_fetch_rows INTEGER NOT NULL,
            message TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (stock_code, timeframe, adjust, start_at, end_at)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_unresolved_lookup "
        "ON market_data_unresolved_gaps(stock_code, timeframe, adjust, start_at, end_at, status)"
    )


def _catalog_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _prepare_unresolved_gap_records(records: pd.DataFrame) -> pd.DataFrame:
    frame = records.copy()
    if frame.empty:
        return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
    now_text = datetime.now(timezone.utc).isoformat()
    for column in UNRESOLVED_GAP_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["timeframe"] = frame["timeframe"].map(lambda value: ensure_supported_timeframe(value) if str(value) else "")
    frame["adjust"] = frame["adjust"].fillna("").astype(str)
    frame["start_at"] = pd.to_datetime(frame["start_at"], errors="coerce").map(_timestamp_text)
    frame["end_at"] = pd.to_datetime(frame["end_at"], errors="coerce").map(_timestamp_text)
    frame["missing_rows"] = pd.to_numeric(frame["missing_rows"], errors="coerce").fillna(0).astype(int)
    frame["last_fetch_rows"] = pd.to_numeric(frame["last_fetch_rows"], errors="coerce").fillna(0).astype(int)
    frame["status"] = frame["status"].fillna("provider_unresolved").astype(str).replace("", "provider_unresolved")
    frame["message"] = frame["message"].fillna("").astype(str)
    for column in ("first_seen_at", "last_seen_at", "updated_at"):
        frame[column] = frame[column].fillna("").astype(str).replace("", now_text)
    frame["retry_count"] = pd.to_numeric(frame["retry_count"], errors="coerce").fillna(0).astype(int)
    frame = frame.loc[
        frame["stock_code"].astype(bool)
        & frame["timeframe"].astype(bool)
        & frame["adjust"].astype(bool)
        & frame["start_at"].astype(bool)
        & frame["end_at"].astype(bool)
        & frame["missing_rows"].gt(0)
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=pd.Index(UNRESOLVED_GAP_COLUMNS))
    return frame.loc[:, UNRESOLVED_GAP_COLUMNS].reset_index(drop=True)


def _query_unresolved_gap_records_for_keys(
    connection: sqlite3.Connection,
    records: pd.DataFrame,
) -> dict[tuple[str, str, str, str, str], dict[str, object]]:
    if records.empty:
        return {}
    result: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    keys = [
        (
            str(row.stock_code),
            str(row.timeframe),
            str(row.adjust),
            str(row.start_at),
            str(row.end_at),
        )
        for row in records.itertuples(index=False)
    ]
    for chunk in _chunks(keys, 100):
        where_parts: list[str] = []
        params: list[object] = []
        for stock_code, timeframe, adjust, start_at, end_at in chunk:
            where_parts.append("(stock_code = ? AND timeframe = ? AND adjust = ? AND start_at = ? AND end_at = ?)")
            params.extend([stock_code, timeframe, adjust, start_at, end_at])
        rows = connection.execute(
            f"""
            SELECT {",".join(UNRESOLVED_GAP_COLUMNS)}
            FROM market_data_unresolved_gaps
            WHERE {" OR ".join(where_parts)}
            """,
            params,
        ).fetchall()
        for row in rows:
            record = dict(zip(UNRESOLVED_GAP_COLUMNS, row, strict=False))
            key = (
                str(record["stock_code"]),
                str(record["timeframe"]),
                str(record["adjust"]),
                str(record["start_at"]),
                str(record["end_at"]),
            )
            result[key] = record
    return result


def _is_catalog_locked_error(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower()


def _is_missing_table_error(exc: BaseException) -> bool:
    return "no such table" in str(exc).lower()


def _is_catalog_corrupt_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "database disk image is malformed" in message
        or "file is not a database" in message
        or "not a database" in message
    )


def _recover_corrupt_catalog(path: Path, exc: BaseException) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.{CATALOG_CORRUPT_MARKER}.{stamp}")
    try:
        path.rename(backup)
    except OSError as rename_exc:
        raise CatalogDatabaseCorrupt(f"catalog database is malformed and could not be backed up: {path}") from rename_exc
    for companion in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not companion.exists():
            continue
        try:
            companion.rename(companion.with_name(f"{companion.name}.{CATALOG_CORRUPT_MARKER}.{stamp}"))
        except OSError:
            _LOGGER.warning("failed to back up SQLite companion for malformed catalog: %s", companion)
    _LOGGER.warning("catalog database was malformed and has been backed up to %s: %s", backup, exc)
    return backup


def _coverage_refresh_targets(
    *,
    data_root: str | Path,
    adjust: str | None,
    timeframes: Sequence[str] | None,
    symbols: Sequence[str] | None,
    inventory: pd.DataFrame | None,
) -> list[tuple[str, str, str, Path]]:
    symbol_filter = {normalize_symbol(value) for value in symbols or () if normalize_symbol(value)}
    timeframe_filter = {ensure_supported_timeframe(value) for value in timeframes or () if str(value)}
    adjust_filter = str(adjust) if adjust is not None else ""
    targets: dict[tuple[str, str, str], Path] = {}
    if inventory is not None and not inventory.empty:
        for row in inventory.itertuples(index=False):
            symbol = normalize_symbol(getattr(row, "stock_code", ""))
            if not symbol or (symbol_filter and symbol not in symbol_filter):
                continue
            try:
                timeframe = ensure_supported_timeframe(getattr(row, "timeframe", ""))
            except ValueError:
                continue
            if timeframe_filter and timeframe not in timeframe_filter:
                continue
            item_adjust = str(getattr(row, "adjust", "") or "")
            if adjust_filter and item_adjust != adjust_filter:
                continue
            if str(getattr(row, "data_kind", "price") or "price") != "price":
                continue
            if str(getattr(row, "indicator", "ohlcv") or "ohlcv") != "ohlcv":
                continue
            raw_path = str(getattr(row, "path", "") or "")
            if not raw_path:
                continue
            targets[(symbol, timeframe, item_adjust)] = Path(raw_path)
    if not targets and symbol_filter and timeframe_filter and adjust is not None:
        for timeframe in sorted(timeframe_filter):
            root = resolve_timeframe_root(data_root, timeframe) / str(adjust)
            for symbol in sorted(symbol_filter):
                targets[(symbol, timeframe, str(adjust))] = root / f"{symbol}.parquet"
    return [(symbol, timeframe, item_adjust, path) for (symbol, timeframe, item_adjust), path in sorted(targets.items())]


def _existing_coverage_file_state(
    connection: sqlite3.Connection,
    *,
    targets: list[tuple[str, str, str, Path]] | None = None,
) -> dict[tuple[str, str, str], tuple[str, int, int]]:
    where = "file_size_bytes > 0 AND mtime_ns > 0"
    params: list[object] = []
    if targets:
        clauses = []
        for symbol, timeframe, adjust, _ in targets:
            clauses.append("(stock_code = ? AND timeframe = ? AND adjust = ?)")
            params.extend([symbol, timeframe, adjust])
        where += " AND (" + " OR ".join(clauses) + ")"
    rows = connection.execute(
        f"""
        SELECT stock_code, timeframe, adjust, path, file_size_bytes, mtime_ns
        FROM market_data_coverage_runs
        WHERE {where}
        GROUP BY stock_code, timeframe, adjust, path, file_size_bytes, mtime_ns
        """,
        params,
    ).fetchall()
    return {
        (normalize_symbol(row[0]), str(row[1]), str(row[2])): (str(row[3]), int(row[4]), int(row[5]))
        for row in rows
    }


def _delete_coverage_runs(connection: sqlite3.Connection, *, symbol: str, timeframe: str, adjust: str) -> None:
    connection.execute(
        "DELETE FROM market_data_coverage_runs WHERE stock_code = ? AND timeframe = ? AND adjust = ?",
        (symbol, timeframe, adjust),
    )


def _query_coverage_records_for_window(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    timeframe: str,
    adjust: str,
    incoming_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    bounds = _coverage_records_merge_bounds(incoming_records, timeframe=timeframe)
    if bounds is None:
        return []
    start, end = bounds
    rows = connection.execute(
        """
        SELECT stock_code, timeframe, adjust, start_at, end_at, row_count,
               file_size_bytes, mtime_ns, path, updated_at
        FROM market_data_coverage_runs
        WHERE stock_code = ? AND timeframe = ? AND adjust = ?
          AND end_at >= ? AND start_at <= ?
        ORDER BY start_at, end_at
        """,
        (symbol, timeframe, adjust, start.isoformat(), end.isoformat()),
    ).fetchall()
    return [dict(zip(COVERAGE_RUN_COLUMNS, row, strict=False)) for row in rows]


def _query_coverage_records_for_windows(
    connection: sqlite3.Connection,
    *,
    records_by_key: dict[tuple[str, str, str], list[dict[str, object]]],
) -> dict[tuple[str, str, str], list[dict[str, object]]]:
    window_rows: list[tuple[str, str, str, pd.Timestamp, pd.Timestamp]] = []
    for (symbol, timeframe, adjust), incoming_records in records_by_key.items():
        bounds = _coverage_records_merge_bounds(incoming_records, timeframe=timeframe)
        if bounds is None:
            continue
        start, end = bounds
        window_rows.append((symbol, timeframe, adjust, start, end))
    if not window_rows:
        return {}

    result: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for chunk in _chunks(window_rows, 150):
        where_parts: list[str] = []
        params: list[object] = []
        for symbol, timeframe, adjust, start, end in chunk:
            where_parts.append(
                "(stock_code = ? AND timeframe = ? AND adjust = ? AND end_at >= ? AND start_at <= ?)"
            )
            params.extend([symbol, timeframe, adjust, start.isoformat(), end.isoformat()])
        rows = connection.execute(
            f"""
            SELECT stock_code, timeframe, adjust, start_at, end_at, row_count,
                   file_size_bytes, mtime_ns, path, updated_at
            FROM market_data_coverage_runs
            WHERE {" OR ".join(where_parts)}
            ORDER BY stock_code, timeframe, adjust, start_at, end_at
            """,
            params,
        ).fetchall()
        for row in rows:
            record = dict(zip(COVERAGE_RUN_COLUMNS, row, strict=False))
            key = (normalize_symbol(row[0]), str(row[1]), str(row[2]))
            result.setdefault(key, []).append(record)
    return result


def _chunks(values: Sequence[object], size: int) -> list[Sequence[object]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _coverage_records_merge_bounds(
    records: list[dict[str, object]],
    *,
    timeframe: str,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for record in records:
        start = _safe_timestamp(record.get("start_at"))
        end = _safe_timestamp(record.get("end_at"))
        if pd.isna(start) or pd.isna(end):
            continue
        starts.append(start)
        ends.append(end)
    if not starts or not ends:
        return None
    return _expand_coverage_merge_window(min(starts), max(ends), timeframe=timeframe)


def _expand_coverage_merge_window(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    timeframe: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    if normalized_timeframe == "1d":
        return pd.Timestamp(start).normalize() - pd.Timedelta(days=7), pd.Timestamp(end).normalize() + pd.Timedelta(days=7)
    minutes = int(normalized_timeframe.removesuffix("m"))
    margin = pd.Timedelta(days=7) + pd.Timedelta(minutes=minutes)
    return pd.Timestamp(start) - margin, pd.Timestamp(end) + margin


def _missing_incoming_coverage_records(
    *,
    current_records: list[dict[str, object]],
    incoming_records: list[dict[str, object]],
    symbol: str,
    timeframe: str,
    adjust: str,
    path: Path,
    updated_at: str,
) -> list[dict[str, object]]:
    incoming_dates = _coverage_record_dates(incoming_records, timeframe=timeframe)
    if not incoming_dates:
        return []
    if current_records:
        current_intervals = _coverage_record_intervals(current_records, timeframe=timeframe)
        incoming_dates = [date for date in incoming_dates if not _timestamp_in_coverage_intervals(date, current_intervals)]
    if not incoming_dates:
        return []
    return _coverage_run_records_from_dates(
        dates=pd.Series(incoming_dates),
        symbol=symbol,
        timeframe=timeframe,
        adjust=adjust,
        file_size=0,
        mtime_ns=0,
        path=path,
        updated_at=updated_at,
    )


def _coverage_record_intervals(
    records: list[dict[str, object]],
    *,
    timeframe: str,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for record in records:
        start = _safe_timestamp(record.get("start_at"))
        end = _safe_timestamp(record.get("end_at"))
        if pd.isna(start) or pd.isna(end):
            continue
        if normalized_timeframe == "1d":
            start = start.normalize()
            end = end.normalize()
        else:
            start = start.floor("min")
            end = end.floor("min")
        intervals.append((start, end))
    return sorted(intervals, key=lambda item: (item[0], item[1]))


def _timestamp_in_coverage_intervals(
    value: pd.Timestamp,
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> bool:
    current = pd.Timestamp(value)
    for start, end in intervals:
        if current < start:
            return False
        if start <= current <= end:
            return True
    return False


def _coverage_record_dates(records: list[dict[str, object]], *, timeframe: str) -> list[pd.Timestamp]:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    dates: set[pd.Timestamp] = set()
    for record in records:
        start = _safe_timestamp(record.get("start_at"))
        end = _safe_timestamp(record.get("end_at"))
        if pd.isna(start) or pd.isna(end):
            continue
        dates.update(_coverage_record_timestamps_between(start, end, timeframe=normalized_timeframe))
    return sorted(dates)


def _coverage_record_timestamps_between(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    timeframe: str,
) -> list[pd.Timestamp]:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts > end_ts:
        return []
    if normalized_timeframe == "1d":
        return [pd.Timestamp(day).normalize() for day in pd.bdate_range(start_ts.normalize(), end_ts.normalize())]
    minutes = int(normalized_timeframe.removesuffix("m"))
    result: list[pd.Timestamp] = []
    for day in pd.bdate_range(start_ts.normalize(), end_ts.normalize()):
        session = pd.Timestamp(day).normalize()
        ranges = (
            (
                session + pd.Timedelta(hours=9, minutes=30 + minutes),
                session + pd.Timedelta(hours=11, minutes=30),
            ),
            (
                session + pd.Timedelta(hours=13, minutes=minutes),
                session + pd.Timedelta(hours=15),
            ),
        )
        for segment_start, segment_end in ranges:
            cursor = segment_start
            while cursor <= segment_end:
                if start_ts <= cursor <= end_ts:
                    result.append(pd.Timestamp(cursor))
                cursor += pd.Timedelta(minutes=minutes)
    return result


def _safe_timestamp(value: object) -> pd.Timestamp:
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def _replace_coverage_runs(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    timeframe: str,
    adjust: str,
    records: list[dict[str, object]],
) -> None:
    _delete_coverage_runs(connection, symbol=symbol, timeframe=timeframe, adjust=adjust)
    if not records:
        return
    _insert_coverage_runs(connection, records=records, replace=True)


def _insert_coverage_runs(
    connection: sqlite3.Connection,
    *,
    records: list[dict[str, object]],
    replace: bool,
) -> None:
    if not records:
        return
    columns = list(COVERAGE_RUN_COLUMNS)
    placeholders = ",".join("?" for _ in columns)
    column_sql = ",".join(columns)
    conflict = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    sql = f"{conflict} INTO market_data_coverage_runs ({column_sql}) VALUES ({placeholders})"
    connection.executemany(sql, [tuple(record[column] for column in columns) for record in records])


def _coverage_run_records_for_file(
    *,
    path: Path,
    symbol: str,
    timeframe: str,
    adjust: str,
    file_size: int,
    mtime_ns: int,
    extra_paths: Sequence[Path] = (),
) -> list[dict[str, object]]:
    frames: list[pd.DataFrame] = []
    for item_path in [path, *_delta_part_paths(path), *extra_paths]:
        if not item_path.exists():
            continue
        try:
            identity_part = pd.read_parquet(item_path, columns=["date", "stock_code"])
        except Exception:  # noqa: BLE001
            return []
        if not identity_part.empty:
            frames.append(identity_part)
    if not frames:
        return []
    identity = pd.concat(frames, ignore_index=True)
    if identity.empty or "date" not in identity.columns:
        return []
    frame = identity.loc[:, ["date", "stock_code"]].copy()
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.loc[frame["stock_code"].eq(symbol) & frame["date"].notna()].copy()
    if frame.empty:
        return []
    if ensure_supported_timeframe(timeframe) == "1d":
        frame["date"] = frame["date"].dt.normalize()
    else:
        frame["date"] = frame["date"].dt.floor("min")
    return _coverage_run_records_from_dates(
        dates=frame["date"],
        symbol=symbol,
        timeframe=timeframe,
        adjust=adjust,
        file_size=file_size,
        mtime_ns=mtime_ns,
        path=path,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _coverage_file_state(path: Path, *, extra_paths: Sequence[Path] = ()) -> tuple[int, int]:
    paths = [path] if path.exists() else []
    paths.extend(_delta_part_paths(path))
    paths.extend(extra_paths)
    if not paths:
        raise OSError(f"coverage path does not exist: {path}")
    size = sum(int(item.stat().st_size) for item in paths if item.exists())
    mtime_ns = max(int(item.stat().st_mtime_ns) for item in paths if item.exists())
    return int(size), int(mtime_ns)


def _shared_part_paths_for_key(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    timeframe: str,
    adjust: str,
) -> list[Path]:
    if not _catalog_table_exists(connection, "market_data_parts") or not _catalog_table_exists(connection, "market_data_part_symbols"):
        return []
    rows = connection.execute(
        """
        SELECT DISTINCT p.path
        FROM market_data_part_symbols ps
        JOIN market_data_parts p ON p.part_id = ps.part_id
        WHERE ps.stock_code = ?
          AND p.timeframe = ?
          AND p.adjust = ?
          AND p.state = 'active'
        ORDER BY p.commit_version, p.path
        """,
        (symbol, timeframe, adjust),
    ).fetchall()
    return [Path(str(row[0])) for row in rows if str(row[0])]


def _delta_part_paths(path: Path) -> list[Path]:
    root = path.with_name(f"{path.stem}.delta")
    if not root.exists():
        return []
    return sorted(part for part in root.glob("*.parquet") if part.is_file())


def _coverage_run_records_from_dates(
    *,
    dates: pd.Series,
    symbol: str,
    timeframe: str,
    adjust: str,
    file_size: int,
    mtime_ns: int,
    path: Path,
    updated_at: str,
) -> list[dict[str, object]]:
    if ensure_supported_timeframe(timeframe) == "1d":
        normalized_dates = pd.to_datetime(dates, errors="coerce").dt.normalize()
    else:
        normalized_dates = pd.to_datetime(dates, errors="coerce").dt.floor("min")
    dates = normalized_dates.dropna().drop_duplicates().sort_values(kind="mergesort").reset_index(drop=True)
    if dates.empty:
        return []
    records: list[dict[str, object]] = []
    start = pd.Timestamp(dates.iloc[0])
    previous = start
    row_count = 1
    minutes = 1440 if ensure_supported_timeframe(timeframe) == "1d" else int(str(timeframe).removesuffix("m"))
    for value in dates.iloc[1:]:
        current = pd.Timestamp(value)
        if _coverage_timestamps_are_contiguous(previous, current, timeframe=timeframe, minutes=minutes):
            previous = current
            row_count += 1
            continue
        records.append(
            _coverage_run_record(
                symbol=symbol,
                timeframe=timeframe,
                adjust=adjust,
                start=start,
                end=previous,
                row_count=row_count,
                file_size=file_size,
                mtime_ns=mtime_ns,
                path=path,
                updated_at=updated_at,
            )
        )
        start = current
        previous = current
        row_count = 1
    records.append(
        _coverage_run_record(
            symbol=symbol,
            timeframe=timeframe,
            adjust=adjust,
            start=start,
            end=previous,
            row_count=row_count,
            file_size=file_size,
            mtime_ns=mtime_ns,
            path=path,
            updated_at=updated_at,
        )
    )
    return records


def _coverage_timestamps_are_contiguous(
    previous: pd.Timestamp,
    current: pd.Timestamp,
    *,
    timeframe: str,
    minutes: int,
) -> bool:
    if ensure_supported_timeframe(timeframe) == "1d":
        return bool(pd.Timestamp(current).normalize() in pd.bdate_range(previous.normalize(), periods=2)[1:])
    expected_delta = pd.Timedelta(minutes=minutes)
    if current - previous == expected_delta:
        return True
    lunch_shifted_previous = pd.Timestamp(current).normalize() + pd.Timedelta(hours=11, minutes=30 - minutes)
    lunch_shifted_current = pd.Timestamp(current).normalize() + pd.Timedelta(hours=13)
    if previous == lunch_shifted_previous and current == lunch_shifted_current:
        return True
    afternoon_first = (pd.Timestamp(current).normalize() + pd.Timedelta(hours=13, minutes=minutes)).strftime("%H:%M")
    if previous.strftime("%H:%M") == "11:30" and current.strftime("%H:%M") == afternoon_first:
        return True
    if _intraday_timestamps_are_next_trading_session(previous, current, minutes=minutes):
        return True
    return False


def _intraday_timestamps_are_next_trading_session(previous: pd.Timestamp, current: pd.Timestamp, *, minutes: int) -> bool:
    previous_ts = pd.Timestamp(previous)
    current_ts = pd.Timestamp(current)
    if previous_ts.strftime("%H:%M") != "15:00":
        return False
    current_first = current_ts.normalize() + pd.Timedelta(hours=9, minutes=30 + minutes)
    if current_ts != current_first:
        return False
    next_business_day = pd.bdate_range(previous_ts.normalize(), periods=2)[1]
    return bool(current_ts.normalize() == pd.Timestamp(next_business_day).normalize())


def _coverage_run_record(
    *,
    symbol: str,
    timeframe: str,
    adjust: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    row_count: int,
    file_size: int,
    mtime_ns: int,
    path: Path,
    updated_at: str,
) -> dict[str, object]:
    return {
        "stock_code": symbol,
        "timeframe": timeframe,
        "adjust": adjust,
        "start_at": pd.Timestamp(start).isoformat(),
        "end_at": pd.Timestamp(end).isoformat(),
        "row_count": int(row_count),
        "file_size_bytes": int(file_size),
        "mtime_ns": int(mtime_ns),
        "path": str(path),
        "updated_at": updated_at,
    }


def _fill_existing_catalog_names(connection: sqlite3.Connection, records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return records
    symbols = tuple(
        normalize_symbol(value)
        for value in records["stock_code"].dropna().astype(str).tolist()
        if normalize_symbol(value)
    )
    if not symbols:
        return records
    existing_frames: list[pd.DataFrame] = []
    for chunk in _chunks(symbols, 500):
        placeholders = ",".join("?" for _ in chunk)
        existing_frames.append(
            pd.read_sql_query(
                f"""
                SELECT stock_code, stock_name
                FROM market_data_files
                WHERE stock_name <> ''
                  AND stock_code IN ({placeholders})
                """,
                connection,
                params=list(chunk),
            )
        )
    existing = pd.concat(existing_frames, ignore_index=True) if existing_frames else pd.DataFrame()
    if existing.empty:
        return records
    names = {
        normalize_symbol(row.stock_code): str(row.stock_name)
        for row in existing.drop_duplicates(subset=["stock_code"], keep="last").itertuples(index=False)
    }
    result = records.copy()
    empty_name = result["stock_name"].fillna("").astype(str).eq("")
    result.loc[empty_name, "stock_name"] = result.loc[empty_name, "stock_code"].map(lambda symbol: names.get(symbol, ""))
    return result


def _catalog_root(data_root: str | Path) -> Path:
    return canonical_data_root(data_root)


def _sequence_values(values: Sequence[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(value) for value in values)


def _symbol_name_map(symbol_metadata: pd.DataFrame | None) -> dict[str, str]:
    if symbol_metadata is None or symbol_metadata.empty:
        return {}
    return {
        normalize_symbol(row.stock_code): str(row.stock_name)
        for row in symbol_metadata.itertuples(index=False)
        if normalize_symbol(row.stock_code)
    }


def _timestamp_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).isoformat()


def _looks_like_etf_code(code: str) -> bool:
    return code.startswith(("159", "510", "511", "512", "513", "515", "516", "517", "518", "520", "560", "561", "562", "563", "588"))
