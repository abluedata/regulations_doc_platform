#!/usr/bin/env bash
# Stop all services: ES (optional) / mineru-api / adapter / API / frontend
# macOS / Linux 版本（根目录入口，唯一脚本）
# Usage:
#   ./stop.sh
#   ./stop.sh --with-es          # also stop the Docker ES container
#   ./stop.sh --mineru-port 8001 --adapter-port 8003 --api-port 8002 --frontend-port 5173

set -uo pipefail

MINERU_PORT=8001
ADAPTER_PORT=8003
API_PORT=8002
FRONTEND_PORT=5173
STOP_ES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-es) STOP_ES=1; shift ;;
        --mineru-port) MINERU_PORT="$2"; shift 2 ;;
        --adapter-port) ADAPTER_PORT="$2"; shift 2 ;;
        --api-port) API_PORT="$2"; shift 2 ;;
        --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

cyan()  { printf '\033[36m%s\033[0m\n' "$1"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.data/logs"

pids_on_port() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2}' | sort -u
    else
        ss -ltnp 2>/dev/null | awk -v p=":$1" '$4 ~ p {print $NF}' | sed 's/.*pid=\([0-9]*\).*/\1/' | sort -u
    fi
}

stop_port() {
    local pids
    pids="$(pids_on_port "$1")"
    if [[ -z "$pids" ]]; then
        echo "  port $1 : no listening process"
        return
    fi
    for pid in $pids; do
        local name
        name="$(ps -p "$pid" -o comm= 2>/dev/null || echo '?')"
        kill -9 "$pid" 2>/dev/null || true
        yellow "  port $1 : killed PID=$pid ($name)"
    done
}

cyan "==> Stopping regulations_doc_platform services"
for p in "$MINERU_PORT" "$ADAPTER_PORT" "$API_PORT" "$FRONTEND_PORT"; do
    stop_port "$p"
done

# clean up nohup pid files spawned by start.sh
if [[ -d "$LOG_DIR" ]]; then
    for pidfile in "$LOG_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        pid="$(cat "$pidfile" 2>/dev/null || echo '')"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
            yellow "  killed $(basename "$pidfile" .pid) PID=$pid"
        fi
        rm -f "$pidfile"
    done
fi

# optional: stop Docker ES container (keep data volume)
if [[ "$STOP_ES" -eq 1 ]]; then
    if docker ps >/dev/null 2>&1; then
        if docker inspect -f '{{.State.Status}}' es-local >/dev/null 2>&1; then
            docker stop es-local >/dev/null
            yellow "  ES container es-local stopped (data volume esdata preserved)"
        else
            echo "  ES container es-local not found, skip"
        fi
    else
        echo "  Docker not running, skip ES stop"
    fi
fi

green "==> done"
