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

CLI：

```bash
python -m tdx_downloader.cli inventory-data --data-root data/market/daily
python -m tdx_downloader.cli plan-data \
  --symbols 000001.SZ,600519.SH \
  --timeframes 1d,5m,60m \
  --start 2026-05-01 \
  --end 2026-06-01 \
  --data-root data/market/daily
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

## 数据目录

默认数据目录为当前项目下：

```text
data/market/daily/<adjust>/<symbol>.parquet
data/market/<timeframe>/<adjust>/<symbol>.parquet
data/market/metadata/market_data_catalog.sqlite
```

`1d` 写入 `daily` 目录；分钟周期写入对应周期目录。
