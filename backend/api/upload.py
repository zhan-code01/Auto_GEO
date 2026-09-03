# -*- coding: utf-8 -*-
"""
图片上传API
支持文章编辑器中的图片上传功能
"""

import shutil
import uuid
import os
import time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from pydantic import BaseModel
from loguru import logger

router = APIRouter()


class UploadResponse(BaseModel):
    """图片上传响应"""

    success: bool
    message: str = "操作成功"
    data: Optional[dict] = None


def _save_upload(file: UploadFile, upload_dir: Path) -> tuple[Path, str]:
    """保存上传文件到 upload_dir，返回（磁盘路径, 相对URL路径）。"""
    filename = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1] if filename else ".jpg"
    new_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / new_filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_url = f"/static/uploads/{new_filename}"
    return file_path, file_url


def _current_user_label(request: Request) -> str:
    """从认证中间件注入的 request.state 读取当前用户（匿名时为 anonymous）。"""
    username = getattr(getattr(request, "state", None), "username", None)
    return str(username) if username else "anonymous"


@router.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    通用文件上传接口
    支持图片、文档等多种文件类型
    """
    user = _current_user_label(request)
    start = time.perf_counter()
    try:
        current_file = Path(__file__).resolve()
        backend_dir = current_file.parent.parent
        upload_dir = backend_dir / "static" / "uploads"

        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path, file_url = _save_upload(file, upload_dir)
        size_kb = file_path.stat().st_size / 1024

        # 返回根相对路径，不带 http://localhost
        # 这样部署到任何域名下，图片链接都自动适配
        logger.info(
            f"[Upload] 上传成功: file={file.filename} size={size_kb:.1f}KB "
            f"url={file_url} user={user} elapsed={(time.perf_counter() - start) * 1000:.1f}ms"
        )
        return {"url": file_url}

    except Exception as e:
        logger.error(f"[Upload] 上传失败: file={file.filename} user={user} error={e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload/image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """
    图片上传专用接口（WangEditor编辑器使用）
    返回格式符合前端期望: {success: true, data: {url, original_name}}
    """
    user = _current_user_label(request)
    start = time.perf_counter()
    try:
        current_file = Path(__file__).resolve()
        backend_dir = current_file.parent.parent
        upload_dir = backend_dir / "static" / "uploads"

        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path, file_url = _save_upload(file, upload_dir)
        size_kb = file_path.stat().st_size / 1024

        logger.info(
            f"[Upload] 图片上传成功: file={file.filename} size={size_kb:.1f}KB "
            f"url={file_url} user={user} elapsed={(time.perf_counter() - start) * 1000:.1f}ms"
        )

        # 匹配前端期望的响应格式
        return UploadResponse(
            success=True, message="图片上传成功", data={"url": file_url, "original_name": file.filename, "alt": file.filename}
        )

    except Exception as e:
        logger.error(f"[Upload] 图片上传失败: file={file.filename} user={user} error={e}")
        raise HTTPException(status_code=500, detail=str(e))
