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

CONDA_ENV="${CONDA_ENV:-provedor-liquidez}"
# 8000 costuma estar ocupada nesta máquina por um container Docker
# (docker-proxy) que não é deste projeto -- 8787 evita a colisão.
BACKEND_PORT="${BACKEND_PORT:-8787}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# Locate conda's base install so we can source conda.sh and `conda activate`
# inside the setsid subshells below, even if this script's own shell never
# had `conda init` run for it.
find_conda_base() {
  local base=""
  if command -v conda >/dev/null 2>&1; then
    base="$(conda info --base 2>/dev/null)" || base=""
  fi
  if [ -n "$base" ]; then
    echo "$base"
    return
  fi
  for candidate in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3"; do
    if [ -x "$candidate/bin/conda" ]; then
      echo "$candidate"
      return
    fi
  done
}
CONDA_BASE="$(find_conda_base)"

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
  if [ -z "$CONDA_BASE" ] || ! [ -d "$CONDA_BASE/envs/$CONDA_ENV" ]; then
    echo "backend: no conda env '$CONDA_ENV' found -- run:" >&2
    echo "  conda env create -f environment.yml && cd backend && conda run -n $CONDA_ENV pip install -r requirements.txt" >&2
    exit 1
  fi
  if [ ! -f "$ROOT_DIR/backend/.env" ]; then
    echo "backend: aviso -- backend/.env não existe (copie de .env.example e defina GRAPH_API_KEY)," \
         "o servidor sobe mas as rotas de pool vão falhar" >&2
  fi
  echo "backend: starting on port $BACKEND_PORT..."
  ROOT_DIR="$ROOT_DIR" BACKEND_PORT="$BACKEND_PORT" CONDA_BASE="$CONDA_BASE" CONDA_ENV="$CONDA_ENV" \
    setsid bash -c '
      cd "$ROOT_DIR/backend"
      . "$CONDA_BASE/etc/profile.d/conda.sh"
      conda activate "$CONDA_ENV"
      exec uvicorn app.main:app --reload --port "$BACKEND_PORT"
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
    echo "frontend: no node_modules -- run 'conda run -n $CONDA_ENV npm install' inside frontend/ first" >&2
    exit 1
  fi
  if [ -z "$CONDA_BASE" ] || ! [ -d "$CONDA_BASE/envs/$CONDA_ENV" ]; then
    echo "frontend: no conda env '$CONDA_ENV' found -- run 'conda env create -f environment.yml' first" >&2
    exit 1
  fi
  echo "frontend: starting on port $FRONTEND_PORT (backend at http://localhost:$BACKEND_PORT)..."
  # Node comes from the conda env (environment.yml pins Node 24), so this is
  # always 18+ regardless of what (if anything) `node` resolves to system-wide.
  ROOT_DIR="$ROOT_DIR" FRONTEND_PORT="$FRONTEND_PORT" CONDA_BASE="$CONDA_BASE" CONDA_ENV="$CONDA_ENV" \
    VITE_API_BASE_URL="http://localhost:$BACKEND_PORT" \
    setsid bash -c '
      cd "$ROOT_DIR/frontend"
      . "$CONDA_BASE/etc/profile.d/conda.sh"
      conda activate "$CONDA_ENV"
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
