from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import operator
from pathlib import Path
import re
import sqlite3
from typing import Any

import pandas as pd

from tdx_downloader.data.schema import (
    CANONICAL_COLUMNS,
    canonical_data_root,
    ensure_supported_timeframe,
    normalize_bars,
    normalize_symbol,
    parse_time_window,
    unique_symbols,
)
from tdx_downloader.data.storage import load_local_bars

INDICATOR_DB_FILE_NAME = "indicator_formulas.sqlite"
INDICATOR_VALUE_COLUMNS = ["date", "stock_code", "value"]
DEFAULT_INDICATOR_FORMULAS = (
    ("ma5", "MA5", "MA(CLOSE,5)", "builtin"),
    ("ma10", "MA10", "MA(CLOSE,10)", "builtin"),
    ("ma20", "MA20", "MA(CLOSE,20)", "builtin"),
)
FORMULA_ID_PATTERN = re.compile(r"[^a-z0-9_-]+")
TDX_COMMENT_PATTERN = re.compile(r"\{.*?\}|//.*?$", flags=re.MULTILINE | re.DOTALL)
ROLLING_PERIOD_PATTERN = re.compile(
    r"\b(?:MA|EMA|HHV|LLV|SUM|STD|REF)\s*\([^,]+,\s*([0-9]+)\s*\)",
    flags=re.IGNORECASE,
)
SINGLE_EQUALS_PATTERN = re.compile(r"(?<![<>=!])=(?!=)")


@dataclass(frozen=True)
class IndicatorFormula:
    formula_id: str
    name: str
    expression: str
    source: str = "custom"
    output_name: str = ""
    tdx_program: str = ""
    warmup_bars: int = 1
    formula_hash: str = ""
    created_at: str = ""
    updated_at: str = ""


class IndicatorStore:
    """SQLite-backed registry for indicator formulas and symbol/timeframe mappings."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = canonical_data_root(data_root)
        self.path = indicator_db_path_for(self.data_root)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)

    def ensure_default_formulas(self) -> None:
        for formula_id, name, expression, source in DEFAULT_INDICATOR_FORMULAS:
            formula = make_indicator_formula(
                formula_id=formula_id,
                name=name,
                expression=expression,
                source=source,
                output_name=name,
            )
            self.upsert_formula(formula)

    def upsert_formula(self, formula: IndicatorFormula) -> IndicatorFormula:
        normalized = normalize_indicator_formula(formula)
        now = utc_now_text()
        existing = self.get_formula(normalized.formula_id, ensure_defaults=False)
        created_at = existing.created_at if existing else now
        normalized = IndicatorFormula(
            formula_id=normalized.formula_id,
            name=normalized.name,
            expression=normalized.expression,
            source=normalized.source,
            output_name=normalized.output_name,
            tdx_program=normalized.tdx_program,
            warmup_bars=normalized.warmup_bars,
            formula_hash=normalized.formula_hash,
            created_at=created_at,
            updated_at=now,
        )
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            connection.execute(
                """
                INSERT INTO indicator_formulas (
                    formula_id, name, expression, source, output_name, tdx_program,
                    warmup_bars, formula_hash, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(formula_id) DO UPDATE SET
                    name=excluded.name,
                    expression=excluded.expression,
                    source=excluded.source,
                    output_name=excluded.output_name,
                    tdx_program=excluded.tdx_program,
                    warmup_bars=excluded.warmup_bars,
                    formula_hash=excluded.formula_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized.formula_id,
                    normalized.name,
                    normalized.expression,
                    normalized.source,
                    normalized.output_name,
                    normalized.tdx_program,
                    int(normalized.warmup_bars),
                    normalized.formula_hash,
                    normalized.created_at,
                    normalized.updated_at,
                ),
            )
            connection.commit()
        return normalized

    def import_tdx_formula_text(self, text: str, *, formula_id_prefix: str = "") -> list[IndicatorFormula]:
        formulas = parse_tdx_formula_text(text, formula_id_prefix=formula_id_prefix)
        imported: list[IndicatorFormula] = []
        for formula in formulas:
            imported.append(self.upsert_formula(formula))
        return imported

    def get_formula(self, formula_id: str, *, ensure_defaults: bool = True) -> IndicatorFormula | None:
        if ensure_defaults:
            self.ensure_default_formulas()
        normalized_id = normalize_formula_id(formula_id)
        if not normalized_id:
            return None
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            row = connection.execute(
                """
                SELECT formula_id, name, expression, source, output_name, tdx_program,
                       warmup_bars, formula_hash, created_at, updated_at
                FROM indicator_formulas
                WHERE formula_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        return _formula_from_row(row) if row else None

    def require_formulas(self, formula_ids: tuple[str, ...] | list[str]) -> list[IndicatorFormula]:
        self.ensure_default_formulas()
        formulas: list[IndicatorFormula] = []
        missing: list[str] = []
        for formula_id in normalize_formula_ids(formula_ids):
            formula = self.get_formula(formula_id, ensure_defaults=False)
            if formula is None:
                missing.append(formula_id)
            else:
                formulas.append(formula)
        if missing:
            raise ValueError(f"指标公式不存在：{','.join(missing)}。请先导入公式。")
        return formulas

    def list_formulas(self) -> pd.DataFrame:
        self.ensure_default_formulas()
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            return pd.read_sql_query(
                """
                SELECT formula_id, name, expression, source, output_name, warmup_bars,
                       formula_hash, created_at, updated_at
                FROM indicator_formulas
                ORDER BY source, formula_id
                """,
                connection,
            )

    def upsert_mapping(
        self,
        *,
        formula_id: str,
        stock_code: str = "",
        asset_type: str = "",
        timeframe: str = "",
        enabled: bool = True,
    ) -> dict[str, object]:
        formula = self.get_formula(formula_id, ensure_defaults=False)
        if formula is None:
            self.ensure_default_formulas()
            formula = self.get_formula(formula_id, ensure_defaults=False)
        if formula is None:
            raise ValueError(f"指标公式不存在：{formula_id}。")
        normalized_symbol = normalize_symbol(stock_code) if str(stock_code or "").strip() else ""
        normalized_timeframe = ensure_supported_timeframe(timeframe) if str(timeframe or "").strip() else ""
        normalized_asset_type = str(asset_type or "").strip().lower()
        mapping_id = _mapping_id(
            formula_id=formula.formula_id,
            stock_code=normalized_symbol,
            asset_type=normalized_asset_type,
            timeframe=normalized_timeframe,
        )
        updated_at = utc_now_text()
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            connection.execute(
                """
                INSERT INTO indicator_mappings (
                    mapping_id, formula_id, stock_code, asset_type, timeframe, enabled, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    mapping_id,
                    formula.formula_id,
                    normalized_symbol,
                    normalized_asset_type,
                    normalized_timeframe,
                    int(bool(enabled)),
                    updated_at,
                ),
            )
            connection.commit()
        return {
            "mapping_id": mapping_id,
            "formula_id": formula.formula_id,
            "stock_code": normalized_symbol,
            "asset_type": normalized_asset_type,
            "timeframe": normalized_timeframe,
            "enabled": bool(enabled),
            "updated_at": updated_at,
        }

    def list_mappings(self) -> pd.DataFrame:
        self.ensure_default_formulas()
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            return pd.read_sql_query(
                """
                SELECT mapping_id, formula_id, stock_code, asset_type, timeframe, enabled, updated_at
                FROM indicator_mappings
                ORDER BY formula_id, asset_type, stock_code, timeframe
                """,
                connection,
            )

    def mapped_formula_ids_for_symbol(self, *, symbol: str, asset_type: str = "", timeframe: str = "") -> tuple[str, ...]:
        self.ensure_default_formulas()
        normalized_symbol = normalize_symbol(symbol)
        normalized_asset_type = str(asset_type or "").strip().lower()
        normalized_timeframe = ensure_supported_timeframe(timeframe) if str(timeframe or "").strip() else ""
        with sqlite3.connect(self.path) as connection:
            _init_indicator_db(connection)
            rows = connection.execute(
                """
                SELECT formula_id
                FROM indicator_mappings
                WHERE enabled = 1
                  AND (stock_code = '' OR stock_code = ?)
                  AND (asset_type = '' OR asset_type = ?)
                  AND (timeframe = '' OR timeframe = ?)
                ORDER BY formula_id
                """,
                (normalized_symbol, normalized_asset_type, normalized_timeframe),
            ).fetchall()
        return tuple(dict.fromkeys(str(row[0]) for row in rows))


def indicator_db_path_for(data_root: str | Path) -> Path:
    return canonical_data_root(data_root) / "metadata" / INDICATOR_DB_FILE_NAME


def indicator_cache_path_for(
    data_root: str | Path,
    *,
    timeframe: str,
    adjust: str,
    formula_id: str,
    symbol: str,
) -> Path:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    normalized_formula_id = normalize_formula_id(formula_id)
    normalized_symbol = normalize_symbol(symbol)
    if not normalized_formula_id:
        raise ValueError("formula_id 不能为空。")
    if not normalized_symbol:
        raise ValueError("stock_code 不能为空。")
    return (
        canonical_data_root(data_root)
        / "indicators"
        / normalized_timeframe
        / str(adjust or "")
        / normalized_formula_id
        / f"{normalized_symbol}.parquet"
    )


def normalize_formula_id(value: object) -> str:
    text = str(value or "").strip().lower()
    text = FORMULA_ID_PATTERN.sub("_", text).strip("_")
    return text[:80]


def normalize_formula_ids(values: tuple[str, ...] | list[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    raw_items = str(values).replace("，", ",").replace("、", ",").split(",") if isinstance(values, str) else values
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        formula_id = normalize_formula_id(item)
        if not formula_id or formula_id in seen:
            continue
        seen.add(formula_id)
        result.append(formula_id)
    return tuple(result)


def make_indicator_formula(
    *,
    formula_id: str,
    name: str,
    expression: str,
    source: str = "custom",
    output_name: str = "",
    tdx_program: str = "",
) -> IndicatorFormula:
    normalized_id = normalize_formula_id(formula_id)
    if not normalized_id:
        raise ValueError("formula_id 不能为空。")
    expression_text = str(expression or "").strip()
    program_text = clean_tdx_formula_text(tdx_program)
    if not expression_text and not program_text:
        raise ValueError("指标公式表达式不能为空。")
    output = str(output_name or name or formula_id).strip()
    raw = "|".join([normalized_id, expression_text, program_text, output])
    formula_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return IndicatorFormula(
        formula_id=normalized_id,
        name=str(name or normalized_id).strip() or normalized_id,
        expression=expression_text,
        source=str(source or "custom").strip().lower() or "custom",
        output_name=output,
        tdx_program=program_text,
        warmup_bars=estimate_warmup_bars(program_text or expression_text),
        formula_hash=formula_hash,
    )


def normalize_indicator_formula(formula: IndicatorFormula) -> IndicatorFormula:
    return make_indicator_formula(
        formula_id=formula.formula_id,
        name=formula.name,
        expression=formula.expression,
        source=formula.source,
        output_name=formula.output_name,
        tdx_program=formula.tdx_program,
    )


def parse_tdx_formula_text(text: str, *, formula_id_prefix: str = "") -> list[IndicatorFormula]:
    program = clean_tdx_formula_text(text)
    if not program:
        raise ValueError("TDX 指标公式为空。")
    output_statements: list[tuple[str, str]] = []
    for statement in split_tdx_statements(program):
        operator = _tdx_assignment_operator(statement)
        if operator != ":":
            continue
        name, expression = statement.split(":", 1)
        output_name = name.strip()
        if not output_name:
            continue
        output_statements.append((output_name, expression.strip()))
    if not output_statements:
        raise ValueError("未识别到 TDX 输出指标。请使用 MA5:MA(CLOSE,5); 这类输出语句。")

    formulas: list[IndicatorFormula] = []
    prefix = normalize_formula_id(formula_id_prefix)
    for output_name, expression in output_statements:
        formula_id = normalize_formula_id(f"{prefix}_{output_name}" if prefix else output_name)
        formulas.append(
            make_indicator_formula(
                formula_id=formula_id,
                name=output_name,
                expression=expression,
                source="tdx",
                output_name=output_name,
                tdx_program=program,
            )
        )
    return formulas


def clean_tdx_formula_text(text: str) -> str:
    cleaned = TDX_COMMENT_PATTERN.sub("", str(text or ""))
    cleaned = cleaned.replace("：", ":").replace("，", ",").replace("\r", "\n")
    return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())


def split_tdx_statements(program: str) -> list[str]:
    return [part.strip() for part in str(program or "").replace("\n", ";").split(";") if part.strip()]


def estimate_warmup_bars(expression: str) -> int:
    periods = [int(match.group(1)) for match in ROLLING_PERIOD_PATTERN.finditer(str(expression or ""))]
    return max(periods, default=1)


def compute_indicator_cache(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: tuple[str, ...] | list[str],
    formula_ids: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    force: bool = False,
) -> pd.DataFrame:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    normalized_symbols = unique_symbols(tuple(symbols))
    normalized_formula_ids = normalize_formula_ids(list(formula_ids))
    if not normalized_symbols:
        raise ValueError("symbols 不能为空。")
    if not normalized_formula_ids:
        raise ValueError("formula_ids 不能为空。")
    start_ts, end_ts = parse_time_window(start, end)
    store = IndicatorStore(data_root)
    formulas = store.require_formulas(normalized_formula_ids)
    rows: list[dict[str, object]] = []
    for symbol in normalized_symbols:
        price_path = _price_cache_path_for(data_root, timeframe=normalized_timeframe, adjust=adjust, symbol=symbol)
        if not price_path.exists():
            for formula in formulas:
                rows.append(_compute_result_row(formula, symbol, normalized_timeframe, adjust, status="missing_price", path="", message="价格缓存不存在。"))
            continue
        for formula in formulas:
            rows.append(
                _ensure_formula_cache(
                    data_root=data_root,
                    adjust=adjust,
                    timeframe=normalized_timeframe,
                    symbol=symbol,
                    formula=formula,
                    price_path=price_path,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    force=force,
                )
            )
    return pd.DataFrame(rows)


def load_indicator_values(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbols: tuple[str, ...] | list[str],
    formula_ids: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    normalized_symbols = unique_symbols(tuple(symbols))
    normalized_formula_ids = normalize_formula_ids(list(formula_ids))
    start_ts, end_ts = parse_time_window(start, end)
    frames: list[pd.DataFrame] = []
    for formula_id in normalized_formula_ids:
        formula_frames: list[pd.DataFrame] = []
        for symbol in normalized_symbols:
            path = indicator_cache_path_for(
                data_root,
                timeframe=timeframe,
                adjust=adjust,
                formula_id=formula_id,
                symbol=symbol,
            )
            if not path.exists():
                continue
            frame = pd.read_parquet(path, columns=list(INDICATOR_VALUE_COLUMNS))
            if frame.empty:
                continue
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
            frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
            frame = frame.loc[
                frame["stock_code"].eq(symbol) & frame["date"].between(start_ts, end_ts),
                ["date", "stock_code", "value"],
            ].copy()
            if not frame.empty:
                frame = frame.rename(columns={"value": formula_id})
                formula_frames.append(frame)
        if formula_frames:
            frames.append(pd.concat(formula_frames, ignore_index=True))
    if not frames:
        return pd.DataFrame(columns=pd.Index(["date", "stock_code", *normalized_formula_ids]))
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on=["date", "stock_code"], how="outer")
    return result.sort_values(["stock_code", "date"]).reset_index(drop=True)


def indicator_cache_inventory(data_root: str | Path) -> pd.DataFrame:
    root = canonical_data_root(data_root) / "indicators"
    columns = [
        "stock_code",
        "data_kind",
        "indicator",
        "timeframe",
        "adjust",
        "storage_format",
        "status",
        "rows",
        "start",
        "end",
        "file_size_bytes",
        "modified_at",
        "path",
        "message",
    ]
    if not root.exists():
        return pd.DataFrame(columns=pd.Index(columns))
    records: list[dict[str, object]] = []
    for path in root.glob("*/*/*/*.parquet"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
            timeframe, adjust, formula_id, filename = relative.parts
        except ValueError:
            continue
        symbol = normalize_symbol(Path(filename).stem)
        if not symbol:
            continue
        try:
            identity = pd.read_parquet(path, columns=["date", "stock_code"])
            identity["date"] = pd.to_datetime(identity["date"], errors="coerce")
            rows = len(identity)
            start_at = identity["date"].min() if rows else pd.NaT
            end_at = identity["date"].max() if rows else pd.NaT
            status = "cached" if rows else "empty"
            message = "指标缓存可用。" if rows else "指标缓存为空。"
        except Exception as exc:  # noqa: BLE001
            rows = 0
            start_at = pd.NaT
            end_at = pd.NaT
            status = "read_error"
            message = f"指标 parquet 读取失败：{exc}"
        stat = path.stat()
        records.append(
            {
                "stock_code": symbol,
                "data_kind": "indicator",
                "indicator": normalize_formula_id(formula_id),
                "timeframe": timeframe,
                "adjust": adjust,
                "storage_format": "parquet",
                "status": status,
                "rows": int(rows),
                "start": start_at,
                "end": end_at,
                "file_size_bytes": int(stat.st_size),
                "modified_at": pd.Timestamp(stat.st_mtime, unit="s"),
                "path": str(path),
                "message": message,
            }
        )
    return pd.DataFrame(records, columns=pd.Index(columns))


def evaluate_indicator_formula(formula: IndicatorFormula, bars: pd.DataFrame) -> pd.Series:
    frame = normalize_bars(bars)
    if frame.empty:
        return pd.Series(dtype="float64")
    context = _base_eval_context(frame)
    if formula.tdx_program:
        result = _evaluate_tdx_program(formula.tdx_program, output_name=formula.output_name, context=context, index=frame.index)
    else:
        result = _evaluate_expression(formula.expression, context=context, index=frame.index)
    if not isinstance(result, pd.Series):
        result = pd.Series([result] * len(frame), index=frame.index)
    return pd.to_numeric(result, errors="coerce")


def _ensure_formula_cache(
    *,
    data_root: str | Path,
    adjust: str,
    timeframe: str,
    symbol: str,
    formula: IndicatorFormula,
    price_path: Path,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    force: bool,
) -> dict[str, object]:
    cache_path = indicator_cache_path_for(
        data_root,
        timeframe=timeframe,
        adjust=adjust,
        formula_id=formula.formula_id,
        symbol=symbol,
    )
    sidecar_path = _indicator_sidecar_path(cache_path)
    price_mtime_ns = price_path.stat().st_mtime_ns
    if not force and _indicator_cache_is_fresh(
        cache_path=cache_path,
        sidecar_path=sidecar_path,
        formula=formula,
        price_mtime_ns=price_mtime_ns,
        start_ts=start_ts,
        end_ts=end_ts,
    ):
        return _cached_result_row(cache_path, formula=formula, symbol=symbol, timeframe=timeframe, adjust=adjust, status="cached", message="指标缓存已命中，未重复计算。")

    previous = _read_existing_indicator_cache(cache_path)
    if previous.empty or force:
        compute_start = pd.Timestamp("1900-01-01")
        preserved = pd.DataFrame(columns=pd.Index(INDICATOR_VALUE_COLUMNS))
    else:
        previous_dates = previous["date"].dropna().sort_values().drop_duplicates().reset_index(drop=True)
        if previous_dates.empty or start_ts < previous_dates.min():
            compute_start = pd.Timestamp("1900-01-01")
            preserved = pd.DataFrame(columns=pd.Index(INDICATOR_VALUE_COLUMNS))
        else:
            tail_index = max(0, len(previous_dates) - max(formula.warmup_bars * 2, formula.warmup_bars + 5))
            compute_start = pd.Timestamp(previous_dates.iloc[tail_index])
            preserved = previous.loc[previous["date"] < compute_start].copy()

    bars = load_local_bars(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=[symbol],
        start=compute_start,
        end=end_ts,
    )
    if bars.empty:
        return _compute_result_row(formula, symbol, timeframe, adjust, status="empty_price", path=str(cache_path), message="计算窗口内没有价格数据。")

    bars = bars.sort_values(["stock_code", "date"]).reset_index(drop=True)
    values = evaluate_indicator_formula(formula, bars)
    computed = bars.loc[:, ["date", "stock_code"]].copy()
    computed["value"] = values.to_numpy()
    merge_parts = [frame for frame in (preserved, computed) if not frame.empty]
    merged = pd.concat(merge_parts, ignore_index=True) if merge_parts else pd.DataFrame(columns=pd.Index(INDICATOR_VALUE_COLUMNS))
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged["stock_code"] = merged["stock_code"].map(normalize_symbol)
    merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
    merged = (
        merged.dropna(subset=["date", "stock_code"])
        .drop_duplicates(subset=["stock_code", "date"], keep="last")
        .sort_values(["stock_code", "date"])
        .reset_index(drop=True)
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    previous_rows = len(previous)
    merged.to_parquet(cache_path, index=False)
    _write_indicator_sidecar(
        sidecar_path,
        formula=formula,
        source_path=price_path,
        source_mtime_ns=price_mtime_ns,
        frame=merged,
        requested_start_ts=start_ts,
        requested_end_ts=end_ts,
    )
    return _compute_result_row(
        formula,
        symbol,
        timeframe,
        adjust,
        status="computed",
        path=str(cache_path),
        rows=len(merged),
        new_rows=max(len(merged) - previous_rows, 0),
        start=merged["date"].min(),
        end=merged["date"].max(),
        message="指标缓存已计算并写入。",
    )


def _indicator_cache_is_fresh(
    *,
    cache_path: Path,
    sidecar_path: Path,
    formula: IndicatorFormula,
    price_mtime_ns: int,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> bool:
    if not cache_path.exists() or not sidecar_path.exists():
        return False
    try:
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        requested_start = pd.Timestamp(metadata.get("requested_start_at") or metadata.get("start_at"))
        requested_end = pd.Timestamp(metadata.get("requested_end_at") or metadata.get("end_at"))
    except (OSError, ValueError, TypeError):
        return False
    if metadata.get("formula_hash") != formula.formula_hash:
        return False
    if int(metadata.get("source_mtime_ns") or 0) < int(price_mtime_ns):
        return False
    if pd.isna(requested_start) or pd.isna(requested_end):
        return False
    return bool(start_ts >= requested_start and end_ts <= requested_end)


def _read_existing_indicator_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=pd.Index(INDICATOR_VALUE_COLUMNS))
    frame = pd.read_parquet(path, columns=list(INDICATOR_VALUE_COLUMNS))
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna(subset=["date", "stock_code"]).reset_index(drop=True)


def _cached_result_row(
    path: Path,
    *,
    formula: IndicatorFormula,
    symbol: str,
    timeframe: str,
    adjust: str,
    status: str,
    message: str,
) -> dict[str, object]:
    frame = _read_existing_indicator_cache(path)
    return _compute_result_row(
        formula,
        symbol,
        timeframe,
        adjust,
        status=status,
        path=str(path),
        rows=len(frame),
        new_rows=0,
        start=frame["date"].min() if not frame.empty else None,
        end=frame["date"].max() if not frame.empty else None,
        message=message,
    )


def _compute_result_row(
    formula: IndicatorFormula,
    symbol: str,
    timeframe: str,
    adjust: str,
    *,
    status: str,
    path: str,
    rows: int = 0,
    new_rows: int = 0,
    start: object = None,
    end: object = None,
    message: str = "",
) -> dict[str, object]:
    return {
        "formula_id": formula.formula_id,
        "indicator": formula.formula_id,
        "stock_code": normalize_symbol(symbol),
        "timeframe": timeframe,
        "adjust": adjust,
        "status": status,
        "rows": int(rows),
        "new_rows": int(new_rows),
        "start": start,
        "end": end,
        "path": path,
        "message": message,
    }


def _write_indicator_sidecar(
    path: Path,
    *,
    formula: IndicatorFormula,
    source_path: Path,
    source_mtime_ns: int,
    frame: pd.DataFrame,
    requested_start_ts: pd.Timestamp,
    requested_end_ts: pd.Timestamp,
) -> None:
    payload = {
        "formula_id": formula.formula_id,
        "formula_hash": formula.formula_hash,
        "source_path": str(source_path),
        "source_mtime_ns": int(source_mtime_ns),
        "rows": int(len(frame)),
        "start_at": pd.Timestamp(frame["date"].min()).isoformat() if not frame.empty else "",
        "end_at": pd.Timestamp(frame["date"].max()).isoformat() if not frame.empty else "",
        "requested_start_at": requested_start_ts.isoformat(),
        "requested_end_at": requested_end_ts.isoformat(),
        "updated_at": utc_now_text(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _indicator_sidecar_path(path: Path) -> Path:
    return path.with_suffix(".json")


def _price_cache_path_for(data_root: str | Path, *, timeframe: str, adjust: str, symbol: str) -> Path:
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    dirname = "daily" if normalized_timeframe == "1d" else normalized_timeframe
    return canonical_data_root(data_root) / dirname / str(adjust or "") / f"{normalize_symbol(symbol)}.parquet"


def _base_eval_context(frame: pd.DataFrame) -> dict[str, Any]:
    context: dict[str, Any] = {}
    aliases = {
        "OPEN": "open",
        "O": "open",
        "HIGH": "high",
        "H": "high",
        "LOW": "low",
        "L": "low",
        "CLOSE": "close",
        "C": "close",
        "VOL": "volume",
        "V": "volume",
        "VOLUME": "volume",
        "AMOUNT": "amount",
        "AMO": "amount",
    }
    for alias, column in aliases.items():
        context[alias] = pd.to_numeric(frame[column], errors="coerce")
    return context


def _evaluate_tdx_program(program: str, *, output_name: str, context: dict[str, Any], index: pd.Index) -> Any:
    requested = str(output_name or "").strip().upper()
    local_context = dict(context)
    for statement in split_tdx_statements(program):
        operator = _tdx_assignment_operator(statement)
        if operator not in {":", ":="}:
            continue
        left, expression = statement.split(operator, 1)
        name = left.strip().upper()
        if not name:
            continue
        local_context[name] = _evaluate_expression(expression, context=local_context, index=index)
    if requested not in local_context:
        raise ValueError(f"TDX 公式未生成输出指标：{output_name}。")
    return local_context[requested]


def _tdx_assignment_operator(statement: str) -> str:
    if ":=" in statement:
        return ":="
    if ":" in statement:
        return ":"
    return ""


def _evaluate_expression(expression: str, *, context: dict[str, Any], index: pd.Index) -> Any:
    prepared = _prepare_python_expression(expression)
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"指标公式语法暂不支持：{expression}") from exc
    return _eval_ast(tree.body, context=context, index=index)


def _prepare_python_expression(expression: str) -> str:
    text = str(expression or "").strip().replace("&&", " and ").replace("||", " or ")
    return SINGLE_EQUALS_PATTERN.sub("==", text)


def _eval_ast(node: ast.AST, *, context: dict[str, Any], index: pd.Index) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        name = node.id.upper()
        if name not in context:
            raise ValueError(f"指标公式引用了未知变量：{node.id}")
        return context[name]
    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand, context=context, index=index)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left, context=context, index=index)
        right = _eval_ast(node.right, context=context, index=index)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        left = _eval_ast(node.left, context=context, index=index)
        right = _eval_ast(node.comparators[0], context=context, index=index)
        operation = _comparison_operator(node.ops[0])
        if operation is not None:
            return operation(_as_series(left, index), _as_series(right, index))
    if isinstance(node, ast.BoolOp):
        values = [_eval_ast(value, context=context, index=index) for value in node.values]
        result = values[0]
        for value in values[1:]:
            if isinstance(node.op, ast.And):
                result = result & value
            elif isinstance(node.op, ast.Or):
                result = result | value
            else:
                raise ValueError("指标公式布尔运算暂不支持。")
        return result
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("指标公式只支持普通函数调用。")
        name = node.func.id.upper()
        args = [_eval_ast(arg, context=context, index=index) for arg in node.args]
        return _call_indicator_function(name, args, index=index)
    raise ValueError(f"指标公式节点暂不支持：{type(node).__name__}")


def _call_indicator_function(name: str, args: list[Any], *, index: pd.Index) -> Any:
    if name == "MA":
        _require_arg_count(name, args, 2)
        return _as_series(args[0], index).rolling(_period(args[1]), min_periods=_period(args[1])).mean()
    if name == "EMA":
        _require_arg_count(name, args, 2)
        period = _period(args[1])
        return _as_series(args[0], index).ewm(span=period, adjust=False, min_periods=period).mean()
    if name == "REF":
        _require_arg_count(name, args, 2)
        return _as_series(args[0], index).shift(_period(args[1]))
    if name == "HHV":
        _require_arg_count(name, args, 2)
        period = _period(args[1])
        return _as_series(args[0], index).rolling(period, min_periods=period).max()
    if name == "LLV":
        _require_arg_count(name, args, 2)
        period = _period(args[1])
        return _as_series(args[0], index).rolling(period, min_periods=period).min()
    if name == "SUM":
        _require_arg_count(name, args, 2)
        period = _period(args[1])
        return _as_series(args[0], index).rolling(period, min_periods=period).sum()
    if name == "STD":
        _require_arg_count(name, args, 2)
        period = _period(args[1])
        return _as_series(args[0], index).rolling(period, min_periods=period).std()
    if name == "IF":
        _require_arg_count(name, args, 3)
        condition = _as_series(args[0], index).fillna(False).astype(bool)
        truthy = _as_series(args[1], index)
        falsy = _as_series(args[2], index)
        return truthy.where(condition, falsy)
    if name == "CROSS":
        _require_arg_count(name, args, 2)
        left = _as_series(args[0], index)
        right = _as_series(args[1], index)
        return ((left > right) & (left.shift(1) <= right.shift(1))).astype(float)
    if name == "ABS":
        _require_arg_count(name, args, 1)
        return _as_series(args[0], index).abs()
    if name == "MAX":
        _require_arg_count(name, args, 2)
        return pd.concat([_as_series(args[0], index), _as_series(args[1], index)], axis=1).max(axis=1)
    if name == "MIN":
        _require_arg_count(name, args, 2)
        return pd.concat([_as_series(args[0], index), _as_series(args[1], index)], axis=1).min(axis=1)
    raise ValueError(f"TDX 函数暂不支持：{name}")


def _comparison_operator(node: ast.cmpop) -> Any:
    if isinstance(node, ast.Gt):
        return operator.gt
    if isinstance(node, ast.GtE):
        return operator.ge
    if isinstance(node, ast.Lt):
        return operator.lt
    if isinstance(node, ast.LtE):
        return operator.le
    if isinstance(node, ast.Eq):
        return operator.eq
    if isinstance(node, ast.NotEq):
        return operator.ne
    return None


def _as_series(value: Any, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce")
    return pd.Series([value] * len(index), index=index, dtype="float64")


def _period(value: Any) -> int:
    if isinstance(value, pd.Series):
        value = value.dropna().iloc[0] if not value.dropna().empty else 0
    period = int(float(value))
    if period <= 0:
        raise ValueError("指标周期必须大于 0。")
    return period


def _require_arg_count(name: str, args: list[Any], expected: int) -> None:
    if len(args) != expected:
        raise ValueError(f"{name} 需要 {expected} 个参数。")


def _init_indicator_db(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS indicator_formulas (
            formula_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            expression TEXT NOT NULL,
            source TEXT NOT NULL,
            output_name TEXT NOT NULL,
            tdx_program TEXT NOT NULL,
            warmup_bars INTEGER NOT NULL,
            formula_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS indicator_mappings (
            mapping_id TEXT PRIMARY KEY,
            formula_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(formula_id) REFERENCES indicator_formulas(formula_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_indicator_mappings_lookup "
        "ON indicator_mappings(stock_code, asset_type, timeframe, enabled)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_indicator_mappings_formula "
        "ON indicator_mappings(formula_id, enabled)"
    )


def _formula_from_row(row: tuple[Any, ...]) -> IndicatorFormula:
    return IndicatorFormula(
        formula_id=str(row[0]),
        name=str(row[1]),
        expression=str(row[2]),
        source=str(row[3]),
        output_name=str(row[4]),
        tdx_program=str(row[5]),
        warmup_bars=int(row[6]),
        formula_hash=str(row[7]),
        created_at=str(row[8]),
        updated_at=str(row[9]),
    )


def _mapping_id(*, formula_id: str, stock_code: str, asset_type: str, timeframe: str) -> str:
    raw = "|".join([normalize_formula_id(formula_id), stock_code, asset_type, timeframe])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
