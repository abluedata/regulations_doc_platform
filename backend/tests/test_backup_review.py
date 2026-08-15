from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_review import create_backup, restore_backup


class ReviewBackupTests(unittest.TestCase):
    def test_backup_and_restore_round_trip_with_manifest(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            data_dir = root / ".review_data"
            (data_dir / "jobs").mkdir(parents=True)
            (data_dir / "jobs" / "job-1.json").write_text(
                json.dumps({"job_id": "job-1", "status": "complete"}),
                encoding="utf-8",
            )
            (data_dir / "schema_version.json").write_text(
                json.dumps({"version": "0001_review_data_governance"}),
                encoding="utf-8",
            )

            archive = create_backup(data_dir, root / "backups")
            restored = root / "restored"
            manifest = restore_backup(archive, restored)

            self.assertEqual("0001_review_data_governance", manifest["migration_version"])
            self.assertEqual(
                {"job_id": "job-1", "status": "complete"},
                json.loads((restored / "jobs" / "job-1.json").read_text(encoding="utf-8")),
            )

    def test_restore_rejects_non_empty_target_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            data_dir = root / ".review_data"
            data_dir.mkdir()
            (data_dir / "state.json").write_text("{}", encoding="utf-8")
            archive = create_backup(data_dir, root / "backups")
            target = root / "target"
            target.mkdir()
            (target / "existing.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                restore_backup(archive, target)


if __name__ == "__main__":
    unittest.main()

