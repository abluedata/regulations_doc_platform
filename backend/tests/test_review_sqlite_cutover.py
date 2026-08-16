from pathlib import Path

from services.review.assistant import ReviewAssistant
from services.review.qa_answer import GroundedAnswer
from services.review.store import ReviewStore


def test_second_store_reads_prior_records_without_json_files(tmp_path: Path):
    first = ReviewStore(tmp_path / "platform.db")
    job = first.create_analysis_job({"status": "queued", "documents": []})
    conversation = first.create_conversation("job-1", {"id": "membership-1", "document_id": "doc-1", "document_version_id": "v1"})

    second = ReviewStore(tmp_path / "platform.db")
    assert second.get("jobs", job["id"])["id"] == job["id"]
    assert second.get("conversations", conversation["id"])["id"] == conversation["id"]
    assert not list(tmp_path.rglob("*.json"))


def test_duplicate_request_is_idempotent_and_meta_contains_message_ids(tmp_path: Path):
    store = ReviewStore(tmp_path / "platform.db")
    conversation = store.create_conversation("job-1", {"id": "membership-1", "document_id": "doc-1", "document_version_id": "v1"})

    def answerer(*args, **kwargs):
        return GroundedAnswer(answer="已回答", refused=False, refusal_code=None, citations=[])

    assistant = ReviewAssistant(store, answerer=answerer)
    first = list(assistant.stream_answer(conversation["id"], {"request_id": "request-1", "message": "问题"}))
    second = list(assistant.stream_answer(conversation["id"], {"request_id": "request-1", "message": "问题"}))
    saved = store.require("conversations", conversation["id"])

    assert len(saved["messages"]) == 2
    assert '"user_message_id"' in first[0] and '"assistant_message_id"' in first[0]
    assert second[-1].startswith("event: done")

