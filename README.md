# TDX Downloader

本项目用于管理本地通达信 K 线缓存、生成下载计划、通过 Parallels Windows Worker 更新数据，并提供 Web 工作台查看和操作。

默认数据目录：

```text
/Volumes/ccOUT 1/tdx-data
```

默认 Web/API 地址：

```text
http://127.0.0.1:8622
```

## 1. 本地启动 Web 服务

```bash
cd "/Volumes/ccOUT 1/tdx-downloader"
python -m pip install -r requirements.txt
python -m tdx_downloader.web_api
```

浏览器打开：

```text
http://127.0.0.1:8622
```

如果需要前端开发模式：

```bash
cd "/Volumes/ccOUT 1/tdx-downloader/web"
npm install
npm run dev
```

前端开发地址通常是：

```text
http://127.0.0.1:5173
```

## 2. Windows Worker

高速下载路径推荐使用 Windows 常驻 Worker。`prlctl exec` 只作为启动、修复或兜底诊断，不作为高频下载通道。

Windows 侧启动：

```powershell
cd C:\path\to\tdx-downloader
python -m tdx_downloader.cli tdx-worker --host 0.0.0.0 --port 8765 --scratch-root C:\tdx_jobs
```

Mac 侧默认访问：

```text
http://127.0.0.1:18765
```

需要把 Mac `18765` 转发到 Windows `8765`，或使用 Host-only/Shared Network 下可访问的 Windows IP。

检查 Worker：

```bash
curl http://127.0.0.1:18765/health
```

常用环境变量：

```bash
export TDX_WORKER_URL="http://127.0.0.1:18765"
export TDX_TQCENTER_PATH="/Volumes/[C] Windows 11/new_tdx64/PYPlugins"
export TDX_DATA_ROOT_HOST="/Volumes/ccOUT 1/tdx-data"
```

## 3. 本地手动更新数据

手动跑一次日常更新：

```bash
cd "/Volumes/ccOUT 1/tdx-downloader"

PYTHON_BIN=/opt/anaconda3/bin/python \
TDX_DATA_ROOT_HOST="/Volumes/ccOUT 1/tdx-data" \
TDX_TQCENTER_PATH="/Volumes/[C] Windows 11/new_tdx64/PYPlugins" \
TDX_WORKER_URL="http://127.0.0.1:18765" \
UPDATE_SHARDS=10 \
TIMEFRAMES="1d,5m" \
scripts/update-local-data.sh
```

生成下载计划但不下载：

```bash
python -m tdx_downloader.cli plan-data \
  --asset-types stock,etf,index \
  --timeframes 1d,5m \
  --start 2026-06-01 \
  --end 2026-06-10 \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --output json
```

只补缺口并写入本地缓存：

```bash
python -m tdx_downloader.cli prepare-data \
  --asset-types stock,etf,index \
  --timeframes 1d,5m \
  --start 2026-06-01 \
  --end 2026-06-10 \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --tdx-path "/Volumes/[C] Windows 11/new_tdx64/PYPlugins" \
  --runtime auto \
  --output table
```

## 4. 每日自动更新

安装 macOS launchd 定时任务，默认每天 17:10 运行：

```bash
cd "/Volumes/ccOUT 1/tdx-downloader"

PYTHON_BIN=/opt/anaconda3/bin/python \
TDX_DATA_ROOT_HOST="/Volumes/ccOUT 1/tdx-data" \
TDX_TQCENTER_PATH="/Volumes/[C] Windows 11/new_tdx64/PYPlugins" \
TDX_WORKER_URL="http://127.0.0.1:18765" \
UPDATE_SHARDS=10 \
TIMEFRAMES="1d,5m" \
scripts/manage-local-update-launchd.sh install
```

查看状态：

```bash
scripts/manage-local-update-launchd.sh status
```

手动触发一次：

```bash
scripts/manage-local-update-launchd.sh run-once
```

验证最近一次自动更新：

```bash
TDX_WRITE_VERIFY_RESULT=1 scripts/manage-local-update-launchd.sh verify
```

卸载：

```bash
scripts/manage-local-update-launchd.sh uninstall
```

关键日志：

```text
/Users/a1234/Library/Logs/tdx-downloader/update-local-data/
/Volumes/ccOUT 1/tdx-data/metadata/update-local-data-status.json
/Volumes/ccOUT 1/tdx-data/metadata/update-local-data-verify.json
```

## 5. 交易日历

同步同花顺/扶摇交易日历：

```bash
python -m tdx_downloader.cli trading-calendar-sync \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --api-key "$FUYAO_API_KEY" \
  --output json
```

没有 API Key 时可使用本机 AkShare fallback：

```bash
python -m tdx_downloader.cli trading-calendar-sync \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --skip-without-key \
  --output json
```

## 6. 覆盖索引与排障

刷新 K 线覆盖索引：

```bash
python -m tdx_downloader.cli coverage-refresh \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --timeframes 1d,5m \
  --output table
```

维护 catalog：

```bash
python -m tdx_downloader.cli catalog-maintain \
  --data-root "/Volumes/ccOUT 1/tdx-data" \
  --vacuum \
  --output table
```

诊断 TDX 连接：

```bash
python -m tdx_downloader.cli tdx-doctor \
  --symbols 000001.SZ \
  --timeframes 1d,5m \
  --start 2026-06-01 \
  --end 2026-06-02 \
  --tdx-path "/Volumes/[C] Windows 11/new_tdx64/PYPlugins" \
  --runtime auto \
  --output table
```

常见判断：

- Web 能打开但不能下载：先查 `TDX_WORKER_URL` 和 `curl /health`。
- 预览慢：先查 coverage 是否过期，再运行 `coverage-refresh`。
- 某些缺口反复存在：如果日志是 `provider_no_data` 或 `provider_partial_gap`，说明真实请求后 provider 未返回完整数据，系统会记录并避免无限重抓。
- Docker 里不能选择本机 TDX 目录：容器只能看到已挂载路径；通达信和 Parallels Windows C 盘建议由 Mac 本地服务/Worker 处理。

## 7. Docker 全天运行

Docker 适合常驻 Web/API 和读取本地数据缓存；不建议让容器直接挂载 Windows TDX 目录。

```bash
cd "/Volumes/ccOUT 1/tdx-downloader"
docker compose up -d --build
```

默认挂载：

```text
/Volumes/ccOUT 1/tdx-data -> /data/tdx-data
```

如果要改端口或数据目录：

```bash
TDX_API_PORT=8767 \
TDX_DATA_ROOT_HOST="/Volumes/ccOUT 1/tdx-data" \
docker compose up -d --build
```

## 8. 验证命令

```bash
python -m compileall -q tdx_downloader
python -m pytest tests/test_update_scheduler.py tests/test_tdx_worker.py -q
python -m pytest tests/test_data_manager.py -q -k "coverage or delta or catalog"
```
