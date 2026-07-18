"""Unit tests for table_utils using unittest (pytest unavailable)."""

import unittest

from table_utils import (
    looks_like_html_table,
    looks_like_markdown_table,
    html_to_grid,
    markdown_to_grid,
    grid_to_html,
    grid_to_markdown,
    normalize_table_fields,
    is_valid_table_grid,
    promote_raw_blocks,
    extract_tables_from_hits,
)


SAMPLE_HTML = (
    "<table>"
    "<tr><th>伤残等级</th><th>一次性伤残补助金</th><th>伤残津贴（月）</th></tr>"
    "<tr><td>一级伤残</td><td><p>27个月本人工资</p></td><td>本人工资的90%</td></tr>"
    "<tr><td>二级伤残</td><td>25个月本人工资</td><td>本人工资的85%</td></tr>"
    "</table>"
)

SAMPLE_MD = (
    "| 伤残等级 | 一次性伤残补助金 | 伤残津贴（月） |\n"
    "| --- | --- | --- |\n"
    "| 一级伤残 | 27个月本人工资 | 本人工资的90% |\n"
    "| 二级伤残 | 25个月本人工资 | 本人工资的85% |\n"
)


class TestLooksLike(unittest.TestCase):
    def test_looks_like_html_table_true(self):
        self.assertTrue(looks_like_html_table(SAMPLE_HTML))
        self.assertTrue(looks_like_html_table("<table><tr><td>x</td></tr></table>"))
        self.assertTrue(looks_like_html_table("prefix <TABLE>..</TABLE> suffix"))

    def test_looks_like_html_table_false(self):
        self.assertFalse(looks_like_html_table("plain text"))
        self.assertFalse(looks_like_html_table("<div>no table</div>"))
        self.assertFalse(looks_like_html_table(""))

    def test_looks_like_markdown_table_true(self):
        self.assertTrue(looks_like_markdown_table(SAMPLE_MD))
        self.assertTrue(looks_like_markdown_table("| a | b |\n| --- | --- |\n| 1 | 2 |"))

    def test_looks_like_markdown_table_false(self):
        self.assertFalse(looks_like_markdown_table("plain text"))
        self.assertFalse(looks_like_markdown_table("| a | b |"))
        self.assertFalse(looks_like_markdown_table(""))
        self.assertFalse(looks_like_markdown_table("| a | b |\nno sep"))


class TestHtmlToGrid(unittest.TestCase):
    def test_html_to_grid_strips_nested_p_and_preserves_text(self):
        grid = html_to_grid(SAMPLE_HTML)
        self.assertEqual(len(grid), 3)  # 1 header + 2 data
        self.assertEqual(len(grid[0]), 3)
        # Header
        self.assertEqual(grid[0], ["伤残等级", "一次性伤残补助金", "伤残津贴（月）"])
        # First data row: <p> stripped, exact text preserved
        self.assertEqual(grid[1], ["一级伤残", "27个月本人工资", "本人工资的90%"])
        self.assertEqual(grid[2], ["二级伤残", "25个月本人工资", "本人工资的85%"])

    def test_html_to_grid_handles_br_as_space(self):
        html = "<table><tr><td>line1<br>line2</td></tr></table>"
        grid = html_to_grid(html)
        self.assertEqual(grid[0][0], "line1 line2")

    def test_html_to_grid_unescapes_entities(self):
        html = "<table><tr><td>a &amp; b &lt; c</td></tr></table>"
        grid = html_to_grid(html)
        self.assertEqual(grid[0][0], "a & b < c")

    def test_html_to_grid_collapses_whitespace(self):
        html = "<table><tr><td>  foo   bar  </td></tr></table>"
        grid = html_to_grid(html)
        self.assertEqual(grid[0][0], "foo bar")

    def test_html_to_grid_bad_input_returns_empty(self):
        self.assertEqual(html_to_grid(""), [])
        self.assertEqual(html_to_grid("no table here"), [])
        self.assertEqual(html_to_grid("<p>text</p>"), [])


class TestMarkdownToGrid(unittest.TestCase):
    def test_markdown_to_grid_parses_and_skips_separator(self):
        grid = markdown_to_grid(SAMPLE_MD)
        self.assertEqual(len(grid), 3)
        self.assertEqual(grid[0], ["伤残等级", "一次性伤残补助金", "伤残津贴（月）"])
        self.assertEqual(grid[1], ["一级伤残", "27个月本人工资", "本人工资的90%"])

    def test_markdown_to_grid_skips_various_separator_styles(self):
        md = "| a | b |\n| --- |:---:|\n| 1 | 2 |"
        grid = markdown_to_grid(md)
        self.assertEqual(grid, [["a", "b"], ["1", "2"]])

    def test_markdown_to_grid_bad_input_returns_empty(self):
        self.assertEqual(markdown_to_grid(""), [])
        self.assertEqual(markdown_to_grid("not a table"), [])
        self.assertEqual(markdown_to_grid("| only | one |"), [])


class TestGridToHtml(unittest.TestCase):
    def test_grid_to_html_uses_thead_th_tbody_td(self):
        grid = [
            ["A", "B"],
            ["1", "2"],
        ]
        html = grid_to_html(grid)
        self.assertIn("<table>", html)
        self.assertIn("<thead>", html)
        self.assertIn("<th>A</th>", html)
        self.assertIn("<tbody>", html)
        self.assertIn("<td>1</td>", html)
        self.assertIn("</thead>", html)
        self.assertIn("</tbody>", html)
        self.assertIn("</table>", html)

    def test_grid_to_html_empty(self):
        self.assertEqual(grid_to_html([]), "")
        self.assertEqual(grid_to_html([[]]), "")


class TestGridToMarkdown(unittest.TestCase):
    def test_grid_to_markdown_has_separator_with_dashes(self):
        grid = [
            ["伤残等级", "一次性伤残补助金"],
            ["一级伤残", "27个月本人工资"],
        ]
        md = grid_to_markdown(grid)
        lines = md.splitlines()
        self.assertGreaterEqual(len(lines), 3)
        # line 0 header, line 1 separator, line 2 data
        self.assertIn("| 伤残等级 |", lines[0])
        self.assertIn("---", lines[1])
        self.assertTrue(lines[1].startswith("|"))
        self.assertTrue(lines[1].endswith("|"))
        self.assertIn("| 一级伤残 |", lines[2])

    def test_grid_to_markdown_escapes_pipe(self):
        grid = [["a|b", "c"]]
        md = grid_to_markdown(grid)
        self.assertIn("a\\|b", md)

    def test_grid_to_markdown_empty(self):
        self.assertEqual(grid_to_markdown([]), "")
        self.assertEqual(grid_to_markdown([[]]), "")


class TestNormalizeTableFields(unittest.TestCase):
    def test_normalize_prefers_html_and_roundtrips_without_p(self):
        result = normalize_table_fields(html=SAMPLE_HTML)
        self.assertIn("html", result)
        self.assertIn("markdown", result)
        self.assertIn("text", result)
        # html must have no nested <p>
        self.assertNotIn("<p>", result["html"])
        self.assertNotIn("</p>", result["html"])
        # markdown must have pipes and 27个月
        self.assertIn("|", result["markdown"])
        self.assertIn("27个月", result["markdown"])
        # text == markdown
        self.assertEqual(result["text"], result["markdown"])

    def test_normalize_from_markdown_only(self):
        result = normalize_table_fields(markdown=SAMPLE_MD)
        self.assertIn("|", result["markdown"])
        self.assertIn("27个月", result["markdown"])
        self.assertEqual(result["text"], result["markdown"])

    def test_normalize_from_text_fallback(self):
        result = normalize_table_fields(text="| x | y |\n| --- |\n| 1 | 2 |")
        self.assertIn("|", result.get("markdown", ""))

    def test_normalize_empty_on_failure(self):
        result = normalize_table_fields(html="garbage")
        self.assertEqual(result["html"], "")
        self.assertEqual(result["markdown"], "")
        self.assertEqual(result["text"], "")

    def test_normalize_roundtrip_idempotent(self):
        r1 = normalize_table_fields(html=SAMPLE_HTML)
        # feed the generated html back
        r2 = normalize_table_fields(html=r1["html"])
        self.assertEqual(r1["markdown"], r2["markdown"])


class TestIsValidTableGrid(unittest.TestCase):
    def test_valid_min_2x2(self):
        grid = [["a", "b"], ["1", "2"]]
        self.assertTrue(is_valid_table_grid(grid))

    def test_too_few_rows(self):
        grid = [["a", "b"]]
        self.assertFalse(is_valid_table_grid(grid))

    def test_too_few_cols(self):
        grid = [["a"], ["b"]]
        self.assertFalse(is_valid_table_grid(grid))

    def test_min_cols_override(self):
        grid = [["a"], ["b"]]
        self.assertTrue(is_valid_table_grid(grid, min_rows=2, min_cols=1))

    def test_bad_input_false(self):
        self.assertFalse(is_valid_table_grid([]))
        self.assertFalse(is_valid_table_grid(None))
        self.assertFalse(is_valid_table_grid("notalist"))


class TestPromoteRawBlocks(unittest.TestCase):
    def test_promote_nested_p_html_to_table(self):
        raw = [
            {
                "type": "paragraph",
                "text": SAMPLE_HTML,
                "html": SAMPLE_HTML,
            }
        ]
        out = promote_raw_blocks(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "table")
        self.assertIn("<table>", out[0].get("html", ""))
        self.assertIn("|", out[0].get("markdown", ""))
        self.assertIn("27个月", out[0].get("markdown", ""))
        self.assertNotIn("<p>", out[0].get("html", ""))

    def test_promote_markdown_in_text(self):
        raw = [{"type": "paragraph", "text": SAMPLE_MD}]
        out = promote_raw_blocks(raw)
        self.assertEqual(out[0]["type"], "table")
        self.assertIn("| 伤残等级 |", out[0]["markdown"])

    def test_already_table_passthrough(self):
        raw = [{"type": "table", "markdown": SAMPLE_MD}]
        out = promote_raw_blocks(raw)
        self.assertEqual(out[0]["type"], "table")

    def test_bad_table_no_promote_no_throw(self):
        raw = [{"type": "paragraph", "text": "not a table at all"}]
        out = promote_raw_blocks(raw)
        self.assertEqual(out[0]["type"], "paragraph")

    def test_promote_preserves_other_fields(self):
        raw = [{"type": "paragraph", "text": SAMPLE_HTML, "page": 3, "meta": {"x": 1}}]
        out = promote_raw_blocks(raw)
        self.assertEqual(out[0].get("page"), 3)
        self.assertEqual(out[0].get("meta"), {"x": 1})


class TestExtractTablesFromHits(unittest.TestCase):
    def test_extract_prefers_block_type_table(self):
        hits = [
            {"block_type": "table", "content": SAMPLE_MD, "filename": "d.docx", "section_path": "s1", "doc_id": "d1", "chunk_id": 7},
        ]
        res = extract_tables_from_hits(hits, max_tables=2)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["markdown"], SAMPLE_MD.strip())
        self.assertEqual(res[0]["filename"], "d.docx")
        self.assertEqual(res[0]["chunk_id"], 7)

    def test_extract_from_content_html_table(self):
        hits = [
            {"block_type": "paragraph", "content": SAMPLE_HTML, "filename": "x.txt", "section_path": "", "doc_id": "x", "chunk_id": 0},
        ]
        res = extract_tables_from_hits(hits)
        self.assertEqual(len(res), 1)
        self.assertIn("27个月", res[0]["markdown"])

    def test_strip_doc_section_headers(self):
        content = "[文档] 工伤保险\n[章节] 待遇\n" + SAMPLE_MD
        hits = [{"block_type": "paragraph", "content": content}]
        res = extract_tables_from_hits(hits)
        self.assertEqual(len(res), 1)
        self.assertIn("| 伤残等级 |", res[0]["markdown"])

    def test_dedup_by_markdown(self):
        hits = [
            {"block_type": "table", "content": SAMPLE_MD},
            {"block_type": "paragraph", "content": SAMPLE_MD},
        ]
        res = extract_tables_from_hits(hits, max_tables=5)
        self.assertEqual(len(res), 1)

    def test_max_tables_limit(self):
        md2 = "| x | y |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        hits = [
            {"block_type": "table", "content": SAMPLE_MD},
            {"block_type": "table", "content": md2},
        ]
        res = extract_tables_from_hits(hits, max_tables=1)
        self.assertEqual(len(res), 1)

    def test_only_valid_2x2(self):
        # truly 1-col table: after split/pad min len=1 < 2
        bad = "| only |\n| --- |\n| one |"
        hits = [{"block_type": "table", "content": bad}]
        res = extract_tables_from_hits(hits)
        self.assertEqual(res, [])

    def test_empty_hits(self):
        self.assertEqual(extract_tables_from_hits([]), [])


if __name__ == "__main__":
    unittest.main()
