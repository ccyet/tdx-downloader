from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def _open_native_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    if sys.platform == "darwin":
        return _open_macos_directory_dialog(initial_directory, title)
    if sys.platform.startswith("win"):
        return _open_windows_directory_dialog(initial_directory, title)
    raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")


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
