"""
api.routers.meta — 基础元信息端点
==================================

健康检查。
"""

import logging
from datetime import datetime

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "openwiki-api",
        "version": "2.0.0",
    }
