"""Deterministic false-positive filtering for review candidates."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, TypeVar


ANTI_FALSE_POSITIVE_RULES = (
    "Ignore standalone sequence numbers, list markers, and isolated letters.",
    "Ignore form placeholders and unfilled underscore fields.",
    "Ignore checkbox and option-symbol rows.",
    "Ignore punctuation-only formatting and separator lines.",
    "Ignore isolated contract labels such as party, signature, seal, and payroll fields.",
    "Ignore isolated numeric, amount, and date fields without substantive context.",
    "When evidence is uncertain, do not report the candidate.",
)

_SEQUENCE_ONLY = re.compile(
    r"^\s*(?:(?:第?[一二三四五六七八九十百千]+(?:章|节|条|款|项)?[、.]?)|"
    r"(?:[（(][一二三四五六七八九十百千\dA-Za-z]+[）)])|"
    r"(?:[（(]?\d+[）).、.]?)|(?:[（(]?[A-Za-z][）).、.]?)|[①-⑳])\s*$"
)
_PLACEHOLDER = re.compile(
    r"(?:_{2,}|＿{2,}|﹍{2,}|-{3,}|…{2,})|"
    r"(?:[_＿﹍]+\s*年\s*[_＿﹍]+\s*月\s*[_＿﹍]+\s*日)|"
    r"(?:[_＿﹍]{1,}\s*(?:元|万元|美元|人民币))"
)
_CHECKBOX = re.compile(
    r"[□☐☑☒○◯●◎]|(?:^|[\s:：;；,，])口(?=$|[\s:：;；,，])"
)
_FORMAT_ONLY = re.compile(r"^[\s:：;；,，.。·•\-—–_=＿﹍/\\|]+$")
_STANDARD_LABEL = re.compile(
    r"^(?:甲方|乙方|丙方|用人单位|劳动者|员工|签字|签名|盖章|公章|"
    r"工资结算|工资发放|结算|发放|日期|年月日|经办人|法定代表人)"
    r"(?:\s*[（(][^）)]{0,12}[）)])?\s*[:：]?\s*$"
)
_PARTY_SIGNATURE_LINE = re.compile(
    r"^(?:(?:甲方|乙方|丙方|用人单位|劳动者|员工)\s*[:：]?\s*)?"
    r"(?:签字|签名|盖章|公章)\s*[:：]?\s*$"
)
_ISOLATED_NUMBER = re.compile(
    r"^\s*(?:人民币|RMB|CNY|USD|US\$|美元|[$￥¥])?\s*"
    r"[+-]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?\s*[万亿]?\s*"
    r"(?:人民币|RMB|CNY|USD|美元|元|万元|亿元|天|日|个月|月|年|%|％)?\s*$",
    re.IGNORECASE,
)
_ISOLATED_DATE = re.compile(
    r"^\s*(?:\d{4}|[一二〇零]{4})\s*[年./-]\s*\d{1,2}\s*[月./-]\s*"
    r"\d{1,2}\s*日?\s*$"
)


def false_positive_reason(text: str | None) -> str | None:
    """Classify clear formatting/form noise; return ``None`` for content."""

    if text is None or not str(text).strip():
        return "empty"
    value = str(text).strip()
    if _SEQUENCE_ONLY.fullmatch(value):
        return "sequence_marker"
    if _PLACEHOLDER.search(value):
        return "placeholder"
    if _CHECKBOX.search(value):
        return "checkbox_or_option"
    if _FORMAT_ONLY.fullmatch(value):
        return "format_marker"
    if _STANDARD_LABEL.fullmatch(value) or _PARTY_SIGNATURE_LINE.fullmatch(value):
        return "standard_contract_label"
    if _ISOLATED_DATE.fullmatch(value):
        return "isolated_date"
    if _ISOLATED_NUMBER.fullmatch(value):
        return "isolated_numeric_value"
    return None


def is_false_positive(text: str | None) -> bool:
    """Return whether a candidate is deterministic form/format noise."""

    return false_positive_reason(text) is not None


T = TypeVar("T")


def filter_false_positives(
    candidates: Iterable[T], *, text_field: str = "quote"
) -> list[T]:
    """Remove candidates classified as false positives while preserving type.

    Strings, mappings, and dataclass instances are supported.  Mapping and
    dataclass candidates use ``text_field`` first, then ``text`` as a fallback.
    """

    return [
        candidate
        for candidate in candidates
        if not is_false_positive(_candidate_text(candidate, text_field))
    ]


def partition_false_positives(
    candidates: Iterable[T], *, text_field: str = "quote"
) -> tuple[list[T], list[tuple[T, str]]]:
    """Return kept candidates and rejected candidates with audit reasons."""

    kept: list[T] = []
    rejected: list[tuple[T, str]] = []
    for candidate in candidates:
        reason = false_positive_reason(_candidate_text(candidate, text_field))
        if reason:
            rejected.append((candidate, reason))
        else:
            kept.append(candidate)
    return kept, rejected


def _candidate_text(candidate: Any, text_field: str) -> str | None:
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, Mapping):
        value = candidate.get(text_field, candidate.get("text"))
        return str(value) if value is not None else None
    value = getattr(candidate, text_field, getattr(candidate, "text", None))
    return str(value) if value is not None else None


__all__ = [
    "ANTI_FALSE_POSITIVE_RULES",
    "false_positive_reason",
    "filter_false_positives",
    "is_false_positive",
    "partition_false_positives",
]
