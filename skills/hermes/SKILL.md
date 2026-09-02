# Skill: WeChat 客服（接 WeChat Agent Bridge）

把 Hermes 作为微信客服 Agent 接入 `wechat-agent-bridge`。

## 用途

当用户要「微信好友消息 → Hermes 自动回复客服」时使用。

## 前置

1. WeChat Agent Bridge 已部署（见 bridge 仓库 README / scripts/doctor.sh）
2. Hermes 侧已有一个客服 profile（人设 SOUL.md + 模型 provider + API server 端口）

## 配置

在 bridge 的 `config.json`：

```json
{
  "provider": "hermes",
  "providers": {
    "hermes": {
      "base_url": "http://127.0.0.1:18645",
      "api_key_file": "~/.hermes/profiles/wechat-cs/.api_server_key",
      "model": "wechat-cs"
    }
  }
}
```

- `base_url`：Hermes API server（`hermes -p <profile> gateway run` 拉起，默认 18642/18645）
- `api_key_file`：该 profile 的 `.api_server_key`
- `model`：API server 的 model 名（默认等于 profile 名）

## 客服人设与知识库（Hermes 侧）

- 人设：`~/.hermes/profiles/<profile>/SOUL.md`
- 知识库/工具：给该 profile 配 skills / MCP（如 FAQ 检索、订单查询）

## 真人优先（HumanLoop）

- 真人在 Mac 微信手动回复 → Hermes 自动暂停
- 真人 `human_timeout_seconds`（默认 600s）未回复 → Hermes 自动接管

状态查询：`curl http://127.0.0.1:36060/health`
