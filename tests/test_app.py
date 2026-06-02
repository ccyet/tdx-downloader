from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import (
    DEFAULT_TIMEFRAMES,
    _date_range_label,
    _date_range_values,
    _execution_mode_label,
    _filter_symbols_by_keyword,
    _source_option_label,
    _subtract_years,
    _symbol_preview_frame,
    _symbols_from_text,
    _symbols_from_uploaded_file,
)


class _UploadedFile:
    def __init__(self, name: str, text: str, *, encoding: str = "utf-8") -> None:
        self.name = name
        self._payload = text.encode(encoding)

    def getvalue(self) -> bytes:
        return self._payload


def test_app_renders_standalone_tdx_downloader_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))

    app.run(timeout=5)

    assert not app.exception
    assert any("TDX Downloader" in item.value for item in app.markdown)
    assert not any(item.label == "行情根目录" for item in app.text_input)
    assert not any(item.label == "TDX PYPlugins/user" for item in app.text_input)
    assert any(button.label == "选择文件夹" for button in app.button)
    assert any(item.label == "代码来源" for item in app.selectbox)
    assert DEFAULT_TIMEFRAMES == ("5m",)
    timeframe = next(item for item in app.multiselect if item.label == "周期")
    assert timeframe.value == list(DEFAULT_TIMEFRAMES)
    source = next(item for item in app.selectbox if item.label == "代码来源")
    assert "上传代码集 · CSV/TXT" in source.options
    assert "ETF样例 · 5只" in source.options
    assert _source_option_label("ETF样例") == "ETF样例 · 5只"
    assert any(item.label == "执行方式" for item in app.selectbox)
    mode = next(item for item in app.selectbox if item.label == "执行方式")
    assert mode.options == ["智能补齐 · 缺什么补什么", "强制刷新 · 重新拉取覆盖"]
    assert _execution_mode_label("force") == "强制刷新 · 重新拉取覆盖"
    assert any(item.label == "工作区" for item in app.radio)
    workspace = next(item for item in app.radio if item.label == "工作区")
    assert workspace.options == list(("数据范围", "下载任务", "本地缓存", "执行记录", "设置"))
    date_range = next(item for item in app.selectbox if item.label == "日期快捷")
    assert date_range.options == ["近 N 天", "年初至今", "近 N 年", "自定义"]
    assert any(button.label == "扫描缓存" for button in app.button)
    assert any(button.label == "预览下载计划" for button in app.button)
    assert any(button.label == "执行下载" for button in app.button)


def test_workspace_radio_switches_rendered_content() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))

    app.run(timeout=5)
    app.radio[0].set_value("本地缓存").run(timeout=5)

    assert not app.exception
    assert any("暂无缓存快照" in item.value for item in app.markdown)

    app.radio[0].set_value("设置").run(timeout=5)

    assert not app.exception
    assert any("下载参数" in item.value for item in app.markdown)


def test_app_source_file_keeps_modern_guidance_and_cloud_boundaries() -> None:
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text()

    assert "数据下载与缓存管理" in source
    assert "智能补齐" in source
    assert "强制刷新" in source
    assert "nav = str(st.radio" in source
    assert "_render_workspace(" in source
    assert "工作区" in source
    assert "代码/名称筛选" in source
    assert "当前匹配数量较大，不展示任意明细" in source
    assert "st.file_uploader(" in source
    assert "altair_chart" not in source
    assert 'st.text_input("行情根目录"' not in source
    assert 'st.text_input("TDX PYPlugins/user"' not in source


def test_uploaded_symbol_files_parse_csv_and_txt() -> None:
    csv_symbols = _symbols_from_uploaded_file(
        _UploadedFile("symbols.csv", "stock_code,stock_name\n000001.SZ,平安银行\n600519.SH,贵州茅台\n")
    )
    txt_symbols = _symbols_from_uploaded_file(_UploadedFile("symbols.txt", "000001.SZ 600519.SH\n300750"))

    assert csv_symbols == ("000001.SZ", "600519.SH")
    assert txt_symbols == ("000001.SZ", "600519.SH", "300750.SZ")
    assert _symbols_from_text("000001.SZ;600519.SH，300750") == ("000001.SZ", "600519.SH", "300750.SZ")


def test_symbol_preview_and_cache_keyword_filter() -> None:
    frame = _symbol_preview_frame(("510300.SH", "159915.SZ"))
    symbols = ("510300.SH", "510500.SH", "000001.SZ")
    name_by_symbol = {"510300.SH": "沪深300ETF", "510500.SH": "中证500ETF", "000001.SZ": "平安银行"}

    assert frame.to_dict("records") == [
        {"序号": 1, "代码": "510300.SH", "名称": "沪深300ETF"},
        {"序号": 2, "代码": "159915.SZ", "名称": "创业板ETF"},
    ]
    assert _filter_symbols_by_keyword(symbols, keyword="ETF", name_by_symbol=name_by_symbol) == (
        "510300.SH",
        "510500.SH",
    )
    assert _filter_symbols_by_keyword(symbols, keyword="000001", name_by_symbol=name_by_symbol) == ("000001.SZ",)


def test_date_range_shortcuts_compute_expected_windows() -> None:
    today = date(2026, 6, 2)

    assert _date_range_label("recent_days") == "近 N 天"
    assert _date_range_values("recent_days", days=20, years=1, today=today) == (date(2026, 5, 13), today)
    assert _date_range_values("year_to_date", days=20, years=1, today=today) == (date(2026, 1, 1), today)
    assert _date_range_values("recent_years", days=20, years=3, today=today) == (date(2023, 6, 2), today)
    assert _subtract_years(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_uploaded_symbol_file_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="上传文件为空"):
        _symbols_from_uploaded_file(_UploadedFile("symbols.txt", ""))
