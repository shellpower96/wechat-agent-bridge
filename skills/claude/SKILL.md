# Skill: WeChat 客服（接 WeChat Agent Bridge）

把 Claude Code 作为微信客服 Agent 接入 `wechat-agent-bridge`。

## 用途

当用户要「微信好友消息 → Claude Code 自动回复」时使用。

## 前置

1. WeChat Agent Bridge 已部署
2. 本机 `claude` CLI 可用且已登录（`claude --version`）

## 配置

bridge 的 `config.json`：

```json
{
  "provider": "claude",
  "providers": {
    "claude": {
      "claude_bin": "claude",
      "timeout_seconds": 300,
      "extra_args": []
    }
  }
}
```

- `extra_args` 可加模型/权限参数，例如 `["--model", "opus"]`
- 多轮会话自动用 `--session-id`（首条）/ `--resume`（续接），每好友独立

## 客服人设

建议在首条消息用 system 指令引导，或让 bridge 在转发时附带固定前缀（修改
`claude.py` 的 args 拼接，或在 `extra_args` 外预置 `--append-system-prompt`）。

## 真人优先（HumanLoop）

同 hermes：真人手动回复 → Claude 暂停；超时未回复 → Claude 自动接管。
`curl http://127.0.0.1:36060/health` 查看 mode。
