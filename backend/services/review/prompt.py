"""Prompt construction for structured review LLM checks."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .anti_fp import ANTI_FALSE_POSITIVE_RULES


PROMPT_VERSION = "review-llm-check-v1"
MAX_FEW_SHOTS_PER_RULE = 3

SYSTEM_INSTRUCTIONS = """你是合同审查引擎中的结构化检查器。
只允许报告启用规则定义的问题类型。不得报告序号、占位符、勾选项、格式符号、标准签署栏、孤立金额或孤立日期。
证据不确定时返回空 issues，不确定宁可不报，不要误报。
输出必须是 JSON 对象，格式为 {"issues":[{"type":"规则名","text":"原文片段","explanation":"原因","suggested_fix":"修改建议","para_index":0}]}。"""

RETRY_INSTRUCTIONS = """上一次输出无法解析为指定 JSON。请只输出 JSON 对象，不要包含 Markdown、解释或代码块。"""


def build_review_messages(
    *,
    chunk_id: str,
    blocks: Sequence[Mapping[str, Any]],
    rules: Sequence[Mapping[str, Any]],
    retry: bool = False,
    include_input: bool = True,
) -> list[dict[str, str]]:
    """Build OpenAI-compatible messages for one chunk of review checks."""

    rule_cards = [_format_rule(rule) for rule in rules]
    system_parts = [
        SYSTEM_INSTRUCTIONS,
        "",
        "允许的问题类型:",
        ", ".join(_rule_name(rule) for rule in rules) or "无",
        "",
        "反误报排除规则:",
        *[f"- {rule}" for rule in ANTI_FALSE_POSITIVE_RULES],
    ]
    if retry:
        system_parts.extend(["", RETRY_INSTRUCTIONS])

    user_parts = [
        f"prompt_version: {PROMPT_VERSION}",
        f"chunk_id: {chunk_id}",
        "",
        "启用规则:",
        *rule_cards,
    ]
    if include_input:
        user_parts.extend(["", "输入段落（para_index 为本块内从 0 开始的索引）:"])
        for index, block in enumerate(blocks):
            user_parts.append(f"[{index}]{str(block.get('text') or '').strip()}")

    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def prompt_hash(messages: Sequence[Mapping[str, str]]) -> str:
    """Return a stable SHA-256 hash for a concrete prompt message list."""

    payload = json.dumps(
        list(messages),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prompt_template_hash(rules: Sequence[Mapping[str, Any]]) -> str:
    """Hash prompt template, anti-FP guidance, and rule cards without document text."""

    return prompt_hash(
        build_review_messages(
            chunk_id="template",
            blocks=[],
            rules=rules,
            include_input=False,
        )
    )


def _format_rule(rule: Mapping[str, Any]) -> str:
    fields = [
        f"- rule_id: {rule.get('rule_id') or rule.get('id') or ''}",
        f"  name: {_rule_name(rule)}",
        f"  severity: {rule.get('risk_level') or rule.get('severity') or 'medium'}",
    ]
    description = rule.get("description") or _definition(rule).get("description")
    if description:
        fields.append(f"  description: {description}")
    examples = _examples(rule)[:MAX_FEW_SHOTS_PER_RULE]
    if examples:
        fields.append("  few_shot_examples:")
        for example in examples:
            fields.append("    - " + json.dumps(example, ensure_ascii=False, sort_keys=True))
    return "\n".join(fields)


def _rule_name(rule: Mapping[str, Any]) -> str:
    return str(rule.get("name") or rule.get("rule_id") or rule.get("id") or "unknown_rule")


def _examples(rule: Mapping[str, Any]) -> list[Any]:
    value = rule.get("examples")
    if value is None:
        value = _definition(rule).get("examples")
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _definition(rule: Mapping[str, Any]) -> Mapping[str, Any]:
    value = rule.get("definition_json") or rule.get("definition") or {}
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "MAX_FEW_SHOTS_PER_RULE",
    "PROMPT_VERSION",
    "build_review_messages",
    "prompt_hash",
    "prompt_template_hash",
]
