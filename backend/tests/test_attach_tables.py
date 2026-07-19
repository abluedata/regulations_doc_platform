"""Unit tests for build_table_appendix in qa_service."""

import unittest

from services.qa_service import build_table_appendix


class TestBuildTableAppendix(unittest.TestCase):
    def test_empty_tables_returns_empty(self):
        self.assertEqual(build_table_appendix([]), "")
        self.assertEqual(build_table_appendix(None), "")  # type: ignore[arg-type]

    def test_builds_with_filename_and_markdown(self):
        tables = [
            {
                "filename": "工伤保险条例.docx",
                "section_path": "第五章",
                "markdown": "| 伤残等级 | 金额 |\n| --- | --- |\n| 一级 | 27个月 |",
            }
        ]
        out = build_table_appendix(tables)
        self.assertIn("## 原文表格", out)
        self.assertIn("> 来源：工伤保险条例.docx · 第五章", out)
        self.assertIn("| 伤残等级 | 金额 |", out)
        self.assertIn("27个月", out)

    def test_builds_with_doc_id_fallback(self):
        tables = [
            {"doc_id": "doc-xyz", "markdown": "| a | b |\n| --- | --- |\n| 1 | 2 |"}
        ]
        out = build_table_appendix(tables)
        self.assertIn("> 来源：doc-xyz", out)
        self.assertIn("| a | b |", out)

    def test_builds_without_section_path(self):
        tables = [
            {"filename": "policy.txt", "markdown": "| x | y |\n| --- | --- |\n| p | q |"}
        ]
        out = build_table_appendix(tables)
        self.assertIn("> 来源：policy.txt\n\n", out)
        self.assertNotIn(" · ", out.split("\n> 来源：", 1)[1].split("\n", 1)[0])

    def test_multiple_tables(self):
        tables = [
            {"filename": "d1", "markdown": "| a |\n| --- |\n| 1 |"},
            {"filename": "d2", "markdown": "| b |\n| --- |\n| 2 |"},
        ]
        out = build_table_appendix(tables)
        self.assertIn("## 原文表格", out)
        self.assertIn("来源：d1", out)
        self.assertIn("来源：d2", out)
        self.assertIn("| a |", out)
        self.assertIn("| b |", out)

    def test_handles_missing_markdown_gracefully(self):
        tables = [{"filename": "x", "markdown": None}]
        out = build_table_appendix(tables)
        self.assertIn("## 原文表格", out)
        self.assertIn("> 来源：x", out)

    def test_uses_doc_id_when_no_filename(self):
        tables = [{"doc_id": "no-fname", "markdown": "| k |\n| --- |\n| v |"}]
        out = build_table_appendix(tables)
        self.assertIn("来源：no-fname", out)


if __name__ == "__main__":
    unittest.main()
