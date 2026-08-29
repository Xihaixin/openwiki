"""
Wiki 缓存键生成（缓存基础设施职责）

从 core.flows.base 迁移至此，使缓存键逻辑归属于缓存层。
对应前端 page.tsx 中的 getCacheKey() 函数。
"""


def get_cache_key(
    owner: str, repo: str, repo_type: str,
    language: str, comprehensive: bool = False,
) -> str:
    """
    生成 Wiki 缓存键。

    与前端 page.tsx 中的 getCacheKey() 完全一致（含下划线的 owner/repo
    不再做字符替换，保证前后端生成的 key 唯一且可互相校验）。
    """
    mode = "comprehensive" if comprehensive else "concise"
    return f"openwiki_cache_{repo_type}_{owner}_{repo}_{language}_{mode}"
