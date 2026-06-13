from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from tdx_downloader.data.catalog import (
    ASSET_TYPE_LABELS,
    build_catalog,
    catalog_path_for,
    enrich_inventory_for_catalog,
    infer_asset_type,
    query_catalog,
    query_coverage_keys,
    query_coverage_runs,
)
from tdx_downloader.data.audit import (
    _audit_window_for_timeframe,
    _expected_timestamps_for_window,
    _missing_coverage_summary,
)
from tdx_downloader.data.indicators import (
    IndicatorFormula,
    IndicatorStore,
    compute_indicator_cache,
    indicator_cache_inventory,
    load_indicator_values,
    make_indicator_formula,
    normalize_formula_ids,
)
from tdx_downloader.data.repository import MarketDataRepository
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES, ensure_supported_timeframe, normalize_symbol, unique_symbols
from tdx_downloader.data.symbols import load_symbol_metadata
from tdx_downloader.data.summary import summarize_data_inventory

ProgressCallback = Callable[[dict[str, object]], None]

DOWNLOAD_MODES = ("smart", "force")
CATALOG_SYMBOL_SOURCE = "catalog"
QUICK_SYMBOL_GROUPS = {
    "核心样例": ("000001.SZ", "600519.SH", "300750.SZ", "601318.SH"),
    "宽基指数": ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000852.SH", "000905.SH"),
    "ETF样例": ("510300.SH", "510500.SH", "159915.SZ", "588000.SH", "512100.SH"),
}
FORCE_DOWNLOAD_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "action",
    "rows_written",
    "new_rows",
    "start",
    "end",
    "path",
    "message",
]
COVERAGE_QUERY_SYMBOL_BATCH_SIZE = 400
COVERAGE_DISPLAY_COLUMNS = [
    "coverage_status",
    "coverage_rows_in_window",
    "coverage_expected_rows",
    "coverage_missing_rows",
    "coverage_ratio",
    "coverage_start_at",
    "coverage_end_at",
    "coverage_first_missing_at",
    "coverage_last_missing_at",
    "coverage_message",
]


@dataclass(frozen=True)
class DataDownloadConfig:
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    start: str
    end: str
    tqcenter_path: str = ""
    batch_size: int = 100
    min_coverage_ratio: float | None = None
    strict_after_update: bool = True


@dataclass(frozen=True)
class DataCacheSnapshot:
    inventory: pd.DataFrame
    catalog: pd.DataFrame
    catalog_path: Path
    summary: dict[str, object]
    readiness: pd.DataFrame
    by_timeframe: pd.DataFrame
    by_status: pd.DataFrame
    by_asset_type: pd.DataFrame
    by_dataset: pd.DataFrame


@dataclass(frozen=True)
class DataDownloadResult:
    table: pd.DataFrame
    summary: dict[str, object]


class DataManagementService:
    """独立数据管理服务；只依赖行情数据层，不依赖回测和 Streamlit。"""

    def __init__(self, data_root: str | Path, adjust: str = "qfq") -> None:
        self.data_root = Path(data_root).expanduser()
        self.adjust = adjust
        self.repository = MarketDataRepository(self.data_root, adjust=adjust)

    def cache_snapshot(
        self,
        *,
        timeframes: tuple[str, ...] | list[str] = SUPPORTED_TIMEFRAMES,
        symbols: tuple[str, ...] | list[str] | None = None,
        asset_types: tuple[str, ...] | list[str] | None = None,
        tdx_path: str | Path = "",
        symbol_metadata: pd.DataFrame | None = None,
        rebuild_catalog: bool = True,
        refresh_coverage: bool = False,
    ) -> DataCacheSnapshot:
        normalized_timeframes = normalize_timeframes(timeframes)
        normalized_symbols = normalize_symbol_tuple(symbols) if symbols is not None else None
        existing_catalog = (
            query_catalog(data_root=self.data_root, adjust=self.adjust, timeframes=normalized_timeframes)
            if rebuild_catalog
            else None
        )
        inventory = self.repository.inventory(
            timeframes=normalized_timeframes,
            symbols=normalized_symbols,
            existing_catalog=existing_catalog,
            fast_existing=rebuild_catalog,
        )
        indicator_inventory = indicator_cache_inventory(self.data_root)
        if normalized_symbols is not None and not indicator_inventory.empty:
            indicator_inventory = indicator_inventory.loc[indicator_inventory["stock_code"].isin(normalized_symbols)].copy()
        if not indicator_inventory.empty:
            indicator_inventory = indicator_inventory.loc[indicator_inventory["timeframe"].isin(normalized_timeframes)].copy()
        if not indicator_inventory.empty:
            inventory = pd.concat([inventory, indicator_inventory], ignore_index=True, sort=False)
        metadata = symbol_metadata if symbol_metadata is not None else self.repository.symbol_metadata(tdx_path=tdx_path)
        catalog = enrich_inventory_for_catalog(inventory, symbol_metadata=metadata)
        catalog_path = catalog_path_for(self.data_root)
        if rebuild_catalog:
            catalog_path = build_catalog(
                data_root=self.data_root,
                inventory=inventory,
                symbol_metadata=metadata,
                refresh_coverage=refresh_coverage,
            )
        if asset_types:
            allowed = {str(item) for item in asset_types}
            catalog = catalog.loc[catalog["asset_type"].isin(allowed)].reset_index(drop=True)
            inventory = inventory.loc[inventory["stock_code"].isin(catalog["stock_code"])].reset_index(drop=True)
        return DataCacheSnapshot(
            inventory=inventory,
            catalog=catalog,
            catalog_path=catalog_path,
            summary=cache_summary(catalog),
            readiness=cache_readiness(catalog),
            by_timeframe=cache_by_timeframe(catalog),
            by_status=cache_by_status(catalog),
            by_asset_type=cache_by_asset_type(catalog),
            by_dataset=cache_by_dataset(catalog),
        )

    def catalog_query(
        self,
        *,
        asset_types: tuple[str, ...] | list[str] | None = None,
        timeframes: tuple[str, ...] | list[str] | None = None,
        indicators: tuple[str, ...] | list[str] | None = None,
        statuses: tuple[str, ...] | list[str] | None = None,
    ) -> pd.DataFrame:
        return query_catalog(
            data_root=self.data_root,
            asset_types=asset_types,
            timeframes=timeframes,
            indicators=indicators,
            statuses=statuses,
        )

    def cached_symbols(
        self,
        *,
        asset_types: tuple[str, ...] | list[str] | None = None,
        timeframes: tuple[str, ...] | list[str] | None = None,
        tdx_path: str | Path = "",
    ) -> tuple[str, ...]:
        snapshot = self.cache_snapshot(
            timeframes=tuple(timeframes or SUPPORTED_TIMEFRAMES),
            symbols=None,
            asset_types=asset_types,
            tdx_path=tdx_path,
            rebuild_catalog=False,
        )
        if snapshot.catalog.empty:
            return ()
        return tuple(sorted(snapshot.catalog["stock_code"].dropna().astype(str).unique().tolist()))

    def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
        return self.repository.plan_from_tdx(
            symbols=normalize_symbol_tuple(config.symbols),
            timeframes=normalize_timeframes(config.timeframes),
            start=config.start,
            end=config.end,
            min_coverage_ratio=config.min_coverage_ratio,
        )

    def preview_download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
        return self.repository.plan_from_tdx(
            symbols=normalize_symbol_tuple(config.symbols),
            timeframes=normalize_timeframes(config.timeframes),
            start=config.start,
            end=config.end,
            min_coverage_ratio=config.min_coverage_ratio,
            audit_mode="fast",
        )

    def download(
        self,
        config: DataDownloadConfig,
        *,
        mode: str = "smart",
        progress_callback: ProgressCallback | None = None,
    ) -> DataDownloadResult:
        normalized_mode = normalize_download_mode(mode)
        if normalized_mode == "smart":
            table = self.repository.prepare_from_tdx(
                symbols=normalize_symbol_tuple(config.symbols),
                timeframes=normalize_timeframes(config.timeframes),
                start=config.start,
                end=config.end,
                tqcenter_path=config.tqcenter_path,
                batch_size=config.batch_size,
                progress_callback=progress_callback,
                min_coverage_ratio=config.min_coverage_ratio,
                strict_after_update=config.strict_after_update,
            )
        else:
            table = self._force_download(config, progress_callback=progress_callback)
        return DataDownloadResult(table=table, summary=download_summary(table))

    def indicator_store(self) -> IndicatorStore:
        return IndicatorStore(self.data_root)

    def list_indicator_formulas(self) -> pd.DataFrame:
        return self.indicator_store().list_formulas()

    def list_indicator_mappings(self) -> pd.DataFrame:
        return self.indicator_store().list_mappings()

    def upsert_indicator_formula(
        self,
        *,
        formula_id: str,
        name: str,
        expression: str,
        source: str = "custom",
        output_name: str = "",
        tdx_program: str = "",
    ) -> IndicatorFormula:
        return self.indicator_store().upsert_formula(
            make_indicator_formula(
                formula_id=formula_id,
                name=name,
                expression=expression,
                source=source,
                output_name=output_name,
                tdx_program=tdx_program,
            )
        )

    def import_tdx_indicator_formulas(self, text: str, *, formula_id_prefix: str = "") -> list[IndicatorFormula]:
        return self.indicator_store().import_tdx_formula_text(text, formula_id_prefix=formula_id_prefix)

    def upsert_indicator_mapping(
        self,
        *,
        formula_id: str,
        stock_code: str = "",
        asset_type: str = "",
        timeframe: str = "",
        enabled: bool = True,
    ) -> dict[str, object]:
        return self.indicator_store().upsert_mapping(
            formula_id=formula_id,
            stock_code=stock_code,
            asset_type=asset_type,
            timeframe=timeframe,
            enabled=enabled,
        )

    def compute_indicators(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        formula_ids: tuple[str, ...] | list[str],
        timeframe: str,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        force: bool = False,
    ) -> pd.DataFrame:
        return compute_indicator_cache(
            data_root=self.data_root,
            adjust=self.adjust,
            timeframe=timeframe,
            symbols=normalize_symbol_tuple(symbols),
            formula_ids=normalize_formula_ids(list(formula_ids)),
            start=start,
            end=end,
            force=force,
        )

    def load_indicators(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        formula_ids: tuple[str, ...] | list[str],
        timeframe: str,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        return load_indicator_values(
            data_root=self.data_root,
            adjust=self.adjust,
            timeframe=timeframe,
            symbols=normalize_symbol_tuple(symbols),
            formula_ids=normalize_formula_ids(list(formula_ids)),
            start=start,
            end=end,
        )

    def _force_download(
        self,
        config: DataDownloadConfig,
        *,
        progress_callback: ProgressCallback | None,
    ) -> pd.DataFrame:
        symbols = normalize_symbol_tuple(config.symbols)
        timeframes = normalize_timeframes(config.timeframes)
        frames: list[pd.DataFrame] = []
        for step_index, timeframe in enumerate(timeframes, start=1):
            _emit_progress(
                progress_callback,
                stage="force_timeframe_start",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(timeframes),
            )
            written = self.repository.update_from_tdx(
                symbols=symbols,
                timeframe=timeframe,
                start=config.start,
                end=config.end,
                tqcenter_path=config.tqcenter_path,
                batch_size=config.batch_size,
                progress_callback=progress_callback,
            )
            frames.append(_force_download_frame(written, timeframe=timeframe, adjust=self.adjust))
            _emit_progress(
                progress_callback,
                stage="force_timeframe_done",
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(timeframes),
            )
        if not frames:
            return pd.DataFrame(columns=FORCE_DOWNLOAD_COLUMNS)
        return pd.concat(frames, ignore_index=True).loc[:, FORCE_DOWNLOAD_COLUMNS]


def normalize_symbol_tuple(symbols: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    return tuple(unique_symbols(tuple(symbols or ())))


def normalize_timeframes(timeframes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in timeframes:
        timeframe = ensure_supported_timeframe(item)
        if timeframe in seen:
            continue
        seen.add(timeframe)
        result.append(timeframe)
    if not result:
        raise ValueError("timeframes 不能为空。")
    return tuple(result)


def normalize_download_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in DOWNLOAD_MODES:
        raise ValueError("下载模式只支持 smart 或 force。")
    return normalized


def shortcut_symbols(name: str) -> tuple[str, ...]:
    return QUICK_SYMBOL_GROUPS.get(str(name), ())


def shortcut_symbol_groups(
    *,
    data_root: str | Path | None = None,
    tdx_path: str | Path = "",
    metadata: pd.DataFrame | None = None,
    include_catalog_universe: bool = False,
) -> list[dict[str, list[str] | str]]:
    groups: list[dict[str, list[str] | str]] = [
        {"name": name, "symbols": list(symbols)} for name, symbols in QUICK_SYMBOL_GROUPS.items()
    ]
    symbol_metadata = metadata
    if symbol_metadata is None and data_root is not None:
        symbol_metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    dynamic_groups = _dynamic_shortcut_groups(
        symbol_metadata,
        include_catalog_universe=include_catalog_universe,
    )
    for name in ("ETF列表", "板块指数", "全A股票"):
        symbols = dynamic_groups.get(name, ())
        if symbols:
            groups.append({"name": name, "symbols": list(symbols)})
    return groups


def _dynamic_shortcut_groups(
    metadata: pd.DataFrame | None,
    *,
    include_catalog_universe: bool = False,
) -> dict[str, tuple[str, ...]]:
    if metadata is None or metadata.empty:
        return {"ETF列表": (), "全A股票": (), "板块指数": ()}
    allow_catalog_universe = include_catalog_universe and not _has_non_catalog_symbol_metadata(metadata)
    all_a: list[str] = []
    etfs: list[str] = []
    sector_indexes: list[str] = []
    for row in metadata.itertuples(index=False):
        source = str(getattr(row, "source", "") or "").strip().lower()
        if source == CATALOG_SYMBOL_SOURCE and not allow_catalog_universe:
            continue
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        if not symbol:
            continue
        name = str(getattr(row, "stock_name", "") or "")
        code, exchange = symbol.split(".", 1)
        asset_type = infer_asset_type(symbol, name)
        if asset_type == "etf":
            etfs.append(symbol)
            continue
        if asset_type == "stock":
            all_a.append(symbol)
            continue
        if asset_type == "index" and exchange == "SH" and code.startswith("880"):
            sector_indexes.append(symbol)
    return {
        "ETF列表": tuple(sorted(unique_symbols(etfs))),
        "全A股票": tuple(sorted(unique_symbols(all_a))),
        "板块指数": tuple(sorted(unique_symbols(sector_indexes))),
    }


def _has_non_catalog_symbol_metadata(metadata: pd.DataFrame) -> bool:
    if "source" not in metadata.columns:
        return bool(len(metadata))
    sources = metadata["source"].fillna("").astype(str).str.strip().str.lower()
    return bool((sources.ne("") & sources.ne(CATALOG_SYMBOL_SOURCE)).any())


def cache_summary(catalog: pd.DataFrame) -> dict[str, object]:
    summary = summarize_data_inventory(catalog)
    symbols = catalog["stock_code"].dropna().astype(str).nunique() if "stock_code" in catalog.columns else 0
    timeframes = catalog["timeframe"].dropna().astype(str).nunique() if "timeframe" in catalog.columns else 0
    asset_types = catalog["asset_type"].dropna().astype(str).nunique() if "asset_type" in catalog.columns else 0
    datasets = (
        catalog.loc[:, ["data_kind", "indicator"]].drop_duplicates().shape[0]
        if {"data_kind", "indicator"}.issubset(catalog.columns)
        else 0
    )
    latest_modified = catalog["modified_at"].max() if "modified_at" in catalog.columns and not catalog.empty else pd.NaT
    summary.update(
        {
            "symbol_count": float(symbols),
            "timeframe_count": float(timeframes),
            "asset_type_count": float(asset_types),
            "dataset_count": float(datasets),
            "catalog_row_count": float(len(catalog)),
            "latest_modified_at": latest_modified,
        }
    )
    return summary


def annotate_catalog_coverage(
    catalog: pd.DataFrame,
    *,
    data_root: str | Path,
    adjust: str,
    start: str = "",
    end: str = "",
) -> pd.DataFrame:
    """Add requested-window coverage columns without changing file availability status."""
    result = _ensure_catalog_coverage_columns(catalog.copy())
    if result.empty or not start or not end:
        return result
    price_mask = (
        result.get("status", pd.Series([""] * len(result))).fillna("").astype(str).eq("cached")
        & result.get("data_kind", pd.Series([""] * len(result))).fillna("").astype(str).eq("price")
        & result.get("indicator", pd.Series([""] * len(result))).fillna("").astype(str).eq("ohlcv")
    )
    if not bool(price_mask.any()):
        return result
    price_rows = result.loc[price_mask]
    timeframes = _coverage_catalog_timeframes(price_rows)
    symbols = _coverage_catalog_symbols(price_rows)
    if not symbols:
        return result
    coverage_timeframes = tuple(sorted(set(timeframes) | {"1d"}, key=_timeframe_sort_key))
    window_by_timeframe: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for timeframe in coverage_timeframes:
        try:
            window_by_timeframe[timeframe] = _audit_window_for_timeframe(timeframe, start=start, end=end)
        except (TypeError, ValueError):
            continue
    query_start, query_end = _coverage_query_window(window_by_timeframe.values())
    coverage = _query_coverage_runs_for_symbols(
        data_root=data_root,
        symbols=symbols,
        adjust=adjust,
        timeframes=coverage_timeframes,
        start=query_start,
        end=query_end,
    )
    coverage_by_key = _coverage_runs_by_key(coverage)
    indexed_keys = _query_coverage_keys_for_symbols(
        data_root=data_root,
        symbols=symbols,
        adjust=adjust,
        timeframes=coverage_timeframes,
    )
    daily_sessions = _daily_sessions_from_coverage(coverage, start=start, end=end)
    expected_cache: dict[tuple[str, tuple[pd.Timestamp, ...]], list[pd.Timestamp]] = {}
    state_cache: dict[tuple[str, str], dict[str, object]] = {}

    for index, row in result.loc[price_mask].iterrows():
        symbol = normalize_symbol(row.get("stock_code", ""))
        timeframe = str(row.get("timeframe", "") or "")
        if not symbol or not timeframe:
            continue
        cache_key = (symbol, timeframe)
        cached_state = state_cache.get(cache_key)
        if cached_state is not None:
            for column, value in cached_state.items():
                result.at[index, column] = value
            continue
        runs = coverage_by_key.get((symbol, timeframe), [])
        if not runs and cache_key not in indexed_keys:
            cached_state = _coverage_status_state(
                status="coverage_unknown",
                message="本地文件可读，但尚未建立覆盖索引；请刷新缓存索引后检查完整性。",
            )
            state_cache[cache_key] = cached_state
            for column, value in cached_state.items():
                result.at[index, column] = value
            continue
        window = window_by_timeframe.get(timeframe)
        if window is None:
            cached_state = _coverage_status_state(status="coverage_unknown", message="检查窗口无效，无法计算覆盖完整性。")
            state_cache[cache_key] = cached_state
            for column, value in cached_state.items():
                result.at[index, column] = value
            continue
        start_ts, end_ts = window
        coverage_state = _coverage_window_state(
            timeframe=timeframe,
            start_ts=start_ts,
            end_ts=end_ts,
            coverage_runs=runs,
            expected_sessions=daily_sessions.get(symbol),
            expected_cache=expected_cache,
        )
        missing = int(coverage_state["coverage_missing_rows"])
        expected = int(coverage_state["coverage_expected_rows"])
        rows_in_window = int(coverage_state["coverage_rows_in_window"])
        status = "coverage_ready"
        if expected <= 0:
            status = "coverage_empty"
        elif rows_in_window <= 0:
            status = "coverage_empty"
        elif missing > 0:
            status = "coverage_partial"
        coverage_state["coverage_status"] = status
        coverage_state["coverage_message"] = _coverage_display_message(status, missing, expected)
        state_cache[cache_key] = coverage_state
        for column, value in coverage_state.items():
            result.at[index, column] = value
    return result


def cache_by_timeframe(catalog: pd.DataFrame) -> pd.DataFrame:
    columns = ["timeframe", "cached_count", "unavailable_count", "rows", "file_size_bytes", "latest_modified_at"]
    if catalog.empty:
        return pd.DataFrame(columns=columns)
    frame = catalog.copy()
    frame["status"] = frame.get("status", pd.Series([""] * len(frame))).fillna("").astype(str)
    frame["rows"] = pd.to_numeric(frame.get("rows", pd.Series([0] * len(frame))), errors="coerce").fillna(0)
    frame["file_size_bytes"] = pd.to_numeric(
        frame.get("file_size_bytes", pd.Series([0] * len(frame))),
        errors="coerce",
    ).fillna(0)
    grouped = frame.groupby("timeframe", sort=False).agg(
        cached_count=("status", lambda values: int(values.eq("cached").sum())),
        row_count=("status", "size"),
        rows=("rows", "sum"),
        file_size_bytes=("file_size_bytes", "sum"),
        latest_modified_at=("modified_at", "max"),
    )
    grouped["unavailable_count"] = grouped["row_count"] - grouped["cached_count"]
    return grouped.reset_index().loc[:, columns]


def _ensure_catalog_coverage_columns(catalog: pd.DataFrame) -> pd.DataFrame:
    for column in COVERAGE_DISPLAY_COLUMNS:
        if column not in catalog.columns:
            catalog[column] = _coverage_column_default(column, len(catalog))
    return catalog


def _coverage_column_default(column: str, length: int) -> object:
    if column in {"coverage_rows_in_window", "coverage_expected_rows", "coverage_missing_rows"}:
        return pd.Series([0] * length)
    if column == "coverage_ratio":
        return pd.Series([0.0] * length)
    if column.endswith("_at"):
        return pd.Series([pd.NaT] * length)
    if column == "coverage_status":
        return pd.Series(["not_checked"] * length)
    return pd.Series([""] * length)


def _coverage_catalog_timeframes(catalog: pd.DataFrame) -> tuple[str, ...]:
    result: list[str] = []
    for value in catalog.get("timeframe", pd.Series(dtype=object)).dropna().astype(str):
        try:
            result.append(ensure_supported_timeframe(value))
        except ValueError:
            continue
    return tuple(dict.fromkeys(result))


def _coverage_catalog_symbols(catalog: pd.DataFrame) -> tuple[str, ...]:
    result: list[str] = []
    for value in catalog.get("stock_code", pd.Series(dtype=object)).dropna().astype(str):
        symbol = normalize_symbol(value)
        if symbol:
            result.append(symbol)
    return tuple(dict.fromkeys(result))


def _query_coverage_runs_for_symbols(
    *,
    data_root: str | Path,
    symbols: tuple[str, ...],
    adjust: str,
    timeframes: tuple[str, ...],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for offset in range(0, len(symbols), COVERAGE_QUERY_SYMBOL_BATCH_SIZE):
        batch = symbols[offset : offset + COVERAGE_QUERY_SYMBOL_BATCH_SIZE]
        frames.append(
            query_coverage_runs(
                data_root=data_root,
                symbols=batch,
                adjust=adjust,
                timeframes=timeframes,
                start=start,
                end=end,
            )
        )
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    return pd.concat(non_empty, ignore_index=True)


def _query_coverage_keys_for_symbols(
    *,
    data_root: str | Path,
    symbols: tuple[str, ...],
    adjust: str,
    timeframes: tuple[str, ...],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for offset in range(0, len(symbols), COVERAGE_QUERY_SYMBOL_BATCH_SIZE):
        batch = symbols[offset : offset + COVERAGE_QUERY_SYMBOL_BATCH_SIZE]
        keys.update(query_coverage_keys(data_root=data_root, symbols=batch, adjust=adjust, timeframes=timeframes))
    return keys


def _coverage_runs_by_key(coverage: pd.DataFrame) -> dict[tuple[str, str], list[object]]:
    result: dict[tuple[str, str], list[object]] = {}
    if coverage.empty:
        return result
    for row in coverage.itertuples(index=False):
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        timeframe = str(getattr(row, "timeframe", "") or "")
        if not symbol or not timeframe:
            continue
        result.setdefault((symbol, timeframe), []).append(row)
    return result


def _daily_sessions_from_coverage(coverage: pd.DataFrame, *, start: str, end: str) -> dict[str, list[pd.Timestamp]]:
    if coverage.empty:
        return {}
    daily = coverage.loc[coverage["timeframe"].astype(str).eq("1d")].copy()
    if daily.empty:
        return {}
    start_day = pd.Timestamp(start).normalize()
    end_day = pd.Timestamp(end).normalize()
    sessions: dict[str, set[pd.Timestamp]] = {}
    for row in daily.itertuples(index=False):
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        if not symbol:
            continue
        run_start = pd.to_datetime(getattr(row, "start_at", pd.NaT), errors="coerce")
        run_end = pd.to_datetime(getattr(row, "end_at", pd.NaT), errors="coerce")
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        session_start = max(start_day, pd.Timestamp(run_start).normalize())
        session_end = min(end_day, pd.Timestamp(run_end).normalize())
        if session_start > session_end:
            continue
        sessions.setdefault(symbol, set()).update(pd.Timestamp(item) for item in pd.bdate_range(session_start, session_end))
    return {symbol: sorted(values) for symbol, values in sessions.items()}


def _coverage_window_state(
    *,
    timeframe: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    coverage_runs: list[object],
    expected_sessions: list[pd.Timestamp] | None,
    expected_cache: dict[tuple[str, tuple[pd.Timestamp, ...]], list[pd.Timestamp]],
) -> dict[str, object]:
    expected = _expected_timestamps_for_window(
        timeframe=timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
        expected_cache=expected_cache,
    )
    if not expected:
        return {
            "coverage_rows_in_window": 0,
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_ratio": 0.0,
            "coverage_start_at": pd.NaT,
            "coverage_end_at": pd.NaT,
            "coverage_first_missing_at": pd.NaT,
            "coverage_last_missing_at": pd.NaT,
        }
    available = _available_timestamps_from_coverage_runs(expected, coverage_runs=coverage_runs, timeframe=timeframe)
    missing = [timestamp for timestamp in expected if timestamp not in available]
    minutes = 1440 if ensure_supported_timeframe(timeframe) == "1d" else int(timeframe.removesuffix("m"))
    missing_summary = _missing_coverage_summary(expected, missing=set(missing), minutes=minutes)
    available_sorted = sorted(available)
    return {
        "coverage_rows_in_window": int(len(available)),
        "coverage_expected_rows": int(len(expected)),
        "coverage_missing_rows": int(len(missing)),
        "coverage_ratio": round(len(available) / len(expected), 12),
        "coverage_start_at": available_sorted[0] if available_sorted else pd.NaT,
        "coverage_end_at": available_sorted[-1] if available_sorted else pd.NaT,
        "coverage_first_missing_at": missing_summary["first_missing_at"],
        "coverage_last_missing_at": missing_summary["last_missing_at"],
    }


def _available_timestamps_from_coverage_runs(
    expected: list[pd.Timestamp],
    *,
    coverage_runs: list[object],
    timeframe: str,
) -> set[pd.Timestamp]:
    available: set[pd.Timestamp] = set()
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    for run in coverage_runs:
        run_start = pd.to_datetime(getattr(run, "start_at", pd.NaT), errors="coerce")
        run_end = pd.to_datetime(getattr(run, "end_at", pd.NaT), errors="coerce")
        if pd.isna(run_start) or pd.isna(run_end):
            continue
        if normalized_timeframe == "1d":
            available.update(
                timestamp
                for timestamp in expected
                if pd.Timestamp(run_start).normalize() <= pd.Timestamp(timestamp).normalize() <= pd.Timestamp(run_end).normalize()
            )
        else:
            available.update(timestamp for timestamp in expected if pd.Timestamp(run_start) <= timestamp <= pd.Timestamp(run_end))
    return available


def _set_coverage_values(catalog: pd.DataFrame, index: object, *, status: str, message: str) -> None:
    catalog.at[index, "coverage_status"] = status
    catalog.at[index, "coverage_message"] = message


def _coverage_status_state(*, status: str, message: str) -> dict[str, object]:
    return {"coverage_status": status, "coverage_message": message}


def _coverage_query_window(windows: object) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    valid = [(start, end) for start, end in windows if not pd.isna(start) and not pd.isna(end)]
    if not valid:
        return None, None
    return min(start for start, _ in valid), max(end for _, end in valid)


def _coverage_display_message(status: str, missing_rows: int, expected_rows: int) -> str:
    if status == "coverage_ready":
        return "当前检查窗口覆盖完整。"
    if status == "coverage_partial":
        return f"当前检查窗口缺失 {missing_rows} / {expected_rows} 根 K。"
    if status == "coverage_empty":
        return "当前检查窗口没有可用 K 线。"
    return "尚未检查覆盖完整性。"


def _timeframe_sort_key(value: str) -> int:
    try:
        return SUPPORTED_TIMEFRAMES.index(ensure_supported_timeframe(value))
    except ValueError:
        return len(SUPPORTED_TIMEFRAMES)


def cache_by_status(catalog: pd.DataFrame) -> pd.DataFrame:
    columns = ["status", "count", "rows", "file_size_bytes"]
    if catalog.empty:
        return pd.DataFrame(columns=columns)
    frame = catalog.copy()
    frame["status"] = frame.get("status", pd.Series([""] * len(frame))).fillna("").astype(str)
    frame["rows"] = pd.to_numeric(frame.get("rows", pd.Series([0] * len(frame))), errors="coerce").fillna(0)
    frame["file_size_bytes"] = pd.to_numeric(
        frame.get("file_size_bytes", pd.Series([0] * len(frame))),
        errors="coerce",
    ).fillna(0)
    return (
        frame.groupby("status", sort=False)
        .agg(count=("status", "size"), rows=("rows", "sum"), file_size_bytes=("file_size_bytes", "sum"))
        .reset_index()
        .loc[:, columns]
    )


def cache_by_asset_type(catalog: pd.DataFrame) -> pd.DataFrame:
    columns = ["asset_type", "asset_type_label", "cached_count", "unavailable_count", "rows", "file_size_bytes"]
    if catalog.empty:
        return pd.DataFrame(columns=columns)
    frame = catalog.copy()
    frame["status"] = frame.get("status", pd.Series([""] * len(frame))).fillna("").astype(str)
    frame["rows"] = pd.to_numeric(frame.get("rows", pd.Series([0] * len(frame))), errors="coerce").fillna(0)
    frame["file_size_bytes"] = pd.to_numeric(
        frame.get("file_size_bytes", pd.Series([0] * len(frame))),
        errors="coerce",
    ).fillna(0)
    grouped = frame.groupby("asset_type", sort=False).agg(
        cached_count=("status", lambda values: int(values.eq("cached").sum())),
        row_count=("status", "size"),
        rows=("rows", "sum"),
        file_size_bytes=("file_size_bytes", "sum"),
    )
    grouped["unavailable_count"] = grouped["row_count"] - grouped["cached_count"]
    result = grouped.reset_index()
    result["asset_type_label"] = result["asset_type"].map(lambda value: ASSET_TYPE_LABELS.get(str(value), str(value)))
    return result.loc[:, columns]


def cache_by_dataset(catalog: pd.DataFrame) -> pd.DataFrame:
    columns = ["asset_type", "data_kind", "indicator", "timeframe", "status", "count", "rows", "file_size_bytes"]
    if catalog.empty:
        return pd.DataFrame(columns=columns)
    frame = catalog.copy()
    frame["rows"] = pd.to_numeric(frame.get("rows", pd.Series([0] * len(frame))), errors="coerce").fillna(0)
    frame["file_size_bytes"] = pd.to_numeric(
        frame.get("file_size_bytes", pd.Series([0] * len(frame))),
        errors="coerce",
    ).fillna(0)
    return (
        frame.groupby(["asset_type", "data_kind", "indicator", "timeframe", "status"], sort=False)
        .agg(count=("status", "size"), rows=("rows", "sum"), file_size_bytes=("file_size_bytes", "sum"))
        .reset_index()
        .loc[:, columns]
    )


def cache_readiness(catalog: pd.DataFrame) -> pd.DataFrame:
    """按资产类型和周期汇总回测准备度，帮助用户先看能否跑，再看明细。"""
    columns = [
        "timeframe",
        "asset_type",
        "asset_type_label",
        "total_count",
        "cached_count",
        "missing_count",
        "coverage_ratio",
        "earliest_start_at",
        "latest_end_at",
        "status",
        "message",
    ]
    if catalog.empty:
        return pd.DataFrame(columns=columns)

    frame = catalog.copy()
    frame["status"] = frame.get("status", pd.Series([""] * len(frame))).fillna("").astype(str)
    frame["start_at"] = pd.to_datetime(frame.get("start_at", pd.Series([pd.NaT] * len(frame))), errors="coerce")
    frame["end_at"] = pd.to_datetime(frame.get("end_at", pd.Series([pd.NaT] * len(frame))), errors="coerce")
    grouped = frame.groupby(["timeframe", "asset_type"], sort=False).agg(
        total_count=("status", "size"),
        cached_count=("status", lambda values: int(values.eq("cached").sum())),
        earliest_start_at=("start_at", "min"),
        latest_end_at=("end_at", "max"),
    )
    grouped["missing_count"] = grouped["total_count"] - grouped["cached_count"]
    grouped["coverage_ratio"] = grouped["cached_count"] / grouped["total_count"].where(grouped["total_count"].ne(0), 1)
    result = grouped.reset_index()
    result["asset_type_label"] = result["asset_type"].map(lambda value: ASSET_TYPE_LABELS.get(str(value), str(value)))
    result["status"] = [
        _cache_readiness_status(cached_count, total_count)
        for cached_count, total_count in zip(result["cached_count"], result["total_count"], strict=False)
    ]
    result["message"] = [
        _cache_readiness_message(status, missing_count)
        for status, missing_count in zip(result["status"], result["missing_count"], strict=False)
    ]
    return result.loc[:, columns]


def download_summary(table: pd.DataFrame) -> dict[str, object]:
    if table.empty:
        return {"row_count": 0.0, "fetched_count": 0.0, "cached_count": 0.0, "new_rows": 0.0, "rows_written": 0.0}
    action = table["action"].fillna("").astype(str) if "action" in table.columns else pd.Series([""] * len(table))
    new_rows = pd.to_numeric(table.get("new_rows", pd.Series([0] * len(table))), errors="coerce").fillna(0)
    rows_written = pd.to_numeric(table.get("rows_written", pd.Series([0] * len(table))), errors="coerce").fillna(0)
    return {
        "row_count": float(len(table)),
        "fetched_count": float(action.eq("fetched").sum()),
        "cached_count": float(action.eq("cached").sum()),
        "new_rows": float(new_rows.sum()),
        "rows_written": float(rows_written.sum()),
    }


def _cache_readiness_status(cached_count: object, total_count: object) -> str:
    cached = int(cached_count)
    total = int(total_count)
    if total <= 0 or cached <= 0:
        return "empty"
    if cached == total:
        return "ready"
    return "partial"


def _cache_readiness_message(status: str, missing_count: object) -> str:
    missing = int(missing_count)
    if status == "ready":
        return "缓存完整，可以进入回测前数据质量审计。"
    if status == "partial":
        return f"部分缓存可用，仍有 {missing} 项需要补齐。"
    return "没有可用缓存，回测前需要先补齐。"


def _force_download_frame(written: pd.DataFrame, *, timeframe: str, adjust: str) -> pd.DataFrame:
    if written.empty:
        return pd.DataFrame(columns=FORCE_DOWNLOAD_COLUMNS)
    frame = written.rename(columns={"symbol": "stock_code"}).copy()
    frame["rows_written"] = pd.to_numeric(frame.get("new_rows", 0), errors="coerce").fillna(0).astype(int)
    frame["timeframe"] = timeframe
    frame["adjust"] = adjust
    frame["action"] = "fetched"
    return frame.reindex(columns=FORCE_DOWNLOAD_COLUMNS)


def _emit_progress(callback: ProgressCallback | None, **payload: object) -> None:
    if callback is not None:
        callback(payload)
