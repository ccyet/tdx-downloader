#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${TDX_UPDATE_LAUNCHD_LABEL:-com.local.tdx-downloader.update-local-data}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
SUPPORT_DIR="$HOME/Library/Application Support/tdx-downloader"
WRAPPER_PATH="$SUPPORT_DIR/update-local-data-launchd.sh"
UPDATE_COPY_PATH="$SUPPORT_DIR/update-local-data.sh"
DATA_ROOT="${TDX_DATA_ROOT_HOST:-/Volumes/ccOUT 1/tdx-data}"
PYTHON_BIN="${PYTHON_BIN:-python}"
UPDATE_HOUR="${TDX_UPDATE_HOUR:-17}"
UPDATE_MINUTE="${TDX_UPDATE_MINUTE:-10}"
UPDATE_TRIGGER_GRACE_MINUTES="${TDX_UPDATE_TRIGGER_GRACE_MINUTES:-10}"
UPDATE_SHARDS="${UPDATE_SHARDS:-10}"
TIMEFRAMES="${TIMEFRAMES:-1d,5m}"
TDX_PATH="${TDX_TQCENTER_PATH:-/Volumes/[C] Windows 11/new_tdx64/PYPlugins}"
WORKER_URL="${TDX_WORKER_URL:-http://127.0.0.1:18765}"
SYNC_TRADING_CALENDAR="${SYNC_TRADING_CALENDAR:-auto}"
STATUS_MAX_AGE_HOURS="${TDX_UPDATE_STATUS_MAX_AGE_HOURS:-36}"
REQUIRE_LAUNCHD_TRIGGER="${TDX_REQUIRE_LAUNCHD_TRIGGER:-0}"
REQUIRE_LOCAL_CALENDAR="${TDX_REQUIRE_LOCAL_CALENDAR:-0}"
REQUIRE_CLEAN_FINAL_PLAN="${TDX_REQUIRE_CLEAN_FINAL_PLAN:-0}"
VERIFY_RESULT_FILE="${TDX_VERIFY_RESULT_FILE:-$DATA_ROOT/metadata/update-local-data-verify.json}"
RUN_ALL_SHARDS_VALUE="1"
LOG_DIR="$DATA_ROOT/logs/update-local-data"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/tdx-downloader"
STDOUT_LOG="$LAUNCHD_LOG_DIR/launchd.out.log"
STDERR_LOG="$LAUNCHD_LOG_DIR/launchd.err.log"

resolve_python_bin() {
  if [[ "$PYTHON_BIN" == */* ]]; then
    if [[ -x "$PYTHON_BIN" ]]; then
      return
    fi
    echo "Python 不可执行：$PYTHON_BIN" >&2
    exit 2
  fi
  local resolved=""
  resolved="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
  if [[ -z "$resolved" && -x "/opt/anaconda3/bin/$PYTHON_BIN" ]]; then
    resolved="/opt/anaconda3/bin/$PYTHON_BIN"
  fi
  if [[ -z "$resolved" && -x "/usr/local/bin/$PYTHON_BIN" ]]; then
    resolved="/usr/local/bin/$PYTHON_BIN"
  fi
  if [[ -z "$resolved" ]]; then
    echo "找不到 Python：$PYTHON_BIN。请设置 PYTHON_BIN=/path/to/python。" >&2
    exit 2
  fi
  PYTHON_BIN="$resolved"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") install|uninstall|status|verify|run-once

Environment:
  TDX_DATA_ROOT_HOST       default: $DATA_ROOT
  TDX_TQCENTER_PATH        default: $TDX_PATH
  TDX_WORKER_URL           default: $WORKER_URL
  PYTHON_BIN               default: $PYTHON_BIN
  TDX_UPDATE_HOUR          default: $UPDATE_HOUR
  TDX_UPDATE_MINUTE        default: $UPDATE_MINUTE
  TDX_UPDATE_TRIGGER_GRACE_MINUTES default: $UPDATE_TRIGGER_GRACE_MINUTES
  UPDATE_SHARDS            default: $UPDATE_SHARDS
  TIMEFRAMES               default: $TIMEFRAMES
  TDX_UPDATE_STATUS_MAX_AGE_HOURS default: $STATUS_MAX_AGE_HOURS
  TDX_REQUIRE_LAUNCHD_TRIGGER default: $REQUIRE_LAUNCHD_TRIGGER
  TDX_REQUIRE_LOCAL_CALENDAR default: $REQUIRE_LOCAL_CALENDAR
  TDX_REQUIRE_CLEAN_FINAL_PLAN default: $REQUIRE_CLEAN_FINAL_PLAN
  TDX_VERIFY_RESULT_FILE default: $VERIFY_RESULT_FILE
  SYNC_TRADING_CALENDAR  default: $SYNC_TRADING_CALENDAR
EOF
}

plist_env_entry() {
  local key="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    return
  fi
  "$PYTHON_BIN" - "$key" "$value" <<'PY'
import html
import sys

key = html.escape(sys.argv[1], quote=False)
value = html.escape(sys.argv[2], quote=False)
print(f"    <key>{key}</key>")
print(f"    <string>{value}</string>")
PY
}

existing_plist_env_value() {
  local key="$1"
  if [[ ! -f "$PLIST_PATH" ]]; then
    return
  fi
  "$PYTHON_BIN" - "$PLIST_PATH" "$key" <<'PY'
import plistlib
import sys

path = sys.argv[1]
key = sys.argv[2]
try:
    with open(path, "rb") as handle:
        payload = plistlib.load(handle)
except Exception:
    raise SystemExit(0)
value = (payload.get("EnvironmentVariables") or {}).get(key) or ""
if value:
    print(value)
PY
}

resolved_env_value() {
  local key="$1"
  local current="${!key:-}"
  if [[ -n "$current" ]]; then
    printf '%s\n' "$current"
    return
  fi
  existing_plist_env_value "$key"
}

write_plist() {
  resolve_python_bin
  local fuyao_api_key=""
  local aicubes_api_key=""
  local ths_api_key=""
  fuyao_api_key="$(resolved_env_value FUYAO_API_KEY)"
  aicubes_api_key="$(resolved_env_value AICUBES_API_KEY)"
  ths_api_key="$(resolved_env_value THS_API_KEY)"
  if [[ "$UPDATE_SHARDS" -le 1 ]]; then
    RUN_ALL_SHARDS_VALUE="0"
  else
    RUN_ALL_SHARDS_VALUE="1"
  fi
  mkdir -p "$PLIST_DIR" "$LOG_DIR" "$LAUNCHD_LOG_DIR" "$SUPPORT_DIR"
  cp "$ROOT_DIR/scripts/update-local-data.sh" "$UPDATE_COPY_PATH"
  chmod +x "$UPDATE_COPY_PATH"
  cat > "$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export TDX_PROJECT_ROOT="$ROOT_DIR"
now_minutes="\$(date '+%H %M' | awk '{print \$1 * 60 + \$2}')"
scheduled_minutes="$((10#$UPDATE_HOUR * 60 + 10#$UPDATE_MINUTE))"
trigger_delta="\$((now_minutes - scheduled_minutes))"
if [[ "\$trigger_delta" -ge 0 && "\$trigger_delta" -le "$UPDATE_TRIGGER_GRACE_MINUTES" ]]; then
  export UPDATE_TRIGGER="launchd-scheduled"
else
  export UPDATE_TRIGGER="launchd-manual"
fi
cd "$SUPPORT_DIR"
exec /bin/bash "$UPDATE_COPY_PATH"
EOF
  chmod +x "$WRAPPER_PATH"
  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WRAPPER_PATH</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$SUPPORT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHON_BIN</key>
    <string>$PYTHON_BIN</string>
    <key>TDX_DATA_ROOT_HOST</key>
    <string>$DATA_ROOT</string>
    <key>TDX_TQCENTER_PATH</key>
    <string>$TDX_PATH</string>
    <key>TDX_WORKER_URL</key>
    <string>$WORKER_URL</string>
    <key>UPDATE_WINDOW</key>
    <string>daily</string>
    <key>RUN_ALL_SHARDS</key>
    <string>$RUN_ALL_SHARDS_VALUE</string>
    <key>UPDATE_SHARDS</key>
    <string>$UPDATE_SHARDS</string>
    <key>TIMEFRAMES</key>
    <string>$TIMEFRAMES</string>
    <key>POST_CHECK_STRICT</key>
    <string>1</string>
    <key>COMPACT_DELTA</key>
    <string>0</string>
    <key>SYNC_TRADING_CALENDAR</key>
    <string>$SYNC_TRADING_CALENDAR</string>
$(plist_env_entry FUYAO_API_KEY "$fuyao_api_key")
$(plist_env_entry AICUBES_API_KEY "$aicubes_api_key")
$(plist_env_entry THS_API_KEY "$ths_api_key")
    <key>UPDATE_LOG</key>
    <string>1</string>
    <key>UPDATE_LOG_DIR</key>
    <string>$LAUNCHD_LOG_DIR/update-local-data</string>
    <key>UPDATE_LOCK_DIR</key>
    <string>$SUPPORT_DIR/update-local-data.lock</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$UPDATE_HOUR</integer>
    <key>Minute</key>
    <integer>$UPDATE_MINUTE</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$STDOUT_LOG</string>
  <key>StandardErrorPath</key>
  <string>$STDERR_LOG</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF
}

install_job() {
  write_plist
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  launchctl enable "gui/$(id -u)/$LABEL"
  echo "Installed launchd job: $PLIST_PATH"
}

uninstall_job() {
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
  rm -f "$WRAPPER_PATH"
  rm -f "$UPDATE_COPY_PATH"
  echo "Uninstalled launchd job: $PLIST_PATH"
}

status_job() {
  resolve_python_bin
  echo "plist: $PLIST_PATH"
  echo "wrapper: $WRAPPER_PATH"
  echo "update_copy: $UPDATE_COPY_PATH"
  local status_ok=0
  if [[ -f "$PLIST_PATH" ]]; then
    echo "plist_exists: yes"
  else
    echo "plist_exists: no"
    status_ok=1
  fi
  if [[ -f "$WRAPPER_PATH" ]]; then
    echo "wrapper_exists: yes"
  else
    echo "wrapper_exists: no"
    status_ok=1
  fi
  if [[ -f "$UPDATE_COPY_PATH" ]]; then
    echo "update_copy_exists: yes"
    if cmp -s "$ROOT_DIR/scripts/update-local-data.sh" "$UPDATE_COPY_PATH"; then
      echo "update_copy_sync: yes"
    else
      echo "update_copy_sync: no"
      status_ok=1
    fi
  else
    echo "update_copy_exists: no"
    status_ok=1
  fi
  print_worker_health_check || status_ok=1
  if launchctl print "gui/$(id -u)/$LABEL"; then
    echo "launchd_loaded: yes"
  else
    echo "launchd_loaded: no"
    status_ok=1
  fi
  status_file="$DATA_ROOT/metadata/update-local-data-status.json"
  if [[ -f "$status_file" ]]; then
    echo "last_status: $status_file"
    cat "$status_file"
    if ! "$PYTHON_BIN" - "$status_file" "$STATUS_MAX_AGE_HOURS" "$DATA_ROOT" "$REQUIRE_LAUNCHD_TRIGGER" "$REQUIRE_LOCAL_CALENDAR" "$REQUIRE_CLEAN_FINAL_PLAN" "${TDX_WRITE_VERIFY_RESULT:-0}" "$VERIFY_RESULT_FILE" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from tdx_downloader.data.trading_calendar import trade_date_status

path = sys.argv[1]
max_age_hours = float(sys.argv[2])
data_root = sys.argv[3]
require_launchd_trigger = str(sys.argv[4]).strip().lower() in {"1", "true", "yes", "on"}
require_local_calendar = str(sys.argv[5]).strip().lower() in {"1", "true", "yes", "on"}
require_clean_final_plan = str(sys.argv[6]).strip().lower() in {"1", "true", "yes", "on"}
write_verify_result = str(sys.argv[7]).strip().lower() in {"1", "true", "yes", "on"}
verify_result_file = Path(sys.argv[8])
status_failed = False
failure_reasons: list[str] = []
payload = json.load(open(path, encoding="utf-8"))
exit_code = int(payload.get("exit_code") or 0)
ended_at = str(payload.get("ended_at") or "")
ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
age_hours = (datetime.now(timezone.utc) - ended).total_seconds() / 3600
if exit_code != 0:
    print(f"status_check: failed exit_code={exit_code}")
    raise SystemExit(1)
if age_hours > max_age_hours:
    print(f"status_check: stale age_hours={age_hours:.2f} max={max_age_hours:.2f}")
    raise SystemExit(1)

calendar = trade_date_status(data_root=data_root, now=datetime.now().astimezone())
calendar_source = str(calendar.get("source") or "")
calendar_status = str(calendar.get("calendar_status") or "")
expected_trade_date = str(calendar.get("trade_date") or "")
calendar_key_names = ("FUYAO_API_KEY", "AICUBES_API_KEY", "THS_API_KEY")
configured_calendar_keys = [name for name in calendar_key_names if os.environ.get(name, "").strip()]
if configured_calendar_keys:
    print(f"calendar_key_check: ok keys={','.join(configured_calendar_keys)}")
else:
    print("calendar_key_check: missing keys=FUYAO_API_KEY,AICUBES_API_KEY,THS_API_KEY")
if calendar_source != "local":
    print(
        "calendar_check: warn "
        f"source={calendar_source} "
        f"status={calendar_status} "
        f"last_day={calendar.get('calendar_last_day') or ''} "
        f"local_last_day={calendar.get('local_last_day') or ''} "
        "message=本地交易日历未覆盖当前候选交易日，节假日可能误判更新窗口；请在服务配置页同步同花顺交易日历。"
    )
    if require_local_calendar:
        status_failed = True
        failure_reasons.append("calendar_not_local")
else:
    print(
        "calendar_check: ok "
        f"source={calendar_source} "
        f"status={calendar_status} "
        f"last_day={calendar.get('calendar_last_day') or ''} "
        f"local_last_day={calendar.get('local_last_day') or ''}"
    )
start_date = str(payload.get("start_date") or "")
end_date = str(payload.get("end_date") or "")
if start_date > expected_trade_date or end_date < expected_trade_date:
    print(
        "status_check: stale_window "
        f"expected={expected_trade_date} "
        f"window={start_date}->{end_date}"
    )
    status_failed = True
    failure_reasons.append("stale_window")
summary = payload.get("summary") or {}
totals = summary.get("totals") or {}
risk_levels = summary.get("risk_levels") or {}
final_plan = summary.get("final_plan") or {}
summary_fetch_count = int(totals.get("fetch_count") or 0)
summary_derive_count = int(totals.get("derive_count") or 0)
summary_unknown_count = int(totals.get("coverage_unknown_count") or 0)
summary_risk_errors = int(risk_levels.get("error") or 0)
final_fetch_count = int(final_plan.get("fetch_count") or 0)
final_derive_count = int(final_plan.get("derive_count") or 0)
final_unknown_count = int(final_plan.get("coverage_unknown_count") or 0)
final_fetch_missing_rows = int(final_plan.get("fetch_missing_rows") or 0)
print(
    "last_run: "
    f"started={payload.get('started_at') or ''} "
    f"ended={payload.get('ended_at') or ''} "
    f"duration={int(payload.get('duration_seconds') or 0)}s "
    f"trigger={payload.get('update_trigger') or ''} "
    f"window={payload.get('start_date') or ''}->{payload.get('end_date') or ''} "
    f"log={payload.get('log_path') or ''}"
)
trigger = str(payload.get("update_trigger") or "")
if trigger == "launchd-scheduled":
    print("trigger_check: ok source=launchd-scheduled")
else:
    print(f"trigger_check: pending source={trigger or 'unknown'} note=等待下一次 launchd 自动触发验证")
    if require_launchd_trigger:
        status_failed = True
        failure_reasons.append("trigger_not_launchd_scheduled")
print(
    "summary_check: "
    f"fetch={summary_fetch_count} "
    f"derive={summary_derive_count} "
    f"unknown={summary_unknown_count} "
    f"unresolved={int(totals.get('unresolved_count') or 0)} "
    f"rows_written={int(totals.get('rows_written') or 0)} "
    f"new_rows={int(totals.get('new_rows') or 0)} "
    f"risk_errors={summary_risk_errors}"
)
print(
    "final_plan_check: "
    f"fetch={final_fetch_count} "
    f"derive={final_derive_count} "
    f"unknown={final_unknown_count} "
    f"fetch_missing_rows={final_fetch_missing_rows}"
)
if require_clean_final_plan and (
    summary_fetch_count
    or summary_derive_count
    or summary_unknown_count
    or summary_risk_errors
    or final_fetch_count
    or final_derive_count
    or final_unknown_count
    or final_fetch_missing_rows
):
    status_failed = True
    failure_reasons.append("final_plan_not_clean")
for row in final_plan.get("by_timeframe") or []:
    if not isinstance(row, dict):
        continue
    timeframe = str(row.get("timeframe") or "")
    if not timeframe:
        continue
    print(
        "timeframe_plan_check: "
        f"timeframe={timeframe} "
        f"fetch={int(row.get('fetch_count') or 0)} "
        f"derive={int(row.get('derive_count') or 0)} "
        f"unknown={int(row.get('coverage_unknown_count') or 0)} "
        f"unresolved={int(row.get('unresolved_count') or 0)} "
        f"missing_rows={int(row.get('missing_rows') or 0)} "
        f"fetch_missing_rows={int(row.get('fetch_missing_rows') or 0)}"
    )
for row in final_plan.get("unresolved_items") or []:
    if not isinstance(row, dict):
        continue
    print(
        "unresolved_gap_check: "
        f"symbol={row.get('stock_code') or ''} "
        f"timeframe={row.get('timeframe') or ''} "
        f"reason={row.get('reason') or ''} "
        f"missing_rows={int(row.get('missing_rows') or 0)} "
        f"window={row.get('first_missing_at') or ''}->{row.get('last_missing_at') or ''}"
    )
print(f"window_check: expected={expected_trade_date} actual={start_date}->{end_date} calendar={calendar_source}")
print(f"status_check: ok age_hours={age_hours:.2f}")
if write_verify_result:
    verify_result_file.parent.mkdir(parents=True, exist_ok=True)
    result_payload = {
        "ok": not status_failed,
        "failure_reasons": failure_reasons,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status_file": str(path),
        "last_run": {
            "started_at": payload.get("started_at") or "",
            "ended_at": payload.get("ended_at") or "",
            "trigger": trigger,
            "window": f"{start_date}->{end_date}",
            "log_path": payload.get("log_path") or "",
        },
        "calendar": {
            "source": calendar_source,
            "status": calendar_status,
            "trade_date": expected_trade_date,
            "last_day": calendar.get("calendar_last_day") or "",
            "local_last_day": calendar.get("local_last_day") or "",
        },
        "summary": {
            "fetch": summary_fetch_count,
            "derive": summary_derive_count,
            "unknown": summary_unknown_count,
            "unresolved": int(totals.get("unresolved_count") or 0),
            "rows_written": int(totals.get("rows_written") or 0),
            "new_rows": int(totals.get("new_rows") or 0),
            "risk_errors": summary_risk_errors,
        },
        "final_plan": {
            "fetch": final_fetch_count,
            "derive": final_derive_count,
            "unknown": final_unknown_count,
            "fetch_missing_rows": final_fetch_missing_rows,
        },
    }
    tmp_path = verify_result_file.with_suffix(verify_result_file.suffix + ".tmp")
    tmp_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(verify_result_file)
    print(f"verify_result: {verify_result_file}")
if status_failed:
    raise SystemExit(1)
PY
    then
      status_ok=1
    fi
  else
    echo "last_status: missing"
    status_ok=1
  fi
  print_recent_write_check "$status_file" || true
  return "$status_ok"
}

print_worker_health_check() {
  "$PYTHON_BIN" - "$WORKER_URL" <<'PY'
from __future__ import annotations

import sys

from tdx_downloader.data.tdx_worker_client import TdxWorkerClient

worker_url = sys.argv[1]
try:
    health = TdxWorkerClient(worker_url, timeout_seconds=2).health()
except Exception as exc:
    print(f"worker_check: failed url={worker_url} error={exc}")
    raise SystemExit(1)
deps = health.get("dependencies") if isinstance(health, dict) else {}
missing = sorted(name for name, ok in (deps or {}).items() if not ok)
if missing:
    print(f"worker_check: failed url={worker_url} missing_deps={','.join(missing)}")
    raise SystemExit(1)
print(
    "worker_check: ok "
    f"url={worker_url} "
    f"python={health.get('python') or ''} "
    f"scratch={health.get('scratch_root') or ''}"
)
PY
}

print_recent_write_check() {
  local status_file="$1"
  "$PYTHON_BIN" - "$status_file" "$DATA_ROOT/logs/update-local-data" "$LAUNCHD_LOG_DIR/update-local-data" <<'PY'
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
import re
import sys

status_path = Path(sys.argv[1])
try:
    payload = json.loads(status_path.read_text(encoding="utf-8") or "{}")
except (OSError, json.JSONDecodeError):
    payload = {}
summary = payload.get("summary") if isinstance(payload, dict) else {}
totals = summary.get("totals") if isinstance(summary, dict) else {}
status_log = Path(str(payload.get("log_path") or "")) if isinstance(payload, dict) else Path()
needs_write_evidence = bool(int(totals.get("fetch_count") or 0) or int(totals.get("derive_count") or 0))

log_dirs = [Path(value) for value in sys.argv[2:] if value]
logs: list[Path] = []
if status_log and str(status_log) != ".":
    logs.append(status_log)
elif not needs_write_evidence:
    print("recent_write_check: not_required note=latest_status_has_no_fetch_or_derive")
    raise SystemExit(0)
for log_dir in log_dirs:
    if needs_write_evidence and log_dir.exists():
        logs.extend(path for path in log_dir.glob("update-*.log") if path.is_file())
logs = sorted(set(logs), key=lambda path: path.stat().st_mtime, reverse=True)[:80]

summary_pattern = re.compile(r"prepare summary: .*?rows_written=(\d+).*?new_rows=(\d+).*?actions=({.*?}).*?statuses=({.*?})")
post_check_pattern = re.compile(r"^\s*(True|False)\s+\d+\s+\d+\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")

for path in logs:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        continue
    for index, line in enumerate(lines):
        match = summary_pattern.search(line)
        if not match:
            continue
        rows_written = int(match.group(1))
        new_rows = int(match.group(2))
        if rows_written <= 0 and new_rows <= 0:
            continue
        post_ok = "unknown"
        post_fetch = "unknown"
        post_fetch_missing = "unknown"
        for after in lines[index + 1 : index + 8]:
            post = post_check_pattern.match(after)
            if post:
                post_ok = post.group(1).lower()
                post_fetch = post.group(2)
                post_fetch_missing = post.group(4)
                break
        age_hours = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600
        print(
            "recent_write_check: "
            f"rows_written={rows_written} "
            f"new_rows={new_rows} "
            f"post_ok={post_ok} "
            f"post_fetch={post_fetch} "
            f"post_fetch_missing_rows={post_fetch_missing} "
            f"age_hours={age_hours:.2f} "
            f"log={path}"
        )
        raise SystemExit(0)
if needs_write_evidence:
    print("recent_write_check: missing note=latest_status_needs_write_evidence_but_no_positive_write_found")
    raise SystemExit(1)
print("recent_write_check: not_required note=latest_status_has_no_fetch_or_derive")
raise SystemExit(0)
PY
}

run_once() {
  resolve_python_bin
  TDX_DATA_ROOT_HOST="$DATA_ROOT" \
  TDX_TQCENTER_PATH="$TDX_PATH" \
  TDX_WORKER_URL="$WORKER_URL" \
  PYTHON_BIN="$PYTHON_BIN" \
  UPDATE_WINDOW=daily \
  UPDATE_TRIGGER=manual-run-once \
  RUN_ALL_SHARDS=1 \
  UPDATE_SHARDS="$UPDATE_SHARDS" \
  TIMEFRAMES="$TIMEFRAMES" \
  POST_CHECK_STRICT=1 \
  COMPACT_DELTA=0 \
  "$ROOT_DIR/scripts/update-local-data.sh"
}

verify_job() {
  REQUIRE_LAUNCHD_TRIGGER=1
  REQUIRE_LOCAL_CALENDAR=1
  REQUIRE_CLEAN_FINAL_PLAN=1
  TDX_WRITE_VERIFY_RESULT=1
  status_job
}

case "${1:-}" in
  install)
    install_job
    ;;
  uninstall)
    uninstall_job
    ;;
  status)
    status_job
    ;;
  verify)
    verify_job
    ;;
  run-once)
    run_once
    ;;
  *)
    usage
    exit 2
    ;;
esac
