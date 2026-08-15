"""Embedding token 安全截断测试（T12 修复）。

背景：BAAI/bge-large-zh-v1.5 上下文 512 token，中文约 1 字 ≈ 1 token；
实测中文文本超 ~616 字符即被 SiliconFlow 拒绝（HTTP 400 code 20015），
导致 144 页 tender_file.pdf 这类长文档 embedding 失败、status=failed。

覆盖：
  1. services.utils.truncate_for_embedding 截断规则；
  2. document_pipeline._embed 请求前截断兜底（保留标题头部）；
  3. indexer.get_embeddings 请求前截断兜底；
  4. 分块配置与安全阈值的常量不变量（CHUNK_SIZE < EMBED_MAX_CHARS < 实测失败点）。
"""

import contextlib
import unittest
from unittest import mock

from core import config as core_config
from services.utils import truncate_for_embedding


# ─── truncate_for_embedding 单元测试 ─────────────────────────

class TestTruncateForEmbedding(unittest.TestCase):
    MAX = 450

    def test_short_text_unchanged(self):
        text = "短文本。"
        self.assertEqual(truncate_for_embedding(text, self.MAX), text)

    def test_exact_boundary_unchanged(self):
        text = "短" * self.MAX
        self.assertEqual(len(text), self.MAX)
        self.assertEqual(truncate_for_embedding(text, self.MAX), text)

    def test_long_text_with_headers_preserves_headers_and_cuts_body(self):
        header = "[文档] tender_file\n[章节] 第一章 > 第一节"
        body = "。".join("这是第{}句内容" .format(i) for i in range(50)) + "。"
        text = f"{header}\n\n{body}"
        self.assertGreater(len(text), self.MAX)

        out = truncate_for_embedding(text, self.MAX)
        self.assertLessEqual(len(out), self.MAX)
        # 头部逐字保留，其后跟 "\n\n" 分隔
        self.assertTrue(out.startswith(header))
        remainder = out[len(header):]
        self.assertTrue(remainder.startswith("\n\n"))
        body_prefix = remainder[2:]
        # 截断后剩余正文应是原正文的前缀（无内容篡改）
        self.assertTrue(body.startswith(body_prefix))
        # 句界截断：结尾是完整句号
        self.assertTrue(body_prefix.endswith("。"))
        # 被切掉的部分应从下一句开头开始（而非半截句的残余）
        tail = body[len(body_prefix):]
        self.assertTrue(tail.startswith("这是第"))

    def test_long_plain_text_cuts_at_sentence_boundary(self):
        body = "。".join("条款{}的说明" .format(i) for i in range(80)) + "。"
        out = truncate_for_embedding(body, self.MAX)
        self.assertLessEqual(len(out), self.MAX)
        self.assertTrue(body.startswith(out))
        self.assertTrue(out.endswith("。"))

    def test_no_sentence_punct_falls_back_to_hard_cut(self):
        header = "[文档] 招标文件"
        body = "甲" * 1000  # 无句界标点
        text = f"{header}\n\n{body}"
        out = truncate_for_embedding(text, self.MAX)
        self.assertEqual(len(out), self.MAX)
        self.assertTrue(out.startswith(header))

    def test_header_longer_than_threshold_hard_cuts(self):
        header = "[文档] " + "很长的标题" * 200
        text = f"{header}\n\n正文内容。"
        out = truncate_for_embedding(text, self.MAX)
        self.assertEqual(len(out), self.MAX)
        self.assertTrue(out.startswith("[文档] "))

    def test_any_oversized_input_never_exceeds_threshold(self):
        cases = [
            "长" * 5000,
            "[文档] d\n[章节] s\n\n" + "长" * 3000,
            ("表格行|" * 400) + "\n" + "| --- |" * 100,
            "[文档] t\n" + "、".join("语{}" .format(i) for i in range(2000)),
        ]
        for text in cases:
            with self.subTest(text=text[:20]):
                out = truncate_for_embedding(text, self.MAX)
                self.assertLessEqual(len(out), self.MAX)
                self.assertTrue(text.startswith(out) or out in text[: self.MAX + 1])

    def test_non_str_passthrough(self):
        self.assertIsNone(truncate_for_embedding(None, self.MAX))
        self.assertEqual(truncate_for_embedding(123, self.MAX), 123)


# ─── _embed / get_embeddings 请求前截断兜底 ──────────────────

class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self.text = ""
        self._payload = payload

    def json(self):
        return {
            "data": [
                {"embedding": [float(i) / 10.0, 1.0]}
                for i, _ in enumerate(self._payload["input"])
            ]
        }


class _FakeSession:
    """捕获 POST payload 的假 session（with 语法兼容）。"""

    def __init__(self, captured):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, headers, json, timeout):
        self._captured.append(json)
        return _FakeResp(json)


@contextlib.contextmanager
def _fake_requests_session(captured):
    with mock.patch("core.http_client.requests_session") as session_factory:
        session_factory.return_value = _FakeSession(captured)
        yield session_factory


class TestEmbedRequestTruncation(unittest.TestCase):
    def _long_text(self, header=True):
        body = "。".join("第{}条规定的内容" .format(i) for i in range(120)) + "。"
        if header:
            return "[文档] tender_file\n[章节] 第一章 招标公告\n\n" + body
        return body

    def test_pipeline_embed_truncates_oversized_chunk_before_request(self):
        from services import document_pipeline as pipeline

        text = self._long_text()
        self.assertGreater(len(text), core_config.EMBED_MAX_CHARS)

        captured = []
        with mock.patch.object(pipeline, "EMBED_API_KEY", "sk-test"):
            with _fake_requests_session(captured):
                embeddings = pipeline._embed([text, "短文本"])

        self.assertEqual(len(embeddings), 2)
        self.assertEqual(len(captured), 1)
        sent_inputs = captured[0]["input"]
        self.assertEqual(len(sent_inputs), 2)
        for t in sent_inputs:
            self.assertLessEqual(len(t), core_config.EMBED_MAX_CHARS)
        # 截断后仍保留 [文档]/[章节] 标题头部
        self.assertTrue(sent_inputs[0].startswith("[文档] tender_file\n[章节]"))
        # 短文本原样透传
        self.assertEqual(sent_inputs[1], "短文本")

    def test_pipeline_embed_multiple_batches_all_safe(self):
        from services import document_pipeline as pipeline

        texts = [self._long_text(header=bool(i % 2)) for i in range(230)]
        captured = []
        with mock.patch.object(pipeline, "EMBED_API_KEY", "sk-test"):
            with _fake_requests_session(captured):
                embeddings = pipeline._embed(texts)

        self.assertEqual(len(embeddings), len(texts))
        self.assertEqual(len(captured), 3)  # 100 + 100 + 30
        for payload in captured:
            for t in payload["input"]:
                self.assertLessEqual(len(t), core_config.EMBED_MAX_CHARS)

    def test_indexer_get_embeddings_truncates_before_request(self):
        from services import indexer

        text = self._long_text()
        self.assertGreater(len(text), core_config.EMBED_MAX_CHARS)

        captured = []
        # indexer 在模块顶层导入了 requests_session，需直接 patch 模块属性
        with mock.patch.object(indexer, "EMBED_API_KEY", "sk-test"), \
             mock.patch.object(indexer, "requests_session") as factory:
            factory.return_value = _FakeSession(captured)
            embeddings = indexer.get_embeddings([text, "短句"])

        self.assertEqual(len(embeddings), 2)
        self.assertEqual(len(captured), 1)
        sent_inputs = captured[0]["input"]
        for t in sent_inputs:
            self.assertLessEqual(len(t), core_config.EMBED_MAX_CHARS)
        self.assertTrue(sent_inputs[0].startswith("[文档] tender_file"))
        self.assertEqual(sent_inputs[1], "短句")


# ─── 端到端：超长表格块 → chunk → 请求前必然安全 ──────────────

class TestOversizedChunkEndToEndSafety(unittest.TestCase):
    def test_giant_table_chunk_is_truncated_before_embed_request(self):
        """构造单行超长表格（超过 2*CHUNK_SIZE 与安全阈值），验证 _embed 兜底。"""
        from services.document_pipeline import (
            _embed,
            _normalize_ir,
            structure_aware_chunk,
        )

        # 单行超长表格：normalize 后 markdown 行超长
        giant_cell = "内容" * 1500  # 3000 字符
        raw = [
            {
                "type": "table",
                "markdown": (
                    "| 项目 | 说明 |\n| --- | --- |\n| 条款 | {} |".format(giant_cell)
                ),
                "page": 1,
            }
        ]
        ir = _normalize_ir(
            doc_id="doc-giant-table",
            title="招标文件",
            filename="tender_file.pdf",
            mime="application/pdf",
            pages=1,
            raw_blocks=raw,
        )
        chunks = structure_aware_chunk(ir)
        self.assertTrue(chunks)
        # 巨型单行表不会被行窗口切小 → 必须由 _embed 兜底
        self.assertTrue(
            any(len(c["content"]) > core_config.EMBED_MAX_CHARS for c in chunks),
            "预期存在超过安全阈值的 chunk 以验证兜底",
        )

        captured = []
        import services.document_pipeline as pipeline
        with mock.patch.object(pipeline, "EMBED_API_KEY", "sk-test"):
            with _fake_requests_session(captured):
                embeddings = _embed([c["content"] for c in chunks])

        self.assertEqual(len(embeddings), len(chunks))
        for payload in captured:
            for t in payload["input"]:
                self.assertLessEqual(len(t), core_config.EMBED_MAX_CHARS)
                self.assertTrue(t.startswith("[文档] 招标文件"))


# ─── 配置不变量 ──────────────────────────────────────────────

class TestEmbedSafetyConfigInvariants(unittest.TestCase):
    def test_chunk_size_below_embed_safe_threshold(self):
        # 分块上限必须低于请求前截断阈值，保证常规 chunk 不被截断
        self.assertLess(core_config.CHUNK_SIZE, core_config.EMBED_MAX_CHARS)

    def test_embed_threshold_below_empirical_failure_point(self):
        # 实测超 ~616 字符触发 SiliconFlow 400 code 20015；
        # 安全阈值必须显著低于该失败点，避免阈值本身越界
        self.assertLessEqual(core_config.EMBED_MAX_CHARS, 500)
        self.assertLess(core_config.EMBED_MAX_CHARS, 616)

    def test_overlap_scales_with_chunk_size(self):
        # 重叠按 ~25% 比例跟随收紧，避免短 chunk 里重叠占比过大
        self.assertLessEqual(
            core_config.CHUNK_OVERLAP, core_config.CHUNK_SIZE // 3 + 8
        )
        self.assertGreaterEqual(core_config.CHUNK_OVERLAP, 32)


if __name__ == "__main__":
    unittest.main()
