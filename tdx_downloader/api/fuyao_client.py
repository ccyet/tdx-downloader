from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FUYAO_BASE_URL = "https://fuyao.aicubes.cn"
TRADING_DAYS_PATH = "/api/a-share/calendar/trading-days"
DEFAULT_TIMEOUT_SECONDS = 15


class FuyaoAPIError(RuntimeError):
    pass


def fetch_trading_days(api_key: str = "") -> dict[str, Any]:
    return _request_data(TRADING_DAYS_PATH, api_key=api_key)


def has_fuyao_api_key() -> bool:
    return bool(_fuyao_api_key())


def normalize_trading_days(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("item", [])
    if not isinstance(raw_items, list):
        raise ValueError("Fuyao 交易日历返回 item 不是数组。")
    days = sorted({_normalize_trading_day(item.get("date")) for item in raw_items if isinstance(item, dict)})
    days = [day for day in days if day]
    return {
        "timestamp": data.get("timestamp"),
        "raw_count": len(raw_items),
        "days": days,
    }


def _request_data(path: str, *, api_key: str = "") -> dict[str, Any]:
    resolved_api_key = _fuyao_api_key(api_key)
    if not resolved_api_key:
        raise FuyaoAPIError("未配置 FUYAO_API_KEY。")
    url = f"{FUYAO_BASE_URL}{path}"
    request = Request(url, headers={"X-api-key": resolved_api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FuyaoAPIError(f"Fuyao API HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise FuyaoAPIError(f"Fuyao API 请求失败: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FuyaoAPIError("Fuyao API 返回不是合法 JSON。") from exc

    if not isinstance(payload, dict):
        raise FuyaoAPIError("Fuyao API 返回不是对象。")
    code = payload.get("code")
    if code != 0:
        message = payload.get("message") or "unknown"
        raise FuyaoAPIError(f"Fuyao API 返回错误 code={code}: {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise FuyaoAPIError("Fuyao API 返回缺少 data 对象。")
    return data


def _fuyao_api_key(explicit_api_key: str = "") -> str:
    if explicit_api_key.strip():
        return explicit_api_key.strip()
    return (
        os.environ.get("FUYAO_API_KEY")
        or os.environ.get("AICUBES_API_KEY")
        or os.environ.get("THS_API_KEY")
        or ""
    ).strip()


def _normalize_trading_day(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""
