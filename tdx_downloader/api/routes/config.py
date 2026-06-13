from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
from time import monotonic
from time import time as wall_time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
import pandas as pd

from tdx_downloader.data.catalog import ASSET_TYPE_LABELS
from tdx_downloader.data.manager import QUICK_SYMBOL_GROUPS, normalize_symbol_tuple, shortcut_symbol_groups
from tdx_downloader.data.parallels_runtime import (
    etf_tracking_with_runtime,
    refresh_symbol_metadata_with_runtime,
    shortcut_symbol_groups_with_runtime,
    should_use_parallels_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES, normalize_symbol
from tdx_downloader.data.storage import load_daily_bars, load_local_bars
from tdx_downloader.data.symbols import DEFAULT_STOCK_NAME_BY_CODE, load_symbol_metadata, symbol_metadata_cache_info
from tdx_downloader.data.tdx import DEFAULT_ETF_TRACKING_INDEX_SYMBOLS
from tdx_downloader.data.tdx_worker_client import TdxWorkerClient, WorkerUnavailable

from .. import schemas
from ..constants import (
    DEFAULT_ADJUST,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DATA_ROOT,
    DEFAULT_TDX_PATH,
    DEFAULT_TIMEFRAMES,
    ETF_API_CACHE_MAX_ENTRIES,
    ETF_RETURNS_CACHE_TTL_SECONDS,
    ETF_TRACKING_CACHE_TTL_SECONDS,
    PICKER_LIQUIDITY_LOOKBACK_BARS,
    PICKER_LIQUIDITY_SORT_GROUPS,
)
from ..fuyao_client import has_fuyao_api_key
from ..serialization import _records

DEFAULT_ETF_TRACKING_INDEX_NAMES = {
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
}

_ETF_TRACKING_CACHE: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()
_ETF_RETURNS_CACHE: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()


def register_config_routes(app: FastAPI) -> None:
    @app.get("/api/config")
    def config() -> dict[str, Any]:
        today = date.today()
        groups = _static_shortcut_symbol_groups()
        return {
            "defaults": {
                "data_root": DEFAULT_DATA_ROOT,
                "adjust": DEFAULT_ADJUST,
                "tdx_path": DEFAULT_TDX_PATH,
                "timeframes": list(DEFAULT_TIMEFRAMES),
                "batch_size": DEFAULT_BATCH_SIZE,
                "start": (today - timedelta(days=20)).isoformat(),
                "end": today.isoformat(),
                "mode": "smart",
                "strict_after_update": True,
            },
            "timeframes": list(SUPPORTED_TIMEFRAMES),
            "asset_types": [{"value": key, "label": label} for key, label in ASSET_TYPE_LABELS.items()],
            "symbol_groups": groups,
            "symbol_names": _symbol_group_names(groups, symbol_metadata=pd.DataFrame()),
            "integrations": {
                "fuyao_calendar": {
                    "configured": has_fuyao_api_key(),
                }
            },
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
            "worker": _worker_status(),
            "symbol_metadata_cache": symbol_metadata_cache_info(data_root=DEFAULT_DATA_ROOT, tdx_path=DEFAULT_TDX_PATH),
        }

    @app.get("/api/symbol-groups")
    def symbol_groups(
        data_root: str = DEFAULT_DATA_ROOT,
        tdx_path: str = DEFAULT_TDX_PATH,
        adjust: str = DEFAULT_ADJUST,
        target: str = "",
        refresh: bool = False,
    ) -> dict[str, Any]:
        try:
            symbol_metadata = (
                symbol_metadata_with_runtime(data_root, tdx_path, force_refresh=True)
                if refresh
                else symbol_metadata_with_runtime(data_root, tdx_path)
            )
            groups = _api_shortcut_symbol_groups(symbol_metadata)
            if target and _missing_target_symbol_group(groups, target):
                groups = shortcut_symbol_groups_with_runtime(data_root, tdx_path, target=target)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sorted_groups = _sort_picker_symbol_groups_by_recent_amount(groups, data_root=data_root, adjust=adjust)
        return {
            "groups": sorted_groups,
            "symbol_names": _symbol_group_names(sorted_groups, symbol_metadata=symbol_metadata),
            "symbol_metadata_cache": symbol_metadata_cache_info(data_root=data_root, tdx_path=tdx_path),
        }

    @app.post("/api/symbol-metadata/refresh")
    def refresh_symbol_metadata(payload: schemas.SymbolMetadataRefreshPayload) -> dict[str, Any]:
        try:
            symbol_metadata = refresh_symbol_metadata_with_runtime(payload.data_root, payload.tdx_path)
            groups = _api_shortcut_symbol_groups(symbol_metadata)
            if payload.target and _missing_target_symbol_group(groups, payload.target):
                groups = shortcut_symbol_groups_with_runtime(payload.data_root, payload.tdx_path, target=payload.target)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sorted_groups = _sort_picker_symbol_groups_by_recent_amount(
            groups,
            data_root=payload.data_root,
            adjust=payload.adjust,
        )
        return {
            "groups": sorted_groups,
            "symbol_names": _symbol_group_names(sorted_groups, symbol_metadata=symbol_metadata),
            "symbol_metadata_cache": symbol_metadata_cache_info(data_root=payload.data_root, tdx_path=payload.tdx_path),
        }

    @app.post("/api/symbol-metrics")
    def symbol_metrics(payload: schemas.SymbolMetricsPayload) -> dict[str, Any]:
        symbols = normalize_symbol_tuple(payload.symbols)
        records = _local_symbol_metric_records(
            data_root=payload.data_root,
            adjust=payload.adjust,
            symbols=symbols,
            end=payload.end,
        )
        return {
            "records": records,
            "record_count": len(records),
            "requested_count": len(symbols),
        }

    @app.get("/api/etf-tracking")
    def etf_tracking(
        data_root: str = DEFAULT_DATA_ROOT,
        tdx_path: str = DEFAULT_TDX_PATH,
        index_symbols: list[str] | None = Query(default=None),
    ) -> dict[str, Any]:
        requested_symbols = normalize_symbol_tuple(index_symbols or list(DEFAULT_ETF_TRACKING_INDEX_SYMBOLS))
        cache_key = ("etf-tracking", data_root, tdx_path, requested_symbols)
        cached = _route_cache_get(_ETF_TRACKING_CACHE, cache_key, ttl_seconds=ETF_TRACKING_CACHE_TTL_SECONDS)
        if cached is not None:
            cached["cache"] = _cache_meta(True, ETF_TRACKING_CACHE_TTL_SECONDS, scope="memory")
            return cached
        cached = _disk_cache_get(
            data_root=data_root,
            scope="etf-tracking",
            key=cache_key,
            ttl_seconds=ETF_TRACKING_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            _route_cache_put(_ETF_TRACKING_CACHE, cache_key, cached)
            cached["cache"] = _cache_meta(True, ETF_TRACKING_CACHE_TTL_SECONDS, scope="disk")
            return cached
        try:
            frame = etf_tracking_with_runtime(data_root, tdx_path, index_symbols=requested_symbols)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        enriched = _enrich_etf_tracking_names(frame, data_root=data_root, tdx_path=tdx_path)
        response = {
            "index_symbols": list(requested_symbols),
            "record_count": int(len(enriched)),
            "records": _records(enriched, limit=None),
            "cache": _cache_meta(False, ETF_TRACKING_CACHE_TTL_SECONDS, scope="network"),
        }
        _attach_disk_cache_result(
            response,
            _disk_cache_put(data_root=data_root, scope="etf-tracking", key=cache_key, payload=response),
        )
        _route_cache_put(_ETF_TRACKING_CACHE, cache_key, response)
        return response

    @app.post("/api/etf-returns")
    def etf_returns(payload: schemas.EtfReturnsPayload) -> dict[str, Any]:
        symbols = normalize_symbol_tuple(payload.symbols)
        if not symbols:
            return {
                "record_count": 0,
                "records": [],
                "cache": _cache_meta(False, ETF_RETURNS_CACHE_TTL_SECONDS, scope="network"),
            }
        cache_key = ("etf-returns", payload.data_root, payload.adjust, payload.end, symbols)
        cached = _route_cache_get(_ETF_RETURNS_CACHE, cache_key, ttl_seconds=ETF_RETURNS_CACHE_TTL_SECONDS)
        if cached is not None:
            cached["cache"] = _cache_meta(True, ETF_RETURNS_CACHE_TTL_SECONDS, scope="memory")
            return cached
        cached = _disk_cache_get(
            data_root=payload.data_root,
            scope="etf-returns",
            key=cache_key,
            ttl_seconds=ETF_RETURNS_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            _route_cache_put(_ETF_RETURNS_CACHE, cache_key, cached)
            cached["cache"] = _cache_meta(True, ETF_RETURNS_CACHE_TTL_SECONDS, scope="disk")
            return cached
        try:
            records = _local_etf_return_records(
                data_root=payload.data_root,
                adjust=payload.adjust,
                symbols=symbols,
                end=payload.end,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = {
            "record_count": len(records),
            "records": records,
            "cache": _cache_meta(False, ETF_RETURNS_CACHE_TTL_SECONDS, scope="network"),
        }
        _attach_disk_cache_result(
            response,
            _disk_cache_put(data_root=payload.data_root, scope="etf-returns", key=cache_key, payload=response),
        )
        _route_cache_put(_ETF_RETURNS_CACHE, cache_key, response)
        return response


def _cache_meta(hit: bool, ttl_seconds: int, *, scope: str) -> dict[str, Any]:
    return {"hit": hit, "scope": scope, "ttl_seconds": ttl_seconds}


def _api_shortcut_symbol_groups(symbol_metadata: pd.DataFrame) -> list[dict[str, list[str] | str]]:
    return shortcut_symbol_groups(
        metadata=symbol_metadata,
        include_catalog_universe=not _has_non_catalog_symbol_metadata(symbol_metadata),
    )


def _static_shortcut_symbol_groups() -> list[dict[str, list[str] | str]]:
    return [{"name": name, "symbols": list(symbols)} for name, symbols in QUICK_SYMBOL_GROUPS.items()]


def _has_non_catalog_symbol_metadata(symbol_metadata: pd.DataFrame) -> bool:
    if symbol_metadata.empty or "source" not in symbol_metadata.columns:
        return bool(len(symbol_metadata))
    sources = symbol_metadata["source"].fillna("").astype(str).str.strip().str.lower()
    return bool((sources.ne("") & sources.ne("catalog")).any())


def _route_cache_get(
    cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]],
    key: tuple[Any, ...],
    *,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    entry = cache.get(key)
    if entry is None:
        return None
    created_at, payload = entry
    if monotonic() - created_at > ttl_seconds:
        cache.pop(key, None)
        return None
    cache.move_to_end(key)
    return _clone_response_payload(payload)


def _route_cache_put(
    cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]],
    key: tuple[Any, ...],
    payload: dict[str, Any],
) -> None:
    cache[key] = (monotonic(), _clone_response_payload(payload))
    cache.move_to_end(key)
    while len(cache) > ETF_API_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def _disk_cache_get(*, data_root: str, scope: str, key: tuple[Any, ...], ttl_seconds: int) -> dict[str, Any] | None:
    path = _disk_cache_path(data_root=data_root, scope=scope, key=key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    saved_at = _finite_float(payload.get("saved_at")) if isinstance(payload, dict) else None
    response = payload.get("payload") if isinstance(payload, dict) else None
    if not saved_at or not isinstance(response, dict):
        return None
    if wall_time() - saved_at > ttl_seconds:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return _clone_response_payload(response)


def _disk_cache_put(*, data_root: str, scope: str, key: tuple[Any, ...], payload: dict[str, Any]) -> str:
    path = _disk_cache_path(data_root=data_root, scope=scope, key=key)
    cache_payload = {
        "saved_at": wall_time(),
        "scope": scope,
        "payload": _clone_response_payload(payload),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(cache_payload, ensure_ascii=False, separators=(",", ":"), default=str),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        return str(exc)
    return ""


def _disk_cache_path(*, data_root: str, scope: str, key: tuple[Any, ...]) -> Path:
    digest = sha256(json.dumps(key, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return Path(data_root).expanduser() / ".tdx_downloader" / "api_cache" / scope / f"{digest}.json"


def _attach_disk_cache_result(response: dict[str, Any], error: str) -> None:
    cache = response.setdefault("cache", {})
    if not isinstance(cache, dict):
        return
    cache["persisted"] = not error
    if error:
        cache["disk_error"] = error


def _clone_response_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cloned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            cloned[key] = [dict(item) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, dict):
            cloned[key] = dict(value)
        else:
            cloned[key] = value
    return cloned


def _clear_etf_route_caches() -> None:
    _ETF_TRACKING_CACHE.clear()
    _ETF_RETURNS_CACHE.clear()


def _sort_picker_symbol_groups_by_recent_amount(
    groups: list[dict[str, Any]],
    *,
    data_root: str,
    adjust: str,
) -> list[dict[str, Any]]:
    sortable_symbols = [
        symbol
        for group in groups
        if str(group.get("name", "")) in PICKER_LIQUIDITY_SORT_GROUPS
        for symbol in _symbol_group_symbols(group)
    ]
    scores = _recent_amount_scores(data_root=data_root, adjust=adjust, symbols=sortable_symbols)
    if not scores:
        return groups

    sorted_groups: list[dict[str, Any]] = []
    for group in groups:
        name = str(group.get("name", ""))
        symbols = _symbol_group_symbols(group)
        if name not in PICKER_LIQUIDITY_SORT_GROUPS or not symbols:
            sorted_groups.append(group)
            continue
        ranked = _sort_symbols_by_amount(symbols, scores)
        sorted_groups.append({**group, "symbols": ranked})
    return sorted_groups


def _symbol_group_symbols(group: dict[str, Any]) -> list[str]:
    raw_symbols = group.get("symbols", [])
    if not isinstance(raw_symbols, list | tuple):
        return []
    return [symbol for symbol in (normalize_symbol(item) for item in raw_symbols) if symbol]


def _missing_target_symbol_group(groups: list[dict[str, Any]], target: str) -> bool:
    required = {
        "etf": ("ETF列表",),
        "index": ("板块指数",),
        "stock": ("全A股票",),
    }.get(str(target).strip().lower(), ())
    if not required:
        return False
    by_name = {str(group.get("name", "")): _symbol_group_symbols(group) for group in groups}
    return any(not by_name.get(name) for name in required)


def _recent_amount_scores(*, data_root: str, adjust: str, symbols: list[str]) -> dict[str, float]:
    from tdx_downloader.data.manager import normalize_symbol_tuple

    unique = normalize_symbol_tuple(symbols)
    if not unique:
        return {}
    bars = load_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust=adjust,
        symbols=unique,
        start="1900-01-01",
        end="2100-01-01",
    )
    if bars.empty or "amount" not in bars.columns:
        return {}
    frame = bars.loc[:, ["stock_code", "date", "amount"]].copy()
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame = frame.dropna(subset=["stock_code", "date", "amount"])
    frame = frame.loc[frame["amount"].gt(0)].sort_values(["stock_code", "date"])
    if frame.empty:
        return {}
    recent = frame.groupby("stock_code", group_keys=False).tail(PICKER_LIQUIDITY_LOOKBACK_BARS)
    scores = recent.groupby("stock_code")["amount"].mean()
    return {str(symbol): float(value) for symbol, value in scores.items() if math.isfinite(float(value))}


def _sort_symbols_by_amount(symbols: list[str], scores: dict[str, float]) -> list[str]:
    original_order = {symbol: index for index, symbol in enumerate(symbols)}

    def sort_key(symbol: str) -> tuple[int, float, int]:
        score = scores.get(symbol)
        if score is None or not math.isfinite(score):
            return (1, 0.0, original_order[symbol])
        return (0, -score, original_order[symbol])

    return sorted(symbols, key=sort_key)


def _local_symbol_metric_records(
    *,
    data_root: str,
    adjust: str,
    symbols: tuple[str, ...],
    end: str,
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    end_ts = pd.Timestamp(end)
    start = (end_ts - pd.Timedelta(days=30)).date().isoformat()
    bars = load_daily_bars(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
    )
    if bars.empty:
        return []
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["stock_code", "date"]).sort_values(["stock_code", "date"])
    if frame.empty:
        return []
    latest_by_symbol = {
        str(symbol): row
        for symbol, row in frame.groupby("stock_code", sort=False).tail(1).set_index("stock_code").iterrows()
    }
    records: list[dict[str, Any]] = []
    for symbol in symbols:
        row = latest_by_symbol.get(symbol)
        if row is None:
            continue
        records.append(
            {
                "symbol": symbol,
                "latest_date": row["date"].date().isoformat(),
                "close": _finite_float(row.get("close")),
                "amount": _finite_float(row.get("amount")),
                "volume": _finite_float(row.get("volume")),
                "market_value": None,
                "turnover_rate": None,
            }
        )
    return records


def _local_etf_return_records(
    *,
    data_root: str,
    adjust: str,
    symbols: tuple[str, ...],
    end: str,
) -> list[dict[str, Any]]:
    end_ts = pd.Timestamp(end)
    start = (end_ts - pd.Timedelta(days=400)).date().isoformat()
    bars = load_daily_bars(
        data_root=data_root,
        adjust=adjust,
        symbols=symbols,
        start=start,
        end=end,
    )
    if bars.empty:
        return []

    frames_by_symbol = {
        str(symbol): frame
        for symbol, frame in bars.groupby("stock_code", sort=False)
        if str(symbol)
    }
    records: list[dict[str, Any]] = []
    for symbol in symbols:
        source_frame = frames_by_symbol.get(symbol)
        if source_frame is None:
            continue
        frame = source_frame.sort_values("date").copy()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        if "amount" in frame.columns:
            frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"])
        if frame.empty:
            continue
        records.append(_local_etf_return_record(symbol, frame, end_ts=end_ts))
    return records


def _local_etf_return_record(symbol: str, frame: pd.DataFrame, *, end_ts: pd.Timestamp) -> dict[str, Any]:
    latest = frame.iloc[-1]
    latest_close = float(latest["close"])
    latest_amount = _finite_float(latest.get("amount"))
    return {
        "symbol": symbol,
        "latest_date": latest["date"],
        "close": latest_close,
        "amount": latest_amount,
        "return_1d": _bar_return(frame, 1),
        "return_5d": _bar_return(frame, 5),
        "return_20d": _bar_return(frame, 20),
        "return_50d": _bar_return(frame, 50),
        "return_ytd": _ytd_return(frame, end_ts=end_ts),
    }


def _bar_return(frame: pd.DataFrame, offset: int) -> float | None:
    if len(frame) <= offset:
        return None
    latest = float(frame.iloc[-1]["close"])
    base = float(frame.iloc[-offset - 1]["close"])
    if not math.isfinite(latest) or not math.isfinite(base) or base == 0:
        return None
    return latest / base - 1.0


def _ytd_return(frame: pd.DataFrame, *, end_ts: pd.Timestamp) -> float | None:
    year_start = pd.Timestamp(year=end_ts.year, month=1, day=1)
    current_year = frame.loc[frame["date"] >= year_start]
    if current_year.empty:
        return None
    latest = float(frame.iloc[-1]["close"])
    base = float(current_year.iloc[0]["close"])
    if not math.isfinite(latest) or not math.isfinite(base) or base == 0:
        return None
    return latest / base - 1.0


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _symbol_group_names(
    groups: list[dict[str, Any]],
    *,
    symbol_metadata: pd.DataFrame,
) -> dict[str, str]:
    from tdx_downloader.data.manager import normalize_symbol_tuple

    symbols = normalize_symbol_tuple(symbol for group in groups for symbol in group.get("symbols", []))
    names = {symbol: DEFAULT_STOCK_NAME_BY_CODE[symbol] for symbol in symbols if symbol in DEFAULT_STOCK_NAME_BY_CODE}
    if not symbol_metadata.empty:
        for row in symbol_metadata.itertuples(index=False):
            symbol = normalize_symbol(getattr(row, "stock_code", ""))
            name = str(getattr(row, "stock_name", "") or "").strip()
            if symbol in symbols and name:
                names[symbol] = name
    return names


def _enrich_etf_tracking_names(frame: pd.DataFrame, *, data_root: str, tdx_path: str) -> pd.DataFrame:
    if frame.empty:
        result = frame.copy()
        result["tracking_name"] = pd.Series(dtype=object)
        return result
    names = dict(DEFAULT_ETF_TRACKING_INDEX_NAMES)
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    if not metadata.empty:
        for row in metadata.itertuples(index=False):
            symbol = normalize_symbol(getattr(row, "stock_code", ""))
            name = str(getattr(row, "stock_name", "") or "").strip()
            if symbol and name:
                names[symbol] = name
    result = frame.copy()
    result["tracking_name"] = result["tracking_symbol"].map(lambda symbol: names.get(normalize_symbol(symbol), ""))
    return result


def _worker_status() -> dict[str, Any]:
    if not should_use_parallels_runtime():
        return {"enabled": False, "configured": False, "status": "local"}
    client = TdxWorkerClient(timeout_seconds=0.5)
    try:
        health = client.health()
    except WorkerUnavailable as exc:
        return {"enabled": True, "configured": True, "status": "unavailable", "url": client.base_url, "message": str(exc)}
    return {
        "enabled": True,
        "configured": True,
        "status": "ok",
        "url": client.base_url,
        "python": health.get("python", ""),
        "scratch_root": health.get("scratch_root", ""),
    }
