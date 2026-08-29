"""
llm.py — LLM 调用协调层
========================

将"模型配置解析"与"客户端调用"组装，对外保持统一接口（调用方无感知）：

  1. call_llm_stream()      — SSE 格式 (data: {"content":"..."}\n\n)，用于 HTTP SSE 端点
  2. call_llm_stream_raw()  — 纯文本格式，用于 WebSocket 逐 token 推流

分层:
  - core.config — 模型/参数配置解析（用什么模型、什么参数）
  - clients.llm — 多 Provider 客户端调度（怎么调用）
  - 本模块      — 配置 + 调用的组装协调

依赖:
  - core.config — get_model_config
  - clients.llm — dispatch_stream
"""

import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from core.config import get_model_config
from clients.llm import dispatch_stream

logger = logging.getLogger("core.utils.llm")


# ══════════════════════════════════════════════════════════════════════════
# 主入口 — SSE 格式（用于 HTTP SSE 端点）
# ══════════════════════════════════════════════════════════════════════════


async def call_llm_stream(
    provider: str,
    model: Optional[str],
    messages: List[Dict[str, str]],
) -> AsyncGenerator[str, None]:
    """
    调用 LLM 并通过 SSE 流式返回结果。

    支持多个提供者：dashscope, google, openai, openrouter, ollama

    参数:
        provider: LLM 提供者名称
        model: 模型名称（可选，未指定时使用配置默认值）
        messages: 消息列表 [{"role": "user", "content": "..."}]

    生成:
        SSE 格式字符串: data: {"content":"文本块"}\n\n
    """
    try:
        model_config = get_model_config(provider=provider, model=model)
        model_kwargs = model_config.get("model_kwargs", {})
        async for chunk in dispatch_stream(provider, model, messages, model_kwargs, raw=False):
            yield chunk
    except Exception as e:
        logger.error(f"LLM call error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ══════════════════════════════════════════════════════════════════════════
# 主入口 — 纯文本格式（用于 WebSocket 逐 token 推流）
# ══════════════════════════════════════════════════════════════════════════


async def call_llm_stream_raw(
    provider: str,
    model: Optional[str],
    messages: List[Dict[str, str]],
) -> AsyncGenerator[str, None]:
    """
    调用 LLM 并通过纯文本流式返回结果（无 SSE 包装）。

    与 call_llm_stream() 使用相同的 provider 分发逻辑，
    但 yield 纯文本块而非 SSE 格式字符串。

    用于 WebSocket 场景，兼容 deepwiki-open 前端协议：
      前端直接拼接 event.data 作为纯文本。

    参数:
        provider: LLM 提供者名称
        model: 模型名称（可选）
        messages: 消息列表

    生成:
        纯文本块（无 SSE 包装）
    """
    try:
        model_config = get_model_config(provider=provider, model=model)
        model_kwargs = model_config.get("model_kwargs", {})
        async for chunk in dispatch_stream(provider, model, messages, model_kwargs, raw=True):
            yield chunk
    except Exception as e:
        logger.error(f"LLM raw call error: {e}")
        yield f"[Error: {e}]"
