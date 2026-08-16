"""Grounded answer generation over trusted document candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable

from core.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from core.http_client import httpx_request
from services.review.qa_retrieval import DocumentScope, build_citation, evidence_snippet, retrieve_evidence


REFUSAL_TEXT = "当前文档未提供足够依据，无法可靠回答该问题。请核对问题是否针对所选文档，或查看文档原文。"


@dataclass
class GroundedAnswer:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    refusal_code: str | None = None

    @classmethod
    def refusal(cls, code: str = "no_evidence") -> "GroundedAnswer":
        return cls(answer=REFUSAL_TEXT, refused=True, refusal_code=code)


def _llm_json(question: str, candidates, *, history: list[dict[str, Any]] | None = None, finding: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = "\n\n".join(
        f"[{item.candidate_id}] {evidence_snippet(item.canonical_text, question)}" for item in candidates
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是企业合同审查问答助手。仅依据给出的证据与上下文回答，不得引入外部知识。"
                "回答需具体、可操作；引用证据编号。输出 JSON: answer, citation_refs(候选编号数组), refused。"
                "证据不足或与上下文无关时必须 refused=true；但不得因存在背景信息而拒绝与背景无关的问题。"
                "answer 字段允许使用 markdown（标题、列表、表格）；当证据为表格时，用 markdown 表格呈现关键行/列。"
            ),
        },
    ]
    if finding:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是与本次审查相关的发现背景（可选参考）："
                    f"规则：{finding.get('title') or finding.get('rule_id') or ''}；"
                    f"风险说明：{finding.get('explanation') or ''}；"
                    f"命中原文：{finding.get('quote') or ''}。"
                    "仅当用户问题明确涉及该发现时才参考此背景；与发现无关的问题必须基于文档证据本身回答。"
                ),
            }
        )
    for item in (history or [])[-8:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = str(item.get("content") or "")
        if content:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": f"问题：{question}\n\n证据：\n{evidence}"})
    response = httpx_request(
        "POST", f"{LLM_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": LLM_MODEL, "temperature": 0, "stream": False,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }, timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(match.group(0))


def answer_document(
    question: str,
    scope: DocumentScope,
    filename: str,
    *,
    history: list[dict[str, Any]] | None = None,
    finding: dict[str, Any] | None = None,
    llm: Callable[[str, list[Any]], dict[str, Any]] = _llm_json,
) -> GroundedAnswer:
    candidates = retrieve_evidence(question, scope, filename=filename)
    if not candidates or max((candidate.score for candidate in candidates), default=0.0) <= 0:
        return GroundedAnswer.refusal("no_evidence")
    payload = llm(question, candidates, history=history, finding=finding)
    if bool(payload.get("refused")):
        return GroundedAnswer.refusal("model_no_evidence")
    refs = payload.get("citation_refs")
    answer = str(payload.get("answer") or "").strip()
    if not answer or not isinstance(refs, list) or not refs:
        return GroundedAnswer.refusal("unverified_answer")
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected = [by_id.get(str(ref)) for ref in refs]
    if any(candidate is None for candidate in selected):
        return GroundedAnswer.refusal("invalid_citation")
    citations = [build_citation(candidate).as_dict() for candidate in selected if candidate is not None]
    return GroundedAnswer(answer=answer, citations=citations)


__all__ = ["GroundedAnswer", "REFUSAL_TEXT", "answer_document"]
