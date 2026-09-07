# -*- coding: utf-8 -*-
"""LLM-enhanced GEO prompt generation.

The template generator remains the deterministic fallback. This service uses an
OpenAI-compatible chat completion model to rewrite and supplement candidate
questions, then validates and fills any gaps before the prompt set is saved.
"""

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from backend.config import (
    AUTOGEO_CONVERSATION_LLM_API_KEY,
    AUTOGEO_CONVERSATION_LLM_BASE_URL,
    AUTOGEO_CONVERSATION_LLM_MODEL,
    DEEPSEEK_API_KEY,
)

try:
    import httpx

    HAS_HTTPX = True
except ImportError:  # pragma: no cover - depends on deployment image
    httpx = None
    HAS_HTTPX = False


VALID_QUESTION_TYPES = {
    "recommendation",
    "scenario",
    "comparison",
    "business_understanding",
    "reputation",
    "brand_awareness",
}

TYPE_REQUIREMENTS = {
    "recommendation": "供应商推荐、区域推荐、主动推荐测试，不直接点名目标公司。",
    "scenario": "具体业务场景、预算/周期/落地问题，贴近真实用户咨询。",
    "comparison": "采购选型、评估维度、服务商差异，不虚构竞品。",
    "business_understanding": "业务关键词理解、采购知识、资质能力、应用场景，不直接点名目标公司。",
    "reputation": "直接询问目标公司的口碑、评价、可靠性。",
    "brand_awareness": "直接询问目标公司是什么、做什么、业务范围。",
}

NEUTRAL_QUESTION_TYPES = {"recommendation", "scenario", "comparison", "business_understanding"}
COMPANY_SELECTION_INTENT_TERMS = {
    "公司",
    "服务商",
    "供应商",
    "厂家",
    "品牌",
    "机构",
    "团队",
    "推荐",
    "哪家",
    "哪些",
    "合作",
    "采购",
    "选型",
    "对比",
    "口碑",
    "案例",
    "解决方案",
}
COMPANY_SELECTION_CONTEXT_TERMS = ("找", "选", "选择", "筛选", "评估", "对比", "推荐", "合作", "采购")
PURE_KNOWLEDGE_PATTERNS = (
    "如何判断",
    "怎么判断",
    "如何评估其",
    "怎么评估其",
    "有什么区别",
    "通常体现",
    "由哪些因素决定",
    "需要注意什么",
    "适合哪些客户",
)


class GeoEvaluationLLMPromptGenerator:
    """Generate GEO evaluation prompts with an LLM and strict local validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 90.0,
        max_retries: int = 2,
    ):
        self.api_key = api_key or AUTOGEO_CONVERSATION_LLM_API_KEY or DEEPSEEK_API_KEY
        self.base_url = (base_url or AUTOGEO_CONVERSATION_LLM_BASE_URL or "").rstrip("/")
        self.model = model or AUTOGEO_CONVERSATION_LLM_MODEL or "deepseek-v4-flash"
        self.timeout = timeout
        self.max_retries = max_retries

    def is_configured(self) -> bool:
        return bool(HAS_HTTPX and self.api_key and self.base_url and self.model)

    def generate(
        self,
        *,
        company_name: str,
        industry: str,
        distribution: Dict[str, int],
        competitors: List[str],
        project_terms: List[str],
        candidates: List[Dict[str, Any]],
        allowed_regions: Optional[List[str]] = None,
        blocked_regions: Optional[List[str]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return validated prompts, or None when LLM generation should fall back."""
        if not self.is_configured():
            logger.info("[GeoPromptLLM] LLM is not configured, using template prompts")
            return None

        accepted: List[Dict[str, Any]] = []
        fallback_candidates = self._dedupe_prompts(candidates, company_name=company_name)

        try:
            for question_type, target_count in distribution.items():
                if target_count <= 0:
                    continue
                type_prompts = self._generate_type_prompts(
                    company_name=company_name,
                    industry=industry,
                    question_type=question_type,
                    target_count=target_count,
                    competitors=competitors,
                    project_terms=project_terms,
                    candidates=[item for item in fallback_candidates if item.get("question_type") == question_type],
                    existing=accepted,
                    allowed_regions=allowed_regions or [],
                    blocked_regions=blocked_regions or [],
                )
                accepted.extend(type_prompts)
        except Exception as exc:
            logger.warning(f"[GeoPromptLLM] LLM generation failed, fallback to template: {exc}")
            return None

        final_prompts = self._order_and_trim(accepted, distribution)
        if sum(1 for item in final_prompts if item.get("question_type") in distribution) != sum(distribution.values()):
            logger.warning("[GeoPromptLLM] Validated LLM prompts did not reach target count, fallback to template")
            return None

        return final_prompts

    def _generate_type_prompts(
        self,
        *,
        company_name: str,
        industry: str,
        question_type: str,
        target_count: int,
        competitors: List[str],
        project_terms: List[str],
        candidates: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
        allowed_regions: List[str],
        blocked_regions: List[str],
    ) -> List[Dict[str, Any]]:
        accepted: List[Dict[str, Any]] = []

        for attempt in range(self.max_retries + 1):
            needed = target_count - len(accepted)
            if needed <= 0:
                break

            raw_items = self._request_questions(
                company_name=company_name,
                industry=industry,
                question_type=question_type,
                target_count=needed,
                competitors=competitors,
                project_terms=project_terms,
                candidates=candidates,
                existing=existing + accepted,
                attempt=attempt,
                allowed_regions=allowed_regions,
                blocked_regions=blocked_regions,
            )
            validated = self._validate_items(
                raw_items,
                question_type=question_type,
                company_name=company_name,
                industry=industry,
                project_terms=project_terms,
                existing=existing + accepted,
                allowed_regions=allowed_regions,
                blocked_regions=blocked_regions,
            )
            accepted.extend(validated[:needed])

        if len(accepted) < target_count:
            accepted.extend(
                self._fill_from_candidates(
                    candidates,
                    question_type=question_type,
                    company_name=company_name,
                    industry=industry,
                    project_terms=project_terms,
                    existing=existing + accepted,
                    needed=target_count - len(accepted),
                    allowed_regions=allowed_regions,
                    blocked_regions=blocked_regions,
                )
            )

        return accepted[:target_count]

    def _request_questions(
        self,
        *,
        company_name: str,
        industry: str,
        question_type: str,
        target_count: int,
        competitors: List[str],
        project_terms: List[str],
        candidates: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
        attempt: int,
        allowed_regions: List[str],
        blocked_regions: List[str],
    ) -> List[Dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": self._user_prompt(
                        company_name=company_name,
                        industry=industry,
                        question_type=question_type,
                        target_count=target_count,
                        competitors=competitors,
                        project_terms=project_terms,
                        candidates=candidates[: max(target_count * 2, 20)],
                        existing=existing[-80:],
                        attempt=attempt,
                        allowed_regions=allowed_regions,
                        blocked_regions=blocked_regions,
                    ),
                },
            ],
            "temperature": 0.35,
            "max_tokens": min(16000, max(3000, target_count * 260)),
            "response_format": {"type": "json_object"},
        }

        url = self._chat_completions_url()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        logger.info(
            f"[GeoPromptLLM] Generating {target_count} {question_type} prompts with {self.model}, attempt={attempt + 1}"
        )
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"LLM API returned {response.status_code}: {response.text[:300]}")

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        raw = (message.get("content") or "").strip()
        if not raw:
            raw = (message.get("reasoning_content") or "").strip()
        return self._parse_items(raw)

    def _system_prompt(self) -> str:
        return (
            "你是GEO测评问题集设计专家。你的任务是生成真实用户会向AI搜索/聊天工具提出的问题。"
            "必须只输出JSON对象，不要输出解释、Markdown或代码块。"
        )

    def _user_prompt(
        self,
        *,
        company_name: str,
        industry: str,
        question_type: str,
        target_count: int,
        competitors: List[str],
        project_terms: List[str],
        candidates: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
        attempt: int,
        allowed_regions: List[str],
        blocked_regions: List[str],
    ) -> str:
        candidate_questions = [item.get("question", "") for item in candidates if item.get("question")]
        existing_questions = [item.get("question", "") for item in existing if item.get("question")]
        return json.dumps(
            {
                "task": "生成GEO测评问题",
                "output_schema": {
                    "questions": [
                        {
                            "question": "中文问题文本",
                            "question_type": question_type,
                            "related_project_name": None,
                            "intent_tags": ["标签1", "标签2"],
                            "competitor_names": [],
                        }
                    ]
                },
                "hard_rules": [
                    f"必须生成正好 {target_count} 条 {question_type} 类型问题",
                    "只输出JSON对象，顶层字段必须是 questions",
                    "每条问题必须自然、具体、像真实用户提问",
                    "不要复制候选问题，要改写、扩展或补充",
                    "不要输出英文问题",
                    "不要编造不存在的竞品或事实",
                    "recommendation/scenario/comparison/business_understanding 必须围绕 industry 或 project_terms 中的真实业务词生成",
                    "中性问题必须能触发AI推荐、比较或评估公司/服务商/供应商，不能只是知识解释或品质判断",
                    "禁止生成类似“如何判断品质稳定性、需要注意什么、有什么区别”的纯知识题，除非问题明确要求推荐或对比供应商",
                    "如果 industry 未填写，不要自行猜测行业，更不要使用本地生活、互联网、品牌营销等泛化行业",
                    "recommendation/scenario/comparison/business_understanding 不要直接点名目标公司",
                    "reputation/brand_awareness 可以直接询问目标公司",
                    "如问题需要地域，只能使用 allowed_regions 中的地域",
                    "禁止使用 blocked_regions 中的地域",
                    "问题长度建议 12 到 80 个中文字符",
                ],
                "question_type": question_type,
                "type_requirement": TYPE_REQUIREMENTS.get(question_type, ""),
                "company_name": company_name,
                "industry": industry or "未填写行业，请优先依据 project_terms 生成问题",
                "competitors": competitors[:8],
                "project_terms": project_terms[:20],
                "allowed_regions": allowed_regions,
                "blocked_regions": blocked_regions,
                "candidate_questions": candidate_questions,
                "already_used_questions": existing_questions,
                "attempt": attempt + 1,
            },
            ensure_ascii=False,
        )

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _parse_items(self, raw: str) -> List[Dict[str, Any]]:
        if not raw:
            return []
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = json.loads(self._extract_json_fragment(text))

        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            questions = parsed.get("questions") or parsed.get("items") or parsed.get("data") or []
            if isinstance(questions, list):
                return [item for item in questions if isinstance(item, dict)]
        return []

    def _extract_json_fragment(self, text: str) -> str:
        object_start = text.find("{")
        object_end = text.rfind("}")
        array_start = text.find("[")
        array_end = text.rfind("]")

        object_fragment = text[object_start : object_end + 1] if object_start >= 0 and object_end > object_start else ""
        array_fragment = text[array_start : array_end + 1] if array_start >= 0 and array_end > array_start else ""

        if object_fragment and (not array_fragment or object_start < array_start):
            return object_fragment
        if array_fragment:
            return array_fragment
        raise json.JSONDecodeError("No JSON fragment found", text, 0)

    def _validate_items(
        self,
        items: List[Dict[str, Any]],
        *,
        question_type: str,
        company_name: str,
        industry: str = "",
        project_terms: Optional[List[str]] = None,
        existing: List[Dict[str, Any]],
        allowed_regions: Optional[List[str]] = None,
        blocked_regions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        accepted: List[Dict[str, Any]] = []
        seen = {self._question_key(item.get("question", "")) for item in existing}

        for item in items:
            normalized, reject_reason = self._normalize_item(
                item,
                question_type,
                company_name,
                industry=industry,
                project_terms=project_terms,
                allowed_regions=allowed_regions,
                blocked_regions=blocked_regions,
            )
            if reject_reason:
                logger.debug(f"[GeoPromptLLM] Reject prompt: {reject_reason}")
                continue

            key = self._question_key(normalized["question"])
            if not key or key in seen:
                continue
            if self._is_similar_to_existing(normalized["question"], existing + accepted):
                continue
            seen.add(key)
            accepted.append(normalized)

        return accepted

    def _normalize_item(
        self,
        item: Dict[str, Any],
        question_type: str,
        company_name: str,
        industry: str = "",
        project_terms: Optional[List[str]] = None,
        allowed_regions: Optional[List[str]] = None,
        blocked_regions: Optional[List[str]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        question = self._clean_question(item.get("question"))
        if not question:
            return None, "empty question"
        if len(question) < 8 or len(question) > 140:
            return None, "question length out of range"
        if self._looks_invalid_text(question):
            return None, "invalid text"
        if question_type not in VALID_QUESTION_TYPES:
            return None, "invalid question type"
        if question_type in NEUTRAL_QUESTION_TYPES and company_name and company_name in question:
            return None, "brand-direct question in neutral type"
        if question_type in NEUTRAL_QUESTION_TYPES and not self._has_company_selection_intent(question):
            return None, "neutral question lacks company selection intent"
        if question_type in NEUTRAL_QUESTION_TYPES and self._is_pure_knowledge_question(question):
            return None, "neutral question is pure knowledge instead of company-related"
        if question_type in NEUTRAL_QUESTION_TYPES and not self._is_domain_relevant(
            question,
            industry=industry,
            project_terms=project_terms or [],
        ):
            return None, "question is not relevant to industry or project terms"
        region_error = self._region_reject_reason(
            question,
            allowed_regions=allowed_regions or [],
            blocked_regions=blocked_regions or [],
        )
        if region_error:
            return None, region_error

        intent_tags = item.get("intent_tags") if isinstance(item.get("intent_tags"), list) else []
        competitor_names = item.get("competitor_names") if isinstance(item.get("competitor_names"), list) else []
        related_project_name = item.get("related_project_name")
        if related_project_name is not None:
            related_project_name = str(related_project_name).strip() or None

        return (
            {
                "question": question,
                "question_type": question_type,
                "related_project_name": related_project_name,
                "intent_tags": [str(tag).strip() for tag in intent_tags if str(tag).strip()][:5],
                "competitor_names": [str(name).strip() for name in competitor_names if str(name).strip()][:5],
            },
            None,
        )

    def _fill_from_candidates(
        self,
        candidates: List[Dict[str, Any]],
        *,
        question_type: str,
        company_name: str,
        industry: str = "",
        project_terms: Optional[List[str]] = None,
        existing: List[Dict[str, Any]],
        needed: int,
        allowed_regions: Optional[List[str]] = None,
        blocked_regions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        filled: List[Dict[str, Any]] = []
        for candidate in candidates:
            normalized, reject_reason = self._normalize_item(
                candidate,
                question_type,
                company_name,
                industry=industry,
                project_terms=project_terms,
                allowed_regions=allowed_regions,
                blocked_regions=blocked_regions,
            )
            if reject_reason:
                continue
            if self._is_similar_to_existing(normalized["question"], existing + filled):
                continue
            filled.append(normalized)
            if len(filled) >= needed:
                break
        return filled

    def _dedupe_prompts(self, prompts: List[Dict[str, Any]], *, company_name: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for item in prompts:
            question_type = item.get("question_type")
            if question_type not in VALID_QUESTION_TYPES:
                continue
            normalized, reject_reason = self._normalize_item(
                item,
                question_type,
                company_name,
                industry=item.get("industry", ""),
                project_terms=[item.get("related_project_name")] if item.get("related_project_name") else [],
            )
            if reject_reason:
                continue
            if self._is_similar_to_existing(normalized["question"], result):
                continue
            result.append(normalized)
        return result

    def _order_and_trim(self, prompts: List[Dict[str, Any]], distribution: Dict[str, int]) -> List[Dict[str, Any]]:
        ordered: List[Dict[str, Any]] = []
        for question_type, count in distribution.items():
            ordered.extend([item for item in prompts if item.get("question_type") == question_type][:count])
        return ordered

    def _clean_question(self, value: Any) -> str:
        if value is None:
            return ""
        question = re.sub(r"\s+", " ", str(value)).strip()
        return question.strip("\"'“”‘’")

    def _question_key(self, question: str) -> str:
        return re.sub(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]{}<>《》]", "", question).lower()

    def _looks_invalid_text(self, question: str) -> bool:
        lower = question.lower()
        blocked = ["作为ai", "我是一个", "无法", "不能提供", "json", "question_type", "示例"]
        if any(token in lower for token in blocked):
            return True
        ascii_letters = sum(1 for char in question if char.isascii() and char.isalpha())
        return bool(ascii_letters and ascii_letters / max(len(question), 1) > 0.35)

    def _is_domain_relevant(self, question: str, *, industry: str, project_terms: List[str]) -> bool:
        terms = [industry, *project_terms]
        cleaned_terms = []
        for term in terms:
            cleaned = str(term or "").strip()
            if cleaned and cleaned not in {"本地生活服务", "服务", "行业"}:
                cleaned_terms.append(cleaned)
        if not cleaned_terms:
            return True
        return any(term in question for term in cleaned_terms)

    def _has_company_selection_intent(self, question: str) -> bool:
        if any(term in question for term in COMPANY_SELECTION_INTENT_TERMS):
            return True
        return "企业" in question and any(term in question for term in COMPANY_SELECTION_CONTEXT_TERMS)

    def _is_pure_knowledge_question(self, question: str) -> bool:
        if not any(pattern in question for pattern in PURE_KNOWLEDGE_PATTERNS):
            return False
        return not self._has_company_selection_intent(question)

    def _region_reject_reason(
        self,
        question: str,
        *,
        allowed_regions: List[str],
        blocked_regions: List[str],
    ) -> Optional[str]:
        if any(region and region in question for region in blocked_regions):
            return "question contains blocked region"
        if not allowed_regions:
            return None
        known_region_hit = [region for region in [*allowed_regions, *blocked_regions] if region and region in question]
        if known_region_hit and not any(region in allowed_regions for region in known_region_hit):
            return "question region is not allowed"
        return None

    def _is_similar_to_existing(self, question: str, existing: List[Dict[str, Any]]) -> bool:
        key = self._question_key(question)
        for item in existing:
            other = self._question_key(item.get("question", ""))
            if not other:
                continue
            if key == other:
                return True
            if SequenceMatcher(None, key, other).ratio() >= 0.92:
                return True
        return False
