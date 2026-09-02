# WeChat Agent Bridge

把「微信好友消息 → 任意 AI Agent → 自动回复」做成**标准化、可插拔、agent 无关**的桥接服务。
本仓库沉淀自一套在 macOS 上验证通过的完整链路，支持把 AI 客服能力迁移到
**Hermes、Claude Code、OpenAI 兼容端点（Ollama / vLLM / LM Studio / DeepSeek …）** 等任意 agent。

## 它解决什么问题

在 macOS 单机上，复用**唯一一个官方微信客户端**（WeChat 4.1.11.53 build 269109），
通过 Frida Gadget + OneBot 捕获微信私聊消息，交给任意 agent 生成回复，再发回微信。
内置**真人优先 + AI 兜底**的客服状态机：真人离开时 AI 自动接待，真人手动回复时 AI
立即让位，真人 10 分钟未回复后 AI 自动唤醒。

```
好友 → 小号微信 → [WeChat Hook] → OneBot(58080/36060) → Bridge ←→ Agent Provider
                                                        ├─ 白名单(wxid)
                                                        ├─ AI/真人状态机(10min 唤醒)
                                                        └─ 多轮会话映射(每好友独立)
```

## 目录结构

```
wechat-agent-bridge/
├── bridge.py               # 核心服务（HTTP 36060，provider 可插拔）
├── mcp_server.py           # MCP server（stdio JSON-RPC，让 agent 反向管理微信客服）
├── providers/              # agent 适配器
│   ├── hermes.py           #   Hermes API server（OpenAI /v1/responses, previous_response_id）
│   ├── claude.py           #   Claude Code headless CLI（--session-id/--resume）
│   └── openai_compat.py    #   通用 OpenAI 兼容端点（chat/completions）
├── config.example.json     # 配置文件样例
├── scripts/                # doctor / start / stop / rebuild_wechat
├── docs/                   # ARCHITECTURE / RUNBOOK / MIGRATION
└── skills/                 # 供 Hermes / Claude 直接引用的 skill 说明
```

## 快速开始

```bash
# 0. 一次性准备：微信 Hook 版（仅需一次，见 scripts/rebuild_wechat.sh）
bash scripts/rebuild_wechat.sh        # 产出 /Applications/WXHook.app（269109 + FridaGadget，无自更新）

# 1. 配置
cp config.example.json config.json     # 选 provider、填白名单 wxid、超时

# 2. 启动
bash scripts/start.sh                  # 依次拉起 WeChat → onebot → bridge

# 3. 体检
bash scripts/doctor.sh                 # 检查 27042 / 58080 / 36060 / provider 连通性

# 4. 运行状态
curl http://127.0.0.1:36060/health     # {"mode":"ai","human_timeout_seconds":600,...}
```

## 三个核心概念

### 1. Provider（agent 适配器）
任意 agent 只要实现「给定 `session_id + 文本`，返回回复文本」，就是一个 provider。
见 `providers/`，接新 agent 参考 `docs/MIGRATION.md`（约 3 步）。

### 2. 会话映射
每个微信好友 `wxid` 对应一条独立多轮会话。Hermes 用 `previous_response_id` 链式，
Claude 用 `--session-id/--resume`，OpenAI 兼容用 messages 历史。Bridge 内部维护映射。

### 3. AI / 真人状态机（HumanLoop）
- `ai`：白名单好友消息 → agent 自动回复
- `human`：检测到真人在 Mac 微信手动发送 → AI 暂停，真人接管
- human 停留超过 `human_timeout_seconds`（默认 600）无新真人回复 → 自动唤醒 AI

真人发送由 Hook 层的**线程 ID 判别**精确区分（bot 发送走 Frida 脚本线程，真人手动走
微信 UI 线程），事件以 `[HUMAN_SEND]` 标记上报。也可手动切换：`POST /human_signal`。

## 已知边界

- 私聊**文本**已支持；群聊支持 `mention`（@ 机器人才回）/ `all`（群白名单内全回）/ `off`
  （群白名单 + 群回复由 bridge 管理，见 `group_reply_mode`）
- 图片/文件/语音未接（需配置 image_path）
- 微信内部系统消息（同步/XML/sys）已自动过滤，不会推给 agent
- Hook 依赖微信精确版本 **4.1.11.53 build 269109**，且**必须禁用自更新**（见脚本）
- 微信 Hook 属逆向注入，请用小号 + 低频，遵守平台规范；正式对外客服建议走微信客服官方 API

## 反向管理（MCP）

`mcp_server.py` 把 bridge 管理端点封装成 MCP tools，供 **Hermes / Claude Code** 等
agent 反过来管理微信客服：查状态、增删白名单/群、切换真人/AI、主动发消息。

- Hermes：在 profile 的 MCP 配置加 `command: python3 .../mcp_server.py`
- Claude Code：`.mcp.json` 加 stdio server

```jsonc
// .mcp.json（Claude Code）
{"mcpServers": {"wechat-agent": {
  "command": "python3",
  "args": ["/path/to/wechat-agent-bridge/mcp_server.py"]
}}}
```

tools：`wx_status` / `wx_list_whitelist` / `wx_add_whitelist` / `wx_remove_whitelist` /
`wx_list_groups` / `wx_add_group` / `wx_remove_group` / `wx_set_human_mode` /
`wx_set_ai_mode` / `wx_send_message` / `wx_send_group_message`。

## 迁移到其他 agent（30 秒版）

1. 在 `providers/` 新建 `myagent.py`，实现 `reply(session_id, text) -> str`
2. `config.json` 里 `"provider": "myagent"` + 对应参数
3. `bash scripts/start.sh` 重启即可

详见 `docs/MIGRATION.md`。
