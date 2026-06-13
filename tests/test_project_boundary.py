from __future__ import annotations

from pathlib import Path


def test_new_project_does_not_import_original_trending_winning_package() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    paths = [*sorted((root / "tdx_downloader").rglob("*.py"))]
    legacy_app = root / "app.py"
    if legacy_app.exists():
        paths.append(legacy_app)
    for path in paths:
        text = path.read_text()
        if "trending_winning" in text:
            offenders.append(str(path.relative_to(root)))

    assert offenders == []
