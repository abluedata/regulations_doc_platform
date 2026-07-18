"""上传 DOCX，确认解析引擎为 mineru pipeline。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8002/api"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    client = httpx.Client(proxy=None, trust_env=False, timeout=60)
    files = list((ROOT / "docs").glob("*.docx"))
    if not files:
        print("no docx")
        return 1
    path = files[0]
    print("upload", path)
    with path.open("rb") as f:
        r = client.post(
            f"{BASE}/docs/upload",
            files={
                "file": (
                    path.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    print("upload status", r.status_code, r.text)
    r.raise_for_status()
    doc_id = r.json()["id"]

    for i in range(180):
        time.sleep(1)
        d = client.get(f"{BASE}/docs/{doc_id}").json()
        item = d.get("item") or d
        status = item.get("status")
        print(
            f"poll {i+1}: status={status} engine={item.get('engine')} "
            f"chunks={item.get('chunk_count')} err={item.get('error')}"
        )
        if status in ("ready", "failed"):
            print(json.dumps(item, ensure_ascii=False, indent=2))
            if status != "ready":
                return 2
            engine = str(item.get("engine") or "")
            if "mineru" not in engine.lower():
                print("WARN: engine is not mineru:", engine)
                return 3
            print("OK: mineru pipeline path confirmed")
            return 0
    print("timeout")
    return 4


if __name__ == "__main__":
    sys.exit(main())
