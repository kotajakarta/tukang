#!/usr/bin/env bash
set -e

# tuKang Unified Runner
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}==========================================================${NC}"
echo -e "${GREEN}    tuKang: Agentless Multi-Server Linux Controller   ${NC}"
echo -e "${BLUE}==========================================================${NC}"

# Check prerequisites
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] python3 is required but not installed.${NC}"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo -e "${RED}[ERROR] Node.js is required but not installed.${NC}"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo -e "${RED}[ERROR] npm is required but not installed.${NC}"
    exit 1
fi

# Track spawned background PIDs
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}-> Stopping tuKang services...${NC}"
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    kill $(jobs -p) 2>/dev/null || true
    echo -e "${GREEN}[OK] tuKang shutdown cleanly.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 1. Start Python FastAPI Backend
echo -e "${BLUE}-> [1/2] Starting Backend API & WebSocket Hub...${NC}"
export PYTHONPATH="$DIR/backend:$PYTHONPATH"
python3 -m uvicorn app.main:app --app-dir "$DIR/backend" --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

sleep 1

# 2. Setup and Start Frontend Vite Server
echo -e "${BLUE}-> [2/2] Preparing Frontend (React + Vite + AntD)...${NC}"
cd "$DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}-> Installing frontend dependencies (first-time setup)...${NC}"
    npm install
fi

echo -e "${GREEN}-> Starting Frontend on http://localhost:3000${NC}"
npm run dev -- --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}==========================================================${NC}"
echo -e "${GREEN} tuKang is up and running!                            ${NC}"
echo -e " - Web Dashboard:  ${BLUE}http://localhost:3000${NC}"
echo -e " - Backend API:    ${BLUE}http://localhost:8000/api/health${NC}"
echo -e " - API Docs:       ${BLUE}http://localhost:8000/docs${NC}"
echo -e "${GREEN}==========================================================${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop all services.${NC}"
echo ""

wait
