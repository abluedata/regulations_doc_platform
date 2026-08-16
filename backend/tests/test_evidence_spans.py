"""Tests for evidence spans (PDF raw coordinates) and the original file endpoint."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.knowledge import document_store as store
from services.common import evidence_spans as evidence

VALID_VERSION_ID = "a" * 64
OTHER_VERSION_ID = "b" * 64


class EvidenceSpansTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name)
        self.uploads_patch = mock.patch.object(
            store, "UPLOADS_DIR", self.data_root / "uploads"
        )
        self.index_patch = mock.patch.object(
            store, "INDEX_FILE", self.data_root / "docs_index.json"
        )
        self.uploads_patch.start()
        self.index_patch.start()
        evidence.clear_ensure_cache()

    def tearDown(self) -> None:
        evidence.clear_ensure_cache()
        self.index_patch.stop()
        self.uploads_patch.stop()

    def _create_doc(
        self,
        doc_id: str = "doc-1",
        *,
        status: str = "ready",
        version_id: str = VALID_VERSION_ID,
        created_at: str = "2026-08-15 17:03:13",
        updated_at: str = "2026-08-15 17:05:22",
    ) -> None:
        directory = store.doc_dir(doc_id)
        directory.mkdir(parents=True)
        meta = {
            "id": doc_id,
            "filename": "tender.pdf",
            "stored_name": "original.pdf",
            "title": "tender",
            "ext": "pdf",
            "mime": "application/pdf",
            "status": status,
            "engine": "mineru:pipeline",
            "current_version_id": version_id,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        store.save_meta(meta)
        store.version_dir(doc_id, version_id).mkdir(parents=True, exist_ok=True)

    # ── spans_from_content_list ─────────────────────────────

    def test_spans_from_content_list_keeps_text_bbox_page(self):
        spans = evidence.spans_from_content_list(
            [
                {
                    "type": "text",
                    "text": "合同业绩要求",
                    "bbox": [115, 529, 877, 601],
                    "page_idx": 5,
                },
                {"type": "text", "text": "无坐标"},
                {
                    "type": "image",
                    "text": "bad bbox",
                    "bbox": [10, 20, 5, 40],
                    "page_idx": 0,
                },
                {
                    "type": "table",
                    "text": "page 从 1 开始",
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 1,
                },
            ],
            task_id="job-123",
            engine="mineru:pipeline",
        )
        self.assertEqual(spans["task_id"], "job-123")
        self.assertEqual(spans["engine"], "mineru:pipeline")
        self.assertEqual(len(spans["spans"]), 2)
        self.assertEqual(
            spans["spans"][0],
            {"text": "合同业绩要求", "bbox": [115.0, 529.0, 877.0, 601.0], "page": 6},
        )
        self.assertEqual(spans["spans"][1]["page"], 2)

    # ── find_span_for_quote ─────────────────────────────────

    def test_find_span_for_quote_containment_and_whitespace(self):
        spans = [
            {"text": "【3】业绩要求：……维护合同业绩2份……", "bbox": [0, 0, 100, 20], "page": 6},
            {"text": "投标人须为\n依法注册的独立法人", "bbox": [0, 30, 100, 50], "page": 2},
        ]
        self.assertEqual(
            evidence.find_span_for_quote(spans, "合同业绩")["page"], 6
        )
        # 换行折叠后匹配
        self.assertEqual(
            evidence.find_span_for_quote(spans, "依法注册的独立法人")["page"], 2
        )
        # 空白错位兜底
        self.assertEqual(
            evidence.find_span_for_quote(spans, "依法注册 的独立 法人")["page"], 2
        )
        self.assertIsNone(evidence.find_span_for_quote(spans, "不存在的引用"))
        self.assertIsNone(evidence.find_span_for_quote(spans, ""))

    def test_find_span_for_quote_prefers_expected_page_and_tightest_span(self):
        spans = [
            # 目录页整行（大框噪音）
            {"text": "第一章 公开招标..................投标保证金............", "bbox": [100, 100, 900, 900], "page": 2},
            # 正文页精确短 span
            {"text": "（4）投标保证金；", "bbox": [157, 297, 299, 315], "page": 20},
            # 正文页中等 span
            {"text": "3.4.1 投标保证金金额与递交方式详见前附表。", "bbox": [114, 466, 870, 504], "page": 20},
        ]
        # 无页码偏好：最短包含 span 优先（避免目录大框）
        self.assertEqual(evidence.find_span_for_quote(spans, "投标保证金")["page"], 20)
        # 指定页码：优先该页
        self.assertEqual(
            evidence.find_span_for_quote(spans, "投标保证金", page_number=20)["bbox"],
            [157, 297, 299, 315],
        )
        # 指定页码但该页无匹配 → 回退全局最精
        self.assertEqual(
            evidence.find_span_for_quote(spans, "投标保证金", page_number=3)["page"], 20
        )

    def test_refine_quote_bbox_narrows_to_character_level(self):
        class FakePage:
            width = 595.0
            height = 842.0

        class FakePdf:
            pages = [FakePage()]

        doc_id = "doc-refine"
        evidence._pdf_cache[doc_id] = FakePdf()
        evidence._pdf_cache_order.append(doc_id)
        text = "（4）投标保证金；"
        chars = []
        for index, char in enumerate(text):
            x0 = 93.0 + index * 18.0
            chars.append(
                {"text": char, "x0": x0, "x1": x0 + 17.0, "top": 253.1, "bottom": 263.6}
            )
        evidence._page_words_cache[("chars", doc_id, 1)] = chars
        try:
            result = evidence.refine_quote_bbox(doc_id, 1, "投标保证金")
        finally:
            evidence._pdf_cache.clear()
            evidence._pdf_cache_order.clear()
            evidence._page_words_cache.clear()
        self.assertIsNotNone(result)
        x0, y0, x1, y1 = result or [0, 0, 0, 0]
        # quote 在 text[3:8]，x 起点 93+3*18，终点 93+7*18+17
        self.assertAlmostEqual(x0, (93.0 + 3 * 18.0) / 595 * 1000, delta=2)
        self.assertAlmostEqual(x1, (93.0 + 7 * 18.0 + 17.0) / 595 * 1000, delta=2)
        self.assertAlmostEqual(y0, 253.1 / 842 * 1000, delta=2)
        self.assertAlmostEqual(y1, 263.6 / 842 * 1000, delta=2)

    def test_refine_quote_bbox_rejects_cross_line_inverted_box(self):
        """跨行匹配必须被拒绝：不能返回 x0 > x1 的倒置矩形。"""
        class FakePage:
            width = 595.0
            height = 842.0

        class FakePdf:
            pages = [FakePage()]

        doc_id = "doc-refine-xline"
        evidence._pdf_cache[doc_id] = FakePdf()
        evidence._pdf_cache_order.append(doc_id)
        # 第一行行尾 + 第二行行首，拼接后包含 quote，但不在同一行
        chars = [
            {"text": "投标保证", "x0": 700.0, "x1": 800.0, "top": 100.0, "bottom": 112.0},
            {"text": "金", "x0": 70.0, "x1": 90.0, "top": 120.0, "bottom": 132.0},
        ]
        evidence._page_words_cache[("chars", doc_id, 1)] = chars
        try:
            result = evidence.refine_quote_bbox(doc_id, 1, "投标保证金")
        finally:
            evidence._pdf_cache.clear()
            evidence._pdf_cache_order.clear()
            evidence._page_words_cache.clear()
        self.assertIsNone(result)

    def test_locate_quote_span_in_block_finds_correct_repeated_instance(self):
        spans = [
            {"text": "3.3.1 投标有效期", "bbox": [100, 100, 900, 120], "page": 20},
            {"text": "3.3.3 出现特殊情况需要延长投标有效期的……其投标保证金的有效期……", "bbox": [114, 682, 870, 704], "page": 20},
            {"text": "（4）投标保证金；", "bbox": [157, 297, 299, 315], "page": 20},
            {"text": "3.4.1 投标保证金金额与递交方式详见前附表。", "bbox": [114, 466, 870, 504], "page": 20},
        ]
        block_text = "3.3.3 出现特殊情况需要延长投标有效期的……其投标保证金的有效期……"
        span = evidence.locate_quote_span_in_block(spans, block_text, "投标保证金")
        self.assertIsNotNone(span)
        self.assertEqual(span["bbox"], [114, 682, 870, 704])
        # 另一 block 内的重复文本 → 定位到另一实例
        span2 = evidence.locate_quote_span_in_block(spans, "3.4.1 投标保证金金额与递交方式详见前附表。", "投标保证金")
        self.assertEqual(span2["bbox"], [114, 466, 870, 504])
        # 找不到时返回 None
        self.assertIsNone(evidence.locate_quote_span_in_block(spans, "完全无关的文本", "投标保证金"))

    def test_enrich_anchor_refines_long_span_with_pdfplumber(self):
        """span 远长于 quote 时，富化应裁剪到字符级 bbox。"""
        doc_id = "doc-enrich-refine"
        finding = {
            "document_id": doc_id,
            "document_version_id": VALID_VERSION_ID,
            "quote": "投标保证金",
            "evidence_anchor": {
                "kind": "pdf",
                "document_id": doc_id,
                "document_version_id": VALID_VERSION_ID,
                "precision": "page",
                "page_number": 20,
                "coordinate_space": "normalized-1000-top-left",
                "rects": [],
            },
        }
        long_span = {
            "text": "3.4.1 投标保证金金额与递交方式详见前附表，其余要求以正文为准。",
            "bbox": [114, 466, 870, 504],
            "page": 20,
        }
        with mock.patch.object(
            evidence,
            "ensure_doc_evidence_spans",
            return_value={"spans": [long_span]},
        ), mock.patch.object(
            evidence,
            "refine_quote_bbox",
            return_value=[157.0, 297.0, 299.0, 315.0],
        ) as refine:
            enriched = evidence.enrich_evidence_anchor(finding)
        refine.assert_called_once_with(doc_id, 20, "投标保证金", span_bbox=[114.0, 466.0, 870.0, 504.0])
        self.assertEqual(
            enriched["evidence_anchor"]["rects"][0],
            {"page": 20, "x0": 157.0, "y0": 297.0, "x1": 299.0, "y1": 315.0, "space": "normalized-1000-top-left"},
        )

    # ── write / load ────────────────────────────────────────

    def test_write_and_load_roundtrip(self):
        self._create_doc()
        spans = evidence.spans_from_content_list(
            [{"type": "text", "text": "合同业绩", "bbox": [115, 529, 877, 601], "page_idx": 5}]
        )
        path = evidence.write_evidence_spans("doc-1", VALID_VERSION_ID, spans)
        self.assertTrue(path.is_file())
        loaded = evidence.load_evidence_spans("doc-1")
        self.assertEqual(loaded["spans"][0]["page"], 6)
        # 显式 version_id 不存在时回退 current_version_id
        self.assertEqual(
            evidence.load_evidence_spans("doc-1", version_id="not-a-version")["spans"][0]["page"],
            6,
        )
        self.assertIsNone(evidence.load_evidence_spans("missing-doc"))

    # ── backfill：时间窗 + 文本重叠匹配 mineru job ────────────

    def _fake_mineru_job(self, job_name: str, texts: list[str]) -> Path:
        root = self.data_root / "mineru_output"
        job_dir = root / job_name
        auto_dir = job_dir / "original" / "auto"
        auto_dir.mkdir(parents=True)
        items = []
        for idx, text in enumerate(texts):
            items.append(
                {"type": "text", "text": text, "bbox": [10, 20, 30, 40], "page_idx": idx}
            )
        content_list = auto_dir / "original_content_list.json"
        content_list.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        stamp = mock.patch.object(
            evidence, "mineru_output_root", return_value=root
        )
        self.addCleanup(stamp.stop)
        stamp.start()
        return job_dir

    def test_backfill_matches_job_by_window_and_overlap(self):
        self._create_doc()
        preview = store.doc_dir("doc-1") / "preview.md"
        preview.write_text("合同业绩要求 火电机组全厂起重设备维护 业绩要求中的关键信息页", encoding="utf-8")
        job_dir = self._fake_mineru_job(
            "job-a",
            ["合同业绩要求", "火电机组全厂起重设备维护", "业绩要求中的关键信息页"],
        )
        # 固定 content_list mtime 使其落在解析窗口内（不依赖真实时钟）
        from datetime import datetime

        window_stamp = datetime.strptime("2026-08-15 17:04:00", "%Y-%m-%d %H:%M:%S")

        def fake_mtime(path):
            return window_stamp

        with mock.patch.object(evidence, "_job_mtime", side_effect=fake_mtime):
            spans = evidence.backfill_doc_evidence_spans("doc-1")
        self.assertIsNotNone(spans)
        self.assertEqual(len(spans["spans"]), 3)
        self.assertEqual(spans["spans"][0]["page"], 1)
        # 落盘
        stored = evidence.evidence_spans_path("doc-1", VALID_VERSION_ID)
        self.assertTrue(stored.is_file())
        # 幂等：再次 backfill 直接读文件
        evidence.clear_ensure_cache()
        self.assertEqual(
            evidence.backfill_doc_evidence_spans("doc-1")["spans"][0]["text"],
            "合同业绩要求",
        )

    def test_backfill_skips_job_outside_window(self):
        self._create_doc()
        preview = store.doc_dir("doc-1") / "preview.md"
        preview.write_text("合同业绩要求", encoding="utf-8")
        self._fake_mineru_job("job-old", ["合同业绩要求"])
        from datetime import datetime

        outside = datetime.strptime("2026-08-14 10:00:00", "%Y-%m-%d %H:%M:%S")
        with mock.patch.object(evidence, "_job_mtime", return_value=outside):
            self.assertIsNone(evidence.backfill_doc_evidence_spans("doc-1"))
        path = evidence.evidence_spans_path("doc-1", VALID_VERSION_ID)
        self.assertIsNotNone(path)
        self.assertFalse(path.exists())


    def test_backfill_ir_pages_matches_block_prefix(self):
        self._create_doc()
        version_path = store.version_dir("doc-1", VALID_VERSION_ID)
        spans = evidence.spans_from_content_list(
            [
                {
                    "type": "text",
                    "text": "【3】业绩要求：投标人须至少具有火电机组全厂起重设备维护合同业绩2份",
                    "bbox": [115, 529, 877, 601],
                    "page_idx": 5,
                },
                {
                    "type": "text",
                    "text": "招标公告",
                    "bbox": [305, 319, 691, 377],
                    "page_idx": 0,
                },
            ]
        )
        (version_path / "evidence_spans.json").write_text(
            json.dumps(spans, ensure_ascii=False), encoding="utf-8"
        )
        ir = {
            "blocks": [
                {"block_id": "b1", "type": "heading", "text": "招标公告", "page_start": None, "page_end": None},
                {"block_id": "b2", "type": "paragraph", "text": "【3】业绩要求：投标人须至少具有火电机组全厂起重设备维护合同业绩2份", "page_start": None, "page_end": None},
                {"block_id": "b3", "type": "paragraph", "text": "无法匹配的文本", "page_start": None, "page_end": None},
            ]
        }
        (version_path / "ir.json").write_text(
            json.dumps(ir, ensure_ascii=False), encoding="utf-8"
        )
        changed = evidence.backfill_ir_pages("doc-1")
        self.assertEqual(changed, 2)
        updated = json.loads(
            (version_path / "ir.json").read_text(encoding="utf-8")
        )
        self.assertEqual(updated["blocks"][0]["page_start"], 1)
        self.assertEqual(updated["blocks"][1]["page_start"], 6)
        self.assertEqual(updated["blocks"][1]["page_end"], 6)
        self.assertIsNone(updated["blocks"][2]["page_start"])
        # 幂等：已回填的不再改动
        self.assertEqual(evidence.backfill_ir_pages("doc-1"), 0)


class DocsFileEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name)
        self.uploads_patch = mock.patch.object(
            store, "UPLOADS_DIR", self.data_root / "uploads"
        )
        self.index_patch = mock.patch.object(
            store, "INDEX_FILE", self.data_root / "docs_index.json"
        )
        self.uploads_patch.start()
        self.index_patch.start()

        from api.routes import docs

        app = FastAPI()
        app.include_router(docs.router, prefix="/api")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.index_patch.stop()
        self.uploads_patch.stop()

    def _create_doc_with_file(self, doc_id: str = "doc-file-1", content: bytes = b"%PDF-1.4 fake") -> None:
        directory = store.doc_dir(doc_id)
        directory.mkdir(parents=True)
        (directory / "original.pdf").write_bytes(content)
        store.save_meta(
            {
                "id": doc_id,
                "filename": "招标文件.pdf",
                "stored_name": "original.pdf",
                "title": "tender",
                "ext": "pdf",
                "mime": "application/pdf",
                "status": "ready",
            }
        )

    def test_file_endpoint_returns_inline_pdf(self):
        self._create_doc_with_file()
        response = self.client.get("/api/docs/doc-file-1/file")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        disposition = response.headers["content-disposition"]
        self.assertIn("inline", disposition)
        self.assertIn("filename", disposition)
        self.assertEqual(response.content, b"%PDF-1.4 fake")

    def test_file_endpoint_supports_range(self):
        self._create_doc_with_file(content=b"%PDF-1.4 fake body")
        response = self.client.get(
            "/api/docs/doc-file-1/file", headers={"Range": "bytes=0-6"}
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"%PDF-1.")

    def test_file_endpoint_404_for_missing_doc(self):
        response = self.client.get("/api/docs/not-there/file")
        self.assertEqual(response.status_code, 404)

    def test_file_endpoint_404_for_missing_file(self):
        directory = store.doc_dir("doc-no-file")
        directory.mkdir(parents=True)
        store.save_meta(
            {
                "id": "doc-no-file",
                "filename": "gone.pdf",
                "stored_name": "original.pdf",
                "title": "gone",
                "ext": "pdf",
                "mime": "application/pdf",
                "status": "ready",
            }
        )
        response = self.client.get("/api/docs/doc-no-file/file")
        self.assertEqual(response.status_code, 404)


class FindingsEvidenceAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name)
        self.uploads_patch = mock.patch.object(
            store, "UPLOADS_DIR", self.data_root / "uploads"
        )
        self.index_patch = mock.patch.object(
            store, "INDEX_FILE", self.data_root / "docs_index.json"
        )
        self.uploads_patch.start()
        self.index_patch.start()
        evidence.clear_ensure_cache()

        from api.routes import review
        from services.review.store import ReviewStore

        self.review = review
        self.store = ReviewStore(self.data_root / "reviews")
        review.configure_for_tests(self.store)
        app = FastAPI()
        app.include_router(review.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        evidence.clear_ensure_cache()
        self.index_patch.stop()
        self.uploads_patch.stop()

    def _seed_doc_with_spans(self) -> None:
        directory = store.doc_dir("doc-1")
        versions = directory / "versions" / VALID_VERSION_ID
        versions.mkdir(parents=True)
        spans = evidence.spans_from_content_list(
            [
                {
                    "type": "text",
                    "text": "【3】业绩要求：……合同业绩2份……",
                    "bbox": [115, 529, 877, 601],
                    "page_idx": 5,
                }
            ]
        )
        (versions / "evidence_spans.json").write_text(
            json.dumps(spans, ensure_ascii=False), encoding="utf-8"
        )
        (versions / "ir.json").write_text(
            json.dumps({"blocks": []}, ensure_ascii=False), encoding="utf-8"
        )
        (versions / "preview.md").write_text("合同业绩", encoding="utf-8")
        (versions / "manifest.json").write_text(
            json.dumps({"version_id": VALID_VERSION_ID, "status": "ready"}),
            encoding="utf-8",
        )
        store.save_meta(
            {
                "id": "doc-1",
                "filename": "tender.pdf",
                "stored_name": "original.pdf",
                "title": "tender",
                "ext": "pdf",
                "mime": "application/pdf",
                "status": "ready",
                "current_version_id": VALID_VERSION_ID,
            }
        )

    def test_findings_endpoint_enriches_evidence_anchor(self):
        self._seed_doc_with_spans()
        job = self.store.create_analysis_job(
            {
                "batch_id": "batch-1",
                "snapshot": {},
                "documents": [
                    {"document_id": "doc-1", "document_version_id": VALID_VERSION_ID}
                ],
            }
        )
        self.store.create_finding(
            {
                "analysis_job_id": job["id"],
                "document_id": "doc-1",
                "document_version_id": VALID_VERSION_ID,
                "severity": "high",
                "title": "业绩要求",
                "quote": "合同业绩",
                "quote_hash": "x",
                "suppressed": False,
                "evidence_anchor": {
                    "kind": "pdf",
                    "document_id": "doc-1",
                    "document_version_id": VALID_VERSION_ID,
                    "precision": "page",
                    "quote": "合同业绩",
                    "quote_sha256": "y",
                    "validation_status": "degraded",
                    "page_number": 1,
                    "coordinate_space": "normalized-1000-top-left",
                    "rects": [],
                },
            }
        )
        findings = self.client.get(f"/review/analysis-jobs/{job['id']}/findings").json()
        self.assertEqual(findings["total"], 1)
        anchor = findings["items"][0]["evidence_anchor"]
        self.assertEqual(anchor["precision"], "rect")
        self.assertEqual(anchor["validation_status"], "exact")
        self.assertEqual(anchor["page_number"], 6)
        self.assertEqual(anchor["coordinate_space"], "normalized-1000-top-left")
        self.assertEqual(
            anchor["rects"],
            [{"page": 6, "x0": 115.0, "y0": 529.0, "x1": 877.0, "y1": 601.0, "space": "normalized-1000-top-left"}],
        )

    def test_findings_endpoint_keeps_degraded_when_no_spans(self):
        job = self.store.create_analysis_job(
            {
                "batch_id": "batch-1",
                "snapshot": {},
                "documents": [{"document_id": "doc-gone", "document_version_id": "x"}],
            }
        )
        anchor = {
            "kind": "pdf",
            "document_id": "doc-gone",
            "document_version_id": "x",
            "precision": "page",
            "quote": "合同业绩",
            "quote_sha256": "y",
            "validation_status": "degraded",
            "page_number": 1,
            "coordinate_space": "normalized-1000-top-left",
            "rects": [],
        }
        self.store.create_finding(
            {
                "analysis_job_id": job["id"],
                "document_id": "doc-gone",
                "document_version_id": "x",
                "severity": "high",
                "title": "t",
                "quote": "合同业绩",
                "quote_hash": "x",
                "suppressed": False,
                "evidence_anchor": anchor,
            }
        )
        findings = self.client.get(f"/review/analysis-jobs/{job['id']}/findings").json()
        self.assertEqual(findings["items"][0]["evidence_anchor"], anchor)


if __name__ == "__main__":
    unittest.main()
