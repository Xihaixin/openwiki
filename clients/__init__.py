"""
clients — LLM 客户端层
=====================

纯客户端调度实现，只负责"如何调用外部模型服务"，不包含业务配置解析。

模块组成：
  - llm.py — 多 Provider 流式调用调度（dashscope / google / openai / openrouter / ollama）

依赖方向：
  clients → infra（API 密钥等基础设施配置），不依赖 core / api。
  模型参数（model_kwargs）由调用方（core.utils.llm 协调层）解析配置后传入。
"""
