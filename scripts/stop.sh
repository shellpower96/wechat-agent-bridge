#!/bin/bash
# 停止 bridge 与 onebot（保留微信运行，避免重复登录）
set -uo pipefail
echo "停止 bridge / onebot ..."
pkill -f "wechat-agent-bridge/bridge.py" 2>/dev/null && echo "  bridge 已停" || echo "  bridge 未在运行"
pkill -f "onebot -type=gadget" 2>/dev/null && echo "  onebot 已停" || echo "  onebot 未在运行"
echo "（微信进程保留；如需完全停止：pkill -x WeChat）"
