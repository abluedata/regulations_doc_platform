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


def test_retrieve_evidence_falls_back_to_current_version_for_legacy_alias(tmp_path: Path):
    """旧成员把文档 ID 当版本 ID（legacy 别名）时，检索应回退到当前版本 IR。

    复现：前端入批时 document_version_id 使用了上传接口返回的文档 ID，而真实
    不可变版本目录是另一个哈希；问答助手因此检索失败（FileNotFoundError）。
    """
    version = "b" * 64
    uploads = tmp_path / "uploads"
    version_dir = uploads / "doc-legacy" / "versions" / version
    version_dir.mkdir(parents=True)
    ir = {
        "blocks": [{
            "block_id": "b1", "type": "paragraph", "text": "乙方应在收到发票之日起三十日内付款。",
            "section_path": ["付款"],
            "locator": {"kind": "pdf", "page_number": 6, "precision": "exact", "rects": []},
        }]
    }
    (version_dir / "ir.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    (uploads / "doc-legacy" / "meta.json").write_text(
        json.dumps({"id": "doc-legacy", "status": "ready", "current_version_id": version}, ensure_ascii=False),
        encoding="utf-8",
    )
    # legacy 别名：版本号 == 文档 ID（非 64 位哈希）
    legacy_scope = DocumentScope("doc-legacy", "doc-legacy")

    with mock.patch("services.review.qa_retrieval.UPLOADS_DIR", uploads):
        candidates = retrieve_evidence("付款期限", legacy_scope, searcher=lambda *_args, **_kwargs: [])

    assert len(candidates) == 1
    # 引用必须携带真实版本号而不是 legacy 别名
    assert candidates[0].scope.document_version_id == version
    assert build_citation(candidates[0]).document_version_id == version


def test_answer_document_embeds_history_and_finding_in_prompt(tmp_path: Path):
    """多轮历史与选中发现必须进入 LLM 提示词：问答助手上下文能力。"""
    from services.review.qa_answer import answer_document

    version = "c" * 64
    uploads = tmp_path / "uploads"
    version_dir = uploads / "doc-ctx" / "versions" / version
    version_dir.mkdir(parents=True)
    ir = {
        "blocks": [{
            "block_id": "b1", "type": "paragraph", "text": "投标保证金应在投标截止前缴纳。",
            "section_path": ["投标"],
            "locator": {"kind": "pdf", "page_number": 3, "precision": "exact", "rects": []},
        }]
    }
    (version_dir / "ir.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    captured = {}

    def fake_llm(_question, _candidates, **kwargs):
        captured.update(kwargs)
        return {"answer": "保证金须在截止前缴纳。", "citation_refs": ["c1"], "refused": False}

    with mock.patch("services.review.qa_retrieval.UPLOADS_DIR", uploads):
        result = answer_document(
            "投标保证金何时缴纳？",
            DocumentScope("doc-ctx", version),
            "tender.pdf",
            history=[{"role": "user", "content": "有哪些风险？"}, {"role": "assistant", "content": "共两项。"}],
            finding={"title": "投标保证金条款", "quote": "投标保证金", "explanation": "缴纳时限审查"},
            llm=fake_llm,
        )

    assert result.answer == "保证金须在截止前缴纳。"
    assert captured["history"][0]["content"] == "有哪些风险？"
    assert captured["finding"]["title"] == "投标保证金条款"


def test_evidence_snippet_centers_on_query_match_in_long_table():
    from services.review.qa_retrieval import evidence_snippet

    text = "| 序号 | 项目 | 金额 |\n| --- | --- | --- |\n" + "| 1 | 普通项 | 100元 |\n" * 40 + "| 41 | 最高投标限价 | 5220000元 |\n" + "| 42 | 其他 | 200元 |\n"
    snippet = evidence_snippet(text, "最高投标限价是多少")
    assert "最高投标限价" in snippet
    assert "5220000元" in snippet
    assert len(snippet) < len(text)
    # 无关短文本：直接返回原文
    assert evidence_snippet("短文本", "最高投标限价") == "短文本"


def test_retrieve_evidence_falls_back_when_es_hits_are_low_score_noise(tmp_path: Path):
    """ES 返回低分噪音命中（空白块/目录块）时，应退回词汇重合排名且过滤无信息块。"""
    version = "d" * 64
    uploads = tmp_path / "uploads"
    version_dir = uploads / "doc-noise" / "versions" / version
    version_dir.mkdir(parents=True)
    ir = {
        "blocks": [
            {
                "block_id": "noise",
                "type": "paragraph",
                "text": " \n \n ",
                "locator": {"kind": "pdf", "page_number": 1, "precision": "page", "rects": []},
            },
            {
                "block_id": "good",
                "type": "paragraph",
                "text": "服务期限：36个月。",
                "locator": {"kind": "pdf", "page_number": 2, "precision": "exact", "rects": []},
            },
        ]
    }
    (version_dir / "ir.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    scope = DocumentScope("doc-noise", version)

    with mock.patch("services.review.qa_retrieval.UPLOADS_DIR", uploads):
        candidates = retrieve_evidence(
            "服务期限是多久",
            scope,
            searcher=lambda *_args, **_kwargs: [{"block_id": "noise", "chunk_id": 0, "score": 0.01}],
        )

    assert len(candidates) >= 1
    assert all(candidate.block_id != "noise" for candidate in candidates)
    assert "36个月" in candidates[0].canonical_text
