from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any


def _open_native_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    if sys.platform == "darwin":
        return _open_macos_directory_dialog(initial_directory, title)
    if sys.platform.startswith("win"):
        return _open_windows_directory_dialog(initial_directory, title)
    raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")


def list_directory(path: str | Path = "") -> dict[str, Any]:
    directory = _directory_for_listing(path)
    entries: list[dict[str, Any]] = []
    try:
        children = list(directory.iterdir())
    except OSError as exc:
        raise RuntimeError(f"目录不可读取：{directory}") from exc
    for child in sorted(children, key=lambda item: (not item.is_dir(), item.name.lower())):
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "readable": _is_readable_directory(child),
            }
        )
    parent = directory.parent if directory.parent != directory else None
    return {
        "path": str(directory),
        "parent": str(parent) if parent is not None else None,
        "entries": entries,
        "entry_count": len(entries),
    }


def _open_macos_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    script = """
on run argv
    set dialogPrompt to item 1 of argv
    set defaultPath to item 2 of argv
    set chosenFolder to choose folder with prompt dialogPrompt default location (POSIX file defaultPath)
    return POSIX path of chosenFolder
end run
"""
    initial_path = Path(initial_directory) if str(initial_directory).strip() else Path.home()
    try:
        result = subprocess.run(
            ["osascript", "-e", script, title or "选择文件夹", str(_existing_directory(initial_path))],
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


def _open_windows_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    script = r"""
param(
    [string]$DialogTitle,
    [string]$InitialDirectory
)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $DialogTitle
$dialog.SelectedPath = $InitialDirectory
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $dialog.SelectedPath
    exit 0
}
if ($result -eq [System.Windows.Forms.DialogResult]::Cancel) {
    exit 2
}
exit 1
"""
    initial_path = Path(initial_directory) if str(initial_directory).strip() else Path.home()
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
                title or "选择文件夹",
                str(_existing_directory(initial_path)),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("文件夹选择窗口超时，请重新点击选择。") from exc
    except OSError as exc:
        raise RuntimeError("无法打开 Windows 文件夹选择窗口，请确认服务在当前桌面用户会话中启动。") from exc

    if result.returncode == 2:
        return None
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows 文件夹选择失败。")

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


def _directory_for_listing(path: str | Path) -> Path:
    raw = str(path or "").strip()
    if not raw:
        data_root = Path("/data")
        return data_root if data_root.exists() and data_root.is_dir() else Path.cwd()
    expanded = Path(raw).expanduser()
    if expanded.exists() and expanded.is_dir():
        return expanded
    if expanded.exists() and expanded.is_file():
        return expanded.parent
    return _existing_directory(expanded)


def _is_readable_directory(path: Path) -> bool:
    try:
        next(path.iterdir(), None)
    except StopIteration:
        return True
    except OSError:
        return False
    return True
