"""Deterministic document-review primitives."""

from .anti_fp import (
    ANTI_FALSE_POSITIVE_RULES,
    false_positive_reason,
    filter_false_positives,
    is_false_positive,
    partition_false_positives,
)
from .matchers import (
    MatchHit,
    MatchResult,
    match_keyword,
    match_numeric,
    match_regex,
    match_rule,
    match_scope,
)
from .engine import LLMUnavailableError, ReviewEngine, ReviewVersionSnapshot
from .evidence import bbox_to_quadpoints, locate_evidence, quote_sha256
from .job_runner import ChunkRuleTask, ReviewJobRunner, TransientReviewError
from .store import ReviewStore
from .prompt import build_review_messages, prompt_hash, prompt_template_hash

__all__ = [
    "ANTI_FALSE_POSITIVE_RULES",
    "MatchHit",
    "MatchResult",
    "ReviewEngine",
    "ReviewJobRunner",
    "ReviewStore",
    "ReviewVersionSnapshot",
    "ChunkRuleTask",
    "LLMUnavailableError",
    "TransientReviewError",
    "bbox_to_quadpoints",
    "build_review_messages",
    "false_positive_reason",
    "filter_false_positives",
    "is_false_positive",
    "locate_evidence",
    "match_keyword",
    "match_numeric",
    "match_regex",
    "match_rule",
    "match_scope",
    "partition_false_positives",
    "prompt_hash",
    "prompt_template_hash",
    "quote_sha256",
]
