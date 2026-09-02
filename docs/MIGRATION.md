# 迁移到其他 Agent（3 步）

Bridge 与 agent 解耦，新增一个 agent 只需实现一个方法。

## 步骤

### 1. 新建 `providers/myagent.py`

```python
class MyAgentProvider:
    def __init__(self, cfg: dict) -> None:
        # 从 cfg 读配置（来自 config.json 的 providers.myagent）
        self.endpoint = cfg.get("endpoint")

    async def reply(self, session_id: str, text: str) -> str:
        # session_id = wxid（每好友独立），text = 好友发来的消息
        # 返回要发给好友的回复文本；抛异常则 bridge 记录日志并跳过
        ...
        return "回复内容"


def make_provider(cfg: dict):
    return MyAgentProvider(cfg)
```

约束：
- 方法签名必须是 `async def reply(self, session_id, text) -> str`
- 多轮上下文自己维护（可用 session_id 作为 key）
- 慢 agent 请自己设超时

### 2. `config.json` 指定

```json
{
  "provider": "myagent",
  "providers": {
    "myagent": {
      "module": "providers.myagent",
      "endpoint": "http://..."
    }
  }
}
```

> `module` 指向可导入模块（含 `make_provider(cfg)`）。若想直接内置，
> 在 `bridge.py` 的 `_load_provider()` 加一个 `if PROVIDER == "myagent"` 分支即可。

### 3. 重启

```bash
bash scripts/stop.sh && bash scripts/start.sh
curl http://127.0.0.1:36060/health   # 确认 provider 字段
```

## 已内置 provider

| provider | agent | 多轮机制 |
|---|---|---|
| `hermes` | Hermes API server | `previous_response_id` |
| `claude` | Claude Code headless | `--session-id` / `--resume` |
| `openai_compat` | Ollama / vLLM / LM Studio / DeepSeek 等 | messages 历史 |

## 常见 agent 接入要点

### Claude Code
- 需要 `claude` 在 PATH；CI/headless 需登录态（`claude` 已在机器登录）
- 慢响应调大 `timeout_seconds`（默认 300）
- 需要工具/权限时在 `extra_args` 加参数（如 `--dangerously-skip-permissions`）

### Hermes
- 用 Hermes 的 API server 端口（本项目 profile 为 18645/18642 视部署）
- `api_key_file` 指向 `.api_server_key`；或直接给 `api_key`
- 人设/知识库在 Hermes 侧配置（profile 的 SOUL.md / skills / MCP）

### 任意 OpenAI 兼容服务
- Ollama：`base_url http://localhost:11434/v1`，`api_key "ollama"`
- vLLM/LM Studio：`base_url` + `model` + 可选 `api_key`
- 想要 OpenAI 官方：`base_url https://api.openai.com/v1`

## 进阶：把 Bridge 本身暴露给其他 agent（反向）

Bridge 的 `/health`、`/human_signal`、OneBot 收发都可被其他 agent 通过 HTTP 调用，
因此也可作为 MCP / skill 的数据源。参考 `skills/` 里的封装说明。
