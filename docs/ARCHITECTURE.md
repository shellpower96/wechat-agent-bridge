# WeChat Agent Bridge · 架构

## 分层

```
┌─────────────────────────────────────────────────────────────┐
│ 微信通道层（WeChat Transport）                              │
│  /Applications/WXHook.app  (4.1.11.53 build 269109 + FridaGadget 17.8.0)  │
│  onebot (wechat_chatter/weixin-macos, gadget 模式)          │
│    · 收消息 → POST 127.0.0.1:36060/onebot (OneBot 格式)     │
│    · 发消息 ← POST 127.0.0.1:58080/send_private_msg         │
└─────────────────────────────────────────────────────────────┘
                              │ HTTP (loopback)
┌─────────────────────────────────────────────────────────────┐
│ Bridge 核心（agent 无关）                                   │
│  1. 白名单过滤（wxid，30s 热更新）                          │
│  2. HumanLoop 状态机（ai / human，10min 自动唤醒）          │
│  3. 会话映射（每 wxid 独立多轮）                            │
│  4. 消息去重（message_id）                                  │
└─────────────────────────────────────────────────────────────┘
                              │ AgentProvider.reply(session_id, text)
┌─────────────────────────────────────────────────────────────┐
│ Provider 适配层（可插拔）                                   │
│  hermes      → Hermes API server (/v1/responses, previous_response_id)  │
│  claude      → Claude Code headless CLI (--session-id / --resume)       │
│  openai_compat → OpenAI 兼容端点 (chat/completions + messages 历史)     │
│  (自定义)     → 实现 reply()，config 指定 module                 │
└─────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. Agent 无关
Bridge 只依赖 `AgentProvider.reply(session_id, text) -> str` 这一个协议。
任何能"收文本回文本"的 agent 都能接入，无需改核心。

### 2. 会话归属
`session_id = wxid`。多轮上下文由 provider 各自维护：
- Hermes 用 OpenAI Responses 的 `previous_response_id` 链式状态
- Claude 用 `--session-id`（首次）/ `--resume`（续接）
- OpenAI 兼容用本地 messages 历史

### 3. HumanLoop（真人优先）
Hook 层通过**线程 ID**精确区分真人手动发送与 bot 发送：
- bot 发送：Frida 脚本线程调用（`Process.getCurrentThreadId() == 脚本线程`）
- 真人发送：微信 UI 线程调用（线程不同）

真人发送 → script.js 上报 `human_send` → onebot 转 `[HUMAN_SEND]` 标记 → bridge 切 `human`。
`human` 下 agent 暂停；停留超过 `human_timeout_seconds` 无新真人回复 → 自动回 `ai`。

### 4. 消息流
- 入站：`onebot` 把捕获的微信消息 POST 到 bridge `/onebot`（带 HMAC-SHA1 `X-Signature`）
- 出站：bridge POST 到 onebot `/send_private_msg`

## 端口与凭据

| 组件 | 地址 | 凭据 |
|---|---|---|
| FridaGadget | 127.0.0.1:27042 | 无（listen 模式）|
| onebot 发送 | 127.0.0.1:58080 | 无 |
| bridge 接收 | 127.0.0.1:36060 | `onebot_token`（HMAC-SHA1）|
| Hermes（可选）| 127.0.0.1:18645 | Bearer `.api_server_key` |

## 微信 Hook 的技术要点（为什么这么繁琐）

| 坑 | 根因 | 解决 |
|---|---|---|
| App Store 版不可改 | macOS 26 App Store 保护（root 也 EPERM）| 用官方 dmg 版复制到用户路径 |
| AMFI 杀进程 | 带 get-task-allow 的临时签名被 macOS 26 拒绝 | 纯 ad-hoc 签名，无 entitlements |
| 签名失败 | FridaGadget.config 是 JSON 不是代码 | 放 Resources + Frameworks 符号链接 |
| 微信自更新覆盖 | dmg 版内置 Sparkle | 删 Updater.app + 关自动更新 |
| 版本不匹配 | hook 偏移随 build 变 | 锁死 4.1.11.53 build 269109 |
| attach 窗口期 | req2buf 特征扫描依赖启动早期内存布局 | 微信启动后 ~15s 内 attach，失败重启重试 |
