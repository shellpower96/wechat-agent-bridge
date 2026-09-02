#!/bin/bash
# 体检：检查微信 hook 链路 + bridge + provider 连通性
set -uo pipefail
BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OK=0

check_port() {
  local name="$1" port="$2"
  if lsof -nP -iTCP:${port} -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  ✅ ${name} (${port})"; return 0
  else
    echo "  ❌ ${name} (${port}) 未监听"; return 1
  fi
}

echo "== 端口 =="
check_port "WeChat FridaGadget" 27042 || OK=1
check_port "onebot 发送接口" 58080 || OK=1
check_port "bridge 服务" 36060 || OK=1

echo "== bridge 健康 =="
H=$(curl -sf http://127.0.0.1:36060/health 2>/dev/null) || { echo "  ❌ bridge 不可达"; OK=1; }
[ -n "${H:-}" ] && echo "  $H"

echo "== 微信版本 =="
V=$(defaults read /Applications/WXHook.app/Contents/Info CFBundleVersion 2>/dev/null || echo "N/A")
echo "  WXHook build = $V (期望 269109)"
[ "$V" != "269109" ] && { echo "  ⚠️ 版本不匹配，微信可能被自更新覆盖，需重跑 rebuild_wechat.sh"; OK=1; }

echo "== FridaGadget 注入 =="
G=$(otool -L /Applications/WXHook.app/Contents/MacOS/WeChat 2>/dev/null | grep -c FridaGadget || echo 0)
echo "  LC_LOAD_DYLIB 引用 = $G (期望 2：双架构)"
[ "$G" != "2" ] && { echo "  ⚠️ gadget 注入丢失，需重跑 rebuild_wechat.sh"; OK=1; }

echo "== provider 连通性 =="
python3 - "$BRIDGE_DIR" <<'PY'
import json, pathlib, sys, urllib.request
cfg = json.loads((pathlib.Path(sys.argv[1]) / "config.json").read_text())
prov = cfg.get("provider", "hermes")
p = cfg.get("providers", {}).get(prov, {})
base = p.get("base_url", "")
if base:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/health", timeout=5) as r:
            print(f"  ✅ provider {prov} health: {r.read()[:120]}")
    except Exception as e:
        print(f"  ⚠️ provider {prov} ({base}) 不可达: {e}")
else:
    print(f"  provider={prov}（CLI 型，无 base_url，跳过）")
PY

exit $OK
