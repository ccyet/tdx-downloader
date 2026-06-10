from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import time as wall_time
from typing import Any

import pandas as pd

from tdx_downloader.data.catalog import catalog_path_for
from tdx_downloader.data.schema import TIMEFRAME_DIR_NAMES, normalize_symbol, unique_symbols

SYMBOL_METADATA_COLUMNS = ["stock_code", "stock_name", "source", "path"]
SYMBOL_METADATA_CACHE_VERSION = 1
DEFAULT_STOCK_NAME_BY_CODE = {
    "000001.SH": "上证指数",
    "000001.SZ": "平安银行",
    "000002.SZ": "万科A",
    "000003.SZ": "PT金田A",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000333.SZ": "美的集团",
    "000688.SH": "科创50",
    "000852.SH": "中证1000",
    "000905.SH": "中证500",
    "002415.SZ": "海康威视",
    "300059.SZ": "东方财富",
    "300750.SZ": "宁德时代",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "510300.SH": "沪深300ETF华泰柏",
    "510500.SH": "中证500ETF南方",
    "512100.SH": "中证1000ETF南方",
    "588000.SH": "科创50ETF华夏",
    "159915.SZ": "创业板ETF易方达",
    "600000.SH": "浦发银行",
    "600036.SH": "招商银行",
    "600519.SH": "贵州茅台",
    "601318.SH": "中国平安",
    "688001.SH": "华兴源创",
}


def load_symbol_metadata(
    data_root: str | Path,
    *,
    tdx_path: str | Path = "",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """加载股票代码和名称；优先使用 sidecar/TDX，本地 catalog 补缺失名称。"""
    frames = [_load_sidecar_symbol_metadata(data_root)]
    if tdx_path:
        frames.append(load_tdx_symbol_metadata(tdx_path, data_root=data_root, force_refresh=force_refresh))
    elif not force_refresh:
        cached = read_symbol_metadata_cache(data_root=data_root, tdx_path="")
        if cached is not None:
            frames.append(cached)
    frames.append(_load_catalog_symbol_metadata(data_root))
    return _merge_symbol_metadata(frames)


def resolve_symbol_names(
    symbols: list[str] | tuple[str, ...],
    *,
    data_root: str | Path | None = None,
    tdx_path: str | Path = "",
) -> dict[str, str]:
    """按标准代码返回股票名称；sidecar/TDX 覆盖默认常用代码表。"""
    requested = unique_symbols(tuple(symbols))
    names = {symbol: DEFAULT_STOCK_NAME_BY_CODE[symbol] for symbol in requested if symbol in DEFAULT_STOCK_NAME_BY_CODE}
    if data_root is not None:
        metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
        for row in metadata.itertuples(index=False):
            symbol = str(row.stock_code)
            if symbol in requested:
                names[symbol] = str(row.stock_name)
    return names


def load_tdx_symbol_metadata(
    tdx_path: str | Path,
    *,
    data_root: str | Path | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """从通达信 hq_cache 的 tnf 代码表读取股票名称。"""
    if data_root is not None and not force_refresh:
        cached = read_symbol_metadata_cache(data_root=data_root, tdx_path=tdx_path)
        if cached is not None:
            return cached
    rows: list[dict[str, object]] = []
    for path in _tdx_tnf_candidates(tdx_path):
        rows.extend(_read_tdx_tnf_file(path))
    metadata = _metadata_frame(rows)
    if data_root is not None:
        save_symbol_metadata_cache(data_root=data_root, tdx_path=tdx_path, metadata=metadata)
    return metadata


def read_symbol_metadata_cache(*, data_root: str | Path, tdx_path: str | Path) -> pd.DataFrame | None:
    payload = _read_symbol_metadata_cache_payload(data_root=data_root, tdx_path=tdx_path)
    if payload is None:
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    return _metadata_frame([record for record in records if isinstance(record, dict)])


def save_symbol_metadata_cache(
    *,
    data_root: str | Path,
    tdx_path: str | Path,
    metadata: pd.DataFrame,
) -> str:
    path = symbol_metadata_cache_path(data_root=data_root, tdx_path=tdx_path)
    frame = _metadata_frame(metadata.to_dict("records")) if not metadata.empty else _metadata_frame([])
    payload = {
        "version": SYMBOL_METADATA_CACHE_VERSION,
        "saved_at": wall_time(),
        "tdx_path": str(tdx_path),
        "record_count": int(len(frame)),
        "records": _metadata_records(frame),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        return str(exc)
    return ""


def symbol_metadata_cache_info(*, data_root: str | Path, tdx_path: str | Path) -> dict[str, Any]:
    path = symbol_metadata_cache_path(data_root=data_root, tdx_path=tdx_path)
    payload = _read_symbol_metadata_cache_payload(data_root=data_root, tdx_path=tdx_path)
    if payload is None:
        return {
            "hit": False,
            "path": str(path),
            "record_count": 0,
            "saved_at": None,
        }
    return {
        "hit": True,
        "path": str(path),
        "record_count": int(payload.get("record_count") or 0),
        "saved_at": payload.get("saved_at"),
    }


def symbol_metadata_cache_path(*, data_root: str | Path, tdx_path: str | Path) -> Path:
    key = {"version": SYMBOL_METADATA_CACHE_VERSION, "tdx_path": str(tdx_path).strip()}
    digest = sha256(json.dumps(key, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return Path(data_root).expanduser() / ".tdx_downloader" / "symbol_metadata" / f"{digest}.json"


def _load_sidecar_symbol_metadata(data_root: str | Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for path in _sidecar_symbol_files(data_root):
        rows.extend(_read_sidecar_symbol_file(path))
    return _metadata_frame(rows)


def _load_catalog_symbol_metadata(data_root: str | Path) -> pd.DataFrame:
    path = catalog_path_for(data_root)
    if not path.exists():
        return _metadata_frame([])
    sql = """
        SELECT stock_code, stock_name, status, end_at
        FROM market_data_files
        WHERE TRIM(stock_code) <> '' AND TRIM(stock_name) <> ''
        ORDER BY
            stock_code,
            CASE WHEN status IN ('cached', 'available', 'ok') THEN 0 ELSE 1 END,
            end_at DESC
    """
    with sqlite3.connect(path) as connection:
        frame = pd.read_sql_query(sql, connection)
    rows = [
        {"stock_code": row.stock_code, "stock_name": row.stock_name, "source": "catalog", "path": str(path)}
        for row in frame.itertuples(index=False)
    ]
    return _metadata_frame(rows).drop_duplicates(subset=["stock_code"], keep="first").reset_index(drop=True)


def _read_symbol_metadata_cache_payload(*, data_root: str | Path, tdx_path: str | Path) -> dict[str, Any] | None:
    path = symbol_metadata_cache_path(data_root=data_root, tdx_path=tdx_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("version") or 0) != SYMBOL_METADATA_CACHE_VERSION:
        return None
    return payload


def _metadata_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    cleaned = frame.loc[:, SYMBOL_METADATA_COLUMNS].astype(object).where(pd.notna(frame), None)
    return [dict(record) for record in cleaned.to_dict("records")]


def _sidecar_symbol_files(data_root: str | Path) -> list[Path]:
    roots = _metadata_roots(data_root)
    names = ("symbols.csv", "stock_names.csv", "symbol_names.csv")
    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for name in names:
            for path in (root / name, root / "metadata" / name):
                key = str(path)
                if key in seen or not path.exists():
                    continue
                seen.add(key)
                files.append(path)
    return files


def _metadata_roots(data_root: str | Path) -> list[Path]:
    root = Path(data_root).expanduser()
    candidates = [root]
    if root.name.lower() in set(TIMEFRAME_DIR_NAMES.values()):
        candidates.append(root.parent)
    candidates.extend(root.parents[:2])
    seen: set[str] = set()
    result: list[Path] = []
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _read_sidecar_symbol_file(path: Path) -> list[dict[str, object]]:
    frame = pd.read_csv(path)
    code_column = _first_existing_column(frame, ("stock_code", "symbol", "code", "代码", "证券代码"))
    name_column = _first_existing_column(frame, ("stock_name", "name", "名称", "证券名称", "股票名称"))
    if not code_column or not name_column:
        raise ValueError(f"股票名称文件缺少代码或名称列：{path}")
    rows: list[dict[str, object]] = []
    for raw_code, raw_name in zip(frame[code_column], frame[name_column], strict=False):
        symbol = normalize_symbol(raw_code)
        name = _clean_text(raw_name)
        if not symbol or not name:
            continue
        rows.append({"stock_code": symbol, "stock_name": name, "source": "sidecar_csv", "path": str(path)})
    return rows


def _first_existing_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    normalized = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        found = normalized.get(candidate.lower())
        if found is not None:
            return found
    return ""


def _tdx_tnf_candidates(tdx_path: str | Path) -> list[Path]:
    base = Path(tdx_path).expanduser()
    if base.is_file() and base.suffix.lower() == ".tnf":
        return [base]
    candidates: list[Path] = []
    roots = [base, *base.parents]
    for root in roots:
        for folder in (root / "T0002" / "hq_cache", root / "hq_cache"):
            for name in ("shs.tnf", "szs.tnf", "bjs.tnf", "shm.tnf", "szm.tnf", "bjm.tnf"):
                path = folder / name
                if path.exists():
                    candidates.append(path)
    return _unique_paths(candidates)


def _read_tdx_tnf_file(path: Path) -> list[dict[str, object]]:
    payload = path.read_bytes()
    if len(payload) <= 50:
        return []
    exchange = _tdx_exchange_from_filename(path.name)
    rows: list[dict[str, object]] = []
    record_size = _tdx_tnf_record_size(payload)
    for offset in range(50, len(payload), record_size):
        record = payload[offset : offset + record_size]
        if len(record) < record_size:
            continue
        code = _decode_record_field(record[0:6], encoding="ascii")
        if not code.isdigit():
            continue
        symbol = normalize_symbol(f"{code}.{exchange}") if exchange else normalize_symbol(code)
        name = _tdx_record_name(record)
        if not symbol or not name:
            continue
        rows.append({"stock_code": symbol, "stock_name": name, "source": "tdx_tnf", "path": str(path)})
    return rows


def _tdx_tnf_record_size(payload: bytes) -> int:
    if (len(payload) - 50) % 360 == 0:
        return 360
    return 314


def _tdx_exchange_from_filename(name: str) -> str:
    lower = name.lower()
    if lower.startswith("sh"):
        return "SH"
    if lower.startswith("sz"):
        return "SZ"
    if lower.startswith("bj"):
        return "BJ"
    return ""


def _tdx_record_name(record: bytes) -> str:
    candidates = [
        _decode_record_field(record[31:47]),
        _decode_record_field(record[31:63]),
        _decode_record_field(record[23:31]),
        _decode_record_field(record[23:39]),
        _decode_record_field(record[6:14]),
        _decode_record_field(record[6:24]),
    ]
    names = [name for name in candidates if _looks_like_stock_name(name)]
    return max(names, key=len) if names else ""


def _decode_record_field(raw: bytes, *, encoding: str = "gbk") -> str:
    value = raw.split(b"\x00", 1)[0].strip()
    if not value:
        return ""
    encodings = (encoding,) if encoding == "ascii" else ("gbk", "utf-8")
    for item in encodings:
        try:
            return _clean_text(value.decode(item, errors="ignore"))
        except UnicodeDecodeError:
            continue
    return ""


def _looks_like_stock_name(value: str) -> bool:
    if not value or value.isdigit():
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in value) or any(char.isalpha() for char in value)


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\x00", "").strip()
    return "".join(char for char in text if char.isprintable()).strip()


def _merge_symbol_metadata(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _metadata_frame([])
    merged = pd.concat(non_empty, ignore_index=True)
    return (
        merged.drop_duplicates(subset=["stock_code"], keep="first")
        .sort_values("stock_code", kind="mergesort")
        .reset_index(drop=True)
    )


def _metadata_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=pd.Index(SYMBOL_METADATA_COLUMNS))
    frame = pd.DataFrame(rows, columns=SYMBOL_METADATA_COLUMNS)
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    frame["stock_name"] = frame["stock_name"].map(_clean_text)
    frame = frame.loc[frame["stock_code"].ne("") & frame["stock_name"].ne("")]
    return frame.loc[:, SYMBOL_METADATA_COLUMNS].reset_index(drop=True)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result
