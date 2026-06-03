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
from tdx_downloader.research.similarity import CrossSectionSearchConfig, search_cross_section


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
