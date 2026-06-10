from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_tdx_path_is_normalized_before_restore_pick_and_api_calls() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "function normalizeTdxPath" in source
    assert "settings.tdx_path = normalizeTdxPath(settings.tdx_path)" in source
    assert "saved.tdx_path = normalizeTdxPath(saved.tdx_path)" in source
    assert "normalizeTdxPath(data.path)" in source
    assert "last === 'pyplugins'" not in source
    assert "last.includes('new_tdx64')" not in source
    assert "parts.slice(0, -1)" in source


def test_docker_default_data_root_ignores_saved_macos_volume_path() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "function savedPathForCurrentRuntime" in source
    assert "currentDefault.startsWith('/data/')" in source
    assert "saved.startsWith('/Volumes/')" in source
    assert "if (!currentDefault && saved.startsWith('/Volumes/')) return ''" in source


def test_directory_picker_falls_back_to_container_browser() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "directoryBrowserOpen" in source
    assert "openDirectoryBrowser(field, extractErrorMessage(error))" in source
    assert "apiGet(`/directories?path=${query}`)" in source
    assert "使用当前目录" in source


def test_settings_exposes_external_api_examples() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "开放数据 API" in source
    assert "/prices/bars" in source
    assert "/ai/stock-agent" in source
    assert "skill_prompt" in source
