from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from tdx_downloader.data.schema import canonical_data_root

TRADING_CALENDAR_FILE_NAME = "trading-calendar.json"


def trading_calendar_path_for(data_root: str | Path) -> Path:
    return canonical_data_root(data_root) / "metadata" / TRADING_CALENDAR_FILE_NAME


def last_completed_trade_date(
    *,
    data_root: str | Path,
    now: datetime | None = None,
    settle_hour: int = 16,
) -> str:
    return trade_date_status(data_root=data_root, now=now, settle_hour=settle_hour)["trade_date"]


def trade_date_status(
    *,
    data_root: str | Path,
    now: datetime | None = None,
    settle_hour: int = 16,
) -> dict[str, Any]:
    current = now or datetime.now().astimezone()
    candidate = _last_completed_business_day(current, settle_hour=settle_hour)
    days = _load_trading_days(data_root)
    local_last_day = _latest_local_daily_trade_date(data_root, candidate=candidate)
    if not days:
        return {
            "trade_date": candidate,
            "source": "business-day-fallback",
            "calendar_status": "missing",
            "calendar_last_day": "",
            "local_last_day": local_last_day,
            "calendar_path": str(trading_calendar_path_for(data_root)),
        }
    if days[-1] < candidate:
        return {
            "trade_date": candidate,
            "source": "business-day-fallback",
            "calendar_status": "stale",
            "calendar_last_day": days[-1],
            "local_last_day": local_last_day,
            "calendar_path": str(trading_calendar_path_for(data_root)),
        }
    valid_days = [day for day in days if day <= candidate]
    trade_date = valid_days[-1] if valid_days else candidate
    return {
        "trade_date": trade_date,
        "source": "local",
        "calendar_status": "ok",
        "calendar_last_day": days[-1],
        "local_last_day": local_last_day,
        "calendar_path": str(trading_calendar_path_for(data_root)),
    }


def save_trading_days(*, data_root: str | Path, days: list[str], source: str = "") -> Path:
    path = trading_calendar_path_for(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "days": sorted({_normalize_day(day) for day in days if _normalize_day(day)}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _last_completed_business_day(now: datetime, *, settle_hour: int) -> str:
    day = now.date()
    if day.weekday() >= 5:
        day -= timedelta(days=day.weekday() - 4)
    elif now.hour < settle_hour:
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
    return day.isoformat()


def _load_trading_days(data_root: str | Path) -> list[str]:
    path = trading_calendar_path_for(data_root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_days = payload.get("days") if isinstance(payload, dict) else []
    if not isinstance(raw_days, list):
        return []
    return sorted({_normalize_day(day) for day in raw_days if _normalize_day(day)})


def _latest_local_daily_trade_date(data_root: str | Path, *, candidate: str) -> str:
    try:
        from tdx_downloader.data.catalog import catalog_path_for, connect_catalog
    except ImportError:
        return ""
    path = catalog_path_for(data_root)
    if not path.exists():
        return ""
    try:
        with connect_catalog(path, read_only=True, timeout_seconds=2) as connection:
            rows = []
            for table_name, column_name in (
                ("market_data_coverage_runs", "end_at"),
                ("market_data_files", "end_at"),
            ):
                if not _sqlite_table_exists(connection, table_name):
                    continue
                rows.extend(
                    item[0]
                    for item in connection.execute(
                        f"SELECT MAX({column_name}) FROM {table_name} WHERE timeframe = '1d' AND substr({column_name}, 1, 10) <= ?",
                        (candidate,),
                    ).fetchall()
                    if item and item[0]
                )
    except sqlite3.DatabaseError:
        return ""
    days = [_normalize_day(str(value)[:10]) for value in rows]
    days = [day for day in days if day]
    return max(days) if days else ""


def _sqlite_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _normalize_day(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""
