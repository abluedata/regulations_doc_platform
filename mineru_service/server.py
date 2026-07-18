"""
平台侧 MinerU 适配 HTTP 服务。

默认：
  监听 127.0.0.1:8003
  上游 mineru-api: 127.0.0.1:8001
  backend=pipeline（CPU）

启动（统一 venv）：
  set MINERU_MODEL_SOURCE=modelscope
  set CUDA_VISIBLE_DEVICES=
  # 终端1：
  venv/Scripts/mineru-api.exe --host 127.0.0.1 --port 8001 --enable-vlm-preload false
  # 终端2：
  venv/Scripts/python.exe -m mineru_service.server
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证项目根在 path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
import uvicorn

from mineru_service.adapter import (
    MINERU_API_URL,
    MINERU_BACKEND,
    health_upstream,
    parse_file_bytes,
)

app = FastAPI(
    title="MinerU Adapter (pipeline/CPU)",
    version="1.0.0",
    description="将官方 mineru-api 适配为本平台 /parse 约定",
)


@app.get("/health")
def health():
    up = health_upstream()
    return {
        "status": "ok" if up.get("ok") else "degraded",
        "backend": MINERU_BACKEND,
        "upstream": up,
    }


@app.post("/parse")
async def parse(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        result = parse_file_bytes(
            filename=file.filename,
            content=data,
            content_type=file.content_type,
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MinerU 解析失败: {e}") from e


def main() -> None:
    host = os.environ.get("MINERU_ADAPTER_HOST", "127.0.0.1")
    port = int(os.environ.get("MINERU_ADAPTER_PORT", "8003"))
    print(f"MinerU adapter on http://{host}:{port}")
    print(f"  upstream: {MINERU_API_URL}")
    print(f"  backend : {MINERU_BACKEND}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
