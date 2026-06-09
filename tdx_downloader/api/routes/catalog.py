from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
import pandas as pd

from tdx_downloader.data.catalog import catalog_path_for, query_catalog
from tdx_downloader.data.manager import (
    DataManagementService,
    cache_by_asset_type,
    cache_by_dataset,
    cache_by_status,
    cache_by_timeframe,
    cache_readiness,
    cache_summary,
)
from tdx_downloader.data.parallels_runtime import symbol_metadata_with_runtime
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES

from ..constants import DEFAULT_ADJUST, DEFAULT_DATA_ROOT, DEFAULT_TDX_PATH
from ..serialization import _json_dict, _records


def register_catalog_routes(app: FastAPI) -> None:
    @app.get("/api/overview")
    def overview(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        tdx_path: str = DEFAULT_TDX_PATH,
        refresh: bool = False,
        include_records: bool = True,
        timeframes: list[str] | None = Query(default=None),
    ) -> dict[str, Any]:
        service = DataManagementService(data_root, adjust=adjust)
        if refresh:
            snapshot = service.cache_snapshot(
                timeframes=tuple(timeframes or SUPPORTED_TIMEFRAMES),
                symbols=None,
                tdx_path=tdx_path,
                symbol_metadata=symbol_metadata_with_runtime(data_root, tdx_path),
                rebuild_catalog=True,
            )
            return _catalog_payload(snapshot.catalog, data_root=data_root, rebuilt=True, include_records=include_records)
        catalog = query_catalog(data_root=data_root)
        return _catalog_payload(catalog, data_root=data_root, rebuilt=False, include_records=include_records)


def _catalog_payload(catalog: pd.DataFrame, *, data_root: str, rebuilt: bool, include_records: bool = True) -> dict[str, Any]:
    path = catalog_path_for(data_root)
    return {
        "summary": _json_dict(cache_summary(catalog)),
        "by_timeframe": _records(cache_by_timeframe(catalog)),
        "by_asset_type": _records(cache_by_asset_type(catalog)),
        "by_status": _records(cache_by_status(catalog)),
        "by_dataset": _records(cache_by_dataset(catalog)),
        "readiness": _records(cache_readiness(catalog)),
        "records": _records(catalog, limit=None) if include_records else [],
        "record_count": int(len(catalog)),
        "catalog_path": str(path),
        "catalog_exists": path.exists(),
        "rebuilt": rebuilt,
        "record_limit": None if include_records else 0,
    }
