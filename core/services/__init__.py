"""
core.services — 业务服务层
==========================

对上层（api）提供业务能力的门面（Facade），屏蔽底层基础设施（infra）细节。

依赖方向：
  api → core.services → infra

模块组成：
  - wiki_cache.py — Wiki 缓存业务服务（CRUD + 已处理项目列表）
"""
