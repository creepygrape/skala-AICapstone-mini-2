# Sourced by run_backend.sh / run_frontend.sh. free_port <port>:
# stop whatever listens on the port (SIGTERM first so lifespan cleanup can run, then SIGKILL).
free_port() {
    local port="$1" pids pid
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
    [ -z "$pids" ] && return 0
    for pid in $pids; do
        echo "Port ${port} is in use: stopping PID ${pid} ($(ps -o command= -p "$pid" 2>/dev/null | cut -c1-80))"
        kill "$pid" 2>/dev/null || true
    done
    for _ in $(seq 1 20); do
        lsof -ti "tcp:${port}" -sTCP:LISTEN >/dev/null 2>&1 || return 0
        sleep 0.5
    done
    for pid in $(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true); do
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 0.5
}
