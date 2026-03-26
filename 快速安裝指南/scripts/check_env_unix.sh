#!/usr/bin/env bash
# 環境檢查腳本 - AI 企業問答助理
# 適用：Linux / macOS

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
WARN=0

echo "========================================"
echo "  AI 企業問答助理 - 環境檢查 (Unix)"
echo "========================================"
echo ""

check() {
    local name="$1"
    local cmd="$2"
    local install_hint="$3"

    if eval "$cmd" > /dev/null 2>&1; then
        local version
        version=$(eval "$cmd" 2>&1 | head -1)
        echo -e "  ${GREEN}✓${NC} $name: $version"
        ((PASS++))
        return 0
    else
        echo -e "  ${RED}✗${NC} $name: 未安裝 — $install_hint"
        ((FAIL++))
        return 1
    fi
}

warn() {
    local name="$1"
    local cmd="$2"
    local hint="$3"

    if eval "$cmd" > /dev/null 2>&1; then
        local version
        version=$(eval "$cmd" 2>&1 | head -1)
        echo -e "  ${GREEN}✓${NC} $name: $version"
        ((PASS++))
    else
        echo -e "  ${YELLOW}?${NC} $name: $hint"
        ((WARN++))
    fi
}

echo "[1/8] Docker"
check "docker" "docker --version" "https://www.docker.com/products/docker-desktop/"

echo "[2/8] Docker Compose"
check "docker compose" "docker compose version" "已包含在 Docker Desktop 中"

echo "[3/8] Python"
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    PY_CMD=""
fi

if [ -n "$PY_CMD" ]; then
    version=$($PY_CMD --version 2>&1)
    echo -e "  ${GREEN}✓${NC} Python: $version (cmd: $PY_CMD)"
    ((PASS++))
else
    echo -e "  ${RED}✗${NC} Python: 未安裝 — brew install python3 或 apt install python3"
    ((FAIL++))
fi

echo "[4/8] psycopg2"
if [ -n "${PY_CMD:-}" ]; then
    if $PY_CMD -c "import psycopg2" > /dev/null 2>&1; then
        version=$($PY_CMD -c "import psycopg2; print(psycopg2.__version__)" 2>&1)
        echo -e "  ${GREEN}✓${NC} psycopg2: $version"
        ((PASS++))
    else
        echo -e "  ${RED}✗${NC} psycopg2: 未安裝 — pip3 install psycopg2-binary"
        ((FAIL++))
    fi
fi

echo "[5/8] Ollama"
check "ollama" "ollama --version" "curl -fsSL https://ollama.ai/install.sh | sh"

echo "[6/8] ngrok"
check "ngrok" "ngrok --version" "brew install ngrok/ngrok/ngrok (Mac) 或 apt install ngrok (Linux)"

echo "[7/8] Git"
check "git" "git --version" "brew install git (Mac) 或 apt install git (Linux)"

echo "[8/8] 磁碟空間"
if [[ "$OSTYPE" == "darwin"* ]]; then
    FREE=$(df -h / | awk 'NR==2 {print $4}')
else
    FREE=$(df -h / | awk 'NR==2 {print $4}')
fi
echo -e "  ${YELLOW}i${NC} 可用磁碟空間: $FREE (需要 >= 20GB)"

echo ""
echo "========================================"
echo "  結果: ${PASS} 項通過 / ${FAIL} 項失敗 / ${WARN} 項警告"
echo "========================================"

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}所有環境檢查通過！可以繼續安裝。${NC}"
    exit 0
else
    echo -e "  ${RED}請先安裝上述失敗的工具，再繼續安裝流程。${NC}"
    exit 1
fi
