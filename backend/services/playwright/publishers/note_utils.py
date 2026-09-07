# -*- coding: utf-8 -*-
"""Shared helpers for image-text publishing adapters."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from backend.config import BASE_DIR


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def generated_publish_images_enabled(config: dict[str, Any] | None = None) -> bool:
    """
    Whether publishers may generate unrelated replacement images at publish time.

    Default is false so the published images match the article generated/edited by
    the writing pipeline. Set AUTO_GEO_ALLOW_PUBLISH_IMAGE_FALLBACKS=true, or pass
    allow_generated_fallback_images in a publisher config, to restore old fallback
    behavior for platforms that need it.
    """
    if isinstance(config, dict) and config.get("allow_generated_fallback_images") is not None:
        return str(config.get("allow_generated_fallback_images")).lower() in {"1", "true", "yes", "on"}
    return os.getenv("AUTO_GEO_ALLOW_PUBLISH_IMAGE_FALLBACKS", "").lower() in {"1", "true", "yes", "on"}


def clean_title(title: str, limit: int) -> str:
    text = re.sub(r"[#*`\"<>]", "", title or "").strip()
    return text[:limit] if len(text) > limit else text


def normalize_tags(article: Any, title: str, max_tags: int = 3) -> list[str]:
    candidates: list[str] = []
    for attr in ("tags", "keywords"):
        value = getattr(article, attr, None)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value)
        elif isinstance(value, str):
            candidates.extend(re.split(r"[,，#\s]+", value))

    if not candidates:
        candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", title or "")[:max_tags]

    tags: list[str] = []
    seen = set()
    for item in candidates:
        tag = re.sub(r"[^\w\u4e00-\u9fff]", "", str(item)).strip("#_ ")
        if not tag or tag in seen:
            continue
        tags.append(tag[:12])
        seen.add(tag)
        if len(tags) >= max_tags:
            break
    return tags


def extract_image_sources(article: Any) -> list[str]:
    sources: list[str] = []
    for attr in ("images", "image_paths", "image_urls", "cover_images"):
        value = getattr(article, attr, None)
        if isinstance(value, list):
            sources.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value.strip():
            sources.extend([part.strip() for part in re.split(r"[,;\n]", value) if part.strip()])

    for attr in ("cover", "cover_image", "cover_url", "image_url"):
        value = getattr(article, attr, None)
        if isinstance(value, str) and value.strip():
            sources.append(value.strip())

    content = getattr(article, "content", "") or ""
    sources.extend(re.findall(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", content))
    sources.extend(re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE))

    deduped: list[str] = []
    seen = set()
    for source in sources:
        source = source.strip()
        if source and source not in seen:
            deduped.append(source)
            seen.add(source)
    return deduped


def plain_note_from_article(article: Any, limit: int = 2000) -> str:
    content = getattr(article, "content", "") or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", content)
    # 与 base.markdown_to_plain_text 保持一致：标题/段落前后只留 1 个换行，
    # 不要 \n\n。富文本编辑器段落自带 margin，双换行会被放大成巨大空栏。
    text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n\1\n", text, flags=re.I | re.S)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    lines = [line.strip() for line in text.splitlines()]

    cleaned: list[str] = []
    previous_empty = False
    for line in lines:
        if not line:
            if not previous_empty:
                cleaned.append("")
            previous_empty = True
            continue
        cleaned.append(line)
        previous_empty = False

    return "\n".join(cleaned).strip()[:limit]


async def materialize_images(article: Any, limit: int = 9) -> tuple[list[str], list[str]]:
    return await materialize_image_sources(extract_image_sources(article), limit=limit)


async def materialize_image_sources(sources: list[str], limit: int = 9) -> tuple[list[str], list[str]]:
    """Materialize an already ordered source list without re-extracting article fields."""
    temp_files: list[str] = []
    image_paths: list[str] = []
    for source in sources[:limit]:
        path = await _materialize_image(source, temp_files)
        if path:
            image_paths.append(path)
    return image_paths, temp_files


async def _materialize_image(source: str, temp_files: list[str]) -> str | None:
    source = unquote(source.strip())
    if source.startswith("//"):
        source = "https:" + source

    if source.startswith("data:image/"):
        return _write_data_url(source, temp_files)

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        local_path = _local_static_path(parsed.path)
        if local_path:
            return local_path
        return await _download_image(source, temp_files)

    local_path = _local_static_path(source)
    if local_path:
        return local_path

    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    if candidate.exists() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
        return str(candidate)

    logger.warning("Image source not found or unsupported: {}", source)
    return None


def _local_static_path(path_or_url_path: str) -> str | None:
    path = unquote(path_or_url_path or "").split("?", 1)[0].split("#", 1)[0]
    candidates: list[Path] = []
    if path.startswith("/static/"):
        candidates.append(BASE_DIR / "backend" / path.lstrip("/"))
    elif path.startswith("static/"):
        candidates.append(BASE_DIR / "backend" / path)
    elif path.startswith("/uploads/"):
        candidates.append(BASE_DIR / "backend" / "static" / path.lstrip("/"))

    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            return str(candidate)
    return None


def _write_data_url(source: str, temp_files: list[str]) -> str | None:
    try:
        header, data = source.split(",", 1)
        mime_match = re.search(r"data:(image/[^;]+)", header)
        ext = mimetypes.guess_extension(mime_match.group(1) if mime_match else "image/png") or ".png"
        fd, path = tempfile.mkstemp(prefix="autogeo_note_", suffix=ext)
        with os.fdopen(fd, "wb") as file:
            file.write(base64.b64decode(data))
        temp_files.append(path)
        return path
    except Exception as exc:
        logger.warning("Failed to decode data-url image: {}", exc)
        return None


async def _download_image(url: str, temp_files: list[str]) -> str | None:
    """下载图片，支持重试机制和递增等待时间"""
    max_retries = 2
    # 发布器整体通常只有 180s 超时，单张坏图不能拖垮整篇发布。
    timeouts = [8.0, 12.0]
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            timeout = timeouts[attempt]
            headers = {"User-Agent": "Mozilla/5.0 AutoGEO image publisher"}
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
                resp = await client.get(url)

            if resp.status_code >= 400:
                logger.warning(
                    "Image download failed: {} status={} (attempt {}/{})",
                    url,
                    resp.status_code,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    logger.info("等待 {} 秒后重试...", retry_delay)
                    await asyncio.sleep(retry_delay)
                continue

            if len(resp.content) < 100:
                logger.warning("Image download got empty response (attempt {}/{})", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    logger.info("等待 {} 秒后重试...", retry_delay)
                    await asyncio.sleep(retry_delay)
                continue

            content_type = resp.headers.get("content-type", "").split(";")[0]
            ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".jpg"
            if ext.lower() not in IMAGE_EXTENSIONS:
                ext = ".jpg"
            fd, path = tempfile.mkstemp(prefix="autogeo_note_", suffix=ext)
            with os.fdopen(fd, "wb") as file:
                file.write(resp.content)
            temp_files.append(path)
            logger.info("Image downloaded successfully: {} ({} bytes)", url, len(resp.content))
            return path

        except httpx.TimeoutException:
            logger.warning("Image download timeout: {} (attempt {}/{})", url, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                logger.info("等待 {} 秒后重试...", retry_delay)
                await asyncio.sleep(retry_delay)
            continue

        except Exception as exc:
            logger.warning("Image download failed: {} {} (attempt {}/{})", url, exc, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                logger.info("等待 {} 秒后重试...", retry_delay)
                await asyncio.sleep(retry_delay)
            continue

    logger.error("Image download failed after {} attempts: {}", max_retries, url)
    return _write_fallback_image(url, temp_files)


def _write_fallback_image(source: str, temp_files: list[str]) -> str | None:
    """Create a local uploadable image when a remote image service is unavailable."""
    try:
        seed = hashlib.sha256((source or "autogeo").encode("utf-8")).hexdigest()
        palette = [
            ((36, 54, 66), (214, 166, 91)),
            ((31, 64, 55), (206, 190, 132)),
            ((64, 45, 52), (218, 160, 142)),
            ((42, 55, 83), (148, 188, 214)),
        ]
        bg, accent = palette[int(seed[:2], 16) % len(palette)]
        image = Image.new("RGB", (1200, 675), bg)
        draw = ImageDraw.Draw(image)

        for index in range(0, 1200, 24):
            shade = tuple(min(255, channel + (index // 24) % 28) for channel in bg)
            draw.line([(index, 0), (index - 360, 675)], fill=shade, width=5)

        draw.rectangle((72, 72, 1128, 603), outline=accent, width=6)
        draw.rectangle((96, 96, 1104, 579), outline=(255, 255, 255), width=2)

        title_font = _load_fallback_font(54)
        body_font = _load_fallback_font(28)
        draw.text((128, 248), "AutoGEO Article Image", fill=(255, 255, 255), font=title_font)
        draw.text((130, 322), "Fallback visual for publishing", fill=accent, font=body_font)

        fd, path = tempfile.mkstemp(prefix="autogeo_note_fallback_", suffix=".jpg")
        os.close(fd)
        image.save(path, format="JPEG", quality=90)
        temp_files.append(path)
        logger.warning("Using generated fallback image for unavailable remote image: {}", source)
        return path
    except Exception as exc:
        logger.warning("Failed to create fallback image for {}: {}", source, exc)
        return None


def _load_fallback_font(size: int) -> ImageFont.ImageFont:
    for font_path in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/msyh.ttc",
    ):
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    return ImageFont.load_default()


async def click_first_visible(page, selectors: list[str], timeout: int = 3000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible(timeout=timeout):
                await locator.click(force=True)
                return True
        except Exception:
            continue
    return False


async def paste_text(page, text: str) -> None:
    await page.evaluate(
        """(text) => {
            const dt = new DataTransfer();
            dt.setData("text/plain", text);
            const ev = new ClipboardEvent("paste", {
                clipboardData: dt, bubbles: true, cancelable: true
            });
            document.activeElement.dispatchEvent(ev);
        }""",
        text,
    )
