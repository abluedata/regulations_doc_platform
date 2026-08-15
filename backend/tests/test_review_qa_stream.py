from __future__ import annotations

import json

import pytest

from services.review.assistant import ReviewAssistant
from services.review.qa_answer import GroundedAnswer
from services.review.store import ReviewStore


def parse_events(chunks):
    events = []
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        events.append((lines[0].split(":", 1)[1].strip(), json.loads(lines[1].split(":", 1)[1].strip())))
    return events


@pytest.fixture
def conversation(tmp_path):
    store = ReviewStore(tmp_path)
    convo = store.create_conversation("job-1", {
        "id": "membership-1", "document_id": "doc-1", "document_version_id": "v1", "filename": "合同.pdf",
    })
    return store, convo


@pytest.mark.parametrize("failure", [None, RuntimeError("provider failed")])
def test_stream_has_exactly_one_terminal_event(conversation, failure):
    store, convo = conversation

    def answerer(question, scope, filename):
        if failure:
            raise failure
        return GroundedAnswer(answer="付款期限为三十日。", citations=[{
            "citation_id": "c1", "document_id": "doc-1", "document_version_id": "v1",
            "filename": filename, "block_id": "b1", "quote": "三十日内付款", "quote_start": 0,
            "quote_end": 7, "locator": {"kind": "pdf", "page_number": 1},
        }])

    assistant = ReviewAssistant(store, answerer=answerer)
    events = parse_events(assistant.stream_answer(convo["id"], {"request_id": "r1", "message": "付款期限？"}))
    terminals = [event for event, _ in events if event in {"done", "error"}]
    assert len(terminals) == 1
    assert events[-1][0] in {"done", "error"}


def test_refusal_uses_done_and_has_no_citations(conversation):
    store, convo = conversation
    assistant = ReviewAssistant(store, answerer=lambda *_args: GroundedAnswer.refusal("no_evidence"))
    events = parse_events(assistant.stream_answer(convo["id"], {"request_id": "r2", "message": "外部收入？"}))
    done = events[-1]
    assert done[0] == "done"
    assert done[1]["refused"] is True
    assert done[1]["citations"] == []


def test_completed_request_is_idempotently_replayed(conversation):
    store, convo = conversation
    calls = 0

    def answerer(*_args):
        nonlocal calls
        calls += 1
        return GroundedAnswer.refusal("no_evidence")

    assistant = ReviewAssistant(store, answerer=answerer)
    first = assistant.stream_answer(convo["id"], {"request_id": "same", "message": "问题"})
    second = assistant.stream_answer(convo["id"], {"request_id": "same", "message": "问题"})
    assert calls == 1
    assert parse_events(first)[-1] == parse_events(second)[-1]
