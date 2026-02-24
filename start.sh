#!/usr/bin/env bash
# Start backend (FastAPI) and frontend (Astro) for the Strudel AI Copilot.
# Run from project root: ./start.sh
# Press Ctrl+C to stop both.

set -e
cd "$(dirname "$0")"

BACKEND_PID=""
cleanup() {
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup SIGINT SIGTERM

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Prefer python3 for portability (e.g. macOS)
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
  PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
  PYTHON_CMD="python"
else
  echo "Error: python or python3 not found in PATH."
  exit 1
fi

echo "Starting backend at http://localhost:8000 ..."
$PYTHON_CMD -m uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

sleep 3
if ! curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q 200; then
  echo ""
  echo "Warning: Backend may not have started. If the copilot does nothing:"
  echo "  1. Ensure backend/.env has OPENAI_API_KEY=sk-..."
  echo "  2. In another terminal run: source .venv/bin/activate && $PYTHON_CMD -m uvicorn backend.main:app --reload --port 8000"
  echo "     and check for errors."
  echo ""
fi

echo "Starting frontend at http://localhost:4321 ..."
echo "Press Ctrl+C to stop both."
pnpm run start
