# TDX Downloader 运维手册

## 服务入口

- 本机下载 Web 服务：`http://127.0.0.1:8767`
- 源码默认 Web 端口：`8622`
- Windows Worker Mac 入口：`http://127.0.0.1:18765`
- Windows Worker 监听端口：`8765`
- 默认数据目录：`/Volumes/ccOUT 1/tdx-data`
- Windows Worker 仓库：`C:\tdx-downloader-app`
- Windows Worker scratch：`C:\tdx_jobs`

## 启停 Web 服务

本机下载 Web 服务由 launchd 管理：

```bash
launchctl kickstart -k "gui/$(id -u)/com.local.tdx-downloader.web-api"
```

检查配置：

```bash
curl http://127.0.0.1:8767/api/config
```

日志：

```text
/Users/a1234/Library/Logs/tdx-downloader/web-api-8767.out.log
/Users/a1234/Library/Logs/tdx-downloader/web-api-8767.err.log
```

## Windows Worker

Worker 应从 Windows 本地目录启动：

```powershell
cd C:\tdx-downloader-app
python -m tdx_downloader.cli tdx-worker --host 0.0.0.0 --port 8765 --scratch-root C:\tdx_jobs
```

Mac 侧健康检查：

```bash
curl http://127.0.0.1:18765/health
```

`/health` 只表示 Worker/Python/项目 import 可用，不表示通达信下载成功。真实下载要看任务事件中的 `tdx_refresh_start`、`tdx_refresh_done`、`refresh_ms` 和 `rows`。

Windows 版本检查：

```powershell
cd C:\tdx-downloader-app
Select-String -Path tdx_downloader\data\tdx.py -Pattern 'REFRESHABLE_KLINE_PERIODS = {"1d", "1m", "5m"}'
Select-String -Path tdx_downloader\data\tdx_worker.py -Pattern 'MAX_INITIAL_EMPTY_FETCH_WINDOWS = 3'
Select-String -Path tdx_downloader\data\tdx_parallels.py -Pattern 'DEFAULT_WINDOWS_WORKER_REPO = r"C:\tdx-downloader-app"'
C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe -m compileall -q tdx_downloader
```

## 下载事件判读

- `tdx_refresh_start`：开始调用 TDX `refresh_kline()`。
- `tdx_refresh_done`：TDX 刷新调用返回。
- `tdx_batch_start`：开始读取一个批次。
- `tdx_batch_done`：批次读取结束。
- `tdx_no_rows`：窗口无返回数据。
- `refresh_ms=0`：没有触发刷新，不是下载很快。
- `rows=0 + refresh_ms=0`：通常是没有进入真实刷新链路。

如果 UI 显示进度但通达信端口无通信，先确认 Windows `C:\tdx-downloader-app` 是否包含当前代码，再看 `/api/tasks` 的事件和计时字段。不要只看 Worker `/health`。

连续 3 个初始窗口都无数据时，Worker 应提前失败；不应继续显示完整市场的假进度。

## 覆盖索引

刷新覆盖索引：

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

缓存扫描异常时，先确认 coverage/catalog 是否指向 `/Volumes/ccOUT 1/tdx-data`，再看 Web 日志。

## Docker 边界

Docker 适合常驻 Web/API 和读取已挂载的数据缓存。通达信、Parallels Windows C 盘、Windows Worker 仍建议由 Mac 本地服务协调；容器不能直接打开本机文件夹选择弹窗，也不能自动看到未挂载的 TDX 目录。

## 最小验证

```bash
python -m compileall -q tdx_downloader
python -m pytest tests/test_tdx_source.py tests/test_tdx_worker.py tests/test_tdx_parallels.py tests/test_web_api.py -q -k "tdx_batch_start or refresh or timing or initial_empty or fetch_windows or worker_config_defaults or start_parallels_tdx_worker or progress"
git diff --check
```
