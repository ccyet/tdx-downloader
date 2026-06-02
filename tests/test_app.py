from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import (
    DEFAULT_TIMEFRAMES,
    SYMBOL_PREVIEW_PAGE_SIZE,
    _date_range_label,
    _date_range_values,
    _execution_mode_label,
    _filter_symbols_by_keyword,
    _force_cli_frame,
    _parse_cli_table,
    _parallels_prepare_command,
    _source_option_label,
    _subtract_years,
    _symbol_preview_frame,
    _symbol_preview_page,
    _symbols_from_text,
    _symbols_from_uploaded_file,
)
import app as tdx_app
from tdx_downloader.data.manager import DataDownloadConfig, DataManagementService


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
    assert any(item.label == "行情根目录路径" for item in app.text_input)
    assert any(item.label == "TDX PYPlugins/user路径" for item in app.text_input)
    assert sum(1 for button in app.button if button.label == "选择文件夹") >= 2
    assert any(item.label == "代码来源" for item in app.selectbox)
    assert DEFAULT_TIMEFRAMES == ("1d",)
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
    for label in ("数据范围", "下载任务", "本地缓存", "执行记录", "设置"):
        assert any(button.label == label for button in app.button)
    date_range = next(item for item in app.selectbox if item.label == "日期快捷")
    assert date_range.options == ["近 N 天", "年初至今", "近 N 年", "自定义"]
    assert any(button.label == "扫描缓存" for button in app.button)
    assert any(button.label == "预览计划" for button in app.button)
    assert any(button.label == "执行下载" for button in app.button)


def test_workspace_buttons_switch_rendered_content() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))

    app.run(timeout=5)
    next(button for button in app.button if button.label == "本地缓存").click().run(timeout=5)

    assert not app.exception
    assert any("暂无缓存快照" in item.value for item in app.markdown)

    next(button for button in app.button if button.label == "设置").click().run(timeout=5)

    assert not app.exception
    assert any("下载参数" in item.value for item in app.markdown)


def test_manual_symbol_preview_uses_pagination() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))
    symbols = "\n".join(f"{index:06d}.SZ" for index in range(1, 13))

    app.run(timeout=5)
    next(item for item in app.selectbox if item.label == "代码来源").set_value("手动输入").run(timeout=5)
    next(item for item in app.text_area if item.label == "补充代码").set_value(symbols).run(timeout=5)

    assert not app.exception
    assert any(item.value == "第 1/2 页 · 每页最多 10 个 · 共 12 个" for item in app.caption)
    assert any(button.label == "下一页" for button in app.button)
    preview_html = next(item.value for item in app.markdown if '<table class="dataframe source-preview-table">' in item.value)
    assert preview_html.count("<tr>") == 10
    assert "000011.SZ" not in preview_html


def test_parallels_prepare_command_uses_cli_runtime() -> None:
    service = DataManagementService("/Volumes/ccOUT 1/tdx-data/daily", adjust="qfq")
    config = DataDownloadConfig(
        symbols=("000001.SZ", "600519.SH"),
        timeframes=("5m",),
        start="2026-06-01",
        end="2026-06-02",
        tqcenter_path="/Volumes/[C] Windows 11/new_tdx64/T0002/dlls",
        batch_size=50,
    )

    command = _parallels_prepare_command(service, config)

    assert command[:3] == [Path(command[0]).as_posix(), "-m", "tdx_downloader.cli"]
    assert "prepare-data" in command
    assert command[command.index("--runtime") + 1] == "parallels"
    assert command[command.index("--tdx-path") + 1] == "/Volumes/[C] Windows 11/new_tdx64/T0002/dlls"
    assert command[command.index("--timeframes") + 1] == "5m"


def test_default_tdx_path_prefers_mounted_parallels_pyplugins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidate = Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user")

    def fake_exists(path: Path) -> bool:
        return path == candidate / "tqcenter.py"

    monkeypatch.setattr(tdx_app.Path, "exists", fake_exists)

    assert tdx_app._default_tdx_path() == candidate


def test_default_tdx_path_uses_parallels_hint_on_mac_without_mount(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tdx_app.sys, "platform", "darwin")
    monkeypatch.setattr(tdx_app.Path, "exists", lambda _: False)

    assert tdx_app._default_tdx_path() == Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user")


def test_directory_picker_migrates_old_home_tdx_default() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))
    old_default = str(Path.home())

    app.session_state["dm_tdx_path_picker_v2_selected_path"] = old_default
    app.session_state["dm_tdx_path_picker_v2_path_input"] = old_default
    app.session_state["dm_tdx_path_picker_v2_default_path"] = old_default
    app.run(timeout=5)

    tdx_path_input = next(item for item in app.text_input if item.label == "TDX PYPlugins/user路径")

    assert tdx_path_input.value == "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"


def test_directory_picker_migrates_home_tdx_path_without_default_marker() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"))
    old_default = str(Path.home())

    app.session_state["dm_tdx_path_picker_v2_selected_path"] = old_default
    app.session_state["dm_tdx_path_picker_v2_path_input"] = old_default
    app.run(timeout=5)

    tdx_path_input = next(item for item in app.text_input if item.label == "TDX PYPlugins/user路径")

    assert tdx_path_input.value == "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"


def test_parse_cli_table_and_force_frame() -> None:
    frame = _parse_cli_table(
        "symbol  rows  new_rows      start        end  path\n"
        "000001.SZ     2         1 2026-06-01 2026-06-02  cache.parquet\n"
    )
    result = _force_cli_frame(frame, timeframe="5m", adjust="qfq")

    assert result.loc[0, "stock_code"] == "000001.SZ"
    assert result.loc[0, "timeframe"] == "5m"
    assert result.loc[0, "action"] == "fetched"


def test_clean_parallels_cli_error_removes_traceback() -> None:
    detail = (
        'Traceback (most recent call last):\n'
        '  File "K:\\tdx-downloader\\tdx_downloader\\cli.py", line 120, in main\n'
        "ValueError: 本地行情数据未通过质量门禁：000001.SZ/5m=missing_file(本地 parquet 不存在。)\n"
        "TQ数据接口初始化成功\n"
    )

    message = tdx_app._clean_parallels_cli_error(detail)

    assert "Traceback" not in message
    assert "ValueError" not in message
    assert "本地行情数据未通过质量门禁" in message
    assert "Windows 通达信" in message


def test_app_source_file_keeps_modern_guidance_and_cloud_boundaries() -> None:
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text()

    assert "数据下载与缓存管理" in source
    assert "智能补齐" in source
    assert "强制刷新" in source
    assert "nav = _render_sidebar_navigation()" in source
    assert "tkinter" not in source
    assert "osascript" in source
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


def test_symbol_preview_paginates_to_ten_rows_per_page() -> None:
    symbols = tuple(f"{index:06d}.SZ" for index in range(1, 24))

    page_symbols, current_page, total_pages, start_index = _symbol_preview_page(
        symbols,
        2,
        page_size=SYMBOL_PREVIEW_PAGE_SIZE,
    )
    frame = _symbol_preview_frame(page_symbols, start_index=start_index)

    assert len(page_symbols) == 10
    assert current_page == 2
    assert total_pages == 3
    assert frame["序号"].tolist() == list(range(11, 21))
    assert _symbol_preview_page(symbols, 9, page_size=SYMBOL_PREVIEW_PAGE_SIZE)[1] == 3


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
