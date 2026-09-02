"""OpenAI 兼容 Provider（Ollama / vLLM / LM Studio / DeepSeek / OpenAI 等）。

使用 chat/completions + messages 历史做多轮。
config 示例:
  {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b",
   "api_key": "ollama", "timeout_seconds": 120}
"""
from __future__ import annotations

import aiohttp


class OpenAiCompatProvider:
    def __init__(self, cfg: dict) -> None:
        self.base_url = str(cfg.get("base_url", "http://localhost:11434/v1")).rstrip("/")
        self.model = cfg.get("model", "gpt-4o-mini")
        self.api_key = cfg.get("api_key", "")
        self.timeout = int(cfg.get("timeout_seconds", 120))
        self.system_prompt = cfg.get("system_prompt", "你是微信自动客服助手，用简洁礼貌的中文回答。")
        self.max_history = int(cfg.get("max_history", 20))
        self._history: dict[str, list[dict]] = {}

    async def reply(self, session_id: str, text: str) -> str:
        hist = self._history.setdefault(session_id, [])
        hist.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": self.system_prompt}] + hist[-self.max_history:]
        body = {"model": self.model, "messages": messages}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.post(f"{self.base_url}/chat/completions", json=body, headers=headers) as r:
                if r.status != 200:
                    raise RuntimeError(f"OpenAI-compat {r.status}: {(await r.text())[:200]}")
                data = await r.json()
        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if reply:
            hist.append({"role": "assistant", "content": reply})
            if len(hist) > self.max_history + 2:
                del hist[:2]
        return reply
