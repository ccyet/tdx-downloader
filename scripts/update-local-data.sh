#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_ROOT="${TDX_DATA_ROOT_HOST:-/Volumes/ccOUT 1/tdx-data}"
TDX_PATH="${TDX_TQCENTER_PATH:-/Volumes/[C] Windows 11/new_tdx64/PYPlugins}"
ASSET_TYPES="${ASSET_TYPES:-stock,etf,index}"
TIMEFRAMES="${TIMEFRAMES:-1d,5m}"
ADJUST="${ADJUST:-qfq}"
BATCH_SIZE="${BATCH_SIZE:-100}"
RUNTIME="${RUNTIME:-auto}"
END_DATE="${END_DATE:-$(date +%F)}"

if [[ -z "${START_DATE:-}" ]]; then
  if START_DATE="$(date -v-30d +%F 2>/dev/null)"; then
    :
  else
    START_DATE="$(date -d '30 days ago' +%F)"
  fi
fi

echo "Updating TDX local cache"
echo "  data_root:   $DATA_ROOT"
echo "  tdx_path:    $TDX_PATH"
echo "  asset_types: $ASSET_TYPES"
echo "  timeframes:  $TIMEFRAMES"
echo "  window:      $START_DATE -> $END_DATE"

export TDX_DATA_ROOT_HOST="$DATA_ROOT"
export TDX_TQCENTER_PATH="$TDX_PATH"
export TIMEFRAMES
export ADJUST

"$PYTHON_BIN" -m tdx_downloader.cli prepare-data \
  --asset-types "$ASSET_TYPES" \
  --timeframes "$TIMEFRAMES" \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --adjust "$ADJUST" \
  --data-root "$DATA_ROOT" \
  --tdx-path "$TDX_PATH" \
  --batch-size "$BATCH_SIZE" \
  --runtime "$RUNTIME" \
  --output table

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
)
print(f"Catalog refreshed: {snapshot.catalog_path} ({len(snapshot.catalog)} rows)")
PY
