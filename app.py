from __future__ import annotations

from datetime import date, timedelta
from html import escape
import io
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from tdx_downloader.data.manager import (
    DataCacheSnapshot,
    DataDownloadConfig,
    DataDownloadResult,
    DataManagementService,
    download_summary,
    normalize_symbol_tuple,
    shortcut_symbols,
)
from tdx_downloader.data.catalog import ASSET_TYPE_LABELS, asset_type_label, data_kind_label, indicator_label
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES

DEFAULT_DATA_ROOT = "/Volumes/ccOUT 1/tdx-data"
DEFAULT_TDX_PATH_CANDIDATES = (
    "/Volumes/[C] Windows 11/new_tdx64/PYPlugins",
)
NAV_ITEMS = ("数据范围", "下载任务", "本地缓存", "执行记录", "设置")
SYMBOL_PREVIEW_PAGE_SIZE = 10
NAV_DESCRIPTIONS = {
    "数据范围": "配置代码、周期、时间窗和补齐方式。",
    "下载任务": "查看下载计划和最近一次执行结果。",
    "本地缓存": "按资产类型与周期查看本地缓存。",
    "执行记录": "查看下载过程事件和写入结果。",
    "设置": "查看当前运行路径、TDX 参数和校验策略。",
}
DATA_RANGE_ANCHOR_ID = "tdx-data-range-panel"
WORKSPACE_ANCHOR_ID = "tdx-workspace-panel"
STATUS_LABELS = {
    "cached": "可用",
    "missing_file": "缺文件",
    "read_error": "读取失败",
    "missing_columns": "缺字段",
    "no_valid_rows": "无有效K线",
    "ok": "通过",
    "quality_error": "质量异常",
    "no_window_data": "窗口无数据",
    "ready": "准备完成",
    "partial": "部分可用",
    "empty": "无可用缓存",
}
ASSET_TYPE_OPTIONS = tuple(ASSET_TYPE_LABELS)
CACHE_ASSET_TABS = (("etf", "ETF"), ("stock", "个股"), ("index", "指数"), ("other", "其他"))
DATA_MANAGER_TIMEFRAMES = list(SUPPORTED_TIMEFRAMES)
DEFAULT_TIMEFRAMES = ("1d",)
TIMEFRAME_DEFAULT_VERSION = "single-1d"
SYMBOL_UPLOAD_COLUMNS = ("stock_code", "symbol", "code", "ticker", "证券代码", "代码")
SOURCE_OPTIONS = ("常用样例", "上传代码集", "手动输入", "当前缓存全部", "缓存按资产类型", "宽基指数", "ETF样例")
CACHE_SOURCE_OPTIONS = {"当前缓存全部", "缓存按资产类型"}
SOURCE_OPTION_LABELS = {
    "常用样例": "常用样例 · 4只",
    "上传代码集": "上传代码集 · CSV/TXT",
    "手动输入": "手动输入",
    "当前缓存全部": "当前缓存全部",
    "缓存按资产类型": "按资产类型筛选",
    "宽基指数": "宽基指数 · 6只",
    "ETF样例": "ETF样例 · 5只",
}
SOURCE_DESCRIPTIONS = {
    "常用样例": "内置核心个股样例，适合快速验证下载链路。",
    "上传代码集": "从 CSV/TXT 文件解析证券代码，适合一次性导入自定义代码池。",
    "手动输入": "不带入内置成分，只使用下方补充代码。",
    "当前缓存全部": "读取本地缓存索引中已有的全部代码。",
    "缓存按资产类型": "读取本地缓存索引，并按选择的资产类型过滤。",
    "宽基指数": "内置宽基指数样例。",
    "ETF样例": "内置 ETF 样例。",
}
EXECUTION_MODE_OPTIONS = ("smart", "force")
EXECUTION_MODE_LABELS = {
    "smart": "智能补齐 · 缺什么补什么",
    "force": "强制刷新 · 重新拉取覆盖",
}
EXECUTION_MODE_HELP = {
    "smart": "先检查本地缓存，只有缺文件、缺字段或覆盖不足才下载；适合日常更新。",
    "force": "跳过缓存判断，按当前代码、周期、时间窗重新拉取并写入；适合重建缓存或怀疑数据异常。",
}
DATE_RANGE_OPTIONS = ("recent_days", "year_to_date", "recent_years", "custom")
DATE_RANGE_LABELS = {
    "recent_days": "近 N 天",
    "year_to_date": "年初至今",
    "recent_years": "近 N 年",
    "custom": "自定义",
}
SYMBOL_NAME_HINTS = {
    "000001.SZ": "平安银行",
    "600519.SH": "贵州茅台",
    "300750.SZ": "宁德时代",
    "601318.SH": "中国平安",
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300",
    "000852.SH": "中证1000",
    "000905.SH": "中证500",
    "510300.SH": "沪深300ETF",
    "510500.SH": "中证500ETF",
    "159915.SZ": "创业板ETF",
    "588000.SH": "科创50ETF",
    "512100.SH": "中证1000ETF",
}
ACTION_LABELS = {
    "cached": "已有缓存",
    "fetch": "待下载",
    "fetched": "已下载",
}
STAGE_LABELS = {
    "audit_start": "审计缓存",
    "audit_done": "审计完成",
    "fetch_start": "请求 TDX",
    "tdx_request_start": "请求 TDX",
    "tdx_batch_start": "批次请求",
    "tdx_batch_done": "批次完成",
    "tdx_fallback_start": "5m 聚合补齐",
    "tdx_request_done": "请求完成",
    "write_start": "写入缓存",
    "write_done": "写入完成",
    "reaudit_start": "复核缓存",
    "reaudit_done": "复核完成",
    "fetch_skipped": "跳过下载",
    "prepare_done": "任务完成",
    "force_timeframe_start": "强制刷新",
    "force_timeframe_done": "刷新完成",
}
COLUMN_LABELS = {
    "stock_code": "代码",
    "stock_name": "名称",
    "asset_type": "资产类型",
    "asset_type_label": "资产类型",
    "data_kind": "数据种类",
    "indicator": "指标",
    "timeframe": "周期",
    "adjust": "复权",
    "status": "状态",
    "exists": "存在",
    "rows": "行数",
    "start": "开始",
    "end": "结束",
    "file_size_bytes": "文件大小",
    "modified_at": "修改时间",
    "missing_columns": "缺失字段",
    "path": "路径",
    "cache_key": "缓存键",
    "storage_format": "存储格式",
    "start_at": "开始",
    "end_at": "结束",
    "message": "说明",
    "action": "动作",
    "reason": "原因",
    "before_status": "补前状态",
    "after_status": "补后状态",
    "rows_written": "写入行数",
    "new_rows": "新增行数",
    "coverage_ratio": "覆盖率",
    "before_coverage_ratio": "补前覆盖率",
    "after_coverage_ratio": "补后覆盖率",
    "missing_rows": "缺失K数",
    "expected_rows": "理论K数",
    "rows_in_window": "窗口K数",
    "max_missing_gap_minutes": "最长缺口分钟",
    "first_missing_at": "首个缺口",
    "last_missing_at": "最后缺口",
    "total_count": "总项数",
    "cached_count": "可用项",
    "missing_count": "缺口项",
    "earliest_start_at": "最早开始",
    "latest_end_at": "最新结束",
}


def main() -> None:
    st.set_page_config(page_title="TDX Downloader", page_icon="TDX", layout="wide")
    _apply_styles()
    _init_state()

    with st.sidebar:
        _render_sidebar_brand()
        nav = _render_sidebar_navigation()
        st.divider()
        st.subheader("运行参数")
        data_root = _directory_picker("行情根目录", DEFAULT_DATA_ROOT, key="dm_data_root_picker")
        adjust = st.selectbox("复权", ["qfq", "hfq", ""], index=0, key="dm_adjust")
        use_default_tdx_path = st.checkbox("使用系统默认 TDX 路径", value=False, key="dm_use_default_tdx_path")
        tdx_path = (
            ""
            if use_default_tdx_path
            else str(_directory_picker("TDX PYPlugins 或根目录", _default_tdx_path(), key="dm_tdx_path_picker_v2"))
        )
        batch_size = int(
            st.number_input("TDX 批次大小", min_value=1, max_value=500, value=100, step=10, key="dm_batch_size")
        )
        strict_after_update = st.checkbox("补齐后严格校验", value=True, key="dm_strict_after_update")
        if sys.platform == "darwin":
            st.caption("Mac 本机不直接取 TDX；真实下载请在 Windows/Parallels 侧运行。")

    _render_header()
    service = DataManagementService(data_root, adjust=adjust)
    _render_panel_anchor(DATA_RANGE_ANCHOR_ID)
    layout_cols = st.columns([1.55, 1], gap="large")
    with layout_cols[0]:
        with st.container(border=True):
            scope = _render_scope_controls(service, tdx_path=tdx_path)
        _render_scope_inline_panel(scope)
    config = _download_config(
        scope=scope,
        tqcenter_path=tdx_path,
        batch_size=batch_size,
        strict_after_update=strict_after_update,
    )
    _scroll_to_selected_panel(nav)
    with layout_cols[1]:
        with st.container(border=True):
            _render_action_bar(service, scope=scope, config=config)
        _render_current_task_card(
            scope=scope,
            data_root=str(data_root),
            adjust=str(adjust),
            batch_size=batch_size,
            strict_after_update=strict_after_update,
        )
    _render_workspace(
        nav,
        data_root=str(data_root),
        tdx_path=tdx_path,
        adjust=str(adjust),
        batch_size=batch_size,
        strict_after_update=strict_after_update,
    )


def _render_sidebar_brand() -> None:
    st.markdown(
        """
        <div class="brand-block">
            <div class="brand-mark">TDX</div>
            <div>
                <div class="brand-title">TDX Downloader</div>
                <div class="brand-subtitle">数据下载与缓存管理</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _default_tdx_path() -> Path:
    for candidate in DEFAULT_TDX_PATH_CANDIDATES:
        path = Path(candidate)
        if any((path / relative).exists() for relative in ("tqcenter.py", "user/tqcenter.py", "sys/tqcenter.py")):
            return path
    if sys.platform == "darwin":
        return Path(DEFAULT_TDX_PATH_CANDIDATES[0])
    return Path.home()


def _render_sidebar_navigation() -> str:
    current = str(st.session_state.get("dm_nav", NAV_ITEMS[0]))
    if current not in NAV_ITEMS:
        current = NAV_ITEMS[0]
        st.session_state["dm_nav"] = current
    st.markdown('<div class="sidebar-nav-title">面板导航</div>', unsafe_allow_html=True)
    for item in NAV_ITEMS:
        clicked = st.button(
            item,
            key=f"dm_nav_button_{item}",
            help=NAV_DESCRIPTIONS[item],
            type="primary" if item == current else "secondary",
            use_container_width=True,
        )
        st.caption(NAV_DESCRIPTIONS[item])
        if clicked:
            st.session_state["dm_nav"] = item
            st.rerun()
    return current


def _render_panel_anchor(anchor_id: str) -> None:
    st.markdown(f'<div id="{anchor_id}" class="panel-anchor"></div>', unsafe_allow_html=True)


def _scroll_to_selected_panel(nav: str) -> None:
    target_id = DATA_RANGE_ANCHOR_ID if nav == "数据范围" else WORKSPACE_ANCHOR_ID
    components.html(
        f"""
        <script>
        const target = window.parent.document.getElementById("{target_id}");
        if (target) {{
            requestAnimationFrame(() => target.scrollIntoView({{
                block: "start",
                behavior: "smooth"
            }}));
        }}
        </script>
        """,
        height=0,
    )


def _render_header() -> None:
    st.markdown(
        """
        <section class="app-header">
            <div>
                <h1>数据下载与缓存管理</h1>
                <p>面向 TDX 行情的独立工作台：先定范围，再预览计划，最后批量写入本地 parquet 缓存。</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _directory_picker(label: str, default: str | Path, *, key: str, disabled: bool = False) -> Path:
    selected_key = f"{key}_selected_path"
    input_key = f"{key}_path_input"
    default_key = f"{key}_default_path"
    default_path = Path(default).expanduser()

    previous_default = st.session_state.get(default_key)
    default_text = str(default_path)
    if previous_default is not None and previous_default != default_text:
        if st.session_state.get(selected_key) == previous_default:
            st.session_state[selected_key] = default_text
        if st.session_state.get(input_key) == previous_default:
            st.session_state[input_key] = default_text
    elif key.startswith("dm_tdx_path_picker") and default_text != str(Path.home()):
        home_text = str(Path.home())
        if st.session_state.get(selected_key) == home_text:
            st.session_state[selected_key] = default_text
        if st.session_state.get(input_key) == home_text:
            st.session_state[input_key] = default_text
    st.session_state[default_key] = default_text
    st.session_state.setdefault(selected_key, default_text)
    st.session_state.setdefault(input_key, st.session_state[selected_key])

    st.markdown(f"**{label}**")
    action_cols = st.columns([1.7, 1])
    with action_cols[0]:
        if st.button(
            "选择文件夹",
            key=f"{key}_native_select",
            disabled=disabled,
            help="打开系统文件夹选择框",
            use_container_width=True,
        ):
            try:
                selected = _open_native_directory_dialog(st.session_state[selected_key], f"选择{label}")
            except RuntimeError as exc:
                st.warning(str(exc))
            else:
                if selected is not None:
                    st.session_state[selected_key] = str(selected)
                    st.session_state[input_key] = str(selected)
    with action_cols[1]:
        if st.button("默认", key=f"{key}_reset", disabled=disabled, help="恢复默认文件夹", use_container_width=True):
            st.session_state[selected_key] = str(default_path)
            st.session_state[input_key] = str(default_path)
    path_value = st.text_input(
        f"{label}路径",
        key=input_key,
        disabled=disabled,
        label_visibility="collapsed",
        placeholder="输入文件夹路径",
    ).strip()
    selected_path = Path(path_value or str(default_path)).expanduser()
    st.session_state[selected_key] = str(selected_path)
    st.caption("当前路径")
    st.code(_display_path(str(selected_path)), language="text")
    return selected_path


def _open_native_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    if sys.platform != "darwin":
        raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")

    script = """
on run argv
    set dialogPrompt to item 1 of argv
    set defaultPath to item 2 of argv
    set chosenFolder to choose folder with prompt dialogPrompt default location (POSIX file defaultPath)
    return POSIX path of chosenFolder
end run
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script, title, str(_existing_directory(Path(initial_directory)))],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("文件夹选择窗口超时，请重新点击选择。") from exc
    except OSError as exc:
        raise RuntimeError("无法打开系统文件夹选择窗口。") from exc

    stderr = result.stderr.strip()
    if result.returncode != 0:
        if "User canceled" in stderr or "用户已取消" in stderr:
            return None
        raise RuntimeError(stderr or "系统文件夹选择失败。")

    selected = result.stdout.strip()
    if not selected:
        return None
    return Path(selected).expanduser()


def _existing_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_dir():
        return expanded
    for parent in expanded.parents:
        if parent.exists() and parent.is_dir():
            return parent
    return Path.home()


def _display_path(value: str) -> str:
    path = Path(value).expanduser()
    home = Path.home()
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if str(relative) == "." else f"~/{relative}"


def _render_scope_controls(service: DataManagementService, *, tdx_path: str) -> dict[str, object]:
    st.markdown("#### 数据范围")
    top_cols = st.columns([1.4, 2.0, 1.5])
    with top_cols[0]:
        source = st.selectbox(
            "代码来源",
            SOURCE_OPTIONS,
            index=0,
            key="dm_symbol_source",
            format_func=_source_option_label,
        )
    with top_cols[1]:
        timeframes = st.multiselect("周期", DATA_MANAGER_TIMEFRAMES, default=DEFAULT_TIMEFRAMES, key="dm_tfs")
    with top_cols[2]:
        mode = st.selectbox(
            "执行方式",
            EXECUTION_MODE_OPTIONS,
            index=0,
            key="dm_mode",
            format_func=_execution_mode_label,
            help=_execution_mode_help_text(),
        )

    asset_filter: tuple[str, ...] = ()
    cache_keyword = ""
    if source == "缓存按资产类型":
        selected_asset_labels = st.multiselect(
            "资产类型",
            [ASSET_TYPE_LABELS[item] for item in ASSET_TYPE_OPTIONS],
            default=[ASSET_TYPE_LABELS["stock"]],
            key="dm_asset_filter",
        )
        asset_filter = tuple(
            key for key, label in ASSET_TYPE_LABELS.items() if label in set(selected_asset_labels)
        )
        if not asset_filter:
            st.warning("请先选择资产类型，再读取本地缓存代码。")
    if source in CACHE_SOURCE_OPTIONS:
        cache_keyword = st.text_input(
            "代码/名称筛选",
            "",
            key="dm_cache_symbol_keyword",
            placeholder="输入代码或名称关键词，例如 510300、ETF、沪深300",
        )

    shortcut = _shortcut_symbols(service, source=source, asset_types=asset_filter, timeframes=tuple(timeframes), tdx_path=tdx_path)
    uploaded_symbols = _render_uploaded_symbols(source)
    name_by_symbol = _symbol_name_lookup(service, tdx_path=tdx_path) if source in CACHE_SOURCE_OPTIONS else {}
    source_symbols = _filter_symbols_by_keyword(
        _merge_symbols(shortcut, uploaded_symbols),
        keyword=cache_keyword,
        name_by_symbol=name_by_symbol,
    )
    manual_default = "000001.SZ,600519.SH" if source == "手动输入" else ""
    _render_date_range_shortcuts(today=date.today())
    bottom_cols = st.columns([2.4, 1.1, 1.1, 1, 1.4])
    with bottom_cols[0]:
        symbols_text = st.text_area("补充代码", manual_default, height=76, key="dm_symbols")
    with bottom_cols[1]:
        start = str(st.date_input("开始", key="dm_start"))
    with bottom_cols[2]:
        end = str(st.date_input("结束", key="dm_end"))
    with bottom_cols[3]:
        min_coverage_input = st.number_input(
            "最低覆盖率",
            min_value=0.0,
            max_value=1.0,
            value=0.0,
            step=0.05,
            format="%.2f",
            key="dm_min_coverage",
        )
    manual_symbols = _symbols_from_text(symbols_text)
    combined_symbols = _merge_symbols(source_symbols, manual_symbols)
    with bottom_cols[4]:
        st.metric("已选标的", _int_metric(len(combined_symbols)))
    return {
        "source": source,
        "source_symbols": source_symbols,
        "manual_symbols": manual_symbols,
        "symbols_text": symbols_text,
        "symbols": combined_symbols,
        "timeframes": tuple(timeframes),
        "start": start,
        "end": end,
        "min_coverage_ratio": float(min_coverage_input) if float(min_coverage_input) > 0 else None,
        "mode": str(mode),
        "asset_types": asset_filter,
        "keyword": cache_keyword,
        "name_by_symbol": name_by_symbol,
    }


def _source_option_label(source: object) -> str:
    return SOURCE_OPTION_LABELS.get(str(source), str(source))


def _execution_mode_label(mode: object) -> str:
    return EXECUTION_MODE_LABELS.get(str(mode), str(mode))


def _execution_mode_help_text() -> str:
    return "\n".join(f"{EXECUTION_MODE_LABELS[key]}：{EXECUTION_MODE_HELP[key]}" for key in EXECUTION_MODE_OPTIONS)


def _date_range_label(mode: object) -> str:
    return DATE_RANGE_LABELS.get(str(mode), str(mode))


def _render_date_range_shortcuts(*, today: date) -> None:
    st.session_state.setdefault("dm_start", today - timedelta(days=20))
    st.session_state.setdefault("dm_end", today)
    range_cols = st.columns([1.2, 1, 3.2])
    with range_cols[0]:
        mode = st.selectbox(
            "日期快捷",
            DATE_RANGE_OPTIONS,
            index=0,
            key="dm_date_range_mode",
            format_func=_date_range_label,
        )
    days = int(st.session_state.get("dm_recent_days", 20))
    years = int(st.session_state.get("dm_recent_years", 1))
    with range_cols[1]:
        if mode == "recent_days":
            days = int(st.number_input("N 天", min_value=1, max_value=3650, value=days, step=1, key="dm_recent_days"))
        elif mode == "recent_years":
            years = int(st.number_input("N 年", min_value=1, max_value=20, value=years, step=1, key="dm_recent_years"))
        else:
            st.empty()
    with range_cols[2]:
        st.caption("快捷会填入开始/结束日期；日期框仍可手动调整。")
    if mode == "custom":
        st.session_state["dm_date_range_signature"] = ("custom",)
        return
    signature = (mode, days, years, today.isoformat())
    if st.session_state.get("dm_date_range_signature") == signature:
        return
    start, end = _date_range_values(str(mode), days=days, years=years, today=today)
    st.session_state["dm_start"] = start
    st.session_state["dm_end"] = end
    st.session_state["dm_date_range_signature"] = signature


def _date_range_values(mode: str, *, days: int, years: int, today: date) -> tuple[date, date]:
    if mode == "recent_days":
        return today - timedelta(days=max(days, 1)), today
    if mode == "year_to_date":
        return date(today.year, 1, 1), today
    if mode == "recent_years":
        return _subtract_years(today, max(years, 1)), today
    return today - timedelta(days=20), today


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _render_uploaded_symbols(source: str) -> tuple[str, ...]:
    if source != "上传代码集":
        return ()
    uploaded_file = st.file_uploader(
        "上传代码集",
        type=["csv", "txt"],
        accept_multiple_files=False,
        key="dm_symbol_upload",
        help="CSV 优先读取 stock_code/code/symbol/代码/证券代码 列；TXT 支持换行、逗号、空格分隔。",
    )
    if uploaded_file is None:
        return ()
    try:
        symbols = _symbols_from_uploaded_file(uploaded_file)
    except ValueError as exc:
        st.error(str(exc))
        return ()
    st.caption(f"已解析 {len(symbols)} 个代码。")
    return symbols


def _render_source_constituents(
    *,
    source: str,
    source_symbols: tuple[str, ...],
    manual_symbols: tuple[str, ...],
    combined_symbols: tuple[str, ...],
    keyword: str = "",
    name_by_symbol: dict[str, str] | None = None,
) -> None:
    st.markdown("##### 代码来源成分")
    st.caption(SOURCE_DESCRIPTIONS.get(source, ""))
    symbols_to_show = manual_symbols if source == "手动输入" else source_symbols
    if source in CACHE_SOURCE_OPTIONS:
        _render_cache_source_summary(symbols_to_show, keyword=keyword, name_by_symbol=name_by_symbol or {})
        if manual_symbols:
            st.caption(f"补充代码已合并 {len(manual_symbols)} 个；合计已选 {len(combined_symbols)} 个。")
        return
    if symbols_to_show:
        _render_symbol_preview_paginated(
            symbols_to_show,
            name_by_symbol=name_by_symbol,
            key=f"dm_source_preview_{source}",
        )
    elif source == "上传代码集":
        st.info("上传 CSV/TXT 后展示解析出的代码。")
    elif source == "手动输入":
        st.info("在“补充代码”输入后展示手动代码。")
    else:
        st.info("当前来源未读取到代码。")
    if manual_symbols and source != "手动输入":
        st.caption(f"补充代码已合并 {len(manual_symbols)} 个；合计已选 {len(combined_symbols)} 个。")


def _render_scope_inline_panel(scope: dict[str, object]) -> None:
    with st.container(border=True):
        st.markdown("##### 代码池与范围")
        metric_cols = st.columns(4)
        metric_cols[0].metric("来源代码", _int_metric(len(tuple(scope["source_symbols"]))))
        metric_cols[1].metric("补充代码", _int_metric(len(tuple(scope["manual_symbols"]))))
        metric_cols[2].metric("合计标的", _int_metric(len(tuple(scope["symbols"]))))
        metric_cols[3].metric("周期数", _int_metric(len(tuple(scope["timeframes"]))))
        _render_source_constituents(
            source=str(scope["source"]),
            source_symbols=tuple(scope["source_symbols"]),
            manual_symbols=tuple(scope["manual_symbols"]),
            combined_symbols=tuple(scope["symbols"]),
            keyword=str(scope["keyword"]),
            name_by_symbol=dict(scope["name_by_symbol"]),
        )


def _render_cache_source_summary(
    symbols: tuple[str, ...],
    *,
    keyword: str,
    name_by_symbol: dict[str, str],
) -> None:
    metric_cols = st.columns(3)
    metric_cols[0].metric("匹配代码", _int_metric(len(symbols)))
    metric_cols[1].metric("名称可识别", _int_metric(sum(1 for symbol in symbols if _symbol_name(symbol, name_by_symbol))))
    metric_cols[2].metric("筛选条件", keyword.strip() or "未输入")
    if not symbols:
        st.info("未匹配到代码。请选择资产类型或输入更准确的代码/名称关键词。")
        return
    if not keyword.strip() and len(symbols) > 80:
        st.info("当前匹配数量较大，不展示任意明细；请用代码/名称筛选缩小范围，或直接执行全量任务。")
        return
    st.markdown("##### 命中示例")
    _render_symbol_preview_paginated(symbols, name_by_symbol=name_by_symbol, key="dm_cache_source_preview")


def _render_symbol_preview_paginated(
    symbols: tuple[str, ...],
    *,
    name_by_symbol: dict[str, str] | None = None,
    key: str,
    page_size: int = SYMBOL_PREVIEW_PAGE_SIZE,
) -> None:
    signature_key = f"{key}_signature"
    page_key = f"{key}_page"
    signature = (len(symbols), symbols[:page_size], symbols[-page_size:])
    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[page_key] = 1

    page_symbols, current_page, total_pages, start_index = _symbol_preview_page(
        symbols,
        int(st.session_state.get(page_key, 1)),
        page_size=page_size,
    )
    st.session_state[page_key] = current_page

    if total_pages > 1:
        nav_cols = st.columns([1, 1, 2.2])
        if nav_cols[0].button("上一页", key=f"{key}_prev", disabled=current_page <= 1, use_container_width=True):
            st.session_state[page_key] = max(1, current_page - 1)
            st.rerun()
        if nav_cols[1].button("下一页", key=f"{key}_next", disabled=current_page >= total_pages, use_container_width=True):
            st.session_state[page_key] = min(total_pages, current_page + 1)
            st.rerun()
        nav_cols[2].caption(f"第 {current_page}/{total_pages} 页 · 每页最多 {page_size} 个 · 共 {len(symbols)} 个")

    st.markdown(
        _symbol_preview_html(
            _symbol_preview_frame(page_symbols, name_by_symbol=name_by_symbol, start_index=start_index)
        ),
        unsafe_allow_html=True,
    )


def _symbol_preview_page(
    symbols: tuple[str, ...],
    page: int,
    *,
    page_size: int = SYMBOL_PREVIEW_PAGE_SIZE,
) -> tuple[tuple[str, ...], int, int, int]:
    total_pages = max(1, (len(symbols) + page_size - 1) // page_size)
    current_page = min(max(page, 1), total_pages)
    start = (current_page - 1) * page_size
    return symbols[start : start + page_size], current_page, total_pages, start + 1


def _symbol_preview_frame(
    symbols: tuple[str, ...],
    *,
    name_by_symbol: dict[str, str] | None = None,
    start_index: int = 1,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"序号": index, "代码": symbol, "名称": _symbol_name(symbol, name_by_symbol or {})}
            for index, symbol in enumerate(symbols, start=start_index)
        ]
    )


def _symbol_preview_html(frame: pd.DataFrame) -> str:
    return frame.to_html(index=False, escape=True, classes="source-preview-table", border=0)


def _symbol_name(symbol: str, name_by_symbol: dict[str, str]) -> str:
    return name_by_symbol.get(symbol, "") or SYMBOL_NAME_HINTS.get(symbol, "")


def _symbol_name_lookup(service: DataManagementService, *, tdx_path: str) -> dict[str, str]:
    try:
        metadata = service.repository.symbol_metadata(tdx_path=tdx_path)
    except Exception as exc:
        st.caption(f"未读取到代码名称索引，本次仅按代码匹配：{exc}")
        return {}
    if metadata.empty or not {"stock_code", "stock_name"}.issubset(metadata.columns):
        return {}
    return {
        str(row.stock_code): str(row.stock_name)
        for row in metadata.loc[:, ["stock_code", "stock_name"]].itertuples(index=False)
        if str(row.stock_code) and str(row.stock_name)
    }


def _filter_symbols_by_keyword(
    symbols: tuple[str, ...],
    *,
    keyword: str,
    name_by_symbol: dict[str, str],
) -> tuple[str, ...]:
    normalized = keyword.strip().upper()
    if not normalized:
        return symbols
    return tuple(
        symbol
        for symbol in symbols
        if normalized in symbol.upper() or normalized in _symbol_name(symbol, name_by_symbol).upper()
    )


def _render_action_bar(
    service: DataManagementService,
    *,
    scope: dict[str, object],
    config: DataDownloadConfig,
) -> None:
    st.markdown(
        f"""
        <div class="action-panel-title">
            <span>执行操作</span>
            <span class="help-dot" title="{escape(_execution_mode_help_text(), quote=True)}">?</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns(4)
    with action_cols[0]:
        scan_clicked = st.button("扫描缓存", use_container_width=True, help="只刷新本地缓存状态，不下载。")
    with action_cols[1]:
        plan_clicked = st.button("预览计划", use_container_width=True, help="可选步骤，只预览将下载哪些数据，不写入。")
    with action_cols[2]:
        run_clicked = st.button("执行下载", type="primary", use_container_width=True, help="按当前执行方式下载并写入缓存。")
    with action_cols[3]:
        clear_clicked = st.button("清空结果", use_container_width=True)

    if clear_clicked:
        _clear_results()
        st.rerun()
    if scan_clicked:
        _scan_cache(service, scope=scope, tdx_path=config.tqcenter_path)
    if plan_clicked:
        _generate_plan(service, config)
    if run_clicked:
        _run_download(service, config, mode=str(scope["mode"]))


def _render_current_task_card(
    *,
    scope: dict[str, object],
    data_root: str,
    adjust: str,
    batch_size: int,
    strict_after_update: bool,
) -> None:
    timeframes = tuple(scope["timeframes"])
    timeframe_label = "、".join(str(item) for item in timeframes) if timeframes else "未选择"
    coverage = scope.get("min_coverage_ratio")
    coverage_label = "不限制" if coverage is None else f"{float(coverage):.2%}"
    mode_label = _execution_mode_label(scope.get("mode"))
    strict_label = "开启" if strict_after_update else "关闭"
    st.markdown(
        f"""
        <div class="status-card">
            <div class="status-card-title">当前任务</div>
            <div class="status-grid">
                <div><span>标的</span><strong>{_int_metric(len(tuple(scope["symbols"])))}</strong></div>
                <div><span>周期</span><strong>{escape(timeframe_label)}</strong></div>
                <div><span>时间窗</span><strong>{escape(str(scope["start"]))} - {escape(str(scope["end"]))}</strong></div>
                <div><span>方式</span><strong>{escape(mode_label)}</strong></div>
                <div><span>最低覆盖</span><strong>{escape(coverage_label)}</strong></div>
                <div><span>复核</span><strong>{strict_label}</strong></div>
            </div>
            <div class="status-path">{escape(_display_path(data_root))}</div>
            <div class="status-foot">复权 {escape(adjust or "不复权")} · 批次 {batch_size}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_workspace(
    nav: str,
    *,
    data_root: str,
    tdx_path: str,
    adjust: str,
    batch_size: int,
    strict_after_update: bool,
) -> None:
    if nav == "数据范围":
        return
    _render_panel_anchor(WORKSPACE_ANCHOR_ID)
    st.markdown(
        f"""
        <section class="workspace-header">
            <div>
                <span class="workspace-kicker">工作区</span>
                <h2>{escape(nav)}</h2>
            </div>
            <p>{escape(NAV_DESCRIPTIONS.get(nav, ""))}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if nav == "下载任务":
        _render_download_workspace()
    elif nav == "本地缓存":
        _render_cache_workspace()
    elif nav == "执行记录":
        _render_execution_workspace()
    elif nav == "设置":
        _render_settings_workspace(
            data_root=data_root,
            tdx_path=tdx_path,
            adjust=adjust,
            batch_size=batch_size,
            strict_after_update=strict_after_update,
        )


def _render_download_workspace() -> None:
    plan = st.session_state.get("dm_plan")
    result = st.session_state.get("dm_result")
    workspace_cols = st.columns(2, gap="large")
    with workspace_cols[0]:
        with st.container(border=True):
            st.markdown("##### 下载计划")
            if isinstance(plan, pd.DataFrame) and not plan.empty:
                _render_plan(plan)
            else:
                _render_empty_state("暂无下载计划", "点击右侧“预览计划”后，这里会显示待下载和已缓存明细。")
    with workspace_cols[1]:
        with st.container(border=True):
            st.markdown("##### 最近执行")
            if isinstance(result, DataDownloadResult):
                _render_download_result(result)
            else:
                _render_empty_state("暂无执行结果", "点击“执行下载”后，这里会显示写入行数、下载项和结果表。")


def _render_cache_workspace() -> None:
    snapshot = st.session_state.get("dm_snapshot")
    if isinstance(snapshot, DataCacheSnapshot):
        _render_snapshot(snapshot)
        return
    with st.container(border=True):
        _render_empty_state("暂无缓存快照", "点击右侧“扫描缓存”后，这里会按 ETF、个股、指数和周期展示本地数据。")


def _render_execution_workspace() -> None:
    result = st.session_state.get("dm_result")
    events = st.session_state.get("dm_events", [])
    workspace_cols = st.columns([1, 1.25], gap="large")
    with workspace_cols[0]:
        with st.container(border=True):
            st.markdown("##### 写入结果")
            if isinstance(result, DataDownloadResult):
                _render_download_result(result)
            else:
                _render_empty_state("暂无写入结果", "执行下载后会显示处理项、下载项、新增行和写入行。")
    with workspace_cols[1]:
        with st.container(border=True):
            st.markdown("##### 过程记录")
            if events:
                st.dataframe(_display_table(pd.DataFrame(events)).tail(120), use_container_width=True, hide_index=True)
            else:
                _render_empty_state("暂无过程记录", "下载过程中的批次请求、写入和复核事件会显示在这里。")


def _render_settings_workspace(
    *,
    data_root: str,
    tdx_path: str,
    adjust: str,
    batch_size: int,
    strict_after_update: bool,
) -> None:
    settings_cols = st.columns(2, gap="large")
    with settings_cols[0]:
        with st.container(border=True):
            st.markdown("##### 路径")
            st.markdown(_key_value_html("行情根目录", _display_path(data_root)), unsafe_allow_html=True)
            st.markdown(_key_value_html("TDX PYPlugins 或根目录", _display_path(tdx_path) if tdx_path else "系统默认"), unsafe_allow_html=True)
    with settings_cols[1]:
        with st.container(border=True):
            st.markdown("##### 下载参数")
            st.markdown(_key_value_html("复权", adjust or "不复权"), unsafe_allow_html=True)
            st.markdown(_key_value_html("批次大小", str(batch_size)), unsafe_allow_html=True)
            st.markdown(_key_value_html("补齐后严格校验", "开启" if strict_after_update else "关闭"), unsafe_allow_html=True)
            if sys.platform == "darwin":
                st.info("Mac 本机只适合做配置和缓存管理；真实 TDX 下载请在 Windows/Parallels 侧运行。")


def _render_empty_state(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="empty-state">
            <strong>{escape(title)}</strong>
            <span>{escape(body)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _key_value_html(label: str, value: str) -> str:
    return f"""
    <div class="kv-row">
        <span>{escape(label)}</span>
        <strong>{escape(value)}</strong>
    </div>
    """


def _scan_cache(service: DataManagementService, *, scope: dict[str, object], tdx_path: str) -> None:
    with st.spinner("正在扫描本地缓存"):
        symbols = tuple(scope["symbols"]) or None
        snapshot = service.cache_snapshot(
            timeframes=tuple(scope["timeframes"]),
            symbols=symbols,
            asset_types=tuple(scope["asset_types"]),
            tdx_path=tdx_path,
        )
    st.session_state["dm_snapshot"] = snapshot


def _generate_plan(service: DataManagementService, config: DataDownloadConfig) -> None:
    if not config.symbols:
        st.error("预览计划需要标的代码。")
        return
    with st.spinner("正在生成补齐计划"):
        st.session_state["dm_plan"] = service.download_plan(config)


def _run_download(service: DataManagementService, config: DataDownloadConfig, *, mode: str) -> None:
    if not config.symbols:
        st.error("执行下载需要标的代码。")
        return
    progress = st.progress(0)
    status_box = st.empty()
    events: list[dict[str, object]] = []
    tracker = _ProgressTracker(total_steps=max(len(config.timeframes), 1), progress=progress, status_box=status_box)

    def on_progress(event: dict[str, object]) -> None:
        event_with_label = {**event, "label": _progress_label(event)}
        events.append(event_with_label)
        tracker.update(event)

    with st.spinner("正在执行数据任务"):
        try:
            if _should_use_parallels_runtime():
                on_progress({"stage": "tdx_request_start", "message": "通过 Parallels/Windows 调用通达信"})
                result = _run_download_via_parallels_cli(service, config, mode=mode)
                on_progress({"stage": "tdx_request_done", "message": "Parallels/Windows 通达信任务完成"})
            else:
                result = service.download(config, mode=mode, progress_callback=on_progress)
        except RuntimeError as exc:
            status_box.error("任务失败")
            st.error(str(exc))
            st.session_state["dm_events"] = events
            return
    progress.progress(1.0)
    status_box.success("任务完成")
    st.session_state["dm_result"] = result
    st.session_state["dm_events"] = events
    st.session_state["dm_snapshot"] = service.cache_snapshot(
        timeframes=config.timeframes,
        symbols=config.symbols,
        tdx_path=config.tqcenter_path,
    )
    st.session_state["dm_plan"] = service.download_plan(config)


def _should_use_parallels_runtime() -> bool:
    return sys.platform == "darwin"


def _run_download_via_parallels_cli(
    service: DataManagementService,
    config: DataDownloadConfig,
    *,
    mode: str,
) -> DataDownloadResult:
    if mode == "smart":
        table = _run_parallels_cli_table(_parallels_prepare_command(service, config))
    elif mode == "force":
        frames = [
            _force_cli_frame(
                _run_parallels_cli_table(_parallels_fetch_command(service, config, timeframe)),
                timeframe=timeframe,
                adjust=service.adjust,
            )
            for timeframe in config.timeframes
        ]
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        raise RuntimeError(f"未知下载方式：{mode}")
    return DataDownloadResult(table=table, summary=download_summary(table))


def _run_parallels_cli_table(command: list[str]) -> pd.DataFrame:
    try:
        result = subprocess.run(command, cwd=Path(__file__).resolve().parent, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"无法启动 Parallels/Windows 通达信任务：{exc}") from exc
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part).strip()
        raise RuntimeError(f"Parallels/Windows 通达信任务失败：{_clean_parallels_cli_error(detail)}")
    return _parse_cli_table(result.stdout)


def _clean_parallels_cli_error(detail: str) -> str:
    text = detail.strip()
    if not text:
        return "未返回错误详情"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    quality_line = next((line for line in reversed(lines) if "本地行情数据未通过质量门禁" in line), "")
    if quality_line:
        message = quality_line.split("ValueError:", 1)[-1].strip()
        return (
            f"{message}\n"
            "Windows 通达信没有返回当前窗口所需数据。若选择分钟周期，请先在 Windows 通达信内下载对应日期的分钟 K 线，"
            "或改用 1d / 已存在的分钟数据日期范围。"
        )
    exception_line = next(
        (
            line
            for line in reversed(lines)
            if line.startswith(("RuntimeError:", "ValueError:", "ModuleNotFoundError:", "ImportError:"))
        ),
        "",
    )
    if exception_line:
        return exception_line.split(":", 1)[-1].strip()
    return text.replace("Traceback (most recent call last):", "").strip()


def _parse_cli_table(stdout: str) -> pd.DataFrame:
    text = stdout.strip()
    if not text:
        return pd.DataFrame()
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    try:
        return pd.read_csv(io.StringIO(normalized), sep=r"\s{2,}", engine="python")
    except Exception as exc:
        raise RuntimeError(f"Parallels/Windows 任务已返回，但结果表解析失败：{exc}") from exc


def _parallels_prepare_command(service: DataManagementService, config: DataDownloadConfig) -> list[str]:
    command = _parallels_base_command(service, config, "prepare-data")
    command.extend(["--timeframes", ",".join(config.timeframes)])
    if config.min_coverage_ratio is not None:
        command.extend(["--min-coverage-ratio", str(config.min_coverage_ratio)])
    if not config.strict_after_update:
        command.append("--allow-incomplete-after-update")
    return command


def _parallels_fetch_command(service: DataManagementService, config: DataDownloadConfig, timeframe: str) -> list[str]:
    command = _parallels_base_command(service, config, "fetch")
    command.extend(["--timeframe", timeframe])
    return command


def _parallels_base_command(
    service: DataManagementService,
    config: DataDownloadConfig,
    command: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tdx_downloader.cli",
        command,
        "--runtime",
        "parallels",
        "--symbols",
        ",".join(config.symbols),
        "--start",
        config.start,
        "--end",
        config.end,
        "--adjust",
        service.adjust,
        "--data-root",
        str(service.data_root),
        "--tdx-path",
        config.tqcenter_path,
        "--batch-size",
        str(config.batch_size),
    ]


def _force_cli_frame(frame: pd.DataFrame, *, timeframe: str, adjust: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["stock_code", "timeframe", "adjust", "action", "rows_written", "new_rows"])
    result = frame.rename(columns={"symbol": "stock_code", "rows": "rows_written"}).copy()
    result["timeframe"] = timeframe
    result["adjust"] = adjust
    result["action"] = "fetched"
    return result


def _render_snapshot(snapshot: DataCacheSnapshot) -> None:
    summary = snapshot.summary
    first_metric_cols = st.columns(5)
    first_metric_cols[0].metric("标的数", _int_metric(summary.get("symbol_count")))
    first_metric_cols[1].metric("周期数", _int_metric(summary.get("timeframe_count")))
    first_metric_cols[2].metric("资产类型", _int_metric(summary.get("asset_type_count")))
    first_metric_cols[3].metric("数据集", _int_metric(summary.get("dataset_count")))
    first_metric_cols[4].metric("索引记录", _int_metric(summary.get("catalog_row_count")))
    second_metric_cols = st.columns(4)
    second_metric_cols[0].metric("可用缓存", _int_metric(summary.get("data_inventory_cached_count")))
    second_metric_cols[1].metric("不可用", _int_metric(summary.get("data_inventory_unavailable_count")))
    second_metric_cols[2].metric("总行数", _int_metric(summary.get("data_inventory_total_rows")))
    second_metric_cols[3].metric("文件体积", _format_bytes(summary.get("data_inventory_total_file_size_bytes")))

    _render_cache_readiness(snapshot.readiness)
    _render_classified_cache(snapshot.catalog)


def _render_cache_readiness(readiness: pd.DataFrame) -> None:
    st.markdown("##### 回测准备度")
    if readiness.empty:
        st.info("暂无准备度记录。先扫描缓存或选择更明确的数据范围。")
        return
    columns = [
        "timeframe",
        "asset_type_label",
        "status",
        "total_count",
        "cached_count",
        "missing_count",
        "coverage_ratio",
        "earliest_start_at",
        "latest_end_at",
        "message",
    ]
    st.dataframe(
        _display_table(readiness.loc[:, [column for column in columns if column in readiness.columns]]),
        use_container_width=True,
        hide_index=True,
    )


def _render_plan(plan: pd.DataFrame) -> None:
    action = plan["action"].fillna("").astype(str) if "action" in plan.columns else pd.Series(dtype=str)
    metric_cols = st.columns(4)
    metric_cols[0].metric("待下载", _int_metric(action.eq("fetch").sum()))
    metric_cols[1].metric("已可用", _int_metric(action.eq("cached").sum()))
    metric_cols[2].metric("缺失K数", _int_metric(pd.to_numeric(plan.get("missing_rows", 0), errors="coerce").sum()))
    metric_cols[3].metric("理论K数", _int_metric(pd.to_numeric(plan.get("expected_rows", 0), errors="coerce").sum()))
    st.dataframe(_display_table(plan), use_container_width=True, hide_index=True)


def _render_download_result(result: DataDownloadResult) -> None:
    summary = result.summary
    metric_cols = st.columns(4)
    metric_cols[0].metric("处理项", _int_metric(summary.get("row_count")))
    metric_cols[1].metric("下载项", _int_metric(summary.get("fetched_count")))
    metric_cols[2].metric("新增行", _int_metric(summary.get("new_rows")))
    metric_cols[3].metric("写入行", _int_metric(summary.get("rows_written")))
    if not result.table.empty:
        st.dataframe(_display_table(result.table), use_container_width=True, hide_index=True)


def _render_classified_cache(catalog: pd.DataFrame) -> None:
    st.markdown("##### 本地缓存分类")
    if catalog.empty:
        st.info("暂无缓存记录。")
        return
    labels = [f"{label} ({_catalog_file_count(catalog, asset_type=asset_type)})" for asset_type, label in CACHE_ASSET_TABS]
    for (asset_type, label), tab in zip(CACHE_ASSET_TABS, st.tabs(labels), strict=False):
        with tab:
            asset_frame = _catalog_filter(catalog, asset_type=asset_type)
            _render_cache_metric_cards(asset_frame)
            if asset_frame.empty:
                st.info(f"暂无{label}缓存记录。")
                continue
            _render_timeframe_cache_tabs(asset_frame)


def _render_cache_metric_cards(frame: pd.DataFrame) -> None:
    cached_count = _status_count(frame, "cached")
    file_count = len(frame)
    metric_cols = st.columns(5)
    metric_cols[0].metric("文件数", _int_metric(file_count))
    metric_cols[1].metric("可用", _int_metric(cached_count))
    metric_cols[2].metric("不可用", _int_metric(file_count - cached_count))
    metric_cols[3].metric("总行数", _int_metric(_numeric_sum(frame, "rows")))
    metric_cols[4].metric("文件体积", _format_bytes(_numeric_sum(frame, "file_size_bytes")))


def _render_timeframe_cache_tabs(frame: pd.DataFrame) -> None:
    timeframes = [timeframe for timeframe in DATA_MANAGER_TIMEFRAMES if not _catalog_filter(frame, timeframe=timeframe).empty]
    if not timeframes:
        st.info("暂无周期缓存记录。")
        return
    labels = [f"{timeframe} ({_catalog_file_count(frame, timeframe=timeframe)})" for timeframe in timeframes]
    for timeframe, tab in zip(timeframes, st.tabs(labels), strict=False):
        with tab:
            timeframe_frame = _catalog_filter(frame, timeframe=timeframe)
            _render_cache_metric_cards(timeframe_frame)
            st.dataframe(
                _display_table(_catalog_table_frame(timeframe_frame)),
                use_container_width=True,
                hide_index=True,
            )


def _catalog_filter(
    frame: pd.DataFrame,
    *,
    asset_type: str | None = None,
    timeframe: str | None = None,
) -> pd.DataFrame:
    result = frame
    if asset_type is not None and "asset_type" in result.columns:
        result = result.loc[result["asset_type"].astype(str).eq(asset_type)]
    if timeframe is not None and "timeframe" in result.columns:
        result = result.loc[result["timeframe"].astype(str).eq(timeframe)]
    return result.copy()


def _catalog_file_count(frame: pd.DataFrame, *, asset_type: str | None = None, timeframe: str | None = None) -> int:
    return len(_catalog_filter(frame, asset_type=asset_type, timeframe=timeframe))


def _status_count(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "status" not in frame.columns:
        return 0
    return int(frame["status"].fillna("").astype(str).eq(status).sum())


def _numeric_sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


class _ProgressTracker:
    def __init__(self, *, total_steps: int, progress, status_box) -> None:
        self.total_steps = total_steps
        self.progress = progress
        self.status_box = status_box
        self.current_step = 1

    def update(self, event: dict[str, object]) -> None:
        step_index = int(event.get("step_index") or self.current_step)
        self.current_step = min(max(step_index, 1), self.total_steps)
        ratio = self._ratio(event)
        self.progress.progress(min(max(ratio, 0.02), 0.98))
        self.status_box.info(_progress_label(event))

    def _ratio(self, event: dict[str, object]) -> float:
        stage = str(event.get("stage", ""))
        base = (self.current_step - 1) / self.total_steps
        unit = 1 / self.total_steps
        if stage.endswith("_done") or stage in {"fetch_skipped", "force_timeframe_done"}:
            return min(base + unit, 0.98)
        if stage == "tdx_batch_done":
            batch_index = int(event.get("batch_index") or 1)
            batch_count = max(int(event.get("batch_count") or 1), 1)
            return base + unit * (0.35 + 0.45 * batch_index / batch_count)
        if stage in {"write_start", "reaudit_start"}:
            return base + unit * 0.85
        if stage == "prepare_done":
            return 1.0
        return base + unit * 0.2


def _download_config(
    *,
    scope: dict[str, object],
    tqcenter_path: str,
    batch_size: int,
    strict_after_update: bool,
) -> DataDownloadConfig:
    return DataDownloadConfig(
        symbols=tuple(scope["symbols"]),
        timeframes=tuple(scope["timeframes"]),
        start=str(scope["start"]),
        end=str(scope["end"]),
        tqcenter_path=tqcenter_path,
        batch_size=batch_size,
        min_coverage_ratio=scope["min_coverage_ratio"],
        strict_after_update=strict_after_update,
    )


def _symbols_from_text(value: str) -> tuple[str, ...]:
    return normalize_symbol_tuple(tuple(item.strip() for item in re.split(r"[\s,;，；]+", value) if item.strip()))


def _symbols_from_uploaded_file(uploaded_file: object) -> tuple[str, ...]:
    name = str(getattr(uploaded_file, "name", "")).lower()
    getvalue = getattr(uploaded_file, "getvalue", None)
    if not callable(getvalue):
        raise ValueError("上传文件无法读取。")
    text = _decode_uploaded_text(getvalue())
    if not text.strip():
        raise ValueError("上传文件为空。")
    symbols = _symbols_from_csv_text(text) if name.endswith(".csv") else _symbols_from_text(text)
    if not symbols:
        raise ValueError("未解析到有效证券代码。")
    return symbols


def _decode_uploaded_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("上传文件编码无法识别，请使用 UTF-8 或 GB18030。")


def _symbols_from_csv_text(text: str) -> tuple[str, ...]:
    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str)
    except Exception as exc:
        raise ValueError(f"CSV 解析失败：{exc}") from exc
    column_by_normalized = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in SYMBOL_UPLOAD_COLUMNS:
        column = column_by_normalized.get(candidate.lower())
        if column is not None:
            return normalize_symbol_tuple(frame[column].dropna().astype(str).tolist())
    return _symbols_from_text(text)


def _shortcut_symbols(
    service: DataManagementService,
    *,
    source: str,
    asset_types: tuple[str, ...],
    timeframes: tuple[str, ...],
    tdx_path: str,
) -> tuple[str, ...]:
    if source == "当前缓存全部":
        return service.cached_symbols(timeframes=timeframes, tdx_path=tdx_path)
    if source == "缓存按资产类型":
        if not asset_types:
            return ()
        return service.cached_symbols(asset_types=asset_types, timeframes=timeframes, tdx_path=tdx_path)
    if source == "宽基指数":
        return shortcut_symbols("宽基指数")
    if source == "ETF样例":
        return shortcut_symbols("ETF样例")
    if source == "常用样例":
        return shortcut_symbols("核心样例")
    return ()


def _merge_symbols(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for symbol in group:
            if symbol in seen:
                continue
            seen.add(symbol)
            result.append(symbol)
    return tuple(result)


def _progress_label(event: dict[str, object]) -> str:
    stage = str(event.get("stage", ""))
    label = STAGE_LABELS.get(stage, stage)
    timeframe = str(event.get("timeframe") or "")
    batch_index = event.get("batch_index")
    batch_count = event.get("batch_count")
    if batch_index and batch_count:
        return f"{label} · {timeframe} · {batch_index}/{batch_count}"
    if timeframe:
        return f"{label} · {timeframe}"
    return label


def _display_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    for column in out.columns:
        if column in {"status", "before_status", "after_status", "reason"}:
            out[column] = out[column].map(lambda value: STATUS_LABELS.get(str(value), str(value)))
        elif column == "asset_type":
            out[column] = out[column].map(asset_type_label)
        elif column == "data_kind":
            out[column] = out[column].map(data_kind_label)
        elif column == "indicator":
            out[column] = out[column].map(indicator_label)
        elif column == "action":
            out[column] = out[column].map(lambda value: ACTION_LABELS.get(str(value), str(value)))
        elif column == "file_size_bytes":
            out[column] = out[column].map(_format_bytes)
        elif "coverage_ratio" in column:
            out[column] = pd.to_numeric(out[column], errors="coerce").map(lambda value: "" if pd.isna(value) else f"{value:.2%}")
        elif column.endswith("_at") or column in {"start", "end", "modified_at"}:
            out[column] = out[column].map(_format_time)
    return out.rename(columns={column: COLUMN_LABELS.get(str(column), str(column)) for column in out.columns})


def _catalog_table_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "stock_code",
        "stock_name",
        "asset_type",
        "data_kind",
        "indicator",
        "timeframe",
        "adjust",
        "status",
        "rows",
        "start_at",
        "end_at",
        "file_size_bytes",
        "modified_at",
        "path",
    ]
    return frame.loc[:, [column for column in columns if column in frame.columns]].copy()


def _format_time(value: object) -> str:
    if pd.isna(value) or str(value).strip() == "":
        return ""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return ""
    return timestamp.strftime("%Y-%m-%d %H:%M")


def _format_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        size = 0.0
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} {units[index]}"


def _int_metric(value: object) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return "0"


def _clear_results() -> None:
    for key in ("dm_snapshot", "dm_plan", "dm_result", "dm_events"):
        st.session_state.pop(key, None)


def _init_state() -> None:
    st.session_state.setdefault("dm_events", [])
    if st.session_state.get("dm_timeframe_default_version") == TIMEFRAME_DEFAULT_VERSION:
        return
    selected_timeframes = tuple(st.session_state.get("dm_tfs", ()))
    if not selected_timeframes or selected_timeframes == tuple(DATA_MANAGER_TIMEFRAMES):
        st.session_state["dm_tfs"] = list(DEFAULT_TIMEFRAMES)
    st.session_state["dm_timeframe_default_version"] = TIMEFRAME_DEFAULT_VERSION


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --tdx-bg: #f5f7f9;
            --tdx-surface: #ffffff;
            --tdx-surface-soft: #f8fafc;
            --tdx-border: #d7dee8;
            --tdx-text: #111827;
            --tdx-muted: #667085;
            --tdx-teal: #0f766e;
            --tdx-teal-soft: #e7f5f2;
            --tdx-amber: #b45309;
            --tdx-amber-soft: #fff7ed;
        }
        .stApp {
            background: var(--tdx-bg);
        }
        .block-container {
            padding-top: 1rem;
            padding-bottom: 2.5rem;
            max-width: 1440px;
        }
        h1, h2, h3, h4 {
            letter-spacing: 0;
            color: var(--tdx-text);
        }
        .app-header {
            display: flex;
            align-items: flex-end;
            gap: 24px;
            padding: 10px 2px 18px;
        }
        .app-header h1 {
            margin: 0;
            font-size: 2rem;
            line-height: 1.15;
            font-weight: 760;
            color: var(--tdx-text);
        }
        .app-header p {
            margin: 8px 0 0;
            color: var(--tdx-muted);
            font-size: 0.98rem;
            line-height: 1.6;
        }
        .brand-block {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 4px 0 12px;
        }
        .brand-mark {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            background: var(--tdx-teal);
            color: white;
            font-weight: 800;
            font-size: 0.86rem;
            letter-spacing: 0;
        }
        .brand-title {
            color: var(--tdx-text);
            font-weight: 760;
            line-height: 1.2;
        }
        .brand-subtitle {
            color: var(--tdx-muted);
            font-size: 0.82rem;
            margin-top: 2px;
        }
        .sidebar-nav-title {
            color: var(--tdx-text);
            font-size: 0.9rem;
            font-weight: 760;
            margin: 4px 0 8px;
        }
        .action-panel-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            color: var(--tdx-text);
            font-weight: 780;
            margin-bottom: 10px;
        }
        .help-dot {
            width: 20px;
            height: 20px;
            border: 1px solid #99c7c0;
            border-radius: 50%;
            display: inline-grid;
            place-items: center;
            color: var(--tdx-teal);
            background: var(--tdx-teal-soft);
            font-size: 0.78rem;
            font-weight: 800;
            cursor: help;
            flex: 0 0 auto;
        }
        .status-card {
            border: 1px solid var(--tdx-border);
            background: var(--tdx-surface);
            border-radius: 8px;
            padding: 14px 16px;
            margin-top: 14px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        .status-card-title {
            color: var(--tdx-text);
            font-weight: 780;
            margin-bottom: 12px;
        }
        .status-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .status-grid div,
        .kv-row {
            border: 1px solid #e4eaf2;
            background: var(--tdx-surface-soft);
            border-radius: 8px;
            padding: 10px 12px;
        }
        .status-grid span,
        .kv-row span {
            display: block;
            color: var(--tdx-muted);
            font-size: 0.78rem;
            line-height: 1.35;
        }
        .status-grid strong,
        .kv-row strong {
            display: block;
            color: var(--tdx-text);
            font-size: 0.95rem;
            margin-top: 4px;
            line-height: 1.35;
            word-break: break-word;
        }
        .status-path {
            margin-top: 12px;
            border: 1px dashed #cad6e3;
            border-radius: 8px;
            color: #475467;
            background: #fbfcfd;
            padding: 9px 10px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
            font-size: 0.82rem;
            overflow-wrap: anywhere;
        }
        .status-foot {
            margin-top: 10px;
            color: var(--tdx-muted);
            font-size: 0.84rem;
        }
        .workspace-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 24px;
            margin: 22px 0 12px;
            padding: 14px 16px;
            border: 1px solid var(--tdx-border);
            border-radius: 8px;
            background: linear-gradient(90deg, #ffffff 0%, #eef8f6 100%);
        }
        .workspace-header h2 {
            margin: 3px 0 0;
            font-size: 1.22rem;
            line-height: 1.25;
        }
        .workspace-header p {
            margin: 0;
            color: var(--tdx-muted);
            line-height: 1.55;
            text-align: right;
        }
        .workspace-kicker {
            color: var(--tdx-teal);
            font-size: 0.78rem;
            font-weight: 760;
        }
        .panel-anchor {
            scroll-margin-top: 12px;
        }
        .empty-state {
            border: 1px dashed #cbd5e1;
            background: #fbfcfd;
            border-radius: 8px;
            padding: 18px 16px;
        }
        .empty-state strong {
            display: block;
            color: var(--tdx-text);
            margin-bottom: 6px;
        }
        .empty-state span {
            color: var(--tdx-muted);
            line-height: 1.55;
        }
        .kv-row {
            margin-bottom: 10px;
        }
        div[data-testid="stMetric"] {
            background: var(--tdx-surface);
            border: 1px solid var(--tdx-border);
            border-radius: 8px;
            padding: 12px 14px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        div[data-testid="stMetricLabel"] {
            color: var(--tdx-muted);
        }
        div[data-testid="stMetricValue"] {
            color: var(--tdx-text);
            font-size: 1.35rem;
        }
        .stButton > button {
            align-items: center;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            display: flex;
            font-weight: 600;
            justify-content: center;
            min-height: 42px;
            text-align: center;
            white-space: nowrap;
        }
        .stButton > button p {
            margin: 0;
            white-space: nowrap;
        }
        .stButton > button[kind="primary"] {
            background: var(--tdx-teal);
            border-color: var(--tdx-teal);
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--tdx-border);
            border-radius: 8px;
            overflow: hidden;
        }
        table.source-preview-table {
            width: 100%;
            border-collapse: collapse;
            border: 1px solid var(--tdx-border);
            border-radius: 8px;
            overflow: hidden;
            font-size: 0.95rem;
        }
        table.source-preview-table th {
            background: var(--tdx-surface-soft);
            color: #475467;
            font-weight: 700;
            text-align: left;
            border-bottom: 1px solid var(--tdx-border);
            padding: 8px 10px;
        }
        table.source-preview-table td {
            border-bottom: 1px solid #edf2f7;
            padding: 8px 10px;
            color: var(--tdx-text);
        }
        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--tdx-border);
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label {
            border-radius: 8px;
            padding: 4px 6px;
        }
        span[data-baseweb="tag"] {
            background: var(--tdx-teal-soft) !important;
            border: 1px solid #99c7c0 !important;
        }
        span[data-baseweb="tag"] span {
            color: var(--tdx-text) !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--tdx-teal) !important;
        }
        div[data-baseweb="tab-highlight"] {
            background-color: var(--tdx-teal) !important;
        }
        div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--tdx-border);
            border-radius: 8px;
            background: var(--tdx-surface);
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        @media (max-width: 760px) {
            .app-header {
                align-items: flex-start;
                flex-direction: column;
            }
            .workspace-header {
                align-items: flex-start;
                flex-direction: column;
            }
            .workspace-header p {
                text-align: left;
            }
            .status-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
