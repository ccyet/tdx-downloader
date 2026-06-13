from __future__ import annotations

from pathlib import Path
from datetime import datetime
import sqlite3

import pandas as pd

from tdx_downloader.cli import _summarize_daily_plan
from tdx_downloader.cli import _import_trading_calendar
from tdx_downloader.cli import _sync_trading_calendar
from tdx_downloader.data.trading_calendar import last_completed_trade_date, save_trading_days, trade_date_status
from tdx_downloader.data.trading_calendar import trading_calendar_path_for

ROOT = Path(__file__).resolve().parents[1]
UPDATE_SCRIPT = ROOT / "scripts" / "update-local-data.sh"
LAUNCHD_SCRIPT = ROOT / "scripts" / "manage-local-update-launchd.sh"


def test_update_script_writes_machine_readable_status() -> None:
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert "UPDATE_STATUS_FILE" in source
    assert "UPDATE_LOCK_DIR" in source
    assert "update-local-data-status.json" in source
    assert "write_update_status" in source
    assert "trap on_exit EXIT" in source
    assert '"exit_code"' in source
    assert '"duration_seconds"' in source
    assert '"log_path"' in source
    assert '"summary"' in source
    assert '"final_plan"' in source
    assert '"worker_ok"' in source
    assert '"update_trigger"' in source
    assert "UPDATE_TRIGGER" in source
    assert "trigger:     $UPDATE_TRIGGER" in source
    assert "merge_update_summary_payload preflight" in source
    assert "merge_update_summary_payload prepare" in source
    assert "merge_update_summary_payload delta" in source
    assert "merge_update_summary_payload catalog" in source
    assert "POST_CHECK_STRICT:-1" in source
    assert "COMPACT_DELTA:-0" in source
    assert "SYNC_TRADING_CALENDAR:-auto" in source
    assert "trading-calendar-sync" in source
    assert "trading-calendar-import" in (ROOT / "tdx_downloader" / "cli.py").read_text(encoding="utf-8")
    assert "--skip-without-key" in source
    assert "trading calendar summary:" in source
    assert "tdx_downloader.data.trading_calendar import trade_date_status" in source
    assert "RUN_ALL_SHARDS=1 requires UPDATE_SHARDS > 1" in source
    assert "Removing stale update lock without pid" in source
    assert "Cannot acquire update lock after stale cleanup" in source
    assert ".XXXXXX.json" not in source
    assert "Skipping post-download verification: no fetch or derive work; preflight already checked this shard." in source


def test_launchd_manager_installs_daily_update_job() -> None:
    source = LAUNCHD_SCRIPT.read_text(encoding="utf-8")

    assert "install|uninstall|status|verify|run-once" in source
    assert "resolve_python_bin" in source
    assert "command -v \"$PYTHON_BIN\"" in source
    assert "/opt/anaconda3/bin/$PYTHON_BIN" in source
    assert "请设置 PYTHON_BIN=/path/to/python" in source
    assert "<string>/bin/bash</string>" in source
    assert "WRAPPER_PATH" in source
    assert "UPDATE_COPY_PATH" in source
    assert "Application Support/tdx-downloader" in source
    assert "<string>$SUPPORT_DIR</string>" in source
    assert "TDX_PROJECT_ROOT" in source
    assert "cp \"$ROOT_DIR/scripts/update-local-data.sh\" \"$UPDATE_COPY_PATH\"" in source
    assert "Library/Logs/tdx-downloader" in source
    assert "UPDATE_LOG_DIR" in source
    assert "$LAUNCHD_LOG_DIR/update-local-data" in source
    assert "UPDATE_LOCK_DIR" in source
    assert "$SUPPORT_DIR/update-local-data.lock" in source
    assert "wrapper_exists" in source
    assert "update_copy_exists" in source
    assert "update_copy_sync:" in source
    assert "cmp -s \"$ROOT_DIR/scripts/update-local-data.sh\" \"$UPDATE_COPY_PATH\"" in source
    assert "com.local.tdx-downloader.update-local-data" in source
    assert "$HOME/Library/LaunchAgents" in source
    assert "StartCalendarInterval" in source
    assert "TDX_UPDATE_HOUR:-17" in source
    assert "TDX_UPDATE_MINUTE:-10" in source
    assert "TDX_UPDATE_TRIGGER_GRACE_MINUTES:-10" in source
    assert "TDX_UPDATE_TRIGGER_GRACE_MINUTES default:" in source
    assert "TDX_UPDATE_STATUS_MAX_AGE_HOURS:-36" in source
    assert "TDX_REQUIRE_LAUNCHD_TRIGGER:-0" in source
    assert "TDX_REQUIRE_LAUNCHD_TRIGGER default:" in source
    assert "TDX_REQUIRE_LOCAL_CALENDAR:-0" in source
    assert "TDX_REQUIRE_LOCAL_CALENDAR default:" in source
    assert "TDX_REQUIRE_CLEAN_FINAL_PLAN:-0" in source
    assert "TDX_REQUIRE_CLEAN_FINAL_PLAN default:" in source
    assert "TDX_VERIFY_RESULT_FILE" in source
    assert "RUN_ALL_SHARDS_VALUE" in source
    assert "if [[ \"$UPDATE_SHARDS\" -le 1 ]]" in source
    assert "RUN_ALL_SHARDS" in source
    assert "UPDATE_SHARDS" in source
    assert "POST_CHECK_STRICT" in source
    assert "COMPACT_DELTA" in source
    assert "SYNC_TRADING_CALENDAR" in source
    assert "UPDATE_TRIGGER" in source
    assert "launchd-scheduled" in source
    assert "launchd-manual" in source
    assert "scheduled_minutes=" in source
    assert "trigger_delta=" in source
    assert "<string>launchd</string>" not in source
    assert "plist_env_entry FUYAO_API_KEY" in source
    assert "plist_env_entry AICUBES_API_KEY" in source
    assert "plist_env_entry THS_API_KEY" in source
    assert "existing_plist_env_value" in source
    assert "resolved_env_value FUYAO_API_KEY" in source
    assert "plistlib.load" in source
    assert "launchctl bootstrap" in source
    assert "launchctl bootout" in source
    assert "launchd_loaded:" in source
    assert "launchctl print \"gui/$(id -u)/$LABEL\"" in source
    assert "update-local-data-status.json" in source
    assert "status_check: ok" in source
    assert "status_check: stale" in source
    assert "status_check: failed" in source
    assert "tdx_downloader.data.trading_calendar import trade_date_status" in source
    assert "calendar_check: warn" in source
    assert "calendar_key_check:" in source
    assert "FUYAO_API_KEY,AICUBES_API_KEY,THS_API_KEY" in source
    assert "source={calendar_source}" in source
    assert "status={calendar_status}" in source
    assert "calendar_check: ok" in source
    assert "require_local_calendar" in source
    assert "local_last_day=" in source
    assert "请在服务配置页同步同花顺交易日历" in source
    assert "status_check: stale_window" in source
    assert "window_check:" in source
    assert "calendar={calendar_source}" in source
    assert "last_run:" in source
    assert "final_plan_check:" in source
    assert "timeframe_plan_check:" in source
    assert "timeframe={timeframe}" in source
    assert "unresolved_items" in UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "query_unresolved_gaps" not in source
    assert "unresolved_gap_check:" in source
    assert "reason=" in source
    assert "print_recent_write_check" in source
    assert "print_worker_health_check" in source
    assert "worker_check:" in source
    assert "TdxWorkerClient(worker_url, timeout_seconds=2).health()" in source
    assert "recent_write_check:" in source
    assert "post_fetch_missing_rows=" in source
    assert "age_hours=" in source
    assert "latest_status_has_no_fetch_or_derive" in source
    assert "latest_status_needs_write_evidence_but_no_positive_write_found" in source
    assert "log={payload.get('log_path')" in source
    assert "trigger={payload.get('update_trigger')" in source
    assert "trigger_check: ok source=launchd-scheduled" in source
    assert "trigger_check: pending" in source
    assert "require_launchd_trigger" in source
    assert "require_local_calendar" in source
    assert "require_clean_final_plan" in source
    assert "status_failed = False" in source
    assert "if status_failed:" in source
    assert "summary_check:" in source
    assert "new_rows=" in source
    assert "risk_errors=" in source
    assert "manual-run-once" in source
    assert "verify_job" in source
    assert "REQUIRE_LAUNCHD_TRIGGER=1" in source
    assert "REQUIRE_LOCAL_CALENDAR=1" in source
    assert "REQUIRE_CLEAN_FINAL_PLAN=1" in source
    assert "TDX_WRITE_VERIFY_RESULT=1" in source
    assert "failure_reasons" in source
    assert "calendar_not_local" in source
    assert "trigger_not_launchd_scheduled" in source
    assert "final_plan_not_clean" in source
    assert "verify_result:" in source


def test_scheduler_trade_date_uses_local_calendar_when_available(tmp_path: Path) -> None:
    save_trading_days(
        data_root=tmp_path,
        days=["2026-06-11", "2026-06-12", "2026-06-16"],
        source="test",
    )

    holiday_monday = datetime(2026, 6, 15, 17, 30)

    assert last_completed_trade_date(data_root=tmp_path, now=holiday_monday) == "2026-06-12"


def test_scheduler_trade_date_ignores_stale_local_calendar(tmp_path: Path) -> None:
    save_trading_days(
        data_root=tmp_path,
        days=["2026-06-05", "2026-06-08"],
        source="stale-test",
    )
    friday_after_close = datetime(2026, 6, 12, 17, 30)

    assert last_completed_trade_date(data_root=tmp_path, now=friday_after_close) == "2026-06-12"
    status = trade_date_status(data_root=tmp_path, now=friday_after_close)
    assert status["source"] == "business-day-fallback"
    assert status["calendar_status"] == "stale"
    assert status["calendar_last_day"] == "2026-06-08"


def test_scheduler_trade_date_falls_back_to_business_day_without_calendar(tmp_path: Path) -> None:
    monday_after_close = datetime(2026, 6, 15, 17, 30)

    assert last_completed_trade_date(data_root=tmp_path, now=monday_after_close) == "2026-06-15"


def test_scheduler_trade_date_reports_local_last_day_without_blocking_candidate(tmp_path: Path) -> None:
    catalog = tmp_path / "metadata" / "market_data_catalog.sqlite"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(catalog) as connection:
        connection.execute(
            """
            CREATE TABLE market_data_coverage_runs (
                stock_code TEXT,
                timeframe TEXT,
                adjust TEXT,
                start_at TEXT,
                end_at TEXT,
                row_count INTEGER,
                file_size_bytes INTEGER,
                mtime_ns INTEGER,
                path TEXT,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO market_data_coverage_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "000001.SZ",
                "1d",
                "qfq",
                "2026-06-12T00:00:00",
                "2026-06-12T00:00:00",
                1,
                1,
                1,
                "/tmp/000001.parquet",
                "2026-06-12T16:00:00",
            ),
        )

    monday_after_close = datetime(2026, 6, 15, 17, 30)
    status = trade_date_status(data_root=tmp_path, now=monday_after_close)

    assert status["trade_date"] == "2026-06-15"
    assert status["source"] == "business-day-fallback"
    assert status["calendar_status"] == "missing"
    assert status["local_last_day"] == "2026-06-12"


def test_daily_plan_summary_includes_actual_unresolved_items() -> None:
    plan = pd.DataFrame(
        [
            {
                "stock_code": "000001.SZ",
                "timeframe": "5m",
                "adjust": "qfq",
                "action": "unresolved",
                "reason": "provider_no_data",
                "coverage_status": "provider_unresolved",
                "missing_rows": 48,
                "first_missing_at": "2026-06-12 09:35:00",
                "last_missing_at": "2026-06-12 15:05:00",
                "message": "provider returned no data",
            },
            {
                "stock_code": "000002.SZ",
                "timeframe": "5m",
                "adjust": "qfq",
                "action": "cached",
                "coverage_status": "coverage_ready",
                "missing_rows": 0,
            },
        ]
    )

    summary = _summarize_daily_plan(plan)

    assert summary["unresolved_count"] == 1
    assert summary["unresolved_items"] == [
        {
            "stock_code": "000001.SZ",
            "timeframe": "5m",
            "adjust": "qfq",
            "reason": "provider_no_data",
            "coverage_status": "provider_unresolved",
            "missing_rows": 48,
            "first_missing_at": "2026-06-12 09:35:00",
            "last_missing_at": "2026-06-12 15:05:00",
            "message": "provider returned no data",
        }
    ]


def test_trading_calendar_sync_writes_local_calendar(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_fetch(api_key: str = "") -> dict[str, object]:
        assert api_key == "local-key"
        return {
            "timestamp": 1780848000000,
            "item": [{"date": "20260612"}, {"date": "20260616"}],
        }

    monkeypatch.setattr("tdx_downloader.api.fuyao_client.fetch_trading_days", fake_fetch)

    args = type(
        "Args",
        (),
        {
            "data_root": str(tmp_path),
            "api_key": "local-key",
            "skip_without_key": False,
        },
    )()

    result = _sync_trading_calendar(args)

    assert result["ok"] is True
    assert result["day_count"] == 2
    assert result["first_day"] == "2026-06-12"
    assert trading_calendar_path_for(tmp_path).exists()


def test_trading_calendar_sync_skips_without_key(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FUYAO_API_KEY", raising=False)
    monkeypatch.delenv("AICUBES_API_KEY", raising=False)
    monkeypatch.delenv("THS_API_KEY", raising=False)
    monkeypatch.setattr(
        "tdx_downloader.cli._sync_trading_calendar_from_akshare",
        lambda args: {
            "ok": False,
            "skipped": True,
            "source": "akshare",
            "message": "AkShare unavailable",
        },
    )

    args = type(
        "Args",
        (),
        {
            "data_root": str(tmp_path),
            "api_key": "",
            "skip_without_key": True,
        },
    )()

    result = _sync_trading_calendar(args)

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "missing_api_key"
    assert result["fallback_error"] == "AkShare unavailable"
    assert not trading_calendar_path_for(tmp_path).exists()


def test_trading_calendar_sync_uses_akshare_without_key(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FUYAO_API_KEY", raising=False)
    monkeypatch.delenv("AICUBES_API_KEY", raising=False)
    monkeypatch.delenv("THS_API_KEY", raising=False)
    monkeypatch.setattr(
        "tdx_downloader.cli._sync_trading_calendar_from_akshare",
        lambda args: {
            "ok": True,
            "skipped": False,
            "source": "akshare-sina",
            "raw_count": 2,
            "day_count": 2,
            "first_day": "2026-06-12",
            "last_day": "2026-06-16",
            "path": str(trading_calendar_path_for(tmp_path)),
        },
    )

    args = type(
        "Args",
        (),
        {
            "data_root": str(tmp_path),
            "api_key": "",
            "skip_without_key": True,
        },
    )()

    result = _sync_trading_calendar(args)

    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["source"] == "akshare-sina"
    assert result["fallback_reason"] == "missing_api_key"


def test_trading_calendar_import_writes_local_calendar(tmp_path: Path) -> None:
    args = type(
        "Args",
        (),
        {
            "data_root": str(tmp_path),
            "days": "2026-06-12, 20260616",
            "file": "",
            "source": "manual-test",
        },
    )()

    result = _import_trading_calendar(args)

    assert result["ok"] is True
    assert result["day_count"] == 2
    assert result["first_day"] == "2026-06-12"
    assert result["last_day"] == "2026-06-16"
    assert trading_calendar_path_for(tmp_path).exists()
    status = trade_date_status(data_root=tmp_path, now=datetime(2026, 6, 15, 17, 30))
    assert status["source"] == "local"
    assert status["trade_date"] == "2026-06-12"
