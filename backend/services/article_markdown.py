# -*- coding: utf-8 -*-
"""
文章正文 Markdown → HTML 转换。

文章生成的 prompt 要求 LLM 以 Markdown 输出正文（`**加粗**`、`## 标题`、`![](url)`），
但富文本编辑器（WangEditor）、WordPress 以及各平台发布都需要 HTML。统一在入库时把
Markdown 转成 HTML 作为规范格式，避免正文里出现字面的 `**` / `##` 等标记。

调用方应先执行图片稳定化（`_stabilize_image_urls`，基于 Markdown 图片正则）再调用本函数，
否则图片 `![](url)` 已被转成 `<img>` 后无法补 lock。
"""

from __future__ import annotations

import re

import markdown2
from loguru import logger

# 启用的 markdown2 扩展：覆盖 AI 正文常见结构（代码块、表格、删除线、标题锚点）。
_EXTRAS = ["fenced-code-blocks", "tables", "strike", "header-ids"]

# markdown2 偶尔会漏转成对的 **（内容含特殊标点/无空格组合时，如 **'foo'bar**）。
# 兜底：把漏掉的成对 ** 转成 <strong>，再清掉任何落单的 **，杜绝正文出现字面 **。
_STRAY_BOLD_PAIR = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", re.DOTALL)


def _cleanup_stray_bold(html: str) -> str:
    html = _STRAY_BOLD_PAIR.sub(r"<strong>\1</strong>", html)
    return html.replace("**", "")


def markdown_to_html(content: str | None) -> str:
    """
    把 Markdown 正文转成 HTML 片段。

    - 空内容原样返回，不做处理。
    - 幂等友好：若传入的已是 HTML，markdown2 会原样透出，不会破坏已编辑过的文章。
    - 兜底清理残留的 `**`，确保正文不出现字面加粗标记。
    """
    if not content or not content.strip():
        return content or ""

    try:
        html = markdown2.markdown(content, extras=_EXTRAS)
        return _cleanup_stray_bold(html.strip())
    except Exception as exc:  # 转换失败时降级：保留原文，避免阻塞入库
        logger.warning(f"Markdown→HTML 转换失败，回退原文: {exc}")
        return content
