from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from tdx_downloader.data.filters import limit_open_dates
from tdx_downloader.data.schema import (
    CANONICAL_COLUMNS,
    ensure_supported_timeframe,
    inclusive_end_timestamp,
    normalize_bars,
    normalize_symbol,
    parse_time_window,
    resolve_timeframe_root,
    unique_symbols,
)


AUDIT_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "status",
    "exists",
    "rows_total",
    "rows_in_window",
    "expected_rows",
    "missing_rows",
    "coverage_ratio",
    "max_missing_gap_minutes",
    "first_missing_at",
    "last_missing_at",
    "max_missing_gap_start_at",
    "max_missing_gap_end_at",
    "start",
    "end",
    "requested_start",
    "requested_end",
    "invalid_date_rows",
    "invalid_symbol_rows",
    "duplicate_rows",
    "null_ohlc_rows",
    "non_positive_price_rows",
    "inconsistent_ohlc_rows",
    "null_volume_amount_rows",
    "zero_volume_amount_rows",
    "negative_volume_amount_rows",
    "missing_columns",
    "path",
    "message",
]

DATA_GAP_EPISODE_COLUMNS = [
    "stock_code",
    "timeframe",
    "adjust",
    "gap_no",
    "start_at",
    "end_at",
    "missing_rows",
    "gap_minutes",
    "previous_available_at",
    "next_available_at",
    "requested_start",
    "requested_end",
    "path",
    "status",
]

LIMIT_FILTER_AUDIT_COLUMNS = [
    "stock_code",
    "status",
    "filter_enabled",
    "daily_rows",
    "filtered_days",
    "message",
]

DAILY_FILTER_AUDIT_STATUS_BY_DATA_STATUS = {
    "read_error": "daily_read_error",
    "missing_columns": "daily_missing_columns",
    "quality_error": "daily_quality_error",
}
DAILY_FILTER_AUDIT_MESSAGE_BY_DATA_STATUS = {
    "read_error": "日K parquet 读取失败",
    "missing_columns": "日K parquet 缺少标准字段",
    "quality_error": "日K parquet 存在质量异常",
}
TDX_SECTOR_INDEX_PREFIX = "880"
DATASET_AUDIT_SYMBOL_THRESHOLD = 200


def audit_local_data(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]] | None = None,
) -> pd.DataFrame:
    """审计本地 parquet 覆盖和 OHLC 质量；回测前用它显式暴露缺口。"""
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    start_ts, end_ts = _audit_window_for_timeframe(timeframe, start=start, end=end)
    normalized_symbols = unique_symbols(tuple(symbols))
    if len(normalized_symbols) >= DATASET_AUDIT_SYMBOL_THRESHOLD:
        if ensure_supported_timeframe(timeframe) == "1d":
            daily_rows = _audit_daily_symbol_files_dataset(
                root=root,
                symbols=normalized_symbols,
                timeframe=timeframe,
                adjust=adjust,
                start_ts=start_ts,
                end_ts=end_ts,
                expected_sessions_by_symbol=expected_sessions_by_symbol or {},
            )
            if daily_rows is not None:
                return pd.DataFrame(daily_rows, columns=AUDIT_COLUMNS)
        dataset_rows = _audit_symbol_files_dataset(
            root=root,
            symbols=normalized_symbols,
            timeframe=timeframe,
            adjust=adjust,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions_by_symbol=expected_sessions_by_symbol or {},
        )
        if dataset_rows is not None:
            return pd.DataFrame(dataset_rows, columns=AUDIT_COLUMNS)
    rows = [
        _audit_symbol_file(
            root=root,
            symbol=symbol,
            timeframe=timeframe,
            adjust=adjust,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions=(expected_sessions_by_symbol or {}).get(symbol),
        )
        for symbol in normalized_symbols
    ]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def data_gap_episodes(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]] | None = None,
) -> pd.DataFrame:
    """输出连续缺失 K 段，便于用户直接定位要补哪一段缓存。"""
    normalized_timeframe = ensure_supported_timeframe(timeframe)
    root = resolve_timeframe_root(data_root, normalized_timeframe) / adjust
    start_ts, end_ts = _audit_window_for_timeframe(normalized_timeframe, start=start, end=end)
    rows: list[dict[str, object]] = []
    for symbol in unique_symbols(tuple(symbols)):
        rows.extend(
            _symbol_gap_episodes(
                root=root,
                symbol=symbol,
                timeframe=normalized_timeframe,
                adjust=adjust,
                start_ts=start_ts,
                end_ts=end_ts,
                expected_sessions=(expected_sessions_by_symbol or {}).get(symbol),
            )
        )
    return pd.DataFrame(rows, columns=DATA_GAP_EPISODE_COLUMNS)


def daily_sessions_by_symbol(
    daily_bars: pd.DataFrame,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> dict[str, list[pd.Timestamp]]:
    daily = normalize_bars(daily_bars)
    if daily.empty:
        return {}
    start_day = pd.Timestamp(start).normalize()
    end_day = inclusive_end_timestamp(end).normalize()
    window = daily.loc[daily["date"].dt.normalize().between(start_day, end_day)].copy()
    if window.empty:
        return {}
    window["session_date"] = window["date"].dt.normalize()
    return {
        str(symbol): sorted(group["session_date"].dropna().drop_duplicates().tolist())
        for symbol, group in window.groupby("stock_code", sort=False)
    }


def limit_open_filter_audit(
    daily_bars: pd.DataFrame,
    *,
    symbols: tuple[str, ...] | list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    filter_enabled: bool,
    blocked: pd.DataFrame,
    daily_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    daily = normalize_bars(daily_bars)
    start_day = pd.Timestamp(start).normalize()
    end_day = inclusive_end_timestamp(end).normalize()
    window = daily.loc[daily["date"].dt.normalize().between(start_day, end_day)].copy() if not daily.empty else daily
    blocked_frame = blocked.copy() if not blocked.empty else pd.DataFrame(columns=["stock_code", "session_date"])
    audit_by_symbol = _daily_audit_by_symbol(daily_audit)
    rows = [
        _limit_open_filter_audit_row(
            symbol=symbol,
            window=window,
            blocked=blocked_frame,
            filter_enabled=filter_enabled,
            daily_audit_row=audit_by_symbol.get(symbol),
        )
        for symbol in unique_symbols(tuple(symbols))
    ]
    return pd.DataFrame(rows, columns=LIMIT_FILTER_AUDIT_COLUMNS)


def limit_open_dates_in_window(
    daily_bars: pd.DataFrame,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    blocked = limit_open_dates(daily_bars)
    if blocked.empty:
        return blocked
    start_day = pd.Timestamp(start).normalize()
    end_day = inclusive_end_timestamp(end).normalize()
    result = blocked.copy()
    result["session_date"] = pd.to_datetime(result["session_date"], errors="coerce").dt.normalize()
    return result.loc[result["session_date"].between(start_day, end_day)].reset_index(drop=True)


def _audit_window_for_timeframe(
    timeframe: str,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """日 K 审计按自然日覆盖，分钟审计保留调用方给定的盘中窗口。"""
    start_ts, end_ts = parse_time_window(start, end)
    if ensure_supported_timeframe(timeframe) == "1d":
        return start_ts.normalize(), end_ts.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return start_ts, end_ts


def _audit_symbol_file(
    *,
    root: Path,
    symbol: str,
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None = None,
) -> dict[str, object]:
    path = root / f"{symbol}.parquet"
    base = {
        "stock_code": symbol,
        "timeframe": timeframe,
        "adjust": adjust,
        "exists": path.exists(),
        "requested_start": start_ts,
        "requested_end": end_ts,
        "path": str(path),
    }
    if not path.exists():
        return _audit_record(base, status="missing_file", message="本地 parquet 不存在。")
    try:
        parquet_file = pq.ParquetFile(path)
    except Exception as exc:  # noqa: BLE001
        return _audit_record(base, status="read_error", message=f"parquet 元数据读取失败：{exc}")

    missing_columns = sorted(set(CANONICAL_COLUMNS).difference(parquet_file.schema.names))
    if missing_columns:
        return _audit_record(
            base,
            status="missing_columns",
            rows_total=_parquet_num_rows(parquet_file),
            missing_columns=",".join(missing_columns),
            message="缺少标准行情字段。",
        )
    try:
        raw = _read_canonical_window(path, start_ts=start_ts, end_ts=end_ts)
    except Exception as exc:  # noqa: BLE001
        return _audit_record(base, status="read_error", message=f"parquet 读取失败：{exc}")

    return _audit_symbol_frame(
        raw,
        base=base,
        symbol=symbol,
        timeframe=timeframe,
        adjust=adjust,
        start_ts=start_ts,
        end_ts=end_ts,
        rows_total=_parquet_num_rows(parquet_file),
        expected_sessions=expected_sessions,
    )


def _audit_symbol_files_dataset(
    *,
    root: Path,
    symbols: list[str],
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]],
) -> list[dict[str, object]] | None:
    try:
        dataset = ds.dataset(root, format="parquet") if root.exists() else None
    except Exception:  # noqa: BLE001
        return None

    if dataset is not None and sorted(set(CANONICAL_COLUMNS).difference(dataset.schema.names)):
        return None

    try:
        rows_total_by_symbol = _dataset_rows_total_by_symbol(dataset) if dataset is not None else {}
    except Exception:  # noqa: BLE001
        return None

    file_info: dict[str, tuple[dict[str, object], int | None, dict[str, object] | None]] = {}
    for symbol in symbols:
        path = root / f"{symbol}.parquet"
        base = {
            "stock_code": symbol,
            "timeframe": timeframe,
            "adjust": adjust,
            "exists": path.exists(),
            "requested_start": start_ts,
            "requested_end": end_ts,
            "path": str(path),
        }
        if not path.exists():
            file_info[symbol] = (base, None, _audit_record(base, status="missing_file", message="本地 parquet 不存在。"))
            continue
        rows_total = rows_total_by_symbol.get(symbol)
        if rows_total is None:
            return None
        file_info[symbol] = (base, rows_total, None)

    try:
        raw = _read_canonical_dataset_window(dataset, start_ts=start_ts, end_ts=end_ts)
    except Exception:  # noqa: BLE001
        return None

    requested = set(symbols)
    if raw.empty:
        raw_by_symbol: dict[str, pd.DataFrame] = {}
    else:
        raw = raw.copy()
        raw["stock_code"] = raw["stock_code"].map(normalize_symbol)
        raw = raw.loc[raw["stock_code"].isin(requested)]
        raw_by_symbol = {str(symbol): frame.copy() for symbol, frame in raw.groupby("stock_code", sort=False)}

    rows: list[dict[str, object]] = []
    empty = pd.DataFrame(columns=list(CANONICAL_COLUMNS))
    for symbol in symbols:
        base, rows_total, error = file_info[symbol]
        if error is not None:
            rows.append(error)
            continue
        rows.append(
            _audit_symbol_frame(
                raw_by_symbol.get(symbol, empty),
                base=base,
                symbol=symbol,
                timeframe=timeframe,
                adjust=adjust,
                start_ts=start_ts,
                end_ts=end_ts,
                rows_total=int(rows_total or 0),
                expected_sessions=expected_sessions_by_symbol.get(symbol),
            )
        )
    return rows


def _audit_daily_symbol_files_dataset(
    *,
    root: Path,
    symbols: list[str],
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]],
) -> list[dict[str, object]] | None:
    try:
        dataset = ds.dataset(root, format="parquet") if root.exists() else None
    except Exception:  # noqa: BLE001
        return None
    if dataset is not None and sorted(set(CANONICAL_COLUMNS).difference(dataset.schema.names)):
        return None
    try:
        rows_total_by_symbol = _dataset_rows_total_by_symbol(dataset) if dataset is not None else {}
        raw = _read_canonical_dataset_window(dataset, start_ts=start_ts, end_ts=end_ts)
    except Exception:  # noqa: BLE001
        return None

    requested = set(symbols)
    if raw.empty:
        window = pd.DataFrame(columns=list(CANONICAL_COLUMNS))
    else:
        window = raw.copy()
        window["stock_code"] = window["stock_code"].map(normalize_symbol)
        window["date"] = pd.to_datetime(window["date"], errors="coerce")
        for column in ["open", "high", "low", "close", "volume", "amount"]:
            window[column] = pd.to_numeric(window[column], errors="coerce")
        window = window.loc[window["stock_code"].isin(requested) & window["date"].between(start_ts, end_ts)].copy()

    tradable = _drop_zero_liquidity_bars(window)
    rows_in_window = _group_size(tradable)
    start_by_symbol = _group_min(tradable, "date")
    end_by_symbol = _group_max(tradable, "date")
    actual_dates = _group_date_sets(tradable)
    expected_dates = _expected_date_sets_for_symbols(
        symbols,
        expected_sessions_by_symbol,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    duplicate_rows = _group_mask_sum(window, window.duplicated(subset=["stock_code", "date"]) if not window.empty else None)
    null_ohlc_rows = _group_mask_sum(window, window[["open", "high", "low", "close"]].isna().any(axis=1) if not window.empty else None)
    non_positive_price_rows = _group_mask_sum(
        window,
        (window[["open", "high", "low", "close"]] <= 0).any(axis=1) if not window.empty else None,
    )
    inconsistent_ohlc_rows = _group_mask_sum(
        window,
        _inconsistent_ohlc_mask(window, require_positive=not _adjust_allows_non_positive_prices(adjust))
        if not window.empty
        else None,
    )
    null_volume_amount_rows = _group_mask_sum(
        window,
        window[["volume", "amount"]].isna().any(axis=1) if not window.empty else None,
    )
    zero_volume_amount_rows = _group_mask_sum(
        window,
        window[["volume", "amount"]].eq(0).any(axis=1) if not window.empty else None,
    )
    negative_volume_amount_rows = _group_mask_sum(
        window,
        (window[["volume", "amount"]] < 0).any(axis=1) if not window.empty else None,
    )

    rows: list[dict[str, object]] = []
    for symbol in symbols:
        path = root / f"{symbol}.parquet"
        base = {
            "stock_code": symbol,
            "timeframe": timeframe,
            "adjust": adjust,
            "exists": path.exists(),
            "requested_start": start_ts,
            "requested_end": end_ts,
            "path": str(path),
        }
        if not path.exists():
            rows.append(_audit_record(base, status="missing_file", message="本地 parquet 不存在。"))
            continue
        rows_total = int(rows_total_by_symbol.get(symbol, 0))
        symbol_expected = expected_dates.get(symbol, set())
        symbol_actual = actual_dates.get(symbol, set())
        coverage = _daily_coverage_from_sets(symbol_expected, symbol_actual)
        quality_error = _daily_fast_quality_error(
            symbol=symbol,
            adjust=adjust,
            duplicate_rows=duplicate_rows.get(symbol, 0),
            null_ohlc_rows=null_ohlc_rows.get(symbol, 0),
            non_positive_price_rows=non_positive_price_rows.get(symbol, 0),
            inconsistent_ohlc_rows=inconsistent_ohlc_rows.get(symbol, 0),
            null_volume_amount_rows=null_volume_amount_rows.get(symbol, 0),
            negative_volume_amount_rows=negative_volume_amount_rows.get(symbol, 0),
        )
        is_tdx_sector_index = _is_tdx_sector_index(symbol)
        relaxed_non_positive_price_rows = (
            non_positive_price_rows.get(symbol, 0)
            if is_tdx_sector_index or _adjust_allows_non_positive_prices(adjust)
            else 0
        )
        relaxed_ohlc_rows = inconsistent_ohlc_rows.get(symbol, 0) if is_tdx_sector_index else 0
        if quality_error:
            status = "quality_error"
            message = "存在日期或标的代码异常、重复时间、非法价格、OHLC 高低点不一致或量能字段异常。"
        elif rows_in_window.get(symbol, 0) <= 0:
            status = "no_window_data"
            message = "请求窗口内无数据。"
        elif zero_volume_amount_rows.get(symbol, 0) > 0:
            status = "ok"
            message = "覆盖按可交易 K 计算；存在零流动性 K，已从回测数据包剔除。"
        elif is_tdx_sector_index and relaxed_non_positive_price_rows > 0:
            status = "ok"
            message = "非常规板块指数使用通达信统计口径，已标记缓存并跳过价格语义门禁；其他质量检查通过。"
        elif relaxed_ohlc_rows > 0:
            status = "ok"
            message = "非常规板块指数使用通达信统计口径，已标记缓存并跳过 OHLC 高低点语义校验；其他质量检查通过。"
        elif _adjust_allows_non_positive_prices(adjust) and relaxed_non_positive_price_rows > 0:
            status = "ok"
            message = "前复权价格允许历史调整后价格小于等于 0，已记录但不阻断；其他质量检查通过。"
        else:
            status = "ok"
            message = "覆盖和质量检查通过。"
        rows.append(
            _audit_record(
                base,
                status=status,
                rows_total=rows_total,
                rows_in_window=rows_in_window.get(symbol, 0),
                **coverage,
                start=start_by_symbol.get(symbol, pd.NaT),
                end=end_by_symbol.get(symbol, pd.NaT),
                duplicate_rows=duplicate_rows.get(symbol, 0),
                null_ohlc_rows=null_ohlc_rows.get(symbol, 0),
                non_positive_price_rows=non_positive_price_rows.get(symbol, 0),
                inconsistent_ohlc_rows=inconsistent_ohlc_rows.get(symbol, 0),
                null_volume_amount_rows=null_volume_amount_rows.get(symbol, 0),
                zero_volume_amount_rows=zero_volume_amount_rows.get(symbol, 0),
                negative_volume_amount_rows=negative_volume_amount_rows.get(symbol, 0),
                message=message,
            )
        )
    return rows


def _audit_symbol_frame(
    raw: pd.DataFrame,
    *,
    base: dict[str, object],
    symbol: str,
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    rows_total: int,
    expected_sessions: Sequence[pd.Timestamp] | None,
) -> dict[str, object]:
    checked = raw.copy()
    checked["stock_code"] = checked["stock_code"].map(normalize_symbol)
    checked["date"] = pd.to_datetime(checked["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        checked[column] = pd.to_numeric(checked[column], errors="coerce")
    invalid_date_rows = int(checked["date"].isna().sum())
    window = checked.loc[checked["date"].between(start_ts, end_ts)].copy()
    invalid_symbol_rows = int(window["stock_code"].eq("").sum())
    duplicate_rows = int(window.duplicated(subset=["stock_code", "date"]).sum())
    null_ohlc_rows = int(window[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    allow_adjusted_non_positive_prices = _adjust_allows_non_positive_prices(adjust)
    non_positive_price_rows = int((window[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    inconsistent_ohlc_rows = int(
        _inconsistent_ohlc_mask(window, require_positive=not allow_adjusted_non_positive_prices).sum()
    )
    is_tdx_sector_index = _is_tdx_sector_index(symbol)
    relaxed_non_positive_price_rows = (
        non_positive_price_rows if is_tdx_sector_index or allow_adjusted_non_positive_prices else 0
    )
    relaxed_ohlc_rows = inconsistent_ohlc_rows if is_tdx_sector_index else 0
    null_volume_amount_rows = int(window[["volume", "amount"]].isna().any(axis=1).sum())
    zero_volume_amount_rows = int(window[["volume", "amount"]].eq(0).any(axis=1).sum())
    negative_volume_amount_rows = int((window[["volume", "amount"]] < 0).any(axis=1).sum())
    quality_issue_messages = _quality_issue_messages(
        checked=checked,
        window=window,
        adjust=adjust,
        symbol=symbol,
    )

    normalized = normalize_bars(raw, symbol)
    raw_in_window = normalized.loc[normalized["date"].between(start_ts, end_ts)]
    in_window = _drop_zero_liquidity_bars(raw_in_window)
    coverage = _intraday_session_coverage(
        in_window,
        timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
    )
    quality_error = bool(quality_issue_messages)
    if quality_error:
        status = "quality_error"
        message = (
            "存在日期或标的代码异常、重复时间、非法价格、OHLC 高低点不一致或量能字段异常。"
            f"首个异常：{quality_issue_messages[0]}"
        )
    elif in_window.empty:
        status = "no_window_data"
        message = "请求窗口内无数据。"
    elif zero_volume_amount_rows > 0:
        status = "ok"
        message = "覆盖按可交易 K 计算；存在零流动性 K，已从回测数据包剔除。"
    elif is_tdx_sector_index and relaxed_non_positive_price_rows > 0:
        status = "ok"
        message = "非常规板块指数使用通达信统计口径，已标记缓存并跳过价格语义门禁；其他质量检查通过。"
    elif relaxed_ohlc_rows > 0:
        status = "ok"
        message = "非常规板块指数使用通达信统计口径，已标记缓存并跳过 OHLC 高低点语义校验；其他质量检查通过。"
    elif allow_adjusted_non_positive_prices and relaxed_non_positive_price_rows > 0:
        status = "ok"
        message = "前复权价格允许历史调整后价格小于等于 0，已记录但不阻断；其他质量检查通过。"
    else:
        status = "ok"
        message = "覆盖和质量检查通过。"
    return _audit_record(
        base,
        status=status,
        rows_total=rows_total,
        rows_in_window=len(in_window),
        **coverage,
        start=in_window["date"].min() if not in_window.empty else pd.NaT,
        end=in_window["date"].max() if not in_window.empty else pd.NaT,
        invalid_date_rows=invalid_date_rows,
        invalid_symbol_rows=invalid_symbol_rows,
        duplicate_rows=duplicate_rows,
        null_ohlc_rows=null_ohlc_rows,
        non_positive_price_rows=non_positive_price_rows,
        inconsistent_ohlc_rows=inconsistent_ohlc_rows,
        null_volume_amount_rows=null_volume_amount_rows,
        zero_volume_amount_rows=zero_volume_amount_rows,
        negative_volume_amount_rows=negative_volume_amount_rows,
        message=message,
    )


def _symbol_gap_episodes(
    *,
    root: Path,
    symbol: str,
    timeframe: str,
    adjust: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None = None,
) -> list[dict[str, object]]:
    path = root / f"{symbol}.parquet"
    base = {
        "stock_code": symbol,
        "timeframe": timeframe,
        "adjust": adjust,
        "requested_start": start_ts,
        "requested_end": end_ts,
        "path": str(path),
    }
    if not path.exists():
        return _gap_episodes_for_dates(
            pd.DataFrame(columns=["date"]),
            timeframe,
            expected_sessions=expected_sessions,
            start_ts=start_ts,
            end_ts=end_ts,
            base=base,
            status="missing_file",
        )
    try:
        parquet_file = pq.ParquetFile(path)
    except Exception:  # noqa: BLE001
        return []
    if sorted(set(CANONICAL_COLUMNS).difference(parquet_file.schema.names)):
        return _gap_episodes_for_dates(
            pd.DataFrame(columns=["date"]),
            timeframe,
            expected_sessions=expected_sessions,
            start_ts=start_ts,
            end_ts=end_ts,
            base=base,
            status="missing_columns",
        )
    try:
        raw = pd.read_parquet(path, columns=list(CANONICAL_COLUMNS))
    except Exception:  # noqa: BLE001
        return []

    normalized = normalize_bars(raw, symbol)
    raw_in_window = normalized.loc[normalized["date"].between(start_ts, end_ts)]
    in_window = _drop_zero_liquidity_bars(raw_in_window)
    return _gap_episodes_for_dates(
        in_window,
        timeframe,
        expected_sessions=expected_sessions,
        start_ts=start_ts,
        end_ts=end_ts,
        base=base,
        status="missing_bars",
    )


def _audit_record(base: dict[str, object], **overrides: object) -> dict[str, object]:
    record = {
        **base,
        "status": "",
        "rows_total": 0,
        "rows_in_window": 0,
        "expected_rows": 0,
        "missing_rows": 0,
        "coverage_ratio": 0.0,
        "max_missing_gap_minutes": 0,
        "first_missing_at": pd.NaT,
        "last_missing_at": pd.NaT,
        "max_missing_gap_start_at": pd.NaT,
        "max_missing_gap_end_at": pd.NaT,
        "start": pd.NaT,
        "end": pd.NaT,
        "invalid_date_rows": 0,
        "invalid_symbol_rows": 0,
        "duplicate_rows": 0,
        "null_ohlc_rows": 0,
        "non_positive_price_rows": 0,
        "inconsistent_ohlc_rows": 0,
        "null_volume_amount_rows": 0,
        "zero_volume_amount_rows": 0,
        "negative_volume_amount_rows": 0,
        "missing_columns": "",
        "message": "",
    }
    record.update(overrides)
    return record


def _parquet_num_rows(parquet_file: pq.ParquetFile) -> int:
    metadata = parquet_file.metadata
    return int(metadata.num_rows) if metadata is not None else 0


def _read_canonical_window(path: Path, *, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    try:
        return pd.read_parquet(
            path,
            columns=list(CANONICAL_COLUMNS),
            filters=[("date", ">=", start_ts), ("date", "<=", end_ts)],
        )
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
        if not _is_date_filter_type_mismatch(exc):
            raise
        return pd.read_parquet(path, columns=list(CANONICAL_COLUMNS))


def _read_canonical_dataset_window(dataset: ds.Dataset | None, *, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    if dataset is None:
        return pd.DataFrame(columns=list(CANONICAL_COLUMNS))
    table = dataset.to_table(
        columns=list(CANONICAL_COLUMNS),
        filter=(ds.field("date") >= start_ts) & (ds.field("date") <= end_ts),
    )
    return table.to_pandas()


def _dataset_rows_total_by_symbol(dataset: ds.Dataset) -> dict[str, int]:
    rows_total: dict[str, int] = {}
    for fragment in dataset.get_fragments():
        metadata = getattr(fragment, "metadata", None)
        rows_total[Path(fragment.path).stem] = int(metadata.num_rows) if metadata is not None else 0
    return rows_total


def _group_size(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {}
    return {str(symbol): int(value) for symbol, value in frame.groupby("stock_code", sort=False).size().items()}


def _group_min(frame: pd.DataFrame, column: str) -> dict[str, object]:
    if frame.empty:
        return {}
    return {str(symbol): value for symbol, value in frame.groupby("stock_code", sort=False)[column].min().items()}


def _group_max(frame: pd.DataFrame, column: str) -> dict[str, object]:
    if frame.empty:
        return {}
    return {str(symbol): value for symbol, value in frame.groupby("stock_code", sort=False)[column].max().items()}


def _group_mask_sum(frame: pd.DataFrame, mask: pd.Series | None) -> dict[str, int]:
    if frame.empty or mask is None:
        return {}
    values = mask.astype(int).groupby(frame["stock_code"], sort=False).sum()
    return {str(symbol): int(value) for symbol, value in values.items()}


def _group_date_sets(frame: pd.DataFrame) -> dict[str, set[pd.Timestamp]]:
    if frame.empty:
        return {}
    valid = frame.loc[frame["date"].notna(), ["stock_code", "date"]].copy()
    if valid.empty:
        return {}
    valid["date"] = pd.to_datetime(valid["date"], errors="coerce").dt.normalize()
    return {
        str(symbol): {pd.Timestamp(item) for item in group["date"].dropna().drop_duplicates()}
        for symbol, group in valid.groupby("stock_code", sort=False)
    }


def _expected_date_sets_from_mapping(
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]],
) -> dict[str, set[pd.Timestamp]]:
    return {
        str(symbol): {
            pd.Timestamp(item).normalize()
            for item in pd.to_datetime(list(sessions), errors="coerce")
            if not pd.isna(item)
        }
        for symbol, sessions in expected_sessions_by_symbol.items()
    }


def _expected_date_sets_for_symbols(
    symbols: list[str],
    expected_sessions_by_symbol: Mapping[str, Sequence[pd.Timestamp]],
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> dict[str, set[pd.Timestamp]]:
    task_dates = {pd.Timestamp(item).normalize() for item in _task_trading_sessions(start_ts=start_ts, end_ts=end_ts)}
    expected = {symbol: set(task_dates) for symbol in symbols}
    for symbol, sessions in _expected_date_sets_from_mapping(expected_sessions_by_symbol).items():
        normalized = normalize_symbol(symbol)
        if normalized in expected:
            expected[normalized].update(sessions)
    return expected


def _daily_coverage_from_sets(
    expected_dates: set[pd.Timestamp],
    actual_dates: set[pd.Timestamp],
) -> dict[str, object]:
    expected = sorted(expected_dates)
    expected_count = len(expected)
    if expected_count == 0:
        return _empty_coverage()
    missing = [timestamp for timestamp in expected if timestamp not in actual_dates]
    return {
        "expected_rows": int(expected_count),
        "missing_rows": int(len(missing)),
        "coverage_ratio": round((expected_count - len(missing)) / expected_count, 12),
        **_missing_coverage_summary(expected, missing=set(missing), minutes=1440),
    }


def _daily_fast_quality_error(
    *,
    symbol: str,
    adjust: str,
    duplicate_rows: int,
    null_ohlc_rows: int,
    non_positive_price_rows: int,
    inconsistent_ohlc_rows: int,
    null_volume_amount_rows: int,
    negative_volume_amount_rows: int,
) -> bool:
    is_tdx_sector_index = _is_tdx_sector_index(symbol)
    non_positive_blocks = (
        non_positive_price_rows > 0
        and not is_tdx_sector_index
        and not _adjust_allows_non_positive_prices(adjust)
    )
    inconsistent_blocks = inconsistent_ohlc_rows > 0 and not is_tdx_sector_index
    return any(
        [
            duplicate_rows > 0,
            null_ohlc_rows > 0,
            non_positive_blocks,
            inconsistent_blocks,
            null_volume_amount_rows > 0,
            negative_volume_amount_rows > 0,
        ]
    )


def _is_date_filter_type_mismatch(exc: Exception) -> bool:
    message = str(exc).lower()
    return "timestamp" in message and "string" in message and ("greater_equal" in message or "less_equal" in message)


def _drop_zero_liquidity_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty or "volume" not in bars.columns or "amount" not in bars.columns:
        return bars
    tradable = bars["volume"].gt(0) & bars["amount"].gt(0)
    return bars.loc[tradable].reset_index(drop=True)


def _quality_issue_messages(
    *,
    checked: pd.DataFrame,
    window: pd.DataFrame,
    adjust: object,
    symbol: str,
) -> list[str]:
    messages: list[str] = []
    invalid_dates = checked.loc[checked["date"].isna()]
    if not invalid_dates.empty:
        messages.append(f"第 {int(invalid_dates.index[0]) + 1} 行日期无法解析")
    invalid_symbols = window.loc[window["stock_code"].eq("")]
    if not invalid_symbols.empty:
        messages.append(_quality_issue_at(invalid_symbols.iloc[0], "标的代码异常"))
    duplicates = window.loc[window.duplicated(subset=["stock_code", "date"], keep=False)]
    if not duplicates.empty:
        messages.append(_quality_issue_at(duplicates.iloc[0], "重复时间"))
    null_ohlc = window.loc[window[["open", "high", "low", "close"]].isna().any(axis=1)]
    if not null_ohlc.empty:
        columns = _bad_columns(null_ohlc.iloc[0], ("open", "high", "low", "close"), lambda value: pd.isna(value))
        messages.append(_quality_issue_at(null_ohlc.iloc[0], f"OHLC 字段为空 {','.join(columns)}"))

    allow_adjusted_non_positive_prices = _adjust_allows_non_positive_prices(adjust)
    is_tdx_sector_index = _is_tdx_sector_index(symbol)
    if not (allow_adjusted_non_positive_prices or is_tdx_sector_index):
        non_positive = window.loc[(window[["open", "high", "low", "close"]] <= 0).any(axis=1)]
        if not non_positive.empty:
            columns = _bad_columns(
                non_positive.iloc[0],
                ("open", "high", "low", "close"),
                lambda value: not pd.isna(value) and float(value) <= 0,
            )
            messages.append(
                _quality_issue_at(
                    non_positive.iloc[0],
                    f"非法价格 {','.join(columns)}",
                    columns=("open", "high", "low", "close"),
                )
            )

    if not is_tdx_sector_index:
        inconsistent = window.loc[
            _inconsistent_ohlc_mask(window, require_positive=not allow_adjusted_non_positive_prices)
        ]
        if not inconsistent.empty:
            messages.append(
                _quality_issue_at(
                    inconsistent.iloc[0],
                    "OHLC 高低点不一致",
                    columns=("open", "high", "low", "close"),
                )
            )

    null_volume_amount = window.loc[window[["volume", "amount"]].isna().any(axis=1)]
    if not null_volume_amount.empty:
        columns = _bad_columns(null_volume_amount.iloc[0], ("volume", "amount"), lambda value: pd.isna(value))
        messages.append(_quality_issue_at(null_volume_amount.iloc[0], f"量能字段为空 {','.join(columns)}"))
    negative_volume_amount = window.loc[(window[["volume", "amount"]] < 0).any(axis=1)]
    if not negative_volume_amount.empty:
        columns = _bad_columns(
            negative_volume_amount.iloc[0],
            ("volume", "amount"),
            lambda value: not pd.isna(value) and float(value) < 0,
        )
        messages.append(
            _quality_issue_at(
                negative_volume_amount.iloc[0],
                f"量能字段为负 {','.join(columns)}",
                columns=("volume", "amount"),
            )
        )
    return messages


def _quality_issue_at(row: pd.Series, reason: str, *, columns: tuple[str, ...] = ()) -> str:
    timestamp = pd.Timestamp(row.get("date")) if not pd.isna(row.get("date")) else pd.NaT
    date_text = str(timestamp.date()) if not pd.isna(timestamp) else "-"
    value_text = f" {_quality_value_summary(row, columns)}" if columns else ""
    return f"{date_text} {reason}{value_text}".strip()


def _quality_value_summary(row: pd.Series, columns: tuple[str, ...]) -> str:
    return " ".join(f"{column}={_format_quality_value(row.get(column))}" for column in columns)


def _format_quality_value(value: object) -> str:
    if pd.isna(value):
        return "NaN"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6g}"


def _bad_columns(row: pd.Series, columns: tuple[str, ...], predicate) -> list[str]:  # type: ignore[no-untyped-def]
    return [column for column in columns if predicate(row.get(column))]


def _inconsistent_ohlc_mask(frame: pd.DataFrame, *, require_positive: bool = True) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    ohlc = frame[["open", "high", "low", "close"]]
    valid = ohlc.notna().all(axis=1)
    if require_positive:
        valid &= (ohlc > 0).all(axis=1)
    max_body = ohlc[["open", "close"]].max(axis=1)
    min_body = ohlc[["open", "close"]].min(axis=1)
    high = ohlc["high"]
    low = ohlc["low"]
    return valid & ((high < max_body) | (low > min_body) | (high < low))


def _adjust_allows_non_positive_prices(adjust: object) -> bool:
    return str(adjust).strip().lower() == "qfq"


def _is_tdx_sector_index(symbol: object) -> bool:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return False
    code, exchange = normalized.split(".", 1)
    return exchange == "SH" and code.startswith(TDX_SECTOR_INDEX_PREFIX)


def _intraday_session_coverage(
    in_window: pd.DataFrame,
    timeframe: str,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None = None,
) -> dict[str, object]:
    if ensure_supported_timeframe(timeframe) == "1d":
        return _daily_session_coverage(
            in_window,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions=expected_sessions,
        )
    minutes = _timeframe_minutes(timeframe)
    expected, actual_set = _intraday_expected_and_actual(
        in_window,
        minutes,
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
    )
    expected_count = len(expected)
    if expected_count == 0:
        return _empty_coverage()
    missing = [timestamp for timestamp in expected if timestamp not in actual_set]
    return {
        "expected_rows": int(expected_count),
        "missing_rows": int(len(missing)),
        "coverage_ratio": round((expected_count - len(missing)) / expected_count, 12),
        **_missing_coverage_summary(expected, missing=set(missing), minutes=minutes),
    }


def _daily_session_coverage(
    in_window: pd.DataFrame,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None = None,
) -> dict[str, object]:
    expected, actual_set = _daily_expected_and_actual(
        in_window,
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
    )
    expected_count = len(expected)
    if expected_count == 0:
        return _empty_coverage()
    missing = [timestamp for timestamp in expected if timestamp not in actual_set]
    return {
        "expected_rows": int(expected_count),
        "missing_rows": int(len(missing)),
        "coverage_ratio": round((expected_count - len(missing)) / expected_count, 12),
        **_missing_coverage_summary(expected, missing=set(missing), minutes=1440),
    }


def _empty_coverage() -> dict[str, object]:
    return {
        "expected_rows": 0,
        "missing_rows": 0,
        "coverage_ratio": 0.0,
        "max_missing_gap_minutes": 0,
        "first_missing_at": pd.NaT,
        "last_missing_at": pd.NaT,
        "max_missing_gap_start_at": pd.NaT,
        "max_missing_gap_end_at": pd.NaT,
    }


def _gap_episodes_for_dates(
    in_window: pd.DataFrame,
    timeframe: str,
    *,
    expected_sessions: Sequence[pd.Timestamp] | None,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    base: dict[str, object],
    status: str,
) -> list[dict[str, object]]:
    if ensure_supported_timeframe(timeframe) == "1d":
        expected, actual_set = _daily_expected_and_actual(
            in_window,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions=expected_sessions,
        )
        minutes = 1440
    else:
        minutes = _timeframe_minutes(timeframe)
        expected, actual_set = _intraday_expected_and_actual(
            in_window,
            minutes,
            start_ts=start_ts,
            end_ts=end_ts,
            expected_sessions=expected_sessions,
        )
    return _missing_gap_episode_rows(expected, actual_set=actual_set, minutes=minutes, base=base, status=status)


def _intraday_expected_and_actual(
    in_window: pd.DataFrame,
    minutes: int,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None,
) -> tuple[list[pd.Timestamp], set[pd.Timestamp]]:
    actual_dates = _actual_minute_dates(in_window)
    session_dates = _task_trading_sessions(
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
    )
    expected = _expected_intraday_timestamps(session_dates, minutes)
    expected = [timestamp for timestamp in expected if start_ts <= timestamp <= end_ts]
    return expected, set(actual_dates)


def _daily_expected_and_actual(
    in_window: pd.DataFrame,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None,
) -> tuple[list[pd.Timestamp], set[pd.Timestamp]]:
    actual_dates = _actual_minute_dates(in_window).dt.normalize()
    session_dates = _task_trading_sessions(
        start_ts=start_ts,
        end_ts=end_ts,
        expected_sessions=expected_sessions,
    )
    start_day = start_ts.normalize()
    end_day = inclusive_end_timestamp(end_ts).normalize()
    expected = [pd.Timestamp(item) for item in session_dates if start_day <= pd.Timestamp(item) <= end_day]
    return expected, set(actual_dates)


def _task_trading_sessions(
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    expected_sessions: Sequence[pd.Timestamp] | None = None,
) -> pd.Series:
    task_sessions = _business_day_sessions(start_ts=start_ts, end_ts=end_ts)
    if not expected_sessions:
        return task_sessions
    known_sessions = pd.Series(pd.to_datetime(list(expected_sessions), errors="coerce")).dropna().dt.normalize()
    combined = pd.concat([task_sessions, known_sessions], ignore_index=True)
    return combined.drop_duplicates().sort_values().reset_index(drop=True)


def _business_day_sessions(*, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.Series:
    start_day = start_ts.normalize()
    end_day = inclusive_end_timestamp(end_ts).normalize()
    return pd.Series(pd.bdate_range(start=start_day, end=end_day), dtype="datetime64[ns]")


def _actual_minute_dates(in_window: pd.DataFrame) -> pd.Series:
    if in_window.empty or "date" not in in_window.columns:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(in_window["date"], errors="coerce").dropna().dt.floor("min")


def _missing_gap_episode_rows(
    expected: list[pd.Timestamp],
    *,
    actual_set: set[pd.Timestamp],
    minutes: int,
    base: dict[str, object],
    status: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_available = pd.NaT
    gap_start = pd.NaT
    gap_end = pd.NaT
    gap_previous = pd.NaT
    missing_rows = 0
    for timestamp in expected:
        if timestamp not in actual_set:
            if missing_rows == 0:
                gap_start = timestamp
                gap_previous = previous_available
            missing_rows += 1
            gap_end = timestamp
            continue
        if missing_rows > 0:
            rows.append(
                _gap_episode_row(
                    base,
                    gap_no=len(rows) + 1,
                    start_at=gap_start,
                    end_at=gap_end,
                    missing_rows=missing_rows,
                    minutes=minutes,
                    previous_available_at=gap_previous,
                    next_available_at=timestamp,
                    status=status,
                )
            )
            missing_rows = 0
            gap_start = pd.NaT
            gap_end = pd.NaT
            gap_previous = pd.NaT
        previous_available = timestamp
    if missing_rows > 0:
        rows.append(
            _gap_episode_row(
                base,
                gap_no=len(rows) + 1,
                start_at=gap_start,
                end_at=gap_end,
                missing_rows=missing_rows,
                minutes=minutes,
                previous_available_at=gap_previous,
                next_available_at=pd.NaT,
                status=status,
            )
        )
    return rows


def _gap_episode_row(
    base: dict[str, object],
    *,
    gap_no: int,
    start_at: pd.Timestamp,
    end_at: pd.Timestamp,
    missing_rows: int,
    minutes: int,
    previous_available_at: pd.Timestamp,
    next_available_at: pd.Timestamp,
    status: str,
) -> dict[str, object]:
    return {
        **base,
        "gap_no": int(gap_no),
        "start_at": start_at,
        "end_at": end_at,
        "missing_rows": int(missing_rows),
        "gap_minutes": int(missing_rows * minutes),
        "previous_available_at": previous_available_at,
        "next_available_at": next_available_at,
        "status": status,
    }


def _daily_audit_by_symbol(daily_audit: pd.DataFrame | None) -> dict[str, Mapping[str, object]]:
    if daily_audit is None or daily_audit.empty or "stock_code" not in daily_audit.columns:
        return {}
    result: dict[str, Mapping[str, object]] = {}
    for row in daily_audit.to_dict("records"):
        symbol = normalize_symbol(row.get("stock_code", ""))
        if symbol:
            result[symbol] = row
    return result


def _limit_open_filter_audit_row(
    *,
    symbol: str,
    window: pd.DataFrame,
    blocked: pd.DataFrame,
    filter_enabled: bool,
    daily_audit_row: Mapping[str, object] | None = None,
) -> dict[str, object]:
    symbol_daily = window.loc[window["stock_code"].eq(symbol)] if not window.empty else window
    filtered_days = int(blocked.loc[blocked.get("stock_code", pd.Series(dtype=str)).eq(symbol)].shape[0])
    if not filter_enabled:
        return {
            "stock_code": symbol,
            "status": "disabled",
            "filter_enabled": False,
            "daily_rows": int(len(symbol_daily)),
            "filtered_days": 0,
            "message": "日K一字涨停过滤已关闭。",
        }
    if symbol_daily.empty:
        audit_status = str(daily_audit_row.get("status", "")) if daily_audit_row is not None else ""
        status = DAILY_FILTER_AUDIT_STATUS_BY_DATA_STATUS.get(audit_status)
        if status is not None:
            detail = str(daily_audit_row.get("message", "")) if daily_audit_row is not None else ""
            summary = DAILY_FILTER_AUDIT_MESSAGE_BY_DATA_STATUS[audit_status]
            return {
                "stock_code": symbol,
                "status": status,
                "filter_enabled": True,
                "daily_rows": 0,
                "filtered_days": 0,
                "message": f"{summary}，无法判断一字涨停开盘过滤：{detail}",
            }
        return {
            "stock_code": symbol,
            "status": "daily_missing",
            "filter_enabled": True,
            "daily_rows": 0,
            "filtered_days": 0,
            "message": "日K缺失，无法判断一字涨停开盘过滤。",
        }
    return {
        "stock_code": symbol,
        "status": "ok",
        "filter_enabled": True,
        "daily_rows": int(len(symbol_daily)),
        "filtered_days": filtered_days,
        "message": "日K一字涨停过滤已执行。",
    }


def _timeframe_minutes(timeframe: str) -> int:
    normalized = ensure_supported_timeframe(timeframe)
    return int(normalized.removesuffix("m"))


def _expected_intraday_timestamps(session_dates: pd.Series, minutes: int) -> list[pd.Timestamp]:
    expected: list[pd.Timestamp] = []
    for session_date in session_dates:
        session = pd.Timestamp(session_date)
        expected.extend(_session_range(session, "09:30", "11:30", minutes))
        expected.extend(_session_range(session, "13:00", "15:00", minutes))
    return expected


def _session_range(session: pd.Timestamp, start: str, end: str, minutes: int) -> list[pd.Timestamp]:
    start_ts = pd.Timestamp(f"{session.date()} {start}") + pd.Timedelta(minutes=minutes)
    end_ts = pd.Timestamp(f"{session.date()} {end}")
    return [pd.Timestamp(item) for item in pd.date_range(start=start_ts, end=end_ts, freq=f"{minutes}min")]


def _missing_coverage_summary(
    expected: list[pd.Timestamp],
    missing: set[pd.Timestamp],
    minutes: int,
) -> dict[str, object]:
    """单次扫描缺失 K，返回全局缺口首尾和最长连续缺口边界。"""
    first_missing = pd.NaT
    last_missing = pd.NaT
    max_gap_minutes = 0
    max_gap_start = pd.NaT
    max_gap_end = pd.NaT
    current_gap_minutes = 0
    current_gap_start = pd.NaT
    current_gap_end = pd.NaT
    for timestamp in expected:
        if timestamp in missing:
            if pd.isna(first_missing):
                first_missing = timestamp
            last_missing = timestamp
            if current_gap_minutes == 0:
                current_gap_start = timestamp
            current_gap_minutes += minutes
            current_gap_end = timestamp
            if current_gap_minutes > max_gap_minutes:
                max_gap_minutes = current_gap_minutes
                max_gap_start = current_gap_start
                max_gap_end = current_gap_end
        else:
            current_gap_minutes = 0
            current_gap_start = pd.NaT
            current_gap_end = pd.NaT
    return {
        "max_missing_gap_minutes": int(max_gap_minutes),
        "first_missing_at": first_missing,
        "last_missing_at": last_missing,
        "max_missing_gap_start_at": max_gap_start,
        "max_missing_gap_end_at": max_gap_end,
    }
