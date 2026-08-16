"""Import legacy review JSON records into the SQLite compatibility store.

The migration is additive: existing SQLite rows win on id collisions and the
legacy JSON tree is never modified or deleted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone


COLLECTIONS = (
    "batches", "rules", "templates", "configurations", "jobs", "findings",
    "decisions", "audit", "conversations", "exports", "hitl", "idempotency",
)


def migrate(source: Path, database: Path, *, apply: bool) -> dict[str, object]:
    if not source.exists():
        raise FileNotFoundError(source)
    if apply:
        database.parent.mkdir(parents=True, exist_ok=True)
        backup = database.with_name(
            f"{database.stem}.before-json-migration-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{database.suffix}"
        )
        if database.exists():
            shutil.copy2(database, backup)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS review_records (
                collection TEXT NOT NULL,
                id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (collection, id)
            )"""
        )
        counts: dict[str, int] = {}
        for collection in COLLECTIONS:
            imported = 0
            for path in sorted((source / collection).glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                record_id = str(payload.get("id") or path.stem)
                payload["id"] = record_id
                created_at = str(payload.get("created_at") or "")
                updated_at = str(payload.get("updated_at") or created_at)
                if apply:
                    result = connection.execute(
                        """INSERT OR IGNORE INTO review_records
                        (collection, id, payload, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)""",
                        (collection, record_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at, updated_at),
                    )
                    imported += int(result.rowcount == 1)
                else:
                    exists = connection.execute(
                        "SELECT 1 FROM review_records WHERE collection=? AND id=?",
                        (collection, record_id),
                    ).fetchone()
                    imported += int(exists is None)
            counts[collection] = imported
        if apply:
            connection.commit()
        return {"source": str(source), "database": str(database), "apply": apply, "importable": counts}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy .data/reviews JSON into platform.db")
    parser.add_argument("--source", default=".data/reviews")
    parser.add_argument("--database", default=".data/platform.db")
    parser.add_argument("--apply", action="store_true", help="write records; without this flag only report counts")
    args = parser.parse_args()
    print(json.dumps(migrate(Path(args.source), Path(args.database), apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
