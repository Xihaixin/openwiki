"""
Wiki 数据存储 — 文件系统实现

从 api/api.py 迁移而来，行为保持向后兼容（存储格式、key 规则均不变）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.config import WIKI_CACHE_DIR
from infra.cache.key import get_cache_key

logger = logging.getLogger(__name__)


class FileSystemWikiCacheStorage:
    """文件系统实现：Wiki 结果以 JSON 文件持久化在 WIKI_CACHE_DIR。"""

    def __init__(self, cache_dir: str = WIKI_CACHE_DIR):
        self.cache_dir = cache_dir

    # ── 内部辅助 ────────────────────────────────────────────────

    def _get_cache_path(
        self,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> str:
        """生成 Wiki 缓存文件路径"""
        repo_cache_info = get_cache_key(owner, repo, repo_type, language, comprehensive)
        filename = f"{repo_cache_info}.json"
        return os.path.join(self.cache_dir, filename)

    # ── 接口实现 ────────────────────────────────────────────────

    def read(
        self,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """从文件系统读取 Wiki（返回 dict，未命中返回 None）"""
        cache_path = self._get_cache_path(owner, repo, repo_type, language, comprehensive)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading wiki cache from {cache_path}: {e}")
                return None
        return None

    def save(
        self,
        payload: Dict[str, Any],
        language: str,
        comprehensive: bool = False,
    ) -> bool:
        """保存 Wiki 到文件系统（payload 为 WikiCacheData 等价 dict）"""
        repo_info = payload.get("repo") or {}
        owner = repo_info.get("owner", "")
        repo = repo_info.get("repo", "")
        repo_type = repo_info.get("type", "github")
        cache_path = self._get_cache_path(owner, repo, repo_type, language, comprehensive)
        logger.info(f"Attempting to save wiki cache. Path: {cache_path}")
        try:
            try:
                payload_json = json.dumps(payload, ensure_ascii=False)
                payload_size = len(payload_json.encode("utf-8"))
                logger.info(f"Payload prepared for caching. Size: {payload_size} bytes.")
            except Exception as ser_e:
                logger.warning(f"Could not serialize payload for size logging: {ser_e}")

            logger.info(f"Writing cache file to: {cache_path}")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Wiki cache successfully saved to {cache_path}")
            return True
        except IOError as e:
            logger.error(
                f"IOError saving wiki cache to {cache_path}: {e.strerror} (errno: {e.errno})",
                exc_info=True,
            )
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving wiki cache to {cache_path}: {e}", exc_info=True)
            return False

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki 缓存文件"""
        cache_path = self._get_cache_path(owner, repo, repo_type, language)
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                logger.info(f"Successfully deleted wiki cache: {cache_path}")
                return True
            except Exception as e:
                logger.error(f"Error deleting wiki cache {cache_path}: {e}")
                return False
        logger.warning(f"Wiki cache not found, cannot delete: {cache_path}")
        return False

    def list_projects(self) -> List[Dict[str, Any]]:
        """扫描缓存目录，列出所有已处理项目"""
        entries: List[Dict[str, Any]] = []
        if not os.path.exists(self.cache_dir):
            return entries

        for filename in os.listdir(self.cache_dir):
            if not (filename.startswith("openwiki_cache_") and filename.endswith(".json")):
                continue
            file_path = os.path.join(self.cache_dir, filename)
            try:
                stats = os.stat(file_path)
                parts = filename.replace("openwiki_cache_", "").replace(".json", "").split("_")
                if len(parts) < 5:
                    logger.warning(f"Could not parse project details from filename: {filename}")
                    continue
                repo_type = parts[0]
                owner = parts[1]
                mode = parts[-1]
                language = parts[-2]
                repo = parts[-3]
                is_comprehensive = mode == "comprehensive"
                entries.append(
                    {
                        "id": filename,
                        "owner": owner,
                        "repo": repo,
                        "name": f"{owner}/{repo}",
                        "repo_type": repo_type,
                        "submittedAt": int(stats.st_mtime * 1000),
                        "language": language,
                        "comprehensive": is_comprehensive,
                    }
                )
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                continue
        return entries
