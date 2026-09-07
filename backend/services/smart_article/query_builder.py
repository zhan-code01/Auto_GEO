from __future__ import annotations

import re

from .region_context import detect_region
from .schemas import CONTEXT_TYPES, INTENT_TYPES, PlannedQuestion, ProjectContext, QuerySpec


STOP_WORDS = {
    "如何",
    "哪些",
    "什么",
    "怎么",
    "为什么",
    "有没有",
    "是否",
    "比较",
    "值得",
    "可以",
    "应该",
    "需要",
    "关注",
    "了解",
    "推荐",
    "选择",
    "哪个",
    "哪些是",
    "的",
    "吗",
    "呢",
    "有哪些",
}


def _clean(text: str) -> str:
    return " ".join(str(text or "").replace("？", "").replace("?", "").split()).strip()


def extract_core_terms(text: str, known_terms: list[str] | None = None) -> list[str]:
    value = str(text or "")
    terms: list[str] = []
    for term in known_terms or []:
        term = _clean(term)
        if term and term not in terms:
            terms.append(term)
    chunks = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", value)
    for chunk in chunks:
        if chunk in STOP_WORDS or chunk in terms:
            continue
        if len(chunk) > 18:
            # The full question is already preserved as user_need; do not turn
            # a long sentence into a misleading partial capability term.
            continue
        if chunk not in terms:
            terms.append(chunk)
    return terms[:5]


INTENT_TERMS = {
    "provider": "公司介绍 项目能力",
    "selection": "产品功能 接入方式 交付实施",
    "solution": "解决方案 应用场景 用户需求",
    "comparison": "产品特点 适用场景 方案差异",
    "scenario": "应用场景 适用对象",
    "implementation": "部署 集成 实施",
    "risk": "服务流程 支持 注意事项",
    "manual": "产品介绍 项目能力",
}


def build_queries(context: ProjectContext, planned: PlannedQuestion) -> list[QuerySpec]:
    """Build 3-6 deterministic QuerySpecs from one final question."""
    terms = extract_core_terms(planned.question, planned.retrieval_terms)
    specs: list[QuerySpec] = []

    def add(text: str, kind: str, purpose: str) -> None:
        text = _clean(text)
        if not text or kind not in {"project_identity", "user_need", "capability_match", "region_verification"}:
            return
        normalized = text.casefold()
        if any(existing.text.casefold() == normalized for existing in specs):
            return
        specs.append(QuerySpec(text=text, kind=kind, purpose=purpose))

    add(f"{context.company_name} {context.project_name} 产品介绍", "project_identity", "查找公司和项目基础事实")
    add(planned.question, "user_need", "检索与完整用户问题相关的资料")
    domain_parts = list(
        dict.fromkeys(part for part in [context.project_name, context.industry, context.domain_keyword] if part)
    )
    domain_query = " ".join(domain_parts)
    add(domain_query, "user_need", "检索项目领域和通用场景资料")

    term_query = " ".join([context.company_name, context.project_name, *terms[:3]]).strip()
    add(term_query, "capability_match", "查找与用户需求对应的项目能力资料")
    add(
        f"{context.company_name} {context.project_name} {INTENT_TERMS.get(planned.intent_type, INTENT_TERMS['manual'])}",
        "capability_match",
        "按问题意图查找产品能力、方案或交付资料",
    )

    region = detect_region(planned.question, context.allowed_regions)
    if planned.context_type == "region" or region:
        region = region or context.location
        if region:
            add(
                f"{context.company_name} {region} {context.project_name} 公司介绍",
                "region_verification",
                "核验公司地域归属资料",
            )
            add(
                f"{context.company_name} {context.project_name} 服务区域 交付方式",
                "region_verification",
                "核验服务区域和交付方式",
            )

    return specs[:6]
