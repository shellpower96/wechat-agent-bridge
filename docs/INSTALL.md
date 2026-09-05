# 安装手册（零卡点版）

从零到跑通。每步给出**前置/命令/验证/卡点**。按顺序执行。

> 目标环境 **macOS 单机**。以下流程在 macOS 26 + Apple Silicon 上验证。

---

## 0. 前置环境矩阵

| 依赖 | 版本/要求 | 用途 | 必需 |
|---|---|---|---|
| macOS | 26 或更高 | 微信 Hook + 签名规则 | ✅ |
| 微信客户端 | **4.1.11.53 build 269109**（官方 dmg，见下）| Hook 目标 | ✅ |
| Xcode Command Line Tools | 有 `xcodebuild` | 构建 insert_dylib / 部分工具 | ✅ |
| Git | 任意 | clone 源码 | ✅ |
| Go | ≥1.21 | 编译 onebot | ✅（用 onebot 预编译二进制可跳过）|
| Python | ≥3.9（建议 3.11）| bridge / MCP server | ✅ |
| `uv` 或 `pip` | 任意 | 装 frida-tools | 可选 |
| hdiutil / 系统自带 | — | 挂载 dmg | ✅ |
| 一个"小号"微信 | 不绑卡/不重要 | 客服号，防封 | ✅ |

> 微信 Hook 属逆向注入，**务必用小号**，遵守平台规范。正式对外请用微信客服官方 API。

---

## 1. 克隆本仓库

```bash
git clone https://github.com/shellpower96/wechat-agent-bridge.git
cd wechat-agent-bridge
```

## 2. 安装基础工具

```bash
# Xcode CLT（若已装 xcodebuild 可跳过）
xcode-select --install

# Go（编译 onebot 需要）
brew install go          # 或 https://go.dev/dl/

# Python 依赖（bridge 用 aiohttp）
python3 -m venv .venv && .venv/bin/pip install aiohttp
```

## 3. 构建 onebot（微信 Hook 的收发代理）

onebot 来自 [`yincongcyincong/weixin-macos`](https://github.com/yincongcyincong/weixin-macos)（GPL）。

```bash
# 3.1 克隆
git clone https://github.com/yincongcyincong/weixin-macos.git ~/wechat-claw/weixin-macos

# 3.2 ★关键卡点：把 onebot 内置脚本里微信的路径改成我们的 hook 版路径
sed -i '' 's|/Applications/WeChat.app/Contents/MacOS/WeChat|/Applications/WXHook.app/Contents/MacOS/WeChat|' ~/wechat-claw/weixin-macos/onebot/script.js

# 3.3 下载 frida devkit 并编译 onebot（脚本会下载 devkit，需网络）
cd ~/wechat-claw/weixin-macos
FRIDA_VERSION=17.8.0 bash setup_frida_and_build.sh    # 若 go 不在 PATH，先 export PATH 或改脚本
#   ↑ 这一步可能因依赖下载慢，建议设 GOPROXY：
#   export GOPROXY=https://goproxy.cn,direct
cd onebot && export PATH="/opt/homebrew/bin:$PATH" GOARCH=arm64 CGO_ENABLED=1 \
  GOPROXY=https://goproxy.cn,direct \
  CGO_CFLAGS="-I../frida-devkit" CGO_LDFLAGS="-L../frida-devkit -lfrida-core" \
  go build -o onebot .
# 产物: ~/wechat-claw/weixin-macos/onebot/onebot
```

> 不用预编译 onebot 二进制：老版本嵌的路径是 `/Applications/WeChat.app`，
> 与我们 hook 版不符。必须按上面重新编译。**这是最常见的卡点**。

## 4. 重建微信 Hook 版（自动下载 dmg + gadget + 签名）

```bash
bash scripts/rebuild_wechat.sh
# 产出 /Applications/WXHook.app（build 269109，FridaGadget 已注入，禁用自更新）
```

该脚本自动：下载 269109 官方 dmg、下载并校验 FridaGadget 17.8.0、注入、去掉 Sparkle 自更新、纯 ad-hoc 签名。
> 若 dmg/gadget 下载慢，可手动放到 `~/wechat-claw/` 再跑（见脚本环境变量注释）。

**验证**：`scripts/doctor.sh` 应看到 `build=269109`、`FridaGadget 引用=2`。

## 5. 启动微信（hook 版）

```bash
open /Applications/WXHook.app
# 在微信中扫码登录**小号**
```

首次启动后，等约 15s 让 FridaGadget 监听：
```bash
lsof -nP -iTCP:27042 -sTCP:LISTEN    # 应看到 WeChat 监听
```

## 6. 配置 bridge

```bash
cp config.example.json config.json
vi config.json          # 改 provider / 白名单文件 / 超时
```

- `provider`：`hermes` / `claude` / `openai_compat`（见 `docs/MIGRATION.md`）
- `whitelist_file`：默认 `~/.wechat-agent/whitelist.json`

```bash
echo '{"items": ["<你的好友wxid>"]}' > ~/.wechat-agent/whitelist.json
```
> 白名单填 **hook 事件的 `user_id`**（形如 `wxid_xxx`），不是微信"微信号"短 ID。
> 卡点：如何拿到好友 wxid？见第 8 步。

## 7. 启动整条链路

```bash
bash scripts/start.sh
# 内部会自动：拉起微信 → 等 gadget → attach onebot（含重试）→ 启动 bridge
```

**验证**：
```bash
bash scripts/doctor.sh
curl http://127.0.0.1:36060/health   # {"mode":"ai","provider":"...",...}
```

## 8. 首次联调（两个必做小动作）

1. **初始化发送通道**：在小号微信里**手动发一条消息**（给任意人）。微信 Hook 的发送
   通道需一次真实发送来捕获参数，否则 bot 回不了消息（最隐蔽卡点）。
2. **拿到好友 wxid**：让好友给小号发一条消息，然后看
   `tail -f ~/.wechat-agent/logs/onebot.log` 或 bridge 日志里的
   `user_id":"wxid_xxx"`，把该 id 填入白名单。

之后：好友发消息 → agent 自动回复；真人在 Mac 微信手动回复 → AI 让位；真人超时未回复 → AI 自动接管。

## 9. 卡点清单（每个坑 + 解法）

| 症状 | 原因 | 解法 |
|---|---|---|
| onebot 报 `找不到模块 /Applications/WeChat.app/...` | script.js 路径没改 | 重做第 3.2 步 sed |
| onebot `❌ 附加失败` | 不在 attach 窗口期 / 微信没起 | 先 `open /Applications/WXHook.app` 等 15s 再 start |
| onebot `Cannot find 'req2buf'` | 内存布局未就绪（启动早期/过晚）| 重启微信重试（start.sh 已内置 5 轮）|
| 微信启动即 Segfault | 删了 Sparkle 框架本体（主程序引用悬空）| 只删 `Updater.app`/`Installer.xpc`，保留框架；重跑 rebuild |
| 微信被自更新覆盖 | 未去 Sparkle 更新组件 | 重跑 rebuild（已内置去除）|
| **发送失败** `triggerX0 或 triggerX1Payload 尚未初始化` | 发送通道未初始化 | 小号微信里手动发一条消息（第 8 步）|
| 收到微信内部系统消息（XML/sys）| 未过滤 | bridge 已只处理 `text` 段，自动忽略 |
| 桥接启动报 `address already in use` | 旧 bridge 未停 | `lsof -tiTCP:36060 -sTCP:LISTEN \| xargs kill` |
| 白名单加了不生效 | 用了短 wxid / 微信"微信号" | 用 hook 事件里的 `user_id`（`wxid_xxx`）|
| 群聊不回 | 群未加白名单 / `group_reply_mode` 不对 | `/groups` 加群 + 设 `mention` 或 `all` |

## 10. 反向管理（可选，MCP）

bridge 提供 MCP server，让 **Hermes / Claude** 反过来管理微信客服：
```bash
python3 mcp_server.py    # stdio；tools 列表见 README
```
接入：Hermes profile MCP 配置加 stdio；Claude Code 用 `.mcp.json`。

---

## 故障与日常运维

见 [`docs/RUNBOOK.md`](RUNBOOK.md)。常用：`scripts/doctor.sh`（体检）、`scripts/stop.sh`（停，保留微信）、`curl -X POST http://127.0.0.1:36060/human_signal`（手动切真人）。
