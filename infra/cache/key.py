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

    对应前端 page.tsx 中的 getCacheKey() 函数。
    """
    mode = "comprehensive" if comprehensive else "concise"
    if "_" in owner:
        owner = owner.replace("_", "-")
    if "_" in repo:
        repo = repo.replace("_", "-")
    return f"openwiki_cache_{repo_type}_{owner}_{repo}_{language}_{mode}"
