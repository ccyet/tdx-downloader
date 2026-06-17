# 项目 Agent 规则

## 项目事实

- 当前项目根目录：`/Volumes/ccOUT 1/tdx-downloader`
- 默认数据目录：`/Volumes/ccOUT 1/tdx-data`
- 源码默认 Web 端口是 `8622`；这台机器的下载 Web 服务由 launchd 跑在 `8767`。
- 下载 Web 服务不是 Docker；用户要求“下载数据的 web 服务”时，优先处理 `com.local.tdx-downloader.web-api`。
- Windows Worker Mac 入口：`http://127.0.0.1:18765`
- Windows Worker 监听端口：`8765`
- Windows Worker 默认仓库：`C:\tdx-downloader-app`
- Windows Worker scratch：`C:\tdx_jobs`

## 调试规则

- 不要使用 `/daima`。
- 不要假设 Mac 仓库代码已经同步到 Windows Worker；Worker 行为异常时先验证 `C:\tdx-downloader-app` 的代码版本。
- `curl http://127.0.0.1:18765/health` 只证明 Worker/Python/项目 import 可用，不证明通达信已下载。
- UI 有进度但通达信端口无通信时，检查 `/api/tasks` 的 `tdx_refresh_start`、`tdx_refresh_done`、`refresh_ms`、`rows`。
- `refresh_ms=0` 表示未触发刷新；`tdx_batch_start` 只是读取批次，不等于实际下载。
- 不能用静默 fallback、mock 成功或吞异常掩盖下载失败。

## 常用命令

重启本机下载 Web 服务：

```bash
launchctl kickstart -k "gui/$(id -u)/com.local.tdx-downloader.web-api"
```

检查服务：

```bash
curl http://127.0.0.1:8767/api/config
curl http://127.0.0.1:18765/health
```

关键日志：

```text
/Users/a1234/Library/Logs/tdx-downloader/web-api-8767.out.log
/Users/a1234/Library/Logs/tdx-downloader/web-api-8767.err.log
```

最小验证：

```bash
python -m compileall -q tdx_downloader
python -m pytest tests/test_tdx_source.py tests/test_tdx_worker.py tests/test_tdx_parallels.py tests/test_web_api.py -q -k "tdx_batch_start or refresh or timing or initial_empty or fetch_windows or worker_config_defaults or start_parallels_tdx_worker or progress"
git diff --check
```
