# -*- coding: utf-8 -*-
"""
网页生成服务
基于公司知识库资料 + RAGFlow 检索 + DeepSeek 结构化提取 + Jinja2 模板渲染，
生成高质量企业单页网站。

核心流水线：
  1. 多角度检索 RAGFlow，拉回公司相关文档片段
  2. DeepSeek 只基于检索内容做结构化 JSON 提取（防幻觉）
  3. Jinja2 模板渲染为完整 HTML 页面
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger

from backend.config import (
    AUTOGEO_CONVERSATION_LLM_API_KEY,
    AUTOGEO_CONVERSATION_LLM_BASE_URL,
    AUTOGEO_CONVERSATION_LLM_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
)
from backend.services.ragflow_client import get_ragflow_client


# ==================== 检索预设问题 ====================
# 多角度提问，尽可能把公司全貌从知识库里拉出来
RETRIEVAL_QUERIES = [
    "公司简介 企业介绍 成立时间 规模 团队",
    "主营业务 核心服务 产品 服务内容",
    "公司优势 核心竞争力 技术实力 差异化",
    "成功案例 客户案例 合作伙伴 项目经验",
    "联系方式 地址 电话 邮箱 联系人",
    "资质证书 荣誉 奖项 认证",
    "公司愿景 使命 价值观 发展方向",
    "行业 背景 市场地位",
]


# ==================== DeepSeek System Prompt ====================
SYSTEM_PROMPT = """你是一个企业信息整理专家。

任务：根据提供的检索到的企业文档片段，提取并整理企业关键信息，用于生成企业官网页面。

铁律：
1. 只能使用提供的文档内容，绝不编造、臆测或补充任何文档中没有的信息
2. 文档中没有提及的字段，填 null 或空数组，不要编造
3. 如果文档信息互相矛盾，选择出现次数更多、更具体的那个版本
4. 描述性文字可以适度润色（如调整语序、修正语法），但不能改变原意
5. 不要添加任何"可能"、"大概"等推测性表述
6. slogan 如果文档中没有明确的宣传语，可以基于公司业务提炼一句（不超过20字），但要忠实于原文

输出格式：严格的 JSON，不要包裹在 markdown 代码块中，不要输出任何解释性文字。
JSON 结构如下：
{
  "company_name": "公司全称",
  "company_short": "简称或品牌名（没有则与 company_name 相同）",
  "slogan": "一句话宣传语（≤20字）",
  "description": "公司简介（2-3句话，100-200字）",
  "industry": "所属行业",
  "stats": [
    {"value": "数字或短文本", "unit": "单位（如'+'、'万'等，可为空）", "label": "指标描述"}
  ],
  "services": [
    {"icon": "Font Awesome 图标名（如 fa-code）", "title": "服务名称", "desc": "服务描述（1-2句话）"}
  ],
  "advantages": [
    "核心优势1（一句话）",
    "核心优势2",
    "核心优势3"
  ],
  "cases": [
    {"image": "", "tag": "分类标签", "title": "案例标题", "desc": "案例简述（1-2句话）"}
  ],
  "qualifications": [
    {"title": "资质名称", "desc": "简要说明"}
  ],
  "about_title": "关于我们（标题，如'关于我们'）",
  "about_intro": "关于我们的详细介绍（3-4句话，200字左右）",
  "contact": {
    "phone": "电话",
    "email": "邮箱",
    "address": "地址",
    "work_time": "工作时间（如 周一至周五 9:00-18:00）"
  },
  "meta_title": "网页标题（SEO用，≤30字）",
  "meta_description": "网页描述（SEO用，≤100字）",
  "meta_keywords": "关键词，逗号分隔",
  "ai_overview": "给AI搜索引擎看的页面摘要（≤80字）",
  "llms_summary": "用于 llms.txt 的完整摘要，用简洁的 Markdown 纯文本概述公司核心信息：主营业务、服务亮点、核心优势、目标客户群。200-400字，不要用 Markdown 语法，用纯文本段落和换行组织。"
}

注意：
- icon 字段如果不确信该用什么图标，填 "fa-star"
- cases 中的 image 字段始终填空字符串（后续由用户补充）
- 如果某个数组类型字段在文档中没有相关信息，返回空数组 []
- stats 最多 4 个，services 最多 6 个，cases 最多 6 个，advantages 最多 6 个，qualifications 最多 6 个
"""


class WebPageGeneratorService:
    """网页生成核心服务"""

    def __init__(self):
        base_dir = Path(__file__).resolve().parent.parent
        self.template_dir = base_dir / "templates" / "webpage"
        # 输出到 sites 目录，和智能建站共用部署路径，DeployService 无需改动
        self.output_dir = base_dir / "static" / "sites"

        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # API Key / URL：优先显式配置的 DEEPSEEK_*，否则 fallback 到 AUTOGEO_CONVERSATION_LLM_*
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or DEEPSEEK_API_KEY
        deepseek_url = os.getenv("DEEPSEEK_API_URL", "").strip()
        conversation_key = os.getenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "").strip() or AUTOGEO_CONVERSATION_LLM_API_KEY
        conversation_url = (
            os.getenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "").strip() or AUTOGEO_CONVERSATION_LLM_BASE_URL
        )

        if deepseek_key:
            self.api_key = deepseek_key
            self.api_url = (deepseek_url or DEEPSEEK_API_URL or "https://api.deepseek.com/v1").rstrip("/")
        else:
            self.api_key = conversation_key
            self.api_url = (
                conversation_url or deepseek_url or DEEPSEEK_API_URL or "https://api.deepseek.com/v1"
            ).rstrip("/")

        # 模型名：优先读取环境变量配置（默认 deepseek-v4-flash），不要再硬编码
        self.model = (
            os.getenv("AUTOGEO_CONVERSATION_LLM_MODEL", "").strip()
            or os.getenv("DEEPSEEK_MODEL", "").strip()
            or AUTOGEO_CONVERSATION_LLM_MODEL
            or "deepseek-v4-flash"
        )

    # ==================== Step 1: RAG 检索 ====================

    def _retrieve_context(self, dataset_id: str) -> str:
        """多角度检索 RAGFlow，合并所有相关文档片段。"""
        ragflow = get_ragflow_client()

        if not ragflow.is_configured():
            logger.warning("RAGFlow 未配置，将返回空 context")
            return ""

        all_chunks: List[str] = []
        seen_ids: set = set()

        for query in RETRIEVAL_QUERIES:
            try:
                result = ragflow.retrieve(
                    question=query,
                    dataset_ids=[dataset_id],
                    similarity_threshold=0.3,
                    top_k=8,
                )
                if result.get("code") != 0:
                    continue

                chunks = result.get("data", {}).get("chunks", [])
                for chunk in chunks:
                    chunk_id = chunk.get("id", "")
                    content = chunk.get("content", "").strip()
                    if content and chunk_id not in seen_ids:
                        seen_ids.add(chunk_id)
                        doc_name = chunk.get("document_name") or chunk.get("docname") or ""
                        all_chunks.append(f"【来源：{doc_name}】\n{content}")
            except Exception as e:
                logger.warning(f"检索失败 [{query[:20]}...]: {e}")

        context = "\n\n---\n\n".join(all_chunks)
        logger.info(f"RAG 检索完成：{len(all_chunks)} 个片段，{len(context)} 字符")
        return context

    # ==================== Step 2: DeepSeek 结构化提取 ====================

    async def _extract_structured_data(self, context: str, extra_instructions: str = "") -> Dict[str, Any]:
        """调用 DeepSeek 从 context 中提取结构化企业信息。"""
        if not self.api_key:
            raise RuntimeError(
                "AI API Key 未配置，请在 .env 中设置 DEEPSEEK_API_KEY 或 AUTOGEO_CONVERSATION_LLM_API_KEY"
            )

        if not context.strip():
            raise RuntimeError("知识库中没有检索到任何相关文档，无法生成网页")

        user_prompt = f"""以下是从企业知识库中检索到的文档片段：

{context}

请根据以上资料提取企业信息。{("额外要求：" + extra_instructions) if extra_instructions else ""}

请严格按 JSON 格式输出，不要包裹在 markdown 代码块中。"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                # 针对常见错误状态码给出清晰提示
                if resp.status_code != 200:
                    body = resp.text[:300]
                    if resp.status_code == 402:
                        raise RuntimeError("AI 服务余额不足，请充值 DeepSeek 账户后重试")
                    elif resp.status_code == 401:
                        raise RuntimeError("AI 服务认证失败，请检查 API Key 配置")
                    elif resp.status_code == 429:
                        raise RuntimeError("AI 服务请求过于频繁，请稍后重试")
                    elif resp.status_code >= 500:
                        raise RuntimeError(f"AI 服务暂时不可用 (HTTP {resp.status_code})，请稍后重试")
                    else:
                        raise RuntimeError(f"AI 服务异常 (HTTP {resp.status_code}): {body}")
                data = resp.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            structured = self._parse_json_response(content)

            if not structured:
                raise RuntimeError("LLM 返回内容无法解析为 JSON")

            logger.info(f"结构化数据提取成功：{len(json.dumps(structured, ensure_ascii=False))} 字符")
            return structured

        except httpx.ConnectError:
            raise RuntimeError("无法连接 AI 服务，请检查网络或 API 地址配置")
        except httpx.TimeoutException:
            raise RuntimeError("AI 服务请求超时，请稍后重试")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"DeepSeek 调用失败: {e}")
            raise RuntimeError(f"AI 调用失败: {e}")

    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """容错解析 LLM 返回的 JSON。"""
        content = content.strip()

        # 去掉可能的 markdown 代码块包裹
        if content.startswith("```"):
            lines = content.split("\n")
            start = 1
            end = len(lines)
            for i in range(1, len(lines)):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            content = "\n".join(lines[start:end])

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试找到第一个 { 和最后一个 }
            first = content.find("{")
            last = content.rfind("}")
            if first != -1 and last != -1 and last > first:
                try:
                    return json.loads(content[first : last + 1])
                except json.JSONDecodeError:
                    pass
            logger.error(f"JSON 解析失败，原始内容前200字: {content[:200]}")
            return None

    # ==================== Step 3: Jinja2 模板渲染 ====================

    def _render_html(self, data: Dict[str, Any], template_id: str) -> str:
        """用 Jinja2 模板渲染最终 HTML。"""
        template_map = {
            "tech": "tech_company.html",
            "classic": "classic_corp.html",
            "modern": "modern_minimal.html",
        }
        template_file = template_map.get(template_id, template_map["tech"])

        try:
            template = self.env.get_template(template_file)
        except Exception:
            # 模板不存在时降级到第一个可用的模板
            available = [f for f in template_map.values() if (self.template_dir / f).exists()]
            if not available:
                raise RuntimeError("没有任何网页模板文件，请检查 backend/templates/webpage/ 目录")
            logger.warning(f"模板 {template_file} 不存在，降级使用 {available[0]}")
            template = self.env.get_template(available[0])

        html = template.render(**data, site_url="", canonical_url="")
        return html

    def _render_llms_txt(self, data: Dict[str, Any]) -> str:
        """用结构化数据生成 llms.txt（Markdown 格式，给 AI/LLM 读的站点摘要）。"""
        lines: List[str] = []

        # 标题
        name = data.get("company_name") or "企业官网"
        lines.append(f"# {name}")
        lines.append("")

        # 摘要（优先用 AI 生成的 llms_summary，fallback 到 ai_overview / description）
        summary = data.get("llms_summary") or data.get("ai_overview") or data.get("description") or ""
        if summary:
            lines.append(f"> {summary}")
            lines.append("")

        # 公司简介
        about = data.get("about_intro") or data.get("description") or ""
        if about:
            lines.append("## 关于我们")
            lines.append(about)
            lines.append("")

        # 主营业务
        services = data.get("services") or []
        if services:
            lines.append("## 服务项目")
            for s in services:
                title = s.get("title") or ""
                desc = s.get("desc") or ""
                if title and desc:
                    lines.append(f"- {title}: {desc}")
                elif title:
                    lines.append(f"- {title}")
            lines.append("")

        # 核心优势
        advantages = data.get("advantages") or []
        if advantages:
            lines.append("## 核心优势")
            for adv in advantages:
                lines.append(f"- {adv}")
            lines.append("")

        # 成功案例
        cases = data.get("cases") or []
        if cases:
            lines.append("## 成功案例")
            for c in cases:
                title = c.get("title") or ""
                desc = c.get("desc") or ""
                tag = c.get("tag") or ""
                parts = [p for p in [tag, title, desc] if p]
                if parts:
                    lines.append("- " + " | ".join(parts))
            lines.append("")

        # 资质认证
        quals = data.get("qualifications") or []
        if quals:
            lines.append("## 资质认证")
            for q in quals:
                title = q.get("title") or ""
                desc = q.get("desc") or ""
                if title and desc:
                    lines.append(f"- {title}: {desc}")
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
        lines.append("")

        return "\n".join(lines)

    # ==================== 对外主入口 ====================

    async def generate(
        self,
        company_name: str,
        dataset_id: str,
        template_id: str = "tech",
        extra_instructions: str = "",
        site_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成企业网页。

        Args:
            company_name: 公司名称
            dataset_id: RAGFlow 知识库 ID
            template_id: 模板风格 (tech / classic / modern)
            extra_instructions: 用户额外指令
            site_id: 指定 site_id（复用已有站点记录），不传则新建

        Returns:
            { site_id, preview_url, structured_data }
        """
        # Step 1: 检索
        sid = site_id or uuid.uuid4().hex
        logger.info(f"[WebPage] 开始为公司 '{company_name}' 生成网页 (site_id={sid})")
        context = self._retrieve_context(dataset_id)

        # Step 2: 结构化提取
        structured_data = await self._extract_structured_data(context, extra_instructions)

        # 确保 company_name 不为空
        if not structured_data.get("company_name"):
            structured_data["company_name"] = company_name

        # Step 3: 渲染
        html_content = self._render_html(structured_data, template_id)

        # 写入文件（和智能建站共用 sites 目录）
        page_dir = self.output_dir / sid
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(html_content, encoding="utf-8")

        # 同时生成 llms.txt（给 AI/LLM 读的站点摘要）
        llms_content = self._render_llms_txt(structured_data)
        (page_dir / "llms.txt").write_text(llms_content, encoding="utf-8")

        preview_url = f"/static/sites/{sid}/index.html"

        logger.info(f"[WebPage] 网页生成完成: {preview_url}")

        return {
            "site_id": sid,
            "preview_url": preview_url,
            "structured_data": structured_data,
            "template_id": template_id,
            "context_length": len(context),
            "chunks_retrieved": context.count("【来源："),
        }

    async def regenerate(
        self,
        site_id: str,
        structured_data: Dict[str, Any],
        template_id: str = "tech",
    ) -> Dict[str, Any]:
        """
        使用已有结构化数据重新渲染（换模板 / 微调字段后重新生成）。
        不再调用 RAG / LLM，纯渲染。
        """
        html_content = self._render_html(structured_data, template_id)

        page_dir = self.output_dir / site_id
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(html_content, encoding="utf-8")

        # 同时重新生成 llms.txt
        llms_content = self._render_llms_txt(structured_data)
        (page_dir / "llms.txt").write_text(llms_content, encoding="utf-8")

        preview_url = f"/static/sites/{site_id}/index.html"

        return {
            "site_id": site_id,
            "preview_url": preview_url,
            "template_id": template_id,
        }

    def list_templates(self) -> List[Dict[str, str]]:
        """列出可用模板。"""
        return [
            {
                "id": "tech",
                "name": "科技风尚",
                "description": "深色主题，渐变色彩，适合科技/互联网/创新企业",
                "preview_color": "#0f172a",
            },
            {
                "id": "classic",
                "name": "经典商务",
                "description": "浅色主题，稳重排版，适合传统企业/服务业/制造业",
                "preview_color": "#1e40af",
            },
            {
                "id": "modern",
                "name": "现代极简",
                "description": "大留白，超大字体，适合品牌/设计/咨询公司",
                "preview_color": "#f59e0b",
            },
        ]
