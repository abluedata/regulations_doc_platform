"""一次性 backfill：为已 ready 的存量文档生成 evidence_spans.json。

从 .data/mineru_output 匹配 mineru job（解析时间窗 + 文本重叠），
把 original_content_list.json 精简为版本级证据坐标。

用法（backend 目录）：
  ..\\venv\\Scripts\\python.exe backfill_evidence_spans.py
  或 ..\\venv\\Scripts\\python.exe -m backfill_evidence_spans
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import evidence_spans  # noqa: E402


def main() -> int:
    results = evidence_spans.backfill_all_ready_docs()
    generated = 0
    for row in results:
        status = "OK  " if row.get("ok") else "SKIP"
        detail = (
            f"spans={row.get('spans')}"
            if row.get("ok")
            else row.get("error", "no mineru job match")
        )
        print(f"[{status}] {row.get('doc_id')}: {detail}")
        generated += 1 if row.get("ok") else 0
    print(f"done: {generated}/{len(results)} docs have evidence_spans.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
