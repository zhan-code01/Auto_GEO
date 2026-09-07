# -*- coding: utf-8 -*-
"""
GEO 统一评估器服务

用固定 prompt + JSON schema 分析 AI 回答，输出结构化评估结果。
使用真实 LLM（DeepSeek/OpenAI-compatible chat completions）评估 AI 平台回答。
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger

from backend.config import (
    AUTOGEO_CONVERSATION_LLM_API_KEY,
    AUTOGEO_CONVERSATION_LLM_BASE_URL,
    AUTOGEO_CONVERSATION_LLM_MODEL,
)

# 评估 schema 版本号
SCHEMA_VERSION = "1.0.0"

# 五档情感映射
SENTIMENT_LABELS = {
    "strongly_positive": 100,
    "positive": 80,
    "neutral": 50,
    "negative": 20,
    "strongly_negative": 0,
}

# 排名分映射
RANK_SCORES = {1: 100, 2: 80, 3: 60, 4: 40, 5: 40}

# LLM Judge 调用稳定性参数
JUDGE_TIMEOUT_SECONDS = 120.0  # 单次请求超时（从 60s 提升到 120s）
JUDGE_MAX_RETRIES = 2  # 额外重试次数（总尝试 = 1 + JUDGE_MAX_RETRIES）
JUDGE_RETRY_BACKOFF = 2.0  # 重试退避基数（秒）


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


# ── LLM Judge 固定 Prompt ──

JUDGE_SYSTEM_PROMPT = """你是一个专业的 AI 搜索引擎结果评估专家（GEO Evaluator）。

你的任务是：分析 AI 聊天机器人对用户问题的回答，评估目标公司/品牌在回答中的表现。

## 评估维度

### 1. 品牌提及 (brand_mentioned)
判断目标公司/品牌是否在 AI 回答中被提及。matched_names 列出所有匹配的名称。

### 2. 推荐排名 (is_recommended / recommendation_rank / ranking_score)
- 明确首推/最推荐/优先考虑 → 第1位, ranking_score=100
- "可以考虑A、B、C"按出现顺序排位 → 第N位
- 只在背景描述顺带提到，不算推荐 → ranking_score=20
- 未提及 → ranking_score=0

### 3. 引用 (citation_supported / own_source_cited)
- citation_supported: 是否提供了可解析来源链接
- own_source_cited: 来源中是否包含我方可控域名

### 4. 情感 (sentiment / sentiment_score)
- strongly_positive (100): 高度正面
- positive (80): 正面
- neutral (50): 中性
- negative (20): 偏负面
- strongly_negative (0): 明显负面
- not_mentioned: 未提及（此时 sentiment_score=0）
只有 brand_mentioned=true 的回答才评估情感。

### 5. 可见度 (visibility_score)

综合计算品牌在本次回答中的 AI 可见度（0-100 分）：

- 品牌未被提及 → visibility = 0
- 品牌被提及 + 有引用来源: visibility = 30 + ranking_score*0.3 + (own_source_cited ? 20 : 0) + sentiment_score*0.2
- 品牌被提及 + 无引用来源: visibility = 40 + ranking_score*0.35 + sentiment_score*0.25

公式含义：出现覆盖率 + 推荐排名 + 引用权重 + 情感权重，四项权重之和为 100%。
引用的 20% 权重在无引用时重新分配给覆盖率和情感。

### 6. 证据 (evidence)
记录评估依据，key-value对。

## 输出格式
严格输出 JSON：
{"brand_mentioned": bool, "matched_names": [], "is_recommended": bool,
 "recommendation_rank": null或int, "ranking_score": 0-100,
 "citation_supported": bool, "own_source_cited": bool,
 "cited_urls": [], "cited_domains": [],
 "sentiment": "positive|neutral|negative|strongly_positive|strongly_negative|not_mentioned",
 "sentiment_score": 0-100, "visibility_score": 0-100,
 "evidence": {}, "confidence": 0.0-1.0}
"""


# ── JSON 提取工具 ──

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_text(raw: str) -> str:
    """从 LLM 原始输出里提取 JSON 文本。

    兼容以下情况：
    - 纯 JSON
    - ```json ... ``` 或 ``` ... ``` 代码块包裹
    - JSON 前后带有解释文字（取第一个 { ... } 片段）
    """
    text = (raw or "").strip()
    if not text:
        return ""

    # 1. 代码块包裹
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()

    # 2. 已是合法 JSON
    if text.startswith("{") or text.startswith("["):
        return text

    # 3. 带解释文字，尝试提取第一个 {...} 片段
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text


def _extract_content(data: Dict[str, Any]) -> str:
    """从 chat completions 响应中提取文本 content。

    兼容 reasoning_content（部分模型把结果放到该字段）以及 content 为空的情况。
    """
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""

    content = (message.get("content") or "").strip() if isinstance(message, dict) else ""
    if content:
        return content

    # content 为空时，部分模型（如深度思考类）会放到 reasoning_content
    reasoning = (message.get("reasoning_content") or "").strip() if isinstance(message, dict) else ""
    return reasoning


class GeoResponseJudgeService:
    """GEO 统一评估器

    评估 AI 回答中的品牌出现、推荐排名、引用、情感和 AI 可见度。
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or AUTOGEO_CONVERSATION_LLM_MODEL

    def _get_api_key(self) -> str:
        return AUTOGEO_CONVERSATION_LLM_API_KEY

    def _get_base_url(self) -> str:
        return AUTOGEO_CONVERSATION_LLM_BASE_URL

    def _get_model(self) -> str:
        return self.model or AUTOGEO_CONVERSATION_LLM_MODEL

    # ── 公开 API ──

    async def evaluate(
        self,
        company_name: str,
        brand_aliases: List[str],
        official_domains: List[str],
        competitors: List[str],
        question: str,
        question_type: str,
        answer: str,
        citations: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """评估单条 AI 回答。

        LLM 评分失败时返回带 judge_error 的降级结果，而不是抛异常，
        以免把 LLM 抖动误判为平台风控失败。
        """
        if not answer:
            raise ValueError("无法评估空回答")
        try:
            return await self._llm_evaluate(
                company_name,
                brand_aliases,
                official_domains,
                competitors,
                question,
                question_type,
                answer,
                citations,
            )
        except Exception as e:
            logger.warning(f"[Judge] LLM 评估失败，返回降级结果: {e}")
            return self._fallback_result(company_name, answer, citations, str(e))

    # ── 真实 LLM 评估 ──

    async def _llm_evaluate(
        self,
        company_name: str,
        brand_aliases: List[str],
        official_domains: List[str],
        competitors: List[str],
        question: str,
        question_type: str,
        answer: str,
        citations: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """通过 httpx 调用 DeepSeek API 进行评估"""
        import httpx

        api_key = self._get_api_key()
        if not api_key:
            raise RuntimeError("未配置 AUTOGEO_CONVERSATION_LLM_API_KEY，无法执行真实 LLM 评估")

        # 构建用户消息
        aliases_text = "、".join(brand_aliases) if brand_aliases else company_name
        domains_text = "、".join(official_domains) if official_domains else "无"
        competitors_text = "、".join(competitors) if competitors else "无"
        citation_text = json.dumps(citations, ensure_ascii=False) if citations else "无引用来源"
        answer_text = answer[:8000]

        user_message = (
            f"## 评估任务\n\n"
            f"**目标公司/品牌：** {company_name}\n"
            f"**品牌别名：** {aliases_text}\n"
            f"**我方可控域名：** {domains_text}\n"
            f"**竞品列表：** {competitors_text}\n"
            f"**提问类型：** {question_type}\n\n"
            f"## 用户提问\n\n{question}\n\n"
            f"## AI 回答\n\n{answer_text}\n\n"
            f"## 引用来源\n\n{citation_text}\n\n"
            f"请严格按 JSON 格式输出评估结果。"
        )

        model = self._get_model()
        base_url = self._get_base_url().rstrip("/")
        url = f"{base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(f"[Judge] API 调用 model={model}")

        last_error = ""
        for attempt in range(1 + JUDGE_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=JUDGE_TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code != 200:
                    last_error = f"API 返回 {resp.status_code}: {resp.text[:300]}"
                    logger.error(f"[Judge] {last_error}")
                    if attempt < JUDGE_MAX_RETRIES:
                        await _sleep(JUDGE_RETRY_BACKOFF * (attempt + 1))
                        continue
                    raise RuntimeError(f"LLM judge {last_error}")

                data = resp.json()
                raw = _extract_content(data)
                logger.debug(f"[Judge] 原始输出(len={len(raw)}): {raw[:200]}...")

                json_text = _extract_json_text(raw)
                if not json_text:
                    last_error = f"LLM 返回空内容(status={resp.status_code})"
                    logger.error(f"[Judge] {last_error}")
                    if attempt < JUDGE_MAX_RETRIES:
                        await _sleep(JUDGE_RETRY_BACKOFF * (attempt + 1))
                        continue
                    raise RuntimeError(f"LLM judge {last_error}")

                try:
                    result = json.loads(json_text)
                except json.JSONDecodeError as e:
                    last_error = f"JSON 解析失败(char {e.pos}): {json_text[:120]!r}"
                    logger.error(f"[Judge] {last_error}")
                    if attempt < JUDGE_MAX_RETRIES:
                        await _sleep(JUDGE_RETRY_BACKOFF * (attempt + 1))
                        continue
                    raise RuntimeError(f"LLM judge {last_error}") from e

                # 解析成功，规范化并返回
                return self._normalize_result(result, citations)

            except httpx.TimeoutException:
                last_error = f"API 超时({JUDGE_TIMEOUT_SECONDS:.0f}s)"
                logger.error(f"[Judge] {last_error} attempt={attempt + 1}/{1 + JUDGE_MAX_RETRIES}")
                if attempt < JUDGE_MAX_RETRIES:
                    await _sleep(JUDGE_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise RuntimeError(f"LLM judge {last_error}")
            except RuntimeError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Judge] 异常: {e} attempt={attempt + 1}/{1 + JUDGE_MAX_RETRIES}")
                if attempt < JUDGE_MAX_RETRIES:
                    await _sleep(JUDGE_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise

        # 理论上不会走到这里
        raise RuntimeError(f"LLM judge 重试耗尽: {last_error}")

    # ── 结果规范化 ──

    def _normalize_result(
        self,
        result: Dict[str, Any],
        citations: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """校验 & 补全评估结果字段"""
        citation_supported = bool(citations)
        cited_urls: List[str] = []
        cited_domains: List[str] = []
        for citation in citations or []:
            if isinstance(citation, dict):
                url = citation.get("url") or citation.get("href")
                domain = citation.get("domain")
            else:
                url = str(citation)
                domain = None
            if url:
                cited_urls.append(url)
            if domain:
                cited_domains.append(domain)

        result.setdefault("brand_mentioned", False)
        result.setdefault("matched_names", [])
        result.setdefault("is_recommended", False)
        result.setdefault("recommendation_rank", None)
        result.setdefault("ranking_score", 0)
        result["citation_supported"] = bool(result.get("citation_supported") or citation_supported)
        result.setdefault("own_source_cited", False)
        if not result.get("cited_urls") and cited_urls:
            result["cited_urls"] = cited_urls
        else:
            result.setdefault("cited_urls", [])
        if not result.get("cited_domains") and cited_domains:
            result["cited_domains"] = cited_domains
        else:
            result.setdefault("cited_domains", [])
        result.setdefault("sentiment", "not_mentioned" if not result.get("brand_mentioned") else "neutral")
        result.setdefault("sentiment_score", 0)
        result.setdefault("visibility_score", 0)
        result.setdefault("evidence", {})
        result.setdefault("confidence", 0.5)
        result["brand_mentioned"] = bool(result["brand_mentioned"])
        result["is_recommended"] = bool(result["is_recommended"])
        result["own_source_cited"] = bool(result["own_source_cited"])
        result["ranking_score"] = _clamp_score(result.get("ranking_score"))
        result["sentiment_score"] = _clamp_score(result.get("sentiment_score"))
        result["visibility_score"] = _clamp_score(result.get("visibility_score"))
        result["schema_version"] = SCHEMA_VERSION

        logger.info(
            f"[Judge] ✅ mentioned={result['brand_mentioned']} "
            f"rec={result['is_recommended']}(R{result.get('recommendation_rank')}) "
            f"rank={result['ranking_score']} "
            f"cited={result['own_source_cited']} "
            f"sentiment={result['sentiment']}({result['sentiment_score']}) "
            f"vis={result['visibility_score']}"
        )
        return result

    def _fallback_result(
        self,
        company_name: str,
        answer: str,
        citations: Optional[List[Dict[str, str]]],
        error: str,
    ) -> Dict[str, Any]:
        """LLM 评分失败时的降级结果：基于关键词做最小可信评估，并标记 judge_error。"""
        mentioned = company_name in answer
        cited_urls: List[str] = []
        cited_domains: List[str] = []
        for citation in citations or []:
            if isinstance(citation, dict):
                if citation.get("url"):
                    cited_urls.append(citation["url"])
                if citation.get("domain"):
                    cited_domains.append(citation["domain"])

        logger.warning(
            f"[Judge] 降级评估 company={company_name} mentioned={mentioned} "
            f"answer_len={len(answer)} error={error[:120]}"
        )

        return {
            "brand_mentioned": mentioned,
            "matched_names": [company_name] if mentioned else [],
            "is_recommended": False,
            "recommendation_rank": None,
            "ranking_score": 0,
            "citation_supported": bool(citations),
            "own_source_cited": False,
            "cited_urls": cited_urls,
            "cited_domains": cited_domains,
            "sentiment": "neutral" if mentioned else "not_mentioned",
            "sentiment_score": 50 if mentioned else 0,
            "visibility_score": 20 if mentioned else 0,
            "evidence": {"judge_error": error[:500], "fallback": True},
            "confidence": 0.1,
            "schema_version": SCHEMA_VERSION,
            "judge_error": error[:500],
        }


# ── 异步工具 ──


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
