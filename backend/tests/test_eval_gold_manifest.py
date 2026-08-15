from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval.metric_calculator import gold_files, load_gold_dataset, verify_gold_manifest


class GoldManifestTests(unittest.TestCase):
    def test_gold_set_has_at_least_30_locked_termination_agreements(self):
        gold_dir = BACKEND / "eval" / "gold"
        manifest = verify_gold_manifest(gold_dir)
        dataset = load_gold_dataset(gold_dir)

        self.assertGreaterEqual(len(gold_files(gold_dir)), 30)
        self.assertEqual("termination_agreement_gold_v1", manifest["dataset_id"])
        self.assertTrue(manifest["dataset_sha256"])
        self.assertTrue(all(doc["doc_type"] == "termination_agreement" for doc in dataset["documents"]))
        self.assertTrue(all(doc.get("annotation", {}).get("reviewer") for doc in dataset["documents"]))

    def test_regression_set_references_at_least_10_locked_gold_documents(self):
        gold_dir = BACKEND / "eval" / "gold"
        manifest = verify_gold_manifest(gold_dir)
        regression_set = json.loads((BACKEND / "eval" / "regression_set.json").read_text(encoding="utf-8"))
        locked_hashes = {entry["path"]: entry["sha256"] for entry in manifest["documents"]}

        self.assertGreaterEqual(len(regression_set["documents"]), 10)
        self.assertEqual(manifest["dataset_sha256"], regression_set["gold_dataset_sha256"])
        for entry in regression_set["documents"]:
            self.assertEqual(locked_hashes[entry["path"]], entry["sha256"])


if __name__ == "__main__":
    unittest.main()
