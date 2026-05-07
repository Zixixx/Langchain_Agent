from __future__ import annotations

"""LLM 构建模块：用 OpenAI 兼容客户端连接 DeepSeek。"""

from langchain_openai import ChatOpenAI

from agent.config import Settings


def build_llm(settings: Settings) -> ChatOpenAI:
    """根据配置创建 DeepSeek 聊天模型实例。"""
    # DeepSeek 兼容 OpenAI Chat Completions 协议，因此可直接复用 ChatOpenAI。
    if not settings.api_key:
        raise RuntimeError("API_KEY is not configured. Copy .env.example to .env and fill it in.")

    return ChatOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        temperature=0.1,
    )
