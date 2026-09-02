#!/bin/bash
# 重建 /Applications/WXHook.app（微信 Hook 版），封装全部踩坑经验：
#   1) 必须用官方 4.1.11.53 build 269109（App Store 269136 / dmg 269111 均不匹配）
#   2) macOS 26 App Store 保护 → 复制到用户可写路径
#   3) AMFI 拒绝带 get-task-allow 的临时签名 → 纯 ad-hoc（无 entitlements）
#   4) 删除 Sparkle 的 Updater.app + 关闭自动更新（否则微信会自更新覆盖注入）
#   5) FridaGadget.config 放 Resources + Frameworks 相对符号链接（避免签名失败）
#
# 环境变量（有默认值）：
#   DMG          269109 官方 dmg 路径       默认 ~/wechat-claw/wx41153.dmg
#   GADGET_DYLIB FridaGadget 17.8.0 dylib   默认 ~/wechat-claw/patch/FridaGadget.dylib
#   INJECT_PY    inject_load_dylib.py 路径  默认 ~/wechat-claw/wechat-mac-hook-main/scripts/inject_load_dylib.py
#   GADGET_CFG   FridaGadget.config 路径    默认 ~/wechat-claw/weixin-macos/frida-gadget/FridaGadget.config
set -euo pipefail

DMG="${DMG:-$HOME/wechat-claw/wx41153.dmg}"
GADGET_DYLIB="${GADGET_DYLIB:-$HOME/wechat-claw/patch/FridaGadget.dylib}"
INJECT_PY="${INJECT_PY:-$HOME/wechat-claw/wechat-mac-hook-main/scripts/inject_load_dylib.py}"
GADGET_CFG="${GADGET_CFG:-$HOME/wechat-claw/weixin-macos/frida-gadget/FridaGadget.config}"
HOOKAPP="/Applications/WXHook.app"
MOUNT="$HOME/wechat-claw/wxmount"

[[ -f "$DMG" ]] || { echo "缺少 dmg: $DMG"; exit 2; }
[[ -f "$GADGET_DYLIB" ]] || { echo "缺少 gadget dylib: $GADGET_DYLIB"; exit 2; }
[[ -f "$INJECT_PY" ]] || { echo "缺少 inject 脚本: $INJECT_PY"; exit 2; }
[[ -f "$GADGET_CFG" ]] || { echo "缺少 gadget config: $GADGET_CFG"; exit 2; }

# 退出微信
pgrep -x WeChat >/dev/null && { echo "退出微信..."; pkill -x WeChat; sleep 3; }

# 挂载 dmg 并校验版本
mkdir -p "$MOUNT"
hdiutil detach "$MOUNT" 2>/dev/null || true
hdiutil attach -readonly -nobrowse -noautoopen -mountpoint "$MOUNT" "$DMG" >/dev/null
SRC="$MOUNT/WeChat.app"
BUILD=$(defaults read "$SRC/Contents/Info" CFBundleVersion)
[[ "$BUILD" == "269109" ]] || { echo "dmg 版本错误 build=$BUILD（期望 269109）"; exit 3; }
echo "✅ dmg 校验通过 build=$BUILD"

# 复制 + 移除 Sparkle 更新组件（保留框架本体，防止主程序 dylib 引用悬空）
rm -rf "$HOOKAPP"
cp -Rp "$SRC" "$HOOKAPP"
rm -rf "$HOOKAPP/Contents/Frameworks/Sparkle.framework/Versions/B/Updater.app" 2>/dev/null || true
rm -rf "$HOOKAPP/Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices/Installer.xpc" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :SUFeedURL" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :SUPublicDSAKeyFile" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :SUEnableAutomaticChecks bool false" "$HOOKAPP/Contents/Info.plist" 2>/dev/null || true

# 注入 gadget + 配置
FW="$HOOKAPP/Contents/Frameworks"
EXE="$HOOKAPP/Contents/MacOS/WeChat"
cp "$GADGET_DYLIB" "$FW/FridaGadget.dylib"
chmod +x "$FW/FridaGadget.dylib"
python3 "$INJECT_PY" "$EXE" "@executable_path/../Frameworks/FridaGadget.dylib"
mkdir -p "$HOOKAPP/Contents/Resources"
cp "$GADGET_CFG" "$HOOKAPP/Contents/Resources/FridaGadget.config"
ln -sf ../Resources/FridaGadget.config "$FW/FridaGadget.config"

# 清理 quarantine/provenance
xattr -dr com.apple.quarantine "$HOOKAPP" 2>/dev/null || true
xattr -dr com.apple.provenance "$HOOKAPP" 2>/dev/null || true

# 纯 ad-hoc 签名（无 entitlements！），深层优先
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
codesign --verify --deep --strict "$HOOKAPP"

echo ""
echo "✅ 重建完成：$HOOKAPP (build 269109, FridaGadget 已注入, Sparkle 更新已禁用)"
echo "   启动：open $HOOKAPP"
