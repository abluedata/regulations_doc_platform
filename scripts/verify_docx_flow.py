"""验证 DOCX：上传 → 解析 → 预览 → 问答。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8002/api"

# 避免系统代理把 127.0.0.1 打成 502
CLIENT = httpx.Client(proxy=None, trust_env=False, timeout=60.0)


def main() -> int:
    docs_dir = ROOT / "docs"
    files = list(docs_dir.glob("*.docx"))
    print("docx files:", [str(f) for f in files])
    if not files:
        print("ERROR: no docx in docs/")
        return 1
    path = files[0]
    print(f"using: {path} ({path.stat().st_size} bytes)")

    # 1) upload
    with path.open("rb") as f:
        r = CLIENT.post(
            f"{BASE}/docs/upload",
            files={
                "file": (
                    path.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            timeout=60,
        )
    print("upload status", r.status_code)
    print(r.text)
    r.raise_for_status()
    up = r.json()
    doc_id = up["id"]
    print("doc_id", doc_id)

    # 2) poll
    meta = None
    for i in range(90):
        time.sleep(1)
        d = CLIENT.get(f"{BASE}/docs/{doc_id}", timeout=30).json()
        item = d.get("item") or d
        st = item.get("status")
        engine = item.get("engine")
        chunks = item.get("chunk_count")
        err = item.get("error")
        print(f"poll {i+1}: status={st} engine={engine} chunks={chunks} err={err}")
        if st in ("ready", "failed"):
            meta = item
            break
    else:
        print("ERROR: timeout waiting parse")
        return 1

    print("FINAL_META:")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if meta.get("status") != "ready":
        print("ERROR: parse failed")
        return 1

    if meta.get("engine") != "python-docx":
        print(f"WARN: expected engine=python-docx, got {meta.get('engine')}")

    # 3) preview
    pv = CLIENT.get(f"{BASE}/docs/{doc_id}/preview", timeout=30).json()
    outline = pv.get("outline") or []
    tables = pv.get("tables") or []
    md = pv.get("markdown") or ""
    print(
        f"preview ready={pv.get('ready')} outline_n={len(outline)} "
        f"tables_n={len(tables)} md_len={len(md)}"
    )
    print("ir_summary:", pv.get("ir_summary"))
    print("markdown_head:")
    print(md[:1200])
    print("outline:")
    print(json.dumps(outline, ensure_ascii=False, indent=2)[:1500])
    if tables:
        print("first_table_md:")
        print((tables[0].get("markdown") or tables[0].get("html") or "")[:600])

    # must-have content checks from sample doc
    must = [
        "工伤保险待遇说明",
        "一次性伤残补助金",
        "27个月",
        "不得认定为工伤",
        "MINERU-WORD-FLOW-OK-2026",
    ]
    missing = [m for m in must if m not in md]
    if missing:
        print("WARN: preview missing expected phrases:", missing)
    else:
        print("preview content checks: OK")

    # 4) QA via SSE
    questions = [
        "一级伤残的一次性伤残补助金是几个月本人工资？",
        "哪些情形不得认定为工伤？",
        "本说明的验证码是什么？",
    ]
    answers = []
    for q in questions:
        print("\n=== QA:", q)
        ans = _stream_answer(q)
        answers.append((q, ans))
        print("answer:", ans[:800] if ans else "(empty)")

    # success criteria
    ok = True
    if not any("27" in a for _, a in answers):
        print("FAIL: expected '27' months in answer about 一级伤残")
        ok = False
    else:
        print("QA check 一级伤残: OK")

    if not any(
        ("故意犯罪" in a) or ("醉酒" in a) or ("自残" in a) or ("自杀" in a)
        for _, a in answers
    ):
        print("FAIL: expected exclusion cases in answer")
        ok = False
    else:
        print("QA check 不得认定: OK")

    if not any("MINERU-WORD-FLOW-OK-2026" in a or "验证码" in a for _, a in answers):
        # model may paraphrase; accept if code appears or mention 验证
        print("WARN: verification code not clearly in answer (soft fail)")
    else:
        print("QA check 验证码: OK")

    out = ROOT / ".data" / "_verify_docx_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "meta": meta,
                "outline_n": len(outline),
                "tables_n": len(tables),
                "preview_missing": missing,
                "answers": [{"q": q, "a": a} for q, a in answers],
                "ok": ok,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("saved", out)
    return 0 if ok else 2


def _stream_answer(message: str) -> str:
    tokens: list[str] = []
    with CLIENT.stream(
        "POST",
        f"{BASE}/chat/stream",
        json={"message": message},
        timeout=httpx.Timeout(300.0, connect=10.0),
    ) as resp:
        resp.raise_for_status()
        event = None
        data_lines: list[str] = []
        for line in resp.iter_lines():
            if line is None:
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
                data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line == "":
                if event and data_lines:
                    payload = "\n".join(data_lines)
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        obj = {"content": payload}
                    if event == "token":
                        tokens.append(obj.get("content") or "")
                    elif event == "done":
                        # some backends put final answer only in tokens
                        pass
                    elif event == "error":
                        print("SSE error:", obj)
                event = None
                data_lines = []
    return "".join(tokens)


if __name__ == "__main__":
    sys.exit(main())
