"""Tests for document parse progress reporting (queue → ready)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.knowledge import document_pipeline as pipeline
from services.knowledge import document_store as store


class TestParseProgress(unittest.TestCase):
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

    def _create_doc(self, doc_id: str = "doc-progress-test", content: bytes = b"source"):
        directory = store.doc_dir(doc_id)
        directory.mkdir(parents=True, exist_ok=True)
        original = directory / "original.pdf"
        original.write_bytes(content)
        store.save_meta(
            {
                "id": doc_id,
                "filename": "a.pdf",
                "stored_name": "original.pdf",
                "title": "A",
                "ext": "pdf",
                "mime": "application/pdf",
                "status": "queued",
            }
        )
        return directory

    def test_status_transitions_write_default_progress(self):
        self._create_doc()
        for status, expected in [
            ("queued", 65),
            ("parsing", 70),
            ("normalizing", 74),
            ("chunking", 80),
            ("indexing", 90),
            ("ready", 100),
            ("failed", 0),
        ]:
            store.update_status("doc-progress-test", status)
            meta = json.loads((store.doc_dir("doc-progress-test") / "meta.json").read_text("utf-8"))
            self.assertEqual(meta["progress"], expected, f"status={status}")

    def test_update_status_preserves_explicit_progress(self):
        self._create_doc()
        store.update_status("doc-progress-test", "parsing")
        store.update_status("doc-progress-test", "parsing", progress=77)
        meta = json.loads((store.doc_dir("doc-progress-test") / "meta.json").read_text("utf-8"))
        self.assertEqual(meta["progress"], 77)
        self.assertEqual(meta["status"], "parsing")

    def test_progress_ticker_climbs_during_parsing_and_stops(self):
        self._create_doc()
        stop = __import__("threading").Event()
        updates = []
        ticker = pipeline._progress_ticker("doc-progress-test", stop, interval=0.01, on_update=updates.append)
        ticker.start()
        ticker.join(timeout=0.15)
        stop.set()
        ticker.join(timeout=2)
        self.assertFalse(ticker.is_alive())
        self.assertTrue(len(updates) >= 2, f"updates={updates}")
        self.assertTrue(all(70 <= p <= 79 for p in updates), f"updates={updates}")
        self.assertEqual(updates, sorted(updates))

    def test_progress_reported_in_doc_meta_and_api_item(self):
        self._create_doc()
        store.update_status("doc-progress-test", "parsing", progress=75)
        item = store.load_meta("doc-progress-test")
        self.assertEqual(item["progress"], 75)


if __name__ == "__main__":
    unittest.main()
