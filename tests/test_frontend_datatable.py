from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_VUE = ROOT / "web" / "src" / "App.vue"
DATA_TABLE = ROOT / "web" / "src" / "components" / "DataTable.vue"


def test_data_table_has_global_expand_sort_and_tone_behaviour() -> None:
    source = DATA_TABLE.read_text(encoding="utf-8")

    assert "DEFAULT_COMPACT_COLUMN_COUNT" in source
    assert "展开查看" in source
    assert "更多指标" in source
    assert "visibleColumns" in source
    assert "expanded" in source

    assert "sortState" in source
    assert "toggleSort" in source
    assert "sortedRows" in source
    assert "aria-sort" in source
    assert "升序" in source
    assert "降序" in source

    assert "cellTone" in source
    assert "cell-badge" in source
    for tone in ["tone-positive", "tone-negative", "tone-success", "tone-warning", "tone-danger", "tone-info"]:
        assert tone in source


def test_data_table_sorts_by_clicking_header_without_visible_sort_text() -> None:
    source = DATA_TABLE.read_text(encoding="utf-8")

    assert "return '排序'" not in source
    assert "sortIndicator" in source
    assert "sortAriaLabel" in source
    assert "↓" in source
    assert "↑" in source


def test_all_data_table_usages_share_the_component_surface() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert source.count("<DataTable ") >= 10
    assert "expandEtf" not in source
    assert "sortEtf" not in source


def test_etf_tracking_index_column_is_last() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    match = re.search(r"const etfTrackerColumns = \[(?P<body>.*?)\n\]", source, re.S)
    assert match is not None
    keys = re.findall(r"key: '([^']+)'", match.group("body"))

    assert keys[-1] == "跟踪指数"
