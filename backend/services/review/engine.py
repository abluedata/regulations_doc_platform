"""Review engine orchestration: deterministic rules followed by LLM checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:  # pragma: no cover - pydantic is part of the backend stack
    BaseModel = object  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment]
    ValidationError = ValueError  # type: ignore[assignment]

from core.config import LLM_MODEL

from .anti_fp import false_positive_reason
from .evidence import locate_evidence, quote_sha256
from .matchers import MatchHit, MatchResult, match_rule
from .prompt import build_review_messages, prompt_template_hash


DEFAULT_TEMPERATURE = 0.2
DEFAULT_SEED = 20260815


class ReviewEngineError(RuntimeError):
    """Base class for review engine errors."""


class LLMUnavailableError(ReviewEngineError):
    """Raised when the configured LLM cannot be called."""


class LLMStructuredOutputError(ReviewEngineError):
    """Raised when structured LLM output cannot be parsed."""


class LLMClient(Protocol):
    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model: str,
        temperature: float,
        seed: int,
        response_format: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


class LLMIssue(BaseModel):  # type: ignore[misc]
    type: str
    text: str
    explanation: str = ""
    suggested_fix: str = ""
    para_index: int | None = None
    confidence: str | None = None


class LLMReviewResponse(BaseModel):  # type: ignore[misc]
    issues: list[LLMIssue] = Field(default_factory=list)  # type: ignore[misc]


@dataclass(frozen=True)
class ReviewVersionSnapshot:
    rule_version: str
    template_version: str
    llm_model: str
    temperature: float
    prompt_hash: str
    eval_set_hash: str
    seed: int
    provider_model: str | None = None
    usage: Mapping[str, Any] | None = None
    finish_reason: str | None = None

    @property
    def six_tuple(self) -> tuple[str, str, str, float, str, str]:
        return (
            self.rule_version,
            self.template_version,
            self.llm_model,
            self.temperature,
            self.prompt_hash,
            self.eval_set_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "template_version": self.template_version,
            "llm_model": self.llm_model,
            "temperature": self.temperature,
            "prompt_hash": self.prompt_hash,
            "eval_set_hash": self.eval_set_hash,
            "seed": self.seed,
            "provider_model": self.provider_model,
            "usage": dict(self.usage or {}),
            "finish_reason": self.finish_reason,
            "six_tuple": list(self.six_tuple),
        }


@dataclass(frozen=True)
class ReviewChunk:
    chunk_id: str
    start_index: int
    blocks: tuple[Mapping[str, Any], ...]


class ReviewEngine:
    """Run review rules with deterministic checks first, then LLM fallbacks."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        seed: int = DEFAULT_SEED,
        eval_set_hash: str | None = None,
        chunk_size: int = 32,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.llm_client = llm_client
        self.model = model or LLM_MODEL
        self.temperature = temperature
        self.seed = seed
        self.eval_set_hash = eval_set_hash or _default_eval_set_hash()
        self.chunk_size = chunk_size

    def analyze_document(
        self,
        ir: Mapping[str, Any],
        rules: Sequence[Mapping[str, Any]],
        *,
        allow_llm: bool = True,
    ) -> dict[str, Any]:
        blocks = tuple(ir.get("blocks") or ())
        rule_list = [dict(rule) for rule in rules]
        findings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        llm_rules: list[Mapping[str, Any]] = []
        provider: dict[str, Any] = {}

        for rule in rule_list:
            matcher = _rule_matcher(rule)
            result = _run_matcher(blocks, matcher)
            if result.matched:
                for hit in result.hits:
                    if false_positive_reason(hit.quote):
                        continue
                    findings.append(_finding_from_hit(ir, rule, hit))
                continue
            if _llm_fallback_enabled(rule):
                llm_rules.append(rule)
            elif result.status == "indeterminate":
                errors.append(
                    {
                        "code": "deterministic_indeterminate",
                        "rule_id": _rule_id(rule),
                        "message": result.reason or "deterministic matcher was indeterminate",
                    }
                )

        if llm_rules and allow_llm:
            if self.llm_client is None:
                raise LLMUnavailableError("LLM client is not configured")
            for chunk in self.iter_chunks(ir):
                for rule in llm_rules:
                    current_findings, current_errors, current_provider = self._run_llm_rule(
                        ir,
                        chunk,
                        rule,
                    )
                    findings.extend(current_findings)
                    errors.extend(current_errors)
                    provider.update({key: value for key, value in current_provider.items() if value is not None})
        elif llm_rules and not allow_llm:
            for rule in llm_rules:
                errors.append(
                    {
                        "code": "llm_skipped",
                        "rule_id": _rule_id(rule),
                        "message": "LLM fallback was skipped because degraded mode is active",
                    }
                )

        snapshot = self._snapshot(rule_list, provider)
        return {
            "status": "completed" if allow_llm else "complete_degraded",
            "document_id": ir.get("doc_id"),
            "document_version_id": _document_version_id(ir),
            "findings": findings,
            "errors": errors,
            "snapshot": snapshot.to_dict(),
        }

    def iter_chunks(self, ir: Mapping[str, Any]) -> list[ReviewChunk]:
        blocks = tuple(ir.get("blocks") or ())
        doc_id = str(ir.get("doc_id") or "doc")
        chunks: list[ReviewChunk] = []
        for start in range(0, len(blocks), self.chunk_size):
            index = len(chunks)
            chunks.append(
                ReviewChunk(
                    chunk_id=f"{doc_id}:{index:04d}",
                    start_index=start,
                    blocks=blocks[start : start + self.chunk_size],
                )
            )
        return chunks or [ReviewChunk(chunk_id=f"{doc_id}:0000", start_index=0, blocks=())]

    def _run_llm_rule(
        self,
        ir: Mapping[str, Any],
        chunk: ReviewChunk,
        rule: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        provider: dict[str, Any] = {}
        for attempt in range(2):
            messages = build_review_messages(
                chunk_id=chunk.chunk_id,
                blocks=chunk.blocks,
                rules=[rule],
                retry=attempt > 0,
            )
            response = self._complete_llm(messages)
            provider = response["provider"]
            try:
                parsed = _parse_llm_response(response["content"])
                return (
                    [
                        finding
                        for issue in parsed.issues
                        if (finding := self._finding_from_llm_issue(ir, chunk, rule, issue)) is not None
                    ],
                    errors,
                    provider,
                )
            except LLMStructuredOutputError as exc:
                if attempt == 0:
                    continue
                errors.append(
                    {
                        "code": "llm_parse_error",
                        "chunk_id": chunk.chunk_id,
                        "rule_id": _rule_id(rule),
                        "message": str(exc),
                        "retryable": True,
                    }
                )
        return [], errors, provider

    def _complete_llm(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        assert self.llm_client is not None
        try:
            if hasattr(self.llm_client, "complete"):
                raw = self.llm_client.complete(
                    messages=messages,
                    model=self.model,
                    temperature=self.temperature,
                    seed=self.seed,
                    response_format={"type": "json_object"},
                )
            elif callable(self.llm_client):
                raw = self.llm_client(
                    messages=messages,
                    model=self.model,
                    temperature=self.temperature,
                    seed=self.seed,
                    response_format={"type": "json_object"},
                )
            else:
                raise TypeError("LLM client must expose complete(...) or be callable")
        except LLMUnavailableError:
            raise
        except Exception as exc:  # provider/network failures degrade at job-runner boundary
            raise LLMUnavailableError(str(exc)) from exc
        return _extract_llm_content(raw)

    def _finding_from_llm_issue(
        self,
        ir: Mapping[str, Any],
        chunk: ReviewChunk,
        rule: Mapping[str, Any],
        issue: LLMIssue,
    ) -> dict[str, Any] | None:
        quote = str(issue.text or "").strip()
        if not quote or false_positive_reason(quote):
            return None
        block_index = _resolve_issue_block_index(chunk, issue)
        if block_index is None:
            block_index = _find_quote_block_index(ir.get("blocks") or [], quote)
        block = (ir.get("blocks") or [{}])[block_index] if block_index is not None else {}
        start = str(block.get("text") or "").find(quote)
        if start < 0:
            start = None
            end = None
        else:
            end = start + len(quote)
        evidence = locate_evidence(
            ir,
            quote,
            block_index=block_index,
            start=start,
            end=end,
            document_version_id=_document_version_id(ir),
        )
        return _base_finding(
            ir,
            rule,
            quote=quote,
            confidence=issue.confidence or "llm_yes",
            explanation=issue.explanation,
            suggested_fix=issue.suggested_fix,
            block_id=block.get("block_id"),
            para_index=block_index,
            chunk_id=chunk.chunk_id,
            evidence=evidence,
        )

    def _snapshot(self, rules: Sequence[Mapping[str, Any]], provider: Mapping[str, Any]) -> ReviewVersionSnapshot:
        return ReviewVersionSnapshot(
            rule_version=_combined_version(rules, "rule_version"),
            template_version=_combined_version(rules, "template_version"),
            llm_model=self.model,
            temperature=self.temperature,
            prompt_hash=prompt_template_hash(rules),
            eval_set_hash=self.eval_set_hash,
            seed=self.seed,
            provider_model=provider.get("provider_model"),
            usage=provider.get("usage"),
            finish_reason=provider.get("finish_reason"),
        )


def _run_matcher(blocks: Sequence[Mapping[str, Any]], matcher: Mapping[str, Any] | None) -> MatchResult:
    if not matcher:
        return MatchResult("indeterminate", reason="rule has no deterministic matcher")
    return match_rule(blocks, matcher)


def _finding_from_hit(ir: Mapping[str, Any], rule: Mapping[str, Any], hit: MatchHit) -> dict[str, Any]:
    evidence = locate_evidence(
        ir,
        hit.quote,
        block_index=hit.block_index,
        block_id=hit.block_id,
        start=hit.start,
        end=hit.end,
        document_version_id=_document_version_id(ir),
    )
    return _base_finding(
        ir,
        rule,
        quote=hit.quote,
        confidence="rule_deterministic",
        explanation=str(rule.get("description") or _definition(rule).get("description") or ""),
        suggested_fix=str(rule.get("suggested_fix") or _definition(rule).get("suggested_fix") or ""),
        block_id=hit.block_id,
        para_index=hit.block_index,
        chunk_id=_chunk_id_for_hit(ir, hit),
        evidence=evidence,
    )


def _base_finding(
    ir: Mapping[str, Any],
    rule: Mapping[str, Any],
    *,
    quote: str,
    confidence: str,
    explanation: str,
    suggested_fix: str,
    block_id: Any,
    para_index: int | None,
    chunk_id: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = str(ir.get("doc_id") or "")
    version_id = _document_version_id(ir)
    rule_id = _rule_id(rule)
    finding_id = _stable_finding_id(document_id, version_id, rule_id, quote, block_id)
    return {
        "finding_id": finding_id,
        "document_id": document_id,
        "document_version_id": version_id,
        "rule_id": rule_id,
        "rule_version": rule.get("rule_version") or _definition(rule).get("rule_version"),
        "template_version": rule.get("template_version") or _definition(rule).get("template_version"),
        "severity": rule.get("risk_level") or rule.get("severity") or "medium",
        "confidence": confidence,
        "quote": quote,
        "quote_hash": quote_sha256(quote),
        "explanation": explanation,
        "suggested_fix": suggested_fix,
        "block_id": block_id,
        "para_index": para_index,
        "chunk_id": chunk_id,
        "evidence": dict(evidence),
    }


def _parse_llm_response(content: Any) -> LLMReviewResponse:
    try:
        if isinstance(content, str):
            if hasattr(LLMReviewResponse, "model_validate_json"):
                return LLMReviewResponse.model_validate_json(content)  # type: ignore[attr-defined]
            return LLMReviewResponse.parse_raw(content)  # type: ignore[attr-defined]
        if hasattr(LLMReviewResponse, "model_validate"):
            return LLMReviewResponse.model_validate(content)  # type: ignore[attr-defined]
        return LLMReviewResponse.parse_obj(content)  # type: ignore[attr-defined]
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise LLMStructuredOutputError(f"invalid structured LLM output: {exc}") from exc


def _extract_llm_content(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"content": raw, "provider": {}}
    if not isinstance(raw, Mapping):
        content = getattr(raw, "content", None)
        return {"content": content if content is not None else str(raw), "provider": {}}

    content: Any = raw.get("content")
    finish_reason = raw.get("finish_reason")
    choices = raw.get("choices")
    if content is None and isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, Mapping):
            finish_reason = finish_reason or choice.get("finish_reason")
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
            elif isinstance(choice.get("delta"), Mapping):
                content = choice["delta"].get("content")
    provider = {
        "provider_model": raw.get("model"),
        "usage": raw.get("usage"),
        "finish_reason": finish_reason,
    }
    return {"content": content if content is not None else "", "provider": provider}


def _resolve_issue_block_index(chunk: ReviewChunk, issue: LLMIssue) -> int | None:
    if issue.para_index is None:
        return None
    relative = int(issue.para_index)
    if 0 <= relative < len(chunk.blocks):
        return chunk.start_index + relative
    if relative >= chunk.start_index:
        return relative
    return None


def _find_quote_block_index(blocks: Sequence[Mapping[str, Any]], quote: str) -> int | None:
    for index, block in enumerate(blocks):
        if quote in str(block.get("text") or ""):
            return index
    return None


def _rule_matcher(rule: Mapping[str, Any]) -> Mapping[str, Any] | None:
    matcher = rule.get("matcher")
    if isinstance(matcher, Mapping):
        return matcher
    definition = _definition(rule)
    matcher = definition.get("matcher")
    if isinstance(matcher, Mapping):
        return matcher
    return None


def _llm_fallback_enabled(rule: Mapping[str, Any]) -> bool:
    value = rule.get("llm_fallback")
    if value is not None:
        return bool(value)
    severity = str(rule.get("risk_level") or rule.get("severity") or "").lower()
    return severity in {"high", "critical", "p0"}


def _rule_id(rule: Mapping[str, Any]) -> str:
    return str(rule.get("rule_id") or rule.get("id") or rule.get("name") or "unknown_rule")


def _definition(rule: Mapping[str, Any]) -> Mapping[str, Any]:
    value = rule.get("definition_json") or rule.get("definition") or {}
    return value if isinstance(value, Mapping) else {}


def _document_version_id(ir: Mapping[str, Any]) -> str:
    return str(ir.get("document_version_id") or ir.get("version_id") or "")


def _chunk_id_for_hit(ir: Mapping[str, Any], hit: MatchHit) -> str:
    doc_id = str(ir.get("doc_id") or "doc")
    return f"{doc_id}:{hit.block_index // 32:04d}"


def _stable_finding_id(document_id: str, version_id: str, rule_id: str, quote: str, block_id: Any) -> str:
    payload = json.dumps(
        {
            "document_id": document_id,
            "version_id": version_id,
            "rule_id": rule_id,
            "quote_hash": quote_sha256(quote),
            "block_id": block_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _combined_version(rules: Sequence[Mapping[str, Any]], field: str) -> str:
    values = [
        {
            "rule_id": _rule_id(rule),
            "version": rule.get(field) or _definition(rule).get(field) or "unversioned",
        }
        for rule in rules
    ]
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_eval_set_hash() -> str:
    manifest = Path(__file__).resolve().parents[2] / "eval" / "gold" / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return str(payload.get("dataset_sha256") or "")
    except (OSError, json.JSONDecodeError):
        return ""


__all__ = [
    "DEFAULT_SEED",
    "DEFAULT_TEMPERATURE",
    "LLMStructuredOutputError",
    "LLMUnavailableError",
    "ReviewChunk",
    "ReviewEngine",
    "ReviewEngineError",
    "ReviewVersionSnapshot",
]
