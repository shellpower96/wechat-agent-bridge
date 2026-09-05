#!/bin/bash
# 重建 /Applications/WXHook.app（微信 Hook 版），封装全部前置与坑位。
# 目标：新用户零卡点。所需文件优先用仓库内嵌，缺失则自动下载并校验 SHA256。
#
# 环境变量（均可不设，脚本自动处理）：
#   DMG          269109 官方 dmg 下载 URL 或本地路径   默认自动下载
#   GADGET_DYLIB FridaGadget dylib 路径               默认 scripts/patch/FridaGadget.dylib（缺则下载）
#   INJECT_PY    inject_load_dylib.py                 默认 scripts/inject_load_dylib.py（内嵌）
#   GADGET_CFG   FridaGadget.config                   默认 scripts/FridaGadget.config（内嵌）
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$DIR/scripts"
PATCH="$DIR/scripts/patch"
mkdir -p "$PATCH" "$HOME/wechat-claw"

# 已知校验值（与官方 manifest / weixin-macos 一致）
EXPECTED_BUILD="269109"
GADGET_SHA="fa67242fa0cee16e80a803703991e81381cd05f7823a4151515460339c942f9f"
DMG_URL="${DMG_URL:-https://dldir1v6.qq.com/weixin/Universal/Mac/xWeChatMac_universal_4.1.11.53_41748.dmg}"
GADGET_URL="https://github.com/frida/frida/releases/download/17.8.0/frida-gadget-17.8.0-macos-universal.dylib.xz"

# 内嵌文件（仓库自带）
INJECT_PY="${INJECT_PY:-$SCRIPTS/inject_load_dylib.py}"
GADGET_CFG="${GADGET_CFG:-$SCRIPTS/FridaGadget.config}"

# 下载工具
fetch() { # fetch <url> <out>
  echo "  下载 $1"
  curl -L --http1.1 --retry 3 --retry-delay 3 --max-time 900 -o "$2" "$1" 2>&1 | tail -1
}

# ---- 1. 微信 269109 dmg ----
if [ -n "${DMG:-}" ] && [ -f "$DMG" ]; then
  DMG_SRC="$DMG"
elif [ -f "$HOME/wechat-claw/wx41153.dmg" ]; then
  DMG_SRC="$HOME/wechat-claw/wx41153.dmg"
else
  DMG_SRC="$HOME/wechat-claw/wx41153.dmg"
  [ -f "$DMG_SRC" ] || fetch "$DMG_URL" "$DMG_SRC"
fi
echo "[1/5] 微信 dmg: $DMG_SRC"

# ---- 2. FridaGadget dylib (17.8.0) ----
GADGET_DYLIB="${GADGET_DYLIB:-$PATCH/FridaGadget.dylib}"
if [ ! -f "$GADGET_DYLIB" ]; then
  XZ="$PATCH/gadget.xz"
  [ -f "$XZ" ] || fetch "$GADGET_URL" "$XZ"
  xz -dkf "$XZ" && mv "$PATCH/gadget" "$GADGET_DYLIB" 2>/dev/null || true
fi
ACTUAL=$(shasum -a 256 "$GADGET_DYLIB" | awk '{print $1}')
[ "$ACTUAL" == "$GADGET_SHA" ] || { echo "❌ FridaGadget 校验失败: $ACTUAL"; exit 6; }
echo "[2/5] FridaGadget 17.8.0 校验通过"

# ---- 3. 退出微信 + 挂载 dmg ----
pgrep -x WeChat >/dev/null && { echo "退出微信..."; pkill -x WeChat; sleep 3; }
MOUNT="$HOME/wechat-claw/wxmount"
mkdir -p "$MOUNT"
hdiutil detach "$MOUNT" 2>/dev/null || true
hdiutil attach -readonly -nobrowse -noautoopen -mountpoint "$MOUNT" "$DMG_SRC" >/dev/null
SRC="$MOUNT/WeChat.app"
BUILD=$(defaults read "$SRC/Contents/Info" CFBundleVersion)
[ "$BUILD" == "$EXPECTED_BUILD" ] || { echo "❌ dmg 版本错误 build=$BUILD（期望 $EXPECTED_BUILD）"; exit 3; }
echo "[3/5] dmg 校验通过 build=$BUILD"

# ---- 4. 复制 + 移除 Sparkle 更新组件（保留框架本体防悬空）----
HOOKAPP="/Applications/WXHook.app"
rm -rf "$HOOKAPP"
cp -Rp "$SRC" "$HOOKAPP"
rm -rf "$HOOKAPP/Contents/Frameworks/Sparkle.framework/Versions/B/Updater.app" 2>/dev/null || true
rm -rf "$HOOKAPP/Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices/Installer.xpc" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :SUFeedURL" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :SUPublicDSAKeyFile" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :SUEnableAutomaticChecks bool false" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true

# ---- 5. 注入 gadget + 配置 + 纯 ad-hoc 签名 ----
FW="$HOOKAPP/Contents/Frameworks"
EXE="$HOOKAPP/Contents/MacOS/WeChat"
cp "$GADGET_DYLIB" "$FW/FridaGadget.dylib"
chmod +x "$FW/FridaGadget.dylib"
python3 "$INJECT_PY" "$EXE" "@executable_path/../Frameworks/FridaGadget.dylib"
mkdir -p "$HOOKAPP/Contents/Resources"
cp "$GADGET_CFG" "$HOOKAPP/Contents/Resources/FridaGadget.config"
ln -sf ../Resources/FridaGadget.config "$FW/FridaGadget.config"
xattr -dr com.apple.quarantine "$HOOKAPP" 2>/dev/null || true
xattr -dr com.apple.provenance "$HOOKAPP" 2>/dev/null || true
codesign -f -s - --timestamp=none "$FW/FridaGadget.dylib"
python3 - "$HOOKAPP/Contents" <<'PY'
import pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
suffixes = (".framework", ".dylib", ".bundle", ".xpc", ".appex", ".app")
code = [p for p in root.rglob("*")
        if (p.is_file() and p.name.endswith(".dylib")) or (p.is_dir() and p.name.endswith(suffixes))]
for p in sorted(code, key=lambda i: len(i.parts), reverse=True):
    subprocess.run(["codesign", "-f", "-s", "-", "--timestamp=none", str(p)], check=True)
PY
codesign -f -s - --timestamp=none --force "$HOOKAPP"
codesign --verify --deep --strict "$HOOKAPP" && echo "[4/5] 签名验证通过"

echo ""
echo "✅ [5/5] 重建完成：$HOOKAPP (build 269109, FridaGadget 已注入, Sparkle 更新已禁用)"
echo "   启动：open $HOOKAPP"
