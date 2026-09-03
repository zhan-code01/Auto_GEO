# -*- coding: utf-8 -*-
"""
llms.txt 渲染器 —— 给 AI/LLM 读的站点摘要（Markdown 格式）。

被两套建站服务共享：
  - WebPageGeneratorService（AI 一键建站）：直接用结构化提取结果
  - SiteGeneratorService（配置驱动建站）：先把 config 适配成渲染器期望的结构

遵循 llms.txt 约定：纯 Markdown，置于站点根，概述公司核心信息以便 AI 检索/摘要。
"""

import re
from typing import Any, Dict, List

# 去标签 + collapse 多余空白
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """清理 HTML 标签（如 <br>）并折叠多余空白，供纯文本场景（llms.txt）使用。

    建站模板里 slogan 等字段常含 <br>（用 | safe 原样输出给浏览器），
    写进 llms.txt 前必须转成纯文本。
    """
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def render_llms_txt(data: Dict[str, Any]) -> str:
    """把结构化站点数据渲染成 llms.txt（Markdown）。缺失字段自动跳过，不抛异常。"""
    lines: List[str] = []

    # 标题
    name = data.get("company_name") or "企业官网"
    slogan = strip_html(data.get("slogan") or "")
    industry = data.get("industry") or ""
    lines.append(f"# {name}")
    if slogan:
        lines.append(f"**Slogan:** {slogan}")
    if industry:
        lines.append(f"**所属行业:** {industry}")
    lines.append("")

    # 完整摘要（llms_summary → ai_overview → description 依次兜底）
    summary = data.get("llms_summary") or data.get("ai_overview") or data.get("description") or ""
    if summary:
        lines.append("## 企业概述")
        lines.append(summary)
        lines.append("")

    # 公司简介
    about = strip_html(data.get("about_intro") or "")
    if about:
        lines.append("## 关于我们")
        lines.append(about)
        lines.append("")

    # 核心数据指标
    stats = data.get("stats") or []
    if stats:
        lines.append("## 核心数据")
        for s in stats:
            val = s.get("value") or ""
            unit = s.get("unit") or ""
            lbl = s.get("label") or ""
            parts = [p for p in [val + unit, lbl] if p]
            if parts:
                lines.append(f"- {''.join(parts)}")
        lines.append("")

    # 主营业务
    services = data.get("services") or []
    if services:
        lines.append("## 主营业务与解决方案")
        for s in services:
            title = s.get("title") or ""
            desc = s.get("desc") or ""
            icon = s.get("icon") or ""
            if title:
                icon_str = f"[{icon}] " if icon else ""
                lines.append(f"### {icon_str}{title}")
                if desc:
                    lines.append(desc)
                lines.append("")

    # 核心优势
    advantages = data.get("advantages") or []
    if advantages:
        lines.append("## 核心优势")
        for adv in advantages:
            adv = strip_html(adv) if isinstance(adv, str) else adv
            if adv:
                lines.append(f"- {adv}")
        lines.append("")

    # 成功案例
    cases = data.get("cases") or []
    if cases:
        lines.append("## 典型客户案例")
        for c in cases:
            tag = c.get("tag") or ""
            title = c.get("title") or ""
            desc = c.get("desc") or ""
            lines.append(f"### [{tag}] {title}" if tag else f"### {title}")
            if desc:
                lines.append(desc)
            lines.append("")
        lines.append("")

    # 资质认证
    quals = data.get("qualifications") or []
    if quals:
        lines.append("## 资质荣誉")
        for q in quals:
            title = q.get("title") or ""
            desc = q.get("desc") or ""
            if title and desc:
                lines.append(f"- **{title}**: {desc}")
            elif title:
                lines.append(f"- {title}")
        lines.append("")

    # 联系方式
    contact = data.get("contact") or {}
    contact_parts = []
    if contact.get("phone"):
        contact_parts.append(f"电话: {contact['phone']}")
    if contact.get("email"):
        contact_parts.append(f"邮箱: {contact['email']}")
    if contact.get("address"):
        contact_parts.append(f"地址: {contact['address']}")
    if contact.get("work_time"):
        contact_parts.append(f"工作时间: {contact['work_time']}")
    if contact_parts:
        lines.append("## 联系方式")
        for p in contact_parts:
            lines.append(p)
        lines.append("")

    # 页面导航
    lines.append("## 页面导航")
    lines.append("- [首页](/index.html)")
    if data.get("services"):
        lines.append("- [核心业务](/index.html#services)")
    if data.get("cases"):
        lines.append("- [客户案例](/index.html#cases)")
    if data.get("about_intro"):
        lines.append("- [关于我们](/index.html#about)")
    if contact:
        lines.append("- [联系我们](/index.html#contact)")
    lines.append("")

    return "\n".join(lines)
