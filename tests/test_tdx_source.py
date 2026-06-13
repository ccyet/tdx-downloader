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


def test_fetch_tdx_bars_maps_adjust_to_tdx_dividend_type() -> None:
    dates = pd.date_range("2026-05-25", periods=1, freq="D")
    payload = _tdx_payload(dates, opens=[10], highs=[11], lows=[9], closes=[10.5])

    for adjust, expected_dividend_type in (("qfq", "front"), ("hfq", "back"), ("", "none")):
        fake = _PeriodFakeTq({"1d": payload})

        tdx.fetch_tdx_bars(
            symbols=("000001.SZ",),
            timeframe="1d",
            adjust=adjust,
            start="2026-05-25",
            end="2026-05-25",
            tq_client=fake,
        )

        assert fake.market_calls[0]["dividend_type"] == expected_dividend_type


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


def test_fetch_tdx_bars_reports_batch_timing_metrics() -> None:
    fake = _PeriodFakeTq({"1d": _tdx_payload(pd.date_range("2026-05-25", periods=1), opens=[10], highs=[11], lows=[9], closes=[10.5])})
    events: list[dict[str, object]] = []

    tdx.fetch_tdx_bars(
        symbols=("000001.SZ",),
        timeframe="1d",
        start="2026-05-25",
        end="2026-05-25",
        tq_client=fake,
        progress_callback=events.append,
    )

    done = next(event for event in events if event["stage"] == "tdx_batch_done")
    assert done["rows_returned"] == 1
    assert "tdx_call_ms" in done
    assert "normalize_ms" in done
    assert "total_ms" in done


def test_aggregate_5m_to_30m_does_not_cross_midday_break() -> None:
    morning = pd.date_range("2026-05-25 11:05:00", "2026-05-25 11:30:00", freq="5min")
    afternoon = pd.date_range("2026-05-25 13:05:00", "2026-05-25 13:30:00", freq="5min")
    dates = morning.append(afternoon)
    bars = pd.DataFrame(
        {
            "date": dates,
            "stock_code": ["000001.SZ"] * len(dates),
            "open": list(range(10, 10 + len(dates))),
            "high": list(range(11, 11 + len(dates))),
            "low": list(range(9, 9 + len(dates))),
            "close": [value + 0.5 for value in range(10, 10 + len(dates))],
            "volume": [100.0] * len(dates),
            "amount": [1000.0] * len(dates),
        }
    )

    aggregated = tdx.aggregate_5m_bars_to_timeframe(
        bars,
        timeframe="30m",
        start="2026-05-25 11:00:00",
        end="2026-05-25 13:30:00",
    )

    assert aggregated["date"].tolist() == [pd.Timestamp("2026-05-25 11:30:00"), pd.Timestamp("2026-05-25 13:30:00")]
    assert aggregated["volume"].tolist() == [600.0, 600.0]


def test_fetch_tdx_etf_tracking_info_normalizes_track_index_payload() -> None:
    class FakeTq:
        def __init__(self) -> None:
            self.initialize_calls: list[str] = []
            self.calls: list[str] = []

        def initialize(self, caller_path: str) -> None:
            self.initialize_calls.append(caller_path)

        def get_trackzs_etf_info(self, zs_code: str) -> list[dict[str, object]]:
            self.calls.append(zs_code)
            return [
                {
                    "Code": "510300.SH",
                    "Name": "沪深300ETF华泰柏瑞",
                    "NowPrice": "3.88",
                    "PreClose": "3.8",
                    "IOPV": "3.87",
                    "Zgb": "592384.7",
                    "Sz": "2298.6",
                },
                {"Code": "", "Name": "无效"},
            ]

    frame = tdx.fetch_tdx_etf_tracking_info(index_symbols=("000300.SH", "000300.SH"), tq_client=FakeTq())

    assert frame.to_dict("records") == [
        {
            "tracking_symbol": "000300.SH",
            "stock_code": "510300.SH",
            "stock_name": "沪深300ETF华泰柏瑞",
            "now_price": 3.88,
            "pre_close": 3.8,
            "iopv": 3.87,
            "shares": 592384.7,
            "market_value": 2298.6,
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
