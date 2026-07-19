#!/usr/bin/env bash
# 启动/检查 Elasticsearch 容器（Docker Desktop / Docker 必须先开）
# 用法:
#   bash scripts/start_es.sh
#   bash scripts/start_es.sh --restart
#   bash scripts/start_es.sh --image-tag 8.19.0 --password es123456 --port 9200

set -euo pipefail

CONTAINER_NAME="es-local"
IMAGE_TAG="8.19.0"
PORT=9200
RESTART=0
ENABLE_SECURITY=0   # 默认关闭 security，开发场景走 HTTP

while [[ $# -gt 0 ]]; do
    case "$1" in
        --restart) RESTART=1; shift ;;
        --image-tag) IMAGE_TAG="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --container-name) CONTAINER_NAME="$2"; shift 2 ;;
        --enable-security) ENABLE_SECURITY=1; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

cyan()    { printf '\033[36m%s\033[0m\n' "$1"; }
green()   { printf '\033[32m%s\033[0m\n' "$1"; }
yellow()  { printf '\033[33m%s\033[0m\n' "$1"; }
red()     { printf '\033[31m%s\033[0m\n' "$1"; }

cyan "==> Elasticsearch 启动检查"

# 1. Docker 是否运行
if ! docker ps >/dev/null 2>&1; then
    red "  XX  Docker 未运行，请先启动 Docker"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        yellow "      macOS: 打开 'Docker Desktop' 应用，或运行 open -a Docker"
    else
        yellow "      Linux: sudo systemctl start docker"
    fi
    exit 1
fi
green "  OK  Docker 已运行"

# 2. 端口已占用 -> 假定 ES 已在跑
es_ready() {
    curl -fsS -m 2 "http://127.0.0.1:${PORT}" >/dev/null 2>&1
}

if es_ready; then
    if [[ "$RESTART" -eq 1 ]]; then
        yellow "  ..  --restart 指定，停止现有 ES 容器"
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        sleep 2
    else
        green "  OK  ES 已在 :${PORT} 运行"
        exit 0
    fi
fi

# 3. 容器是否存在（已停止）
state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "")"
if [[ -z "$state" ]]; then
    yellow "  ..  Container does not exist, creating (image elasticsearch:${IMAGE_TAG})..."
    ENV_FLAGS=(-e "discovery.type=single-node")
    if [[ "$ENABLE_SECURITY" -eq 1 ]]; then
        ENV_FLAGS+=(-e "xpack.security.enabled=true" -e "ELASTIC_PASSWORD=es123456")
    else
        ENV_FLAGS+=(-e "xpack.security.enabled=false")
    fi
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p "${PORT}:9200" -p "9300:9300" \
        "${ENV_FLAGS[@]}" \
        -v esdata:/usr/share/elasticsearch/data \
        --restart unless-stopped \
        "docker.elastic.co/elasticsearch/elasticsearch:${IMAGE_TAG}" >/dev/null
elif [[ "$state" == "exited" ]]; then
    yellow "  ..  容器 ${CONTAINER_NAME} 已存在但停止，启动中..."
    docker start "$CONTAINER_NAME" >/dev/null
elif [[ "$state" == "running" ]]; then
    yellow "  ..  容器 running 但端口未响应，等待..."
else
    yellow "  !!  容器 ${CONTAINER_NAME} 状态异常: ${state}"
    docker restart "$CONTAINER_NAME" >/dev/null
fi

# 4. Wait for ES ready
yellow "  ..  Waiting for ES health..."
for i in $(seq 1 60); do
    if es_ready; then
        if [[ "$ENABLE_SECURITY" -eq 1 ]]; then
            green "  OK  ES ready on :${PORT} (user=elastic, password=es123456)"
        else
            green "  OK  ES ready on :${PORT} (security disabled, no auth)"
        fi
        exit 0
    fi
    sleep 2
    echo "      ... (${i}/60)"
done

red "  XX  ES 120s 内未就绪"
yellow "      查看日志: docker logs ${CONTAINER_NAME}"
exit 1
