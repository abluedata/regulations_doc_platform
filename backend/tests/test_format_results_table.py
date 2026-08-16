"""Unit tests for format_results_for_llm table handling."""

import unittest

from services.knowledge.search import format_results_for_llm


SAMPLE_TABLE_MD = (
    "| 伤残等级 | 一次性伤残补助金 | 伤残津贴（月） |\n"
    "| --- | --- | --- |\n"
    "| 一级伤残 | 27个月本人工资 | 本人工资的90% |\n"
    "| 二级伤残 | 25个月本人工资 | 本人工资的85% |\n"
)


class TestFormatResultsTableAware(unittest.TestCase):
    def test_format_results_for_llm_table_block_preserves_content_and_instruction(self):
        search_result = {
            "local": [
                {
                    "title": "工伤保险待遇",
                    "content": SAMPLE_TABLE_MD,
                    "doc_id": "d1",
                    "chunk_id": 0,
                    "filename": "sample.docx",
                    "score": 1.0,
                    "source": "local",
                    "block_type": "table",
                    "section_path": "待遇标准",
                }
            ],
            "web": [],
        }

        ctx = format_results_for_llm(search_result)

        # Key table content must be present
        self.assertIn("27个月本人工资", ctx)

        # When a table is present, instruction text should mention table / original / do-not
        # Chinese keywords from the appended instruction: 表格 / 原文 / 不要
        self.assertTrue(
            ("表格" in ctx) or ("原文" in ctx) or ("不要" in ctx),
            "Expected instruction text mentioning 表格/原文/不要 when table hits are present"
        )

    def test_format_results_for_llm_non_table_uses_800_limit(self):
        long_text = "x" * 2000
        search_result = {
            "local": [
                {
                    "title": "普通段落",
                    "content": long_text,
                    "doc_id": "d2",
                    "chunk_id": 1,
                    "filename": "sample.docx",
                    "score": 0.9,
                    "source": "local",
                    "block_type": "paragraph",
                    "section_path": "",
                }
            ],
            "web": [],
        }

        ctx = format_results_for_llm(search_result)

        # Non-table should have been truncated near 800 (plus "...")
        # We don't assert exact 800 due to headers, but should not contain the full 2000 chars
        self.assertLess(len([p for p in ctx.splitlines() if "x" * 100 in p or len(p) > 900]), 5)
        # Heuristic: the long run of x's should be cut
        self.assertNotIn("x" * 900, ctx)

    def test_format_results_for_llm_has_section_path_and_headers(self):
        search_result = {
            "local": [
                {
                    "title": "待遇表",
                    "content": SAMPLE_TABLE_MD,
                    "doc_id": "d3",
                    "chunk_id": 2,
                    "filename": "doc.docx",
                    "score": 0.8,
                    "source": "local",
                    "block_type": "table",
                    "section_path": "第五章 > 伤残待遇",
                }
            ],
            "web": [],
        }

        ctx = format_results_for_llm(search_result)
        self.assertIn("27个月本人工资", ctx)
        self.assertIn("第五章 > 伤残待遇", ctx)
        # Note: [文档] header is injected upstream in document_pipeline, not here; ensure filename/section shown
        self.assertIn("doc.docx", ctx)


if __name__ == "__main__":
    unittest.main()
