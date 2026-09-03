# -*- coding: utf-8 -*-
"""
客户端安装包下载 API

Web 端"下载客户端"功能：提供最新客户端安装包的版本与下载地址。

安装包由部署方上传到 backend/static/downloads/ 目录（Docker 部署时
随 backend 代码目录挂载，无需额外卷）。文件名约定：
  AutoGeo-{version}-{os}-{arch}.exe

接口：
- GET /api/client/latest   → 最新安装包信息（version/filename/url/size）
- GET /api/client/download → 直接下载最新安装包（attachment 强制下载）
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from loguru import logger

from backend.schemas import ApiResponse


router = APIRouter(prefix="/api/client", tags=["客户端下载"])


def _download_dir() -> str:
    """返回安装包存放目录：backend/static/downloads"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "static", "downloads")


def _scan_installers() -> list:
    """扫描安装包目录，按修改时间倒序返回所有安装包。"""
    directory = _download_dir()
    if not os.path.isdir(directory):
        return []

    installers = []
    for name in os.listdir(directory):
        if not name.lower().endswith((".exe", ".msi", ".dmg", ".pkg", ".AppImage")):
            continue
        full_path = os.path.join(directory, name)
        installers.append(
            {
                "filename": name,
                "path": full_path,
                "size": os.path.getsize(full_path),
                "mtime": os.path.getmtime(full_path),
            }
        )
    installers.sort(key=lambda item: item["mtime"], reverse=True)
    return installers


def _parse_version(filename: str) -> Optional[str]:
    """从文件名解析版本号，例如 AutoGeo-1.0.1-win-x64.exe → 1.0.1"""
    import re

    match = re.search(r"(\d+\.\d+\.\d+(?:[.\-]\d+)?)", filename)
    return match.group(1) if match else None


def _latest_installer() -> Optional[dict]:
    """返回最新安装包（无则 None）"""
    installers = _scan_installers()
    return installers[0] if installers else None


@router.get("/latest", response_model=ApiResponse)
async def get_latest_client():
    """返回最新客户端安装包信息（版本、文件名、下载 URL、大小）。"""
    latest = _latest_installer()
    if not latest:
        logger.warning("[ClientDownload] 查询最新安装包：目录为空或不存在")
        raise HTTPException(status_code=404, detail="暂无可用安装包，请联系管理员上传")
    return ApiResponse(
        data={
            "version": _parse_version(latest["filename"]) or "unknown",
            "filename": latest["filename"],
            "url": f"/static/downloads/{latest['filename']}",
            "size": latest["size"],
        }
    )


@router.get("/download")
async def download_client():
    """下载最新客户端安装包（attachment 强制下载）。"""
    latest = _latest_installer()
    if not latest:
        logger.warning("[ClientDownload] 下载请求被拒绝：暂无可用安装包")
        raise HTTPException(status_code=404, detail="暂无可用安装包，请联系管理员上传")
    logger.info(f"客户端下载: {latest['filename']} ({latest['size']} bytes)")
    return FileResponse(
        path=latest["path"],
        filename=latest["filename"],
        media_type="application/octet-stream",
    )
