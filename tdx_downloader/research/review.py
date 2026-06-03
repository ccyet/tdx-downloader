from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tdx_downloader.data.schema import inclusive_end_timestamp, normalize_symbol
from tdx_downloader.research.features import max_drawdown
from tdx_downloader.research.scoring import prepare_research_bars


@dataclass(frozen=True)
class ReviewConfig:
    symbol: str
    start: str | pd.Timestamp
    end: str | pd.Timestamp
    min_swing_return: float = 0.05
    min_segment_bars: int = 3
    max_segments: int = 6


@dataclass(frozen=True)
class ReviewResult:
    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    window: pd.DataFrame
    overview: dict[str, float]
    segments: pd.DataFrame
    main_segments: pd.DataFrame
    warnings: tuple[str, ...] = ()


def analyze_price_review(bars: pd.DataFrame, config: ReviewConfig) -> ReviewResult:
    symbol = normalize_symbol(config.symbol)
    if not symbol:
        raise ValueError("复盘代码无效。")
    window = _review_window(bars, symbol, config.start, config.end)
    start = pd.Timestamp(config.start)
    end = inclusive_end_timestamp(config.end)
    if window.empty:
        return ReviewResult(
            symbol=symbol,
            start=start,
            end=end,
            window=window,
            overview=_empty_overview(),
            segments=pd.DataFrame(),
            main_segments=pd.DataFrame(),
            warnings=(f"{symbol} 在所选区间没有本地行情。",),
        )
    segments = _swing_segments(
        window,
        min_return=max(float(config.min_swing_return), 0.0),
        min_bars=max(int(config.min_segment_bars), 1),
    )
    main_segments = _select_main_segments(segments, max_segments=max(int(config.max_segments), 1))
    warnings: list[str] = []
    if len(window) < 2:
        warnings.append(f"{symbol} 所选区间 K 线不足 2 根，无法识别波段。")
    elif segments.empty:
        warnings.append("所选区间没有达到最小幅度的主要上涨或回撤段。")
    return ReviewResult(
        symbol=symbol,
        start=pd.Timestamp(window["date"].min()),
        end=pd.Timestamp(window["date"].max()),
        window=window,
        overview=_window_overview(window),
        segments=segments,
        main_segments=main_segments,
        warnings=tuple(warnings),
    )


def rank_review_results(
    results: list[ReviewResult] | tuple[ReviewResult, ...],
    comparisons: pd.DataFrame | None = None,
    *,
    stock_names: dict[str, str] | None = None,
    direction_by_symbol: dict[str, str] | None = None,
) -> pd.DataFrame:
    valid = [result for result in results if not result.window.empty]
    columns = [
        "排名",
        "代码",
        "股票",
        "所属方向",
        "对标指数",
        "指数阶段",
        "强弱等级",
        "区间收益",
        "最大回撤",
        "上涨K占比",
        "相对超额",
        "关键转折点",
        "当前性质",
        "锐评结论",
        "明日验证",
        "排序分",
    ]
    if not valid:
        return pd.DataFrame(columns=columns)

    comparison_lookup = _comparison_lookup(comparisons)
    rows: list[dict[str, object]] = []
    for result in valid:
        overview = result.overview
        comparison = comparison_lookup.get(result.symbol, {})
        period_return = _numeric(overview.get("return"))
        drawdown = _numeric(overview.get("max_drawdown"))
        up_share = _numeric(overview.get("up_day_share"))
        excess = _numeric(comparison.get("超额收益"))
        nature = _lifecycle_label(overview)
        turning_point = _turning_point_label(result.window)
        score = _ranking_score(period_return, drawdown, up_share, excess, nature)
        grade = _ranking_grade(period_return, drawdown, up_share, excess, nature, score)
        rows.append(
            {
                "代码": result.symbol,
                "股票": str((stock_names or {}).get(result.symbol, "") or "").strip(),
                "所属方向": str((direction_by_symbol or {}).get(result.symbol, "") or "-").strip() or "-",
                "对标指数": comparison.get("标的", "-") or "-",
                "指数阶段": _index_phase_label(comparison.get("对比收益")),
                "强弱等级": grade,
                "区间收益": period_return,
                "最大回撤": drawdown,
                "上涨K占比": up_share,
                "相对超额": excess,
                "关键转折点": turning_point,
                "当前性质": nature,
                "锐评结论": _ranking_critique(grade, nature, excess),
                "明日验证": _tomorrow_check(turning_point, nature, grade),
                "排序分": score,
            }
        )

    ranking = pd.DataFrame(rows).sort_values(["排序分", "相对超额", "区间收益"], ascending=False).reset_index(drop=True)
    ranking.insert(0, "排名", np.arange(1, len(ranking) + 1))
    return ranking[columns]


def _review_window(
    bars: pd.DataFrame,
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    prepared = prepare_research_bars(bars)
    prepared["stock_code"] = prepared["stock_code"].map(normalize_symbol)
    start_ts = pd.Timestamp(start)
    end_ts = inclusive_end_timestamp(end)
    window = prepared.loc[
        (prepared["stock_code"] == symbol)
        & prepared["date"].between(start_ts, end_ts)
    ]
    return window.sort_values("date").reset_index(drop=True)


def _empty_overview() -> dict[str, float]:
    return {
        "return": float("nan"),
        "max_drawdown": float("nan"),
        "up_day_share": float("nan"),
        "volatility": float("nan"),
        "bars": 0.0,
        "start_close": float("nan"),
        "end_close": float("nan"),
    }


def _window_overview(window: pd.DataFrame) -> dict[str, float]:
    close = pd.to_numeric(window["close"], errors="coerce").dropna().to_numpy(dtype=float)
    if len(close) == 0:
        return _empty_overview()
    returns = pd.Series(close).pct_change().dropna()
    return {
        "return": float(close[-1] / close[0] - 1.0) if len(close) >= 2 and close[0] else 0.0,
        "max_drawdown": max_drawdown(close),
        "up_day_share": float((returns > 0).mean()) if len(returns) else 0.0,
        "volatility": float(returns.std(ddof=0)) if len(returns) else 0.0,
        "bars": float(len(close)),
        "start_close": float(close[0]),
        "end_close": float(close[-1]),
    }


def _swing_segments(window: pd.DataFrame, *, min_return: float, min_bars: int) -> pd.DataFrame:
    close = pd.to_numeric(window["close"], errors="coerce").to_numpy(dtype=float)
    if len(close) < 2:
        return pd.DataFrame()
    pivots = _turning_point_indexes(close)
    rows: list[dict[str, object]] = []
    for left, right in zip(pivots, pivots[1:]):
        bars = int(right - left + 1)
        if bars < min_bars or not np.isfinite(close[left]) or not np.isfinite(close[right]) or close[left] == 0:
            continue
        period_return = float(close[right] / close[left] - 1.0)
        if abs(period_return) < min_return:
            continue
        rows.append(
            {
                "起点": window["date"].iloc[left],
                "终点": window["date"].iloc[right],
                "K线数": bars,
                "类型": "上涨" if period_return >= 0 else "回撤",
                "区间收益": period_return,
                "最大回撤": max_drawdown(close[left : right + 1]),
                "起点价": float(close[left]),
                "终点价": float(close[right]),
            }
        )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return frame.sort_values("区间收益", key=lambda values: values.abs(), ascending=False).reset_index(drop=True)


def _turning_point_indexes(close: np.ndarray) -> list[int]:
    changes = np.diff(close)
    directions = np.sign(changes)
    pivots = [0]
    previous = 0.0
    for index, direction in enumerate(directions, start=1):
        if direction == 0:
            continue
        if previous != 0 and direction != previous:
            pivots.append(index - 1)
        previous = direction
    if pivots[-1] != len(close) - 1:
        pivots.append(len(close) - 1)
    return pivots


def _select_main_segments(segments: pd.DataFrame, *, max_segments: int) -> pd.DataFrame:
    if segments.empty:
        return segments
    return segments.head(max_segments).reset_index(drop=True)


def _comparison_lookup(comparisons: pd.DataFrame | None) -> dict[str, dict[str, object]]:
    if comparisons is None or comparisons.empty:
        return {}
    frame = comparisons.copy()
    code_column = "代码" if "代码" in frame.columns else "symbol" if "symbol" in frame.columns else ""
    if not code_column:
        return {}
    frame["_symbol"] = frame[code_column].map(normalize_symbol)
    return {
        str(row["_symbol"]): {key: value for key, value in row.items() if key != "_symbol"}
        for _, row in frame.iterrows()
        if row["_symbol"]
    }


def _numeric(value: object, default: float = 0.0) -> float:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return default
    return float(number)


def _ranking_score(period_return: float, drawdown: float, up_share: float, excess: float, nature: str) -> float:
    nature_bonus = {
        "主升趋势": 0.12,
        "震荡上行": 0.06,
        "高位震荡": 0.02,
        "弱势修复": -0.02,
        "下行趋势": -0.12,
    }.get(nature, 0.0)
    return float(period_return + excess * 0.55 + up_share * 0.18 + drawdown * 0.65 + nature_bonus)


def _ranking_grade(period_return: float, drawdown: float, up_share: float, excess: float, nature: str, score: float) -> str:
    if period_return >= 0.18 and drawdown > -0.08 and up_share >= 0.58 and excess >= 0:
        return "夯爆了"
    if period_return >= 0.12 and drawdown > -0.12 and score >= 0.16:
        return "人上人"
    if period_return > 0.04 and excess > 0.03 and nature in {"主升趋势", "震荡上行", "高位震荡"}:
        return "立棍单打"
    if period_return > 0.02 and drawdown <= -0.12:
        return "刷子"
    if score >= -0.02:
        return "路边"
    if period_return > -0.08:
        return "NPC"
    return "拉完了"


def _lifecycle_label(overview: dict[str, float]) -> str:
    period_return = _numeric(overview.get("return"))
    drawdown = _numeric(overview.get("max_drawdown"))
    up_share = _numeric(overview.get("up_day_share"))
    if period_return >= 0.12 and drawdown > -0.1:
        return "主升趋势"
    if period_return > 0.03 and up_share >= 0.5:
        return "震荡上行"
    if period_return > -0.03 and drawdown > -0.08:
        return "高位震荡"
    if period_return > -0.08:
        return "弱势修复"
    return "下行趋势"


def _turning_point_label(window: pd.DataFrame) -> str:
    close = pd.to_numeric(window["close"], errors="coerce").dropna().to_numpy(dtype=float)
    if len(close) < 2:
        return "样本不足"
    high_index = int(np.nanargmax(close))
    low_index = int(np.nanargmin(close))
    high_date = pd.Timestamp(window["date"].iloc[high_index]).strftime("%Y-%m-%d")
    low_date = pd.Timestamp(window["date"].iloc[low_index]).strftime("%Y-%m-%d")
    if high_index > low_index:
        return f"{low_date}低点后抬升，{high_date}创区间高点"
    return f"{high_date}高点后回落，{low_date}形成区间低点"


def _index_phase_label(value: object) -> str:
    number = _numeric(value, default=float("nan"))
    if pd.isna(number):
        return "无对标"
    if number > 0.05:
        return "指数上行"
    if number < -0.05:
        return "指数下行"
    return "指数震荡"


def _ranking_critique(grade: str, nature: str, excess: float) -> str:
    if grade in {"夯爆了", "人上人"}:
        return f"{nature}里有强承接，排序靠前。"
    if grade == "立棍单打":
        return f"相对超额 {excess:.2%}，不是单纯跟指数。"
    if grade == "刷子":
        return "涨幅有，但回撤体验拖后腿。"
    if grade == "路边":
        return "跟随行情摆动，地位不突出。"
    if grade == "NPC":
        return "存在感偏弱，强度不够。"
    return "区间破位或明显跑输。"


def _tomorrow_check(turning_point: str, nature: str, grade: str) -> str:
    if grade in {"夯爆了", "人上人", "立棍单打"}:
        return f"观察能否延续{nature}，并守住{turning_point}。"
    if grade in {"刷子", "路边"}:
        return f"观察{turning_point}附近是否继续反复。"
    return f"重点看{turning_point}后是否止跌。"
