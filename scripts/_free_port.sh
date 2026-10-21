# Sourced by run_backend.sh / run_frontend.sh. free_port <port>:
# stop whatever listens on the port (SIGTERM first so lifespan cleanup can run, then SIGKILL).
# On Windows (Git Bash) there is no lsof/SIGTERM: netstat + taskkill (forceful) are used instead.
_port_pids() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true
    else
        netstat -ano 2>/dev/null | tr -d '\r' |
            awk -v p=":${port}" '$1=="TCP" && $2 ~ p"$" && $4=="LISTENING" {print $5}' | sort -u
    fi
}

free_port() {
    local port="$1" pids pid
    pids="$(_port_pids "$port")"
    [ -z "$pids" ] && return 0
    if ! command -v lsof >/dev/null 2>&1; then
        for pid in $pids; do
            echo "Port ${port} is in use: stopping PID ${pid}"
            taskkill //F //PID "$pid" >/dev/null 2>&1 || true
        done
        sleep 0.5
        return 0
    fi
    for pid in $pids; do
        echo "Port ${port} is in use: stopping PID ${pid} ($(ps -o command= -p "$pid" 2>/dev/null | cut -c1-80))"
        kill "$pid" 2>/dev/null || true
    done
    for _ in $(seq 1 20); do
        [ -z "$(_port_pids "$port")" ] && return 0
        sleep 0.5
    done
    for pid in $(_port_pids "$port"); do
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 0.5
}
