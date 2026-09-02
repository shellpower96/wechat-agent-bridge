#!/bin/bash
# 启动微信 hook 链路 + bridge（幂等）。onebot 需在微信启动窗口期 attach，内置重试。
set -uo pipefail
BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYBIN="${WXAB_PYTHON:-/Users/LittleGrass/.hermes/hermes-agent/venv/bin/python}"
ONEBOT="$HOME/wechat-claw/weixin-macos/onebot/onebot"
LOG_DIR="$HOME/.wechat-agent/logs"
mkdir -p "$LOG_DIR"

# 1. WeChat (hook 版)
if pgrep -x WeChat >/dev/null 2>&1; then
  echo "[1/4] WeChat 已在运行"
else
  echo "[1/4] 启动 WeChat (WXHook)..."
  /Applications/WXHook.app/Contents/MacOS/WeChat > "$LOG_DIR/wechat.log" 2>&1 &
fi

# 2. 等 gadget
for i in $(seq 1 40); do
  lsof -nP -iTCP:27042 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 2
done
lsof -nP -iTCP:27042 -sTCP:LISTEN >/dev/null 2>&1 && echo "  ✅ gadget 27042" || echo "  ⚠️ gadget 未就绪"

# 3. onebot（attach 窗口期，最多 5 轮，失败则重启微信）
if lsof -nP -iTCP:58080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[2/4] onebot 已在运行"
else
  echo "[2/4] 启动 onebot..."
  for i in 1 2 3 4 5; do
    pkill -f "onebot -type=gadget" 2>/dev/null; sleep 2
    (cd "$(dirname "$ONEBOT")" && nohup "$ONEBOT" -type=gadget -image_path="" > "$LOG_DIR/onebot.log" 2>&1 &)
    sleep 20
    if grep -q "Dynamic Text Message Setup Complete" "$LOG_DIR/onebot.log" 2>/dev/null \
       && ! grep -qE "JS日志报错|Cannot find 'req2buf'" "$LOG_DIR/onebot.log" 2>/dev/null; then
      echo "  ✅ onebot hook 就绪 (round $i)"; break
    fi
    if [ "$i" -lt 5 ]; then
      pkill -x WeChat 2>/dev/null; sleep 3
      /Applications/WXHook.app/Contents/MacOS/WeChat > "$LOG_DIR/wechat.log" 2>&1 &
      for j in $(seq 1 40); do lsof -nP -iTCP:27042 -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 2; done
    fi
  done
fi

# 4. bridge
if curl -sf http://127.0.0.1:36060/health >/dev/null 2>&1; then
  echo "[3/4] bridge 已在运行"
else
  echo "[3/4] 启动 bridge..."
  (cd "$BRIDGE_DIR" && nohup "$PYBIN" bridge.py > "$LOG_DIR/bridge.log" 2>&1 &)
  sleep 2
fi

echo "[4/4] 状态："
curl -s http://127.0.0.1:36060/health; echo
lsof -nP -iTCP:27042 -sTCP:LISTEN 2>/dev/null | tail -1
lsof -nP -iTCP:58080 -sTCP:LISTEN 2>/dev/null | tail -1
