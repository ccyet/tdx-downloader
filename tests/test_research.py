from __future__ import annotations

import pandas as pd
import pytest

from tdx_downloader.research.history import HistorySearchConfig, search_history
from tdx_downloader.research.review import (
    ReviewConfig,
    analyze_price_review,
    build_equal_weight_series,
    rank_review_results,
    render_multi_review_text,
    render_multi_video_script_text,
)
from tdx_downloader.research.features import window_features
from tdx_downloader.research import market_regime as market_regime_module
from tdx_downloader.research.market_regime import MarketRegimeConfig, run_market_regime_research
from tdx_downloader.research.scoring import fast_window_feature_arrays
from tdx_downloader.research.similarity import (
    CrossSectionSearchConfig,
    CrossSectionWindowTraversalConfig,
    search_cross_section,
    search_cross_section_window_traversal,
)


def _bars(symbol: str, closes: list[float], *, start: str = "2026-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "stock_code": symbol,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0 + index for index, _ in enumerate(closes)],
            "amount": [100000.0 + index * 100 for index, _ in enumerate(closes)],
        }
    )


def test_history_search_finds_prior_similar_window() -> None:
    bars = _bars(
        "000001.SZ",
        [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16],
    )

    result = search_history(
        bars,
        HistorySearchConfig(
            symbol="000001.SZ",
            as_of="2026-01-20",
            window_size=4,
            top_n=3,
            exclusion_bars=1,
            forward_windows=(2,),
        ),
    )

    assert result.window_size == 4
    assert not result.results.empty
    assert result.results.iloc[0]["symbol"] == "000001.SZ"
    assert "综合相似度" in result.results.columns
    assert "后2根收益" in result.results.columns


def test_history_search_returns_candidate_windows_with_forward_bars() -> None:
    bars = _bars(
        "000001.SZ",
        [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16],
    )

    result = search_history(
        bars,
        HistorySearchConfig(
            symbol="000001.SZ",
            as_of="2026-01-20",
            window_size=4,
            top_n=2,
            exclusion_bars=1,
            forward_windows=(2,),
        ),
    )

    assert result.historical_chart_windows
    assert len(result.historical_chart_windows[0]) == result.window_size + 2
    assert len(result.historical_windows[0]) == result.window_size


def test_history_search_supports_source_algorithm_and_nearby_window_filter() -> None:
    bars = _bars(
        "000001.SZ",
        [10, 11, 12, 13, 10, 11, 12, 13, 10, 11, 12, 13, 10, 11, 12, 13, 10, 11, 12, 13],
    )

    result = search_history(
        bars,
        HistorySearchConfig(
            symbol="000001.SZ",
            as_of="2026-01-28",
            window_size=4,
            top_n=3,
            candidate_n=20,
            exclusion_bars=1,
            nearby_gap_days=10,
            forward_windows=(2,),
            algorithm="return_shape",
        ),
    )

    assert result.results["算法"].dropna().unique().tolist() == ["return_shape"]
    assert {"价格路径距离", "收益路径距离"}.issubset(result.results.columns)
    windows = [
        (pd.Timestamp(row["窗口开始"]), pd.Timestamp(row["窗口结束"]))
        for _, row in result.results.iterrows()
    ]
    for index, (left_start, left_end) in enumerate(windows):
        for right_start, right_end in windows[index + 1:]:
            assert _window_gap_days(left_start, left_end, right_start, right_end) >= 10


def test_history_search_rejects_explicit_window_without_end_coverage() -> None:
    bars = _bars("000001.SZ", [10, 11, 12, 13, 14, 15])

    with pytest.raises(ValueError, match="未覆盖选定窗口结束"):
        search_history(
            bars,
            HistorySearchConfig(
                symbol="000001.SZ",
                window_start="2026-01-01",
                as_of="2026-02-20",
                window_size=4,
                top_n=3,
                exclusion_bars=1,
                forward_windows=(2,),
            ),
        )


def test_history_feature_arrays_include_price_liquidity_correlation() -> None:
    bars = _bars("000001.SZ", [10, 11, 10.5, 12, 11.5, 13])
    bars["amount"] = [1000, 1800, 900, 2200, 1100, 2600]
    close = bars["close"].to_numpy(dtype=float)
    liquidity = bars["amount"].to_numpy(dtype=float)

    values = fast_window_feature_arrays(close, liquidity, starts=pd.Index([0]).to_numpy(), window_size=len(bars))

    assert values["量价相关"][0] == pytest.approx(window_features(bars)["量价相关"])
    assert values["量价相关"][0] != 0


def test_cross_section_search_keeps_vectorized_date_tolerance_match() -> None:
    target = _bars("000001.SZ", [10, 11, 12, 13, 14, 15, 16, 17])
    shifted = _bars("000002.SZ", [8, 9, 10, 11, 12, 13, 15, 16])
    weak = _bars("000003.SZ", [20, 19, 18, 17, 16, 15, 14, 13])
    bars = pd.concat([target, shifted, weak], ignore_index=True)

    result = search_cross_section(
        bars,
        CrossSectionSearchConfig(
            target_symbol="000001.SZ",
            universe_symbols=("000002.SZ", "000003.SZ"),
            start="2026-01-06",
            end="2026-01-09",
            top_n=2,
            date_tolerance_bars=2,
        ),
    )

    assert result.window_size == 4
    assert result.results.iloc[0]["symbol"] == "000002.SZ"
    assert abs(float(result.results.iloc[0]["日期偏移"])) <= 2
    assert "后3根收益" in result.results.columns


def test_cross_section_window_traversal_searches_candidate_interval() -> None:
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 12, 11, 13], start="2026-05-18"),
            _bars("000002.SZ", [7, 8, 10, 12, 11, 13, 14], start="2021-01-01"),
            _bars("000003.SZ", [30, 29, 28, 27, 26, 25, 24], start="2021-01-01"),
        ],
        ignore_index=True,
    )

    result = search_cross_section_window_traversal(
        bars,
        CrossSectionWindowTraversalConfig(
            target_symbol="000001.SZ",
            universe_symbols=("000002.SZ", "000003.SZ"),
            target_start="2026-05-18",
            target_end="2026-05-21",
            traversal_start="2021-01-01",
            traversal_end="2021-01-11",
            top_n=2,
            min_coverage=1.0,
            forward_windows=(1,),
        ),
    )

    assert result.window_size == 4
    first = result.results.iloc[0]
    assert first["symbol"] == "000002.SZ"
    assert first["区间开始"] == pd.Timestamp("2021-01-05")
    assert first["区间结束"] == pd.Timestamp("2021-01-08")
    assert first["遍历偏移"] == 2
    assert "后1根收益" in result.results.columns


def test_review_ranking_uses_local_bars_without_external_sources() -> None:
    strong = _bars("000001.SZ", [10, 10.5, 11, 12, 13, 14])
    weak = _bars("000002.SZ", [10, 9.8, 9.5, 9.7, 9.6, 9.4])
    bars = pd.concat([strong, weak], ignore_index=True)
    results = [
        analyze_price_review(bars, ReviewConfig(symbol="000001.SZ", start="2026-01-01", end="2026-01-08")),
        analyze_price_review(bars, ReviewConfig(symbol="000002.SZ", start="2026-01-01", end="2026-01-08")),
    ]

    ranking = rank_review_results(results, stock_names={"000001.SZ": "强势样例", "000002.SZ": "弱势样例"})

    assert ranking["代码"].tolist()[0] == "000001.SZ"
    assert {"排名", "代码", "股票", "强弱等级", "区间收益", "最大回撤", "锐评结论"}.issubset(ranking.columns)


def test_review_text_outputs_ranking_framework() -> None:
    strong = _bars("000001.SZ", [10, 10.5, 11, 12, 13, 14])
    weak = _bars("000002.SZ", [10, 9.8, 9.5, 9.7, 9.6, 9.4])
    bars = pd.concat([strong, weak], ignore_index=True)
    results = [
        analyze_price_review(bars, ReviewConfig(symbol="000001.SZ", start="2026-01-01", end="2026-01-08")),
        analyze_price_review(bars, ReviewConfig(symbol="000002.SZ", start="2026-01-01", end="2026-01-08")),
    ]

    review_text = render_multi_review_text(results, stock_names={"000001.SZ": "强势样例", "000002.SZ": "弱势样例"})
    script_text = render_multi_video_script_text(results, stock_names={"000001.SZ": "强势样例", "000002.SZ": "弱势样例"})

    assert "研究端排序复盘" in review_text
    assert "排序总表" in review_text
    assert "逐个锐评" in review_text
    assert "强势样例（000001.SZ）" in review_text
    assert "视频脚本视角" in script_text
    assert "强势样例（000001.SZ）" in script_text


def test_build_equal_weight_series_normalizes_without_dataframe_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 11, 12]),
            _bars("000002.SZ", [20, 21, 22]),
        ],
        ignore_index=True,
    )

    def fail_apply(*_: object, **__: object) -> None:
        raise AssertionError("等权序列不应退回 DataFrame.apply 逐行处理。")

    monkeypatch.setattr(pd.DataFrame, "apply", fail_apply)

    result = build_equal_weight_series(bars, ("000001.SZ", "000002.SZ"), label="等权组合")

    assert result.warning == ""
    assert result.coverage == 1.0
    assert result.frame["stock_code"].tolist() == ["等权组合", "等权组合", "等权组合"]


def test_market_regime_reuses_precomputed_benchmark_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = pd.concat(
        [
            _bars("000300.SH", [10 + index * 0.03 for index in range(100)]),
            _bars("000001.SZ", [8 + index * 0.02 for index in range(100)]),
            _bars("000002.SZ", [12 - index * 0.01 for index in range(100)]),
        ],
        ignore_index=True,
    )

    def fail_aligned_benchmark_forward(*_: object, **__: object) -> None:
        raise AssertionError("市场风偏计算不应在分组循环内重复构造基准前瞻收益。")

    monkeypatch.setattr(market_regime_module, "_aligned_benchmark_forward", fail_aligned_benchmark_forward)

    result = run_market_regime_research(
        bars,
        MarketRegimeConfig(
            benchmark_symbol="000300.SH",
            symbols=("000001.SZ", "000002.SZ"),
            start="2026-01-01",
            end="2026-05-15",
            forward_windows=(3, 5, 10),
        ),
    )

    assert result["factor_backtest"]
    assert result["high_liquidity_break_study"]


def _window_gap_days(
    left_start: pd.Timestamp,
    left_end: pd.Timestamp,
    right_start: pd.Timestamp,
    right_end: pd.Timestamp,
) -> int:
    if left_start <= right_end and right_start <= left_end:
        return 0
    if left_end < right_start:
        return int((right_start - left_end).days)
    return int((left_start - right_end).days)
