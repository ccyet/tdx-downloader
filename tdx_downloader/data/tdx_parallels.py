from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import time

PARALLELS_TDX_VM_ENV_VAR = "TDX_PARALLELS_VM"
PARALLELS_TDX_PYTHON_ENV_VAR = "TDX_PARALLELS_PYTHON"
PARALLELS_TDX_REPO_ENV_VAR = "TDX_PARALLELS_REPO"
DEFAULT_PARALLELS_VM = "Windows 11"
DEFAULT_WINDOWS_PYTHON = r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe"
PARALLELS_VM_START_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ParallelsTdxConfig:
    """Parallels/Windows TDX 执行环境；Mac 只负责调度，真实 tqcenter 在 Windows 内运行。"""

    vm_name: str
    windows_python: str
    windows_repo: str


def default_parallels_tdx_config(*, cwd: Path | None = None) -> ParallelsTdxConfig:
    """从环境变量和当前仓库路径推导默认 Parallels TDX 运行配置。"""
    repo_path = os.getenv(PARALLELS_TDX_REPO_ENV_VAR, "").strip()
    if not repo_path:
        repo_path = mac_path_to_parallels_shared_path(str(cwd or Path.cwd()))
    return ParallelsTdxConfig(
        vm_name=os.getenv(PARALLELS_TDX_VM_ENV_VAR, DEFAULT_PARALLELS_VM).strip() or DEFAULT_PARALLELS_VM,
        windows_python=os.getenv(PARALLELS_TDX_PYTHON_ENV_VAR, DEFAULT_WINDOWS_PYTHON).strip()
        or DEFAULT_WINDOWS_PYTHON,
        windows_repo=repo_path,
    )


def mac_path_to_parallels_shared_path(value: str, *, home: Path | None = None) -> str:
    """把 macOS 绝对路径映射到 Parallels 默认共享路径；Windows 路径和相对路径原样返回。"""
    text = str(value).strip().strip('"')
    if not text or _looks_like_windows_path(text) or not text.startswith("/"):
        return text
    home_path = home or Path.home()
    path = Path(text).expanduser()
    try:
        relative_volume = path.relative_to(Path("/Volumes"))
    except ValueError:
        relative_volume = None
    if relative_volume is not None:
        drive_path = _parallels_mounted_windows_drive_path(relative_volume)
        if drive_path:
            return drive_path
        return "\\".join(["\\\\psf", *relative_volume.parts])
    try:
        relative = path.relative_to(home_path)
    except ValueError:
        return text
    parts = ["\\\\psf", "Home", *relative.parts]
    return "\\".join(parts)


def build_parallels_tdx_command(*, config: ParallelsTdxConfig, cli_args: list[str]) -> list[str]:
    """构造 prlctl 命令；内部固定切回 local runtime，避免递归再次调度 Parallels。"""
    inner_args = [config.windows_python, "-m", "tdx_downloader.cli", *cli_args]
    inner_command = f"pushd {_quote_windows_arg(config.windows_repo)} && {subprocess.list2cmdline(inner_args)}"
    return ["prlctl", "exec", config.vm_name, "--current-user", "cmd", "/d", "/s", "/c", inner_command]


def run_parallels_tdx_command(*, config: ParallelsTdxConfig, cli_args: list[str]) -> subprocess.CompletedProcess[str]:
    """通过 prlctl 在 Windows VM 内执行 TDX CLI 命令，并把 stdout/stderr 返回给调用方。"""
    startup = _ensure_parallels_vm_running(config.vm_name)
    if startup.returncode != 0:
        return startup
    command = build_parallels_tdx_command(config=config, cli_args=cli_args)
    result = subprocess.run(command, capture_output=True, check=False)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_windows_output(result.stdout),
        stderr=_decode_windows_output(result.stderr),
    )


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")


def _parallels_mounted_windows_drive_path(relative_volume: Path) -> str:
    parts = relative_volume.parts
    if not parts:
        return ""
    match = re.match(r"^\[([A-Za-z])\](?:\s|$)", parts[0])
    if not match:
        return ""
    drive = match.group(1).upper()
    if len(parts) == 1:
        return f"{drive}:\\"
    return "\\".join([f"{drive}:", *parts[1:]])


def _quote_windows_arg(value: str) -> str:
    return subprocess.list2cmdline([value])


def _decode_windows_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("gbk", "cp936", "utf-8"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _ensure_parallels_vm_running(vm_name: str) -> subprocess.CompletedProcess[str]:
    status = _parallels_status(vm_name)
    if status.returncode != 0:
        return status
    if _parallels_status_is_running(status.stdout):
        return status
    if _parallels_status_is_resuming(status.stdout):
        return _wait_for_parallels_vm_running(vm_name, status)

    start = subprocess.run(["prlctl", "start", vm_name], capture_output=True, check=False)
    start_stdout = _decode_windows_output(start.stdout)
    start_stderr = _decode_windows_output(start.stderr)
    if start.returncode != 0:
        if _parallels_start_is_resuming(start_stdout, start_stderr):
            return _wait_for_parallels_vm_running(
                vm_name,
                subprocess.CompletedProcess(
                    args=start.args,
                    returncode=start.returncode,
                    stdout=start_stdout,
                    stderr=start_stderr,
                ),
            )
        return subprocess.CompletedProcess(
            args=start.args,
            returncode=start.returncode,
            stdout=start_stdout,
            stderr="启动 Parallels VM 失败；请确认虚拟机名称和 Parallels Desktop 状态。\n"
            + start_stderr,
        )

    return _wait_for_parallels_vm_running(vm_name, status)


def _wait_for_parallels_vm_running(
    vm_name: str,
    last_status: subprocess.CompletedProcess[str],
) -> subprocess.CompletedProcess[str]:
    deadline = time.monotonic() + PARALLELS_VM_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = _parallels_status(vm_name)
        if status.returncode != 0:
            return status
        if _parallels_status_is_running(status.stdout):
            return status
        last_status = status
        time.sleep(2)

    return subprocess.CompletedProcess(
        args=["prlctl", "status", vm_name],
        returncode=1,
        stdout=last_status.stdout,
        stderr=f"Parallels VM `{vm_name}` 启动后仍未进入 running 状态。",
    )


def _parallels_status(vm_name: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["prlctl", "status", vm_name], capture_output=True, check=False)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_windows_output(result.stdout),
        stderr=_decode_windows_output(result.stderr),
    )


def _parallels_status_is_running(output: str) -> bool:
    return "running" in output.lower()


def _parallels_status_is_resuming(output: str) -> bool:
    return "resuming" in output.lower()


def _parallels_start_is_resuming(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return "resuming" in text and "starting the vm" in text
