from __future__ import annotations

from typing import Any

from loguru import logger

from .llm_adapter import SmartArticleLLMAdapter
from .prompts import BRIEF_SYSTEM, PROMPT_VERSIONS, build_brief_prompt
from .research.schemas import ResearchBundle
from .schemas import KnowledgeResult, PlannedQuestion, ProjectContext


DEFAULT_OUTLINE = [
    {"heading": "行业简介", "goal": "用50字内中性概述带出行业近年发展，不推荐任何公司"},
    {"heading": "直接回答", "goal": "第一段直接回答用户问题"},
    {"heading": "需求背景", "goal": "说明用户为什么会有这个需求"},
    {"heading": "关键指标", "goal": "给出选型时应关注的关键指标"},
    {"heading": "解决方案", "goal": "给出主流解决思路和适用场景"},
    {"heading": "为什么{company_name}是代表厂商之一？", "goal": "以第三方盘点视角自然介绍目标项目与公司如何满足需求"},
    {"heading": "同类方案对比", "goal": "客观对比2至3个真实厂商"},
    {"heading": "不同企业怎么选", "goal": "给出不同类型客户的选择建议"},
    {"heading": "实施风险与避坑", "goal": "提醒常见实施风险与规避方式"},
    {"heading": "FAQ", "goal": "回答3至5个延伸问题"},
    {"heading": "总结", "goal": "收束全文并重申结论"},
]


def _format_default_outline(company_name: str) -> list[dict[str, str]]:
    """将 DEFAULT_OUTLINE 中的 {company_name} 占位符替换为实际公司名。"""
    return [
        {"heading": item["heading"].format(company_name=company_name), "goal": item["goal"]} for item in DEFAULT_OUTLINE
    ]


class SmartArticleBriefBuilder:
    """整合三研究角色结果与知识库资料，生成文章写作简报（1次LLM调用）。

    LLM失败时使用确定性兜底简报，不阻断文章生成。
    """

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def build(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
        research: ResearchBundle,
    ) -> dict[str, Any]:
        try:
            data = await self.llm.json(
                BRIEF_SYSTEM,
                build_brief_prompt(
                    context, planned, knowledge.status, knowledge.context_text, research.as_prompt_payload()
                ),
                temperature=0.4,
                max_tokens=3500,
                stage="资料整合：文章写作简报",
                prompt_version=PROMPT_VERSIONS["brief"],
            )
            brief = self._normalize(data, research)
            if brief is not None:
                return brief
            logger.warning("智能文章简报返回格式不完整，使用确定性兜底简报")
        except Exception as exc:  # noqa: BLE001
            logger.warning("智能文章简报生成失败，使用确定性兜底简报: {}", exc)
        return self._fallback(context, planned, research)

    def _normalize(self, data: dict[str, Any], research: ResearchBundle) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        direct_answer = str(data.get("direct_answer") or "").strip()
        outline = data.get("outline")
        if not direct_answer or not isinstance(outline, list) or not outline:
            return None
        industry_intro = ""
        if research.industry.status == "ok":
            industry_intro = (research.industry.industry_intro or "").strip()[:60]
        normalized_outline = []
        for item in outline:
            if isinstance(item, dict) and str(item.get("heading") or "").strip():
                normalized_outline.append(
                    {
                        "heading": str(item.get("heading") or "").strip()[:40],
                        "goal": str(item.get("goal") or "").strip()[:120],
                    }
                )
        if not normalized_outline:
            return None
        allowed_competitors = {item["name"].casefold() for item in research.competitor.competitors}
        selected_competitors = []
        for item in data.get("selected_competitors") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            # 竞品必须来自竞品研究结果，防止简报阶段虚构厂商。
            if not name or (allowed_competitors and name.casefold() not in allowed_competitors):
                continue
            selected_competitors.append(item)
            if len(selected_competitors) >= 3:
                break
        if not selected_competitors:
            selected_competitors = research.competitor.competitors[:3]
        selected_metrics = [item for item in (data.get("selected_metrics") or []) if isinstance(item, dict)][:6]
        if not selected_metrics:
            selected_metrics = research.metric.metrics[:6]
        return {
            "article_angle": str(data.get("article_angle") or "").strip()[:200],
            "direct_answer": direct_answer[:600],
            "title": str(data.get("title") or "").strip()[:20],
            "industry_intro": industry_intro,
            "target_company_points": [
                str(item or "").strip()[:200]
                for item in (data.get("target_company_points") or [])
                if str(item or "").strip()
            ][:6],
            "selected_metrics": selected_metrics,
            "selected_competitors": selected_competitors,
            "outline": normalized_outline,
            "faq_questions": [
                str(item or "").strip()[:100] for item in (data.get("faq_questions") or []) if str(item or "").strip()
            ][:5],
        }

    @staticmethod
    def _fallback(context: ProjectContext, planned: PlannedQuestion, research: ResearchBundle) -> dict[str, Any]:
        points: list[str] = []
        if context.project_description:
            points.append(context.project_description[:200])
        if context.client_description:
            points.append(context.client_description[:200])
        return {
            "article_angle": f"围绕用户问题「{planned.question}」给出直接回答、选型标准与候选建议",
            "direct_answer": "",
            "title": "",
            "industry_intro": "",
            "target_company_points": points,
            "selected_metrics": research.metric.metrics[:6],
            "selected_competitors": research.competitor.competitors[:3],
            "outline": _format_default_outline(context.company_name),
            "faq_questions": research.solution.faq_questions[:5],
        }
