from __future__ import annotations

import re
from typing import Any

from .schemas import GeneratedArticle


# 标准占位符：索引 | 意图(hero/section/case/summary) | 描述，无多余空格。
SLOT_RE = re.compile(r"\{\{IMAGE_SLOT:(\d+)\|(hero|section|case|summary)\|([^{}|]+)\}\}")

# 容错版：容忍模型在占位符内部/周围多加的空格。DeepSeek 经常输出
# `{{ IMAGE_SLOT: 1 | section | 描述 }}` 这类带空格的写法，严格正则匹配不到会误判
# 占位符数量为 0，进而触发“图片占位符数量必须为2到3个”并导致所有生成失败。
# 这里按容错正则找出占位符，再统一重写为无空格的标准写法。
_SLOT_LOOSE_RE = re.compile(r"\{\{\s*IMAGE_SLOT\s*:\s*(\d+)\s*\|\s*([A-Za-z]+)\s*\|\s*([^{}|]+?)\s*\}\}")

# 模型偶尔会吐出 (PARSING) / （PARSING） 这类解析残留，清理掉以免污染正文。
_PARSING_ARTIFACT_RE = re.compile(r"[（(]\s*PARSING\s*[）)]", re.IGNORECASE)

SLOT_INTENTS = ("hero", "section", "case", "summary")

# 立场词：暴露推广立场的内部称呼，必须杜绝。
STANCE_WORDS = ("我方", "竞品")


class ArticleFormatError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors))


# 文章首段（行业简介）字数上限：用户要求约50字、不要太长，留出一定浮动。
FIRST_PARAGRAPH_MAX_CHARS = 80


def _normalize_article_content(content: str) -> str:
    """归一化文章正文：清理解析残留，并把图片占位符统一为标准格式。

    模型（尤其 DeepSeek）常在占位符里加空格，如
    `{{ IMAGE_SLOT: 1 | section | 描述 }}`，严格正则匹配不到会误判占位符数量为 0。
    这里先按容错正则找出来，再重写成无空格的标准写法，保证后续校验与渲染一致。
    """
    content = _PARSING_ARTIFACT_RE.sub("", content)

    def _replace(m: re.Match) -> str:
        idx = int(m.group(1))
        intent = m.group(2).strip().lower()
        desc = m.group(3).strip()
        return f"{{{{IMAGE_SLOT:{idx}|{intent}|{desc}}}}}"

    return _SLOT_LOOSE_RE.sub(_replace, content)


def _first_content_paragraph(content: str) -> str:
    """提取 H1 之后第一个非空段落（到空行或下一个标题为止）。"""
    lines = content.split("\n")
    idx = 0
    if idx < len(lines) and lines[idx].lstrip().startswith("# "):
        idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    paragraph_lines: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#"):
            break
        paragraph_lines.append(line)
        idx += 1
    return "\n".join(paragraph_lines).strip()


def _check_first_paragraph_length(content: str, errors: list[str]) -> None:
    paragraph = _first_content_paragraph(content)
    if not paragraph:
        return
    # 去除 Markdown 链接语法外壳，只统计可见字数。
    visible = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", paragraph)
    # 占位符是模板标记，不计入正文可见字数。
    visible = re.sub(SLOT_RE, "", visible)
    visible = re.sub(r"[#*>\-`\s]", "", visible)
    if len(visible) > FIRST_PARAGRAPH_MAX_CHARS:
        errors.append(
            f"文章首段应为50字左右的行业简介、不应过长，当前约{len(visible)}字，请压缩到{FIRST_PARAGRAPH_MAX_CHARS}字以内"
        )


def _check_stance_words(title: str, content: str, errors: list[str]) -> None:
    haystack = f"{title}\n{content}"
    for word in STANCE_WORDS:
        if word in haystack:
            errors.append(f"正文中出现了暴露推广立场的内部称呼“{word}”，必须改用第三方评测视角客观陈述")


def validate_generated_article(data: dict[str, Any], chunk_count: int) -> GeneratedArticle:
    errors: list[str] = []
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    # 先归一化：清理解析残留 + 统一占位符格式，避免模型空格导致误判。
    content = _normalize_article_content(content)
    references = data.get("references")
    if not title:
        errors.append("标题为空")
    if len(title) > 30:
        errors.append("标题超过30个汉字")
    if not content:
        errors.append("正文为空")
    if content and not content.startswith(f"# {title}"):
        errors.append("正文第一行H1必须与title一致")

    slots = list(SLOT_RE.finditer(content))
    if len(slots) not in (2, 3):
        errors.append("图片占位符数量必须为2到3个")
    indexes = [int(item.group(1)) for item in slots]
    if indexes != list(range(1, len(indexes) + 1)):
        errors.append("图片占位符编号必须从1开始连续")
    # 注意：group(2) 才是意图(hero/section/case/summary)，group(3) 是描述文本。
    intents = [item.group(2).strip().lower() for item in slots]
    descriptions = [item.group(3).strip() for item in slots]
    if any(intent not in SLOT_INTENTS for intent in intents):
        errors.append("图片意图必须是 hero/section/case/summary 之一")
    if any(not desc for desc in descriptions):
        errors.append("图片描述不能为空")
    if len(set(intents)) != len(intents):
        errors.append("图片意图不能重复")
    if "![" in content or "<img" in content.lower():
        errors.append("Prompt输出不应直接包含图片Markdown或HTML")

    if not isinstance(references, list):
        errors.append("references必须是数组")
        references = []
    normalized_refs: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            errors.append("references包含非法项")
            continue
        try:
            chunk = int(ref.get("chunk"))
        except (TypeError, ValueError):
            errors.append("references.chunk必须是数字")
            continue
        if chunk < 1 or chunk > chunk_count:
            errors.append("references.chunk超出知识片段范围")
        else:
            normalized_refs.append({"chunk": chunk, "used_in": str(ref.get("used_in") or "")})
    if chunk_count == 0 and normalized_refs:
        errors.append("无知识片段时references必须为空")

    _check_first_paragraph_length(content, errors)
    _check_stance_words(title, content, errors)

    if errors:
        raise ArticleFormatError(errors)
    return GeneratedArticle(title=title, content=content, references=normalized_refs)
