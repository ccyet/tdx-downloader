from __future__ import annotations

from datetime import datetime
import math
from typing import Any

import pandas as pd

from .constants import MAX_TABLE_RECORDS


def _records(frame: pd.DataFrame, *, limit: int | None = MAX_TABLE_RECORDS) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records = frame if limit is None else frame.head(limit)
    return [_json_dict(record) for record in records.to_dict("records")]


def _json_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in values.items()}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return _json_dict(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _numeric_sum(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
