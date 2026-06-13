from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from tdx_downloader.data.schema import normalize_bars, normalize_symbol


TRADING_DAYS_PER_YEAR = 252
MARKET_REGIME_STUDY_WINDOWS = (5, 10, 20)
RISK_RELEASE_LAYER_ORDER = ("高波资产", "高位资产", "高流动性资产", "现金偏好代理")


@dataclass(frozen=True)
class MarketRegimeConfig:
    benchmark_symbol: str
    symbols: tuple[str, ...]
    start: str
    end: str
    forward_windows: tuple[int, ...] = (3, 5, 10)
    benchmark_rally_60_threshold: float = 0.08
    benchmark_pullback_20_threshold: float = -0.03
    pullback_20_threshold: float = -0.06
    pullback_60_threshold: float = -0.10
    liquidity_high_percentile: float = 0.80
    liquidity_mid_percentile: float = 0.35
    liquidity_low_percentile: float = 0.20
    volatility_high_percentile: float = 0.80
    volatility_low_percentile: float = 0.20
    high_position_drawdown_threshold: float = -0.10
    high_position_return_percentile: float = 0.80
    leader_return_5d_threshold: float = 0.03
    stress_ma20_break_threshold: float = 0.60
    stress_return_5d_threshold: float = 0.0
    cash_stress_score_threshold: float = 0.62
    cash_preference_proxy_threshold: float = 0.60
    risk_expansion_breadth_threshold: float = 0.60
    risk_contraction_breadth_threshold: float = 0.40
    risk_release_breadth_threshold: float = 0.45
    high_liquidity_selloff_threshold: float = 0.60
    concentration_top_n: int = 20
    daily_report_days: int = 20
    flow_candidate_limit: int = 30
    risk_timeline_days: int = 60


def run_market_regime_research(bars: pd.DataFrame, config: MarketRegimeConfig) -> dict[str, object]:
    normalized = normalize_bars(bars)
    if normalized.empty:
        raise ValueError("市场风险偏好研究没有可用本地日线数据。")
    symbols = tuple(symbol for symbol in (normalize_symbol(value) for value in config.symbols) if symbol)
    if not symbols:
        raise ValueError("市场风险偏好研究至少需要 1 个研究标的。")
    benchmark_symbol = normalize_symbol(config.benchmark_symbol)
    frame = _feature_frame(normalized, config=config, benchmark_symbol=benchmark_symbol)
    if frame.empty:
        raise ValueError("市场风险偏好研究无法生成特征。")
    asset_frame = frame.loc[frame["stock_code"].isin(symbols)].copy()
    if asset_frame.empty:
        raise ValueError("市场风险偏好研究标的没有可用特征。")
    start_ts = pd.Timestamp(config.start)
    end_ts = pd.Timestamp(config.end)
    classified_frame = _classify_frame(asset_frame, config)
    sample_frame = classified_frame.loc[classified_frame["date"].between(start_ts, end_ts)].copy()
    latest = _latest_rows(classified_frame.loc[classified_frame["date"] <= end_ts])
    if latest.empty:
        raise ValueError("市场风险偏好研究在所选结束日期前没有标的行情。")
    benchmark_frame = frame.loc[frame["stock_code"] == benchmark_symbol].copy()
    benchmark_daily = benchmark_frame.set_index("date") if not benchmark_frame.empty else pd.DataFrame()
    benchmark_forward = _benchmark_forward_returns(
        benchmark_daily,
        tuple(sorted({*config.forward_windows, *MARKET_REGIME_STUDY_WINDOWS})),
    )
    factor_backtest = _factor_backtest(
        classified_frame,
        benchmark_forward=benchmark_forward,
        config=config,
        start=start_ts,
        end=end_ts,
    )
    factor_advantage = _factor_advantage(factor_backtest)
    adjustment_factor_backtest = _factor_backtest(
        classified_frame,
        benchmark_forward=benchmark_forward,
        config=config,
        start=start_ts,
        end=end_ts,
        adjustment_only=True,
    )
    adjustment_factor_advantage = _factor_advantage(adjustment_factor_backtest)
    benchmark_regime = _benchmark_regime(
        frame,
        benchmark_symbol=benchmark_symbol,
        config=config,
        start=start_ts,
        end=end_ts,
    )
    migration_layers = _migration_layers(latest)
    risk_layer_history = _risk_release_layer_history(sample_frame, config)
    latest_layer_history = _risk_release_layer_history(latest, config)
    risk_release_sequence = _risk_release_sequence(risk_layer_history, latest_layer_history)
    risk_release_timeline = _risk_release_timeline(risk_layer_history, config)
    high_liquidity_break_study = _high_liquidity_break_study(sample_frame, benchmark_forward=benchmark_forward)
    market_scope = _market_scope(sample_frame, config)
    risk_appetite = _risk_appetite(latest, migration_layers, market_scope, config)
    risk_appetite_components = _risk_appetite_components(latest, migration_layers, market_scope, config)
    risk_appetite_series = _risk_appetite_series(sample_frame, market_scope, config)
    flow_candidates = _flow_candidates(latest, config)
    state_report = _state_report(latest, risk_appetite, config)
    daily_report_history = _daily_report_history(
        sample_frame=sample_frame,
        risk_layer_history=risk_layer_history,
        factor_backtest=adjustment_factor_backtest,
        market_scope=market_scope,
        config=config,
    )
    daily_report = _daily_report(
        latest=latest,
        config=config,
        risk_appetite=risk_appetite,
        state_report=state_report,
        migration_layers=migration_layers,
        factor_backtest=adjustment_factor_backtest,
        risk_release_sequence=risk_release_sequence,
        market_scope=market_scope,
    )
    answer_cards = _answer_cards(
        daily_report=daily_report,
        risk_appetite=risk_appetite,
        factor_advantage=adjustment_factor_advantage,
        risk_release_sequence=risk_release_sequence,
        flow_candidates=flow_candidates,
    )
    return {
        "summary": {
            "benchmark_symbol": benchmark_symbol,
            "asset_count": int(latest["stock_code"].nunique()),
            "start": start_ts,
            "end": end_ts,
            "as_of": latest["date"].max(),
            "forward_windows": list(config.forward_windows),
            "study_windows": list(MARKET_REGIME_STUDY_WINDOWS),
            "free_float_market_cap_available": False,
            "parameters": _config_parameters(config),
        },
        "risk_appetite": risk_appetite,
        "state_report": state_report,
        "daily_report": daily_report,
        "daily_report_history": daily_report_history,
        "benchmark_regime": benchmark_regime,
        "risk_appetite_series": risk_appetite_series,
        "risk_appetite_components": risk_appetite_components,
        "flow_candidates": flow_candidates,
        "answer_cards": answer_cards,
        "factor_backtest": factor_backtest,
        "factor_advantage": factor_advantage,
        "adjustment_factor_backtest": adjustment_factor_backtest,
        "adjustment_factor_advantage": adjustment_factor_advantage,
        "migration_layers": migration_layers,
        "risk_release_sequence": risk_release_sequence,
        "risk_release_timeline": risk_release_timeline,
        "high_liquidity_break_study": high_liquidity_break_study,
        "market_scope": market_scope,
        "asset_rows": _asset_rows(latest),
    }


def _config_parameters(config: MarketRegimeConfig) -> dict[str, object]:
    return {
        "benchmark_rally_60_threshold": config.benchmark_rally_60_threshold,
        "benchmark_pullback_20_threshold": config.benchmark_pullback_20_threshold,
        "pullback_20_threshold": config.pullback_20_threshold,
        "pullback_60_threshold": config.pullback_60_threshold,
        "liquidity_high_percentile": config.liquidity_high_percentile,
        "liquidity_mid_percentile": config.liquidity_mid_percentile,
        "liquidity_low_percentile": config.liquidity_low_percentile,
        "volatility_high_percentile": config.volatility_high_percentile,
        "volatility_low_percentile": config.volatility_low_percentile,
        "high_position_drawdown_threshold": config.high_position_drawdown_threshold,
        "high_position_return_percentile": config.high_position_return_percentile,
        "leader_return_5d_threshold": config.leader_return_5d_threshold,
        "stress_ma20_break_threshold": config.stress_ma20_break_threshold,
        "stress_return_5d_threshold": config.stress_return_5d_threshold,
        "cash_stress_score_threshold": config.cash_stress_score_threshold,
        "cash_preference_proxy_threshold": config.cash_preference_proxy_threshold,
        "risk_expansion_breadth_threshold": config.risk_expansion_breadth_threshold,
        "risk_contraction_breadth_threshold": config.risk_contraction_breadth_threshold,
        "risk_release_breadth_threshold": config.risk_release_breadth_threshold,
        "high_liquidity_selloff_threshold": config.high_liquidity_selloff_threshold,
        "concentration_top_n": config.concentration_top_n,
        "daily_report_days": config.daily_report_days,
        "flow_candidate_limit": config.flow_candidate_limit,
        "risk_timeline_days": config.risk_timeline_days,
    }


def _feature_frame(bars: pd.DataFrame, *, config: MarketRegimeConfig, benchmark_symbol: str) -> pd.DataFrame:
    frame = bars.sort_values(["stock_code", "date"]).reset_index(drop=True).copy()
    grouped = frame.groupby("stock_code", group_keys=False, sort=False)
    close = grouped["close"]
    amount = grouped["amount"]
    high = grouped["high"]
    frame["ret_3"] = close.pct_change(3, fill_method=None)
    frame["ret_5"] = close.pct_change(5, fill_method=None)
    frame["ret_10"] = close.pct_change(10, fill_method=None)
    frame["ret_20"] = close.pct_change(20, fill_method=None)
    frame["ret_60"] = close.pct_change(60, fill_method=None)
    frame["ret_120"] = close.pct_change(120, fill_method=None)
    frame["ma20"] = close.transform(lambda series: series.rolling(20, min_periods=5).mean())
    frame["ma60"] = close.transform(lambda series: series.rolling(60, min_periods=10).mean())
    frame["ma20_slope"] = grouped["ma20"].pct_change(5, fill_method=None)
    frame["drawdown_20"] = frame["close"] / high.transform(lambda series: series.rolling(20, min_periods=5).max()) - 1.0
    frame["drawdown_60"] = frame["close"] / high.transform(lambda series: series.rolling(60, min_periods=10).max()) - 1.0
    frame["drawdown_250"] = frame["close"] / high.transform(lambda series: series.rolling(250, min_periods=20).max()) - 1.0
    frame["amount20"] = amount.transform(lambda series: series.rolling(20, min_periods=5).mean())
    frame["amount60"] = amount.transform(lambda series: series.rolling(60, min_periods=10).mean())
    frame["amount_contraction"] = frame["amount20"] / frame["amount60"] - 1.0
    daily_return = close.pct_change(fill_method=None)
    frame["ret_1"] = daily_return
    frame["hv20"] = daily_return.groupby(frame["stock_code"]).transform(lambda series: series.rolling(20, min_periods=5).std()) * math.sqrt(
        TRADING_DAYS_PER_YEAR
    )
    frame["hv60"] = daily_return.groupby(frame["stock_code"]).transform(lambda series: series.rolling(60, min_periods=10).std()) * math.sqrt(
        TRADING_DAYS_PER_YEAR
    )
    true_range = (frame["high"] - frame["low"]).abs()
    frame["atr20_close"] = (
        true_range.groupby(frame["stock_code"]).transform(lambda series: series.rolling(20, min_periods=5).mean()) / frame["close"]
    )
    forward_windows = tuple(sorted({*config.forward_windows, *MARKET_REGIME_STUDY_WINDOWS}))
    for window in forward_windows:
        frame[f"fwd_{window}"] = grouped["close"].shift(-int(window)) / frame["close"] - 1.0
    frame["above_ma20"] = frame["close"] > frame["ma20"]
    frame["above_ma60"] = frame["close"] > frame["ma60"]
    benchmark = frame.loc[
        frame["stock_code"] == benchmark_symbol,
        ["date", "ret_20", "ret_60", "drawdown_20", "above_ma20", "above_ma60"],
    ].rename(
        columns={
            "ret_20": "benchmark_ret_20",
            "ret_60": "benchmark_ret_60",
            "drawdown_20": "benchmark_drawdown_20",
            "above_ma20": "benchmark_above_ma20",
            "above_ma60": "benchmark_above_ma60",
        }
    )
    frame = frame.merge(benchmark, on="date", how="left")
    frame["rs20"] = frame["ret_20"] - frame["benchmark_ret_20"]
    frame["turn_strong"] = frame["above_ma20"] & (frame["ma20_slope"] > 0) & (frame["ret_5"] > 0) & (frame["rs20"] > 0)
    frame["pullback_sufficient"] = (frame["drawdown_20"] <= config.pullback_20_threshold) | (
        frame["drawdown_60"] <= config.pullback_60_threshold
    )
    frame["near_high"] = frame["drawdown_250"] >= config.high_position_drawdown_threshold
    frame["strong_continuation"] = frame["near_high"] & frame["above_ma20"] & (frame["ret_20"] > 0)
    return frame


def _latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    positions = frame.sort_values("date").groupby("stock_code", sort=False).tail(1).index
    return frame.loc[positions].sort_values("stock_code").reset_index(drop=True)


def _classify_frame(frame: pd.DataFrame, config: MarketRegimeConfig) -> pd.DataFrame:
    result = frame.copy()
    result["group"] = np.select(
        [
            result["pullback_sufficient"] & result["turn_strong"],
            result["pullback_sufficient"] & ~result["turn_strong"],
            result["strong_continuation"],
        ],
        ["A 回调充分+转强", "B 回调充分+未转强", "C 强势延续"],
        default="D 全市场基准",
    )
    result["volatility_percentile"] = _date_rank_percentile(result, "hv20")
    result["amount_percentile"] = _date_rank_percentile(result, "amount20")
    result["rs_rank"] = _date_rank_percentile(result, "rs20")
    result["ret120_rank"] = _date_rank_percentile(result, "ret_120")
    result["amount_rank"] = result.groupby("date")["amount20"].rank(ascending=False, method="min")
    result["volatility_bucket"] = _bucket_from_percentile(
        result["volatility_percentile"],
        high_threshold=config.volatility_high_percentile,
        low_threshold=config.volatility_low_percentile,
        high_label="高波动",
        mid_label="中波动",
        low_label="低波动",
    )
    result["liquidity_bucket"] = _bucket_from_percentile(
        result["amount_percentile"],
        high_threshold=config.liquidity_high_percentile,
        low_threshold=config.liquidity_low_percentile,
        high_label="高流动性",
        mid_label="中流动性",
        low_label="低流动性",
    )
    result["high_liquidity_signal"] = result["amount_percentile"] >= config.liquidity_high_percentile
    result["high_position_signal"] = result["near_high"].fillna(False) | (result["ret120_rank"] >= config.high_position_return_percentile)
    result["position_bucket"] = np.where(result["high_position_signal"], "高位资产", "非高位资产")
    result["asset_pool"] = np.select(
        [
            result["high_liquidity_signal"],
            result["amount_percentile"].between(config.liquidity_mid_percentile, config.liquidity_high_percentile, inclusive="left"),
        ],
        ["大盘/高流动性", "中盘核心"],
        default="长尾/低流动性",
    )
    return result


def _date_rank_percentile(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby("date")[column].rank(pct=True)


def _bucket_from_percentile(
    values: pd.Series,
    *,
    high_threshold: float,
    low_threshold: float,
    high_label: str,
    mid_label: str,
    low_label: str,
) -> pd.Series:
    return pd.Series(np.select([values >= high_threshold, values <= low_threshold], [high_label, low_label], default=mid_label), index=values.index)


def _factor_backtest(
    frame: pd.DataFrame,
    *,
    benchmark_forward: pd.DataFrame,
    config: MarketRegimeConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    adjustment_only: bool = False,
) -> list[dict[str, object]]:
    sample = frame.loc[frame["date"].between(start, end)].copy()
    if adjustment_only and not sample.empty:
        sample = sample.loc[_benchmark_adjustment_mask(sample, config)].copy()
    if sample.empty:
        return []
    sample["group"] = np.select(
        [
            sample["pullback_sufficient"] & sample["turn_strong"],
            sample["pullback_sufficient"] & ~sample["turn_strong"],
            sample["strong_continuation"],
        ],
        ["A 回调充分+转强", "B 回调充分+未转强", "C 强势延续"],
        default="D 全市场基准",
    )
    rows: list[dict[str, object]] = []
    for group in ["A 回调充分+转强", "B 回调充分+未转强", "C 强势延续", "D 全市场基准"]:
        group_frame = sample.loc[sample["group"] == group]
        for window in config.forward_windows:
            column = f"fwd_{int(window)}"
            values = pd.to_numeric(group_frame[column], errors="coerce").dropna()
            if values.empty:
                continue
            benchmark_values = _aligned_forward_values(benchmark_forward, group_frame.loc[values.index, "date"], int(window))
            rows.append(
                {
                    "group": group,
                    "window": f"{int(window)}日",
                    "sample_scope": "基准上涨后调整" if adjustment_only else "全样本",
                    "sample_count": int(values.count()),
                    "mean_return": float(values.mean()),
                    "win_rate": float((values > 0).mean()),
                    "excess_return": float(values.mean() - benchmark_values.mean()) if not benchmark_values.empty else float("nan"),
                }
            )
    return rows


def _factor_advantage(factor_backtest: list[dict[str, object]]) -> dict[str, object]:
    if not factor_backtest:
        return {"summary": {}, "by_window": [], "verdict": "样本不足"}
    by_group_window = {(str(row.get("group")), str(row.get("window"))): row for row in factor_backtest}
    windows = sorted({str(row.get("window")) for row in factor_backtest}, key=_window_sort_key)
    rows: list[dict[str, object]] = []
    positive_windows = 0
    for window in windows:
        a_row = by_group_window.get(("A 回调充分+转强", window), {})
        d_row = by_group_window.get(("D 全市场基准", window), {})
        a_return = _numeric_or_nan(a_row.get("mean_return"))
        d_return = _numeric_or_nan(d_row.get("mean_return"))
        a_win_rate = _numeric_or_nan(a_row.get("win_rate"))
        excess_vs_market = a_return - d_return if math.isfinite(a_return) and math.isfinite(d_return) else float("nan")
        if math.isfinite(excess_vs_market) and excess_vs_market > 0:
            positive_windows += 1
        rows.append(
            {
                "window": window,
                "a_sample_count": int(a_row.get("sample_count", 0) or 0),
                "market_sample_count": int(d_row.get("sample_count", 0) or 0),
                "a_mean_return": a_return,
                "market_mean_return": d_return,
                "excess_vs_market": excess_vs_market,
                "a_win_rate": a_win_rate,
                "benchmark_excess_return": a_row.get("excess_return"),
                "advantage": math.isfinite(excess_vs_market) and excess_vs_market > 0,
            }
        )
    valid_rows = [row for row in rows if math.isfinite(_numeric_or_nan(row.get("excess_vs_market")))]
    advantage_ratio = float(positive_windows / len(valid_rows)) if valid_rows else 0.0
    best_row = max(valid_rows, key=lambda row: _numeric_or_nan(row.get("excess_vs_market"))) if valid_rows else {}
    if advantage_ratio >= 0.67:
        verdict = "统计优势明显"
    elif advantage_ratio > 0:
        verdict = "统计优势不稳定"
    else:
        verdict = "暂未验证优势"
    return {
        "summary": {
            "verdict": verdict,
            "advantage_ratio": advantage_ratio,
            "positive_window_count": positive_windows,
            "valid_window_count": len(valid_rows),
            "best_window": best_row.get("window"),
            "best_excess_vs_market": best_row.get("excess_vs_market"),
        },
        "by_window": rows,
        "verdict": verdict,
    }


def _benchmark_adjustment_mask(frame: pd.DataFrame, config: MarketRegimeConfig) -> pd.Series:
    if "benchmark_ret_60" not in frame.columns or "benchmark_drawdown_20" not in frame.columns:
        return pd.Series(False, index=frame.index)
    rally = pd.to_numeric(frame["benchmark_ret_60"], errors="coerce") >= config.benchmark_rally_60_threshold
    pullback = pd.to_numeric(frame["benchmark_drawdown_20"], errors="coerce") <= config.benchmark_pullback_20_threshold
    return (rally & pullback).fillna(False)


def _benchmark_regime(
    frame: pd.DataFrame,
    *,
    benchmark_symbol: str,
    config: MarketRegimeConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, object]:
    sample = frame.loc[(frame["stock_code"] == benchmark_symbol) & frame["date"].between(start, end)].copy()
    if sample.empty:
        return {
            "benchmark_symbol": benchmark_symbol,
            "stage": "样本不足",
            "is_adjustment_stage": False,
            "sample_count": 0,
            "adjustment_sample_count": 0,
            "adjustment_ratio": 0.0,
            "rally_60_threshold": config.benchmark_rally_60_threshold,
            "pullback_20_threshold": config.benchmark_pullback_20_threshold,
        }
    mask = _benchmark_adjustment_mask(sample, config)
    latest = sample.sort_values("date").iloc[-1]
    latest_ret_60 = _numeric_or_nan(latest.get("ret_60"))
    latest_drawdown_20 = _numeric_or_nan(latest.get("drawdown_20"))
    latest_is_adjustment = bool(mask.loc[latest.name]) if latest.name in mask.index else False
    return {
        "benchmark_symbol": benchmark_symbol,
        "as_of": latest.get("date"),
        "stage": _benchmark_stage(latest_ret_60, latest_drawdown_20, config),
        "is_adjustment_stage": latest_is_adjustment,
        "ret_60": latest_ret_60,
        "drawdown_20": latest_drawdown_20,
        "above_ma20": _bool_value(latest.get("above_ma20")),
        "above_ma60": _bool_value(latest.get("above_ma60")),
        "sample_count": int(sample["date"].nunique()),
        "adjustment_sample_count": int(sample.loc[mask, "date"].nunique()),
        "adjustment_ratio": float(mask.mean()) if len(mask) else 0.0,
        "rally_60_threshold": config.benchmark_rally_60_threshold,
        "pullback_20_threshold": config.benchmark_pullback_20_threshold,
    }


def _benchmark_stage(ret_60: float, drawdown_20: float, config: MarketRegimeConfig) -> str:
    rallied = math.isfinite(ret_60) and ret_60 >= config.benchmark_rally_60_threshold
    pulled_back = math.isfinite(drawdown_20) and drawdown_20 <= config.benchmark_pullback_20_threshold
    if rallied and pulled_back:
        return "上涨后调整"
    if rallied:
        return "上涨延续"
    if pulled_back:
        return "弱势调整"
    return "非明显上涨"


def _answer_cards(
    *,
    daily_report: dict[str, object],
    risk_appetite: dict[str, object],
    factor_advantage: dict[str, object],
    risk_release_sequence: dict[str, object],
    flow_candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    answers = daily_report.get("answers", {}) if isinstance(daily_report, dict) else {}
    flow = daily_report.get("flow", {}) if isinstance(daily_report, dict) else {}
    factor_summary = factor_advantage.get("summary", {}) if isinstance(factor_advantage, dict) else {}
    top_candidate = flow_candidates[0] if flow_candidates else {}
    high_liquidity_selloff = bool(answers.get("high_liquidity_selloff"))
    sequence_score = _numeric_or_nan(risk_release_sequence.get("sequence_score") if isinstance(risk_release_sequence, dict) else None)
    return [
        {
            "question": "当前风险偏好阶段",
            "answer": answers.get("risk_phase") or risk_appetite.get("phase") or "-",
            "signal": risk_appetite.get("score"),
            "detail": f"RAI {risk_appetite.get('score', '-')}",
            "tone": _phase_tone(answers.get("risk_phase") or risk_appetite.get("phase")),
        },
        {
            "question": "资金正在流出哪里",
            "answer": answers.get("funds_leaving") or "-",
            "signal": flow.get("current_release_stage"),
            "detail": f"当前释放阶段 {flow.get('current_release_stage', '-')}",
            "tone": "risk",
        },
        {
            "question": "资金正在流向哪里",
            "answer": answers.get("funds_entering") or "-",
            "signal": top_candidate.get("stock_code") or "",
            "detail": f"候选 {top_candidate.get('stock_code', '-')} · {top_candidate.get('reason', '-')}",
            "tone": "opportunity" if top_candidate else "neutral",
        },
        {
            "question": "高流动性是否被抛售",
            "answer": "已触发" if high_liquidity_selloff else "未触发",
            "signal": risk_appetite.get("high_liquidity_break_ratio"),
            "detail": f"破位比例 {_format_ratio_text(risk_appetite.get('high_liquidity_break_ratio'))}",
            "tone": "risk" if high_liquidity_selloff else "neutral",
        },
        {
            "question": "更接近主升还是释放",
            "answer": answers.get("closer_to") or "-",
            "signal": risk_appetite.get("breadth_ma20"),
            "detail": f"MA20宽度 {_format_ratio_text(risk_appetite.get('breadth_ma20'))}",
            "tone": _phase_tone(answers.get("closer_to")),
        },
        {
            "question": "回调转强是否有优势",
            "answer": factor_summary.get("verdict") or factor_advantage.get("verdict") or "-",
            "signal": factor_summary.get("advantage_ratio"),
            "detail": f"最佳窗口 {factor_summary.get('best_window', '-')} · 超额 {_format_ratio_text(factor_summary.get('best_excess_vs_market'))}",
            "tone": "opportunity" if _numeric_or_nan(factor_summary.get("advantage_ratio")) >= 0.67 else "neutral",
        },
        {
            "question": "释放顺序是否稳定",
            "answer": "顺序较稳定" if sequence_score >= 0.67 else "顺序待确认" if sequence_score > 0 else "样本不足",
            "signal": sequence_score,
            "detail": f"顺序得分 {_format_ratio_text(sequence_score)}",
            "tone": "risk" if sequence_score >= 0.67 else "neutral",
        },
    ]


def _benchmark_forward_returns(benchmark_daily: pd.DataFrame, windows: tuple[int, ...]) -> pd.DataFrame:
    if benchmark_daily.empty or "close" not in benchmark_daily.columns:
        return pd.DataFrame()
    benchmark = benchmark_daily.sort_index().copy()
    for window in windows:
        benchmark[f"fwd_{int(window)}"] = benchmark["close"].shift(-int(window)) / benchmark["close"] - 1.0
    return benchmark[[f"fwd_{int(window)}" for window in windows]]


def _aligned_forward_values(forward_frame: pd.DataFrame, dates: pd.Series, window: int) -> pd.Series:
    column = f"fwd_{int(window)}"
    if forward_frame.empty or column not in forward_frame.columns:
        return pd.Series(dtype=float)
    values = forward_frame.reindex(pd.to_datetime(dates))[column]
    return pd.to_numeric(values, errors="coerce").dropna()


def _aligned_benchmark_forward(benchmark_daily: pd.DataFrame, dates: pd.Series, window: int) -> pd.Series:
    benchmark = _benchmark_forward_returns(benchmark_daily, (int(window),))
    return _aligned_forward_values(benchmark, dates, int(window))


def _migration_layers(latest: pd.DataFrame) -> list[dict[str, object]]:
    layers = [
        ("高波资产", latest["volatility_bucket"] == "高波动"),
        ("高位资产", latest["high_position_signal"].fillna(False)),
        ("高流动性资产", latest["high_liquidity_signal"].fillna(False)),
        ("全市场", pd.Series(True, index=latest.index)),
    ]
    total_amount = pd.to_numeric(latest["amount20"], errors="coerce").fillna(0).sum()
    rows: list[dict[str, object]] = []
    for label, mask in layers:
        layer = latest.loc[mask].copy()
        if layer.empty:
            rows.append({"layer": label, "asset_count": 0, "return_5d": None, "ma20_break_ratio": None, "amount_share": 0.0})
            continue
        amount = pd.to_numeric(layer["amount20"], errors="coerce").fillna(0).sum()
        rows.append(
            {
                "layer": label,
                "asset_count": int(layer["stock_code"].nunique()),
                "return_5d": _safe_mean(layer["ret_5"]),
                "ma20_break_ratio": float((~layer["above_ma20"].fillna(False)).mean()),
                "amount_share": float(amount / total_amount) if total_amount else 0.0,
            }
        )
    return rows


def _risk_release_sequence(history: pd.DataFrame, latest_history: pd.DataFrame) -> dict[str, object]:
    first_dates: dict[str, pd.Timestamp | None] = {}
    rows: list[dict[str, object]] = []
    anchor_date: pd.Timestamp | None = None
    for layer in RISK_RELEASE_LAYER_ORDER:
        layer_history = history.loc[history["layer"] == layer].sort_values("date")
        stress_rows = layer_history.loc[layer_history["stress_signal"]]
        first_date = pd.Timestamp(stress_rows["date"].iloc[0]) if not stress_rows.empty else None
        first_dates[layer] = first_date
        if anchor_date is None and first_date is not None:
            anchor_date = first_date
        latest_row = latest_history.loc[latest_history["layer"] == layer]
        latest_record = latest_row.iloc[-1].to_dict() if not latest_row.empty else {}
        rows.append(
            {
                "layer": layer,
                "first_stress_date": first_date,
                "lead_lag_days": int((first_date - anchor_date).days) if first_date is not None and anchor_date is not None else None,
                "current_stress": bool(latest_record.get("stress_signal", False)),
                "asset_count": int(latest_record.get("asset_count", 0) or 0),
                "return_5d": latest_record.get("return_5d"),
                "ma20_break_ratio": latest_record.get("ma20_break_ratio"),
                "stress_score": latest_record.get("stress_score"),
            }
        )
    dated_layers = [first_dates[layer] for layer in RISK_RELEASE_LAYER_ORDER if first_dates.get(layer) is not None]
    sequence_score = _sequence_score(dated_layers)
    current_stage = next((row["layer"] for row in reversed(rows) if row["current_stress"]), "未触发")
    return {
        "layers": rows,
        "sequence_score": sequence_score,
        "current_stage": current_stage,
        "expected_order": list(RISK_RELEASE_LAYER_ORDER),
    }


def _risk_release_timeline(history: pd.DataFrame, config: MarketRegimeConfig) -> list[dict[str, object]]:
    if history.empty:
        return []
    dates = list(pd.Series(history["date"].dropna().unique()).sort_values().tail(config.risk_timeline_days))
    if not dates:
        return []
    order_by_layer = {layer: index + 1 for index, layer in enumerate(RISK_RELEASE_LAYER_ORDER)}
    sample = history.loc[history["date"].isin(dates)].copy()
    sample["layer_order"] = sample["layer"].map(order_by_layer).fillna(99)
    rows: list[dict[str, object]] = []
    for _, row in sample.sort_values(["date", "layer_order"]).iterrows():
        stress_score = _finite(row.get("stress_score"))
        rows.append(
            {
                "date": row.get("date"),
                "layer": row.get("layer"),
                "layer_order": int(row.get("layer_order") or 99),
                "asset_count": int(row.get("asset_count", 0) or 0),
                "return_5d": row.get("return_5d"),
                "ma20_break_ratio": row.get("ma20_break_ratio"),
                "amount_share": row.get("amount_share"),
                "stress_score": stress_score,
                "stress_signal": bool(row.get("stress_signal", False)),
                "stress_level": "触发" if bool(row.get("stress_signal", False)) else "观察" if stress_score >= 0.35 else "平稳",
            }
        )
    return rows


def _risk_appetite_series(
    sample_frame: pd.DataFrame,
    market_scope: dict[str, object],
    config: MarketRegimeConfig,
) -> list[dict[str, object]]:
    if sample_frame.empty:
        return []
    scope_by_date = {
        pd.Timestamp(row.get("date")).normalize(): row
        for row in market_scope.get("series", [])
        if isinstance(row, dict) and pd.notna(row.get("date"))
    }
    daily_by_date = _daily_frames_by_date(sample_frame)
    dates = sorted(daily_by_date)[-config.risk_timeline_days :]
    rows: list[dict[str, object]] = []
    for date_ts in dates:
        daily = daily_by_date[date_ts]
        risk_appetite = _risk_appetite(daily, _migration_layers(daily), {"latest": scope_by_date.get(date_ts, {})}, config)
        rows.append(
            {
                "date": date_ts,
                "score": risk_appetite["score"],
                "phase": risk_appetite["phase"],
                "breadth_ma20": risk_appetite["breadth_ma20"],
                "high_liquidity_break_ratio": risk_appetite["high_liquidity_break_ratio"],
                "short_momentum": risk_appetite["short_momentum"],
                "cash_preference_proxy": risk_appetite["cash_preference_proxy"],
                "amount_concentration": risk_appetite["amount_concentration"],
            }
        )
    return rows


def _daily_report_history(
    *,
    sample_frame: pd.DataFrame,
    risk_layer_history: pd.DataFrame,
    factor_backtest: list[dict[str, object]],
    market_scope: dict[str, object],
    config: MarketRegimeConfig,
) -> list[dict[str, object]]:
    if sample_frame.empty:
        return []
    scope_by_date = {
        pd.Timestamp(row.get("date")).normalize(): row
        for row in market_scope.get("series", [])
        if isinstance(row, dict) and pd.notna(row.get("date"))
    }
    daily_by_date = _daily_frames_by_date(sample_frame)
    release_state_by_date = _risk_release_states_by_date(risk_layer_history)
    dates = sorted(daily_by_date)[-config.daily_report_days :]
    rows: list[dict[str, object]] = []
    for date_ts in dates:
        daily = daily_by_date[date_ts]
        migration_layers = _migration_layers(daily)
        daily_scope = {"latest": scope_by_date.get(date_ts, {})}
        risk_appetite = _risk_appetite(daily, migration_layers, daily_scope, config)
        state_report = _state_report(daily, risk_appetite, config)
        release_state = release_state_by_date.get(date_ts, _empty_risk_release_state())
        report = _daily_report(
            latest=daily,
            config=config,
            risk_appetite=risk_appetite,
            state_report=state_report,
            migration_layers=migration_layers,
            factor_backtest=factor_backtest,
            risk_release_sequence=release_state,
            market_scope=daily_scope,
        )
        rows.append(
            {
                "as_of": report["as_of"],
                "phase": report["phase"],
                "score": report["score"],
                "trend_status": report["trend_status"],
                "volatility_status": report["volatility_status"],
                "liquidity_status": report["liquidity_status"],
                "funds_leaving": report["answers"]["funds_leaving"],
                "funds_entering": report["answers"]["funds_entering"],
                "high_liquidity_selloff": report["answers"]["high_liquidity_selloff"],
                "closer_to": report["answers"]["closer_to"],
                "current_release_stage": report["flow"]["current_release_stage"],
                "breadth_ma20": risk_appetite["breadth_ma20"],
                "high_liquidity_break_ratio": risk_appetite["high_liquidity_break_ratio"],
                "cash_preference_proxy": risk_appetite["cash_preference_proxy"],
                "amount_concentration": risk_appetite["amount_concentration"],
            }
        )
    return rows


def _daily_frames_by_date(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    return {pd.Timestamp(date_value).normalize(): daily for date_value, daily in frame.groupby("date", sort=True)}


def _empty_risk_release_state() -> dict[str, object]:
    return {"layers": [], "current_stage": "未触发"}


def _risk_release_states_by_date(risk_layer_history: pd.DataFrame) -> dict[pd.Timestamp, dict[str, object]]:
    if risk_layer_history.empty:
        return {}
    return {
        pd.Timestamp(date_value).normalize(): _risk_release_state_from_daily_history(daily_history)
        for date_value, daily_history in risk_layer_history.groupby("date", sort=False)
    }


def _risk_release_state_for_date(risk_layer_history: pd.DataFrame, date_ts: pd.Timestamp) -> dict[str, object]:
    if risk_layer_history.empty:
        return _empty_risk_release_state()
    daily_history = risk_layer_history.loc[pd.to_datetime(risk_layer_history["date"]).dt.normalize() == date_ts]
    return _risk_release_state_from_daily_history(daily_history)


def _risk_release_state_from_daily_history(daily_history: pd.DataFrame) -> dict[str, object]:
    layers: list[dict[str, object]] = []
    for layer in RISK_RELEASE_LAYER_ORDER:
        rows = daily_history.loc[daily_history["layer"] == layer]
        row = rows.iloc[-1].to_dict() if not rows.empty else {}
        layers.append(
            {
                "layer": layer,
                "current_stress": bool(row.get("stress_signal", False)),
                "asset_count": int(row.get("asset_count", 0) or 0),
                "return_5d": row.get("return_5d"),
                "ma20_break_ratio": row.get("ma20_break_ratio"),
                "stress_score": row.get("stress_score"),
            }
        )
    current_stage = next((row["layer"] for row in reversed(layers) if row["current_stress"]), "未触发")
    return {"layers": layers, "current_stage": current_stage}


def _risk_release_layer_history(frame: pd.DataFrame, config: MarketRegimeConfig) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "layer", "asset_count", "return_5d", "ma20_break_ratio", "amount_share", "stress_signal", "stress_score"])
    rows: list[dict[str, object]] = []
    for date_value, daily in frame.groupby("date", sort=True):
        total_amount = pd.to_numeric(daily["amount20"], errors="coerce").fillna(0).sum()
        layer_masks = {
            "高波资产": daily["volatility_bucket"] == "高波动",
            "高位资产": daily["high_position_signal"].fillna(False),
            "高流动性资产": daily["high_liquidity_signal"].fillna(False),
            "现金偏好代理": pd.Series(True, index=daily.index),
        }
        for layer, mask in layer_masks.items():
            layer_frame = daily.loc[mask].copy()
            if layer_frame.empty:
                rows.append(
                    {
                        "date": date_value,
                        "layer": layer,
                        "asset_count": 0,
                        "return_5d": None,
                        "ma20_break_ratio": None,
                        "amount_share": 0.0,
                        "stress_signal": False,
                        "stress_score": 0.0,
                    }
                )
                continue
            return_5d = _safe_mean(layer_frame["ret_5"])
            ma20_break_ratio = float((~layer_frame["above_ma20"].fillna(False)).mean())
            amount = pd.to_numeric(layer_frame["amount20"], errors="coerce").fillna(0).sum()
            amount_share = float(amount / total_amount) if total_amount else 0.0
            if layer == "现金偏好代理":
                breadth = float(layer_frame["above_ma20"].fillna(False).mean())
                high_liq = daily.loc[daily["high_liquidity_signal"].fillna(False)]
                high_liq_break = float((~high_liq["above_ma20"].fillna(False)).mean()) if not high_liq.empty else 0.0
                stress_score = float(np.clip((1 - breadth) * 0.55 + high_liq_break * 0.35 + max(0.0, -return_5d) * 3.0, 0, 1))
                stress_signal = stress_score >= config.cash_stress_score_threshold
            else:
                stress_score = float(np.clip(ma20_break_ratio * 0.7 + max(0.0, -return_5d) * 4.0, 0, 1))
                stress_signal = bool(ma20_break_ratio >= config.stress_ma20_break_threshold and return_5d < config.stress_return_5d_threshold)
            rows.append(
                {
                    "date": date_value,
                    "layer": layer,
                    "asset_count": int(layer_frame["stock_code"].nunique()),
                    "return_5d": return_5d,
                    "ma20_break_ratio": ma20_break_ratio,
                    "amount_share": amount_share,
                    "stress_signal": stress_signal,
                    "stress_score": stress_score,
                }
            )
    return pd.DataFrame(rows)


def _sequence_score(dates: list[pd.Timestamp]) -> float:
    if len(dates) < 2:
        return 0.0
    ordered_pairs = sum(1 for left, right in zip(dates, dates[1:]) if left <= right)
    return float(ordered_pairs / (len(dates) - 1))


def _high_liquidity_break_study(sample: pd.DataFrame, *, benchmark_forward: pd.DataFrame) -> list[dict[str, object]]:
    if sample.empty:
        return [
            {"window": f"{window}日", "event_count": 0, "market_mean_return": None, "benchmark_mean_return": None, "benchmark_win_rate": None}
            for window in MARKET_REGIME_STUDY_WINDOWS
        ]
    events = sample.loc[sample["high_liquidity_signal"].fillna(False) & ~sample["above_ma20"].fillna(False)].copy()
    rows: list[dict[str, object]] = []
    for window in MARKET_REGIME_STUDY_WINDOWS:
        column = f"fwd_{window}"
        event_values = pd.to_numeric(events[column], errors="coerce").dropna() if column in events.columns else pd.Series(dtype=float)
        event_dates = events.loc[event_values.index, "date"] if not event_values.empty else pd.Series(dtype="datetime64[ns]")
        market_values = _market_forward_values(sample, event_dates, window)
        benchmark_values = _aligned_forward_values(benchmark_forward, event_dates, window)
        rows.append(
            {
                "window": f"{window}日",
                "event_count": int(event_values.count()),
                "event_asset_mean_return": float(event_values.mean()) if not event_values.empty else None,
                "market_mean_return": float(market_values.mean()) if not market_values.empty else None,
                "benchmark_mean_return": float(benchmark_values.mean()) if not benchmark_values.empty else None,
                "benchmark_win_rate": float((benchmark_values > 0).mean()) if not benchmark_values.empty else None,
                "breadth_ma20_at_event": _safe_mean(events.loc[event_values.index, "above_ma20"].astype(float)) if not event_values.empty else None,
            }
        )
    return rows


def _market_forward_values(sample: pd.DataFrame, dates: pd.Series, window: int) -> pd.Series:
    if sample.empty or dates.empty:
        return pd.Series(dtype=float)
    column = f"fwd_{window}"
    if column not in sample.columns:
        return pd.Series(dtype=float)
    market_by_date = sample.groupby("date")[column].mean()
    values = market_by_date.reindex(pd.to_datetime(dates))
    return pd.to_numeric(values, errors="coerce").dropna()


def _market_scope(sample: pd.DataFrame, config: MarketRegimeConfig) -> dict[str, object]:
    if sample.empty:
        return {"latest": {}, "series": []}
    rows: list[dict[str, object]] = []
    for date_value, daily in sample.groupby("date", sort=True):
        amount = pd.to_numeric(daily["amount20"], errors="coerce").fillna(0).sort_values(ascending=False)
        total_amount = amount.sum()
        rising = daily["ret_5"] > 0
        leaders = daily["ret_5"] > config.leader_return_5d_threshold
        rows.append(
            {
                "date": date_value,
                "asset_count": int(daily["stock_code"].nunique()),
                "rising_count": int(rising.fillna(False).sum()),
                "rising_ratio": float(rising.fillna(False).mean()),
                "leader_count": int(leaders.fillna(False).sum()),
                "leader_ratio": float(leaders.fillna(False).mean()),
                "breadth_ma20": float(daily["above_ma20"].fillna(False).mean()),
                "top20_amount_share": float(amount.head(config.concentration_top_n).sum() / total_amount) if total_amount else 0.0,
                "median_return_5d": _safe_median(daily["ret_5"]),
            }
        )
    series = rows[-max(60, config.daily_report_days, config.risk_timeline_days) :]
    latest = series[-1] if series else {}
    return {"latest": latest, "series": series}


def _risk_appetite(
    latest: pd.DataFrame,
    migration_layers: list[dict[str, object]],
    market_scope: dict[str, object],
    config: MarketRegimeConfig,
) -> dict[str, object]:
    breadth = float(latest["above_ma20"].fillna(False).mean())
    momentum = _safe_mean(latest["ret_5"])
    high_liquidity = next((row for row in migration_layers if row["layer"] == "高流动性资产"), {})
    high_liq_break = float(high_liquidity.get("ma20_break_ratio") or 0)
    scope_latest = market_scope.get("latest", {}) if isinstance(market_scope, dict) else {}
    concentration = float(scope_latest.get("top20_amount_share") or 0)
    cash_preference_proxy = float(np.clip(high_liq_break * 0.45 + (1 - breadth) * 0.4 + max(0.0, -momentum) * 3.0, 0, 1))
    score = 50 + (breadth - 0.5) * 55 + np.clip(momentum, -0.05, 0.05) * 260 - high_liq_break * 18 - cash_preference_proxy * 10
    score = float(np.clip(score, 0, 100))
    if high_liq_break >= config.high_liquidity_selloff_threshold and breadth <= config.risk_release_breadth_threshold:
        phase = "风险释放后段"
    elif breadth >= config.risk_expansion_breadth_threshold and momentum > 0:
        phase = "风险偏好扩张"
    elif breadth <= config.risk_contraction_breadth_threshold:
        phase = "风险偏好收缩"
    else:
        phase = "震荡修复"
    return {
        "score": round(score, 2),
        "phase": phase,
        "breadth_ma20": breadth,
        "high_liquidity_break_ratio": high_liq_break,
        "short_momentum": momentum,
        "cash_preference_proxy": cash_preference_proxy,
        "amount_concentration": concentration,
    }


def _risk_appetite_components(
    latest: pd.DataFrame,
    migration_layers: list[dict[str, object]],
    market_scope: dict[str, object],
    config: MarketRegimeConfig,
) -> list[dict[str, object]]:
    if latest.empty:
        return []
    total_amount = pd.to_numeric(latest["amount20"], errors="coerce").fillna(0).sum()
    breadth = float(latest["above_ma20"].fillna(False).mean())
    scope_latest = market_scope.get("latest", {}) if isinstance(market_scope, dict) else {}
    concentration = _finite(scope_latest.get("top20_amount_share"))
    high_liquidity = next((row for row in migration_layers if row.get("layer") == "高流动性资产"), {})
    high_liquidity_break = _finite(high_liquidity.get("ma20_break_ratio"))
    return_1d = _safe_mean(latest["ret_1"])
    momentum = _safe_mean(latest["ret_5"])
    cash_preference = float(np.clip(high_liquidity_break * 0.45 + (1 - breadth) * 0.4 + max(0.0, -momentum) * 3.0, 0, 1))
    high_position = latest.loc[latest["high_position_signal"].fillna(False)]
    mid_core = latest.loc[latest["asset_pool"] == "中盘核心"]
    high_liquidity_sample = latest.loc[latest["high_liquidity_signal"].fillna(False)]
    rows = [
        {
            "component": "市场宽度",
            "signal": "扩散" if breadth >= config.risk_expansion_breadth_threshold else "收缩" if breadth <= config.risk_contraction_breadth_threshold else "均衡",
            "asset_count": int(latest["stock_code"].nunique()),
            "score": float(np.clip(breadth * 100, 0, 100)),
            "contribution": float((breadth - 0.5) * 55),
            "return_1d": return_1d,
            "return_5d": momentum,
            "ma20_break_ratio": float(1 - breadth),
            "amount_share": 1.0,
            "threshold": config.risk_expansion_breadth_threshold,
        },
        _component_row(
            "中盘核心资产",
            mid_core,
            total_amount=total_amount,
            signal_positive="回流扩散",
            signal_negative="中段走弱",
            contribution_scale=220,
            break_penalty=10,
        ),
        _component_row(
            "高位资产",
            high_position,
            total_amount=total_amount,
            signal_positive="高位承接",
            signal_negative="高位松动",
            contribution_scale=160,
            break_penalty=16,
        ),
        _component_row(
            "高流动性资产",
            high_liquidity_sample,
            total_amount=total_amount,
            signal_positive="权重承接",
            signal_negative="权重补跌",
            contribution_scale=160,
            break_penalty=18,
        ),
        {
            "component": "现金偏好代理",
            "signal": "现金偏好抬升" if cash_preference >= config.cash_preference_proxy_threshold else "风险资产占优",
            "asset_count": int(latest["stock_code"].nunique()),
            "score": float(np.clip((1 - cash_preference) * 100, 0, 100)),
            "contribution": float(-cash_preference * 10),
            "return_1d": return_1d,
            "return_5d": momentum,
            "ma20_break_ratio": high_liquidity_break,
            "amount_share": concentration,
            "threshold": config.cash_preference_proxy_threshold,
        },
    ]
    return rows


def _component_row(
    component: str,
    sample: pd.DataFrame,
    *,
    total_amount: float,
    signal_positive: str,
    signal_negative: str,
    contribution_scale: float,
    break_penalty: float,
) -> dict[str, object]:
    if sample.empty:
        return {
            "component": component,
            "signal": "样本不足",
            "asset_count": 0,
            "score": None,
            "contribution": 0.0,
            "return_1d": None,
            "return_5d": None,
            "ma20_break_ratio": None,
            "amount_share": 0.0,
            "threshold": None,
        }
    return_1d = _safe_mean(sample["ret_1"])
    return_5d = _safe_mean(sample["ret_5"])
    ma20_break_ratio = float((~sample["above_ma20"].fillna(False)).mean())
    amount = pd.to_numeric(sample["amount20"], errors="coerce").fillna(0).sum()
    score = 50 + np.clip(return_5d, -0.05, 0.05) * 300 - ma20_break_ratio * 35
    contribution = np.clip(return_5d, -0.05, 0.05) * contribution_scale - ma20_break_ratio * break_penalty
    signal = signal_positive if contribution >= 0 else signal_negative
    return {
        "component": component,
        "signal": signal,
        "asset_count": int(sample["stock_code"].nunique()),
        "score": float(np.clip(score, 0, 100)),
        "contribution": float(contribution),
        "return_1d": return_1d,
        "return_5d": return_5d,
        "ma20_break_ratio": ma20_break_ratio,
        "amount_share": float(amount / total_amount) if total_amount else 0.0,
        "threshold": None,
    }


def _flow_candidates(latest: pd.DataFrame, config: MarketRegimeConfig) -> list[dict[str, object]]:
    if latest.empty:
        return []
    sample = latest.copy()
    ret_5 = pd.to_numeric(sample["ret_5"], errors="coerce").fillna(0.0)
    ret_20 = pd.to_numeric(sample["ret_20"], errors="coerce").fillna(0.0)
    drawdown_20 = pd.to_numeric(sample["drawdown_20"], errors="coerce").fillna(0.0)
    rs_rank = pd.to_numeric(sample["rs_rank"], errors="coerce").fillna(0.5)
    amount_percentile = pd.to_numeric(sample["amount_percentile"], errors="coerce").fillna(0.0)
    amount_contraction = pd.to_numeric(sample["amount_contraction"], errors="coerce").fillna(0.0)
    group_bonus = sample["group"].map({"A 回调充分+转强": 35.0, "C 强势延续": 18.0, "B 回调充分+未转强": 10.0}).fillna(0.0)
    turn_bonus = sample["turn_strong"].fillna(False).astype(float) * 12.0
    pullback_bonus = sample["pullback_sufficient"].fillna(False).astype(float) * 8.0
    trend_bonus = sample["above_ma20"].fillna(False).astype(float) * 5.0 + sample["above_ma60"].fillna(False).astype(float) * 3.0
    contraction_bonus = np.clip(-amount_contraction, 0, 0.35) * 12.0
    high_position_penalty = sample["high_position_signal"].fillna(False).astype(float) * 6.0
    high_liquidity_break_penalty = (
        sample["high_liquidity_signal"].fillna(False).astype(float) * (~sample["above_ma20"].fillna(False)).astype(float) * 8.0
    )
    score = (
        12.0
        + group_bonus
        + turn_bonus
        + pullback_bonus
        + trend_bonus
        + rs_rank * 22.0
        + amount_percentile * 12.0
        + np.clip(ret_5, -0.05, 0.08) * 120.0
        + np.clip(ret_20, -0.08, 0.12) * 40.0
        + np.clip(-drawdown_20, 0, 0.20) * 25.0
        + contraction_bonus
        - high_position_penalty
        - high_liquidity_break_penalty
    )
    sample["flow_candidate_score"] = np.clip(score, 0, 100)
    sample = sample.sort_values(["flow_candidate_score", "rs_rank", "amount_percentile"], ascending=False).head(config.flow_candidate_limit)
    rows: list[dict[str, object]] = []
    for rank, (_, row) in enumerate(sample.iterrows(), start=1):
        rows.append(
            {
                "rank": rank,
                "date": row.get("date"),
                "stock_code": row.get("stock_code"),
                "group": row.get("group"),
                "asset_pool": row.get("asset_pool"),
                "score": float(row.get("flow_candidate_score")),
                "reason": _flow_candidate_reason(row),
                "ret_5": row.get("ret_5"),
                "ret_20": row.get("ret_20"),
                "drawdown_20": row.get("drawdown_20"),
                "drawdown_60": row.get("drawdown_60"),
                "rs20": row.get("rs20"),
                "rs_rank": row.get("rs_rank"),
                "amount_percentile": row.get("amount_percentile"),
                "amount_contraction": row.get("amount_contraction"),
                "above_ma20": _bool_value(row.get("above_ma20")),
                "turn_strong": _bool_value(row.get("turn_strong")),
                "pullback_sufficient": _bool_value(row.get("pullback_sufficient")),
                "high_position_signal": _bool_value(row.get("high_position_signal")),
                "high_liquidity_signal": _bool_value(row.get("high_liquidity_signal")),
            }
        )
    return rows


def _flow_candidate_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    group = str(row.get("group") or "")
    if group.startswith("A"):
        reasons.append("回调充分且转强")
    elif group.startswith("C"):
        reasons.append("强势延续")
    elif group.startswith("B"):
        reasons.append("回调充分待确认")
    if _bool_value(row.get("above_ma20")):
        reasons.append("站上MA20")
    if _bool_value(row.get("turn_strong")):
        reasons.append("短线转强")
    if _finite(row.get("rs_rank")) >= 0.7:
        reasons.append("相对强度靠前")
    if _finite(row.get("amount_percentile")) >= 0.7:
        reasons.append("流动性靠前")
    if _finite(row.get("amount_contraction")) < -0.10:
        reasons.append("成交收缩后修复")
    return "、".join(reasons[:4]) if reasons else "横截面基准候选"


def _state_report(latest: pd.DataFrame, risk_appetite: dict[str, object], config: MarketRegimeConfig) -> dict[str, object]:
    return {
        "trend": {
            "breadth_ma20": float(latest["above_ma20"].fillna(False).mean()),
            "breadth_ma60": float(latest["above_ma60"].fillna(False).mean()),
            "positive_5d_ratio": float((latest["ret_5"] > 0).fillna(False).mean()),
        },
        "volatility": {
            "median_hv20": _safe_median(latest["hv20"]),
            "median_atr20_close": _safe_median(latest["atr20_close"]),
        },
        "liquidity": {
            "top20_amount_share": _top_amount_share(latest, config.concentration_top_n),
            "median_amount20": _safe_median(latest["amount20"]),
        },
        "phase": risk_appetite.get("phase", ""),
    }


def _daily_report(
    *,
    latest: pd.DataFrame,
    config: MarketRegimeConfig,
    risk_appetite: dict[str, object],
    state_report: dict[str, object],
    migration_layers: list[dict[str, object]],
    factor_backtest: list[dict[str, object]],
    risk_release_sequence: dict[str, object],
    market_scope: dict[str, object],
) -> dict[str, object]:
    phase = str(risk_appetite.get("phase") or "-")
    score = risk_appetite.get("score")
    as_of = latest["date"].max() if "date" in latest.columns and not latest.empty else pd.NaT
    flow_from = _daily_flow_from(migration_layers, risk_release_sequence)
    flow_to = _daily_flow_to(latest, factor_backtest, risk_appetite, config)
    high_liquidity_selloff = float(risk_appetite.get("high_liquidity_break_ratio") or 0) >= config.high_liquidity_selloff_threshold
    market_mode = _market_mode(phase, risk_appetite)
    return {
        "as_of": as_of,
        "title": f"{pd.Timestamp(as_of).date().isoformat() if pd.notna(as_of) else '-'} 市场状态报告",
        "phase": phase,
        "score": score,
        "trend_status": _trend_status(state_report, config),
        "volatility_status": _volatility_status(state_report),
        "liquidity_status": _liquidity_status(state_report, config),
        "flow": {
            "from": flow_from,
            "to": flow_to,
            "high_liquidity_selloff": high_liquidity_selloff,
            "current_release_stage": risk_release_sequence.get("current_stage", "未触发"),
            "market_mode": market_mode,
        },
        "answers": {
            "risk_phase": phase,
            "funds_leaving": flow_from,
            "funds_entering": flow_to,
            "high_liquidity_selloff": high_liquidity_selloff,
            "closer_to": market_mode,
        },
        "evidence": _daily_evidence(latest, state_report, migration_layers, market_scope),
        "caveats": [
            "当前本地行情缓存只提供 OHLCV，未读取到自由流通市值；大盘/中盘分层暂按 20 日成交额横截面分位近似。",
        ],
    }


def _daily_flow_from(migration_layers: list[dict[str, object]], risk_release_sequence: dict[str, object]) -> str:
    stressed = [
        str(row.get("layer"))
        for row in risk_release_sequence.get("layers", [])
        if isinstance(row, dict) and row.get("current_stress") and row.get("layer") != "现金偏好代理"
    ]
    if stressed:
        return "、".join(stressed)
    weak_layers = [
        str(row.get("layer"))
        for row in migration_layers
        if str(row.get("layer")) != "全市场" and _numeric_or_nan(row.get("return_5d")) < 0
    ]
    return "、".join(weak_layers) if weak_layers else "未观察到明确单一流出层"


def _daily_flow_to(
    latest: pd.DataFrame,
    factor_backtest: list[dict[str, object]],
    risk_appetite: dict[str, object],
    config: MarketRegimeConfig,
) -> str:
    group_counts = latest["group"].value_counts() if "group" in latest.columns else pd.Series(dtype=int)
    if int(group_counts.get("A 回调充分+转强", 0)) > 0:
        return "回调充分 + 转强资产"
    best_group = _best_factor_group(factor_backtest)
    if best_group:
        return best_group.replace("+", " + ")
    if _numeric_or_nan(risk_appetite.get("cash_preference_proxy")) >= config.cash_preference_proxy_threshold:
        return "现金偏好"
    return "尚未形成稳定回流方向"


def _best_factor_group(factor_backtest: list[dict[str, object]]) -> str:
    rows = [row for row in factor_backtest if row.get("window") in {"5日", "10日"}]
    if not rows:
        return ""
    best = max(rows, key=lambda row: _numeric_or_nan(row.get("excess_return")))
    return str(best.get("group") or "")


def _market_mode(phase: str, risk_appetite: dict[str, object]) -> str:
    score = _numeric_or_nan(risk_appetite.get("score"))
    if phase == "风险偏好扩张" or score >= 65:
        return "主升/扩散阶段"
    if phase == "风险释放后段":
        return "风险释放后段"
    if phase == "风险偏好收缩" or score <= 35:
        return "风险释放阶段"
    return "震荡修复阶段"


def _trend_status(state_report: dict[str, object], config: MarketRegimeConfig) -> str:
    trend = state_report.get("trend", {}) if isinstance(state_report, dict) else {}
    breadth = _numeric_or_nan(trend.get("breadth_ma20") if isinstance(trend, dict) else None)
    if breadth >= config.risk_expansion_breadth_threshold:
        return "扩散"
    if breadth <= config.risk_contraction_breadth_threshold:
        return "收缩"
    return "均衡"


def _volatility_status(state_report: dict[str, object]) -> str:
    volatility = state_report.get("volatility", {}) if isinstance(state_report, dict) else {}
    hv20 = _numeric_or_nan(volatility.get("median_hv20") if isinstance(volatility, dict) else None)
    if hv20 >= 0.35:
        return "高波动"
    if hv20 <= 0.18:
        return "低波动"
    return "中波动"


def _liquidity_status(state_report: dict[str, object], config: MarketRegimeConfig) -> str:
    liquidity = state_report.get("liquidity", {}) if isinstance(state_report, dict) else {}
    share = _numeric_or_nan(liquidity.get("top20_amount_share") if isinstance(liquidity, dict) else None)
    if share >= config.high_liquidity_selloff_threshold:
        return "集中"
    if share <= config.liquidity_mid_percentile:
        return "分散"
    return "均衡"


def _daily_evidence(
    latest: pd.DataFrame,
    state_report: dict[str, object],
    migration_layers: list[dict[str, object]],
    market_scope: dict[str, object],
) -> list[dict[str, object]]:
    trend = state_report.get("trend", {}) if isinstance(state_report, dict) else {}
    latest_scope = market_scope.get("latest", {}) if isinstance(market_scope, dict) else {}
    high_liquidity = next((row for row in migration_layers if row.get("layer") == "高流动性资产"), {})
    return [
        {"metric": "MA20宽度", "value": trend.get("breadth_ma20") if isinstance(trend, dict) else None},
        {"metric": "MA60宽度", "value": trend.get("breadth_ma60") if isinstance(trend, dict) else None},
        {"metric": "高流动性跌破MA20", "value": high_liquidity.get("ma20_break_ratio")},
        {"metric": "成交额集中度", "value": latest_scope.get("top20_amount_share") if isinstance(latest_scope, dict) else None},
        {"metric": "回调充分+转强数量", "value": int(latest["group"].eq("A 回调充分+转强").sum()) if "group" in latest.columns else 0},
    ]


def _asset_rows(latest: pd.DataFrame) -> list[dict[str, object]]:
    columns = [
        "date",
        "stock_code",
        "group",
        "asset_pool",
        "drawdown_20",
        "drawdown_60",
        "rs20",
        "rs_rank",
        "ret_5",
        "ret_20",
        "ret_120",
        "hv20",
        "hv60",
        "atr20_close",
        "amount20",
        "amount60",
        "amount_rank",
        "amount_percentile",
        "volatility_bucket",
        "liquidity_bucket",
        "position_bucket",
        "high_position_signal",
        "high_liquidity_signal",
        "above_ma20",
        "above_ma60",
    ]
    present = [column for column in columns if column in latest.columns]
    return latest[present].sort_values(["group", "stock_code"]).to_dict("records")


def _safe_mean(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else float("nan")


def _numeric_or_nan(value: object) -> float:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(number) if pd.notna(number) else float("nan")


def _window_sort_key(value: object) -> int:
    text = str(value or "")
    digits = "".join(char for char in text if char.isdigit())
    return int(digits) if digits else 9999


def _phase_tone(value: object) -> str:
    text = str(value or "")
    if "扩张" in text or "主升" in text or "回流" in text:
        return "opportunity"
    if "释放" in text or "收缩" in text or "抛售" in text:
        return "risk"
    return "neutral"


def _format_ratio_text(value: object) -> str:
    number = _numeric_or_nan(value)
    return f"{number:.2%}" if math.isfinite(number) else "-"


def _finite(value: object, default: float = 0.0) -> float:
    number = _numeric_or_nan(value)
    return number if math.isfinite(number) else default


def _bool_value(value: object) -> bool:
    return bool(value) if pd.notna(value) else False


def _safe_median(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else float("nan")


def _top_amount_share(latest: pd.DataFrame, count: int) -> float:
    amount = pd.to_numeric(latest["amount20"], errors="coerce").fillna(0).sort_values(ascending=False)
    total = amount.sum()
    return float(amount.head(count).sum() / total) if total else 0.0
