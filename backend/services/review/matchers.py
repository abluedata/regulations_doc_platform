"""Pure deterministic matchers for the review rule DSL.

The functions in this module intentionally accept plain mappings from the
document IR.  They therefore stay independent of the API schemas and can be
used by both the review engine and focused unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable, Mapping, Sequence


_DEFAULT_REGEX_FLAGS = re.IGNORECASE | re.UNICODE
_COMPARATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
    "eq": lambda value, threshold: value == threshold,
}
_UNIT_ALIASES = {
    "cny": ("cny", "rmb", "人民币", "元", "￥", "¥"),
    "usd": ("usd", "美元", "$", "us$"),
    "day": ("day", "days", "天", "日"),
    "month": ("month", "months", "个月", "月"),
    "year": ("year", "years", "年"),
    "percent": ("percent", "%", "％", "百分比"),
}
_MULTIPLIERS = {"万": Decimal("10000"), "亿": Decimal("100000000")}
_NUMBER_RE = re.compile(
    r"(?P<prefix>人民币|RMB|CNY|USD|US\$|美元|[$￥¥])?\s*"
    r"(?P<number>[+-]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<scale>[万亿])?\s*"
    r"(?P<suffix>人民币|RMB|CNY|USD|美元|元|天|日|个月|月|年|%|％)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MatchHit:
    """A source-preserving deterministic match."""

    block_id: str | None
    block_index: int
    quote: str
    start: int
    end: int
    matcher: str
    pattern: str | None = None
    value: Decimal | None = None
    unit: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    """Result of the combined matcher pipeline.

    ``indeterminate`` means deterministic evaluation could not be completed
    (for example, a referenced threshold was absent).  The engine may then use
    its configured LLM fallback; ``no_match`` is a completed negative result.
    """

    status: str
    hits: tuple[MatchHit, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"matched", "no_match", "indeterminate"}:
            raise ValueError(f"unsupported match status: {self.status}")

    @property
    def matched(self) -> bool:
        return self.status == "matched"


def match_keyword(
    text: str,
    patterns: str | Sequence[str],
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    block_id: str | None = None,
    block_index: int = 0,
) -> list[MatchHit]:
    """Return every non-overlapping literal keyword occurrence."""

    if not isinstance(text, str) or not text:
        return []
    values = _as_patterns(patterns)
    flags = re.UNICODE if case_sensitive else _DEFAULT_REGEX_FLAGS
    hits: list[MatchHit] = []
    for pattern in values:
        expression = re.escape(pattern)
        if whole_word:
            expression = rf"(?<!\w){expression}(?!\w)"
        for found in re.finditer(expression, text, flags):
            hits.append(
                MatchHit(
                    block_id=block_id,
                    block_index=block_index,
                    quote=found.group(0),
                    start=found.start(),
                    end=found.end(),
                    matcher="keyword",
                    pattern=pattern,
                )
            )
    return _deduplicate_hits(hits)


def match_regex(
    text: str,
    patterns: str | Sequence[str],
    *,
    flags: int = _DEFAULT_REGEX_FLAGS,
    block_id: str | None = None,
    block_index: int = 0,
) -> list[MatchHit]:
    """Return regex occurrences, preserving the exact matched source quote."""

    if not isinstance(text, str) or not text:
        return []
    hits: list[MatchHit] = []
    for pattern in _as_patterns(patterns):
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc
        for found in compiled.finditer(text):
            if found.start() == found.end():
                continue
            hits.append(
                MatchHit(
                    block_id=block_id,
                    block_index=block_index,
                    quote=found.group(0),
                    start=found.start(),
                    end=found.end(),
                    matcher="regex",
                    pattern=pattern,
                    details={"groups": found.groupdict()},
                )
            )
    return _deduplicate_hits(hits)


def match_scope(
    blocks: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any] | None,
) -> list[tuple[int, Mapping[str, Any]]]:
    """Select IR blocks within a configured section/window scope.

    A block matches when the expression is present in its section path or its
    own heading text.  ``window_blocks`` adds the configured number of blocks
    following every matching heading/path anchor.  With no section expression,
    all blocks remain eligible.
    """

    indexed = list(enumerate(blocks))
    if not scope:
        return indexed
    expression = scope.get("section_match")
    if not expression:
        return indexed
    try:
        section_re = re.compile(str(expression), _DEFAULT_REGEX_FLAGS)
    except re.error as exc:
        raise ValueError(f"invalid scope section_match {expression!r}: {exc}") from exc

    window = scope.get("window_blocks", 0)
    if isinstance(window, bool) or not isinstance(window, int) or window < 0:
        raise ValueError("scope.window_blocks must be a non-negative integer")

    selected: set[int] = set()
    anchors: list[int] = []
    for index, block in indexed:
        path_text = " > ".join(_section_parts(block.get("section_path")))
        heading_text = str(block.get("text") or "") if block.get("type") == "heading" else ""
        path_matches = bool(section_re.search(path_text))
        heading_matches = bool(section_re.search(heading_text))
        if path_matches or heading_matches:
            selected.add(index)
        if heading_matches:
            anchors.append(index)

    for anchor in anchors:
        stop = min(len(blocks), anchor + window + 1)
        for index in range(anchor, stop):
            if index > anchor and blocks[index].get("type") == "heading":
                break
            selected.add(index)
    return [(index, blocks[index]) for index in sorted(selected)]


def match_numeric(
    text: str,
    config: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
    block_id: str | None = None,
    block_index: int = 0,
) -> MatchResult:
    """Extract numeric values and compare them with an absolute/ref threshold."""

    compare = str(config.get("compare") or "").lower()
    comparator = _COMPARATORS.get(compare)
    if comparator is None:
        raise ValueError(f"numeric.compare must be one of {sorted(_COMPARATORS)}")

    threshold, reason = _resolve_threshold(config, context or {})
    if threshold is None:
        return MatchResult("indeterminate", reason=reason)

    requested_unit = _canonical_unit(config.get("unit"))
    field_hint = str(config.get("field") or "").strip()
    hits: list[MatchHit] = []
    for found in _NUMBER_RE.finditer(text or ""):
        raw_unit = (found.group("prefix") or found.group("suffix") or "").strip()
        actual_unit = _canonical_unit(raw_unit)
        if requested_unit and not _unit_matches(requested_unit, actual_unit, raw_unit):
            continue
        if field_hint and not _field_is_near(text, found.start(), found.end(), field_hint):
            continue
        try:
            value = Decimal(found.group("number").replace(",", "").replace("，", ""))
        except InvalidOperation:
            continue
        value *= _MULTIPLIERS.get(found.group("scale") or "", Decimal("1"))
        if comparator(value, threshold):
            hits.append(
                MatchHit(
                    block_id=block_id,
                    block_index=block_index,
                    quote=found.group(0),
                    start=found.start(),
                    end=found.end(),
                    matcher="numeric",
                    value=value,
                    unit=requested_unit or actual_unit or None,
                    details={"compare": compare, "threshold": threshold},
                )
            )
    if hits:
        return MatchResult("matched", tuple(_deduplicate_hits(hits)))
    return MatchResult("no_match", reason="no extracted value satisfied the threshold")


def match_rule(
    blocks: Sequence[Mapping[str, Any]],
    matcher: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> MatchResult:
    """Evaluate one rule matcher in scope -> text -> numeric order."""

    scoped = match_scope(blocks, matcher.get("scope"))
    if not scoped:
        return MatchResult("no_match", reason="scope did not select any blocks")

    text_patterns = matcher.get("text_pattern") or []
    text_hits: list[MatchHit] = []
    hit_blocks: set[int] = set()
    if text_patterns:
        if isinstance(text_patterns, (str, bytes)) or not isinstance(text_patterns, Sequence):
            raise ValueError("matcher.text_pattern must be a sequence")
        for index, block in scoped:
            text = str(block.get("text") or "")
            block_id = _block_id(block)
            for pattern_config in text_patterns:
                config = _pattern_config(pattern_config)
                kind = config["kind"]
                pattern = config["pattern"]
                if kind in {"keyword", "phrase"}:
                    current = match_keyword(
                        text,
                        pattern,
                        case_sensitive=bool(config.get("case_sensitive", False)),
                        whole_word=bool(config.get("whole_word", False)),
                        block_id=block_id,
                        block_index=index,
                    )
                elif kind == "regex":
                    flags = re.UNICODE
                    if not config.get("case_sensitive", False):
                        flags |= re.IGNORECASE
                    current = match_regex(
                        text, pattern, flags=flags, block_id=block_id, block_index=index
                    )
                else:
                    raise ValueError(f"unsupported text pattern kind: {kind}")
                if current:
                    hit_blocks.add(index)
                    text_hits.extend(current)
        if not text_hits:
            return MatchResult("no_match", reason="no text pattern matched")

    numeric = matcher.get("numeric")
    if not numeric:
        if not text_patterns:
            return MatchResult("indeterminate", reason="matcher has no text or numeric condition")
        return MatchResult("matched", tuple(_deduplicate_hits(text_hits)))
    if not isinstance(numeric, Mapping):
        raise ValueError("matcher.numeric must be a mapping")

    numeric_hits: list[MatchHit] = []
    numeric_blocks = [item for item in scoped if not hit_blocks or item[0] in hit_blocks]
    for index, block in numeric_blocks:
        result = match_numeric(
            str(block.get("text") or ""),
            numeric,
            context=context,
            block_id=_block_id(block),
            block_index=index,
        )
        if result.status == "indeterminate":
            return result
        numeric_hits.extend(result.hits)
    if numeric_hits:
        return MatchResult("matched", tuple(_deduplicate_hits(numeric_hits)))
    return MatchResult("no_match", reason="numeric condition was not satisfied")


def _as_patterns(patterns: str | Sequence[str]) -> list[str]:
    values = [patterns] if isinstance(patterns, str) else list(patterns)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("patterns must contain non-empty strings")
    return values


def _pattern_config(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"pattern": value, "kind": "keyword"}
    if not isinstance(value, Mapping):
        raise ValueError("text pattern entries must be strings or mappings")
    pattern = value.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("text pattern requires a non-empty pattern")
    return {**value, "pattern": pattern, "kind": str(value.get("kind") or "keyword").lower()}


def _resolve_threshold(
    config: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[Decimal | None, str | None]:
    if config.get("threshold") is not None:
        source = config["threshold"]
    elif config.get("threshold_ref"):
        ref = str(config["threshold_ref"])
        if ref not in context:
            return None, f"threshold_ref {ref!r} is missing"
        source = context[ref]
    else:
        return None, "numeric threshold or threshold_ref is required"
    try:
        return Decimal(str(source).replace(",", "").replace("，", "")), None
    except (InvalidOperation, ValueError):
        return None, f"threshold {source!r} is not numeric"


def _canonical_unit(unit: Any) -> str:
    value = str(unit or "").strip().lower()
    for canonical, aliases in _UNIT_ALIASES.items():
        if value in {alias.lower() for alias in aliases}:
            return canonical
    return value


def _unit_matches(requested: str, actual: str, raw: str) -> bool:
    if actual:
        return requested == actual
    # A bare number is accepted only when the configured field provides enough
    # semantic context.  Currency/duration matchers must see an explicit unit.
    return not raw and requested not in _UNIT_ALIASES


def _field_is_near(text: str, start: int, end: int, field: str) -> bool:
    # DSL field names are often identifiers (liability_amount), not literal
    # document labels.  Only enforce a proximity hint when it actually occurs.
    normalized_field = field.replace("_", " ")
    if field.lower() not in text.lower() and normalized_field.lower() not in text.lower():
        return True
    nearby = text[max(0, start - 48) : min(len(text), end + 48)].lower()
    return field.lower() in nearby or normalized_field.lower() in nearby


def _section_parts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(part) for part in value if part is not None]
    return []


def _block_id(block: Mapping[str, Any]) -> str | None:
    value = block.get("block_id")
    return str(value) if value is not None else None


def _deduplicate_hits(hits: Sequence[MatchHit]) -> list[MatchHit]:
    seen: set[tuple[Any, ...]] = set()
    result: list[MatchHit] = []
    for hit in sorted(
        hits,
        key=lambda item: (item.block_index, item.start, item.end, item.matcher),
    ):
        key = (hit.block_index, hit.start, hit.end, hit.quote, hit.matcher)
        if key not in seen:
            seen.add(key)
            result.append(hit)
    return result


# Readable aliases for callers that prefer noun-first matcher names.
keyword_match = match_keyword
regex_match = match_regex
scope_match = match_scope
numeric_match = match_numeric


__all__ = [
    "MatchHit",
    "MatchResult",
    "keyword_match",
    "match_keyword",
    "match_numeric",
    "match_regex",
    "match_rule",
    "match_scope",
    "numeric_match",
    "regex_match",
    "scope_match",
]
