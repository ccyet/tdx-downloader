from __future__ import annotations

from pathlib import Path

import pandas as pd

from tdx_downloader.data import tdx


class _PeriodFakeTq:
    def __init__(self, payloads: dict[str, dict[str, pd.DataFrame]]) -> None:
        self.payloads = payloads
        self.market_calls: list[dict[str, object]] = []
        self.refresh_calls: list[tuple[list[str], str]] = []
        self.initialize_calls: list[str] = []

    def initialize(self, caller_path: str) -> None:
        self.initialize_calls.append(caller_path)

    def refresh_kline(self, stock_list: list[str], period: str) -> str:
        self.refresh_calls.append((stock_list, period))
        return '{"ErrorId":"0","Msg":"ok"}'

    def get_market_data(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        self.market_calls.append(kwargs)
        return self.payloads.get(str(kwargs["period"]), {})


def test_candidate_import_paths_use_windows_default_tdx_install(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tdx.sys, "platform", "win32")
    monkeypatch.delenv(tdx.TDX_TQCENTER_ENV_VAR, raising=False)

    paths = tdx._candidate_import_paths("")
    normalized = {_windows_text(path) for path in paths}

    assert r"c:\new_tdx64\pyplugins\user" in normalized
    assert r"c:\new_tdx64\pyplugins\sys" in normalized


def test_candidate_import_paths_recover_pyplugins_from_tdx_subdirectory() -> None:
    paths = tdx._candidate_import_paths("/Volumes/[C] Windows 11/new_tdx64/T0002/dlls")
    normalized = {str(path) for path in paths}

    assert "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user" in normalized
    assert "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/sys" in normalized
    assert "/Volumes/[C] Windows 11/new_tdx64/T0002/dlls" in normalized


def test_candidate_import_paths_include_pyplugins_sys_for_pyplugins_root() -> None:
    paths = tdx._candidate_import_paths("/Volumes/[C] Windows 11/new_tdx64/PYPlugins")
    normalized = {str(path) for path in paths}

    assert "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user" in normalized
    assert "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/sys" in normalized


def test_fetch_tdx_bars_derives_5m_from_1m_when_native_5m_empty() -> None:
    fake = _PeriodFakeTq(
        {
            "1m": _tdx_payload(
                pd.date_range("2026-05-25 09:31:00", periods=5, freq="1min"),
                opens=[10, 11, 12, 13, 14],
                highs=[11, 12, 13, 14, 15],
                lows=[9, 10, 11, 12, 13],
                closes=[10.5, 11.5, 12.5, 13.5, 14.5],
            )
        }
    )

    bars = tdx.fetch_tdx_bars(
        symbols=("000001.SZ",),
        timeframe="5m",
        start="2026-05-25 09:30:00",
        end="2026-05-25 09:35:00",
        tq_client=fake,
    )

    assert [call["period"] for call in fake.market_calls] == ["5m", "1m"]
    assert all(int(call["count"]) > 0 for call in fake.market_calls)
    assert bars[["date", "open", "high", "low", "close", "volume", "amount"]].to_dict("records") == [
        {
            "date": pd.Timestamp("2026-05-25 09:35:00"),
            "open": 10.0,
            "high": 15.0,
            "low": 9.0,
            "close": 14.5,
            "volume": 500.0,
            "amount": 5000.0,
        }
    ]


def test_fetch_tdx_bars_derives_15m_from_1m_when_5m_empty() -> None:
    fake = _PeriodFakeTq(
        {
            "1m": _tdx_payload(
                pd.date_range("2026-05-25 09:31:00", periods=15, freq="1min"),
                opens=list(range(10, 25)),
                highs=list(range(11, 26)),
                lows=list(range(9, 24)),
                closes=[value + 0.5 for value in range(10, 25)],
            )
        }
    )

    bars = tdx.fetch_tdx_bars(
        symbols=("000001.SZ",),
        timeframe="15m",
        start="2026-05-25 09:30:00",
        end="2026-05-25 09:45:00",
        tq_client=fake,
    )

    assert [call["period"] for call in fake.market_calls] == ["15m", "5m", "1m"]
    assert all(int(call["count"]) > 0 for call in fake.market_calls)
    assert bars[["date", "open", "high", "low", "close", "volume", "amount"]].to_dict("records") == [
        {
            "date": pd.Timestamp("2026-05-25 09:45:00"),
            "open": 10.0,
            "high": 25.0,
            "low": 9.0,
            "close": 24.5,
            "volume": 1500.0,
            "amount": 15000.0,
        }
    ]


def test_start_tdx_terminal_launches_when_not_running(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    launched: list[tuple[list[str], str]] = []

    class _Popen:
        def __init__(self, args: list[str], *, cwd: str, stdout: object, stderr: object) -> None:
            launched.append((args, cwd))

    monkeypatch.setattr(tdx.sys, "platform", "win32")
    monkeypatch.setattr(tdx, "_tdx_terminal_is_running", lambda: False)
    monkeypatch.setattr(tdx, "_find_tdx_terminal", lambda _: Path("C:/new_tdx64/TdxW.exe"))
    monkeypatch.setattr(tdx.subprocess, "Popen", _Popen)
    monkeypatch.setattr(tdx.time, "sleep", lambda _: None)

    tdx._start_tdx_terminal_if_needed("")

    assert launched == [(["C:/new_tdx64/TdxW.exe"], "C:/new_tdx64")]


def test_start_tdx_terminal_skips_when_already_running(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tdx.sys, "platform", "win32")
    monkeypatch.setattr(tdx, "_tdx_terminal_is_running", lambda: True)
    monkeypatch.setattr(
        tdx.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not launch")),
    )

    tdx._start_tdx_terminal_if_needed("")


def test_tdx_terminal_running_checks_current_windows_session(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    class _Process:
        stdout = b"TdxW.exe 5448 Console 2"

    def fake_run(command: list[str], **_: object) -> _Process:
        calls.append(command)
        return _Process()

    monkeypatch.setattr(tdx, "_current_windows_session_id", lambda: 2)
    monkeypatch.setattr(tdx.subprocess, "run", fake_run)

    assert tdx._tdx_terminal_is_running()
    assert calls == [
        ["tasklist", "/FI", "IMAGENAME eq TdxW.exe", "/FI", "SESSION eq 2"],
    ]


def _windows_text(path: Path) -> str:
    return str(path).replace("/", "\\").lower()


def _tdx_payload(
    dates: pd.DatetimeIndex,
    *,
    opens: list[int],
    highs: list[int],
    lows: list[int],
    closes: list[float],
) -> dict[str, pd.DataFrame]:
    return {
        "Open": pd.DataFrame({"000001.SZ": opens}, index=dates),
        "High": pd.DataFrame({"000001.SZ": highs}, index=dates),
        "Low": pd.DataFrame({"000001.SZ": lows}, index=dates),
        "Close": pd.DataFrame({"000001.SZ": closes}, index=dates),
        "Volume": pd.DataFrame({"000001.SZ": [100] * len(dates)}, index=dates),
        "Amount": pd.DataFrame({"000001.SZ": [1000] * len(dates)}, index=dates),
    }
