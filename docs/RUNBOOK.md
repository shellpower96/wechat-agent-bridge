# WeChat Agent Bridge · 运维手册（Runbook）

## 日常操作

```bash
bash scripts/start.sh       # 拉起 WeChat → onebot → bridge（幂等）
bash scripts/stop.sh        # 停 bridge + onebot（保留微信）
bash scripts/doctor.sh      # 体检：端口 / 版本 / gadget / provider
curl http://127.0.0.1:36060/health   # 运行状态（mode / provider / 唤醒倒计时）
```

## 状态机

| 状态 | 触发 | 行为 | 退出 |
|---|---|---|---|
| `ai` | 默认 / 真人超时未回复 | 白名单好友消息 → agent 自动回复 | 检测到真人手动发送 |
| `human` | 真人手动发送（或 `POST /human_signal`）| AI 暂停，真人接管 | 超过 `human_timeout_seconds` 无新真人回复 |

手动切换真人模式：
```bash
curl -X POST http://127.0.0.1:36060/human_signal
```

## 白名单

`whitelist.json`（路径见 config.json），30 秒热更新：
```json
{"wxids": ["wxid_t0d9qj8tscwb22"]}
```
注意：填的是 **hook 事件里的 user_id**（形如 `wxid_xxx`），不是微信号短 ID。
可在 onebot 日志里观察：`"user_id":"wxid_xxx","sender":{"nickname":"..."}`。

## 常见故障

### 微信被自更新覆盖（hook 失效）
症状：`doctor.sh` 报版本 ≠ 269109 或 gadget 引用 ≠ 2；微信变成 4.1.12+。
处理：`bash scripts/rebuild_wechat.sh`（重建 + 禁用自更新）。

### onebot 附加失败 / 收不到消息
症状：onebot 日志 `❌ 附加失败` 或 `Cannot find 'req2buf'`。
处理：微信启动后 ~15s 内 attach；`scripts/start.sh` 已内置重试（重启微信重试 5 轮）。
手动重试：`pkill -x WeChat; sleep 3; open /Applications/WXHook.app; sleep 15; bash scripts/start.sh`。

### 发送失败 `triggerX0 或 triggerX1Payload 尚未初始化` / onebot `send text failed`
症状：agent 有回复但发不出去（bridge 日志 `send FAILED`，onebot 返回 500）。
处理：在小号微信里**手动发一条消息**（触发 StartTask 捕获，初始化发送通道）。这是
微信 Hook 的固有机制：重启微信后第一次必须真人发一次。

### 微信睡眠/长时间后 hook 失活
症状：`onebot.log` 长时间无新事件（如 Mac 睡眠数小时后），好友发消息无回复。
处理：整链重启 `pkill -f 'onebot -type=gadget'; pkill -x WeChat; bash scripts/start.sh`。

### 系统消息污染回复
微信内部同步/XML/sys 消息曾被推给 agent。已修复：bridge 只处理 `text` 段，非文本
（sys/XML/appmsg）自动忽略。若再出现，检查 onebot 事件里 `message[].type`。

## 群聊

- 配置 `group_reply_mode`：`mention`（仅 @ 机器人）/ `all`（群白名单内全回）/ `off`
- 群白名单：`groups.json`（或 MCP `wx_add_group`）
- 群消息发送用 `send_group_msg`，会话按 `group_id` 独立

## MCP server（反向管理）

```bash
python3 mcp_server.py                     # stdio，默认连 http://127.0.0.1:36060
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp_server.py
```
接入 Hermes：profile 的 MCP 配置加 stdio command；接入 Claude Code：`.mcp.json`。

### 桥接 500 / 日志报错
查看：`~/.wechat-agent/logs/bridge.log`。
已知：早期版本 `_whitelist_cache` 元组赋值 bug 已修复；系统事件（sys）已忽略。

### 系统负载高导致微信启动慢/崩溃
观察 `uptime`。内存/负载紧张时微信可能僵死或 gadget 不加载；等系统空闲再 `start.sh`。

## 升级 agent / 换 provider

改 `config.json` 的 `"provider"` 与对应 `"providers"` 块，`bash scripts/stop.sh && scripts/start.sh`。

## 备份

- 微信 hook 版可随时用 `rebuild_wechat.sh` 从 269109 dmg 重建（无状态）
- bridge 配置：`config.json` + `whitelist.json`（`~/.wechat-agent/`）
- Hermes profile（若用 hermes provider）：`~/.hermes/profiles/wechat-cs/`
