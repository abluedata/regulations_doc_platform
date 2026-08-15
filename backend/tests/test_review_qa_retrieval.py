from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from services.review.qa_retrieval import (
    CitationValidationError,
    DocumentScope,
    build_citation,
    retrieve_evidence,
)
from services.search import search_document


class FakeEs:
    def __init__(self, hits):
        self.hits = hits
        self.bodies = []

    def search(self, *, index, body):
        self.bodies.append(body)
        return {"hits": {"hits": self.hits}}


def test_search_document_filters_bm25_and_knn_by_immutable_scope():
    hits = [
        {"_source": {"doc_id": "doc-a", "document_version_id": "v-a", "chunk_id": 1, "content": "付款三十日"}},
        {"_source": {"doc_id": "doc-b", "document_version_id": "v-b", "chunk_id": 2, "content": "污染结果"}},
    ]
    es = FakeEs(hits)
    with mock.patch("services.search.get_es", return_value=es), mock.patch(
        "services.search.get_embeddings", return_value=[[0.1, 0.2]]
    ):
        results = search_document("付款", scope=DocumentScope("doc-a", "v-a"), k=3)

    assert len(es.bodies) == 2
    serialized = json.dumps(es.bodies, ensure_ascii=False)
    assert "doc-a:v-a" in serialized
    assert [(item["doc_id"], item["document_version_id"]) for item in results] == [("doc-a", "v-a")]


def test_retrieve_evidence_reads_canonical_version_and_builds_exact_quote(tmp_path: Path):
    version = "a" * 64
    version_dir = tmp_path / "uploads" / "doc-a" / "versions" / version
    version_dir.mkdir(parents=True)
    ir = {
        "blocks": [{
            "block_id": "b1", "type": "paragraph", "text": "乙方应在收到发票之日起三十日内付款。",
            "section_path": ["付款"],
            "locator": {"kind": "pdf", "page_number": 6, "precision": "exact", "rects": []},
        }]
    }
    (version_dir / "ir.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    scope = DocumentScope("doc-a", version)

    with mock.patch("services.review.qa_retrieval.UPLOADS_DIR", tmp_path / "uploads"):
        candidates = retrieve_evidence("付款期限", scope, searcher=lambda *_args, **_kwargs: [])
        citation = build_citation(candidates[0], quote="三十日内付款")

    assert citation.quote == candidates[0].canonical_text[citation.quote_start:citation.quote_end]
    assert citation.locator["page_number"] == 6
    with pytest.raises(CitationValidationError):
        build_citation(candidates[0], quote="四十五日内付款")
