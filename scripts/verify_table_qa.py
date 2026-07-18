"""表格问答端到端验证脚本。

POST /api/chat/stream message="待遇标准"，解析 SSE，断言包含原文表格、伤残等级、27个月及表格管道符。
"""
from __future__ import annotations

import json
import os
import sys

import httpx


API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8002")
URL = f"{API_BASE}/api/chat/stream"

# 避免系统代理把 127.0.0.1 打成 502；超时 180s
CLIENT = httpx.Client(
    proxy=None,
    trust_env=False,
    timeout=httpx.Timeout(180.0, connect=30.0),
)


def main() -> int:
    payload = {"message": "待遇标准", "history": []}
    print(f"POST {URL}")
    print(f"payload: {json.dumps(payload, ensure_ascii=False)}")

    tokens: list[str] = []
    errors: list[dict] = []

    try:
        with CLIENT.stream("POST", URL, json=payload) as resp:
            resp.raise_for_status()
            event: str | None = None
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
                    if data_lines:
                        payload_str = "\n".join(data_lines)
                        try:
                            obj = json.loads(payload_str)
                        except json.JSONDecodeError:
                            obj = {"content": payload_str}
                        # 收集 token 内容：event token 或任意含 content 字段的 data
                        if isinstance(obj, dict):
                            content = obj.get("content")
                            if event == "token" or (content is not None):
                                if content:
                                    tokens.append(str(content))
                            if event == "error":
                                errors.append(obj)
                    event = None
                    data_lines = []
    except Exception as e:
        print(f"ERROR: stream failed: {e}")
        return 1

    full_text = "".join(tokens)
    print(f"received tokens: {len(tokens)}, full_text len: {len(full_text)}")
    if errors:
        print("collected error events:", errors)

    # 断言
    check_table_header = "原文表格" in full_text or "## 原文表格" in full_text
    check_injury = "伤残等级" in full_text
    check_27 = ("27" in full_text) and ("27个月" in full_text or "27 个月" in full_text)
    pipe_count = full_text.count("|")
    check_pipes = pipe_count >= 6

    results = [
        ("原文表格 / ## 原文表格", check_table_header),
        ("伤残等级", check_injury),
        ('"27" and ("27个月" or "27 个月")', check_27),
        (f'full_text.count("|") >= 6 (actual={pipe_count})', check_pipes),
    ]

    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name}")

    if errors:
        print("FAIL: error events received during stream")
        all_ok = False
    else:
        all_ok = all(ok for _, ok in results)

    if all_ok:
        print("OK: table QA e2e verification passed")
        return 0
    else:
        # 打印关键片段便于诊断
        head = full_text[:800]
        tail = full_text[-800:] if len(full_text) > 800 else ""
        print("FAIL: table QA e2e verification failed")
        print("--- head ---")
        print(head)
        if tail:
            print("--- tail ---")
            print(tail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
