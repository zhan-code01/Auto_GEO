# -*- coding: utf-8 -*-
"""
AI 生成服务 - 直连 DeepSeek
v2.0 - 2026-06-23

三个核心能力：
1. 关键词蒸馏：输入核心词 → 产出语义相近的关键词词族（纯术语）
2. 搜索问题生成：输入关键词词族 + 公司信息 → 产出自然搜索问题
3. GEO文章生成：标题优选 → 正文生成 → SEO检测 → 结构化返回

特点：
- 直连 DeepSeek API
- All Prompts in code, traceable & debuggable
- 关键词（检测目标）和搜索问题（提问方式）明确分离
"""

import os
import json
import re
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from backend.config import (
    AUTOGEO_CONVERSATION_LLM_API_KEY,
    AUTOGEO_CONVERSATION_LLM_BASE_URL,
    AUTOGEO_CONVERSATION_LLM_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
)

MAX_OUTPUT_TOKENS_LIMIT = 32768
DEEPSEEK_MAX_TOKENS_SAFE = 8192


class AIGenerationService:
    """直连 DeepSeek 的 AI 生成服务"""

    def __init__(self):
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or DEEPSEEK_API_KEY
        deepseek_url = os.getenv("DEEPSEEK_API_URL", "").strip()
        conversation_key = os.getenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "").strip() or AUTOGEO_CONVERSATION_LLM_API_KEY
        conversation_url = (
            os.getenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "").strip()
            or AUTOGEO_CONVERSATION_LLM_BASE_URL
        )

        if deepseek_key:
            self.api_key = deepseek_key
            self.api_url = (deepseek_url or DEEPSEEK_API_URL or "https://api.deepseek.com/v1").rstrip("/")
        else:
            self.api_key = conversation_key
            self.api_url = (conversation_url or deepseek_url or DEEPSEEK_API_URL or "https://api.deepseek.com/v1").rstrip("/")

        self.model = (
            os.getenv("AUTOGEO_CONVERSATION_LLM_MODEL", "").strip()
            or AUTOGEO_CONVERSATION_LLM_MODEL
            or "deepseek-chat"
        )
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=200.0,
                follow_redirects=True,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ================================================================
    #  底层调用
    # ================================================================

    async def _chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """调用 DeepSeek Chat Completions API"""
        if not self.api_key:
            raise RuntimeError("AI API Key 未配置")

        selected_model = model or self.model
        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.api_url}/chat/completions"
        logger.info(
            f"🛰️ DeepSeek API 调用: model={selected_model}, msgs={len(messages)}, max_tokens={max_tokens}"
        )

        try:
            resp = await self.client.post(url, json=payload)
            if resp.status_code != 200:
                body = resp.text[:300]
                if resp.status_code == 402:
                    raise RuntimeError("DeepSeek 余额不足")
                elif resp.status_code == 429:
                    raise RuntimeError("DeepSeek 请求频率过高")
                raise RuntimeError(f"DeepSeek HTTP {resp.status_code}: {body}")

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            logger.info(f"✅ DeepSeek 响应: {len(content)} chars, tokens={usage}")
            return {"content": content, "usage": usage, "raw": data}

        except httpx.TimeoutException:
            raise RuntimeError("DeepSeek API 超时")
        except httpx.ConnectError:
            raise RuntimeError("无法连接 DeepSeek API")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"DeepSeek 调用失败: {e}")
            raise

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict]:
        """容错解析 JSON"""
        content = content.strip()
        # 去掉 markdown 代码块
        if content.startswith("```"):
            lines = content.split("\n")
            start, end = 1, len(lines)
            for i in range(1, len(lines)):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            content = "\n".join(lines[start:end])

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 { 到 }
            first = content.find("{")
            last = content.rfind("}")
            if first != -1 and last > first:
                try:
                    return json.loads(content[first : last + 1])
                except json.JSONDecodeError:
                    pass
            return None

    @staticmethod
    def _is_output_truncated(result: Dict, max_tokens: int) -> bool:
        usage = (result or {}).get("usage") or {}
        completion = usage.get("completion_tokens") or 0
        content = str(result.get("content") or "").strip()
        return completion >= max_tokens or (not content and completion > 0)

    async def _chat_with_retry(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        json_mode: bool = False,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """_chat 的截断自适应版本，供文章生成等长输出链路复用。

        推理模型（如 deepseek-v4-flash）的 reasoning_tokens 计入 completion_tokens
        配额，输出配额容易被思考占满导致正文/JSON 被截断。本方法检测截断后
        自动翻倍 max_tokens 重试；网关拒绝过大配额时回退到官方安全上限再试。
        截断重试耗尽后返回最后一次结果，由调用方自行降级。
        """
        import asyncio

        current_max_tokens = max_tokens
        last_error = ""
        result: Optional[Dict] = None

        for attempt in range(max_retries + 1):
            truncated = False
            try:
                result = await self._chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=current_max_tokens,
                    json_mode=json_mode,
                )
                truncated = self._is_output_truncated(result, current_max_tokens)
                if not truncated:
                    return result
                last_error = "输出被截断（内容不完整）"
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = str(exc)
                if current_max_tokens > DEEPSEEK_MAX_TOKENS_SAFE:
                    current_max_tokens = DEEPSEEK_MAX_TOKENS_SAFE

            if attempt < max_retries:
                if truncated:
                    current_max_tokens = min(current_max_tokens * 2, MAX_OUTPUT_TOKENS_LIMIT)
                logger.warning(
                    "LLM 输出异常，第{}次重试 ({})，max_tokens 调至 {}",
                    attempt + 1,
                    last_error,
                    current_max_tokens,
                )
                await asyncio.sleep(1)

        if result is not None:
            return result
        raise ValueError(f"LLM 调用连续失败: {last_error}")

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_retries: int = 2,
    ) -> Dict:
        """提供给新业务复用的结构化调用入口，保持现有传输层不变。

        JSON 解析失败时自动重试（最多 max_retries 次），
        避免模型偶发返回非 JSON 内容导致整个批次失败。

        输出被截断（如推理模型 reasoning_tokens 占满配额）时，
        重试会自动调大 max_tokens，避免用相同参数反复失败。
        """
        import asyncio

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Optional[str] = None
        current_max_tokens = max_tokens

        for attempt in range(max_retries + 1):
            try:
                result = await self._chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=current_max_tokens,
                    json_mode=True,
                )
                parsed = self._parse_json(result.get("content", ""))
                if isinstance(parsed, dict):
                    return parsed
                truncated = self._is_output_truncated(result, current_max_tokens)
                last_error = "模型返回内容无法解析为 JSON 对象"
                if truncated:
                    last_error += "（输出被截断）"
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = str(exc)
                truncated = False
                # 网关可能拒绝过大的 max_tokens，回退到官方安全上限再试
                if current_max_tokens > DEEPSEEK_MAX_TOKENS_SAFE:
                    current_max_tokens = DEEPSEEK_MAX_TOKENS_SAFE

            if attempt < max_retries:
                if truncated:
                    current_max_tokens = min(current_max_tokens * 2, MAX_OUTPUT_TOKENS_LIMIT)
                    logger.warning(
                        "LLM JSON 解析失败，第{}次重试 ({})，max_tokens 已调至 {}",
                        attempt + 1,
                        last_error,
                        current_max_tokens,
                    )
                else:
                    logger.warning("LLM JSON 解析失败，第{}次重试 ({})", attempt + 1, last_error)
                await asyncio.sleep(1)

        raise ValueError(f"模型未返回合法 JSON 对象（已重试{max_retries}次）: {last_error}")

    # ================================================================
    #  流式调用（Agent V2 SSE 用）
    # ================================================================

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ):
        """流式调用 DeepSeek，逐 chunk yield 文本 delta。

        用法：
            async for delta in service.chat_stream(messages, max_tokens=512):
                print(delta, end="")

        Yields:
            str: 每个 chunk 的文本增量（可能为空字符串）
        """
        if not self.api_key:
            raise RuntimeError("AI API Key 未配置")

        selected_model = model or self.model
        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        url = f"{self.api_url}/chat/completions"
        logger.info(f"🛰️ DeepSeek API 流式调用: model={selected_model}, msgs={len(messages)}")

        try:
            async with self.client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")[:300]
                    if response.status_code == 402:
                        raise RuntimeError("DeepSeek 余额不足")
                    elif response.status_code == 429:
                        raise RuntimeError("DeepSeek 请求频率过高")
                    raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {body_text}")

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException:
            raise RuntimeError("DeepSeek API 超时")
        except httpx.ConnectError:
            raise RuntimeError("无法连接 DeepSeek API")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"DeepSeek 流式调用失败: {e}")
            raise

    async def chat_json_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        max_retries: int = 2,
    ):
        """流式调用 + JSON 解析。先逐 chunk yield 文本 delta，最后 yield 解析后的 dict。

        Yields:
            str | dict: 先 yield 文本 delta，最后 yield 解析后的 dict（或 None）
        """
        import asyncio

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Optional[str] = None

        for attempt in range(max_retries + 1):
            try:
                full_content = ""
                async for delta in self.chat_stream(
                    messages, temperature=temperature, max_tokens=max_tokens,
                ):
                    full_content += delta
                    yield delta  # 转发给上层
                parsed = self._parse_json(full_content)
                if isinstance(parsed, dict):
                    yield parsed  # 最后 yield 解析结果
                    return
                last_error = "模型返回内容无法解析为 JSON 对象"
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = str(exc)

            if attempt < max_retries:
                logger.warning("LLM JSON 流式解析失败，第%d次重试 (%s)...", attempt + 1, last_error)
                await asyncio.sleep(1)

        # 重试耗尽，yield None 表示解析失败
        yield None

    @staticmethod
    def _print_prompt_to_terminal(label: str, prompt: str, *, article_id: Optional[int] = None) -> None:
        header = f"[AutoGeo Prompt] {label}"
        if article_id is not None:
            header += f" article_id={article_id}"
        border = "=" * 88
        logger.debug(f"\n{border}\n{header}\n{border}\n{prompt}\n{border}")

    # ================================================================
    #  模块一：关键词蒸馏（产出语义相近的词族）
    # ================================================================

    async def distill_keywords(
        self,
        *,
        core_kw: str = "",
        target_info: str = "",
        prefixes: str = "",
        suffixes: str = "",
        # 直接传入关键词列表（跳过生成，仅去重整理）
        keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        关键词蒸馏：输入核心概念，产出语义相近的关键词/术语（词族）。

        如果传入 keywords 列表则跳过生成，直接去重返回；
        否则调 DeepSeek 生成语义变体。
        """
        logger.info(f"🧹 开始关键词蒸馏: {core_kw or f'(整理 {len(keywords or [])} 个关键词)'}")

        if keywords and len(keywords) > 0:
            raw_keywords = list(dict.fromkeys(keywords))
            logger.info(f"📋 跳过生成，直接整理 {len(raw_keywords)} 个关键词")
        else:
            targets = [t.strip() for t in re.split(r"[,，\s]+", target_info) if t.strip()]
            targets_display = "、".join(targets) if targets else core_kw
            prompt = self._build_distill_prompt(core_kw, targets_display)
            result = await self._chat_with_retry(
                messages=[
                    {"role": "system", "content": "你是行业术语专家，只返回JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=8000,
                json_mode=True,
            )
            parsed = self._parse_json(result["content"])
            raw_keywords = parsed.get("keywords", []) if parsed else []
            logger.info(f"📋 蒸馏出 {len(raw_keywords)} 个关键词术语")

        # 去重 + 过滤空值
        clean_keywords = list(dict.fromkeys([kw.strip() for kw in raw_keywords if kw.strip()]))

        return {
            "status": "success",
            "keywords": clean_keywords,
            "count": len(clean_keywords),
        }

    def _build_distill_prompt(self, core_kw: str, targets: str) -> str:
        """构建关键词词族蒸馏 Prompt：产出语义相近的术语，不是搜索短语。"""
        return f"""你是行业术语专家。围绕核心概念「{core_kw}」，生成 15 个语义相近或相关的关键词/术语。

要求：
1. 同义词、近义词、行业的其他叫法
2. 英文缩写/变体（如有）
3. 上下游/细分方向的概念
4. 纯关键词/术语，不是完整句子或搜索问题
5. 不要加"哪家好""排名""推荐""价格""怎么样""厂家"等转化后缀
6. 每词 2-8 字，中性通用

领域上下文：{targets}

严格返回 JSON（只返回 JSON，不要多余文字）：
{{"keywords": ["词1", "词2", "词3", ...]}}"""

    # ================================================================
    #  模块二：搜索问题生成（从关键词词族 + 公司信息产出自然搜索问题）
    # ================================================================

    async def generate_search_questions(
        self,
        *,
        keyword_family: List[str],
        company_name: str = "",
        industry: str = "",
        description: str = "",
        count: int = 25,
    ) -> Dict[str, Any]:
        """
        搜索问题生成：从关键词词族 + 公司/行业信息，产生自然搜索问题。

        用纯文本模式（不用 json_mode），和单关键词生成保持一致，已验证稳定。
        """
        kw_text = "、".join(keyword_family[:20])
        context_parts = []
        if company_name:
            context_parts.append(f"公司：{company_name}")
        if industry:
            context_parts.append(f"行业：{industry}")
        if description:
            context_parts.append(f"描述：{description}")
        context = "；".join(context_parts) if context_parts else ""

        prompt = f"""基于以下信息，生成 {count} 个用户在 AI 搜索平台（豆包、DeepSeek、通义千问）上可能搜索的自然问题。

关键词：{kw_text}
{context}

要求：
1. 像真人在搜索框/聊天框里随手输入的自然语言
2. 覆盖多种意图：了解概念、对比、怎么选、怎么做、误区、价格
3. 句式多样
4. 每行一个问题，不带序号
5. 不要出现具体公司/品牌名"""

        try:
            result = await self._chat_with_retry(
                messages=[
                    {"role": "system", "content": "你是真实用户搜索行为分析专家。只输出问题，每行一个，不要编号、不要多余文字。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                max_tokens=8000,
            )
            content = result.get("content", "")
            lines = [re.sub(r"^[0-9.、\-•·\*]+\s*", "", l).strip() for l in content.strip().split("\n")]
            questions = [l for l in lines if l and 5 < len(l) < 80]
            if questions:
                logger.info(f"📋 生成 {len(questions)} 个搜索问题")
                return {"status": "success", "questions": questions}
            logger.warning(f"搜索问题生成返回空，raw len={len(content)}")
            return {"status": "error", "questions": [], "message": f"返回空，原文{len(content)}字"}
        except Exception as e:
            logger.error(f"搜索问题生成异常: {e}")
            return {"status": "error", "questions": [], "message": str(e)}

    # ================================================================
    #  模块三：GEO 文章生成
    # ================================================================

    async def generate_geo_article(
        self,
        *,
        keyword: str,
        company_name: str = "",
        requirements: str = "",
        word_count: int = 1200,
        article_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        GEO 文章生成增强版：
        Step 1: AI 生成 5 个标题候选
        Step 2: 选最佳标题
        Step 3: AI 按标题写完整文章
        Step 4: SEO 检测 + 结构化返回
        """
        logger.info(f"📝 开始生成文章: keyword={keyword}, company={company_name}, article_id={article_id}")

        knowledge_text = requirements or (
            "当前未提供客户知识库资料，请按通用行业知识写作，"
            "但不要编造具体资质、客户案例、价格或承诺。"
        )

        # ========== Step 1: 生成标题候选 ==========
        title_prompt = f"""为关键词「{keyword}」和公司「{company_name}」生成5个高点击率文章标题。

要求：
- 每个标题15-30字
- 包含关键词「{keyword}」
- 风格：专业、吸引点击、适合B2B
- 不要标题党，不要感叹号

返回JSON：{{"titles": ["标题1", "标题2", "标题3", "标题4", "标题5"]}}"""

        self._print_prompt_to_terminal("Title candidate prompt", title_prompt, article_id=article_id)

        title_result = await self._chat_with_retry(
            messages=[
                {"role": "system", "content": "你是SEO标题专家，只返回JSON。"},
                {"role": "user", "content": title_prompt},
            ],
            temperature=0.8,
            max_tokens=4000,
            json_mode=True,
        )

        title_data = self._parse_json(title_result["content"])
        if title_data and "titles" in title_data:
            titles = title_data["titles"]
        else:
            titles = [
                f"{keyword}全面解析：行业趋势与最佳实践",
                f"深度解读{keyword}：企业如何选择最优方案",
                f"{keyword}指南：从入门到精通",
                f"2024年{keyword}行业分析报告",
                f"{keyword}常见问题解答与避坑指南",
            ]

        best_title = titles[0] if titles else f"{keyword}深度解析"
        logger.info(f"📋 标题候选: {titles[:3]}... → 选定: {best_title}")

        # ========== Step 2: 写完整文章 ==========
        article_prompt = self._build_article_prompt(
            best_title, keyword, company_name, knowledge_text, word_count
        )

        self._print_prompt_to_terminal("Article generation prompt", article_prompt, article_id=article_id)

        article_result = await self._chat_with_retry(
            messages=[
                {"role": "system", "content": "你是拥有10年经验的SEO营销专家，撰写风格稳重专业，适合B2B企业发布。严格按JSON格式输出。"},
                {"role": "user", "content": article_prompt},
            ],
            temperature=0.7,
            max_tokens=8000,
        )

        # 解析文章
        content_text = article_result["content"]
        article_parsed = self._parse_json(content_text)

        if article_parsed and "title" in article_parsed and "content" in article_parsed:
            final_title = article_parsed.get("title", best_title)
            final_content = article_parsed["content"]
        else:
            final_title = best_title
            final_content = content_text

        # v2.0: Parse citation references from AI output
        references = article_parsed.get("references", []) if article_parsed else []
        if not isinstance(references, list):
            references = []
        citation_count = len(references)
        cited_chunks = [ref.get("chunk") for ref in references if isinstance(ref, dict)]

        logger.info(
            f"📄 文章生成完成: {len(final_content)} chars, "
            f"引用知识库片段 {citation_count} 个 (chunks: {cited_chunks})"
        )

        # ========== Step 3: SEO 检测 ==========
        seo_report = self._seo_check(final_content, keyword)

        # ========== Step 4: 组装返回 ==========
        return {
            "status": "success",
            "data": {
                "title": final_title,
                "content": final_content,
            },
            "seo": seo_report,
            "meta": {
                "title_candidates": titles,
                "best_title": best_title,
                "keyword": keyword,
                "company_name": company_name,
                "article_id": article_id,
            },
            "references": references,
            "citation_count": citation_count,
            "cited_chunks": cited_chunks,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }

    def _build_article_prompt(
        self, title: str, keyword: str, company: str, knowledge: str, word_count: int
    ) -> str:
        return f"""请以标题「{title}」为关键词「{keyword}」为公司「{company}」撰写一篇深度、专业的SEO优化文章。

### 核心要求：
1. **身份设定**：你是10年经验的SEO营销专家，风格稳重专业，适合B2B。
2. **公司植入**：自然提及公司【{company}】2-3次，不突兀。
3. **格式要求**：Markdown格式，H1标题、H2/H3小标题。
4. **图文并茂**：
   - 不要输出真实图片 URL，不要输出 loremflickr、pollinations 或任何外链图片。
   - 只在正文中输出 2-3 个图片占位符，短文或 H2 较少时输出 2 个，结构完整的常规文章输出 3 个。
   - 占位符格式严格为：{{{{IMAGE_SLOT:序号|类型|英文图片意图}}}}
   - 类型只允许 hero、section、case、summary；第1张通常用 hero，其余用 section/case/summary。
   - 英文图片意图必须优先围绕文章关键词「{keyword}」及所在小节语义生成，包含具体可拍摄对象；不要只写 business、office、meeting。
   - 不同占位符的英文图片意图不能重复，应覆盖“行业场景、工具设备、团队/流程、成果展示”等不同角度。
   - 示例：{{{{IMAGE_SLOT:1|hero|ai assistant automated report dashboard}}}}
5. **字数要求**：正文 {word_count - 200}-{word_count + 200} 字。

### 客户知识库参考资料：
{knowledge}

### 知识库使用规则：
- 优先使用资料中的公司、产品、服务信息
- 资料不足时补充通用行业观点，不编造资质、案例、价格
- 自然融入，不要逐字罗列
- 如果引用了知识库某个片段的事实，请在 references 中标注来源片段编号

### 输出格式：
严格只返回JSON：
{{"title": "{title}", "content": "完整Markdown正文", "references": [{{"chunk": 1, "used_in": "简述在此处使用了该资料的哪个事实或段落"}}]}}

references 说明：
- chunk 是上面【客户知识库片段 N】的编号
- 只列出实际使用了的片段，没有使用的不要列
- 如果没有使用任何知识库资料（纯通用知识创作），返回空数组 []"""

    @staticmethod
    def _seo_check(content: str, keyword: str) -> Dict[str, Any]:
        """SEO 检测"""
        # 统计
        word_count = len(re.sub(r"[\s#*>[\]()!-]", "", content))
        image_count = len(
            re.findall(r"\{\{IMAGE_SLOT:", content)
            + re.findall(r"/static/uploads/article-images/", content)
            + re.findall(r"!\[[^\]]*\]\([^)]+\)", content)
            + re.findall(r"<img[^>]+src=", content, flags=re.IGNORECASE)
        )
        h2_count = len(re.findall(r"^##\s", content, re.MULTILINE))
        keyword_count = len(re.findall(re.escape(keyword), content))
        keyword_density = f"{(keyword_count / word_count * 100):.1f}%" if word_count > 0 else "0%"

        # 检查问题
        issues = []
        suggestions = []

        density_val = float(keyword_density.rstrip("%"))
        if density_val < 1:
            issues.append(f"关键词密度过低（{keyword_density}）")
            suggestions.append("建议增加关键词出现频率")
        elif density_val > 5:
            issues.append(f"关键词密度过高（{keyword_density}），可能被判堆砌")
            suggestions.append("建议减少关键词出现次数")

        if image_count < 2:
            issues.append(f"图片数量不足（{image_count}/2）")
            suggestions.append("建议输出2-3个图片占位符")

        if word_count < 600:
            issues.append(f"字数偏少（{word_count}字）")
            suggestions.append("建议扩充内容到800字以上")

        if h2_count < 3:
            issues.append(f"H2小标题不足（{h2_count}/3）")
            suggestions.append("建议增加小标题提升结构感")

        # 计算分数
        score = max(60, 100 - len(issues) * 8)

        if not issues:
            suggestions.append("文章SEO质量优秀，可以发布")

        return {
            "score": score,
            "keyword_density": keyword_density,
            "word_count": word_count,
            "image_count": image_count,
            "h2_count": h2_count,
            "keyword_count": keyword_count,
            "issues": issues,
            "suggestions": suggestions,
            "readability": "Good" if word_count > 800 else "Fair",
        }


# ================================================================
#  单例
# ================================================================

_instance: Optional[AIGenerationService] = None


def get_ai_service() -> AIGenerationService:
    global _instance
    if _instance is None:
        _instance = AIGenerationService()
    return _instance


# ================================================================
#  LangChain ChatOpenAI 适配器（供 Agent V2 ReAct Tool Calling 用）
# ================================================================

_chat_model_instance: Optional[Any] = None


def get_chat_model():
    """返回 LangChain ChatOpenAI 实例（懒加载，全局共享）。

    复用 AIGenerationService 的 api_key / api_url / model 配置，
    让 Agent V2 能用 llm.bind_tools(tools).ainvoke(messages) 实现原生 Tool Calling。

    对应 PRD §4.4 ReAct Agent 节点的 LLM 调用方式。
    """
    global _chat_model_instance
    if _chat_model_instance is not None:
        return _chat_model_instance

    from langchain_openai import ChatOpenAI

    service = get_ai_service()
    # ChatOpenAI 需要 openai_api_key/base_url，DeepSeek API 兼容 OpenAI 协议
    _chat_model_instance = ChatOpenAI(
        model=service.model,
        api_key=service.api_key,
        base_url=service.api_url,
        temperature=0.1,
        max_tokens=2048,
        timeout=60,
        max_retries=2,
    )
    logger.info(
        f"[get_chat_model] LangChain ChatOpenAI 初始化: model={service.model} "
        f"base_url={service.api_url}"
    )
    return _chat_model_instance
