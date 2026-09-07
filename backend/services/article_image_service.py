# -*- coding: utf-8 -*-
"""Article image post-processing.

The article writer decides where an image is useful and what it should
express. Generated slots are stored as stable remote loremflickr URLs, so
article generation does not download image files to the backend.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import httpx
from loguru import logger

from backend.config import BASE_DIR


SLOT_RE = re.compile(r"\{\{IMAGE_SLOT:(\d+)\|([^|{}]+)\|([^{}]+)\}\}")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMAGE_RE = re.compile(r"<img[^>]+>", re.IGNORECASE)
HTML_IMAGE_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'][^>]*>)', re.IGNORECASE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
BAD_QUERY_WORDS = {"business", "office", "meeting", "service", "help", "blood", "surgery", "dead"}
GENERIC_SCENE_TOKENS = {"professional", "business", "corporate", "modern", "technology", "office"}
LOREMFLICKR_SAFE_TAGS = {
    "agriculture",
    "ai",
    "analytics",
    "architecture",
    "banking",
    "bar",
    "beach",
    "building",
    "campus",
    "chef",
    "chemistry",
    "city",
    "clinic",
    "cloud",
    "classroom",
    "coffee",
    "commerce",
    "computer",
    "construction",
    "cooking",
    "corporate",
    "crops",
    "data",
    "delivery",
    "digital",
    "dish",
    "drone",
    "education",
    "energy",
    "engineering",
    "factory",
    "farm",
    "finance",
    "food",
    "healthcare",
    "hotel",
    "hospital",
    "industrial",
    "investment",
    "kitchen",
    "learning",
    "logistics",
    "machine",
    "manufacturing",
    "medical",
    "office",
    "power",
    "production",
    "restaurant",
    "retail",
    "sales",
    "school",
    "shopping",
    "software",
    "solar",
    "store",
    "technology",
    "tourism",
    "training",
    "transportation",
    "travel",
    "warehouse",
    "wine",
    "work",
    "workspace",
}
LOREMFLICKR_LOCK_POOL = [111111, 123456, 222222, 456789, 555555, 678901, 890123]

# 扩展的行业场景词映射表，覆盖新建客户中的所有行业
INDUSTRY_SCENE_TOKENS = {
    # 食品/餐饮
    "食品": ["food", "restaurant", "chef", "kitchen", "dish", "cooking"],
    "餐饮": ["restaurant", "chef", "kitchen", "food", "dish", "cooking"],
    "食品供应链": ["food", "warehouse", "logistics", "delivery", "storage"],
    "预制菜": ["food", "kitchen", "chef", "dish", "restaurant"],
    "生鲜食材": ["food", "farm", "restaurant", "kitchen", "chef"],
    "餐饮食材供应": ["food", "restaurant", "warehouse", "logistics", "kitchen"],
    "酒水饮料": ["wine", "coffee", "restaurant", "food", "kitchen"],
    "农产品": ["agriculture", "farm", "crops", "harvest", "farming", "rural", "organic"],
    "冷链物流": ["warehouse", "logistics", "delivery", "food", "transportation"],
    "电商": ["retail", "commerce", "shopping", "store", "delivery"],
    "本地生活": ["city", "restaurant", "store", "shopping", "service"],
    "SaaS软件": ["software", "technology", "office", "workspace", "cloud"],
    "企业服务": ["office", "corporate", "workspace", "software", "technology"],
    "AI服务": ["ai", "technology", "software", "office", "data"],
    "数字营销": ["sales", "office", "technology", "data", "corporate"],
    "教育培训": ["education", "training", "classroom", "learning", "school"],
    "金融服务": ["finance", "banking", "investment", "office", "corporate"],
    "医疗健康": ["healthcare", "medical", "clinic", "hospital", "technology"],
    "制造业": ["factory", "production", "manufacturing", "industrial", "machine"],
    "工业设备": ["factory", "machine", "industrial", "production", "engineering"],
    "环保工程": ["energy", "engineering", "construction", "industrial", "technology"],
    "工业清洗": ["factory", "industrial", "machine", "production", "engineering"],
    "无人机服务": ["drone", "technology", "city", "farm", "engineering"],
    "房地产": ["architecture", "construction", "city", "building", "engineering"],
    "建筑工程": ["construction", "engineering", "architecture", "city", "industrial"],
    "旅游出行": ["travel", "tourism", "hotel", "city", "beach"],
    "物流运输": ["warehouse", "logistics", "delivery", "transportation", "city"],
    "新能源": ["energy", "solar", "power", "engineering", "technology"],
    "化工行业": ["chemistry", "factory", "industrial", "production", "engineering"],
    "餐饮美食": ["restaurant", "chef", "kitchen", "food", "dish"],
    "鹅肝": ["food", "restaurant", "chef", "kitchen", "dish"],
    "罐头": ["food", "warehouse", "production", "factory", "storage"],
    "冷链": ["warehouse", "logistics", "delivery", "food", "transportation"],
    "包装": ["factory", "production", "warehouse", "food", "industrial"],
    "肉冻": ["food", "restaurant", "chef", "dish", "kitchen"],
    "医疗": ["healthcare", "medical", "clinic", "hospital", "patient-care"],
    "诊所": ["clinic", "healthcare", "medical", "patient-care", "reception"],
    "金融": ["finance", "banking", "investment", "corporate", "business"],
    "教育": ["education", "training", "classroom", "learning", "campus"],
    "制造": ["manufacturing", "factory", "industrial", "production", "automation"],
    "物流": ["logistics", "warehouse", "delivery", "transportation", "supply-chain"],
    "零售": ["retail", "store", "commerce", "e-commerce", "shopping"],
    "能源": ["energy", "power", "solar", "renewable", "industry"],
    "建筑": ["construction", "engineering", "architecture", "site", "real-estate"],
    "科技": ["technology", "innovation", "digital", "software", "office"],
    # 通用
    "通用": ["professional", "business", "corporate", "modern", "technology", "office"],
}

# 根据 slot 类型添加风格词
SLOT_STYLE_TOKENS = {
    "hero": ["modern-office", "corporate", "professional", "business-team", "workspace"],
    "section": ["team-meeting", "collaboration", "discussion", "business", "office-work"],
    "case": ["results", "success", "growth", "achievement", "performance-improvement"],
    "summary": ["future", "strategy", "planning", "roadmap", "conclusion", "vision"],
}


@dataclass
class ImageSlot:
    index: int
    kind: str
    intent: str
    section_title: str = ""


@dataclass
class ResolvedImage:
    slot: ImageSlot
    url: str
    path: Path
    digest: str


class ArticleImageResolutionError(RuntimeError):
    """Raised when an article cannot get enough real local images."""


class ArticleImageService:
    """Resolve generated article image slots into local image URLs."""

    MIN_IMAGES = 2
    MAX_IMAGES = 3
    IMAGE_ATTEMPTS = 4
    DOWNLOAD_TIMEOUT = 8.0

    def __init__(self) -> None:
        self.upload_root = BASE_DIR / "backend" / "static" / "uploads" / "article-images"

    def render_remote_image_slots(
        self,
        content: str,
        *,
        article_id: int,
        keyword: str,
        title: str = "",
    ) -> str:
        """Replace image slots with stable remote image Markdown links without downloading files."""
        if not content:
            return content

        seen_intents: set[str] = set()

        def replace_slot(match: re.Match) -> str:
            try:
                index = int(match.group(1))
            except ValueError:
                index = len(seen_intents) + 1
            kind = match.group(2).strip() or "section"
            raw_intent = match.group(3).strip()
            intent = self._normalize_intent(raw_intent, keyword=keyword, title=title)
            if intent in seen_intents:
                intent = f"{intent} {self._angle_word(index)}"
            seen_intents.add(intent)
            slot = ImageSlot(index=index, kind=kind, intent=intent)
            url = self._image_url(slot, article_id=article_id, keyword=keyword, title=title, attempt=0)
            alt = self._alt_text(ResolvedImage(slot=slot, url=url, path=Path(), digest=""))
            return f"![{alt}]({url})"

        return re.sub(r"\n{3,}", "\n\n", SLOT_RE.sub(replace_slot, content)).strip()

    async def process_article_images(
        self,
        content: str,
        *,
        article_id: int,
        keyword: str,
        title: str = "",
        min_images: int | None = None,
    ) -> str:
        """Replace image slots with stable remote URLs without downloading files.

        Keep this method async for compatibility with existing callers.
        ``min_images`` is retained for API compatibility but is
        intentionally unused because remote URLs are not fetched or validated
        during article generation.
        """
        return self.render_remote_image_slots(
            content,
            article_id=article_id,
            keyword=keyword,
            title=title,
        )

    def _target_image_count(self, content: str) -> int:
        h2_count = len(H2_RE.findall(content or ""))
        word_count = len(re.sub(r"[\s#*>[\]()!。，、；：,.?-]", "", content or ""))
        if word_count < 900 or h2_count <= 2:
            return 2
        return 3

    def _extract_slots(self, content: str) -> list[ImageSlot]:
        slots: list[ImageSlot] = []
        for match in SLOT_RE.finditer(content or ""):
            try:
                index = int(match.group(1))
            except ValueError:
                index = len(slots) + 1
            slots.append(
                ImageSlot(
                    index=index,
                    kind=match.group(2).strip() or "section",
                    intent=match.group(3).strip(),
                )
            )
        return slots

    def _strip_generated_image_markers(self, content: str) -> str:
        text = SLOT_RE.sub("", content or "")
        text = MARKDOWN_IMAGE_RE.sub("", text)
        text = HTML_IMAGE_RE.sub("", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _normalize_slots(
        self,
        slots: list[ImageSlot],
        content: str,
        *,
        keyword: str,
        title: str,
        target_count: int,
    ) -> list[ImageSlot]:
        h2_titles = [self._clean_heading(item) for item in H2_RE.findall(content or "")]
        result: list[ImageSlot] = []
        seen_intents: set[str] = set()

        for slot in sorted(slots, key=lambda item: item.index):
            intent = self._normalize_intent(slot.intent, keyword=keyword, title=title)
            if not intent or intent in seen_intents:
                continue
            section = h2_titles[min(len(result), len(h2_titles) - 1)] if h2_titles else ""
            result.append(
                ImageSlot(index=len(result) + 1, kind=slot.kind or "section", intent=intent, section_title=section)
            )
            seen_intents.add(intent)
            if len(result) >= target_count:
                return result

        while len(result) < target_count:
            section = self._pick_section_title(h2_titles, len(result))
            intent = self._build_intent(keyword=keyword, title=title, section=section, index=len(result))
            if intent in seen_intents:
                intent = f"{intent} {self._angle_word(len(result))}"
            result.append(
                ImageSlot(
                    index=len(result) + 1,
                    kind="hero" if len(result) == 0 else "section",
                    intent=intent,
                    section_title=section,
                )
            )
            seen_intents.add(intent)

        return result

    def _normalize_intent(self, intent: str, *, keyword: str, title: str) -> str:
        tokens = self._query_tokens(f"{keyword} {intent} {title}")
        useful = [token for token in tokens if token not in BAD_QUERY_WORDS]
        if len(useful) < 3:
            return self._build_intent(keyword=keyword, title=title, section=intent, index=0)
        return " ".join(useful[:8])

    def _build_intent(self, *, keyword: str, title: str, section: str, index: int) -> str:
        semantic = self._semantic_tokens(f"{keyword} {title} {section}")
        angle = self._angle_word(index)
        tokens = self._dedupe([*semantic, angle, "dashboard", "professional"])
        return " ".join(tokens[:8])

    def _semantic_tokens(self, text: str) -> list[str]:
        lower = (text or "").lower()
        mapping = [
            # AI/软件类
            (("ai", "人工智能", "智能", "agent", "助理"), ["ai", "assistant", "automation", "machine-learning"]),
            (("saas", "软件", "系统", "平台"), ["saas", "software", "cloud", "web-application", "platform"]),
            (("crm", "客户管理", "销售管理"), ["crm", "customer-management", "sales", "relationships"]),
            (("erp", "企业管理", "资源计划"), ["erp", "enterprise", "workflow", "management"]),
            (("mes", "生产管理", "制造执行"), ["mes", "manufacturing", "production", "automation"]),
            # 功能类
            (("报表", "报告", "数据", "分析", "统计"), ["report", "analytics", "dashboard", "data-visualization"]),
            (("营销", "推广", "获客"), ["marketing", "growth", "strategy", "campaign", "customer-acquisition"]),
            (("管理", "团队", "协作"), ["management", "team", "collaboration", "leadership"]),
            (("客户", "服务", "售后"), ["customer-service", "support", "client", "after-sales"]),
            # 行业类 - 食品/餐饮
            (("食品",), ["food", "catering", "restaurant", "culinary", "gourmet"]),
            (("餐饮",), ["restaurant", "dining", "catering", "food-service", "kitchen"]),
            (("食品供应链",), ["food-supply-chain", "food-logistics", "supply-chain", "distribution"]),
            (("预制菜",), ["ready-meal", "prepared-food", "frozen-food", "meal-kit"]),
            (("生鲜", "生鲜食材"), ["fresh-produce", "fresh-ingredients", "vegetables", "seafood"]),
            (("餐饮食材",), ["food-ingredient", "catering-supply", "wholesale-food"]),
            (("酒水", "饮料"), ["beverage", "drinks", "wine", "soft-drink", "tea", "coffee"]),
            (("农产品", "农业"), ["agriculture", "farm", "crops", "harvest", "farming"]),
            # 行业类 - 其他
            (("医疗", "医院", "诊所", "健康"), ["healthcare", "medical", "hospital", "clinic"]),
            (("金融", "银行", "投资", "理财", "证券"), ["banking", "finance", "investment", "corporate"]),
            (("教育", "培训", "学校", "课程"), ["education", "training", "learning", "classroom"]),
            (("制造", "工厂", "生产", "工业"), ["manufacturing", "factory", "industrial", "production"]),
            (("零售", "门店", "电商", "商铺"), ["retail", "store", "commerce", "e-commerce"]),
            (("物流", "仓储", "配送", "运输"), ["logistics", "warehouse", "delivery", "transportation"]),
            (("能源", "电力", "光伏", "新能源"), ["energy", "power", "solar", "renewable"]),
            (("建筑", "工程", "施工", "房地产"), ["construction", "engineering", "architecture", "real-estate"]),
            (("科技", "技术", "互联网"), ["technology", "tech", "internet", "digital", "innovation"]),
            # 通用场景词
            (("现代", "专业"), ["modern", "professional", "corporate", "business"]),
            (("办公", "办公室"), ["office", "workspace", "corporate", "business"]),
        ]
        tokens: list[str] = []
        for keys, values in mapping:
            if any(key in lower or key in text for key in keys):
                tokens.extend(values)

        tokens.extend(self._query_tokens(text))
        tokens = [token for token in tokens if token not in BAD_QUERY_WORDS]
        if not tokens:
            tokens = ["professional", "business", "modern", "technology"]
        return self._dedupe(tokens)

    def _get_industry_tokens(self, keyword: str) -> list[str]:
        """根据关键词获取行业相关的场景词"""
        lower = (keyword or "").lower()
        text = keyword or ""

        matches: list[tuple[int, list[str]]] = []
        for industry, scene_tokens in INDUSTRY_SCENE_TOKENS.items():
            if industry == "通用":
                continue
            if industry.lower() in lower or industry in text:
                matches.append((len(industry), scene_tokens))

        if not matches:
            return INDUSTRY_SCENE_TOKENS.get("通用", [])

        matches.sort(key=lambda item: item[0], reverse=True)
        selected = [scene_tokens for _, scene_tokens in matches[:3]]
        interleaved: list[str] = []
        max_len = max((len(tokens) for tokens in selected), default=0)
        for index in range(max_len):
            for tokens in selected:
                if index < len(tokens):
                    interleaved.append(tokens[index])
        return self._dedupe(interleaved)

    def _has_specific_scene_tokens(self, tokens: list[str]) -> bool:
        return any(token not in GENERIC_SCENE_TOKENS for token in tokens)

    def _loremflickr_tags(self, tokens: Iterable[str]) -> list[str]:
        tags: list[str] = []
        for token in tokens:
            parts = re.findall(r"[a-zA-Z][a-zA-Z0-9]{1,24}", str(token).lower())
            for part in parts:
                if part in BAD_QUERY_WORDS or part not in LOREMFLICKR_SAFE_TAGS:
                    continue
                tags.append(part)
        return self._dedupe(tags)

    def _stable_loremflickr_query_tags(self, tokens: list[str]) -> list[str]:
        token_set = set(tokens)
        if {"logistics", "transportation"} & token_set:
            return [tag for tag in ["warehouse", "logistics", "delivery", "transportation"] if tag in token_set]
        if {"energy", "solar", "power"} & token_set:
            return [
                tag
                for tag in ["energy", "solar", "power", "engineering"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        food_tags = {"food", "restaurant", "chef", "kitchen", "dish", "cooking"}
        if "food" in token_set and token_set & food_tags:
            return [tag for tag in ["food", "restaurant", "chef", "dish", "kitchen"] if tag in LOREMFLICKR_SAFE_TAGS]
        if {"factory", "production", "manufacturing", "industrial"} & token_set:
            return [
                tag for tag in ["factory", "production", "manufacturing", "industrial", "machine"] if tag in token_set
            ]
        if {"technology", "software", "ai", "cloud", "data"} & token_set:
            return [
                tag
                for tag in ["technology", "software", "computer", "office"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        if {"education", "training", "classroom", "school"} & token_set:
            return [tag for tag in ["education", "training", "classroom", "school"] if tag in token_set]
        if {"finance", "banking", "investment"} & token_set:
            return [
                tag
                for tag in ["finance", "banking", "investment", "office"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        if {"healthcare", "medical", "clinic", "hospital"} & token_set:
            return [tag for tag in ["healthcare", "medical", "clinic", "hospital"] if tag in token_set]
        if {"travel", "tourism", "hotel", "beach"} & token_set:
            return [
                tag
                for tag in ["travel", "tourism", "hotel", "city"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        if {"construction", "engineering", "architecture", "building"} & token_set:
            return [
                tag
                for tag in ["construction", "engineering", "architecture", "city"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        if {"city", "bar", "coffee"} & token_set:
            return [
                tag
                for tag in ["city", "restaurant", "store", "coffee"]
                if tag in token_set or tag in LOREMFLICKR_SAFE_TAGS
            ]
        if {"retail", "store", "commerce", "shopping"} & token_set:
            return [tag for tag in ["retail", "store", "shopping", "commerce"] if tag in token_set]
        return tokens[:5]

    def _query_tokens(self, text: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,24}", text or "")
        return [token.lower().replace("_", "-") for token in tokens]

    def _angle_word(self, index: int) -> str:
        return ["workflow", "software", "team", "results"][index % 4]

    def _pick_section_title(self, h2_titles: list[str], index: int) -> str:
        if not h2_titles:
            return ""
        if index == 0:
            return h2_titles[0]
        if index == 2:
            for title in h2_titles:
                if any(word in title for word in ("应用", "场景", "案例", "价值", "方案", "成果", "总结")):
                    return title
        return h2_titles[min(index, len(h2_titles) - 1)]

    def _clean_heading(self, heading: str) -> str:
        return re.sub(r"^[一二三四五六七八九十0-9]+[、.．]\s*", "", heading or "").strip()

    async def _resolve_slot(
        self,
        slot: ImageSlot,
        *,
        article_id: int,
        keyword: str,
        title: str,
        seen_hashes: set[str],
    ) -> ResolvedImage | None:
        for attempt in range(self.IMAGE_ATTEMPTS):
            url = self._image_url(slot, article_id=article_id, keyword=keyword, title=title, attempt=attempt)
            content, content_type = await self._download_image(url)
            if not content:
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen_hashes:
                logger.warning(
                    "duplicate article image skipped: article_id={}, slot={}, attempt={}",
                    article_id,
                    slot.index,
                    attempt,
                )
                continue
            path = self._write_image(article_id, slot.index, digest, content, content_type)
            return ResolvedImage(
                slot=slot, url=f"/static/uploads/article-images/{article_id}/{path.name}", path=path, digest=digest
            )
        return None

    def _image_url(self, slot: ImageSlot, *, article_id: int, keyword: str, title: str, attempt: int) -> str:
        """构建图片搜索 URL，组合 AI 意图 + 行业词"""
        # 1. AI 生成的核心意图（最重要，优先保留）
        intent_tags = slot.intent.split()

        # 2. 用 keyword/title/intent 提取业务场景词，避免图片只剩通用软件/办公场景
        scene_tags = self._get_industry_tokens(f"{keyword} {title} {slot.intent}")[:4]
        semantic_tags = self._semantic_tokens(f"{keyword} {title} {slot.intent}")[:4]

        # 3. 有具体业务词时前置业务词；没有时才使用通用职业/办公词兜底
        if self._has_specific_scene_tokens(scene_tags):
            all_tags = self._dedupe([*scene_tags, *intent_tags, *semantic_tags])
        else:
            all_tags = self._dedupe([*intent_tags, *semantic_tags, *scene_tags])

        # 4. 取前 4-5 个关键词（简洁精准，避免太散）
        # 如果意图词少于3个，用语义词补充
        if len(all_tags) < 4:
            all_tags = self._dedupe([*all_tags, *semantic_tags])

        # 5. 最终取前 5 个。后续 attempt 使用更宽泛的行业词兜底，提升下载成功率。
        safe_tags = self._stable_loremflickr_query_tags(self._loremflickr_tags(all_tags))[:5]
        all_tags = self._fallback_loremflickr_tags(safe_tags, attempt)

        # 6. 构建查询字符串
        query = quote(",".join(all_tags) or "food,restaurant,chef", safe=",")

        # 7. 生成稳定的 lock 值
        seed_index = (article_id + slot.index + attempt) % len(LOREMFLICKR_LOCK_POOL)
        seed = LOREMFLICKR_LOCK_POOL[seed_index]

        logger.debug(
            "[图片搜索] keyword={}, slot={}, intent={}, query={}",
            keyword,
            slot.index,
            slot.intent[:30],
            query[:60],
        )

        return f"https://loremflickr.com/1200/675/{query}?lock={seed}"

    def _fallback_loremflickr_tags(self, tags: list[str], attempt: int) -> list[str]:
        if attempt <= 0:
            return tags
        token_set = set(tags)
        if token_set & {"food", "restaurant", "chef", "dish", "kitchen", "cooking"}:
            levels = [
                ["food", "restaurant", "chef", "dish", "kitchen"],
                ["food", "restaurant", "dish"],
                ["restaurant", "food"],
            ]
        elif token_set & {"warehouse", "logistics", "delivery", "transportation"}:
            levels = [
                ["warehouse", "logistics", "delivery", "transportation"],
                ["warehouse", "delivery"],
                ["logistics", "warehouse"],
            ]
        elif token_set & {"factory", "production", "manufacturing", "industrial"}:
            levels = [
                ["factory", "production", "manufacturing", "industrial"],
                ["factory", "industrial"],
                ["manufacturing", "factory"],
            ]
        elif token_set & {"technology", "software", "computer", "office", "ai"}:
            levels = [
                ["technology", "software", "computer", "office"],
                ["technology", "office"],
                ["computer", "office"],
            ]
        else:
            levels = [tags, ["professional", "corporate", "office"], ["business", "office"]]
        return [tag for tag in levels[min(attempt, len(levels) - 1)] if tag in LOREMFLICKR_SAFE_TAGS] or tags

    async def _download_image(self, url: str) -> tuple[bytes | None, str]:
        headers = {"User-Agent": "Mozilla/5.0 AutoGEO article image resolver"}
        try:
            async with httpx.AsyncClient(
                headers=headers, follow_redirects=True, timeout=self.DOWNLOAD_TIMEOUT
            ) as client:
                response = await client.get(url)
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if response.status_code != 200 or len(response.content) < 2000 or not content_type.startswith("image/"):
                logger.warning(
                    "article image rejected: status={}, size={}, type={}",
                    response.status_code,
                    len(response.content),
                    content_type,
                )
                return None, content_type
            return response.content, content_type
        except Exception as exc:
            logger.warning("article image download failed: {}", exc)
            return None, ""

    def _write_image(self, article_id: int, slot_index: int, digest: str, content: bytes, content_type: str) -> Path:
        directory = self.upload_root / str(article_id)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = mimetypes.guess_extension(content_type) or ".jpg"
        if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        path = directory / f"slot-{slot_index}-{digest[:12]}{suffix}"
        path.write_bytes(content)
        return path

    def _insert_images(self, content: str, images: list[ResolvedImage]) -> str:
        if not images:
            return content

        lines = (content or "").splitlines()
        used_positions: set[int] = set()
        offset = 0
        for idx, image in enumerate(images):
            markdown = f"![{self._alt_text(image)}]({image.url})"
            position = self._insertion_index(lines, idx)
            while position in used_positions and position < len(lines):
                position += 1
            lines.insert(position + offset, "")
            lines.insert(position + offset + 1, markdown)
            lines.insert(position + offset + 2, "")
            used_positions.add(position)
            offset += 3

        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    def _insertion_index(self, lines: list[str], image_index: int) -> int:
        if image_index == 0:
            return self._after_intro_index(lines)

        h2_indices = [i for i, line in enumerate(lines) if line.startswith("## ")]
        if not h2_indices:
            return min(len(lines), self._after_intro_index(lines) + 1)
        if image_index == 2:
            for i in h2_indices:
                if any(word in lines[i] for word in ("应用", "场景", "案例", "价值", "方案", "成果", "总结")):
                    return i + 1
        return h2_indices[min(image_index - 1, len(h2_indices) - 1)] + 1

    def _after_intro_index(self, lines: list[str]) -> int:
        index = 0
        while index < len(lines) and (not lines[index].strip() or lines[index].startswith("#")):
            index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].startswith("#"):
            index += 1
        return index

    def _alt_text(self, image: ResolvedImage) -> str:
        label = image.slot.section_title or image.slot.intent
        label = re.sub(r"\s+", " ", label).strip()
        return label[:40] or f"文章配图{image.slot.index}"

    def _dedupe(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = re.sub(r"[^a-zA-Z0-9-]", "", str(value).lower()).strip("-")
            if not item or item in seen:
                continue
            result.append(item)
            seen.add(item)
        return result
