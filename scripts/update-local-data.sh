#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${TDX_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_ROOT="${TDX_DATA_ROOT_HOST:-/Volumes/ccOUT 1/tdx-data}"
TDX_PATH="${TDX_TQCENTER_PATH:-/Volumes/[C] Windows 11/new_tdx64/PYPlugins}"
ASSET_TYPES="${ASSET_TYPES:-stock,etf,index}"
TIMEFRAMES="${TIMEFRAMES:-1d,5m}"
UPDATE_UNIVERSE="${UPDATE_UNIVERSE:-existing}"
UPDATE_WINDOW="${UPDATE_WINDOW:-daily}"
ADJUST="${ADJUST:-qfq}"
BATCH_SIZE="${BATCH_SIZE:-100}"
SYMBOL_LIMIT="${SYMBOL_LIMIT:-0}"
SYMBOL_OFFSET="${SYMBOL_OFFSET:-0}"
UPDATE_SHARDS="${UPDATE_SHARDS:-1}"
UPDATE_SHARD_INDEX="${UPDATE_SHARD_INDEX:-0}"
RUN_ALL_SHARDS="${RUN_ALL_SHARDS:-0}"
RUNTIME="${RUNTIME:-auto}"
WORKER_URL="${TDX_WORKER_URL:-http://127.0.0.1:18765}"
WORKER_ALLOW_CLI_FALLBACK="${TDX_WORKER_ALLOW_CLI_FALLBACK:-0}"
END_DATE="${END_DATE:-}"
DAILY_CHECK="${DAILY_CHECK:-1}"
POST_CHECK="${POST_CHECK:-1}"
COMPACT_DELTA="${COMPACT_DELTA:-0}"
COMPACT_DELTA_PARTS="${COMPACT_DELTA_PARTS:-200}"
COMPACT_DELTA_BYTES="${COMPACT_DELTA_BYTES:-268435456}"
PLAN_FETCH_THRESHOLD="${PLAN_FETCH_THRESHOLD:-6000}"
PLAN_MISSING_THRESHOLD="${PLAN_MISSING_THRESHOLD:-400000}"
FAIL_ON_LARGE_FETCH_PLAN="${FAIL_ON_LARGE_FETCH_PLAN:-0}"
FAIL_ON_LARGE_MISSING_PLAN="${FAIL_ON_LARGE_MISSING_PLAN:-1}"
FAIL_ON_UNRESOLVED_PROVIDER_GAP="${FAIL_ON_UNRESOLVED_PROVIDER_GAP:-0}"
REFRESH_COVERAGE="${REFRESH_COVERAGE:-0}"
MAINTAIN_CATALOG="${MAINTAIN_CATALOG:-1}"
VACUUM_CATALOG="${VACUUM_CATALOG:-0}"
FORCE_CATALOG_REFRESH="${FORCE_CATALOG_REFRESH:-0}"
UPDATE_LOCK="${UPDATE_LOCK:-1}"
UPDATE_LOCK_DIR="${UPDATE_LOCK_DIR:-}"
UPDATE_LOG="${UPDATE_LOG:-1}"
UPDATE_LOG_DIR="${UPDATE_LOG_DIR:-$DATA_ROOT/logs/update-local-data}"
UPDATE_STATUS_FILE="${UPDATE_STATUS_FILE:-$DATA_ROOT/metadata/update-local-data-status.json}"
UPDATE_TRIGGER="${UPDATE_TRIGGER:-manual-shell}"
PREPARE_OUTPUT="${PREPARE_OUTPUT:-json}"
COMPACT_OUTPUT="${COMPACT_OUTPUT:-json}"
POST_CHECK_STRICT="${POST_CHECK_STRICT:-1}"
SYNC_TRADING_CALENDAR="${SYNC_TRADING_CALENDAR:-auto}"
TDX_PROGRESS_JSONL="${TDX_PROGRESS_JSONL:-1}"
UPDATE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
UPDATE_STARTED_EPOCH="$(date +%s)"
UPDATE_SUMMARY_FILE="${UPDATE_SUMMARY_FILE:-$(mktemp "${TMPDIR:-/tmp}/tdx-update-summary.XXXXXX")}"

init_update_summary() {
  "$PYTHON_BIN" - "$UPDATE_SUMMARY_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
payload = {
    "shards": [],
    "totals": {
        "symbol_count": 0,
        "row_count": 0,
        "fetch_count": 0,
        "derive_count": 0,
        "cached_count": 0,
        "unresolved_count": 0,
        "missing_rows": 0,
        "fetch_missing_rows": 0,
        "coverage_unknown_count": 0,
        "rows_written": 0,
        "new_rows": 0,
    },
    "risk_counts": {},
    "risk_levels": {},
    "worker_ok": None,
    "final_plan": {},
    "delta": {},
    "catalog": {},
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False)
    handle.write("\n")
PY
}

merge_update_summary_payload() {
  local kind="$1"
  local shard_index="$2"
  local payload_path="$3"
  "$PYTHON_BIN" - "$UPDATE_SUMMARY_FILE" "$kind" "$shard_index" "$payload_path" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
kind = sys.argv[2]
shard_index = int(sys.argv[3])
payload_path = Path(sys.argv[4])

try:
    summary = json.loads(summary_path.read_text(encoding="utf-8") or "{}")
except FileNotFoundError:
    summary = {}
try:
    payload = json.loads(payload_path.read_text(encoding="utf-8") or "{}")
except FileNotFoundError:
    payload = {}

summary.setdefault("shards", [])
summary.setdefault("totals", {})
summary.setdefault("risk_counts", {})
summary.setdefault("risk_levels", {})

def add_total(key, value):
    try:
        amount = int(float(value or 0))
    except (TypeError, ValueError):
        amount = 0
    summary["totals"][key] = int(summary["totals"].get(key) or 0) + amount

def normalized_plan(plan):
    return {
        "row_count": int(plan.get("row_count") or 0),
        "fetch_count": int(plan.get("fetch_count") or 0),
        "derive_count": int(plan.get("derive_count") or 0),
        "cached_count": int(plan.get("cached_count") or 0),
        "unresolved_count": int(plan.get("unresolved_count") or 0),
        "missing_rows": int(plan.get("missing_rows") or 0),
        "fetch_missing_rows": int(plan.get("fetch_missing_rows") or 0),
        "coverage_unknown_count": int(plan.get("coverage_unknown_count") or 0),
    }

def merge_risks(risks):
    for risk in risks or []:
        code = str(risk.get("code") or "unknown")
        level = str(risk.get("level") or "")
        summary["risk_counts"][code] = int(summary["risk_counts"].get(code) or 0) + 1
        if level:
            summary["risk_levels"][level] = int(summary["risk_levels"].get(level) or 0) + 1

if kind in {"preflight", "postcheck"}:
    plan = payload.get("plan") or {}
    shard = {
        "shard_index": shard_index,
        "kind": kind,
        "ok": bool(payload.get("ok")),
        "elapsed_ms": int(payload.get("elapsed_ms") or 0),
        "symbol_count": int(payload.get("symbol_count") or 0),
        "plan": normalized_plan(plan),
        "risks": payload.get("risks") or [],
    }
    by_timeframe = []
    for row in plan.get("by_timeframe") or []:
        if isinstance(row, dict):
            normalized = normalized_plan(row)
            normalized["timeframe"] = str(row.get("timeframe") or "")
            by_timeframe.append(normalized)
    if by_timeframe:
        shard["plan"]["by_timeframe"] = by_timeframe
    unresolved_items = []
    for row in plan.get("unresolved_items") or []:
        if isinstance(row, dict):
            unresolved_items.append(dict(row))
    if unresolved_items:
        shard["plan"]["unresolved_items"] = unresolved_items
    summary["shards"].append(shard)
    if kind == "preflight":
        add_total("symbol_count", payload.get("symbol_count"))
        for key in (
            "row_count",
            "fetch_count",
            "derive_count",
            "cached_count",
            "unresolved_count",
            "missing_rows",
            "fetch_missing_rows",
            "coverage_unknown_count",
        ):
            add_total(key, plan.get(key))
        summary["final_plan"] = shard["plan"]
    if kind == "postcheck":
        summary["final_plan"] = shard["plan"]
    worker = payload.get("worker") or {}
    if isinstance(worker, dict) and "ok" in worker:
        current = summary.get("worker_ok")
        summary["worker_ok"] = bool(worker.get("ok")) if current is None else bool(current and worker.get("ok"))
    merge_risks(payload.get("risks") or [])
elif kind == "prepare":
    rows = payload if isinstance(payload, list) else []
    rows_written = 0
    new_rows = 0
    for row in rows:
        try:
            rows_written += int(float(row.get("rows_written") or 0))
            new_rows += int(float(row.get("new_rows") or 0))
        except (AttributeError, TypeError, ValueError):
            continue
    add_total("rows_written", rows_written)
    add_total("new_rows", new_rows)
    summary["shards"].append(
        {
            "shard_index": shard_index,
            "kind": kind,
            "row_count": len(rows),
            "rows_written": rows_written,
            "new_rows": new_rows,
        }
    )
elif kind == "delta":
    summary["delta"] = payload
elif kind == "catalog":
    summary["catalog"] = payload

tmp_path = summary_path.with_suffix(summary_path.suffix + ".tmp")
tmp_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
tmp_path.replace(summary_path)
PY
}

init_update_summary

write_update_status() {
  local exit_code="$1"
  mkdir -p "$(dirname "$UPDATE_STATUS_FILE")"
  "$PYTHON_BIN" - "$UPDATE_STATUS_FILE" "$UPDATE_SUMMARY_FILE" <<'PY'
import json
import os
import sys

path = sys.argv[1]
summary_path = sys.argv[2]
try:
    summary = json.loads(open(summary_path, encoding="utf-8").read() or "{}")
except FileNotFoundError:
    summary = {}

def aggregate_final_plan(summary):
    by_shard = {}
    for shard in summary.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        kind = str(shard.get("kind") or "")
        if kind not in {"preflight", "postcheck"}:
            continue
        shard_index = int(shard.get("shard_index") or 0)
        current = by_shard.get(shard_index)
        if current is None or kind == "postcheck":
            by_shard[shard_index] = shard
    totals = {
        "row_count": 0,
        "fetch_count": 0,
        "derive_count": 0,
        "cached_count": 0,
        "unresolved_count": 0,
        "missing_rows": 0,
        "fetch_missing_rows": 0,
        "coverage_unknown_count": 0,
    }
    by_timeframe = {}
    unresolved_items = []
    for shard in by_shard.values():
        plan = shard.get("plan") or {}
        for key in totals:
            totals[key] += int(plan.get(key) or 0)
        for row in plan.get("by_timeframe") or []:
            if not isinstance(row, dict):
                continue
            timeframe = str(row.get("timeframe") or "")
            if not timeframe:
                continue
            target = by_timeframe.setdefault(timeframe, {key: 0 for key in totals})
            target["timeframe"] = timeframe
            for key in totals:
                target[key] += int(row.get(key) or 0)
        for row in plan.get("unresolved_items") or []:
            if isinstance(row, dict):
                unresolved_items.append(dict(row))
    if by_timeframe:
        totals["by_timeframe"] = [by_timeframe[key] for key in sorted(by_timeframe)]
    if unresolved_items:
        totals["unresolved_items"] = unresolved_items[:20]
    return totals

summary["final_plan"] = aggregate_final_plan(summary)
payload = {
    "started_at": os.environ.get("UPDATE_STARTED_AT", ""),
    "ended_at": os.environ.get("UPDATE_ENDED_AT", ""),
    "duration_seconds": int(os.environ.get("UPDATE_DURATION_SECONDS") or 0),
    "exit_code": int(os.environ.get("UPDATE_EXIT_CODE") or 0),
    "log_path": os.environ.get("UPDATE_LOG_PATH", ""),
    "data_root": os.environ.get("TDX_DATA_ROOT_HOST", ""),
    "tdx_path": os.environ.get("TDX_TQCENTER_PATH", ""),
    "asset_types": os.environ.get("ASSET_TYPES", ""),
    "timeframes": os.environ.get("TIMEFRAMES", ""),
    "update_universe": os.environ.get("UPDATE_UNIVERSE", ""),
    "update_window": os.environ.get("UPDATE_WINDOW", ""),
    "update_trigger": os.environ.get("UPDATE_TRIGGER", ""),
    "start_date": os.environ.get("START_DATE", ""),
    "end_date": os.environ.get("END_DATE", ""),
    "update_shards": os.environ.get("UPDATE_SHARDS", ""),
    "run_all_shards": os.environ.get("RUN_ALL_SHARDS", ""),
    "post_check_strict": os.environ.get("POST_CHECK_STRICT", ""),
    "compact_delta": os.environ.get("COMPACT_DELTA", ""),
    "worker_url": os.environ.get("TDX_WORKER_URL", ""),
    "summary": summary,
}
tmp_path = f"{path}.tmp"
with open(tmp_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.replace(tmp_path, path)
PY
}

on_exit() {
  local exit_code="$?"
  export UPDATE_EXIT_CODE="$exit_code"
  export UPDATE_ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  export UPDATE_DURATION_SECONDS="$(($(date +%s) - UPDATE_STARTED_EPOCH))"
  write_update_status "$exit_code" || true
  if [[ -n "${LOCK_DIR:-}" && -d "${LOCK_DIR:-}" ]]; then
    rm -rf "$LOCK_DIR"
  fi
}

trap on_exit EXIT

if [[ "$UPDATE_LOG" == "1" && -z "${UPDATE_LOG_ACTIVE:-}" ]]; then
  mkdir -p "$UPDATE_LOG_DIR"
  log_stamp="$(date +%Y%m%d-%H%M%S)"
  log_path="$UPDATE_LOG_DIR/update-${log_stamp}-$$.log"
  export UPDATE_LOG_ACTIVE=1
  export UPDATE_LOG_PATH="$log_path"
  exec > >(tee -a "$log_path") 2>&1
fi

if [[ -z "${START_DATE:-}" || -z "${END_DATE:-}" ]]; then
  if [[ "$UPDATE_WINDOW" == "daily" ]]; then
    completed_day="$("$PYTHON_BIN" - "$DATA_ROOT" <<'PY'
import sys

from tdx_downloader.data.trading_calendar import trade_date_status

print(trade_date_status(data_root=sys.argv[1])["trade_date"])
PY
)"
    START_DATE="${START_DATE:-$completed_day}"
    END_DATE="${END_DATE:-$completed_day}"
  elif [[ "$UPDATE_WINDOW" == "backfill" ]]; then
    END_DATE="${END_DATE:-$(date +%F)}"
    if [[ -z "${START_DATE:-}" ]]; then
      if START_DATE="$(date -v-30d +%F 2>/dev/null)"; then
        :
      else
        START_DATE="$(date -d '30 days ago' +%F)"
      fi
    fi
  else
    echo "Unsupported UPDATE_WINDOW=$UPDATE_WINDOW; use daily or backfill" >&2
    exit 2
  fi
fi

echo "Updating TDX local cache"
echo "  data_root:   $DATA_ROOT"
echo "  tdx_path:    $TDX_PATH"
echo "  asset_types: $ASSET_TYPES"
echo "  timeframes:  $TIMEFRAMES"
echo "  universe:    $UPDATE_UNIVERSE"
echo "  window_mode: $UPDATE_WINDOW"
echo "  trigger:     $UPDATE_TRIGGER"
echo "  shard:       ${UPDATE_SHARD_INDEX}/${UPDATE_SHARDS} limit=${SYMBOL_LIMIT} offset=${SYMBOL_OFFSET}"
echo "  all_shards:  $RUN_ALL_SHARDS"
echo "  window:      $START_DATE -> $END_DATE"
echo "  check:       $DAILY_CHECK"
echo "  post_check:  $POST_CHECK"
echo "  compact:     $COMPACT_DELTA"
echo "  compact_at:  ${COMPACT_DELTA_PARTS} parts / ${COMPACT_DELTA_BYTES} bytes"
echo "  fetch_gate:  ${PLAN_FETCH_THRESHOLD} / fail=${FAIL_ON_LARGE_FETCH_PLAN}"
echo "  missing_gate:${PLAN_MISSING_THRESHOLD} / fail=${FAIL_ON_LARGE_MISSING_PLAN}"
echo "  unresolved:  fail=${FAIL_ON_UNRESOLVED_PROVIDER_GAP}"
echo "  coverage:    $REFRESH_COVERAGE"
echo "  maintain:    $MAINTAIN_CATALOG"
echo "  catalog:     force_refresh=$FORCE_CATALOG_REFRESH"
echo "  lock:        $UPDATE_LOCK"
echo "  log:         ${UPDATE_LOG_PATH:-disabled}"
echo "  worker_url:  $WORKER_URL"
echo "  output:      prepare=${PREPARE_OUTPUT} compact=${COMPACT_OUTPUT} post_strict=${POST_CHECK_STRICT}"
echo "  calendar:    sync=${SYNC_TRADING_CALENDAR}"

export TDX_DATA_ROOT_HOST="$DATA_ROOT"
export TDX_TQCENTER_PATH="$TDX_PATH"
export TDX_WORKER_URL="$WORKER_URL"
export TDX_WORKER_ALLOW_CLI_FALLBACK="$WORKER_ALLOW_CLI_FALLBACK"
export TDX_PROGRESS_JSONL
export ASSET_TYPES
export UPDATE_UNIVERSE
export UPDATE_WINDOW
export UPDATE_TRIGGER
export UPDATE_SHARDS
export RUN_ALL_SHARDS
export POST_CHECK_STRICT
export COMPACT_DELTA
export SYNC_TRADING_CALENDAR
export UPDATE_STARTED_AT
export START_DATE
export END_DATE
export TIMEFRAMES
export ADJUST
PREPARE_WORK_DONE=0
COMPACT_WORK_DONE=0

SYMBOL_SOURCE="auto"
if [[ "$UPDATE_UNIVERSE" == "existing" ]]; then
  SYMBOL_SOURCE="cached-primary"
elif [[ "$UPDATE_UNIVERSE" == "cached" ]]; then
  SYMBOL_SOURCE="cached"
elif [[ "$UPDATE_UNIVERSE" == "all" ]]; then
  SYMBOL_SOURCE="metadata"
else
  echo "Unsupported UPDATE_UNIVERSE=$UPDATE_UNIVERSE; use existing, cached, or all" >&2
  exit 2
fi

LOCK_DIR="${UPDATE_LOCK_DIR:-$DATA_ROOT/metadata/update-local-data.lock}"
if [[ "$UPDATE_LOCK" == "1" ]]; then
  mkdir -p "$DATA_ROOT/metadata"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [[ -f "$LOCK_DIR/pid" ]]; then
      lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
      if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
        echo "Another update-local-data task is running: pid=$lock_pid lock=$LOCK_DIR" >&2
        exit 2
      fi
      echo "Removing stale update lock: $LOCK_DIR" >&2
      rm -rf "$LOCK_DIR"
      mkdir "$LOCK_DIR"
    else
      echo "Removing stale update lock without pid: $LOCK_DIR" >&2
      rm -rf "$LOCK_DIR"
      if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "Cannot acquire update lock after stale cleanup: $LOCK_DIR" >&2
        exit 2
      fi
    fi
  fi
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
fi

if [[ "$SYNC_TRADING_CALENDAR" != "0" && "$SYNC_TRADING_CALENDAR" != "off" ]]; then
  echo "Syncing trading calendar"
  calendar_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-trading-calendar.XXXXXX")"
  calendar_args=(
    trading-calendar-sync
    --data-root "$DATA_ROOT"
    --output json
  )
  if [[ "$SYNC_TRADING_CALENDAR" == "auto" ]]; then
    calendar_args+=(--skip-without-key)
  fi
  if "$PYTHON_BIN" -m tdx_downloader.cli "${calendar_args[@]}" > "$calendar_tmp"; then
    "$PYTHON_BIN" - "$calendar_tmp" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read() or "{}")
print(
    "trading calendar summary: "
    f"ok={bool(payload.get('ok'))} "
    f"skipped={bool(payload.get('skipped'))} "
    f"days={int(payload.get('day_count') or 0)} "
    f"window={payload.get('first_day') or ''}->{payload.get('last_day') or ''} "
    f"message={payload.get('message') or ''}"
)
PY
  else
    echo "Trading calendar sync failed; continuing with local calendar/fallback." >&2
    cat "$calendar_tmp" >&2 || true
  fi
  rm -f "$calendar_tmp"
fi

run_update_for_shard() {
  local shard_index="$1"
  local preflight_tmp=""
  local preflight_action_count=""
  echo "Running shard ${shard_index}/${UPDATE_SHARDS}"

  if [[ "$DAILY_CHECK" == "1" ]]; then
    echo "Running daily preflight check"
    preflight_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-daily-check-${shard_index}.XXXXXX")"
    daily_check_args=(
      daily-check
      --asset-types "$ASSET_TYPES"
      --symbol-source "$SYMBOL_SOURCE"
      --symbol-limit "$SYMBOL_LIMIT"
      --symbol-offset "$SYMBOL_OFFSET"
      --symbol-shard-count "$UPDATE_SHARDS"
      --symbol-shard-index "$shard_index"
      --timeframes "$TIMEFRAMES"
      --start "$START_DATE"
      --end "$END_DATE"
      --adjust "$ADJUST"
      --data-root "$DATA_ROOT"
      --tdx-path "$TDX_PATH"
      --delta-part-threshold "$COMPACT_DELTA_PARTS"
      --delta-byte-threshold "$COMPACT_DELTA_BYTES"
      --plan-fetch-threshold "$PLAN_FETCH_THRESHOLD"
      --plan-missing-threshold "$PLAN_MISSING_THRESHOLD"
      --output json
    )
    if [[ "$FAIL_ON_LARGE_FETCH_PLAN" == "1" ]]; then
      daily_check_args+=(--fail-on-large-fetch-plan)
    fi
    if [[ "$FAIL_ON_LARGE_MISSING_PLAN" == "1" ]]; then
      daily_check_args+=(--fail-on-large-missing-plan)
    fi
    "$PYTHON_BIN" -m tdx_downloader.cli daily-check \
      "${daily_check_args[@]:1}" > "$preflight_tmp"
    merge_update_summary_payload preflight "$shard_index" "$preflight_tmp"
    "$PYTHON_BIN" - "$preflight_tmp" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read() or "{}")
plan = payload.get("plan") or {}
risks = payload.get("risks") or []
delta = (payload.get("delta") or {}).get("summary") or {}
timings = payload.get("timings") or {}
print(
    "daily preflight summary: "
    f"ok={bool(payload.get('ok'))} elapsed_ms={int(payload.get('elapsed_ms') or 0)} "
    f"symbols={int(payload.get('symbol_count') or 0)} "
    f"fetch={int(plan.get('fetch_count') or 0)} derive={int(plan.get('derive_count') or 0)} "
    f"unresolved={int(plan.get('unresolved_count') or 0)} missing_rows={int(plan.get('missing_rows') or 0)} "
    f"fetch_missing_rows={int(plan.get('fetch_missing_rows') or 0)} "
    f"risks={len(risks)} delta_parts={int(delta.get('part_count') or 0)}"
)
if timings:
    print(
        "daily preflight timings: "
        f"resolve={int(timings.get('resolve_symbols_ms') or 0)}ms "
        f"worker={int(timings.get('worker_health_ms') or 0)}ms "
        f"delta={int(timings.get('delta_summary_ms') or 0)}ms "
        f"catalog={int(timings.get('catalog_maintain_ms') or 0)}ms "
        f"plan={int(timings.get('preview_plan_ms') or 0)}ms"
    )
for risk in risks:
    print(f"  {risk.get('level', '')} {risk.get('code', '')}: {risk.get('message', '')}")
PY
    preflight_action_count="$("$PYTHON_BIN" - "$preflight_tmp" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read() or "{}")
plan = payload.get("plan") or {}
print(int(plan.get("fetch_count") or 0) + int(plan.get("derive_count") or 0))
PY
)"
  fi

  if [[ "$DAILY_CHECK" == "1" && "${preflight_action_count:-}" == "0" ]]; then
    echo "Skipping prepare-data: preflight found no fetch or derive work."
    echo "prepare summary: skipped rows=0 rows_written=0 new_rows=0 missing_rows=0 actions={} statuses={}"
    rm -f "$preflight_tmp"
    if [[ "$POST_CHECK" == "1" ]]; then
      echo "Skipping post-download verification: no fetch or derive work; preflight already checked this shard."
    fi
    return
  fi
  rm -f "$preflight_tmp"
  PREPARE_WORK_DONE=1

  prepare_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-prepare-${shard_index}.XXXXXX")"
  trap 'rm -f "$prepare_tmp"' RETURN
  "$PYTHON_BIN" -m tdx_downloader.cli prepare-data \
    --asset-types "$ASSET_TYPES" \
    --symbol-source "$SYMBOL_SOURCE" \
    --symbol-limit "$SYMBOL_LIMIT" \
    --symbol-offset "$SYMBOL_OFFSET" \
    --symbol-shard-count "$UPDATE_SHARDS" \
    --symbol-shard-index "$shard_index" \
    --timeframes "$TIMEFRAMES" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --adjust "$ADJUST" \
    --data-root "$DATA_ROOT" \
    --tdx-path "$TDX_PATH" \
    --batch-size "$BATCH_SIZE" \
    --runtime "$RUNTIME" \
    --output "$PREPARE_OUTPUT" > "$prepare_tmp"
  if [[ "$PREPARE_OUTPUT" == "json" ]]; then
    merge_update_summary_payload prepare "$shard_index" "$prepare_tmp"
    "$PYTHON_BIN" - "$prepare_tmp" <<'PY'
import json
import sys
from collections import Counter

path = sys.argv[1]
rows = json.loads(open(path, encoding="utf-8").read() or "[]")
actions = Counter(str(row.get("action") or "") for row in rows)
statuses = Counter(str(row.get("after_status") or row.get("status") or "") for row in rows)
rows_written = sum(int(float(row.get("rows_written") or 0)) for row in rows)
new_rows = sum(int(float(row.get("new_rows") or 0)) for row in rows)
missing_rows = sum(int(float(row.get("missing_rows") or 0)) for row in rows)
print(
    "prepare summary: "
    f"rows={len(rows)} rows_written={rows_written} new_rows={new_rows} "
    f"missing_rows={missing_rows} actions={dict(actions)} statuses={dict(statuses)}"
)
PY
  else
    cat "$prepare_tmp"
  fi
  rm -f "$prepare_tmp"
  trap - RETURN

  if [[ "$POST_CHECK" == "1" ]]; then
    echo "Running post-download verification"
    post_check_output="table"
    if [[ -n "${UPDATE_SUMMARY_FILE:-}" ]]; then
      post_check_output="json"
    fi
    post_check_args=(
      daily-check
      --asset-types "$ASSET_TYPES" \
      --symbol-source "$SYMBOL_SOURCE" \
      --symbol-limit "$SYMBOL_LIMIT" \
      --symbol-offset "$SYMBOL_OFFSET" \
      --symbol-shard-count "$UPDATE_SHARDS" \
      --symbol-shard-index "$shard_index" \
      --timeframes "$TIMEFRAMES" \
      --start "$START_DATE" \
      --end "$END_DATE" \
      --adjust "$ADJUST" \
      --data-root "$DATA_ROOT" \
      --tdx-path "$TDX_PATH" \
      --delta-part-threshold "$COMPACT_DELTA_PARTS" \
      --delta-byte-threshold "$COMPACT_DELTA_BYTES" \
      --plan-fetch-threshold "$PLAN_FETCH_THRESHOLD" \
      --plan-missing-threshold "$PLAN_MISSING_THRESHOLD" \
      --output "$post_check_output"
    )
    if [[ "$POST_CHECK_STRICT" == "1" ]]; then
      post_check_args+=(--fail-on-fetch --fail-on-coverage-unknown)
    fi
    if [[ "$FAIL_ON_UNRESOLVED_PROVIDER_GAP" == "1" ]]; then
      post_check_args+=(--fail-on-unresolved-provider-gap)
    fi
    if [[ "$FAIL_ON_LARGE_FETCH_PLAN" == "1" ]]; then
      post_check_args+=(--fail-on-large-fetch-plan)
    fi
    if [[ "$FAIL_ON_LARGE_MISSING_PLAN" == "1" ]]; then
      post_check_args+=(--fail-on-large-missing-plan)
    fi
    if [[ "$post_check_output" == "json" ]]; then
      post_check_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-post-check-${shard_index}.XXXXXX")"
      "$PYTHON_BIN" -m tdx_downloader.cli "${post_check_args[@]}" > "$post_check_tmp"
      merge_update_summary_payload postcheck "$shard_index" "$post_check_tmp"
      "$PYTHON_BIN" - "$post_check_tmp" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read() or "{}")
plan = payload.get("plan") or {}
risks = payload.get("risks") or []
print(
    "  ok  elapsed_ms  symbol_count timeframes  plan_fetch  plan_missing_rows  plan_fetch_missing_rows  risk_count"
)
print(
    f"{bool(payload.get('ok'))!s:>4} "
    f"{int(payload.get('elapsed_ms') or 0):>11} "
    f"{int(payload.get('symbol_count') or 0):>13} "
    f"{','.join(payload.get('timeframes') or []):>10} "
    f"{int(plan.get('fetch_count') or 0):>11} "
    f"{int(plan.get('missing_rows') or 0):>18} "
    f"{int(plan.get('fetch_missing_rows') or 0):>24} "
    f"{len(risks):>11}"
)
for risk in risks:
    print(f"{risk.get('level', ''):>5} {risk.get('code', ''):>23} {risk.get('message', '')}")
PY
      rm -f "$post_check_tmp"
    else
      "$PYTHON_BIN" -m tdx_downloader.cli "${post_check_args[@]}"
    fi
  fi
}

if [[ "$RUN_ALL_SHARDS" == "1" ]]; then
  if [[ "$UPDATE_SHARDS" -le 1 ]]; then
    echo "RUN_ALL_SHARDS=1 requires UPDATE_SHARDS > 1" >&2
    exit 2
  fi
  for ((shard_index = 0; shard_index < UPDATE_SHARDS; shard_index++)); do
    run_update_for_shard "$shard_index"
  done
else
  run_update_for_shard "$UPDATE_SHARD_INDEX"
fi

echo "Delta sidecar summary"
delta_summary_json="$("$PYTHON_BIN" -m tdx_downloader.cli delta-summary \
  --timeframes "$TIMEFRAMES" \
  --adjust "$ADJUST" \
  --data-root "$DATA_ROOT" \
  --part-threshold "$COMPACT_DELTA_PARTS" \
  --byte-threshold "$COMPACT_DELTA_BYTES" \
  --output json)"
printf '%s\n' "$delta_summary_json"
delta_summary_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-delta-summary.XXXXXX")"
printf '%s\n' "$delta_summary_json" > "$delta_summary_tmp"
merge_update_summary_payload delta 0 "$delta_summary_tmp"
rm -f "$delta_summary_tmp"

should_compact="$COMPACT_DELTA"
if [[ "$COMPACT_DELTA" == "auto" ]]; then
  should_compact="$(DELTA_SUMMARY_JSON="$delta_summary_json" "$PYTHON_BIN" - "$COMPACT_DELTA_PARTS" "$COMPACT_DELTA_BYTES" <<'PY'
import json
import os
import sys

threshold_parts = int(sys.argv[1])
threshold_bytes = int(sys.argv[2])
payload = json.loads(os.environ.get("DELTA_SUMMARY_JSON", "{}"))
summary = payload.get("summary", {})
parts = int(summary.get("part_count") or 0)
size = int(summary.get("file_size_bytes") or 0)
needs_compaction = bool(summary.get("needs_compaction"))
print("1" if needs_compaction or parts >= threshold_parts or size >= threshold_bytes else "0")
PY
)"
fi

if [[ "$should_compact" == "1" ]]; then
  echo "Compacting delta sidecars"
  COMPACT_WORK_DONE=1
  compact_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-compact.XXXXXX")"
  "$PYTHON_BIN" -m tdx_downloader.cli delta-compact \
    --timeframes "$TIMEFRAMES" \
    --adjust "$ADJUST" \
    --data-root "$DATA_ROOT" \
    --output "$COMPACT_OUTPUT" > "$compact_tmp"
  if [[ "$COMPACT_OUTPUT" == "json" ]]; then
    "$PYTHON_BIN" - "$compact_tmp" <<'PY'
import json
import sys
from collections import Counter

path = sys.argv[1]
rows = json.loads(open(path, encoding="utf-8").read() or "[]")
statuses = Counter(str(row.get("status") or "") for row in rows)
delta_parts = sum(int(float(row.get("delta_parts") or 0)) for row in rows)
delta_rows = sum(int(float(row.get("delta_rows") or 0)) for row in rows)
print(
    "compact summary: "
    f"symbols={len(rows)} delta_parts={delta_parts} delta_rows={delta_rows} statuses={dict(statuses)}"
)
PY
  else
    cat "$compact_tmp"
  fi
  rm -f "$compact_tmp"
else
  echo "Skipping delta compaction"
fi

if [[ "$REFRESH_COVERAGE" == "1" ]]; then
  echo "Refreshing coverage runs"
  "$PYTHON_BIN" -m tdx_downloader.cli coverage-refresh \
    --timeframes "$TIMEFRAMES" \
    --adjust "$ADJUST" \
    --data-root "$DATA_ROOT" \
    --output table
fi

if [[ "$FORCE_CATALOG_REFRESH" == "1" ]]; then
  "$PYTHON_BIN" - <<'PY'
import os

from tdx_downloader.data.manager import DataManagementService
from tdx_downloader.data.symbols import load_symbol_metadata

data_root = os.environ.get("TDX_DATA_ROOT_HOST", "/Volumes/ccOUT 1/tdx-data")
tdx_path = os.environ.get("TDX_TQCENTER_PATH", "/Volumes/[C] Windows 11/new_tdx64/PYPlugins")
adjust = os.environ.get("ADJUST", "qfq")
timeframes = tuple(item.strip() for item in os.environ.get("TIMEFRAMES", "1d,5m").split(",") if item.strip())

service = DataManagementService(data_root, adjust=adjust)
metadata = load_symbol_metadata(data_root, tdx_path=tdx_path)
snapshot = service.cache_snapshot(
    timeframes=timeframes,
    tdx_path=tdx_path,
    symbol_metadata=metadata,
    rebuild_catalog=True,
    refresh_coverage=False,
)
print(f"Catalog refreshed: {snapshot.catalog_path} ({len(snapshot.catalog)} rows)")
PY
else
  echo "Skipping catalog refresh: Worker/delta commits update catalog incrementally; set FORCE_CATALOG_REFRESH=1 for a full rebuild."
fi

if [[ "$MAINTAIN_CATALOG" == "1" ]]; then
  echo "Maintaining catalog SQLite"
  catalog_output="table"
  if [[ -n "${UPDATE_SUMMARY_FILE:-}" ]]; then
    catalog_output="json"
  fi
  catalog_args=(
    catalog-maintain
    --data-root "$DATA_ROOT"
    --output "$catalog_output"
  )
  if [[ "$VACUUM_CATALOG" == "1" ]]; then
    catalog_args+=(--vacuum)
  fi
  if [[ "$catalog_output" == "json" ]]; then
    catalog_tmp="$(mktemp "${TMPDIR:-/tmp}/tdx-catalog-maintain.XXXXXX")"
    "$PYTHON_BIN" -m tdx_downloader.cli "${catalog_args[@]}" > "$catalog_tmp"
    merge_update_summary_payload catalog 0 "$catalog_tmp"
    cat "$catalog_tmp"
    rm -f "$catalog_tmp"
  else
    "$PYTHON_BIN" -m tdx_downloader.cli "${catalog_args[@]}"
  fi
fi
