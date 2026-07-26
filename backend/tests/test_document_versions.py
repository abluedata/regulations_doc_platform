"""Tests for immutable, deterministic document parse versions."""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import document_pipeline as pipeline
from services import document_store as store


class TestDocumentVersions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.uploads_patch = mock.patch.object(
            store, "UPLOADS_DIR", self.data_root / "uploads"
        )
        self.index_patch = mock.patch.object(
            store, "INDEX_FILE", self.data_root / "docs_index.json"
        )
        self.uploads_patch.start()
        self.index_patch.start()

    def tearDown(self):
        self.index_patch.stop()
        self.uploads_patch.stop()
        self.temp_dir.cleanup()

    def _create_doc(self, doc_id: str = "doc-version-test", content: bytes = b"source"):
        directory = store.doc_dir(doc_id)
        directory.mkdir(parents=True)
        source = directory / "original.pdf"
        source.write_bytes(content)
        store.save_meta(
            {
                "id": doc_id,
                "filename": "source.pdf",
                "stored_name": "original.pdf",
                "title": "Source",
                "ext": "pdf",
                "mime": "application/pdf",
                "status": "queued",
            }
        )
        return source

    def _require_store_api(self, *names: str) -> None:
        missing = [name for name in names if not hasattr(store, name)]
        self.assertEqual([], missing, f"missing document version API: {missing}")

    def test_version_id_is_deterministic_and_path_safe(self):
        self._require_store_api("source_sha256", "compute_version_id")
        source = self._create_doc(content=b"stable source bytes")
        digest = store.source_sha256(source)
        config_a = {"ocr": True, "layout": {"language": "zh", "dpi": 300}}
        config_b = {"layout": {"dpi": 300, "language": "zh"}, "ocr": True}

        first = store.compute_version_id(digest, "schema-v1", config_a)
        second = store.compute_version_id(digest, "schema-v1", config_b)

        self.assertEqual(first, second)
        self.assertRegex(first, re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotEqual(
            first, store.compute_version_id(digest, "schema-v2", config_a)
        )
        self.assertNotEqual(
            first, store.compute_version_id(digest, "schema-v1", {"ocr": False})
        )
        source.write_bytes(b"changed source bytes")
        self.assertNotEqual(
            first,
            store.compute_version_id(
                store.source_sha256(source), "schema-v1", config_a
            ),
        )

    def test_version_directory_is_complete_and_immutable(self):
        self._require_store_api(
            "source_sha256", "compute_version_id", "write_version_artifacts"
        )
        source = self._create_doc()
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {})
        ir = {"doc_id": "doc-version-test", "blocks": []}
        manifest = {
            "version_id": version_id,
            "source_sha256": digest,
            "parser_schema_version": "schema-v1",
            "parse_config": {},
            "status": "ready",
        }

        version_dir = store.write_version_artifacts(
            "doc-version-test", version_id, ir, "# Preview", manifest
        )

        self.assertEqual(
            store.doc_dir("doc-version-test") / "versions" / version_id,
            version_dir,
        )
        self.assertEqual(ir, json.loads((version_dir / "ir.json").read_text("utf-8")))
        self.assertEqual("# Preview", (version_dir / "preview.md").read_text("utf-8"))
        self.assertEqual(
            manifest, json.loads((version_dir / "manifest.json").read_text("utf-8"))
        )

        with self.assertRaises(FileExistsError):
            store.write_version_artifacts(
                "doc-version-test",
                version_id,
                {"changed": True},
                "changed",
                manifest,
            )
        self.assertEqual(ir, json.loads((version_dir / "ir.json").read_text("utf-8")))

    def test_current_reads_prefer_version_and_fall_back_to_legacy(self):
        self._require_store_api(
            "source_sha256",
            "compute_version_id",
            "write_version_artifacts",
            "set_current_version",
        )
        source = self._create_doc()
        store.save_ir("doc-version-test", {"kind": "legacy"})
        store.save_preview_md("doc-version-test", "legacy preview")
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {})
        manifest = {
            "version_id": version_id,
            "source_sha256": digest,
            "parser_schema_version": "schema-v1",
            "parse_config": {},
            "status": "ready",
        }
        store.write_version_artifacts(
            "doc-version-test",
            version_id,
            {"kind": "versioned"},
            "versioned preview",
            manifest,
        )

        self.assertTrue(store.set_current_version("doc-version-test", version_id))
        self.assertEqual(version_id, store.load_meta("doc-version-test")["current_version_id"])
        self.assertEqual({"kind": "versioned"}, store.load_ir("doc-version-test"))
        self.assertEqual("versioned preview", store.load_preview_md("doc-version-test"))

        meta = store.load_meta("doc-version-test")
        meta.pop("current_version_id")
        store.save_meta(meta)
        self.assertEqual({"kind": "legacy"}, store.load_ir("doc-version-test"))
        self.assertEqual("legacy preview", store.load_preview_md("doc-version-test"))

    def test_failed_or_incomplete_version_cannot_become_current(self):
        self._require_store_api(
            "source_sha256",
            "compute_version_id",
            "write_version_artifacts",
            "set_current_version",
        )
        source = self._create_doc()
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {})
        manifest = {
            "version_id": version_id,
            "source_sha256": digest,
            "parser_schema_version": "schema-v1",
            "parse_config": {},
            "status": "failed",
        }
        store.write_version_artifacts(
            "doc-version-test", version_id, {"blocks": []}, "", manifest
        )

        self.assertFalse(store.set_current_version("doc-version-test", version_id))
        self.assertNotIn("current_version_id", store.load_meta("doc-version-test"))
        self.assertFalse(
            store.set_current_version("doc-version-test", "0" * 64),
            "an unpublished version directory must not become current",
        )

    def test_reparse_publishes_new_version_without_deleting_prior_artifacts(self):
        self._require_store_api("source_sha256", "compute_version_id")
        source = self._create_doc(content=b"first source")
        first_blocks = [{"type": "paragraph", "text": "First", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(first_blocks, 1, "test-parser"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")

        first_meta = store.load_meta("doc-version-test")
        self.assertIn("current_version_id", first_meta)
        first_id = first_meta["current_version_id"]
        first_dir = store.doc_dir("doc-version-test") / "versions" / first_id
        first_ir = (first_dir / "ir.json").read_bytes()

        source.write_bytes(b"second source")
        second_blocks = [{"type": "paragraph", "text": "Second", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(second_blocks, 1, "test-parser"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")

        second_id = store.load_meta("doc-version-test")["current_version_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first_ir, (first_dir / "ir.json").read_bytes())
        self.assertTrue(
            (store.doc_dir("doc-version-test") / "versions" / second_id / "manifest.json").is_file()
        )

    def test_pipeline_failure_keeps_previous_current_version(self):
        self._require_store_api("source_sha256", "compute_version_id")
        source = self._create_doc(content=b"published source")
        blocks = [{"type": "paragraph", "text": "Published", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "test-parser"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        published_id = store.load_meta("doc-version-test")["current_version_id"]

        source.write_bytes(b"failing source")
        failed_digest = store.source_sha256(source)
        failed_id = store.compute_version_id(
            failed_digest,
            pipeline.PARSER_SCHEMA_VERSION,
            pipeline.current_parse_config(),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(
                pipeline,
                "_parse_with_mineru_or_fallback",
                return_value=(blocks, 1, "test-parser"),
            ), mock.patch.object(
                pipeline, "_index_chunks", side_effect=RuntimeError("index failed")
            ):
                pipeline._run_pipeline("doc-version-test")

        failed_meta = store.load_meta("doc-version-test")
        self.assertEqual("failed", failed_meta["status"])
        self.assertEqual(published_id, failed_meta["current_version_id"])
        self.assertFalse(
            (store.doc_dir("doc-version-test") / "versions" / failed_id).exists()
        )


if __name__ == "__main__":
    unittest.main()
