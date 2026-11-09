#!/usr/bin/env bash
# Start, stop, restart, or check the local ResearchRelay service (macOS/Linux).
# Usage: scripts/researchrelay.sh {start|stop|restart|status} [port]
# Env:   RESEARCHRELAY_ENV (mamba env name, default "researchrelay")
set -euo pipefail

action="${1:-}"
port="${2:-8000}"
env_name="${RESEARCHRELAY_ENV:-researchrelay}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log="$root/.runtime/serve.log"

pids() {
  { lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true
    pgrep -f "researchrelay serve.*--port $port( |$)" 2>/dev/null || true
  } | sort -u
}

stop_service() {
  local found
  found="$(pids)"
  if [ -z "$found" ]; then echo "ResearchRelay is not running on port $port."; return 0; fi
  # shellcheck disable=SC2086
  kill $found 2>/dev/null || true
  for _ in $(seq 1 20); do [ -z "$(pids)" ] && break; sleep 0.5; done
  if [ -n "$(pids)" ]; then
    # shellcheck disable=SC2046
    kill -9 $(pids) 2>/dev/null || true
  fi
  echo "Stopped ResearchRelay on port $port."
}

start_service() {
  if [ -n "$(pids)" ]; then echo "Already running on port $port (PIDs: $(pids | tr '\n' ' '))."; return 0; fi
  mkdir -p "$root/.runtime"
  cd "$root"
  if command -v mamba >/dev/null 2>&1; then
    nohup mamba run -n "$env_name" researchrelay serve --port "$port" >"$log" 2>&1 &
  elif command -v researchrelay >/dev/null 2>&1; then
    nohup researchrelay serve --port "$port" >"$log" 2>&1 &
  else
    echo "Neither mamba nor researchrelay found on PATH." >&2; exit 1
  fi
  for _ in $(seq 1 30); do
    if curl -fs -o /dev/null "http://127.0.0.1:$port/workspace"; then
      echo "ResearchRelay running at http://127.0.0.1:$port/workspace (log: $log)"; return 0
    fi
    sleep 1
  done
  echo "Did not become ready; see $log" >&2; exit 1
}

case "$action" in
  start)   start_service ;;
  stop)    stop_service ;;
  restart) stop_service; start_service ;;
  status)
    if [ -n "$(pids)" ]; then echo "Running on port $port (PIDs: $(pids | tr '\n' ' '))."; else echo "Not running on port $port."; fi ;;
  *) echo "Usage: $0 {start|stop|restart|status} [port]" >&2; exit 2 ;;
esac
