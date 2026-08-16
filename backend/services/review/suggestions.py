"""Model-generated revision suggestions for deterministic review findings.

Deterministic matchers locate the evidence; the LLM tailors a concrete,
operable 修改建议 per finding from the rule description and the matched
original text. When the model is unavailable or returns malformed output,
findings keep their rule-authored static suggestion.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Sequence

from core.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from core.http_client import httpx_request

SYSTEM_PROMPT = (
    "你是企业合同审查助手。根据每条风险命中的原文与规则说明，给出一条具体、"
    "可操作的修改建议（贴合原文语境，包含明确的修订方向；中文，不超过120字）。"
    '只输出 JSON：{"items":[{"finding_id":"...","suggestion":"..."}]}，'
    "finding_id 必须与输入一一对应。"
)


def _default_llm(messages: Sequence[Mapping[str, str]]) -> str:
    response = httpx_request(
        "POST",
        f"{LLM_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": LLM_MODEL,
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": list(messages),
        },
        timeout=90,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"])


def _parse_payload(content: str) -> list[dict[str, Any]]:
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("LLM did not return a JSON object")
    payload = json.loads(match.group(0))
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("LLM payload missing items array")
    return items


def generate_suggestions(
    findings: Sequence[dict[str, Any]],
    *,
    llm: Callable[[Sequence[Mapping[str, str]]], str] | None = None,
    batch_size: int = 12,
) -> list[dict[str, Any]]:
    """Enrich findings with model suggestions; degrade to rule-authored text."""
    caller = llm or _default_llm
    enriched: list[dict[str, Any]] = []
    for start in range(0, len(findings), batch_size):
        group = [dict(finding) for finding in findings[start : start + batch_size]]
        try:
            briefs = "\n".join(
                f'- finding_id: {item.get("finding_id")}\n'
                f'  规则: {item.get("title") or item.get("rule_id") or ""}\n'
                f'  规则说明: {item.get("explanation") or item.get("description") or ""}\n'
                f'  命中原文: {item.get("quote") or ""}'
                for item in group
            )
            content = caller(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"为以下风险生成修改建议：\n{briefs}"},
                ]
            )
            by_id = {
                str(item.get("finding_id")): str(item.get("suggestion") or "").strip()
                for item in _parse_payload(content)
            }
            for finding in group:
                text = by_id.get(str(finding.get("finding_id")))
                if text:
                    finding["suggested_fix"] = text
                    finding["suggestion_source"] = "model"
                else:
                    finding.setdefault("suggestion_source", "rule")
        except Exception:  # model outage / parse error → keep static suggestions
            for finding in group:
                finding.setdefault("suggestion_source", "rule")
        enriched.extend(group)
    return enriched


__all__ = ["generate_suggestions"]
