"""Associate predicted review issues with gold annotations.

The evaluator treats a finding as correct only when it matches the same
document, rule, severity, and document type. Text similarity is used only to
choose among multiple candidates for the same stratification key.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


TEXT_FIELDS = ("text", "quote", "evidence_text", "matched_text", "snippet")


def _first_text(record: Mapping[str, Any], fields: Sequence[str] = TEXT_FIELDS) -> str:
    for field in fields:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    evidence = record.get("evidence")
    if isinstance(evidence, Mapping):
        for field in ("quote", "text", "evidence_text"):
            value = evidence.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _clean_text(value: str) -> str:
    return "".join(value.lower().split())


def text_similarity(left: str, right: str) -> float:
    """Return a deterministic 0..1 similarity for short legal snippets."""

    left_clean = _clean_text(left)
    right_clean = _clean_text(right)
    if not left_clean and not right_clean:
        return 1.0
    if not left_clean or not right_clean:
        return 0.0
    if left_clean == right_clean:
        return 1.0
    if left_clean in right_clean or right_clean in left_clean:
        # 子串包含：命中文本确实是另一侧文本的一部分。
        # 对“关键词命中 vs 风险描述”的比对，纯长度比(3/17≈0.18)会
        # 把完全正确的关联误判为不匹配，因此子串包含给一个稳定的高基准。
        shorter = min(len(left_clean), len(right_clean))
        longer = max(len(left_clean), len(right_clean))
        return max(0.8, shorter / longer)
    return SequenceMatcher(None, left_clean, right_clean).ratio()


@dataclass(frozen=True)
class Issue:
    doc_id: str
    rule_id: str
    severity: str
    doc_type: str
    issue_id: str = ""
    text: str = ""
    confidence: float | None = None
    confidence_label: str = ""
    raw: Mapping[str, Any] | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.doc_id, self.rule_id, self.severity, self.doc_type)

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any] | "Issue",
        doc_type_by_doc: Mapping[str, str] | None = None,
    ) -> "Issue":
        if isinstance(record, Issue):
            return record
        doc_id = _as_str(record.get("doc_id") or record.get("document_id"))
        rule_id = _as_str(record.get("rule_id") or record.get("type") or record.get("rule"))
        severity = _as_str(record.get("severity"), "unknown").lower()
        doc_type = _as_str(record.get("doc_type") or record.get("document_type"))
        if not doc_type and doc_type_by_doc:
            doc_type = doc_type_by_doc.get(doc_id, "")
        confidence = record.get("confidence")
        try:
            parsed_confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            parsed_confidence = None
        return cls(
            doc_id=doc_id,
            rule_id=rule_id,
            severity=severity,
            doc_type=doc_type or "unknown",
            issue_id=_as_str(record.get("issue_id") or record.get("id")),
            text=_first_text(record),
            confidence=parsed_confidence,
            confidence_label=_as_str(record.get("confidence_label") or record.get("confidence_bucket")),
            raw=record,
        )


@dataclass(frozen=True)
class IssueMatch:
    gold: Issue
    prediction: Issue
    score: float


@dataclass(frozen=True)
class AssociationResult:
    matches: tuple[IssueMatch, ...]
    false_positives: tuple[Issue, ...]
    false_negatives: tuple[Issue, ...]

    @property
    def true_positive_count(self) -> int:
        return len(self.matches)

    @property
    def false_positive_count(self) -> int:
        return len(self.false_positives)

    @property
    def false_negative_count(self) -> int:
        return len(self.false_negatives)


def coerce_issues(
    records: Iterable[Mapping[str, Any] | Issue],
    doc_type_by_doc: Mapping[str, str] | None = None,
) -> list[Issue]:
    return [Issue.from_record(record, doc_type_by_doc=doc_type_by_doc) for record in records]


def _candidate_score(gold: Issue, prediction: Issue) -> float:
    if gold.issue_id and prediction.issue_id and gold.issue_id == prediction.issue_id:
        return 1.0
    if gold.text and prediction.text:
        return text_similarity(gold.text, prediction.text)
    return 1.0


def associate_issues(
    gold_records: Iterable[Mapping[str, Any] | Issue],
    prediction_records: Iterable[Mapping[str, Any] | Issue],
    *,
    min_text_similarity: float = 0.55,
) -> AssociationResult:
    """Greedily associate predictions to gold issues.

    Severity or document-type mismatches intentionally do not match. They become
    one false positive in the predicted bucket and one false negative in the gold
    bucket so the per-rule matrix shows the regression clearly.
    """

    gold = coerce_issues(gold_records)
    doc_type_by_doc = {issue.doc_id: issue.doc_type for issue in gold if issue.doc_type}
    predictions = coerce_issues(prediction_records, doc_type_by_doc=doc_type_by_doc)

    candidates: list[tuple[float, int, int]] = []
    for gold_index, gold_issue in enumerate(gold):
        for pred_index, pred_issue in enumerate(predictions):
            if gold_issue.key != pred_issue.key:
                continue
            score = _candidate_score(gold_issue, pred_issue)
            if score >= min_text_similarity:
                candidates.append((score, gold_index, pred_index))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    matched_gold: set[int] = set()
    matched_predictions: set[int] = set()
    matches: list[IssueMatch] = []
    for score, gold_index, pred_index in candidates:
        if gold_index in matched_gold or pred_index in matched_predictions:
            continue
        matched_gold.add(gold_index)
        matched_predictions.add(pred_index)
        matches.append(IssueMatch(gold=gold[gold_index], prediction=predictions[pred_index], score=score))

    false_positives = tuple(
        prediction for index, prediction in enumerate(predictions) if index not in matched_predictions
    )
    false_negatives = tuple(issue for index, issue in enumerate(gold) if index not in matched_gold)
    return AssociationResult(tuple(matches), false_positives, false_negatives)


def issue_to_dict(issue: Issue) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_id": issue.doc_id,
        "rule_id": issue.rule_id,
        "severity": issue.severity,
        "doc_type": issue.doc_type,
    }
    if issue.issue_id:
        payload["issue_id"] = issue.issue_id
    if issue.text:
        payload["text"] = issue.text
    if issue.confidence is not None:
        payload["confidence"] = issue.confidence
    if issue.confidence_label:
        payload["confidence_label"] = issue.confidence_label
    return payload

