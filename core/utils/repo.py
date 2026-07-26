"""
repo.py — 仓库下载与远程文件读取工具
=====================================

提供仓库克隆和远程文件内容获取功能。

依赖:
  - core.config — DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_FILES（间接）
"""

import logging
import os
import subprocess
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("core.utils.repo")


# ══════════════════════════════════════════════════════════════════════════
# 代理配置
# ══════════════════════════════════════════════════════════════════════════

# 代理环境变量名列表（按优先级从高到低）
_PROXY_ENV_VARS = [
    "HTTPS_PROXY", "https_proxy",
    "HTTP_PROXY", "http_proxy",
    "ALL_PROXY", "all_proxy",
]


def _is_git_proxy_enabled() -> bool:
    """
    检查是否应启用 GIT 代理。

    优先级：
      1. 环境变量 OPENWIKI_GIT_PROXY=true 显式启用（开发者后端配置，对前端透明）
      2. 环境变量 https_proxy/http_proxy 已设置时自动启用（兼容模式）

    Returns:
        bool: 是否启用代理
    """
    # 显式配置优先：OPENWIKI_GIT_PROXY=true/false
    explicit = os.environ.get("OPENWIKI_GIT_PROXY", "")
    if explicit.lower() in ("true", "1", "t"):
        logger.info("环境变量 OPENWIKI_GIT_PROXY=true，已启用 GIT 代理")
        return True
    if explicit.lower() in ("false", "0", "f", ""):
        if explicit.lower() in ("false", "0", "f"):
            logger.info("环境变量 OPENWIKI_GIT_PROXY=false，已禁用 GIT 代理")
        return False

    # 兼容模式：如果设置了 https_proxy 等环境变量，自动启用
    for var_name in _PROXY_ENV_VARS:
        if os.environ.get(var_name):
            logger.info(f"检测到代理环境变量 {var_name}，自动启用 GIT 代理")
            return True

    return False


def _resolve_proxy_url() -> Optional[str]:
    """
    从环境变量中解析代理 URL。

    优先级: HTTPS_PROXY > https_proxy > HTTP_PROXY > http_proxy > ALL_PROXY > all_proxy

    Returns:
        Optional[str]: 代理 URL，如果未设置任何代理环境变量则返回 None
    """
    for var_name in _PROXY_ENV_VARS:
        value = os.environ.get(var_name)
        if value:
            logger.info(f"从环境变量 {var_name} 读取代理: {value}")
            return value
    return None


def _build_git_clone_command(
    auth_url: str,
    local_path: str,
    use_proxy: Optional[bool] = None,
) -> list[str]:
    """
    构建 git clone 命令，可选地包含代理配置。

    Args:
        auth_url: 带认证信息的仓库 URL
        local_path: 本地目标路径
        use_proxy:
            - True: 强制启用代理
            - False: 强制禁用代理
            - None: 自动检测（检查 OPENWIKI_GIT_PROXY 环境变量和代理环境变量）

    Returns:
        list[str]: git clone 命令参数列表
    """
    cmd = ["git", "clone", "--depth=1"]

    # 确定是否启用代理
    if use_proxy is None:
        use_proxy = _is_git_proxy_enabled()

    if use_proxy:
        proxy_url = _resolve_proxy_url()
        if proxy_url:
            # 使用 git -c 选项设置代理，不影响全局 git 配置
            cmd.insert(1, "-c")
            cmd.insert(2, f"http.proxy={proxy_url}")
            cmd.insert(3, "-c")
            cmd.insert(4, f"https.proxy={proxy_url}")
            logger.info(f"已启用代理: {proxy_url}")
        else:
            logger.warning(
                "代理已启用但未找到代理环境变量。"
                "请设置 HTTPS_PROXY、HTTP_PROXY 或 ALL_PROXY 环境变量。"
            )

    cmd.extend([auth_url, local_path])
    return cmd


# ══════════════════════════════════════════════════════════════════════════
# 仓库下载
# ══════════════════════════════════════════════════════════════════════════


def download_repo(
    repo_url: str,
    local_path: str,
    repo_type: Optional[str] = None,
    access_token: Optional[str] = None,
    use_proxy: Optional[bool] = None,
) -> str:
    """
    下载仓库到本地。

    参数:
        repo_url: 仓库 URL
        local_path: 本地路径
        repo_type: 仓库类型 (github, gitlab, bitbucket, gitee)
        access_token: 访问令牌
        use_proxy:
            - True: 强制启用代理
            - False: 强制禁用代理
            - None（默认）: 自动检测，规则：
                1. OPENWIKI_GIT_PROXY=true → 启用
                2. 环境变量 https_proxy/http_proxy 已设置 → 启用
                3. 否则 → 禁用

    返回:
        str: 本地路径
    """
    logger.info(f"Downloading repo: {repo_url} to {local_path}")

    # 如果本地路径已存在，跳过下载
    if os.path.exists(local_path) and os.listdir(local_path):
        logger.info(f"Local path already exists: {local_path}")
        return local_path

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    try:
        # 构建带认证的 URL
        if access_token:
            parsed = urlparse(repo_url)
            auth_url = f"{parsed.scheme}://{access_token}@{parsed.netloc}{parsed.path}"
        else:
            auth_url = repo_url

        # 构建 git clone 命令（自动检测代理配置）
        git_cmd = _build_git_clone_command(auth_url, local_path, use_proxy)

        # 执行 git clone
        logger.debug(f"执行命令: {' '.join(git_cmd)}")
        result = subprocess.run(
            git_cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
        )

        if result.returncode != 0:
            logger.error(f"Git clone failed: {result.stderr}")
            raise RuntimeError(f"Failed to clone repository: {result.stderr}")

        logger.info(f"Repository cloned successfully to {local_path}")
        return local_path

    except subprocess.TimeoutExpired:
        logger.error("Git clone timed out")
        raise RuntimeError("Repository clone timed out")
    except Exception as e:
        logger.error(f"Error downloading repo: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════
# 远程文件内容获取
# ══════════════════════════════════════════════════════════════════════════


def get_github_file_content(repo_url: str, file_path: str, access_token: Optional[str] = None) -> str:
    """通过 GitHub API 获取文件内容"""
    import json
    import urllib.request

    parsed_url = urlparse(repo_url)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) < 2:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    owner, repo = path_parts[0], path_parts[1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path.lstrip('/')}"

    headers = {
        "Accept": "application/vnd.github.v3.raw",
        "User-Agent": "DeepWiki-Open",
    }
    if access_token:
        headers["Authorization"] = f"token {access_token}"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Error fetching GitHub file {file_path}: {e}")
        raise


def get_gitlab_file_content(repo_url: str, file_path: str, access_token: Optional[str] = None) -> str:
    """通过 GitLab API 获取文件内容"""
    import urllib.parse
    import urllib.request

    parsed_url = urlparse(repo_url)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) < 2:
        raise ValueError(f"Invalid GitLab URL: {repo_url}")

    project_path = urllib.parse.quote("/".join(path_parts), safe="")
    encoded_file_path = urllib.parse.quote(file_path.lstrip("/"), safe="")
    api_url = f"https://gitlab.com/api/v4/projects/{project_path}/repository/files/{encoded_file_path}/raw"

    headers = {"User-Agent": "DeepWiki-Open"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Error fetching GitLab file {file_path}: {e}")
        raise


def get_bitbucket_file_content(repo_url: str, file_path: str, access_token: Optional[str] = None) -> str:
    """通过 Bitbucket API 获取文件内容"""
    import urllib.parse
    import urllib.request

    parsed_url = urlparse(repo_url)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) < 2:
        raise ValueError(f"Invalid Bitbucket URL: {repo_url}")

    owner, repo = path_parts[0], path_parts[1]
    encoded_path = urllib.parse.quote(file_path.lstrip("/"), safe="")
    api_url = f"https://api.bitbucket.org/2.0/repositories/{owner}/{repo}/src/master/{encoded_path}"

    headers = {"User-Agent": "DeepWiki-Open"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Error fetching Bitbucket file {file_path}: {e}")
        raise


def get_file_content(
    repo_url: str,
    file_path: str,
    repo_type: Optional[str] = None,
    access_token: Optional[str] = None,
) -> str:
    """
    从远程仓库获取文件内容。

    参数:
        repo_url: 仓库 URL
        file_path: 文件路径
        repo_type: 仓库类型 (github, gitlab, bitbucket)
        access_token: 访问令牌

    返回:
        str: 文件内容
    """
    if repo_type == "gitlab" or "gitlab.com" in repo_url:
        return get_gitlab_file_content(repo_url, file_path, access_token)
    elif repo_type == "bitbucket" or "bitbucket.org" in repo_url:
        return get_bitbucket_file_content(repo_url, file_path, access_token)
    else:
        return get_github_file_content(repo_url, file_path, access_token)
