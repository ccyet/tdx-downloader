from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

PARALLELS_TDX_VM_ENV_VAR = "TDX_PARALLELS_VM"
PARALLELS_TDX_PYTHON_ENV_VAR = "TDX_PARALLELS_PYTHON"
PARALLELS_TDX_REPO_ENV_VAR = "TDX_PARALLELS_REPO"
PARALLELS_TDX_WORKER_SCRATCH_ENV_VAR = "TDX_WORKER_SCRATCH"
PARALLELS_PROGRESS_ENV_VAR = "TDX_PROGRESS_JSONL"
PARALLELS_PROGRESS_PREFIX = "__TDX_PROGRESS__="
DEFAULT_PARALLELS_VM = "Windows 11"
DEFAULT_WINDOWS_PYTHON = r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe"
PARALLELS_VM_START_TIMEOUT_SECONDS = 60
WINDOWS_PYTHON_SETUP_TIMEOUT_SECONDS = 300
PARALLELS_WORKER_START_TIMEOUT_SECONDS = 15
PARALLELS_RUNNER_DIR_NAME = ".tdx-parallels"
PARALLELS_RUNTIME_CACHE_FILE = "runtime-cache.json"
WINDOWS_PYTHON_APP_ALIAS_MARKER = r"\Microsoft\WindowsApps\python.exe"
WINDOWS_PYTHON_RESULT_PREFIX = "__TDX_WINDOWS_PYTHON__="
WINDOWS_RUNTIME_IMPORT_CHECK = "import numpy, pandas, pyarrow, dateutil, pytz"
WINDOWS_RUNTIME_PIP_PACKAGES = (
    "numpy",
    "pandas",
    "pyarrow",
    "python-dateutil",
    "pytz",
    "tzdata",
)
DEFAULT_WINDOWS_PYTHON_CANDIDATES = (
    DEFAULT_WINDOWS_PYTHON,
    r"%USERPROFILE%\anaconda3\python.exe",
    r"%USERPROFILE%\miniconda3\python.exe",
    r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe",
    r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe",
    r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe",
    r"C:\ProgramData\anaconda3\python.exe",
    r"C:\ProgramData\miniconda3\python.exe",
    r"C:\Program Files\Python313\python.exe",
    r"C:\Program Files\Python312\python.exe",
    r"C:\Program Files\Python311\python.exe",
)


_PARALLELS_RUNNER_SOURCE = """\
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

payload_path = Path(__file__).with_suffix(".json")
payload = json.loads(payload_path.read_text(encoding="utf-8"))
windows_repo = payload["windows_repo"]
cli_args = [str(item) for item in payload["cli_args"]]

os.chdir(windows_repo)
if windows_repo not in sys.path:
    sys.path.insert(0, windows_repo)
sys.argv = ["tdx_downloader.cli", *cli_args]
runpy.run_module("tdx_downloader.cli", run_name="__main__")
"""


@dataclass(frozen=True)
class ParallelsTdxConfig:
    """Parallels/Windows TDX 执行环境；Mac 只负责调度，真实 tqcenter 在 Windows 内运行。"""

    vm_name: str
    windows_python: str
    windows_repo: str
    worker_scratch: str = r"C:\tdx_jobs"


@dataclass(frozen=True)
class ParallelsRunnerFiles:
    """Mac 侧临时 runner 及其 Windows 共享路径。"""

    runner_path: Path
    payload_path: Path
    command_path: Path
    windows_command_path: str


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
        worker_scratch=os.getenv(PARALLELS_TDX_WORKER_SCRATCH_ENV_VAR, r"C:\tdx_jobs").strip() or r"C:\tdx_jobs",
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


def build_parallels_tdx_command(
    *,
    config: ParallelsTdxConfig,
    cli_args: list[str],
    command_path: str,
) -> list[str]:
    """构造 prlctl 命令；cmd 只执行临时脚本，复杂 CLI 参数走 JSON。"""
    del cli_args
    return ["prlctl", "exec", config.vm_name, "--current-user", "cmd", "/d", "/s", "/c", _quote_windows_arg(command_path)]


def run_parallels_tdx_command(*, config: ParallelsTdxConfig, cli_args: list[str]) -> subprocess.CompletedProcess[str]:
    """通过 prlctl 在 Windows VM 内执行 TDX CLI 命令，并把 stdout/stderr 返回给调用方。"""
    started_at = time.perf_counter()
    _emit_runtime_progress(
        stage="parallels_vm_check_start",
        message=f"开始检查 Parallels VM：{config.vm_name}",
        vm_name=config.vm_name,
    )
    startup = _ensure_parallels_vm_running(config.vm_name)
    _emit_runtime_progress(
        stage="parallels_vm_check_done" if startup.returncode == 0 else "parallels_vm_check_failed",
        message="Parallels VM 已运行。" if startup.returncode == 0 else "Parallels VM 检查失败。",
        vm_name=config.vm_name,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
    )
    if startup.returncode != 0:
        return startup
    python_started_at = time.perf_counter()
    _emit_runtime_progress(
        stage="parallels_python_check_start",
        message="开始解析 Windows Python 路径。",
        vm_name=config.vm_name,
    )
    python_check = resolve_windows_python(config)
    _emit_runtime_progress(
        stage="parallels_python_check_done" if python_check.returncode == 0 else "parallels_python_check_failed",
        message=(
            f"Windows Python 可用：{python_check.stdout.strip()}"
            if python_check.returncode == 0
            else "Windows Python 检查失败。"
        ),
        vm_name=config.vm_name,
        windows_python=python_check.stdout.strip(),
        elapsed_ms=int((time.perf_counter() - python_started_at) * 1000),
    )
    if python_check.returncode != 0:
        return python_check
    resolved_config = ParallelsTdxConfig(
        vm_name=config.vm_name,
        windows_python=python_check.stdout.strip(),
        windows_repo=config.windows_repo,
        worker_scratch=config.worker_scratch,
    )
    runner_files = write_parallels_runner(config=resolved_config, cli_args=cli_args, cwd=Path.cwd())
    try:
        command = build_parallels_tdx_command(
            config=resolved_config,
            cli_args=cli_args,
            command_path=runner_files.windows_command_path,
        )
        runner_started_at = time.perf_counter()
        _emit_runtime_progress(
            stage="parallels_runner_start",
            message="Windows CLI 已启动，等待 TDX 批次进度。",
            vm_name=config.vm_name,
            command=str(cli_args[0]) if cli_args else "",
        )
        result = _run_streaming_subprocess(command) if _progress_enabled() else _run_subprocess(command)
        _emit_runtime_progress(
            stage="parallels_runner_done" if result.returncode == 0 else "parallels_runner_failed",
            message="Windows CLI 已返回。" if result.returncode == 0 else "Windows CLI 执行失败。",
            vm_name=config.vm_name,
            command=str(cli_args[0]) if cli_args else "",
            elapsed_ms=int((time.perf_counter() - runner_started_at) * 1000),
        )
        return result
    finally:
        cleanup_parallels_runner(runner_files)


def start_parallels_tdx_worker(
    *,
    config: ParallelsTdxConfig | None = None,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> subprocess.CompletedProcess[str]:
    resolved = config or default_parallels_tdx_config(cwd=Path.cwd())
    if _is_parallels_shared_repo_path(resolved.windows_repo):
        return subprocess.CompletedProcess(
            args=["tdx-worker"],
            returncode=2,
            stdout="",
            stderr=(
                "TDX_PARALLELS_REPO 指向 Parallels 共享目录，禁止用 \\\\psf 启动常驻 Worker。"
                "请在 Windows 本地部署项目，例如 C:\\tdx-downloader-app，"
                "并设置 TDX_PARALLELS_REPO 指向该目录。"
            ),
        )
    startup = _ensure_parallels_vm_running(resolved.vm_name)
    if startup.returncode != 0:
        return startup
    python_check = resolve_windows_python(resolved)
    if python_check.returncode != 0:
        return python_check
    resolved = ParallelsTdxConfig(
        vm_name=resolved.vm_name,
        windows_python=python_check.stdout.strip(),
        windows_repo=resolved.windows_repo,
        worker_scratch=resolved.worker_scratch,
    )
    runner_files = write_parallels_runner(
        config=resolved,
        cli_args=[
            "tdx-worker",
            "--host",
            host,
            "--port",
            str(port),
            "--scratch-root",
            resolved.worker_scratch,
        ],
        cwd=Path.cwd(),
    )
    log_path = runner_files.command_path.with_suffix(".log")
    windows_python = subprocess.list2cmdline([resolved.windows_python, mac_path_to_parallels_shared_path(str(runner_files.runner_path))])
    windows_log_path = mac_path_to_parallels_shared_path(str(log_path))
    runner_files.command_path.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set PYTHONUTF8=1\r\n"
        f'set "{PARALLELS_TDX_WORKER_SCRATCH_ENV_VAR}={resolved.worker_scratch}"\r\n'
        f'start "tdx-worker" /min cmd.exe /d /s /c "{windows_python} 1>>"{windows_log_path}" 2>>&1"\r\n'
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    command = build_parallels_tdx_command(
        config=resolved,
        cli_args=[],
        command_path=runner_files.windows_command_path,
    )
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=PARALLELS_WORKER_START_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=_decode_windows_output(exc.stdout),
            stderr=f"启动 Windows Worker 超时：prlctl exec {PARALLELS_WORKER_START_TIMEOUT_SECONDS} 秒内未返回。",
        )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_windows_output(result.stdout),
        stderr=_decode_windows_output(result.stderr),
    )


def write_parallels_runner(*, config: ParallelsTdxConfig, cli_args: list[str], cwd: Path) -> ParallelsRunnerFiles:
    """写入 Windows 侧临时 Python runner；payload 用 UTF-8 JSON，避开 shell 字符转义。"""
    runner_dir = cwd / PARALLELS_RUNNER_DIR_NAME
    runner_dir.mkdir(parents=True, exist_ok=True)
    stem = f"tdx_runner_{uuid4().hex}"
    runner_path = runner_dir / f"{stem}.py"
    payload_path = runner_dir / f"{stem}.json"
    command_path = runner_dir / f"{stem}.cmd"
    windows_runner_path = mac_path_to_parallels_shared_path(str(runner_path))
    payload = {
        "windows_repo": config.windows_repo,
        "cli_args": [str(item) for item in cli_args],
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    runner_path.write_text(_PARALLELS_RUNNER_SOURCE, encoding="utf-8")
    command_lines = [
        "@echo off",
        "chcp 65001 >nul",
        "set PYTHONUTF8=1",
    ]
    if _progress_enabled():
        command_lines.append(f"set {PARALLELS_PROGRESS_ENV_VAR}=1")
    command_lines.append(f'set "{PARALLELS_TDX_WORKER_SCRATCH_ENV_VAR}={config.worker_scratch}"')
    command_lines.append(subprocess.list2cmdline([config.windows_python, windows_runner_path]))
    command_path.write_text("\r\n".join(command_lines) + "\r\n", encoding="utf-8")
    return ParallelsRunnerFiles(
        runner_path=runner_path,
        payload_path=payload_path,
        command_path=command_path,
        windows_command_path=mac_path_to_parallels_shared_path(str(command_path)),
    )


def cleanup_parallels_runner(files: ParallelsRunnerFiles) -> None:
    for path in (files.runner_path, files.payload_path, files.command_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")


def _is_parallels_shared_repo_path(value: str) -> bool:
    normalized = str(value or "").strip().replace("/", "\\").lower()
    return normalized.startswith("\\\\psf\\")


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


def _decode_windows_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _run_streaming_subprocess(command: list[str]) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_thread = threading.Thread(
        target=_collect_process_stream,
        args=(process.stdout, stdout_parts),
        kwargs={"progress_stream": False},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_collect_process_stream,
        args=(process.stderr, stderr_parts),
        kwargs={"progress_stream": True},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    return subprocess.CompletedProcess(
        args=command,
        returncode=int(returncode or 0),
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )


def _run_subprocess(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, check=False)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_windows_output(result.stdout),
        stderr=_decode_windows_output(result.stderr),
    )


def _collect_process_stream(stream: object, sink: list[str], *, progress_stream: bool) -> None:
    if stream is None:
        return
    for raw_line in stream:  # type: ignore[union-attr]
        line = _decode_windows_output(raw_line)
        if progress_stream and _forward_progress_line(line):
            continue
        sink.append(line)


def _forward_progress_line(line: str) -> bool:
    text = line.strip()
    if not text.startswith(PARALLELS_PROGRESS_PREFIX):
        return False
    print(text, file=sys.stderr, flush=True)
    return True


def _emit_runtime_progress(**payload: object) -> None:
    if not _progress_enabled():
        return
    print(
        PARALLELS_PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False, default=str),
        file=sys.stderr,
        flush=True,
    )


def _progress_enabled() -> bool:
    return os.getenv(PARALLELS_PROGRESS_ENV_VAR, "").strip() == "1"


def _quote_windows_arg(value: str) -> str:
    return subprocess.list2cmdline([value])


def resolve_windows_python(config: ParallelsTdxConfig) -> subprocess.CompletedProcess[str]:
    """解析 Windows Python；显式配置优先，默认自动发现 Conda/Python 安装。"""
    python_path = config.windows_python.strip()
    explicit = bool(os.getenv(PARALLELS_TDX_PYTHON_ENV_VAR, "").strip())
    if python_path and python_path.lower() != "python" and (explicit or python_path != DEFAULT_WINDOWS_PYTHON):
        return _ensure_windows_python_exists(config.vm_name, python_path, explicit=True)
    cached_python = _read_cached_windows_python(config)
    if cached_python:
        cached_check = _ensure_windows_python_exists(config.vm_name, cached_python, explicit=False)
        if cached_check.returncode == 0:
            return subprocess.CompletedProcess(args=cached_check.args, returncode=0, stdout=cached_python, stderr="")
    bootstrap_python = _discover_windows_python(config.vm_name, preferred=python_path)
    if bootstrap_python:
        resolved = _ensure_default_windows_python_runtime(config, bootstrap_python)
        if resolved.returncode == 0 and resolved.stdout.strip():
            _write_cached_windows_python(config, bootstrap_python=bootstrap_python, windows_python=resolved.stdout.strip())
        return resolved
    return subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr=_windows_python_missing_message(python_path or "python"),
    )


def _ensure_windows_python_exists(
    vm_name: str,
    python_path: str,
    *,
    explicit: bool,
) -> subprocess.CompletedProcess[str]:
    if not python_path or python_path.lower() == "python":
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=_windows_python_missing_message(python_path or "python"),
        )
    command = [
        "prlctl",
        "exec",
        vm_name,
        "--current-user",
        "cmd",
        "/d",
        "/s",
        "/c",
        f"if exist {_quote_windows_arg(python_path)} (exit /b 0) else (exit /b 1)",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode == 0:
        return subprocess.CompletedProcess(args=result.args, returncode=0, stdout=python_path, stderr="")
    if not explicit:
        return subprocess.CompletedProcess(args=result.args, returncode=1, stdout="", stderr="")
    detail = "\n".join(
        part
        for part in (_decode_windows_output(result.stderr).strip(), _decode_windows_output(result.stdout).strip())
        if part
    )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode or 1,
        stdout="",
        stderr=_windows_python_missing_message(python_path, detail=detail),
    )


def _discover_windows_python(vm_name: str, *, preferred: str = "") -> str:
    candidates = _windows_python_candidates(preferred)
    probe_path = _write_windows_python_probe(candidates, cwd=Path.cwd())
    command = [
        "prlctl",
        "exec",
        vm_name,
        "--current-user",
        "cmd",
        "/d",
        "/s",
        "/c",
        _quote_windows_arg(mac_path_to_parallels_shared_path(str(probe_path))),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    finally:
        try:
            probe_path.unlink()
        except FileNotFoundError:
            pass
    if result.returncode != 0:
        return ""
    for line in _decode_windows_output(result.stdout).splitlines():
        candidate = line.strip().strip('"')
        if _valid_windows_python_candidate(candidate):
            return candidate
    return ""


def _ensure_default_windows_python_runtime(
    config: ParallelsTdxConfig,
    bootstrap_python: str,
) -> subprocess.CompletedProcess[str]:
    setup_path = _write_windows_python_setup_script(
        bootstrap_python=bootstrap_python,
        windows_repo=config.windows_repo,
        cwd=Path.cwd(),
    )
    command = [
        "prlctl",
        "exec",
        config.vm_name,
        "--current-user",
        "cmd",
        "/d",
        "/s",
        "/c",
        _quote_windows_arg(mac_path_to_parallels_shared_path(str(setup_path))),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=WINDOWS_PYTHON_SETUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr=_windows_python_setup_failed_message(
                bootstrap_python,
                stdout=_decode_windows_output(exc.stdout),
                stderr=(
                    f"Windows Python 环境初始化超过 {WINDOWS_PYTHON_SETUP_TIMEOUT_SECONDS} 秒；"
                    "请检查 Windows 网络或手动运行 pip install -r requirements.txt。"
                ),
            ),
        )
    finally:
        try:
            setup_path.unlink()
        except FileNotFoundError:
            pass
    stdout = _decode_windows_output(result.stdout)
    stderr = _decode_windows_output(result.stderr)
    if result.returncode != 0:
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout="",
            stderr=_windows_python_setup_failed_message(bootstrap_python, stdout=stdout, stderr=stderr),
        )
    for line in stdout.splitlines():
        text = line.strip()
        if text.startswith(WINDOWS_PYTHON_RESULT_PREFIX):
            python_path = text.removeprefix(WINDOWS_PYTHON_RESULT_PREFIX).strip()
            if _valid_windows_python_candidate(python_path):
                return subprocess.CompletedProcess(args=result.args, returncode=0, stdout=python_path, stderr="")
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=1,
        stdout="",
        stderr=_windows_python_setup_failed_message(bootstrap_python, stdout=stdout, stderr=stderr),
    )


def _windows_python_candidates(preferred: str = "") -> list[str]:
    candidates = [preferred.strip()] if preferred.strip() and preferred.strip().lower() != "python" else []
    candidates.extend(DEFAULT_WINDOWS_PYTHON_CANDIDATES)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if not candidate or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _windows_python_probe_script(candidates: list[str]) -> str:
    lines = ["@echo off", "chcp 65001 >nul"]
    lines.extend(f'if exist "{candidate}" echo {candidate}' for candidate in candidates)
    lines.append("where python 2>nul")
    lines.append('py -3 -c "import sys; print(sys.executable)" 2>nul')
    lines.append("exit /b 0")
    return "\r\n".join(lines) + "\r\n"


def _write_windows_python_probe(candidates: list[str], *, cwd: Path) -> Path:
    runner_dir = cwd / PARALLELS_RUNNER_DIR_NAME
    runner_dir.mkdir(parents=True, exist_ok=True)
    probe_path = runner_dir / f"tdx_python_probe_{uuid4().hex}.cmd"
    probe_path.write_text(_windows_python_probe_script(candidates), encoding="utf-8")
    return probe_path


def _write_windows_python_setup_script(*, bootstrap_python: str, windows_repo: str, cwd: Path) -> Path:
    runner_dir = cwd / PARALLELS_RUNNER_DIR_NAME
    runner_dir.mkdir(parents=True, exist_ok=True)
    setup_path = runner_dir / f"tdx_python_setup_{uuid4().hex}.cmd"
    del windows_repo
    runtime_packages = " ".join(WINDOWS_RUNTIME_PIP_PACKAGES)
    script = "\r\n".join(
        [
            "@echo off",
            "chcp 65001 >nul",
            "set PYTHONUTF8=1",
            f'set "TDX_BOOTSTRAP_PYTHON={bootstrap_python}"',
            r'set "TDX_VENV=C:\Users\Public\venvs\tdx-downloader"',
            r'set "TDX_LOCK=C:\Users\Public\venvs\tdx-downloader.lock"',
            'if not exist "%TDX_BOOTSTRAP_PYTHON%" (',
            "  echo Bootstrap Python not found: %TDX_BOOTSTRAP_PYTHON% 1>&2",
            "  exit /b 1",
            ")",
            'mkdir "%TDX_LOCK%" 2>nul',
            "if errorlevel 1 (",
            "  echo Windows Python project environment is already initializing. Please retry shortly. 1>&2",
            "  exit /b 1",
            ")",
            'if not exist "%TDX_VENV%" mkdir "%TDX_VENV%"',
            'if not exist "%TDX_VENV%\\Scripts\\python.exe" (',
            '  "%TDX_BOOTSTRAP_PYTHON%" -m venv "%TDX_VENV%"',
            "  if errorlevel 1 goto fail",
            ")",
            f'"%TDX_VENV%\\Scripts\\python.exe" -c "{WINDOWS_RUNTIME_IMPORT_CHECK}" >nul 2>nul',
            "if errorlevel 1 (",
            f'  "%TDX_VENV%\\Scripts\\python.exe" -m pip install --disable-pip-version-check {runtime_packages}',
            "  if errorlevel 1 goto fail",
            ")",
            f'"%TDX_VENV%\\Scripts\\python.exe" -c "{WINDOWS_RUNTIME_IMPORT_CHECK}"',
            "if errorlevel 1 goto fail",
            f"echo {WINDOWS_PYTHON_RESULT_PREFIX}%TDX_VENV%\\Scripts\\python.exe",
            'rmdir "%TDX_LOCK%" 2>nul',
            "exit /b 0",
            ":fail",
            "set TDX_ERROR=%errorlevel%",
            'rmdir "%TDX_LOCK%" 2>nul',
            "exit /b %TDX_ERROR%",
        ]
    )
    setup_path.write_text(script + "\r\n", encoding="utf-8")
    return setup_path


def _runtime_cache_path(*, cwd: Path | None = None) -> Path:
    runner_dir = (cwd or Path.cwd()) / PARALLELS_RUNNER_DIR_NAME
    runner_dir.mkdir(parents=True, exist_ok=True)
    return runner_dir / PARALLELS_RUNTIME_CACHE_FILE


def _read_cached_windows_python(config: ParallelsTdxConfig) -> str:
    path = _runtime_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
    if not isinstance(payload, dict):
        return ""
    if str(payload.get("vm_name", "")) != config.vm_name:
        return ""
    if str(payload.get("windows_repo", "")) != config.windows_repo:
        return ""
    python_path = str(payload.get("windows_python", "")).strip()
    return python_path if _valid_windows_python_candidate(python_path) else ""


def _write_cached_windows_python(
    config: ParallelsTdxConfig,
    *,
    bootstrap_python: str,
    windows_python: str,
) -> None:
    if not _valid_windows_python_candidate(windows_python):
        return
    path = _runtime_cache_path()
    payload = {
        "vm_name": config.vm_name,
        "windows_repo": config.windows_repo,
        "bootstrap_python": bootstrap_python,
        "windows_python": windows_python,
        "created_at": int(time.time()),
        "version": 1,
    }
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _valid_windows_python_candidate(value: str) -> bool:
    text = value.strip().strip('"')
    if not text:
        return False
    if ">" in text or "if exist" in text.lower():
        return False
    if not (re.match(r"^[A-Za-z]:\\", text) or text.startswith("\\\\")):
        return False
    return text.lower().endswith("\\python.exe") and WINDOWS_PYTHON_APP_ALIAS_MARKER.lower() not in text.lower()


def _windows_python_missing_message(windows_python: str, *, detail: str = "") -> str:
    message = (
        f"Windows Python 不可用：{windows_python}。\n"
        "已自动查找 Anaconda、Miniconda、py launcher 和常见 Python 安装路径，但没有找到可用 python.exe。\n"
        f"请确认 Windows 侧 Python 已安装，或通过环境变量 {PARALLELS_TDX_PYTHON_ENV_VAR} "
        "或 CLI 参数 --windows-python 指向真实 python.exe。注意不要使用 Microsoft Store 的 WindowsApps python.exe。"
    )
    if detail:
        message += f"\nWindows 返回：{detail}"
    return message


def _windows_python_setup_failed_message(bootstrap_python: str, *, stdout: str, stderr: str) -> str:
    detail = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
    message = (
        "Windows Python 环境初始化失败。\n"
        f"已找到 Python：{bootstrap_python}。\n"
        f"但无法创建或修复项目虚拟环境：{DEFAULT_WINDOWS_PYTHON}。\n"
        "请确认 Windows Python 可执行 `python -m venv`，且 Windows 能安装 numpy/pandas/pyarrow 等取数依赖。"
    )
    if detail:
        message += f"\nWindows 返回：{detail}"
    return message


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
