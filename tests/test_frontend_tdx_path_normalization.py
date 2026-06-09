from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_tdx_path_is_normalized_before_restore_pick_and_api_calls() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "function normalizeTdxPath" in source
    assert "settings.tdx_path = normalizeTdxPath(settings.tdx_path)" in source
    assert "saved.tdx_path = normalizeTdxPath(saved.tdx_path)" in source
    assert "normalizeTdxPath(data.path)" in source
    assert "PYPlugins${separator}user" in source
