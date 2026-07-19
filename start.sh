#!/usr/bin/env bash
# One-click start: ES(Docker) → mineru-api :8001 → adapter :8003 → API :8002 → frontend :5173
# macOS / Linux 版本（根目录入口，唯一脚本）
#
# Usage:
#   ./start.sh
#   ./start.sh --skip-frontend
#   ./start.sh --skip-mineru       # 跳过 MinerU（仅 ES + API + 前端）
#   ./start.sh --restart
#   ./start.sh --open-browser

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MINERU_PORT=8001
ADAPTER_PORT=8003
API_PORT=8002
FRONTEND_PORT=5173
SKIP_FRONTEND=0
SKIP_MINERU=0
RESTART=0
OPEN_BROWSER=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-frontend) SKIP_FRONTEND=1; shift ;;
        --skip-mineru) SKIP_MINERU=1; shift ;;
        --restart) RESTART=1; shift ;;
        --open-browser) OPEN_BROWSER=1; shift ;;
        --mineru-port) MINERU_PORT="$2"; shift 2 ;;
        --adapter-port) ADAPTER_PORT="$2"; shift 2 ;;
        --api-port) API_PORT="$2"; shift 2 ;;
        --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

# venv python path (macOS / Linux)
PY="$ROOT/venv/bin/python"
MINERU_API="$ROOT/venv/bin/mineru-api"

FRONTEND_DIR="$ROOT/frontend"
LOG_DIR="$ROOT/.data/logs"
PID_FILE="$LOG_DIR/services.pids.json"

mkdir -p "$LOG_DIR" "$ROOT/.data/mineru_output"

cyan()  { printf '\033[36m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }

step() { cyan "==> $1"; }
ok()   { green "  OK  $1"; }
warn() { yellow "  !!  $1"; }
fail() { red "  XX  $1"; }

http_ok() {
    curl -fsS -m 2 -o /dev/null "$1" 2>/dev/null
}

pids_on_port() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2}' | sort -u
    else
        ss -ltnp 2>/dev/null | awk -v p=":$1" '$4 ~ p {print $NF}' | sed 's/.*pid=\([0-9]*\).*/\1/' | sort -u
    fi
}

stop_port() {
    for pid in $(pids_on_port "$1"); do
        kill -9 "$pid" 2>/dev/null || true
        warn "stopped PID=$pid on port $1"
    done
}

start_logged() {
    local name="$1"; shift
    local logfile="$LOG_DIR/$name.out.log"
    local errfile="$LOG_DIR/$name.err.log"
    echo "  .. starting $name → log: $logfile"
    nohup "$@" >>"$logfile" 2>>"$errfile" &
    local pid=$!
    echo "$pid" > "$LOG_DIR/$name.pid"
    echo "$pid"
}

wait_http() {
    local name="$1" url="$2" retries="${3:-60}" delay="${4:-2}"
    for i in $(seq 1 "$retries"); do
        if http_ok "$url"; then
            ok "$name ready  $url"
            return 0
        fi
        echo "  ... waiting $name ($i/$retries)"
        sleep "$delay"
    done
    fail "$name not ready: $url"
    return 1
}

# -- precheck --
if [[ ! -f "$PY" ]]; then
    fail "Missing venv python: $PY"
    echo "  Create with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
if [[ "$SKIP_MINERU" -eq 0 && ! -f "$MINERU_API" ]]; then
    fail "Missing mineru-api: $MINERU_API"
    echo "  Run: ./venv/bin/pip install 'mineru[pipeline]==3.4.4'" >&2
    exit 1
fi
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
    [[ -f "$FRONTEND_DIR/package.json" ]] || { fail "Missing frontend: $FRONTEND_DIR"; exit 1; }
    command -v npm >/dev/null || { fail "npm not found. Install Node.js or use --skip-frontend"; exit 1; }
fi

echo ""
cyan "========================================"
cyan " regulations_doc_platform  start"
echo "  root: $ROOT"
echo "  venv: $PY"
cyan "========================================"
echo ""

# -- restart? --
PORTS=("$MINERU_PORT" "$ADAPTER_PORT" "$API_PORT")
[[ "$SKIP_FRONTEND" -eq 0 ]] && PORTS+=("$FRONTEND_PORT")
if [[ "$RESTART" -eq 1 ]]; then
    step "Restart: free ports ${PORTS[*]}"
    for p in "${PORTS[@]}"; do stop_port "$p"; done
    sleep 1
fi

STARTED=()

# 0) Elasticsearch
step "0/4 Elasticsearch"
ES_ARGS=""
[[ "$RESTART" -eq 1 ]] && ES_ARGS="--restart"
bash "$ROOT/scripts/start_es.sh" $ES_ARGS || fail "Elasticsearch not ready"

# 1) mineru-api
if [[ "$SKIP_MINERU" -eq 0 ]]; then
    step "1/4 mineru-api :$MINERU_PORT"
    mineru_url="http://127.0.0.1:$MINERU_PORT/health"
    if [[ "$RESTART" -eq 0 ]] && http_ok "$mineru_url"; then
        ok "mineru-api already running :$MINERU_PORT"
    else
        [[ "$RESTART" -eq 0 ]] && stop_port "$MINERU_PORT"
        export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"
        export MINERU_BACKEND="pipeline"
        export MINERU_API_URL="http://127.0.0.1:$MINERU_PORT"
        export MINERU_URL="http://127.0.0.1:$ADAPTER_PORT"
        export MINERU_FALLBACK="${MINERU_FALLBACK:-true}"
        export MINERU_FORMULA_ENABLE="${MINERU_FORMULA_ENABLE:-false}"
        export MINERU_TABLE_ENABLE="${MINERU_TABLE_ENABLE:-true}"
        export MINERU_ADAPTER_PORT="$ADAPTER_PORT"
        export MINERU_API_OUTPUT_ROOT="$ROOT/.data/mineru_output"
        export CUDA_VISIBLE_DEVICES=""
        start_logged mineru-api "$MINERU_API" --host 127.0.0.1 --port "$MINERU_PORT" --enable-vlm-preload false
    fi
    wait_http mineru-api "$mineru_url" 60 2 || warn "mineru-api not ready, see logs under $LOG_DIR"
fi

# 2) adapter
if [[ "$SKIP_MINERU" -eq 0 ]]; then
    step "2/4 adapter :$ADAPTER_PORT"
    adapter_url="http://127.0.0.1:$ADAPTER_PORT/health"
    if [[ "$RESTART" -eq 0 ]] && http_ok "$adapter_url"; then
        ok "adapter already running :$ADAPTER_PORT"
    else
        [[ "$RESTART" -eq 0 ]] && stop_port "$ADAPTER_PORT"
        start_logged adapter "$PY" -m mineru_service.server
    fi
    wait_http adapter "$adapter_url" 30 1 || warn "adapter not ready, see logs under $LOG_DIR"
fi

# 3) business API (cwd=backend)
step "3/4 business API :$API_PORT"
api_url="http://127.0.0.1:$API_PORT/api/docs"
api_docs_url="http://127.0.0.1:$API_PORT/docs"
if [[ "$RESTART" -eq 0 ]] && { http_ok "$api_url" || http_ok "$api_docs_url"; }; then
    ok "business API already running :$API_PORT"
else
    [[ "$RESTART" -eq 0 ]] && stop_port "$API_PORT"
    (cd "$ROOT/backend" && start_logged api "$PY" -m uvicorn api.main:app --host 127.0.0.1 --port "$API_PORT")
fi
wait_http business-api "$api_url" 30 1 || wait_http business-api "$api_docs_url" 5 1 || warn "business API not ready, see logs under $LOG_DIR"

# 4) frontend
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
    step "4/4 frontend :$FRONTEND_PORT"
    fe_url="http://127.0.0.1:$FRONTEND_PORT/"
    if [[ "$RESTART" -eq 0 ]] && http_ok "$fe_url"; then
        ok "frontend already running :$FRONTEND_PORT"
    else
        [[ "$RESTART" -eq 0 ]] && stop_port "$FRONTEND_PORT"
        (cd "$FRONTEND_DIR" && start_logged frontend npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT")
    fi
    wait_http frontend "$fe_url" 30 1 || warn "frontend not ready, see logs under $LOG_DIR"
fi

# save pid info
{
    echo "{"
    echo "  \"started_at\": \"$(date -u +%FT%TZ)\","
    echo "  \"root\": \"$ROOT\","
    echo "  \"urls\": {"
    echo "    \"es\":         \"http://127.0.0.1:9200\","
    echo "    \"mineru_api\": \"http://127.0.0.1:$MINERU_PORT/health\","
    echo "    \"adapter\":    \"http://127.0.0.1:$ADAPTER_PORT/health\","
    echo "    \"api\":        \"http://127.0.0.1:$API_PORT\","
    echo "    \"frontend\":   \"http://127.0.0.1:$FRONTEND_PORT/\""
    echo "  }"
    echo "}"
} > "$PID_FILE"

echo ""
cyan "========================================"
cyan " started"
echo "----------------------------------------"
echo "  Elasticsearch: http://127.0.0.1:9200"
echo "  MinerU API   : http://127.0.0.1:$MINERU_PORT/health"
echo "  Adapter      : http://127.0.0.1:$ADAPTER_PORT/health"
echo "  Business API : http://127.0.0.1:$API_PORT"
echo "  API docs     : http://127.0.0.1:$API_PORT/docs"
[[ "$SKIP_FRONTEND" -eq 0 ]] && green "  Frontend     : http://127.0.0.1:$FRONTEND_PORT/"
echo "----------------------------------------"
echo "  Logs         : $LOG_DIR"
echo "  Stop         : ./stop.sh"
cyan "========================================"
echo ""

if [[ "$OPEN_BROWSER" -eq 1 && "$SKIP_FRONTEND" -eq 0 ]]; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
        open "$fe_url"
    else
        xdg-open "$fe_url" 2>/dev/null || true
    fi
fi
