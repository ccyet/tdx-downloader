from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
import pandas as pd

from tdx_downloader.data.catalog import query_catalog
from tdx_downloader.data.manager import normalize_symbol_tuple, normalize_timeframes
from tdx_downloader.data.schema import parse_time_window
from tdx_downloader.data.storage import load_local_bars

from .. import schemas
from ..constants import (
    DEFAULT_ADJUST,
    DEFAULT_DATA_ROOT,
    PRICE_BARS_DEFAULT_LIMIT,
    PRICE_BARS_MAX_LIMIT,
    PRICE_SYMBOLS_DEFAULT_LIMIT,
    PRICE_SYMBOLS_MAX_LIMIT,
)
from ..serialization import _records

DEFAULT_PRICE_ASSET_TYPES = ("stock",)
PRICE_BAR_COLUMNS = [
    "date",
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
PRICE_SYMBOL_COLUMNS = [
    "stock_code",
    "stock_name",
    "asset_type",
    "timeframe",
    "adjust",
    "rows",
    "start_at",
    "end_at",
    "file_size_bytes",
    "modified_at",
]


def register_prices_routes(app: FastAPI) -> None:
    @app.get("/api/prices/symbols")
    def price_symbols_get(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        timeframe: str = "1d",
        asset_types: str = "stock",
        keyword: str = "",
        limit: int = Query(default=PRICE_SYMBOLS_DEFAULT_LIMIT, ge=1, le=PRICE_SYMBOLS_MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        payload = schemas.PriceSymbolsPayload(
            data_root=data_root,
            adjust=adjust,
            timeframe=timeframe,
            asset_types=_split_query_values(asset_types),
            keyword=keyword,
            limit=limit,
            offset=offset,
        )
        return _price_symbols_response(payload)

    @app.get("/api/prices/bars")
    def price_bars_get(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        timeframe: str = "1d",
        symbols: str = "",
        asset_types: str = "stock",
        start: str = "",
        end: str = "",
        limit: int = Query(default=PRICE_BARS_DEFAULT_LIMIT, ge=1, le=PRICE_BARS_MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        order: str = "asc",
    ) -> dict[str, Any]:
        payload = schemas.PriceBarsPayload(
            data_root=data_root,
            adjust=adjust,
            timeframe=timeframe,
            symbols=_split_query_values(symbols),
            asset_types=_split_query_values(asset_types),
            start=start or schemas.PriceBarsPayload().start,
            end=end or schemas.PriceBarsPayload().end,
            limit=limit,
            offset=offset,
            order=order,
        )
        return _price_bars_response(payload)

    @app.post("/api/prices/bars")
    def price_bars_post(payload: schemas.PriceBarsPayload) -> dict[str, Any]:
        return _price_bars_response(payload)


def _price_bars_response(payload: schemas.PriceBarsPayload) -> dict[str, Any]:
    try:
        timeframe = normalize_timeframes([payload.timeframe])[0]
        order = _normalize_price_order(payload.order)
        symbols, names, asset_types, symbol_stats = _resolve_price_symbols(payload, timeframe=timeframe)
        page, scanned_symbol_count, has_more = _load_price_bars_page(
            payload,
            timeframe=timeframe,
            symbols=symbols,
            names=names,
            asset_types=asset_types,
            symbol_stats=symbol_stats,
            order=order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    records = _records(page, limit=None)
    next_offset = payload.offset + len(records) if has_more else None
    return {
        "data_root": payload.data_root,
        "adjust": payload.adjust,
        "timeframe": timeframe,
        "start": payload.start,
        "end": payload.end,
        "order": order,
        "limit": payload.limit,
        "offset": payload.offset,
        "next_offset": next_offset,
        "has_more": has_more,
        "symbol_count": len(symbols),
        "scanned_symbol_count": scanned_symbol_count,
        "record_count": len(records),
        "columns": list(PRICE_BAR_COLUMNS),
        "records": records,
    }


def _price_symbols_response(payload: schemas.PriceSymbolsPayload) -> dict[str, Any]:
    try:
        timeframe = normalize_timeframes([payload.timeframe])[0]
        asset_types = tuple(str(item).strip() for item in payload.asset_types if str(item).strip())
        if not asset_types:
            asset_types = DEFAULT_PRICE_ASSET_TYPES
        catalog = query_catalog(
            data_root=payload.data_root,
            asset_types=asset_types,
            timeframes=(timeframe,),
            data_kinds=("price",),
            indicators=("ohlcv",),
            statuses=("cached",),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.adjust.strip():
        catalog = catalog.loc[catalog["adjust"].astype(str).eq(payload.adjust.strip())].copy()
    catalog = _filter_price_symbol_catalog(catalog, payload.keyword)
    total_count = int(len(catalog))
    page = catalog.iloc[payload.offset : payload.offset + payload.limit].copy()
    if page.empty:
        page = pd.DataFrame(columns=pd.Index(PRICE_SYMBOL_COLUMNS))
    else:
        page = page.loc[:, [column for column in PRICE_SYMBOL_COLUMNS if column in page.columns]]
    records = _records(page, limit=None)
    next_offset = payload.offset + len(records) if payload.offset + len(records) < total_count else None
    return {
        "data_root": payload.data_root,
        "adjust": payload.adjust,
        "timeframe": timeframe,
        "asset_types": list(asset_types),
        "keyword": payload.keyword,
        "limit": payload.limit,
        "offset": payload.offset,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "total_count": total_count,
        "record_count": len(records),
        "columns": list(PRICE_SYMBOL_COLUMNS),
        "records": records,
    }


def _resolve_price_symbols(
    payload: schemas.PriceBarsPayload,
    *,
    timeframe: str,
) -> tuple[list[str], dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    catalog = query_catalog(
        data_root=payload.data_root,
        timeframes=(timeframe,),
        data_kinds=("price",),
        indicators=("ohlcv",),
        statuses=("cached",),
    )
    if payload.adjust.strip() and not catalog.empty:
        catalog = catalog.loc[catalog["adjust"].astype(str).eq(payload.adjust.strip())].copy()
    names = _catalog_value_map(catalog, "stock_name")
    asset_types = _catalog_value_map(catalog, "asset_type")
    symbol_stats = _catalog_symbol_stats(catalog)
    explicit_symbols = normalize_symbol_tuple(payload.symbols)
    if explicit_symbols:
        return list(explicit_symbols), names, asset_types, symbol_stats

    requested_asset_types = tuple(str(item).strip() for item in payload.asset_types if str(item).strip())
    if not requested_asset_types:
        requested_asset_types = DEFAULT_PRICE_ASSET_TYPES
    catalog = catalog.loc[catalog["asset_type"].astype(str).isin(requested_asset_types)].copy()
    if catalog.empty:
        raise ValueError("当前筛选条件没有可用价格数据，请先扫描缓存或指定 symbols。")
    symbols = [str(symbol) for symbol in catalog["stock_code"].dropna().astype(str).drop_duplicates().tolist()]
    return symbols, names, asset_types, symbol_stats


def _load_price_bars_page(
    payload: schemas.PriceBarsPayload,
    *,
    timeframe: str,
    symbols: list[str],
    names: dict[str, str],
    asset_types: dict[str, str],
    symbol_stats: dict[str, dict[str, Any]],
    order: str,
) -> tuple[pd.DataFrame, int, bool]:
    needed = payload.limit + 1
    skipped_rows = 0
    scanned_symbol_count = 0
    frames: list[pd.DataFrame] = []
    start_ts, end_ts = parse_time_window(payload.start, payload.end)
    for symbol in symbols:
        remaining = needed - sum(len(frame) for frame in frames)
        if remaining <= 0:
            break
        full_window_rows = _full_window_row_count(symbol_stats.get(symbol), start_ts=start_ts, end_ts=end_ts)
        if full_window_rows is not None and skipped_rows + full_window_rows <= payload.offset:
            skipped_rows += full_window_rows
            continue
        bars = load_local_bars(
            data_root=payload.data_root,
            timeframe=timeframe,
            adjust=payload.adjust,
            symbols=[symbol],
            start=payload.start,
            end=payload.end,
        )
        scanned_symbol_count += 1
        if bars.empty:
            continue
        bars = _sort_price_bars(bars, order=order)
        row_count = len(bars)
        if skipped_rows + row_count <= payload.offset:
            skipped_rows += row_count
            continue
        start_index = max(payload.offset - skipped_rows, 0)
        page_part = bars.iloc[start_index : start_index + remaining].copy()
        page_part["stock_name"] = page_part["stock_code"].map(lambda value: names.get(str(value), ""))
        page_part["asset_type"] = page_part["stock_code"].map(lambda value: asset_types.get(str(value), ""))
        frames.append(page_part)
        skipped_rows += row_count
    if not frames:
        return pd.DataFrame(columns=pd.Index(PRICE_BAR_COLUMNS)), scanned_symbol_count, False
    page = pd.concat(frames, ignore_index=True)
    has_more = len(page) > payload.limit
    page = page.head(payload.limit).loc[:, PRICE_BAR_COLUMNS]
    return page.reset_index(drop=True), scanned_symbol_count, has_more


def _sort_price_bars(frame: pd.DataFrame, *, order: str) -> pd.DataFrame:
    ascending = order == "asc"
    return frame.sort_values(["stock_code", "date"], ascending=[True, ascending]).reset_index(drop=True)


def _normalize_price_order(order: str) -> str:
    normalized = str(order or "asc").strip().lower()
    if normalized not in {"asc", "desc"}:
        raise ValueError("order 仅支持 asc 或 desc。")
    return normalized


def _catalog_value_map(catalog: pd.DataFrame, column: str) -> dict[str, str]:
    if catalog.empty or column not in catalog.columns:
        return {}
    return {
        str(row.stock_code): str(getattr(row, column) or "")
        for row in catalog.drop_duplicates(subset=["stock_code"], keep="first").itertuples(index=False)
    }


def _catalog_symbol_stats(catalog: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if catalog.empty:
        return {}
    stats: dict[str, dict[str, Any]] = {}
    for row in catalog.drop_duplicates(subset=["stock_code"], keep="first").itertuples(index=False):
        symbol = str(row.stock_code)
        stats[symbol] = {
            "rows": getattr(row, "rows", None),
            "start_at": getattr(row, "start_at", ""),
            "end_at": getattr(row, "end_at", ""),
        }
    return stats


def _full_window_row_count(
    stats: dict[str, Any] | None,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> int | None:
    if not stats:
        return None
    rows = int(float(stats.get("rows") or 0))
    if rows <= 0:
        return None
    try:
        local_start = pd.Timestamp(stats.get("start_at"))
        local_end = pd.Timestamp(stats.get("end_at"))
    except (TypeError, ValueError):
        return None
    if pd.isna(local_start) or pd.isna(local_end):
        return None
    return rows if start_ts <= local_start and end_ts >= local_end else None


def _split_query_values(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace("，", ",").replace("、", ",").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def _filter_price_symbol_catalog(catalog: pd.DataFrame, keyword: str) -> pd.DataFrame:
    if catalog.empty:
        return catalog
    text = str(keyword or "").strip()
    if not text:
        return catalog.sort_values(["asset_type", "stock_code", "adjust"]).reset_index(drop=True)
    keyword_lower = text.lower()
    mask = (
        catalog["stock_code"].astype(str).str.lower().str.contains(keyword_lower, regex=False)
        | catalog["stock_name"].astype(str).str.lower().str.contains(keyword_lower, regex=False)
    )
    return catalog.loc[mask].sort_values(["asset_type", "stock_code", "adjust"]).reset_index(drop=True)
