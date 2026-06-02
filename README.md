# TDX Downloader

独立的 TDX 行情数据下载与缓存管理 Web 应用，从 `TrendingWinning` 当前数据模块抽取而来，不依赖原库的回测、策略或实验模块。

## 能力

- 批量下载 `1d / 1m / 5m / 15m / 30m / 60m` 行情数据
- 智能补齐：先审计本地 parquet 缓存，只下载缺失或质量不足的数据
- 强制刷新：按当前范围重新拉取并覆盖写入缓存
- 本地缓存分类：按 ETF、个股、指数、其他和周期切换查看
- SQLite catalog：扫描缓存后生成 `metadata/market_data_catalog.sqlite`
- 代码来源：内置样例、CSV/TXT 上传、手动输入、当前缓存全部、按资产类型筛选
- 日期快捷：近 N 天、年初至今、近 N 年、自定义

## 本地运行

```bash
cd ccOUT/tdx-downloader
python -m pip install -r requirements.txt
streamlit run app.py --server.port 8522
```

新的轻量 Web 控制台参考 sub2api 的前后端分离方式，避免 Streamlit 每次交互重跑整页：

```bash
python -m tdx_downloader.web_api
cd web
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。API 服务默认在 `http://127.0.0.1:8622`，Vite 开发服务会把 `/api` 转发到该服务。

CLI：

```bash
python -m tdx_downloader.cli inventory-data
python -m tdx_downloader.cli plan-data \
  --symbols 000001.SZ,600519.SH \
  --timeframes 1d,5m,60m \
  --start 2026-05-01 \
  --end 2026-06-01
```

本机 Mac + Parallels 默认数据目录：

```bash
python -m tdx_downloader.cli prepare-data \
  --symbols 000001.SZ \
  --timeframes 5m \
  --start 2026-06-01 \
  --end 2026-06-02
```

默认写入：

```text
/Volumes/ccOUT 1/tdx-data/daily/qfq/<symbol>.parquet
/Volumes/ccOUT 1/tdx-data/<timeframe>/qfq/<symbol>.parquet
```

## Streamlit Cloud 部署

- 入口文件：`app.py`
- 依赖文件：根目录 `requirements.txt`
- Python：3.11+
- 系统依赖：没有必须的 `packages.txt`

`tkinter` 不是 pip 包，也不是云端必须依赖。本地桌面运行时，如果 Python 自带 Tk，就可以点击“选择文件夹”弹出系统窗口；Streamlit Cloud 是无桌面的 Linux 环境，不能弹出用户本机文件夹窗口，因此云端不维护 `python3-tk`。

## TDX 边界

真实 TDX 下载依赖 Windows/Parallels 内的通达信 `tqcenter`。macOS 本机不能直接从通达信取数；在 macOS 上 CLI 默认通过 Parallels 调度到 Windows 侧执行。Streamlit Cloud 不能访问本机 Windows/Parallels 的 `tqcenter`，适合查看和管理已同步到云端的 parquet 缓存。

默认 Parallels 参数：

- VM：`Windows 11`
- Windows Python：`C:\Users\Public\venvs\tdx-downloader\Scripts\python.exe`
- Windows 仓库：默认由 macOS 共享路径推导，可用 `TDX_PARALLELS_REPO` 覆盖
- 外置盘共享：`/Volumes/ccOUT 1` 已配置为 Parallels Host Shared Folder，Windows 侧路径为 `\\psf\ccOUT 1`
- 通达信默认目录：`C:\new_tdx64`，可用 `TDX_TQCENTER_PATH` 覆盖 `PYPlugins/user` 路径，可用 `TDX_TERMINAL_PATH` 覆盖 `TdxW.exe`
- Windows 执行会话：必须通过 `prlctl exec --current-user` 进入当前登录用户会话；普通 `prlctl exec` 会落到 SYSTEM/Session 0，`tqcenter` 无法连接已登录的通达信客户端。

如果重建 VM，需要先加外置盘共享：

```bash
prlctl set "Windows 11" --shf-host-add "ccOUT 1" --path "/Volumes/ccOUT 1" --mode rw --enable --shf-host-automount on
```

Windows 侧必须启动并登录通达信客户端；程序会尝试在当前用户会话启动 `TdxW.exe`，但不会替用户登录。分钟线取数还依赖 Windows 通达信本地已具备对应分钟缓存；若 `tdx-doctor` 返回 `no_data`，先在 Windows 通达信内补齐对应分钟数据。

诊断：

```bash
python -m tdx_downloader.cli tdx-doctor \
  --symbols 000001.SZ \
  --timeframes 1d,5m \
  --start 2026-06-01 \
  --end 2026-06-02 \
  --runtime parallels
```

## 数据目录

默认数据目录为 `/Volumes/ccOUT 1/tdx-data`：

```text
/Volumes/ccOUT 1/tdx-data/daily/<adjust>/<symbol>.parquet
/Volumes/ccOUT 1/tdx-data/<timeframe>/<adjust>/<symbol>.parquet
/Volumes/ccOUT 1/tdx-data/metadata/market_data_catalog.sqlite
```

`1d` 写入 `daily` 目录；分钟周期写入对应周期目录。
