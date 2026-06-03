from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tdx_downloader.research.review import ReviewConfig, analyze_price_review, build_comparison_stats
from tdx_downloader.research.review_ai import (
    ReviewAIFormatError,
    build_multi_review_ai_evidence,
    build_review_ai_evidence,
    build_review_ai_messages,
    parse_review_ai_result,
)


def _bars(symbol: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "stock_code": symbol,
            "open": closes,
            "high": [value * 1.02 for value in closes],
            "low": [value * 0.98 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "amount": [100000.0] * len(closes),
        }
    )


def test_build_review_ai_evidence_uses_only_local_review_inputs() -> None:
    target = _bars("000001.SZ", [10, 11, 12, 11, 13])
    benchmark = _bars("000300.SH", [10, 10.5, 10.4, 10.6, 10.7])
    result = analyze_price_review(target, ReviewConfig(symbol="000001.SZ", start="2026-01-01", end="2026-01-07"))
    comparisons = pd.DataFrame([build_comparison_stats(result.window, benchmark, "沪深300")])

    evidence = build_review_ai_evidence(
        result,
        comparisons,
        stock_names={"000001.SZ": "平安银行"},
        warnings=["样例风险"],
    )

    assert evidence["target"]["symbol"] == "000001.SZ"
    assert evidence["target"]["name"] == "平安银行"
    assert evidence["overview"]["return"] == result.overview["return"]
    assert evidence["segments"]
    assert evidence["comparisons"][0]["标的"] == "沪深300"
    assert evidence["warnings"] == ["样例风险"]
    assert "新闻" in evidence["limits"][0]
    json.dumps(evidence, ensure_ascii=False)


def test_build_multi_review_ai_evidence_includes_rankings_and_sanitizes_values() -> None:
    first = analyze_price_review(
        _bars("000001.SZ", [10, 11, 12, 13]),
        ReviewConfig(symbol="000001.SZ", start="2026-01-01", end="2026-01-06"),
    )
    second = analyze_price_review(
        _bars("600519.SH", [10, 9.8, 9.7, 9.6]),
        ReviewConfig(symbol="600519.SH", start="2026-01-01", end="2026-01-06"),
    )
    comparisons = pd.DataFrame(
        [
            {"代码": "000001.SZ", "标的": "沪深300", "超额收益": np.float64(0.12), "date": pd.Timestamp("2026-01-06")},
            {"代码": "600519.SH", "标的": "沪深300", "超额收益": np.nan, "date": pd.NaT},
        ]
    )

    evidence = build_multi_review_ai_evidence(
        [first, second],
        comparisons,
        stock_names={"000001.SZ": "平安银行", "600519.SH": "贵州茅台"},
        warnings=("ok", ""),
    )

    assert evidence["mode"] == "multi_stock"
    assert evidence["targets"] == ["000001.SZ", "600519.SH"]
    assert evidence["rankings"][0]["代码"] == "000001.SZ"
    assert evidence["reviews"][0]["target"]["name"] == "平安银行"
    assert evidence["comparisons"][0]["date"] == "2026-01-06"
    assert evidence["comparisons"][1]["超额收益"] is None
    assert evidence["warnings"] == ["ok"]
    json.dumps(evidence, ensure_ascii=False)


def test_build_review_ai_messages_require_json_contract() -> None:
    messages = build_review_ai_messages({"target": {"symbol": "000001.SZ"}, "warnings": []})

    assert messages[0]["role"] == "system"
    assert "JSON" in messages[0]["content"]
    assert "不得输出 Markdown" in messages[0]["content"]
    assert "review" in messages[0]["content"]
    assert "analysis" in messages[0]["content"]
    assert "critique" in messages[0]["content"]
    assert "script_cards" in messages[0]["content"]
    assert "夯爆了 > 人上人 > 立棍单打 > 刷子 > 路边 > NPC > 拉完了" in messages[0]["content"]
    assert "不得模仿具体真人" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "000001.SZ" in messages[1]["content"]


def test_parse_review_ai_result_accepts_structured_sections_and_cards() -> None:
    raw = json.dumps(
        {
            "review": {"市场总环境": "指数震荡", "排序总表": ["夯爆了：平安银行"]},
            "analysis": ["超额收益更强", "回撤控制更好"],
            "critique": {"【夯爆了】": "强趋势核心"},
            "script_cards": [{"title": "平安银行", "body": "强。", "grade": "夯爆了", "tomorrow_check": ""}],
            "evidence_refs": ["rankings[0]", "reviews[0].overview.return"],
            "disclaimer": "仅供研究",
        },
        ensure_ascii=False,
    )
    evidence = {"rankings": [{"代码": "000001.SZ"}], "reviews": [{"overview": {"return": 0.1}}]}

    result = parse_review_ai_result(raw, evidence=evidence)

    assert "市场总环境：指数震荡" in result.review
    assert "超额收益更强" in result.analysis
    assert "【夯爆了】：强趋势核心" in result.critique
    assert result.script_cards[0].grade == "夯爆了"
    assert result.evidence_refs == ("rankings[0]", "reviews[0].overview.return")


def test_parse_review_ai_result_rejects_missing_evidence_ref() -> None:
    raw = json.dumps(
        {
            "review": "复盘",
            "analysis": "分析",
            "critique": "锐评",
            "evidence_refs": ["news[0]"],
        },
        ensure_ascii=False,
    )

    with pytest.raises(ReviewAIFormatError, match="news\\[0\\]"):
        parse_review_ai_result(raw, evidence={"rankings": []})
