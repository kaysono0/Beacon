#!/bin/bash
# Beacon Mac Test Console 手工环境：一个 Server、一个 App、三家真实 SDK。
#
#   up       在 tmux 中启动统一 Server 与 Console App
#   down     优雅停止 Server、回收全部 Agent，并删除 tmux 会话
#   status   查看 tmux 窗口与 :8000 端口
#   server   仅启动统一 Server（普通终端回退路径）
#   app      仅启动 Console App（普通终端回退路径）
#
# 凭证来自 local.agora.env（Agora + ZEGO）和 local.volcengine.env。两个文件的
# BEACON_AUTH_TOKEN 必须一致；三家 Agent 都注册到同一个 127.0.0.1:8000 Server。
set -euo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
ROOT="$(cd "$(dirname "$SELF")/../.." && pwd)"
SESSION="${BEACON_MAC_CONSOLE_SESSION:-beacon-mac-console}"
PORT="${BEACON_CONSOLE_SERVER_PORT:-8000}"
WINDOWS_CREATED=0

usage() {
  sed -n '2,10p' "$SELF" | sed 's/^# \{0,1\}//'
}

env_token_of() {
  sed -n 's/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}BEACON_AUTH_TOKEN=//p' "$1" \
    | tail -n1 | sed "s/^[\"']//;s/[\"']$//" | tr -d '\r'
}

require_environment() {
  local agora_env="$ROOT/local.agora.env" volcengine_env="$ROOT/local.volcengine.env"
  [ -f "$agora_env" ] || { echo "缺少 $agora_env"; exit 1; }
  [ -f "$volcengine_env" ] || { echo "缺少 $volcengine_env"; exit 1; }
  if [ "$(env_token_of "$agora_env")" != "$(env_token_of "$volcengine_env")" ]; then
    echo "local.agora.env 与 local.volcengine.env 的 BEACON_AUTH_TOKEN 必须一致" >&2
    exit 2
  fi
}

wait_for_server() {
  for _ in $(seq 1 360); do
    if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/v1/status"; then
      return 0
    fi
    sleep 0.5
  done
  echo "统一 Server 180s 未就绪：http://127.0.0.1:${PORT}" >&2
  exit 1
}

require_port_free() {
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 ${PORT} 已被占用；先停掉现有统一 Server，或设置 BEACON_CONSOLE_SERVER_PORT" >&2
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
    exit 1
  fi
}

run_server() {
  cd "$ROOT"
  exec env BEACON_CONSOLE_SERVER_PORT="$PORT" make run-mac-console-real-server
}

run_app() {
  cd "$ROOT"
  echo "[app] 等待统一 Server：http://127.0.0.1:${PORT}"
  wait_for_server
  exec env \
    BEACON_CONSOLE_SERVER_PORT="$PORT" \
    BEACON_CONSOLE_SERVER_URL="http://127.0.0.1:${PORT}" \
    make run-mac-console-app
}

add_window() {
  local name="$1" cmd="$2"
  if [ "$WINDOWS_CREATED" = "0" ]; then
    tmux new-session -d -s "$SESSION" -n "$name" -c "$ROOT" "$cmd"
    WINDOWS_CREATED=1
  else
    tmux new-window -t "$SESSION" -n "$name" -c "$ROOT" "$cmd"
  fi
  tmux set-window-option -t "$SESSION:$name" remain-on-exit on
}

cmd_up() {
  [ "${1:-}" = "" ] || { echo "usage: $0 up" >&2; exit 2; }
  command -v tmux >/dev/null || { echo "缺少 tmux（brew install tmux）"; exit 1; }
  tmux has-session -t "$SESSION" 2>/dev/null && { echo "tmux 会话 ${SESSION} 已存在；先执行: $0 down"; exit 1; }
  require_environment
  require_port_free
  (cd "$ROOT" && make build-mac-console-app)

  WINDOWS_CREATED=0
  add_window "server" "env BEACON_CONSOLE_SERVER_PORT='$PORT' bash '$SELF' server"
  add_window "app" "env BEACON_CONSOLE_SERVER_PORT='$PORT' bash '$SELF' app"
  tmux select-window -t "$SESSION:server"
  echo "已启动统一 Mac Console 环境 ${SESSION}："
  echo "  server: http://127.0.0.1:${PORT}（Agora + 火山 + ZEGO，15 个 Agent）"
  echo "  app   : 一个 Console；侧栏切换 SDK 仅切默认节点"
  echo "  停止  : $0 down"
  tmux attach -t "$SESSION" || true
}

cmd_down() {
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "会话 ${SESSION} 不存在"
    return
  fi
  if tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -qx server; then
    echo "停止统一 Server（Ctrl-C，等待回收 15 个 Agent…）"
    tmux send-keys -t "$SESSION:server" C-c
    for _ in $(seq 1 40); do
      [ "$(tmux display-message -p -t "$SESSION:server" '#{pane_dead}' 2>/dev/null || echo 1)" = "1" ] && break
      sleep 0.5
    done
  fi
  tmux kill-session -t "$SESSION"
  echo "已停止 tmux 会话 ${SESSION}"
}

cmd_status() {
  tmux list-sessions 2>/dev/null || echo "(无 tmux 会话)"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux list-windows -t "$SESSION" -F '  #{window_index} #{window_name} dead=#{pane_dead}'
  fi
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 ${PORT}: 已占用"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  else
    echo "端口 ${PORT}: 空闲"
  fi
}

case "${1:-up}" in
  up) cmd_up "${2:-}" ;;
  down) cmd_down ;;
  status) cmd_status ;;
  server) run_server ;;
  app) run_app ;;
  help|-h|--help) usage ;;
  *) usage; exit 2 ;;
esac
