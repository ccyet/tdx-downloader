from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.request

from tdx_downloader.research.review_ai import ReviewAIFormatError, parse_review_ai_result

from .schemas import ReviewAIPayload


def _call_review_ai(payload: ReviewAIPayload) -> dict[str, Any]:
    base_url = payload.base_url.strip()
    api_key = payload.api_key.strip()
    model = payload.model.strip()
    if not base_url:
        raise ValueError("请填写 AI 接口 URL。")
    if not api_key:
        raise ValueError("请填写 AI API Key。")
    if not model:
        raise ValueError("请填写 AI 模型名称。")
    if not payload.messages:
        raise ValueError("缺少可提交给模型的 messages。")
    request_body = {
        "model": model,
        "messages": payload.messages,
        "temperature": float(payload.temperature),
    }
    request = urllib.request.Request(
        _chat_completions_url(base_url),
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_ai_timeout(payload.timeout_seconds)) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"AI 接口调用失败：HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI 接口连接失败：{exc.reason}") from exc
    try:
        response_payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI 接口返回不是合法 JSON：{exc}") from exc
    content = _ai_message_content(response_payload)
    try:
        parsed = parse_review_ai_result(content, evidence=payload.evidence or None)
    except ReviewAIFormatError as exc:
        raise ValueError(f"AI 输出格式错误：{exc}") from exc
    return {
        "review": parsed.review,
        "analysis": parsed.analysis,
        "critique": parsed.critique,
        "script_cards": [
            {
                "title": card.title,
                "body": card.body,
                "grade": card.grade,
                "tomorrow_check": card.tomorrow_check,
            }
            for card in parsed.script_cards
        ],
        "evidence_refs": list(parsed.evidence_refs),
        "disclaimer": parsed.disclaimer,
        "raw": parsed.raw,
    }


def _chat_completions_url(base_url: str) -> str:
    text = base_url.strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise ValueError("AI 接口 URL 必须以 http:// 或 https:// 开头。")
    if text.endswith("/chat/completions"):
        return text
    return f"{text}/chat/completions"


def _ai_timeout(value: int) -> int:
    return max(5, min(int(value or 60), 180))


def _ai_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("AI 接口返回缺少 choices。")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI 接口返回缺少 message.content。")
    return content
