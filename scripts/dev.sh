#!/usr/bin/env bash
# Start/stop the local dev servers (backend FastAPI + frontend Vite).
#
# Usage:
#   scripts/dev.sh start    # start backend + frontend (no-op if already running)
#   scripts/dev.sh stop     # stop backend + frontend
#   scripts/dev.sh restart
#   scripts/dev.sh status
#   scripts/dev.sh logs     # tail both logs (Ctrl-C to stop tailing, servers keep running)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.dev"
mkdir -p "$RUN_DIR"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

NODE_VERSION="${NODE_VERSION:-lts/*}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

is_running() {
  local pid_file="$1"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# setsid puts the process in its own session/process group, with pgid ==
# its own pid. That lets `stop` kill the whole tree (uvicorn+reloader,
# vite+esbuild, etc.) via `kill -- -PID` instead of just the top-level
# wrapper.
start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    echo "backend: already running (pid $(cat "$BACKEND_PID_FILE"))"
    return
  fi
  if [ ! -x "$ROOT_DIR/backend/.venv/bin/uvicorn" ]; then
    echo "backend: no venv at backend/.venv -- run:" >&2
    echo "  cd backend && uv venv --python 3.12 .venv && uv pip install -r requirements.txt" >&2
    exit 1
  fi
  if [ ! -f "$ROOT_DIR/backend/.env" ]; then
    echo "backend: aviso -- backend/.env não existe (copie de .env.example e defina GRAPH_API_KEY)," \
         "o servidor sobe mas as rotas de pool vão falhar" >&2
  fi
  echo "backend: starting on port $BACKEND_PORT..."
  ROOT_DIR="$ROOT_DIR" BACKEND_PORT="$BACKEND_PORT" \
    setsid bash -c '
      cd "$ROOT_DIR/backend"
      exec .venv/bin/uvicorn app.main:app --reload --port "$BACKEND_PORT"
    ' > "$BACKEND_LOG" 2>&1 &
  echo $! > "$BACKEND_PID_FILE"
  echo "backend: started (pid $!), logs: $BACKEND_LOG"
}

start_frontend() {
  if is_running "$FRONTEND_PID_FILE"; then
    echo "frontend: already running (pid $(cat "$FRONTEND_PID_FILE"))"
    return
  fi
  if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo "frontend: no node_modules -- run 'cd frontend && npm install' first" >&2
    exit 1
  fi
  echo "frontend: starting on port $FRONTEND_PORT (backend at http://localhost:$BACKEND_PORT)..."
  # Vite needs Node 18+; this machine's default `node` may resolve to an
  # older version, which fails with a confusing TypeScript SyntaxError.
  # nvm use here makes that a non-issue for this script.
  ROOT_DIR="$ROOT_DIR" NODE_VERSION="$NODE_VERSION" FRONTEND_PORT="$FRONTEND_PORT" \
    VITE_API_BASE_URL="http://localhost:$BACKEND_PORT" \
    setsid bash -c '
      cd "$ROOT_DIR/frontend"
      export NVM_DIR="$HOME/.nvm"
      [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
      command -v nvm >/dev/null && nvm use "$NODE_VERSION" >/dev/null
      exec npm run dev -- --port "$FRONTEND_PORT"
    ' > "$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PID_FILE"
  echo "frontend: started (pid $!), logs: $FRONTEND_LOG"
}

stop_one() {
  local name="$1" pid_file="$2"
  if ! is_running "$pid_file"; then
    echo "$name: not running"
    rm -f "$pid_file"
    return
  fi
  local pid
  pid="$(cat "$pid_file")"
  # setsid made this pid its own process group leader, so -PID kills the
  # whole tree (uvicorn+reloader, vite+esbuild), not just the wrapper.
  echo "$name: stopping (pid $pid)..."
  kill -TERM "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    is_running "$pid_file" || break
    sleep 0.5
  done
  if is_running "$pid_file"; then
    echo "$name: still running, sending SIGKILL"
    kill -KILL "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  echo "$name: stopped"
}

status_one() {
  local name="$1" pid_file="$2"
  if is_running "$pid_file"; then
    echo "$name: running (pid $(cat "$pid_file"))"
  else
    echo "$name: stopped"
  fi
}

cmd="${1:-}"
case "$cmd" in
  start)
    start_backend
    start_frontend
    ;;
  stop)
    stop_one "frontend" "$FRONTEND_PID_FILE"
    stop_one "backend" "$BACKEND_PID_FILE"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    status_one "backend" "$BACKEND_PID_FILE"
    status_one "frontend" "$FRONTEND_PID_FILE"
    ;;
  logs)
    tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
