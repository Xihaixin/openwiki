"""
api.routers.system — 系统配置端点
==================================

语言配置、认证状态、模型提供者配置。

模块归属：
  - 业务逻辑在 core（配置加载统一在 core.config）
  - 本模块只负责 HTTP 协议处理与契约模型
"""

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from api.config import WIKI_AUTH_CODE, WIKI_AUTH_MODE, configs

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Pydantic 模型（仅本模块使用）
# ============================================================


class Model(BaseModel):
    """LLM 模型"""
    id: str
    name: str


class Provider(BaseModel):
    """LLM 提供者"""
    id: str
    name: str
    models: List[Model]
    supportsCustomModel: Optional[bool] = False


class ModelConfig(BaseModel):
    """模型配置"""
    providers: List[Provider]
    defaultProvider: str


class AuthorizationConfig(BaseModel):
    """授权配置"""
    code: str


# ============================================================
# 端点
# ============================================================


@router.get("/lang/config")
async def get_lang_config():
    """获取语言配置"""
    return configs.get("lang", {
        "supported_languages": {"en": "English"},
        "default": "zh",
    })


@router.get("/auth/status")
async def get_auth_status():
    """检查是否需要认证"""
    return {"auth_required": WIKI_AUTH_MODE}


@router.post("/auth/validate")
async def validate_auth_code(request: AuthorizationConfig):
    """验证授权码"""
    return {"success": WIKI_AUTH_CODE == request.code}


@router.get("/models/config", response_model=ModelConfig)
async def get_model_config():
    """
    获取可用的模型提供者和模型列表

    从 generator.json 配置中读取提供者和模型信息。
    """
    try:
        logger.info("Fetching model configurations")

        providers = []
        default_provider = configs.get("default_provider", "dashscope")

        for provider_id, provider_config in configs.get("providers", {}).items():
            models = []
            for model_id in provider_config.get("models", {}).keys():
                models.append(Model(id=model_id, name=model_id))

            providers.append(
                Provider(
                    id=provider_id,
                    name=provider_id.capitalize(),
                    supportsCustomModel=provider_config.get("supportsCustomModel", False),
                    models=models,
                )
            )

        return ModelConfig(providers=providers, defaultProvider=default_provider)

    except Exception as e:
        logger.error(f"Error creating model configuration: {str(e)}")
        return ModelConfig(
            providers=[
                Provider(
                    id="dashscope",
                    name="DashScope",
                    supportsCustomModel=True,
                    models=[Model(id="qwen-plus", name="Qwen Plus")],
                )
            ],
            defaultProvider="dashscope",
        )
