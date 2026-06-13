from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from tdx_downloader.data.catalog import infer_asset_type
from tdx_downloader.data.schema import canonical_data_root, ensure_supported_timeframe, resolve_timeframe_root, unique_symbols
from tdx_downloader.data.storage import load_daily_bars, load_local_bars
from tdx_downloader.data.symbols import load_symbol_metadata

AI_INDEX_FILE_NAME = "ai_market_index.sqlite"
AI_PRICE_TABLE = "ai_price_bars"
AI_SOURCE_TABLE = "ai_index_sources"
AI_PRICE_COLUMNS = [
    "timeframe",
    "adjust",
    "ts",
    "trade_date",
    "stock_code",
    "stock_name",
    "asset_type",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
]


def ai_index_path_for(data_root: str | Path) -> Path:
    return canonical_data_root(data_root) / "metadata" / AI_INDEX_FILE_NAME


def ensure_ai_price_index(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: list[str] | tuple[str, ...],
    start: str,
    end: str,
    tdx_path: str | Path = "",
) -> dict[str, Any]:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    normalized_symbols = tuple(unique_symbols(tuple(symbols)))
    path = ai_index_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    start_date = pd.Timestamp(start).date().isoformat()
    end_date = pd.Timestamp(end).date().isoformat()
    with sqlite3.connect(path) as connection:
        _init_ai_index(connection)
        if not normalized_symbols:
            return _index_info(path, normalized_timeframe, adjust, start_date, end_date, 0, 0)
        source_state = _source_state(
            data_root=data_root,
            adjust=adjust,
            timeframe=normalized_timeframe,
            symbols=normalized_symbols,
        )
        stale_symbols = _stale_symbols(
            connection,
            timeframe=normalized_timeframe,
            adjust=adjust,
            symbols=normalized_symbols,
            start=start_date,
            end=end_date,
            source_state=source_state,
        )
        if not stale_symbols:
            return _index_info(path, normalized_timeframe, adjust, start_date, end_date, len(normalized_symbols), 0)
        _delete_price_index_window(
            connection,
            timeframe=normalized_timeframe,
            adjust=adjust,
            symbols=stale_symbols,
            start=start_date,
            end=end_date,
        )
        bars = _load_price_bars(
            data_root=data_root,
            adjust=adjust,
            timeframe=normalized_timeframe,
            symbols=stale_symbols,
            start=start,
            end=end,
        )
        records = _price_index_records(
            bars,
            data_root=data_root,
            tdx_path=tdx_path,
            timeframe=normalized_timeframe,
            adjust=adjust,
        )
        if records:
            connection.executemany(
                f"""
                INSERT OR REPLACE INTO {AI_PRICE_TABLE} (
                    timeframe, adjust, ts, trade_date, stock_code, stock_name, asset_type,
                    open, high, low, close, volume, amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        _upsert_source_state(
            connection,
            timeframe=normalized_timeframe,
            adjust=adjust,
            start=start_date,
            end=end_date,
            source_state=source_state,
            symbols=stale_symbols,
            records=records,
        )
        connection.commit()
    return _index_info(path, normalized_timeframe, adjust, start_date, end_date, len(normalized_symbols), len(records))


def rank_symbols_by_ai_price_index(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: list[str] | tuple[str, ...],
    start: str,
    end: str,
    metric: str,
    limit: int | None,
    ascending: bool,
    tdx_path: str | Path = "",
) -> tuple[list[str], pd.DataFrame, dict[str, Any]]:
    normalized_symbols = tuple(unique_symbols(tuple(symbols)))
    index_info = ensure_ai_price_index(
        data_root=data_root,
        adjust=adjust,
        timeframe=timeframe,
        symbols=normalized_symbols,
        start=start,
        end=end,
        tdx_path=tdx_path,
    )
    frame = query_ai_price_index(
        data_root=data_root,
        adjust=adjust,
        timeframe=timeframe,
        symbols=normalized_symbols,
        start=start,
        end=end,
    )
    if frame.empty or metric not in frame.columns:
        return [], frame, index_info
    ranked = frame.copy()
    ranked[metric] = pd.to_numeric(ranked[metric], errors="coerce")
    ranked = ranked.dropna(subset=["stock_code", "ts", metric]).sort_values(["stock_code", "ts"])
    if ranked.empty:
        return [], ranked, index_info
    ranked = ranked.groupby("stock_code", sort=False).tail(1).sort_values(metric, ascending=ascending, kind="mergesort")
    if limit is not None:
        ranked = ranked.head(limit)
    return [str(symbol) for symbol in ranked["stock_code"].tolist()], ranked.reset_index(drop=True), index_info


def query_ai_price_index(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: list[str] | tuple[str, ...],
    start: str,
    end: str,
) -> pd.DataFrame:
    path = ai_index_path_for(data_root)
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(AI_PRICE_COLUMNS))
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    start_date = pd.Timestamp(start).date().isoformat()
    end_date = pd.Timestamp(end).date().isoformat()
    with sqlite3.connect(path) as connection:
        _init_ai_index(connection)
        frame = pd.read_sql_query(
            f"""
            SELECT {", ".join(AI_PRICE_COLUMNS)}
            FROM {AI_PRICE_TABLE}
            WHERE timeframe = ?
              AND adjust = ?
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY stock_code, ts
            """,
            connection,
            params=(normalized_timeframe, adjust, start_date, end_date),
        )
    normalized_symbols = set(unique_symbols(tuple(symbols)))
    if normalized_symbols and not frame.empty:
        frame = frame.loc[frame["stock_code"].isin(normalized_symbols)].copy()
    return frame.reset_index(drop=True)


def _load_price_bars(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: tuple[str, ...],
    start: str,
    end: str,
) -> pd.DataFrame:
    if timeframe == "1d":
        return load_daily_bars(data_root=data_root, adjust=adjust, symbols=symbols, start=start, end=end)
    return load_local_bars(data_root=data_root, timeframe=timeframe, adjust=adjust, symbols=symbols, start=start, end=end)


def _price_index_records(
    bars: pd.DataFrame,
    *,
    data_root: str | Path,
    tdx_path: str | Path,
    timeframe: str,
    adjust: str,
) -> list[tuple[Any, ...]]:
    if bars.empty:
        return []
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    names = {
        str(row.stock_code): str(row.stock_name)
        for row in metadata.itertuples(index=False)
        if str(getattr(row, "stock_code", "") or "")
    } if not metadata.empty else {}
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "stock_code"]).sort_values(["stock_code", "date"])
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    records: list[tuple[Any, ...]] = []
    for row in frame.itertuples(index=False):
        symbol = str(row.stock_code)
        name = names.get(symbol, "")
        ts = pd.Timestamp(row.date)
        records.append(
            (
                timeframe,
                adjust,
                ts.isoformat(),
                ts.date().isoformat(),
                symbol,
                name,
                infer_asset_type(symbol, name),
                _float_or_none(row.open),
                _float_or_none(row.high),
                _float_or_none(row.low),
                _float_or_none(row.close),
                _float_or_none(row.volume),
                _float_or_none(row.amount),
            )
        )
    return records


def _delete_price_index_window(
    connection: sqlite3.Connection,
    *,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
    start: str,
    end: str,
) -> None:
    connection.executemany(
        f"""
        DELETE FROM {AI_PRICE_TABLE}
        WHERE timeframe = ?
          AND adjust = ?
          AND stock_code = ?
          AND trade_date >= ?
          AND trade_date <= ?
        """,
        [(timeframe, adjust, symbol, start, end) for symbol in symbols],
    )


def _source_state(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    state: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        path = root / f"{symbol}.parquet"
        try:
            stat = path.stat()
        except OSError:
            state[symbol] = {"path": str(path), "source_mtime_ns": 0}
            continue
        state[symbol] = {"path": str(path), "source_mtime_ns": int(stat.st_mtime_ns)}
    return state


def _stale_symbols(
    connection: sqlite3.Connection,
    *,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
    start: str,
    end: str,
    source_state: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    if not symbols:
        return ()
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        f"""
        SELECT stock_code, source_mtime_ns, indexed_start, indexed_end
        FROM {AI_SOURCE_TABLE}
        WHERE timeframe = ?
          AND adjust = ?
          AND stock_code IN ({placeholders})
        """,
        (timeframe, adjust, *symbols),
    ).fetchall()
    by_symbol = {str(row[0]): row for row in rows}
    stale: list[str] = []
    for symbol in symbols:
        row = by_symbol.get(symbol)
        source_mtime = int(source_state.get(symbol, {}).get("source_mtime_ns") or 0)
        if row is None:
            stale.append(symbol)
            continue
        indexed_mtime = int(row[1] or 0)
        indexed_start = str(row[2] or "")
        indexed_end = str(row[3] or "")
        if indexed_mtime != source_mtime or indexed_start > start or indexed_end < end:
            stale.append(symbol)
    return tuple(stale)


def _upsert_source_state(
    connection: sqlite3.Connection,
    *,
    timeframe: str,
    adjust: str,
    start: str,
    end: str,
    source_state: dict[str, dict[str, Any]],
    symbols: tuple[str, ...],
    records: list[tuple[Any, ...]],
) -> None:
    row_count_by_symbol: dict[str, int] = {}
    for record in records:
        symbol = str(record[4])
        row_count_by_symbol[symbol] = row_count_by_symbol.get(symbol, 0) + 1
    rows = []
    for symbol in symbols:
        state = source_state.get(symbol, {})
        rows.append(
            (
                timeframe,
                adjust,
                symbol,
                str(state.get("path") or ""),
                int(state.get("source_mtime_ns") or 0),
                start,
                end,
                int(row_count_by_symbol.get(symbol, 0)),
            )
        )
    connection.executemany(
        f"""
        INSERT OR REPLACE INTO {AI_SOURCE_TABLE} (
            timeframe, adjust, stock_code, source_path, source_mtime_ns,
            indexed_start, indexed_end, row_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _init_ai_index(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AI_PRICE_TABLE} (
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            ts TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            PRIMARY KEY (timeframe, adjust, ts, stock_code)
        )
        """
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ai_price_date_metric ON {AI_PRICE_TABLE}"
        "(timeframe, adjust, trade_date, asset_type, amount, volume, close)"
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ai_price_symbol_time ON {AI_PRICE_TABLE}"
        "(stock_code, timeframe, adjust, ts)"
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AI_SOURCE_TABLE} (
            timeframe TEXT NOT NULL,
            adjust TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_mtime_ns INTEGER NOT NULL,
            indexed_start TEXT NOT NULL,
            indexed_end TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            PRIMARY KEY (timeframe, adjust, stock_code)
        )
        """
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ai_source_window ON {AI_SOURCE_TABLE}"
        "(timeframe, adjust, indexed_start, indexed_end, stock_code)"
    )


def _index_info(
    path: Path,
    timeframe: str,
    adjust: str,
    start: str,
    end: str,
    symbol_count: int,
    rows_indexed: int,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "table": AI_PRICE_TABLE,
        "timeframe": timeframe,
        "adjust": adjust,
        "start": start,
        "end": end,
        "symbol_count": symbol_count,
        "rows_indexed": rows_indexed,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None
