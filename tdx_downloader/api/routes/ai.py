from __future__ import annotations

import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException
import pandas as pd

from tdx_downloader.data.catalog import infer_asset_type, query_catalog
from tdx_downloader.data.manager import normalize_symbol_tuple
from tdx_downloader.data.schema import normalize_symbol
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.data.symbols import load_symbol_metadata, resolve_symbol_names

from ..ai_client import call_compatible_chat, call_stock_agent_ai
from ..schemas import AICommandPayload, AIStockAgentPayload
from ..serialization import _json_value, _records


def register_ai_routes(app: FastAPI) -> None:
    @app.post("/api/ai/command")
    def ai_command(payload: AICommandPayload) -> dict[str, Any]:
        try:
            return _json_value(_plan_ai_command(payload))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ai/stock-agent")
    def ai_stock_agent(payload: AIStockAgentPayload) -> dict[str, Any]:
        try:
            context = _stock_data_context(payload)
            messages = _stock_agent_messages(payload, context)
            content = call_stock_agent_ai(payload, messages)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _json_value(
            {
                "content": content,
                "messages": messages,
                "data_context": context,
                "disclaimer": "仅用于本地行情研究，不构成投资建议。",
            }
        )


def _plan_ai_command(payload: AICommandPayload) -> dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise ValueError("请先输入 AI 命令。")
    local_plan = _local_command_plan(payload)
    warnings: list[str] = list(local_plan["warnings"])
    patches: list[dict[str, Any]] = []
    parser = "local"
    if _command_model_ready(payload):
        try:
            model_plan = _model_command_plan(payload)
            parser = "model"
            patches.extend(model_plan["patches"])
            warnings.extend(model_plan["warnings"])
        except (RuntimeError, ValueError) as exc:
            warnings.append(f"模型命令解析失败，已使用本地规则：{exc}")
    else:
        warnings.append("AI 命令解析未配置模型，已使用本地规则。")
    seen_targets = {str(patch.get("target") or "") for patch in patches}
    patches.extend(patch for patch in local_plan["patches"] if str(patch.get("target") or "") not in seen_targets)
    if not patches:
        warnings.append("暂未识别到可直接应用的字段；可尝试说“选择所有创业板股票”或“现金偏好阈值设为65%”。")
    return {
        "summary": _command_summary(text, patches),
        "patches": patches,
        "selected_symbols": local_plan["selected_symbols"][:200],
        "selected_symbol_count": len(local_plan["selected_symbols"]),
        "warnings": warnings,
        "parser": parser,
        "scope": {
            "current_view": payload.current_view,
            "research_tab": payload.research_tab,
        },
    }


def _local_command_plan(payload: AICommandPayload) -> dict[str, Any]:
    text = payload.text.strip()
    patches: list[dict[str, Any]] = []
    warnings: list[str] = []
    selected_symbols = _symbols_from_command(payload)
    if selected_symbols:
        target = _symbol_patch_target(payload)
        patches.append(
            {
                "target": target,
                "value": "\n".join(selected_symbols),
                "mode": "replace",
                "label": "标的池",
                "summary": f"已选择 {len(selected_symbols)} 个标的。",
            }
        )
        if _wants_stock_agent(text) and target != "aiWorkbenchForm.symbols":
            patches.append(_patch("activeView", "ai", "切换到 AI 工作台"))
            patches.append(_patch("aiWorkbenchForm.symbols", "\n".join(selected_symbols), f"AI 模块载入 {len(selected_symbols)} 个标的"))
            patches.append(_patch("aiWorkbenchForm.prompt", text, "AI 模块任务使用当前命令"))
    patches.extend(_general_parameter_patches(payload))
    patches.extend(_risk_parameter_patches(text))
    return {
        "patches": patches,
        "selected_symbols": selected_symbols,
        "warnings": warnings,
    }


def _model_command_plan(payload: AICommandPayload) -> dict[str, Any]:
    content = call_compatible_chat(
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        messages=_command_model_messages(payload),
        temperature=payload.temperature,
        timeout_seconds=payload.timeout_seconds,
    )
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("模型命令输出必须是 JSON 对象。")
    patches = _sanitize_model_patches(raw.get("patches"))
    warnings = [str(item) for item in raw.get("warnings", []) if str(item).strip()] if isinstance(raw.get("warnings"), list) else []
    return {"patches": patches, "warnings": warnings}


def _command_model_ready(payload: AICommandPayload) -> bool:
    return bool(payload.base_url.strip() and payload.api_key.strip() and payload.model.strip())


def _command_model_messages(payload: AICommandPayload) -> list[dict[str, str]]:
    allowed = sorted(_ALLOWED_COMMAND_TARGETS)
    system = (
        "你是 TDX 本地行情工作台的命令解析器。只把用户中文命令解析为 JSON，不要解释。"
        "输出必须是严格 JSON 对象，字段只能包含 summary、patches、warnings。"
        "patches 是数组，每项包含 target、value、summary。target 必须来自白名单。"
        "百分比字段若是 regimeForm.*，value 用用户界面百分数，例如 65 表示 65%。"
        "reviewForm.min_swing_return 用比例小数，例如 0.05 表示 5%。"
        "不要输出 API key、不要请求外部数据、不要执行交易。"
    )
    user = {
        "command": payload.text,
        "current_view": payload.current_view,
        "research_tab": payload.research_tab,
        "allowed_targets": allowed,
        "examples": [
            {"command": "帮我选择所有创业板股票", "patches": [{"target": "regimeForm.symbols", "value": "300001.SZ\n301001.SZ"}]},
            {"command": "现金偏好阈值设为65%", "patches": [{"target": "regimeForm.cash_preference_proxy_threshold", "value": 65}]},
            {"command": "用AI分析000001.SZ近一年日线", "patches": [{"target": "activeView", "value": "ai"}, {"target": "aiWorkbenchForm.symbols", "value": "000001.SZ"}]},
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _sanitize_model_patches(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    patches: list[dict[str, Any]] = []
    for raw in value[:30]:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or "").strip()
        if target not in _ALLOWED_COMMAND_TARGETS:
            continue
        normalized = _normalize_patch_value(target, raw.get("value"))
        if normalized is _SKIP_PATCH:
            continue
        patches.append(
            {
                "target": target,
                "value": normalized,
                "mode": "replace",
                "label": target,
                "summary": str(raw.get("summary") or target),
            }
        )
    return patches


_SKIP_PATCH = object()


def _normalize_patch_value(target: str, value: object) -> object:
    if target == "selectedTimeframes":
        values = value if isinstance(value, list) else [value]
        timeframes = [str(item) for item in values if str(item) in {"1d", "1m", "5m", "15m", "30m", "60m"}]
        return timeframes or _SKIP_PATCH
    if target in {"activeView"}:
        text = str(value)
        return text if text in {"dashboard", "download", "cache", "research", "ai", "tasks", "settings"} else _SKIP_PATCH
    if target.endswith(".date_shortcut"):
        text = str(value)
        return text if text in {"20d", "50d", "ytd", "1y"} else _SKIP_PATCH
    if target.endswith(".symbols") or target in {"symbolsText", "crossForm.universe_symbols", "aiWorkbenchForm.prompt", "aiWorkbenchForm.skill_prompt"}:
        return str(value or "")
    if target in _BOOLEAN_TARGETS:
        return bool(value)
    if target in _INTEGER_TARGETS:
        number = _finite_number(value)
        return int(number) if number is not None else _SKIP_PATCH
    if target in _NUMERIC_TARGETS:
        number = _finite_number(value)
        if number is None:
            return _SKIP_PATCH
        if target in _UI_PERCENT_TARGETS and abs(number) <= 1:
            return number * 100
        if target == "reviewForm.min_swing_return" and abs(number) > 1:
            return number / 100
        return number
    if target in _STRING_ENUM_TARGETS:
        text = str(value or "")
        allowed = _STRING_ENUM_TARGETS[target]
        return text if text in allowed else _SKIP_PATCH
    return str(value or "")


def _finite_number(value: object) -> float | None:
    try:
        number = float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _symbols_from_command(payload: AICommandPayload) -> list[str]:
    text = payload.text.upper()
    selector = _symbol_selector(text)
    if not selector:
        explicit = normalize_symbol_tuple(_split_symbol_like_text(payload.text))
        return list(explicit)
    return _symbols_by_selector(
        selector=selector,
        data_root=payload.data_root,
        tdx_path=payload.tdx_path,
        timeframe=payload.timeframe,
    )


def _symbol_selector(text: str) -> str:
    if "创业板" in text:
        return "chinext"
    if "科创" in text:
        return "star"
    if "ETF" in text:
        return "etf"
    if "指数" in text:
        return "index"
    if "全A" in text or "全部A股" in text or "所有A股" in text or "所有个股" in text or "全部个股" in text:
        return "stock"
    return ""


def _wants_stock_agent(text: str) -> bool:
    return any(keyword in text for keyword in ("AI", "ai", "分析", "研究", "行情", "数据", "工作台", "skill", "提示词"))


def _symbols_by_selector(*, selector: str, data_root: str, tdx_path: str, timeframe: str) -> list[str]:
    symbols: set[str] = set()
    names: dict[str, str] = {}
    metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
    if not metadata.empty:
        for row in metadata.itertuples(index=False):
            symbol = normalize_symbol(row.stock_code)
            if not symbol:
                continue
            name = str(getattr(row, "stock_name", "") or "")
            names[symbol] = name
            if _selector_matches(selector, symbol, name):
                symbols.add(symbol)
    try:
        catalog = query_catalog(data_root=data_root, timeframes=(timeframe,), statuses=("cached", "available", "ok"))
    except Exception:  # noqa: BLE001
        catalog = pd.DataFrame()
    if not catalog.empty:
        for row in catalog.itertuples(index=False):
            symbol = normalize_symbol(getattr(row, "stock_code", ""))
            if not symbol:
                continue
            name = str(getattr(row, "stock_name", "") or names.get(symbol, ""))
            if _selector_matches(selector, symbol, name):
                symbols.add(symbol)
    return sorted(symbols)


def _selector_matches(selector: str, symbol: str, name: str) -> bool:
    code = symbol.split(".", 1)[0]
    asset_type = infer_asset_type(symbol, name)
    if selector == "chinext":
        return symbol.endswith(".SZ") and code.startswith(("300", "301")) and asset_type == "stock"
    if selector == "star":
        return symbol.endswith(".SH") and code.startswith(("688", "689")) and asset_type == "stock"
    if selector == "etf":
        return asset_type == "etf"
    if selector == "index":
        return asset_type == "index"
    if selector == "stock":
        return asset_type == "stock"
    return False


def _split_symbol_like_text(text: str) -> list[str]:
    return [item for item in text.replace("，", " ").replace("、", " ").replace(";", " ").split() if any(char.isdigit() for char in item)]


def _symbol_patch_target(payload: AICommandPayload) -> str:
    if payload.current_view == "ai":
        return "aiWorkbenchForm.symbols"
    if payload.current_view == "download":
        return "symbolsText"
    if payload.current_view == "cache":
        return "cacheFilters.keyword"
    if payload.current_view == "research":
        if payload.research_tab == "cross":
            return "crossForm.universe_symbols"
        if payload.research_tab == "review":
            return "reviewForm.symbols"
        if payload.research_tab == "regime":
            return "regimeForm.symbols"
    return "symbolsText"


def _risk_parameter_patches(text: str) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for field, labels in _RISK_PERCENT_FIELDS.items():
        value = _percent_after_any_label(text, labels)
        if value is not None:
            patches.append(_risk_patch(field, value, labels[0]))
    if patches:
        return patches
    if not any(keyword in text for keyword in ("风险", "回撤", "现金", "宽度", "释放")):
        return []
    if any(keyword in text for keyword in ("保守", "防守", "收紧", "降低风险")):
        return [
            _risk_patch("regimeForm.cash_preference_proxy_threshold", 55, "现金偏好阈值"),
            _risk_patch("regimeForm.risk_contraction_breadth_threshold", 45, "收缩宽度"),
            _risk_patch("regimeForm.risk_release_breadth_threshold", 50, "释放后段宽度"),
            _risk_patch("regimeForm.high_liquidity_selloff_threshold", 55, "高流动性抛售"),
        ]
    if any(keyword in text for keyword in ("激进", "宽松", "提高弹性", "风险偏好")):
        return [
            _risk_patch("regimeForm.risk_expansion_breadth_threshold", 55, "扩张宽度"),
            _risk_patch("regimeForm.risk_contraction_breadth_threshold", 35, "收缩宽度"),
            _risk_patch("regimeForm.risk_release_breadth_threshold", 40, "释放后段宽度"),
        ]
    return []


def _general_parameter_patches(payload: AICommandPayload) -> list[dict[str, Any]]:
    text = payload.text
    patches: list[dict[str, Any]] = []
    timeframe = _timeframe_from_text(text)
    if timeframe:
        if payload.current_view == "download":
            patches.append(_patch("selectedTimeframes", [timeframe], f"周期设为 {timeframe}"))
        elif payload.current_view == "cache":
            patches.append(_patch("cacheFilters.timeframe", timeframe, f"缓存周期筛选 {timeframe}"))
        elif payload.current_view == "research":
            patches.append(_patch("researchTimeframe", timeframe, f"研究周期设为 {timeframe}"))
        elif payload.current_view == "ai":
            patches.append(_patch("aiWorkbenchForm.timeframe", timeframe, f"AI 数据周期设为 {timeframe}"))
    shortcut = _date_shortcut_from_text(text)
    if shortcut:
        patches.append(_patch(_date_shortcut_target(payload), shortcut, f"日期快捷设为 {shortcut}"))
    if payload.current_view == "download":
        mode = "force" if any(keyword in text for keyword in ("强制", "重建", "覆盖")) else "smart" if "智能" in text else ""
        if mode:
            patches.append(_patch("settings.mode", mode, f"下载模式设为 {mode}"))
        batch_size = _int_after_any_label(text, ("批次", "batch"))
        if batch_size is not None:
            patches.append(_patch("settings.batch_size", batch_size, f"批次设为 {batch_size}"))
    if payload.current_view == "cache":
        asset_type = _asset_type_from_text(text)
        if asset_type:
            patches.append(_patch("cacheFilters.assetType", asset_type, f"缓存资产筛选 {asset_type}"))
    if payload.current_view == "ai":
        max_rows = _int_after_any_label(text, ("最大数据行", "数据行", "max_rows"))
        if max_rows is not None:
            patches.append(_patch("aiWorkbenchForm.max_rows", max_rows, f"AI 数据行上限设为 {max_rows}"))
        max_symbols = _int_after_any_label(text, ("最大标的数", "标的数", "max_symbols"))
        if max_symbols is not None:
            patches.append(_patch("aiWorkbenchForm.max_symbols", max_symbols, f"AI 标的上限设为 {max_symbols}"))
    if payload.current_view == "settings":
        if "后复权" in text or "hfq" in text.lower():
            patches.append(_patch("settings.adjust", "hfq", "复权设为 hfq"))
        elif "不复权" in text:
            patches.append(_patch("settings.adjust", "", "复权设为不复权"))
        elif "前复权" in text or "qfq" in text.lower():
            patches.append(_patch("settings.adjust", "qfq", "复权设为 qfq"))
        if any(keyword in text for keyword in ("严格校验", "质量门禁")):
            patches.append(_patch("settings.strict_after_update", not any(keyword in text for keyword in ("关闭", "不要", "禁用")), "补齐后严格校验已更新"))
    if payload.current_view != "research":
        return patches
    tab = payload.research_tab
    if tab == "history":
        patches.extend(_numeric_field_patches(text, "historyForm", {
            "window_size": ("窗口K数", "窗口"),
            "top_n": ("返回数量", "top"),
            "candidate_n": ("初筛候选", "候选"),
            "exclusion_bars": ("排除近端K数", "排除"),
            "nearby_gap_days": ("样本间隔天数", "间隔"),
        }))
        windows = _number_list_after_any_label(text, ("前瞻K数", "前瞻"))
        if windows:
            patches.append(_patch("historyForm.forward_windows", ",".join(str(item) for item in windows), "历史前瞻窗口已更新"))
    elif tab == "cross":
        patches.extend(_numeric_field_patches(text, "crossForm", {
            "top_n": ("返回数量", "top"),
            "date_tolerance_bars": ("日期容忍K数", "容忍"),
            "exclusion_bars": ("邻近排除K数", "排除"),
        }))
        target_symbol = _symbol_after_any_label(text, ("目标标的", "目标"))
        if target_symbol:
            patches.append(_patch("crossForm.target_symbol", target_symbol, f"目标标的设为 {target_symbol}"))
        if "遍历" in text or "指定区间" in text:
            patches.append(_patch("crossForm.search_mode", "traversal", "横截面搜索方式设为指定区间"))
        elif "同区间" in text:
            patches.append(_patch("crossForm.search_mode", "same_date", "横截面搜索方式设为同区间"))
    elif tab == "review":
        benchmark = _symbol_after_any_label(text, ("对标指数", "基准", "benchmark"))
        if benchmark:
            patches.append(_patch("reviewForm.benchmark_symbol", benchmark, f"对标指数设为 {benchmark}"))
        swing = _percent_after_any_label(text, ("最小波段幅度", "波段幅度"))
        if swing is not None:
            patches.append(_patch("reviewForm.min_swing_return", swing / 100, f"最小波段幅度设为 {swing:g}%"))
        bars = _int_after_any_label(text, ("最小波段K数", "波段K数"))
        if bars is not None:
            patches.append(_patch("reviewForm.min_segment_bars", bars, f"最小波段K数设为 {bars}"))
    elif tab == "etf":
        category = _etf_category_from_text(text)
        if category:
            patches.append(_patch("etfTrackerForm.category", category, f"ETF类别设为 {category}"))
        if "合并" in text:
            patches.append(_patch("etfTrackerForm.merge_similar", True, "已启用合并同类ETF"))
        top_n = _int_after_any_label(text, ("复盘数量", "返回数量", "top"))
        if top_n is not None:
            patches.append(_patch("etfTrackerForm.top_n", top_n, f"ETF复盘数量设为 {top_n}"))
    return patches


def _patch(target: str, value: Any, summary: str) -> dict[str, Any]:
    return {"target": target, "value": value, "mode": "replace", "label": target, "summary": summary}


def _numeric_field_patches(text: str, prefix: str, fields: dict[str, tuple[str, ...]]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for field, labels in fields.items():
        value = _int_after_any_label(text, labels)
        if value is not None:
            patches.append(_patch(f"{prefix}.{field}", value, f"{labels[0]}设为 {value}"))
    return patches


def _int_after_any_label(text: str, labels: tuple[str, ...]) -> int | None:
    value = _number_after_any_label(text, labels)
    return int(value) if value is not None else None


def _number_after_any_label(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        match = re.search(r"\d+(?:\.\d+)?", text[index + len(label) : index + len(label) + 24])
        if match:
            return float(match.group(0))
    return None


def _number_list_after_any_label(text: str, labels: tuple[str, ...]) -> list[int]:
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        values = [int(item) for item in re.findall(r"\d+", text[index + len(label) : index + len(label) + 40])]
        if values:
            return values
    return []


def _symbol_after_any_label(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        fragment = text[index + len(label) : index + len(label) + 32]
        match = re.search(r"\d{6}(?:\.(?:SH|SZ|BJ))?", fragment, re.IGNORECASE)
        if match:
            return normalize_symbol(match.group(0))
    return ""


def _timeframe_from_text(text: str) -> str:
    lower = text.lower()
    if "60m" in lower or "60分钟" in text:
        return "60m"
    if "30m" in lower or "30分钟" in text:
        return "30m"
    if "15m" in lower or "15分钟" in text:
        return "15m"
    if "5m" in lower or "5分钟" in text:
        return "5m"
    if "1m" in lower or "1分钟" in text:
        return "1m"
    if "1d" in lower or "日线" in text:
        return "1d"
    return ""


def _date_shortcut_from_text(text: str) -> str:
    upper = text.upper()
    if "YTD" in upper or "年初至今" in text:
        return "ytd"
    if "近一年" in text or "一年" in text:
        return "1y"
    if "50" in text and "交易日" in text:
        return "50d"
    if "20" in text and "交易日" in text:
        return "20d"
    return ""


def _date_shortcut_target(payload: AICommandPayload) -> str:
    if payload.current_view == "ai":
        return "aiWorkbenchForm.date_shortcut"
    if payload.current_view == "download":
        return "settings.date_shortcut"
    if payload.current_view == "research":
        return f"{payload.research_tab or 'review'}Form.date_shortcut"
    return "settings.date_shortcut"


def _asset_type_from_text(text: str) -> str:
    if "ETF" in text.upper():
        return "etf"
    if "指数" in text:
        return "index"
    if "个股" in text or "股票" in text:
        return "stock"
    return ""


def _etf_category_from_text(text: str) -> str:
    if "行业" in text:
        return "industry"
    if "主题" in text:
        return "theme"
    if "宽基" in text:
        return "broad"
    if "债" in text:
        return "bond"
    return ""


_ALLOWED_COMMAND_TARGETS = {
    "activeView",
    "selectedTimeframes",
    "researchTimeframe",
    "symbolsText",
    "settings.date_shortcut",
    "settings.mode",
    "settings.batch_size",
    "settings.adjust",
    "settings.strict_after_update",
    "cacheFilters.keyword",
    "cacheFilters.assetType",
    "cacheFilters.timeframe",
    "cacheFilters.status",
    "historyForm.date_shortcut",
    "historyForm.symbol",
    "historyForm.window_size",
    "historyForm.top_n",
    "historyForm.candidate_n",
    "historyForm.exclusion_bars",
    "historyForm.nearby_gap_days",
    "historyForm.forward_windows",
    "crossForm.date_shortcut",
    "crossForm.target_symbol",
    "crossForm.universe_symbols",
    "crossForm.search_mode",
    "crossForm.top_n",
    "crossForm.date_tolerance_bars",
    "crossForm.exclusion_bars",
    "crossForm.forward_windows",
    "reviewForm.date_shortcut",
    "reviewForm.symbols",
    "reviewForm.benchmark_symbol",
    "reviewForm.min_swing_return",
    "reviewForm.min_segment_bars",
    "reviewForm.enable_ai_review",
    "etfForm.date_shortcut",
    "etfTrackerForm.category",
    "etfTrackerForm.type",
    "etfTrackerForm.tracking_index",
    "etfTrackerForm.keyword",
    "etfTrackerForm.merge_similar",
    "etfTrackerForm.top_n",
    "etfTrackerForm.benchmark_symbol",
    "etfTrackerForm.min_swing_return",
    "etfTrackerForm.min_segment_bars",
    "regimeForm.date_shortcut",
    "regimeForm.symbols",
    "regimeForm.benchmark_symbol",
    "regimeForm.forward_windows",
    "regimeForm.benchmark_rally_60_threshold",
    "regimeForm.benchmark_pullback_20_threshold",
    "regimeForm.pullback_20_threshold",
    "regimeForm.pullback_60_threshold",
    "regimeForm.liquidity_high_percentile",
    "regimeForm.liquidity_mid_percentile",
    "regimeForm.liquidity_low_percentile",
    "regimeForm.volatility_high_percentile",
    "regimeForm.volatility_low_percentile",
    "regimeForm.high_position_drawdown_threshold",
    "regimeForm.high_position_return_percentile",
    "regimeForm.leader_return_5d_threshold",
    "regimeForm.stress_ma20_break_threshold",
    "regimeForm.stress_return_5d_threshold",
    "regimeForm.cash_stress_score_threshold",
    "regimeForm.cash_preference_proxy_threshold",
    "regimeForm.risk_expansion_breadth_threshold",
    "regimeForm.risk_contraction_breadth_threshold",
    "regimeForm.risk_release_breadth_threshold",
    "regimeForm.high_liquidity_selloff_threshold",
    "aiWorkbenchForm.date_shortcut",
    "aiWorkbenchForm.symbols",
    "aiWorkbenchForm.prompt",
    "aiWorkbenchForm.skill_prompt",
    "aiWorkbenchForm.timeframe",
    "aiWorkbenchForm.max_symbols",
    "aiWorkbenchForm.max_rows",
}

_UI_PERCENT_TARGETS = {
    "regimeForm.benchmark_rally_60_threshold",
    "regimeForm.benchmark_pullback_20_threshold",
    "regimeForm.pullback_20_threshold",
    "regimeForm.pullback_60_threshold",
    "regimeForm.liquidity_high_percentile",
    "regimeForm.liquidity_mid_percentile",
    "regimeForm.liquidity_low_percentile",
    "regimeForm.volatility_high_percentile",
    "regimeForm.volatility_low_percentile",
    "regimeForm.high_position_drawdown_threshold",
    "regimeForm.high_position_return_percentile",
    "regimeForm.leader_return_5d_threshold",
    "regimeForm.stress_ma20_break_threshold",
    "regimeForm.stress_return_5d_threshold",
    "regimeForm.cash_stress_score_threshold",
    "regimeForm.cash_preference_proxy_threshold",
    "regimeForm.risk_expansion_breadth_threshold",
    "regimeForm.risk_contraction_breadth_threshold",
    "regimeForm.risk_release_breadth_threshold",
    "regimeForm.high_liquidity_selloff_threshold",
}
_NUMERIC_TARGETS = {
    *_UI_PERCENT_TARGETS,
    "reviewForm.min_swing_return",
    "etfTrackerForm.min_swing_return",
}
_INTEGER_TARGETS = {
    "settings.batch_size",
    "historyForm.window_size",
    "historyForm.top_n",
    "historyForm.candidate_n",
    "historyForm.exclusion_bars",
    "historyForm.nearby_gap_days",
    "crossForm.top_n",
    "crossForm.date_tolerance_bars",
    "crossForm.exclusion_bars",
    "reviewForm.min_segment_bars",
    "etfTrackerForm.top_n",
    "etfTrackerForm.min_segment_bars",
    "aiWorkbenchForm.max_symbols",
    "aiWorkbenchForm.max_rows",
}
_BOOLEAN_TARGETS = {
    "settings.strict_after_update",
    "reviewForm.enable_ai_review",
    "etfTrackerForm.merge_similar",
}
_STRING_ENUM_TARGETS = {
    "settings.mode": {"smart", "force"},
    "settings.adjust": {"qfq", "hfq", ""},
    "cacheFilters.assetType": {"", "stock", "etf", "index", "other"},
    "cacheFilters.timeframe": {"", "1d", "1m", "5m", "15m", "30m", "60m"},
    "cacheFilters.status": {"", "cached", "missing_file", "read_error", "missing_columns", "no_valid_rows"},
    "crossForm.search_mode": {"same_date", "traversal"},
    "etfTrackerForm.category": {"all", "industry", "theme", "broad", "bond", "other"},
    "etfTrackerForm.type": {"", "股票型", "其他型"},
    "aiWorkbenchForm.timeframe": {"1d", "1m", "5m", "15m", "30m", "60m"},
}


_RISK_PERCENT_FIELDS = {
    "regimeForm.benchmark_rally_60_threshold": ("基准60日涨幅", "基准 60 日涨幅"),
    "regimeForm.benchmark_pullback_20_threshold": ("基准20日回撤", "基准 20 日回撤"),
    "regimeForm.pullback_20_threshold": ("20日回撤阈值", "20日回撤"),
    "regimeForm.pullback_60_threshold": ("60日回撤阈值", "60日回撤"),
    "regimeForm.liquidity_high_percentile": ("高流动性分位", "高流动性"),
    "regimeForm.liquidity_mid_percentile": ("中盘起始分位", "中盘分位"),
    "regimeForm.liquidity_low_percentile": ("低流动性分位", "低流动性"),
    "regimeForm.volatility_high_percentile": ("高波动分位", "高波动"),
    "regimeForm.volatility_low_percentile": ("低波动分位", "低波动"),
    "regimeForm.high_position_drawdown_threshold": ("高位回撤阈值", "高位回撤"),
    "regimeForm.high_position_return_percentile": ("高位涨幅分位", "高位涨幅"),
    "regimeForm.leader_return_5d_threshold": ("领涨5日阈值", "领涨5日"),
    "regimeForm.stress_ma20_break_threshold": ("压力破位阈值", "压力破位"),
    "regimeForm.stress_return_5d_threshold": ("压力收益阈值", "压力收益"),
    "regimeForm.cash_stress_score_threshold": ("现金压力分", "现金压力"),
    "regimeForm.cash_preference_proxy_threshold": ("现金偏好阈值", "现金偏好"),
    "regimeForm.risk_expansion_breadth_threshold": ("扩张宽度", "风险扩张宽度"),
    "regimeForm.risk_contraction_breadth_threshold": ("收缩宽度", "风险收缩宽度"),
    "regimeForm.risk_release_breadth_threshold": ("释放后段宽度", "风险释放宽度"),
    "regimeForm.high_liquidity_selloff_threshold": ("高流动性抛售", "高流动性破位"),
}


def _percent_after_any_label(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        value = _first_percent_number(text[index + len(label) : index + len(label) + 24])
        if value is not None:
            return value
    return None


def _first_percent_number(text: str) -> float | None:
    normalized = text.replace("％", "%").replace("负", "-")
    match = re.search(r"-?\d+(?:\.\d+)?\s*%?", normalized)
    if match:
        return float(match.group(0).replace("%", "").strip())
    return None


def _risk_patch(target: str, value: float, label: str) -> dict[str, Any]:
    return {
        "target": target,
        "value": value,
        "mode": "replace",
        "label": label,
        "summary": f"{label}设为 {value:g}%。",
    }


def _command_summary(text: str, patches: list[dict[str, Any]]) -> str:
    if not patches:
        return "未生成可应用动作。"
    labels = "；".join(str(patch.get("summary") or patch.get("label")) for patch in patches[:4])
    suffix = f"；另有 {len(patches) - 4} 项" if len(patches) > 4 else ""
    return f"已解析命令“{text[:36]}”：{labels}{suffix}"


def _stock_data_context(payload: AIStockAgentPayload) -> dict[str, Any]:
    symbols = normalize_symbol_tuple(payload.symbols)[: payload.max_symbols]
    if not symbols:
        raise ValueError("AI 股票数据接口至少需要 1 个标的代码。")
    bars = load_local_bars(
        data_root=payload.data_root,
        timeframe=payload.timeframe,
        adjust=payload.adjust,
        symbols=symbols,
        start=payload.start,
        end=payload.end,
    )
    if bars.empty:
        raise ValueError("所选标的在当前时间窗口没有本地行情。")
    names = resolve_symbol_names(list(symbols), data_root=payload.data_root)
    records = _records(bars.sort_values(["stock_code", "date"]), limit=payload.max_rows)
    return {
        "symbols": list(symbols),
        "symbol_names": names,
        "timeframe": payload.timeframe,
        "adjust": payload.adjust,
        "start": payload.start,
        "end": payload.end,
        "row_count": int(len(bars)),
        "record_limit": payload.max_rows,
        "records": records,
        "latest": _latest_stock_metrics(bars, names=names),
    }


def _latest_stock_metrics(bars: pd.DataFrame, *, names: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, frame in bars.sort_values("date").groupby("stock_code", sort=True):
        first = frame.iloc[0]
        latest = frame.iloc[-1]
        first_close = float(first["close"])
        latest_close = float(latest["close"])
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(str(symbol), ""),
                "date": latest["date"],
                "close": latest_close,
                "return": latest_close / first_close - 1.0 if first_close else None,
                "rows": int(len(frame)),
            }
        )
    return rows


def _stock_agent_messages(payload: AIStockAgentPayload, context: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是本地股票数据研究助手。只能基于用户提供的本地行情 JSON 与用户提示词回答；"
        "不要声称调用了外部行情、新闻或交易接口。输出需注明研究用途，不构成投资建议。"
    )
    skill = payload.skill_prompt.strip()
    prompt = payload.prompt.strip()
    if not prompt:
        raise ValueError("请填写 AI 模块提示词。")
    user_content = {
        "skill_prompt": skill,
        "user_prompt": prompt,
        "stock_data": context,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_content, ensure_ascii=False, default=str)},
    ]
