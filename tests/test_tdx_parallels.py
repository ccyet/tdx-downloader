from __future__ import annotations

from pathlib import Path

from tdx_downloader.cli import DEFAULT_DATA_ROOT, _forward_args
from tdx_downloader.data import tdx_parallels
from tdx_downloader.data.tdx_parallels import (
    ParallelsTdxConfig,
    build_parallels_tdx_command,
    mac_path_to_parallels_shared_path,
    run_parallels_tdx_command,
)


class _Args:
    command = "prepare-data"
    symbols = "000001.SZ"
    timeframes = "5m"
    start = "2026-06-01"
    end = "2026-06-02"
    adjust = "qfq"
    data_root = DEFAULT_DATA_ROOT
    tdx_path = ""
    batch_size = 100
    min_coverage_ratio = None
    allow_incomplete_after_update = False


class _SymbolGroupsArgs:
    command = "symbol-groups"
    data_root = DEFAULT_DATA_ROOT
    tdx_path = "/Volumes/[C] Windows 11/new_tdx64/PYPlugins"
    output = "json"


def test_default_data_root_points_to_external_tdx_data_root() -> None:
    assert DEFAULT_DATA_ROOT == "/Volumes/ccOUT 1/tdx-data"


def test_mac_volume_path_maps_to_parallels_mac_volume_share() -> None:
    mapped = mac_path_to_parallels_shared_path("/Volumes/ccOUT 1/tdx-data")

    assert mapped == r"\\psf\ccOUT 1\tdx-data"


def test_parallels_mounted_windows_drive_path_maps_back_to_drive_letter() -> None:
    mapped = mac_path_to_parallels_shared_path("/Volumes/[C] Windows 11/new_tdx64/T0002/dlls")

    assert mapped == r"C:\new_tdx64\T0002\dlls"


def test_forward_args_maps_default_data_root_for_windows_side_cli() -> None:
    forwarded = _forward_args(_Args())

    assert "--data-root" in forwarded
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"


def test_forward_args_maps_selected_parallels_tdx_path_to_windows_drive() -> None:
    args = _Args()
    args.tdx_path = "/Volumes/[C] Windows 11/new_tdx64/T0002/dlls"

    forwarded = _forward_args(args)

    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\T0002\dlls"


def test_forward_args_maps_symbol_groups_paths_for_windows_cli() -> None:
    forwarded = _forward_args(_SymbolGroupsArgs())

    assert forwarded[:3] == ["symbol-groups", "--runtime", "local"]
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"
    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\PYPlugins"
    assert forwarded[-2:] == ["--output", "json"]


def test_forward_args_maps_symbol_metadata_paths_for_windows_cli() -> None:
    args = _SymbolGroupsArgs()
    args.command = "symbol-metadata"

    forwarded = _forward_args(args)

    assert forwarded[:3] == ["symbol-metadata", "--runtime", "local"]
    assert forwarded[forwarded.index("--data-root") + 1] == r"\\psf\ccOUT 1\tdx-data"
    assert forwarded[forwarded.index("--tdx-path") + 1] == r"C:\new_tdx64\PYPlugins"
    assert forwarded[-2:] == ["--output", "json"]


def test_parallels_command_runs_windows_cli_inside_repo() -> None:
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    command = build_parallels_tdx_command(config=config, cli_args=["tdx-doctor", "--runtime", "local"])

    assert command[:4] == ["prlctl", "exec", "Windows 11", "--current-user"]
    assert command[-1].startswith("pushd ")
    assert "tdx_downloader.cli" in command[-1]
    assert r"\\psf\ccOUT 1\tdx-downloader" in command[-1]
    assert "popd" not in command[-1]


def test_run_parallels_tdx_command_starts_vm_before_exec(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"] and len(calls) == 1:
            return _Process(command, stdout=b"VM 'Windows 11' is suspended\n")
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:2] == ["prlctl", "start"]:
            return _Process(command)
        if command[:2] == ["prlctl", "exec"]:
            return _Process(command, stdout=b"ok\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = run_parallels_tdx_command(config=config, cli_args=["tdx-doctor", "--runtime", "local"])

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert calls[0] == ["prlctl", "status", "Windows 11"]
    assert calls[1] == ["prlctl", "start", "Windows 11"]
    assert calls[2] == ["prlctl", "status", "Windows 11"]
    assert calls[3][:4] == ["prlctl", "exec", "Windows 11", "--current-user"]


def test_run_parallels_tdx_command_waits_when_start_reports_resuming(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        calls.append(command)
        if command[:2] == ["prlctl", "status"] and len(calls) == 1:
            return _Process(command, stdout=b"VM 'Windows 11' is suspended\n")
        if command[:2] == ["prlctl", "start"]:
            return _Process(
                command,
                returncode=1,
                stderr=(
                    b'Failed to start the VM: Unable to complete the operation. '
                    b'This operation cannot be completed because "Windows 11" is in the "resuming" state. '
                    b"Starting the VM...\n"
                ),
            )
        if command[:2] == ["prlctl", "status"]:
            return _Process(command, stdout=b"VM 'Windows 11' is running\n")
        if command[:2] == ["prlctl", "exec"]:
            return _Process(command, stdout=b"ok\n")
        raise AssertionError(command)

    monkeypatch.setattr(tdx_parallels.subprocess, "run", fake_run)
    monkeypatch.setattr(tdx_parallels.time, "sleep", lambda _: None)
    config = ParallelsTdxConfig(
        vm_name="Windows 11",
        windows_python=r"C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe",
        windows_repo=r"\\psf\ccOUT 1\tdx-downloader",
    )

    result = run_parallels_tdx_command(config=config, cli_args=["symbol-groups", "--runtime", "local"])

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert calls[0] == ["prlctl", "status", "Windows 11"]
    assert calls[1] == ["prlctl", "start", "Windows 11"]
    assert calls[2] == ["prlctl", "status", "Windows 11"]
    assert calls[3][:4] == ["prlctl", "exec", "Windows 11", "--current-user"]


def test_home_path_still_maps_to_parallels_home_share() -> None:
    mapped = mac_path_to_parallels_shared_path("/Users/a1234/Desktop/project", home=Path("/Users/a1234"))

    assert mapped == r"\\psf\Home\Desktop\project"


class _Process:
    def __init__(
        self,
        args: list[str],
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
