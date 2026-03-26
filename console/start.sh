#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== JJ Command Console ==="
echo ""

# Activate virtualenv (create if missing)
if [ ! -d "server/venv" ]; then
  echo "Creating Python virtualenv..."
  python3 -m venv server/venv
  source server/venv/bin/activate
  pip install -r server/requirements.txt
else
  source server/venv/bin/activate
fi

# Start backend from console/ so 'server.main' resolves to console/server/main.py
echo "Starting backend on :8000..."
uvicorn server.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend on :5173..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "JJ Console running:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop"

trap "echo 'Shutting down...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" EXIT INT TERM
wait
