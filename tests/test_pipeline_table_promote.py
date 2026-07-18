"""Unit tests for table promotion flow in document_pipeline (unittest)."""

import unittest

from core.table_utils import promote_raw_blocks
from services.document_pipeline import _normalize_ir, structure_aware_chunk, _run_pipeline

# Reused SAMPLE_HTML from test_table_utils (nested <p> + "27个月本人工资")
SAMPLE_HTML = (
    "<table>"
    "<tr><th>伤残等级</th><th>一次性伤残补助金</th><th>伤残津贴（月）</th></tr>"
    "<tr><td>一级伤残</td><td><p>27个月本人工资</p></td><td>本人工资的90%</td></tr>"
    "<tr><td>二级伤残</td><td>25个月本人工资</td><td>本人工资的85%</td></tr>"
    "</table>"
)


class TestPipelineTablePromote(unittest.TestCase):
    def test_promote_raw_blocks_then_normalize_ir_then_structure_aware_chunk(self):
        # 1) promote
        raw = [
            {
                "type": "paragraph",
                "text": SAMPLE_HTML,
                "html": SAMPLE_HTML,
                "page": 1,
            }
        ]
        promoted = promote_raw_blocks(raw)
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["type"], "table")

        # 2) _normalize_ir (simulates the post-promote path in _run_pipeline)
        ir = _normalize_ir(
            doc_id="doc-test-1",
            title="工伤保险待遇说明",
            filename="test.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            pages=1,
            raw_blocks=promoted,
        )

        # Assertions on IR
        self.assertIn("blocks", ir)
        self.assertEqual(len(ir["blocks"]), 1)
        blk = ir["blocks"][0]
        self.assertEqual(blk["type"], "table")
        self.assertIn("markdown", blk)
        self.assertIn("html", blk)
        # markdown must contain 27个月 (key content preserved)
        self.assertIn("27个月", blk["markdown"])
        # html must NOT contain nested <p> (stripped by grid roundtrip)
        self.assertNotIn("<p>", blk.get("html", ""))
        self.assertNotIn("</p>", blk.get("html", ""))
        # both html and markdown are non-empty (dual-form from same grid)
        self.assertTrue(blk.get("html"))
        self.assertTrue(blk.get("markdown"))
        # text == markdown (per normalize_table_fields contract)
        self.assertEqual(blk.get("text"), blk.get("markdown"))

        # 3) structure_aware_chunk
        chunks = structure_aware_chunk(ir)
        self.assertTrue(chunks, "chunks should not be empty for a table block")

        # All table chunks must have block_type=table
        for ch in chunks:
            self.assertEqual(ch.get("block_type"), "table")
            content = ch.get("content", "")
            # header injected
            self.assertIn("[文档]", content)
            # must include key table tokens in final chunk content
            self.assertIn("伤残等级", content)
            self.assertIn("27个月", content)

    def test_structure_aware_chunk_body_is_markdown_not_html(self):
        # raw table with html body (no markdown) — after normalize_ir should prefer md
        raw = [
            {
                "type": "table",
                "html": SAMPLE_HTML,
                "page": 1,
            }
        ]
        ir = _normalize_ir(
            doc_id="doc-test-2",
            title="T",
            filename="t.docx",
            mime="",
            pages=1,
            raw_blocks=raw,
        )
        blk = ir["blocks"][0]
        # markdown preferred
        self.assertIn("|", blk.get("markdown", ""))
        self.assertIn("27个月", blk.get("markdown", ""))
        # structure_aware_chunk uses markdown body
        chunks = structure_aware_chunk(ir)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0]["block_type"], "table")
        self.assertIn("| 伤残等级 |", chunks[0]["content"])

    def test_normalize_ir_rejects_pre_fallback_on_grid_success(self):
        # Explicitly feed markdown that would have triggered old <pre> path
        raw = [
            {
                "type": "table",
                "markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                "html": None,
            }
        ]
        ir = _normalize_ir(
            doc_id="doc-test-3",
            title="T",
            filename="t.docx",
            mime="",
            pages=1,
            raw_blocks=raw,
        )
        blk = ir["blocks"][0]
        html = blk.get("html", "")
        # must NOT be the old <pre> wrapper as primary html
        self.assertFalse(html.startswith("<pre>"), f"html unexpectedly used <pre> fallback: {html}")
        self.assertIn("<table>", html)
        self.assertIn("<th>A</th>", html)


if __name__ == "__main__":
    unittest.main()
