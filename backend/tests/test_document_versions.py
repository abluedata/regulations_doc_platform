"""Tests for immutable, deterministic document parse versions."""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import threading
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
            {**pipeline.current_parse_config(), "effective_engine": "test-parser"},
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
        self.assertTrue(
            (store.doc_dir("doc-version-test") / "versions" / failed_id).exists(),
            "failed index versions remain durable but unpublished for retry",
        )

    def test_same_source_with_different_effective_engines_gets_distinct_versions(self):
        self._create_doc(content=b"same source")
        mineru_blocks = [{"type": "paragraph", "text": "MinerU", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(mineru_blocks, 1, "mineru:pipeline"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        mineru_id = store.load_meta("doc-version-test")["current_version_id"]

        fallback_blocks = [{"type": "paragraph", "text": "Fallback", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(fallback_blocks, 1, "pdfplumber"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        fallback_id = store.load_meta("doc-version-test")["current_version_id"]

        self.assertNotEqual(mineru_id, fallback_id)
        self.assertEqual(
            "MinerU",
            json.loads(
                (store.version_dir("doc-version-test", mineru_id) / "ir.json").read_text(
                    "utf-8"
                )
            )["blocks"][0]["text"],
        )
        self.assertEqual(
            "Fallback",
            store.load_ir("doc-version-test")["blocks"][0]["text"],
        )

    def test_artifact_failure_precedes_index_and_crash_retry_reconciles(self):
        source = self._create_doc(content=b"published source")
        blocks = [{"type": "paragraph", "text": "Published", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "engine-a"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        published_id = store.load_meta("doc-version-test")["current_version_id"]

        source.write_bytes(b"artifact failure")
        index_mock = mock.Mock()
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(
                pipeline,
                "_parse_with_mineru_or_fallback",
                return_value=(blocks, 1, "engine-b"),
            ), mock.patch.object(
                pipeline, "write_version_artifacts", side_effect=OSError("disk full")
            ), mock.patch.object(pipeline, "_index_chunks", index_mock):
                pipeline._run_pipeline("doc-version-test")
        self.assertFalse(
            index_mock.called,
            "artifact failure must not mutate or stage the search index",
        )
        self.assertEqual(
            published_id, store.load_meta("doc-version-test")["current_version_id"]
        )

        source.write_bytes(b"crash window")
        crash_digest = store.source_sha256(source)
        crash_id = store.compute_version_id(
            crash_digest,
            pipeline.PARSER_SCHEMA_VERSION,
            {**pipeline.current_parse_config(), "effective_engine": "engine-c"},
        )
        with self.assertRaises(SystemExit):
            with mock.patch.object(
                pipeline,
                "_parse_with_mineru_or_fallback",
                return_value=(blocks, 1, "engine-c"),
            ), mock.patch.object(
                pipeline, "_index_chunks", side_effect=SystemExit("crash after stage")
            ):
                pipeline._run_pipeline("doc-version-test")
        self.assertTrue(
            (store.version_dir("doc-version-test", crash_id) / "manifest.json").is_file(),
            "artifacts must be durable before index staging begins",
        )
        self.assertEqual(
            published_id, store.load_meta("doc-version-test")["current_version_id"]
        )

        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "engine-c"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        self.assertEqual(
            crash_id, store.load_meta("doc-version-test")["current_version_id"]
        )

    def test_concurrent_status_update_cannot_erase_current_version(self):
        source = self._create_doc()
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {})
        store.write_version_artifacts(
            "doc-version-test",
            version_id,
            {"blocks": []},
            "preview",
            {
                "version_id": version_id,
                "source_sha256": digest,
                "parser_schema_version": "schema-v1",
                "parse_config": {},
                "status": "ready",
            },
        )

        status_loaded = threading.Event()
        release_status = threading.Event()
        original_load_meta = store.load_meta

        def controlled_load_meta(doc_id):
            meta = original_load_meta(doc_id)
            if threading.current_thread().name == "status-writer":
                status_loaded.set()
                release_status.wait(timeout=2)
            return meta

        status_thread = threading.Thread(
            name="status-writer",
            target=store.update_status,
            args=("doc-version-test", "chunking"),
        )
        publish_thread = threading.Thread(
            name="version-publisher",
            target=store.set_current_version,
            args=("doc-version-test", version_id),
        )
        with mock.patch.object(store, "load_meta", side_effect=controlled_load_meta):
            status_thread.start()
            self.assertTrue(status_loaded.wait(timeout=2))
            publish_thread.start()
            publish_thread.join(timeout=0.2)
            release_status.set()
            status_thread.join(timeout=2)
            publish_thread.join(timeout=2)

        meta = store.load_meta("doc-version-test")
        self.assertEqual("chunking", meta["status"])
        self.assertEqual(version_id, meta.get("current_version_id"))

    def test_search_hides_staged_chunks_until_version_publication(self):
        from services import search

        source = self._create_doc()
        digest = store.source_sha256(source)
        old_id = store.compute_version_id(digest, "schema-v1", {"engine": "old"})
        new_id = store.compute_version_id(digest, "schema-v1", {"engine": "new"})
        for version_id in (old_id, new_id):
            store.write_version_artifacts(
                "doc-version-test",
                version_id,
                {"blocks": []},
                "preview",
                {
                    "version_id": version_id,
                    "source_sha256": digest,
                    "parser_schema_version": "schema-v1",
                    "parse_config": {},
                    "status": "ready",
                },
            )
        store.set_current_version(
            "doc-version-test", old_id, indexed_version_id=old_id
        )

        class FakeElasticsearch:
            def __init__(self):
                self.bodies = []

            def search(self, *, index, body):
                self.bodies.append(body)
                serialized = json.dumps(body)
                has_visibility_filter = "visibility_key" in serialized
                selected_id = (
                    new_id if has_visibility_filter and new_id in serialized else old_id
                ) if has_visibility_filter else new_id
                selected_content = (
                    "staged" if selected_id == new_id else "published"
                )
                hits = [{
                    "_source": {
                        "doc_id": "doc-version-test",
                        "document_version_id": selected_id,
                        "visibility_key": f"doc-version-test:{selected_id}",
                        "chunk_id": 1,
                        "content": selected_content,
                    }
                }]
                return {"hits": {"hits": hits}}

        fake_es = FakeElasticsearch()
        with mock.patch.object(search, "get_es", return_value=fake_es), \
             mock.patch.object(search, "get_embeddings", return_value=[None]):
            before = search.search_local("query", k=2)
            self.assertEqual(["published"], [item["content"] for item in before])
            self.assertIn("visibility_key", json.dumps(fake_es.bodies[0]))

            store.set_current_version(
                "doc-version-test", new_id, indexed_version_id=new_id
            )
            after = search.search_local("query", k=2)
            self.assertEqual(["staged"], [item["content"] for item in after])

    def test_same_engine_with_different_build_versions_gets_distinct_versions(self):
        self._create_doc(content=b"same service input")
        blocks = [{"type": "paragraph", "text": "Parsed", "page": 1}]
        with mock.patch.object(
            pipeline, "PARSER_BUILD_VERSION", "parser-build-a", create=True
        ), mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "mineru:pipeline"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        first_id = store.load_meta("doc-version-test")["current_version_id"]

        with mock.patch.object(
            pipeline, "PARSER_BUILD_VERSION", "parser-build-b", create=True
        ), mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "mineru:pipeline"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        second_id = store.load_meta("doc-version-test")["current_version_id"]

        self.assertNotEqual(first_id, second_id)

    def test_same_version_id_with_different_output_fails_before_indexing(self):
        self._create_doc(content=b"collision input")
        first_blocks = [{"type": "paragraph", "text": "First", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(first_blocks, 1, "same-engine"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")
        published_id = store.load_meta("doc-version-test")["current_version_id"]

        second_blocks = [{"type": "paragraph", "text": "Different", "page": 1}]
        index_mock = mock.Mock()
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(
                pipeline,
                "_parse_with_mineru_or_fallback",
                return_value=(second_blocks, 1, "same-engine"),
            ), mock.patch.object(pipeline, "_index_chunks", index_mock):
                pipeline._run_pipeline("doc-version-test")

        index_mock.assert_not_called()
        self.assertEqual("failed", store.load_meta("doc-version-test")["status"])
        self.assertEqual(
            "First",
            json.loads(
                (store.version_dir("doc-version-test", published_id) / "ir.json").read_text(
                    "utf-8"
                )
            )["blocks"][0]["text"],
        )

    def test_publishing_new_version_retains_historical_version_chunks(self):
        source = self._create_doc(content=b"first")
        blocks = [{"type": "paragraph", "text": "First", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "engine-a"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")

        source.write_bytes(b"second")
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "engine-b"),
        ), mock.patch.object(pipeline, "_index_chunks"):
            pipeline._run_pipeline("doc-version-test")

        self.assertFalse(hasattr(pipeline, "_delete_inactive_index_versions"))

    def test_reparse_route_does_not_delete_active_index_before_staging(self):
        from api.routes import docs

        self._create_doc()
        with mock.patch.object(docs, "delete_doc_from_index") as delete_index, \
             mock.patch.object(docs, "enqueue_parse") as enqueue:
            response = docs.api_reparse("doc-version-test")

        delete_index.assert_not_called()
        enqueue.assert_called_once_with("doc-version-test")
        self.assertTrue(response.success)

    def test_failed_reparse_preserves_legacy_top_level_artifacts(self):
        from api.routes import docs

        self._create_doc()
        store.save_ir("doc-version-test", {"kind": "legacy"})
        store.save_preview_md("doc-version-test", "legacy preview")
        with mock.patch.object(docs, "enqueue_parse"):
            docs.api_reparse("doc-version-test")
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(
                pipeline,
                "_parse_with_mineru_or_fallback",
                side_effect=RuntimeError("parse failed"),
            ):
                pipeline._run_pipeline("doc-version-test")

        self.assertEqual({"kind": "legacy"}, store.load_ir("doc-version-test"))
        self.assertEqual("legacy preview", store.load_preview_md("doc-version-test"))

    def test_visibility_query_supports_existing_text_mappings_and_pre_key_chunks(self):
        from services import search

        doc_id = "doc-version-test"
        active_id = "a" * 64
        inactive_id = "b" * 64
        captured_bodies = []

        class CapturingElasticsearch:
            def search(self, *, index, body):
                captured_bodies.append(body)
                return {"hits": {"hits": []}}

        with mock.patch.object(search, "get_es", return_value=CapturingElasticsearch()), \
             mock.patch.object(search, "get_embeddings", return_value=[[0.1]]), \
             mock.patch.object(
                 search,
                 "index_visibility_snapshot",
                 return_value=([f"{doc_id}:{active_id}"], [doc_id]),
             ):
            search.search_local("query", k=2)

        visibility_filter = captured_bodies[0]["query"]["bool"]["filter"][0]
        self.assertEqual(visibility_filter, captured_bodies[1]["knn"]["filter"])
        serialized = json.dumps(visibility_filter)
        self.assertIn("visibility_key.keyword", serialized)
        self.assertIn("document_version_id.keyword", serialized)
        self.assertIn("doc_id.keyword", serialized)

        text_mapped = {"visibility_key", "document_version_id"}

        def exact_value(document, field):
            base = field.removesuffix(".keyword")
            if field in text_mapped:
                return None
            return document.get(base)

        def matches(clause, document):
            if "term" in clause:
                field, expected = next(iter(clause["term"].items()))
                return exact_value(document, field) == expected
            if "terms" in clause:
                field, expected = next(iter(clause["terms"].items()))
                return exact_value(document, field) in expected
            if "exists" in clause:
                return document.get(clause["exists"]["field"]) is not None
            boolean = clause["bool"]
            if not all(matches(item, document) for item in boolean.get("filter", [])):
                return False
            if not all(matches(item, document) for item in boolean.get("must", [])):
                return False
            if any(matches(item, document) for item in boolean.get("must_not", [])):
                return False
            should = boolean.get("should", [])
            required = boolean.get("minimum_should_match", 0 if not should else 1)
            return sum(matches(item, document) for item in should) >= required

        active_pre_key = {
            "doc_id": doc_id,
            "document_version_id": active_id,
        }
        inactive_pre_key = {
            "doc_id": doc_id,
            "document_version_id": inactive_id,
        }
        active_keyed = {
            "doc_id": doc_id,
            "document_version_id": active_id,
            "visibility_key": f"{doc_id}:{active_id}",
        }
        inactive_keyed = {
            "doc_id": doc_id,
            "document_version_id": inactive_id,
            "visibility_key": f"{doc_id}:{inactive_id}",
        }
        legacy_other = {"doc_id": "legacy-document"}
        stale_legacy = {"doc_id": doc_id}

        self.assertTrue(matches(visibility_filter, active_pre_key))
        self.assertFalse(matches(visibility_filter, inactive_pre_key))
        self.assertTrue(matches(visibility_filter, active_keyed))
        self.assertFalse(matches(visibility_filter, inactive_keyed))
        self.assertTrue(matches(visibility_filter, legacy_other))
        self.assertFalse(matches(visibility_filter, stale_legacy))

    def test_visibility_snapshot_uses_index_without_per_document_reads(self):
        doc_id = "doc-version-test"
        version_id = "c" * 64
        store.INDEX_FILE.write_text(
            json.dumps([{
                "id": doc_id,
                "current_version_id": version_id,
                "indexed_version_id": version_id,
            }]),
            encoding="utf-8",
        )

        class ScanningUploads:
            scanned = False

            def exists(self):
                return True

            def glob(self, pattern):
                self.scanned = True
                return []

        uploads = ScanningUploads()
        with mock.patch.object(store, "UPLOADS_DIR", uploads):
            snapshot = store.index_visibility_snapshot()

        self.assertFalse(uploads.scanned, "visibility snapshot must not scan meta.json")
        self.assertEqual(([f"{doc_id}:{version_id}"], [doc_id]), snapshot)

    def test_legacy_docs_index_row_is_migrated_once_from_current_metadata(self):
        doc_id = "doc-version-test"
        version_id = "d" * 64
        self._create_doc()
        meta = store.load_meta(doc_id)
        meta["current_version_id"] = version_id
        meta["indexed_version_id"] = version_id
        store.save_meta(meta)
        store.INDEX_FILE.write_text(
            json.dumps([{"id": doc_id, "status": "ready"}]), encoding="utf-8"
        )
        self.assertTrue(
            hasattr(store, "migrate_index_visibility"),
            "missing legacy visibility-index migration",
        )

        store.migrate_index_visibility()

        migrated = json.loads(store.INDEX_FILE.read_text("utf-8"))[0]
        self.assertEqual(version_id, migrated["current_version_id"])
        self.assertEqual(version_id, migrated["indexed_version_id"])
        self.assertEqual(([f"{doc_id}:{version_id}"], [doc_id]), store.index_visibility_snapshot())

    def test_malformed_visibility_index_fails_closed(self):
        from services import search

        self._create_doc()
        store.INDEX_FILE.write_text("{malformed", encoding="utf-8")
        captured_bodies = []

        class ExistingIndexElasticsearch:
            def search(self, *, index, body):
                captured_bodies.append(body)
                if "match_none" in json.dumps(body):
                    return {"hits": {"hits": []}}
                return {
                    "hits": {
                        "hits": [{
                            "_source": {
                                "doc_id": "doc-version-test",
                                "chunk_id": 1,
                                "content": "stale legacy chunk",
                            }
                        }]
                    }
                }

        with mock.patch.object(
            search, "get_es", return_value=ExistingIndexElasticsearch()
        ), mock.patch.object(search, "get_embeddings", return_value=[None]):
            results = search.search_local("query", k=2)

        self.assertEqual([], results)
        self.assertIn("match_none", json.dumps(captured_bodies[0]))


if __name__ == "__main__":
    unittest.main()
