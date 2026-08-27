"""
api.routers.local_repo — 本地仓库结构端点
==========================================

扫描本地仓库目录，返回文件树与 README 内容。
"""

import logging
import os

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/local_repo/structure")
async def get_local_repo_structure(path: str = Query(None, description="Path to local repository")):
    """返回本地仓库的文件树和 README 内容"""
    if not path:
        return JSONResponse(
            status_code=400,
            content={"error": "No path provided. Please provide a 'path' query parameter."},
        )

    if not os.path.isdir(path):
        return JSONResponse(
            status_code=404,
            content={"error": f"Directory not found: {path}"},
        )

    try:
        logger.info(f"Processing local repository at: {path}")
        file_tree_lines = []
        readme_content = ""

        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d != "__pycache__"
                and d != "node_modules"
                and d != ".venv"
            ]
            for file in files:
                if file.startswith(".") or file == "__init__.py" or file == ".DS_Store":
                    continue
                rel_dir = os.path.relpath(root, path)
                rel_file = os.path.join(rel_dir, file) if rel_dir != "." else file
                file_tree_lines.append(rel_file)
                if file.lower() == "readme.md" and not readme_content:
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            readme_content = f.read()
                    except Exception as e:
                        logger.warning(f"Could not read README.md: {str(e)}")
                        readme_content = ""

        file_tree_str = "\n".join(sorted(file_tree_lines))
        return {"file_tree": file_tree_str, "readme": readme_content}

    except Exception as e:
        logger.error(f"Error processing local repository: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error processing local repository: {str(e)}"},
        )
