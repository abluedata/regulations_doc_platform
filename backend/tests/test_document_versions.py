"""Tests for immutable, deterministic document parse versions."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import threading
import types
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

    def test_failed_index_publication_leaves_journal_and_reads_fail_closed(self):
        source = self._create_doc()
        digest = store.source_sha256(source)
        old_id = store.compute_version_id(digest, "schema-v1", {"build": "old"})
        new_id = store.compute_version_id(digest, "schema-v1", {"build": "new"})
        for version_id, preview in ((old_id, "old preview"), (new_id, "new preview")):
            store.write_version_artifacts(
                "doc-version-test",
                version_id,
                {"version": version_id},
                preview,
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

        with mock.patch.object(
            store, "_save_index", side_effect=OSError("index write failed")
        ):
            with self.assertRaises(OSError):
                store.set_current_version(
                    "doc-version-test", new_id, indexed_version_id=new_id
                )

            raw_meta = json.loads(store.meta_path("doc-version-test").read_text("utf-8"))
            raw_index = json.loads(store.INDEX_FILE.read_text("utf-8"))[0]
            self.assertEqual(new_id, raw_meta["current_version_id"])
            self.assertEqual(old_id, raw_index["indexed_version_id"])
            self.assertTrue(
                list((store.INDEX_FILE.parent / "publication_journal").glob("*.json"))
            )
            with self.assertRaises(OSError):
                store.load_preview_md("doc-version-test")

    def test_pending_publication_reconciles_after_simulated_restart(self):
        source = self._create_doc()
        digest = store.source_sha256(source)
        old_id = store.compute_version_id(digest, "schema-v1", {"build": "old"})
        new_id = store.compute_version_id(digest, "schema-v1", {"build": "new"})
        for version_id, preview in ((old_id, "old preview"), (new_id, "new preview")):
            store.write_version_artifacts(
                "doc-version-test",
                version_id,
                {"version": version_id},
                preview,
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
        with mock.patch.object(
            store, "_save_index", side_effect=OSError("index write failed")
        ):
            with self.assertRaises(OSError):
                store.set_current_version(
                    "doc-version-test", new_id, indexed_version_id=new_id
                )

        with store._doc_locks_guard:
            store._doc_locks.clear()
        self._require_store_api("reconcile_pending_publications")
        store.reconcile_pending_publications()

        self.assertEqual("new preview", store.load_preview_md("doc-version-test"))
        self.assertEqual(
            ([f"doc-version-test:{new_id}"], ["doc-version-test"], []),
            store.index_visibility_snapshot(),
        )
        self.assertEqual(
            [],
            list((store.INDEX_FILE.parent / "publication_journal").glob("*.json")),
        )

    def test_backend_startup_reconciles_pending_publications(self):
        from api import main

        self.assertTrue(
            hasattr(main, "reconcile_document_publications"),
            "backend startup must reconcile durable publication journals",
        )
        self.assertIn(
            main.reconcile_document_publications,
            main.app.router.on_startup,
        )
        with mock.patch.object(store, "reconcile_pending_publications") as reconcile:
            main.reconcile_document_publications()
        reconcile.assert_called_once_with()

    def test_pending_publication_fails_closed_on_malformed_existing_index(self):
        source = self._create_doc()
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {"build": "new"})
        store.write_version_artifacts(
            "doc-version-test",
            version_id,
            {"version": version_id},
            "new preview",
            {
                "version_id": version_id,
                "source_sha256": digest,
                "parser_schema_version": "schema-v1",
                "parse_config": {},
                "status": "ready",
            },
        )
        with mock.patch.object(
            store, "_save_index", side_effect=OSError("index write failed")
        ):
            with self.assertRaises(OSError):
                store.set_current_version(
                    "doc-version-test", version_id, indexed_version_id=version_id
                )

        journal = next(
            (store.INDEX_FILE.parent / "publication_journal").glob("*.json")
        )
        store.INDEX_FILE.write_text("{malformed", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            store.reconcile_pending_publications()

        self.assertEqual("{malformed", store.INDEX_FILE.read_text("utf-8"))
        self.assertTrue(journal.is_file())

    def test_delete_resolves_pending_publication_without_resurrection(self):
        source = self._create_doc()
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {"build": "new"})
        store.write_version_artifacts(
            "doc-version-test",
            version_id,
            {"version": version_id},
            "new preview",
            {
                "version_id": version_id,
                "source_sha256": digest,
                "parser_schema_version": "schema-v1",
                "parse_config": {},
                "status": "ready",
            },
        )
        with mock.patch.object(
            store, "_save_index", side_effect=OSError("index write failed")
        ):
            with self.assertRaises(OSError):
                store.set_current_version(
                    "doc-version-test", version_id, indexed_version_id=version_id
                )

        stale_meta = json.loads(
            store.meta_path("doc-version-test").read_text("utf-8")
        )
        self.assertTrue(store.delete_doc("doc-version-test"))
        with self.assertRaises(RuntimeError):
            store.save_meta(stale_meta)
        self.assertEqual(([], [], []), store.index_visibility_snapshot())
        self.assertFalse(store.doc_dir("doc-version-test").exists())
        self.assertEqual(
            [],
            list((store.INDEX_FILE.parent / "publication_journal").glob("*.json")),
        )

    def test_successful_delete_removes_directory_before_index_row(self):
        self._create_doc()
        original_save_index = store._save_index

        def save_after_filesystem(items):
            self.assertFalse(store.doc_dir("doc-version-test").exists())
            return original_save_index(items)

        with mock.patch.object(store, "_save_index", side_effect=save_after_filesystem):
            self.assertTrue(store.delete_doc("doc-version-test"))

        self.assertEqual([], json.loads(store.INDEX_FILE.read_text("utf-8")))
        self.assertTrue(
            list((store.INDEX_FILE.parent / "deletion_tombstones").glob("*.json"))
        )

    def test_failed_delete_retains_directory_index_row_and_tombstone(self):
        self._create_doc()

        with mock.patch.object(
            store.shutil,
            "rmtree",
            side_effect=PermissionError("file is open"),
        ):
            with self.assertRaises(PermissionError):
                store.delete_doc("doc-version-test")

        self.assertTrue(store.doc_dir("doc-version-test").is_dir())
        self.assertEqual(
            ["doc-version-test"],
            [item["id"] for item in json.loads(store.INDEX_FILE.read_text("utf-8"))],
        )
        self.assertTrue(
            list((store.INDEX_FILE.parent / "deletion_tombstones").glob("*.json"))
        )

    def test_stale_writer_cannot_publish_after_failed_delete_starts(self):
        self._create_doc()
        stale_meta = store.load_meta("doc-version-test")
        delete_entered = threading.Event()
        release_delete = threading.Event()
        writer_started = threading.Event()
        delete_errors = []
        writer_errors = []

        def blocked_rmtree(*args, **kwargs):
            delete_entered.set()
            release_delete.wait(timeout=2)
            raise PermissionError("file is open")

        def delete_target():
            try:
                store.delete_doc("doc-version-test")
            except Exception as exc:
                delete_errors.append(exc)

        def writer_target():
            writer_started.set()
            try:
                store.save_meta(stale_meta)
            except Exception as exc:
                writer_errors.append(exc)

        with mock.patch.object(store.shutil, "rmtree", side_effect=blocked_rmtree):
            delete_thread = threading.Thread(target=delete_target)
            writer_thread = threading.Thread(target=writer_target)
            delete_thread.start()
            self.assertTrue(delete_entered.wait(timeout=2))
            writer_thread.start()
            self.assertTrue(writer_started.wait(timeout=2))
            writer_thread.join(timeout=0.1)
            self.assertTrue(writer_thread.is_alive(), "writer must wait for deletion lock")
            release_delete.set()
            delete_thread.join(timeout=2)
            writer_thread.join(timeout=2)

        self.assertIsInstance(delete_errors[0], PermissionError)
        self.assertEqual(1, len(writer_errors))
        self.assertIsInstance(writer_errors[0], RuntimeError)
        self.assertEqual(
            ["doc-version-test"],
            [item["id"] for item in json.loads(store.INDEX_FILE.read_text("utf-8"))],
        )

    def test_delete_waits_for_inflight_indexing_before_es_cleanup(self):
        from api.routes import docs

        self._create_doc()
        index_started = threading.Event()
        release_index = threading.Event()
        index_finished = threading.Event()
        cleanup_called = threading.Event()
        cleanup_after_index = []
        delete_errors = []

        def blocked_index(*args, **kwargs):
            index_started.set()
            release_index.wait(timeout=2)
            index_finished.set()

        def cleanup_index(doc_id):
            cleanup_after_index.append(index_finished.is_set())
            cleanup_called.set()

        def delete_target():
            try:
                docs.api_delete("doc-version-test")
            except Exception as exc:
                delete_errors.append(exc)

        blocks = [{"type": "paragraph", "text": "Published", "page": 1}]
        with mock.patch.object(
            pipeline,
            "_parse_with_mineru_or_fallback",
            return_value=(blocks, 1, "test-parser"),
        ), mock.patch.object(
            pipeline, "_index_chunks", side_effect=blocked_index
        ), mock.patch.object(
            docs, "delete_doc_from_index", side_effect=cleanup_index
        ):
            pipeline_thread = threading.Thread(
                target=pipeline._run_pipeline, args=("doc-version-test",)
            )
            delete_thread = threading.Thread(target=delete_target)
            pipeline_thread.start()
            self.assertTrue(index_started.wait(timeout=2))
            delete_thread.start()
            cleanup_called.wait(timeout=0.2)
            cleanup_was_early = cleanup_called.is_set()
            release_index.set()
            pipeline_thread.join(timeout=2)
            delete_thread.join(timeout=2)

        self.assertFalse(cleanup_was_early, "ES cleanup must wait for active indexing")
        self.assertEqual([True], cleanup_after_index)
        self.assertEqual([], delete_errors)
        self.assertFalse(store.doc_dir("doc-version-test").exists())

    def test_deletion_tombstone_survives_restart_and_rejects_write_paths(self):
        source = self._create_doc()
        stale_meta = store.load_meta("doc-version-test")
        digest = store.source_sha256(source)
        version_id = store.compute_version_id(digest, "schema-v1", {"retry": True})
        manifest = {
            "version_id": version_id,
            "source_sha256": digest,
            "parser_schema_version": "schema-v1",
            "parse_config": {},
            "status": "ready",
        }
        with mock.patch.object(
            store.shutil,
            "rmtree",
            side_effect=PermissionError("file is open"),
        ):
            with self.assertRaises(PermissionError):
                store.delete_doc("doc-version-test")

        with store._doc_locks_guard:
            store._doc_locks.clear()

        with self.assertRaises(RuntimeError):
            store.save_meta(stale_meta)
        self.assertIsNone(store.update_status("doc-version-test", "ready"))
        with self.assertRaises(RuntimeError):
            store.save_ir("doc-version-test", {"stale": True})
        with self.assertRaises(RuntimeError):
            store.save_preview_md("doc-version-test", "stale")
        with self.assertRaises(RuntimeError):
            store.write_version_artifacts(
                "doc-version-test",
                version_id,
                {"stale": True},
                "stale",
                manifest,
            )

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
             mock.patch.object(search, "get_embeddings", return_value=[None]), \
             mock.patch.object(search, "_visibility_v2_ready", True):
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

    def test_delete_route_keeps_es_when_local_deletion_fails(self):
        from api.routes import docs

        self._create_doc()
        with mock.patch.object(docs, "delete_doc_from_index") as delete_index, \
             mock.patch.object(
                 docs, "delete_doc", side_effect=PermissionError("file is open")
             ):
            with self.assertRaises(PermissionError):
                docs.api_delete("doc-version-test")

        delete_index.assert_not_called()

    def test_delete_route_retries_tombstoned_local_deletion(self):
        from api.routes import docs

        self._create_doc()
        with mock.patch.object(
            store.shutil,
            "rmtree",
            side_effect=PermissionError("file is open"),
        ):
            with self.assertRaises(PermissionError):
                store.delete_doc("doc-version-test")

        with mock.patch.object(docs, "delete_doc_from_index") as delete_index:
            response = docs.api_delete("doc-version-test")

        self.assertTrue(response.success)
        delete_index.assert_called_once_with("doc-version-test")
        self.assertFalse(store.doc_dir("doc-version-test").exists())
        self.assertEqual([], json.loads(store.INDEX_FILE.read_text("utf-8")))

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
            def __init__(self):
                self.mapping_calls = []
                self.backfill_calls = []
                self.indices = self
                self.records = [
                    {
                        "doc_id": doc_id,
                        "document_version_id": active_id,
                        "chunk_id": 1,
                        "content": "active pre-key",
                    },
                    {
                        "doc_id": doc_id,
                        "document_version_id": inactive_id,
                        "chunk_id": 1,
                        "content": "inactive pre-key",
                    },
                ]

            def get_mapping(self, *, index):
                return {
                    index: {
                        "mappings": {
                            "properties": {"visibility_key": {"type": "text"}}
                        }
                    }
                }

            def put_mapping(self, **kwargs):
                self.mapping_calls.append(kwargs)
                return {"acknowledged": True}

            def update_by_query(self, **kwargs):
                self.backfill_calls.append(kwargs)
                for record in self.records:
                    record["visibility_key_v2"] = (
                        f"{record['doc_id']}:{record['document_version_id']}"
                    )
                return {
                    "timed_out": False,
                    "failures": [],
                    "version_conflicts": 0,
                    "total": len(self.records),
                    "updated": len(self.records),
                    "noops": 0,
                }

            def search(self, *, index, body):
                captured_bodies.append(body)
                serialized = json.dumps(body)
                visible = [
                    {"_source": record}
                    for record in self.records
                    if record.get("visibility_key_v2") == f"{doc_id}:{active_id}"
                    and "visibility_key_v2" in serialized
                ]
                return {"hits": {"hits": visible}}

        fake_es = CapturingElasticsearch()
        with mock.patch.object(search, "get_es", return_value=fake_es), \
             mock.patch.object(search, "get_embeddings", return_value=[[0.1]]), \
             mock.patch.object(
                 search,
                 "index_visibility_snapshot",
                 return_value=([f"{doc_id}:{active_id}"], [doc_id], []),
             ), mock.patch.object(
                 search, "_visibility_v2_ready", False, create=True
             ):
            results = search.search_local("query", k=2)

        visibility_filter = captured_bodies[0]["query"]["bool"]["filter"][0]
        self.assertEqual(visibility_filter, captured_bodies[1]["knn"]["filter"])
        serialized = json.dumps(visibility_filter)
        self.assertIn("visibility_key_v2", serialized)
        self.assertNotIn("document_version_id.keyword", serialized)
        self.assertLessEqual(len(visibility_filter["bool"]["should"]), 2)
        self.assertTrue(fake_es.mapping_calls)
        self.assertTrue(fake_es.backfill_calls)
        self.assertEqual(["active pre-key"], [item["content"] for item in results])

    def test_visibility_filter_is_bounded_for_more_than_1024_active_documents(self):
        from services import search

        active_keys = [f"doc-{i}:{i:064x}" for i in range(1100)]
        doc_ids = [f"doc-{i}" for i in range(1100)]
        captured_bodies = []

        class ExistingElasticsearch:
            def __init__(self):
                self.indices = self

            def get_mapping(self, *, index):
                return {
                    index: {
                        "mappings": {
                            "properties": {
                                "visibility_key_v2": {"type": "keyword"}
                            }
                        }
                    }
                }

            def put_mapping(self, **kwargs):
                return None

            def update_by_query(self, **kwargs):
                return {
                    "timed_out": False,
                    "failures": [],
                    "version_conflicts": 0,
                    "total": 0,
                    "updated": 0,
                    "noops": 0,
                }

            def search(self, *, index, body):
                captured_bodies.append(body)
                return {"hits": {"hits": []}}

        with mock.patch.object(search, "get_es", return_value=ExistingElasticsearch()), \
             mock.patch.object(search, "get_embeddings", return_value=[None]), \
             mock.patch.object(
                 search,
                 "index_visibility_snapshot",
                 return_value=(active_keys, doc_ids, []),
             ), mock.patch.object(
                 search, "_visibility_v2_ready", False, create=True
             ):
            search.search_local("query", k=2)

        visibility_filter = captured_bodies[0]["query"]["bool"]["filter"][0]
        self.assertLessEqual(len(visibility_filter["bool"]["should"]), 2)
        self.assertIn(active_keys, [
            value
            for clause in visibility_filter["bool"]["should"]
            for value in (clause.get("terms") or {}).values()
        ])

    def test_visibility_mapping_or_backfill_failure_fails_closed(self):
        from services import search

        class FailingElasticsearch:
            def __init__(self, failure_mode):
                self.indices = self
                self.failure_mode = failure_mode
                self.captured_bodies = []

            def get_mapping(self, *, index):
                return {index: {"mappings": {"properties": {}}}}

            def put_mapping(self, **kwargs):
                if self.failure_mode == "mapping":
                    raise RuntimeError("mapping failed")
                return {"acknowledged": True}

            def update_by_query(self, **kwargs):
                if self.failure_mode == "backfill":
                    return {
                        "timed_out": False,
                        "failures": [{"cause": "script failed"}],
                        "version_conflicts": 0,
                        "total": 1,
                        "updated": 0,
                        "noops": 0,
                    }
                return {
                    "timed_out": False,
                    "failures": [],
                    "version_conflicts": 0,
                    "total": 0,
                    "updated": 0,
                    "noops": 0,
                }

            def search(self, *, index, body):
                self.captured_bodies.append(body)
                if "match_none" in json.dumps(body):
                    return {"hits": {"hits": []}}
                return {"hits": {"hits": [{"_source": {"content": "stale"}}]}}

        for failure_mode in ("mapping", "backfill"):
            with self.subTest(failure_mode=failure_mode):
                fake_es = FailingElasticsearch(failure_mode)
                with mock.patch.object(search, "get_es", return_value=fake_es), \
                     mock.patch.object(search, "get_embeddings", return_value=[None]), \
                     mock.patch.object(search, "_visibility_v2_ready", False):
                    results = search.search_local("query", k=2)

                self.assertEqual([], results)
                self.assertIn("match_none", json.dumps(fake_es.captured_bodies[0]))

    def test_visibility_snapshot_uses_index_without_per_document_reads(self):
        doc_id = "doc-version-test"
        version_id = "c" * 64
        store.INDEX_FILE.write_text(
            json.dumps([{
                "id": doc_id,
                "current_version_id": version_id,
                "indexed_version_id": version_id,
                "visibility_migrated": True,
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
        self.assertEqual(([f"{doc_id}:{version_id}"], [doc_id], []), snapshot)

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
        self.assertEqual(
            ([f"{doc_id}:{version_id}"], [doc_id], []),
            store.index_visibility_snapshot(),
        )

    def test_missing_visibility_index_with_existing_uploads_fails_closed(self):
        self._create_doc()
        store.INDEX_FILE.unlink()

        with self.assertRaises(RuntimeError):
            store.index_visibility_snapshot()

    def test_visibility_migration_rejects_missing_or_malformed_metadata(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                doc_id = f"migration-{malformed}"
                directory = store.doc_dir(doc_id)
                directory.mkdir(parents=True, exist_ok=True)
                if malformed:
                    (directory / "meta.json").write_text("{bad", encoding="utf-8")
                store.INDEX_FILE.write_text(
                    json.dumps([{"id": doc_id, "status": "ready"}]),
                    encoding="utf-8",
                )

                with self.assertRaises(RuntimeError):
                    store.migrate_index_visibility()

                persisted = json.loads(store.INDEX_FILE.read_text("utf-8"))[0]
                self.assertNotIn("current_version_id", persisted)
                self.assertNotIn("indexed_version_id", persisted)

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

    def test_index_chunks_installs_v2_mapping_before_existing_index_bulk(self):
        calls = []

        class ObjectResponse:
            def __init__(self, body):
                self.body = body

        class FakeIndices:
            def exists(self, *, index):
                calls.append("exists")
                return True

            def get_mapping(self, *, index):
                calls.append("get_mapping")
                return ObjectResponse({index: {"mappings": {"properties": {}}}})

            def put_mapping(self, **kwargs):
                calls.append("put_mapping")
                return ObjectResponse({"acknowledged": True})

        class FakeElasticsearch:
            def __init__(self, *args, **kwargs):
                self.indices = FakeIndices()

            def bulk(self, *, body, refresh):
                calls.append("bulk")
                return {
                    "errors": False,
                    "items": [{"index": {"status": 201}}],
                }

        fake_module = types.SimpleNamespace(Elasticsearch=FakeElasticsearch)
        chunks = [{
            "doc_id": "doc-version-test",
            "chunk_id": 1,
            "content": "content",
        }]
        with mock.patch.dict(sys.modules, {"elasticsearch": fake_module}), \
             mock.patch.object(pipeline, "_embed", return_value=[[0.1]]):
            pipeline._index_chunks(
                "doc-version-test", "e" * 64, {"filename": "f.pdf"}, chunks
            )

        self.assertIn("put_mapping", calls)
        self.assertLess(calls.index("put_mapping"), calls.index("bulk"))

    def test_index_chunks_rejects_short_embedding_response_before_bulk(self):
        bulk_called = False

        class FakeIndices:
            def exists(self, *, index):
                return True

            def get_mapping(self, *, index):
                return {
                    index: {
                        "mappings": {
                            "properties": {
                                "visibility_key_v2": {"type": "keyword"}
                            }
                        }
                    }
                }

        class FakeElasticsearch:
            def __init__(self, *args, **kwargs):
                self.indices = FakeIndices()

            def bulk(self, **kwargs):
                nonlocal bulk_called
                bulk_called = True

        fake_module = types.SimpleNamespace(Elasticsearch=FakeElasticsearch)
        with mock.patch.dict(sys.modules, {"elasticsearch": fake_module}), \
             mock.patch.object(pipeline, "_embed", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "embedding.*count"):
                pipeline._index_chunks(
                    "doc-version-test",
                    "2" * 64,
                    {"filename": "f.pdf"},
                    [{"doc_id": "doc-version-test", "chunk_id": 1, "content": "x"}],
                )

        self.assertFalse(bulk_called)

    def test_index_chunks_rejects_incomplete_object_bulk_responses(self):
        class ObjectResponse:
            def __init__(self, body):
                self.body = body

        class FakeIndices:
            def exists(self, *, index):
                return True

            def get_mapping(self, *, index):
                return ObjectResponse({
                    index: {
                        "mappings": {
                            "properties": {
                                "visibility_key_v2": {"type": "keyword"}
                            }
                        }
                    }
                })

        cases = {
            "item_error": {
                "errors": True,
                "items": [{"index": {"status": 500, "error": {"type": "boom"}}}],
            },
            "count_mismatch": {
                "errors": False,
                "items": [],
            },
            "malformed": {
                "errors": False,
                "items": [{"index": {"status": "201"}}],
            },
        }
        for name, response_body in cases.items():
            with self.subTest(name=name):
                class FakeElasticsearch:
                    def __init__(self, *args, **kwargs):
                        self.indices = FakeIndices()

                    def bulk(self, **kwargs):
                        return ObjectResponse(response_body)

                fake_module = types.SimpleNamespace(Elasticsearch=FakeElasticsearch)
                with mock.patch.dict(sys.modules, {"elasticsearch": fake_module}), \
                     mock.patch.object(pipeline, "_embed", return_value=[[0.1]]):
                    with self.assertRaisesRegex(RuntimeError, "bulk"):
                        pipeline._index_chunks(
                            "doc-version-test",
                            "3" * 64,
                            {"filename": "f.pdf"},
                            [{
                                "doc_id": "doc-version-test",
                                "chunk_id": 1,
                                "content": "x",
                            }],
                        )

    def test_index_chunks_rejects_incompatible_existing_v2_mapping_before_bulk(self):
        bulk_called = False

        class ObjectResponse:
            def __init__(self, body):
                self.body = body

        class FakeIndices:
            def exists(self, *, index):
                return True

            def get_mapping(self, *, index):
                return ObjectResponse({
                    index: {
                        "mappings": {
                            "properties": {"visibility_key_v2": {"type": "text"}}
                        }
                    }
                })

        class FakeElasticsearch:
            def __init__(self, *args, **kwargs):
                self.indices = FakeIndices()

            def bulk(self, **kwargs):
                nonlocal bulk_called
                bulk_called = True

        fake_module = types.SimpleNamespace(Elasticsearch=FakeElasticsearch)
        with mock.patch.dict(sys.modules, {"elasticsearch": fake_module}), \
             mock.patch.object(pipeline, "_embed", return_value=[[0.1]]):
            with self.assertRaisesRegex(RuntimeError, "visibility_key_v2.*keyword"):
                pipeline._index_chunks(
                    "doc-version-test",
                    "f" * 64,
                    {"filename": "f.pdf"},
                    [{"doc_id": "doc-version-test", "chunk_id": 1, "content": "x"}],
                )
        self.assertFalse(bulk_called)

    def test_index_chunks_requires_acknowledged_mapping_before_embedding(self):
        bulk_called = False

        class ObjectResponse:
            def __init__(self, body):
                self.body = body

        class FakeIndices:
            def exists(self, *, index):
                return True

            def get_mapping(self, *, index):
                return ObjectResponse({index: {"mappings": {"properties": {}}}})

            def put_mapping(self, **kwargs):
                return ObjectResponse({"acknowledged": False})

        class FakeElasticsearch:
            def __init__(self, *args, **kwargs):
                self.indices = FakeIndices()

            def bulk(self, **kwargs):
                nonlocal bulk_called
                bulk_called = True

        embed = mock.Mock(return_value=[[0.1]])
        fake_module = types.SimpleNamespace(Elasticsearch=FakeElasticsearch)
        with mock.patch.dict(sys.modules, {"elasticsearch": fake_module}), \
             mock.patch.object(pipeline, "_embed", embed):
            with self.assertRaisesRegex(RuntimeError, "acknowledged"):
                pipeline._index_chunks(
                    "doc-version-test",
                    "1" * 64,
                    {"filename": "f.pdf"},
                    [{"doc_id": "doc-version-test", "chunk_id": 1, "content": "x"}],
                )

        embed.assert_not_called()
        self.assertFalse(bulk_called)

    def test_object_response_partial_backfill_does_not_set_ready_and_retries(self):
        from services import search

        class ObjectResponse:
            def __init__(self, body):
                self.body = body

        class FakeIndices:
            def get_mapping(self, *, index):
                return ObjectResponse({index: {"mappings": {"properties": {}}}})

            def put_mapping(self, **kwargs):
                return ObjectResponse({"acknowledged": True})

        class FakeElasticsearch:
            def __init__(self):
                self.indices = FakeIndices()
                self.calls = 0

            def update_by_query(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ObjectResponse({
                        "timed_out": False,
                        "failures": [],
                        "version_conflicts": 1,
                        "total": 2,
                        "updated": 1,
                        "noops": 0,
                    })
                return ObjectResponse({
                    "timed_out": False,
                    "failures": [],
                    "version_conflicts": 0,
                    "total": 2,
                    "updated": 2,
                    "noops": 0,
                })

        fake_es = FakeElasticsearch()
        with mock.patch.object(search, "_visibility_v2_ready", False):
            with self.assertRaises(RuntimeError):
                search._ensure_visibility_v2(fake_es)
            self.assertFalse(search._visibility_v2_ready)
            search._ensure_visibility_v2(fake_es)
            self.assertTrue(search._visibility_v2_ready)
        self.assertEqual(2, fake_es.calls)

    def test_malformed_backfill_counters_do_not_set_ready(self):
        from services import search

        class FakeIndices:
            def get_mapping(self, *, index):
                return {
                    index: {
                        "mappings": {
                            "properties": {
                                "visibility_key_v2": {"type": "keyword"}
                            }
                        }
                    }
                }

        invalid_counters = (
            {"total": -1, "updated": -1, "noops": 0, "version_conflicts": 0},
            {"total": True, "updated": True, "noops": 0, "version_conflicts": 0},
        )
        for counters in invalid_counters:
            with self.subTest(counters=counters):
                fake_es = mock.Mock()
                fake_es.indices = FakeIndices()
                fake_es.update_by_query.return_value = {
                    "timed_out": False,
                    "failures": [],
                    **counters,
                }
                with mock.patch.object(search, "_visibility_v2_ready", False):
                    with self.assertRaises(RuntimeError):
                        search._ensure_visibility_v2(fake_es)
                    self.assertFalse(search._visibility_v2_ready)

    def test_legacy_filter_excludes_deleted_residual_chunks(self):
        from services import search

        self._create_doc(doc_id="kept-legacy")
        captured = []

        class FakeElasticsearch:
            def search(self, *, index, body):
                captured.append(body)
                serialized = json.dumps(body)
                if "visibility_key_v2" in serialized and "deleted-doc" not in serialized:
                    return {"hits": {"hits": []}}
                return {"hits": {"hits": [{
                    "_source": {
                        "doc_id": "deleted-doc",
                        "chunk_id": 1,
                        "content": "deleted residual",
                    }
                }]}}

        with mock.patch.object(search, "get_es", return_value=FakeElasticsearch()), \
             mock.patch.object(search, "get_embeddings", return_value=[None]), \
             mock.patch.object(search, "_visibility_v2_ready", True):
            results = search.search_local("query", k=2)

        self.assertEqual([], results)
        self.assertIn("kept-legacy", json.dumps(captured[0]))

    def test_valid_empty_installation_searches_match_none(self):
        from services import search

        store.INDEX_FILE.write_text("[]", encoding="utf-8")
        captured = []

        class FakeElasticsearch:
            def search(self, *, index, body):
                captured.append(body)
                if "match_none" in json.dumps(body):
                    return {"hits": {"hits": []}}
                return {"hits": {"hits": [{"_source": {"content": "orphan"}}]}}

        with mock.patch.object(search, "get_es", return_value=FakeElasticsearch()), \
             mock.patch.object(search, "get_embeddings", return_value=[None]), \
             mock.patch.object(search, "_visibility_v2_ready", True):
            results = search.search_local("query", k=2)

        self.assertEqual([], results)
        self.assertIn("match_none", json.dumps(captured[0]))


if __name__ == "__main__":
    unittest.main()
