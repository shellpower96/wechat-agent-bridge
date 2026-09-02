"""WeChat Agent Bridge —— agent provider 适配器。

每个 provider 实现 `async def reply(session_id, text) -> str`。
session_id 由 bridge 传入（每好友独立），provider 内部负责多轮上下文。
"""
from .hermes import HermesProvider
from .claude import ClaudeProvider
from .openai_compat import OpenAiCompatProvider

__all__ = ["HermesProvider", "ClaudeProvider", "OpenAiCompatProvider"]
