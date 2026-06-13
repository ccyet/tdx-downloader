from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from tdx_downloader.data.manager import DataManagementService, normalize_symbol_tuple, normalize_timeframes

from .. import schemas
from ..constants import DEFAULT_DATA_ROOT
from ..serialization import _records


def register_indicators_routes(app: FastAPI) -> None:
    @app.get("/api/indicators/formulas")
    def indicator_formulas_get(data_root: str = DEFAULT_DATA_ROOT) -> dict[str, Any]:
        service = DataManagementService(data_root)
        formulas = service.list_indicator_formulas()
        return {
            "data_root": data_root,
            "record_count": int(len(formulas)),
            "records": _records(formulas, limit=None),
        }

    @app.post("/api/indicators/formulas")
    def indicator_formula_post(payload: schemas.IndicatorFormulaPayload) -> dict[str, Any]:
        service = DataManagementService(payload.data_root)
        try:
            formula = service.upsert_indicator_formula(
                formula_id=payload.formula_id,
                name=payload.name or payload.formula_id,
                expression=payload.expression,
                source=payload.source,
                output_name=payload.output_name,
                tdx_program=payload.tdx_program,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"data_root": payload.data_root, "formula": formula.__dict__}

    @app.post("/api/indicators/import-tdx")
    def indicator_import_tdx_post(payload: schemas.IndicatorTdxImportPayload) -> dict[str, Any]:
        service = DataManagementService(payload.data_root)
        try:
            formulas = service.import_tdx_indicator_formulas(payload.text, formula_id_prefix=payload.formula_id_prefix)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "data_root": payload.data_root,
            "record_count": len(formulas),
            "records": [formula.__dict__ for formula in formulas],
        }

    @app.get("/api/indicators/mappings")
    def indicator_mappings_get(data_root: str = DEFAULT_DATA_ROOT) -> dict[str, Any]:
        service = DataManagementService(data_root)
        mappings = service.list_indicator_mappings()
        return {
            "data_root": data_root,
            "record_count": int(len(mappings)),
            "records": _records(mappings, limit=None),
        }

    @app.post("/api/indicators/mappings")
    def indicator_mapping_post(payload: schemas.IndicatorMappingPayload) -> dict[str, Any]:
        service = DataManagementService(payload.data_root)
        try:
            mapping = service.upsert_indicator_mapping(
                formula_id=payload.formula_id,
                stock_code=payload.stock_code,
                asset_type=payload.asset_type,
                timeframe=payload.timeframe,
                enabled=payload.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"data_root": payload.data_root, "mapping": mapping}

    @app.post("/api/indicators/compute")
    def indicator_compute_post(payload: schemas.IndicatorComputePayload) -> dict[str, Any]:
        service = DataManagementService(payload.data_root, adjust=payload.adjust)
        try:
            timeframe = normalize_timeframes([payload.timeframe])[0]
            symbols = normalize_symbol_tuple(payload.symbols)
            result = service.compute_indicators(
                symbols=symbols,
                formula_ids=payload.formula_ids,
                timeframe=timeframe,
                start=payload.start,
                end=payload.end,
                force=payload.force,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "data_root": payload.data_root,
            "adjust": payload.adjust,
            "timeframe": timeframe,
            "record_count": int(len(result)),
            "records": _records(result, limit=None),
        }
