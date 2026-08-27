"""
api.routers.export — Wiki 导出端点
==================================

将 Wiki 页面导出为 Markdown 或 JSON 文件。
"""

import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.models import WikiExportRequest, WikiPage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/export/wiki")
async def export_wiki(request: WikiExportRequest):
    """
    导出 Wiki 内容为 Markdown 或 JSON

    Args:
        request: 导出请求

    Returns:
        可下载的文件
    """
    try:
        logger.info(f"Exporting wiki for {request.repo_url} in {request.format} format")

        repo_parts = request.repo_url.rstrip("/").split("/")
        repo_name = repo_parts[-1] if repo_parts else "wiki"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if request.format == "markdown":
            content = generate_markdown_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.md"
            media_type = "text/markdown"
        else:
            content = generate_json_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.json"
            media_type = "application/json"

        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        error_msg = f"Error exporting wiki: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


# ============================================================
# 导出辅助函数
# ============================================================


def generate_markdown_export(repo_url: str, pages: List[WikiPage]) -> str:
    """生成 Markdown 导出"""
    markdown = f"# Wiki Documentation for {repo_url}\n\n"
    markdown += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    markdown += "## Table of Contents\n\n"
    for page in pages:
        markdown += f"- [{page.title}](#{page.id})\n"
    markdown += "\n"

    for page in pages:
        markdown += f"<a id='{page.id}'></a>\n\n"
        markdown += f"## {page.title}\n\n"

        if page.relatedPages and len(page.relatedPages) > 0:
            markdown += "### Related Pages\n\n"
            related_titles = []
            for related_id in page.relatedPages:
                related_page = next((p for p in pages if p.id == related_id), None)
                if related_page:
                    related_titles.append(f"[{related_page.title}](#{related_id})")
            if related_titles:
                markdown += "Related topics: " + ", ".join(related_titles) + "\n\n"

        markdown += f"{page.content}\n\n"
        markdown += "---\n\n"

    return markdown


def generate_json_export(repo_url: str, pages: List[WikiPage]) -> str:
    """生成 JSON 导出"""
    export_data = {
        "metadata": {
            "repository": repo_url,
            "generated_at": datetime.now().isoformat(),
            "page_count": len(pages),
        },
        "pages": [page.model_dump() for page in pages],
    }
    return json.dumps(export_data, indent=2)
