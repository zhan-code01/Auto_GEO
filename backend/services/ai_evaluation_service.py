# -*- coding: utf-8 -*-
"""
AI 评估服务 - 火山方舟 ARK（豆包 + DeepSeek）
v2.0 - 2026-06-25

两个模型均通过 ARK API 调用，内置联网搜索能力：
- DeepSeek-R1 联网搜索版：模型自带联网搜索
- 豆包（doubao-seed-1.6）：通过 ARK web_search 插件实现联网搜索

用途：收录检测模块的测评引擎
- 纯 API 调用，无需浏览器、无需登录授权
- 即使平台已登录，测评也一律走 API

配置（环境变量）：
- VOLCENGINE_ARK_API_KEY: 火山方舟 API Key
- VOLCENGINE_ARK_BASE_URL: API 地址
- VOLCENGINE_ARK_DEEPSEEK_ENDPOINT: DeepSeek 模型/接入点
- VOLCENGINE_ARK_DOUBAO_ENDPOINT: 豆包模型/接入点
"""

import json
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from loguru import logger

from backend.config import (
    VOLCENGINE_ARK_API_KEY,
    VOLCENGINE_ARK_BASE_URL,
    VOLCENGINE_ARK_DEEPSEEK_ENDPOINT,
    VOLCENGINE_ARK_DOUBAO_ENDPOINT,
)


class AIEvaluationService:
    """
    AI 评估服务 - 火山方舟 ARK（豆包 + DeepSeek）

    1. 纯 API 调用，无需浏览器、无需登录授权
    2. DeepSeek-R1 联网搜索版：模型自带联网搜索
    3. 豆包：通过 ARK API + web_search 插件实现联网搜索
    4. 兼容原有 index_check_service 接口
    """

    # 各平台的 ARK 模型/接入点配置
    PLATFORM_ENDPOINTS = {
        "deepseek": {
            "model": VOLCENGINE_ARK_DEEPSEEK_ENDPOINT,
            # DeepSeek-R1 联网搜索版内置搜索，无需 plugins
            "use_search_plugin": False,
        },
        "doubao": {
            "model": VOLCENGINE_ARK_DOUBAO_ENDPOINT,
            # 豆包通过 web_search 插件实现联网搜索
            "use_search_plugin": False,  # DeepSeek API does not support web_search plugin
        },
    }

    def __init__(self):
        self.api_key = VOLCENGINE_ARK_API_KEY
        self.base_url = VOLCENGINE_ARK_BASE_URL.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        # 兼容旧代码：默认 endpoint 指向 deepseek
        self.endpoint = VOLCENGINE_ARK_DEEPSEEK_ENDPOINT

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=120.0,
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
    #  核心方法：联网搜索 + 评估
    # ================================================================

    async def evaluate_keyword(
        self,
        question: str,
        keyword: str,
        company: str,
        platform: str = "deepseek",
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        核心方法：对关键词进行联网搜索并评估是否被收录

        Args:
            question: 搜索问题
            keyword: 目标关键词
            company: 公司名称
            platform: 评估平台（"deepseek" / "doubao"）
            stream: 是否使用流式输出（默认 False）

        Returns:
            评估结果，兼容原有 index_check_service 接口
        """
        platform = platform or "deepseek"
        platform_config = self.PLATFORM_ENDPOINTS.get(platform)
        if not platform_config:
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": f"不支持的平台: {platform}",
            }

        logger.info(f"[API-Eval] platform={platform}, keyword={keyword}, company={company}")
        logger.info(f"   question: {question[:50]}...")

        if not self.api_key:
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": "VOLCENGINE_ARK_API_KEY 未配置",
            }

        try:
            response = await self._call_ark_api(question, platform=platform, stream=stream)

            if not response.get("success"):
                return response

            answer_text = response.get("answer", "")
            check_result = self._check_keywords_in_text(answer_text, keyword, company)
            citations = response.get("citations", [])

            logger.info(
                f"[API-Eval] done: "
                f"keyword_found={check_result['keyword_found']}, "
                f"company_found={check_result['company_found']}, "
                f"confidence={check_result['confidence']:.2f}"
            )

            return {
                "success": True,
                "answer": answer_text,
                "keyword_found": check_result["keyword_found"],
                "company_found": check_result["company_found"],
                "keyword_count": check_result.get("keyword_count", 0),
                "company_count": check_result.get("company_count", 0),
                "confidence": check_result.get("confidence", 0.0),
                "company_matched": check_result.get("company_matched", ""),
                "citations": citations,
                "citation_count": len(citations),
                "error_msg": None,
            }

        except httpx.TimeoutException:
            logger.error(f"[API-Eval-{platform}] request timeout")
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": "API 请求超时",
            }
        except httpx.ConnectError:
            logger.error(f"[API-Eval-{platform}] cannot connect to ARK API")
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": "无法连接火山方舟 API",
            }
        except Exception as e:
            logger.error(f"[API-Eval-{platform}] error: {e}")
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": str(e),
            }

    async def _call_ark_api(
        self,
        question: str,
        platform: str = "deepseek",
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        调用火山方舟 ARK chat completions API（豆包 / DeepSeek）

        豆包通过 web_search 插件实现联网搜索，
        DeepSeek-R1 联网搜索版自带搜索能力。
        """
        url = f"{self.base_url}/chat/completions"

        platform_config = self.PLATFORM_ENDPOINTS.get(platform, self.PLATFORM_ENDPOINTS["deepseek"])
        model_name = platform_config["model"]
        use_search_plugin = platform_config.get("use_search_plugin", False)

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": question}],
            "stream": stream,
        }

        # 豆包通过 web_search 插件实现联网搜索
        if use_search_plugin:
            payload["plugins"] = [{"type": "web_search", "enable": True}]
            logger.info(f"[ARK-{platform}] model={model_name}, stream={stream}, web_search=ON")
        else:
            logger.info(f"[ARK-{platform}] model={model_name}, stream={stream}")

        try:
            resp = await self.client.post(url, json=payload)

            if resp.status_code != 200:
                body = resp.text[:300]
                logger.error(f"[ARK-{platform}] HTTP {resp.status_code}: {body}")
                return {
                    "success": False,
                    "answer": None,
                    "error_msg": f"API HTTP {resp.status_code}: {body}",
                }

            data = resp.json()
            answer_text = self._extract_content_from_response(data)
            citations = self._extract_citations(data)

            usage = data.get("usage", {})
            logger.info(
                f"[ARK-{platform}] response: {len(answer_text)} chars, "
                f"tokens={usage.get('total_tokens', 'N/A')}, "
                f"citations={len(citations)}"
            )

            return {
                "success": True,
                "answer": answer_text,
                "citations": citations,
                "raw": data,
            }

        except Exception as e:
            logger.error(f"[ARK-{platform}] call failed: {e}")
            raise

    def _extract_content_from_response(self, data: Dict) -> str:
        """
        从 ARK API 响应中提取文本内容（OpenAI 兼容格式）
        """
        try:
            choices = data.get("choices", [])
            if not choices:
                return ""

            message = choices[0].get("message", {})
            content = message.get("content", "")

            if content:
                return content

            # DeepSeek-R1 可能在 reasoning 字段中返回内容
            reasoning = message.get("reasoning", "")
            if reasoning:
                pass  # reasoning 是思考过程，content 才是最终回答

            return content

        except Exception as e:
            logger.warning(f"提取响应内容失败: {e}")
            return ""

    def _extract_citations(self, data: Dict) -> List[Dict[str, str]]:
        """
        从 ARK API 响应中提取引用来源
        支持多种格式：citations、annotations、plugin_search_results
        """
        citations = []

        try:
            choices = data.get("choices", [])
            if not choices:
                return citations

            message = choices[0].get("message", {})

            # 方式1：直接 citations 字段（DeepSeek-R1 联网搜索）
            if "citations" in message:
                raw_citations = message["citations"]
                if isinstance(raw_citations, list):
                    for cite in raw_citations:
                        if isinstance(cite, dict):
                            citations.append(
                                {
                                    "url": cite.get("url", cite.get("link", "")),
                                    "title": cite.get("title", cite.get("text", "")[:100]),
                                    "source": cite.get("source", ""),
                                }
                            )
                        elif isinstance(cite, str):
                            citations.append({"url": cite, "title": "", "source": ""})

            # 方式2：annotations 字段
            if "annotations" in message:
                annotations = message["annotations"]
                if isinstance(annotations, list):
                    for ann in annotations:
                        if isinstance(ann, dict):
                            url = ann.get("url", ann.get("link", ""))
                            if url:
                                citations.append(
                                    {
                                        "url": url,
                                        "title": ann.get("title", ann.get("text", "")[:100]),
                                        "source": ann.get("source", ""),
                                    }
                                )

            # 方式3：web_search 插件返回的搜索结果（豆包特有）
            search_results = message.get("plugin_search_results") or message.get("search_results")
            if search_results and isinstance(search_results, list):
                for sr in search_results:
                    if isinstance(sr, dict):
                        url = sr.get("url", sr.get("link", sr.get("origin_url", "")))
                        if url:
                            citations.append(
                                {
                                    "url": url,
                                    "title": sr.get("title", sr.get("content", "")[:100]),
                                    "source": sr.get("site_name", ""),
                                }
                            )

            # 去重
            seen = set()
            unique = []
            for cite in citations:
                url = cite.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    unique.append(cite)

            logger.info(f"提取到 {len(unique)} 个引用来源")
            return unique

        except Exception as e:
            logger.warning(f"提取引用失败: {e}")
            return []

    # ================================================================
    #  关键词检测（复用 base.py 的逻辑）
    # ================================================================

    def _extract_company_layers(self, company: str) -> List[str]:
        """从完整公司名提取分层匹配词"""
        locations = [
            "北京",
            "上海",
            "深圳",
            "广州",
            "杭州",
            "南京",
            "成都",
            "武汉",
            "重庆",
            "西安",
            "天津",
            "苏州",
            "东莞",
            "佛山",
            "合肥",
            "长沙",
            "郑州",
            "济南",
            "青岛",
            "大连",
            "厦门",
            "福州",
            "无锡",
            "宁波",
        ]
        suffixes = [
            "股份有限公司",
            "有限责任公司",
            "集团有限公司",
            "科技有限公司",
            "信息技术有限公司",
            "网络技术有限公司",
            "实业有限公司",
            "贸易有限公司",
            "投资有限公司",
            "控股有限公司",
            "发展有限公司",
            "有限公司",
        ]
        industries = [
            "信息技术",
            "网络技术",
            "生物医药",
            "新能源",
            "科技",
            "实业",
            "贸易",
            "投资",
            "控股",
            "发展",
        ]

        name = company.strip()
        core = name
        for loc in sorted(locations, key=len, reverse=True):
            if core.startswith(loc):
                core = core[len(loc) :]
                break
        for suf in sorted(suffixes, key=len, reverse=True):
            if core.endswith(suf):
                core = core[: -len(suf)]
                break
        industry_matched = ""
        for ind in sorted(industries, key=len, reverse=True):
            if core.endswith(ind):
                industry_matched = ind
                core = core[: -len(ind)]
                break

        core = core.strip()
        layers = []
        seen = set()

        def add(s):
            if s and len(s) >= 2 and s not in seen:
                seen.add(s)
                layers.append(s)

        add(core)
        if core and industry_matched:
            add(core + industry_matched)
        add(name)
        return layers

    def _check_keywords_in_text(self, text: str, keyword: str, company: str) -> Dict[str, Any]:
        """
        检查文本中是否包含关键词和公司名
        复用 base.py 的检测逻辑
        """
        if not text:
            return {
                "keyword_found": False,
                "keyword_count": 0,
                "company_found": False,
                "company_count": 0,
                "company_matched": "",
                "confidence": 0.0,
            }

        def clean_str(s: str) -> str:
            s = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s.lower()

        text_lower = clean_str(text)
        keyword_lower = clean_str(keyword)

        keyword_count = text_lower.count(keyword_lower)
        keyword_positions = [m.start() for m in re.finditer(re.escape(keyword_lower), text_lower)]

        # 公司名分层匹配
        company_layers = self._extract_company_layers(company)
        logger.debug(f"company layers: {' > '.join(company_layers)}")

        company_found = False
        company_count = 0
        company_matched = ""
        company_positions = []

        for layer in company_layers:
            layer_lower = clean_str(layer)
            if len(layer_lower) < 2:
                continue
            count = text_lower.count(layer_lower)
            if count > 0:
                company_found = True
                company_count = count
                company_matched = layer
                company_positions = [m.start() for m in re.finditer(re.escape(layer_lower), text_lower)]
                logger.debug(f"company hit: '{layer}' (layer {company_layers.index(layer) + 1}/{len(company_layers)})")
                break

        # 计算置信度
        confidence = 0.0
        if keyword_count > 0:
            confidence = min(0.5 + keyword_count * 0.1, 0.9)
        if company_found:
            confidence = min(confidence + 0.2, 0.95)

        result = {
            "keyword_found": keyword_count > 0,
            "keyword_count": keyword_count,
            "keyword_positions": keyword_positions[:5],
            "company_found": company_found,
            "company_count": company_count,
            "company_matched": company_matched,
            "confidence": confidence,
        }

        logger.info(
            f"keyword check: found={result['keyword_found']}({keyword_count}), "
            f"company={result['company_found']}({company_count} layer='{company_matched}'), "
            f"confidence={confidence:.2f}"
        )

        return result


# ================================================================
#  单例
# ================================================================

_instance: Optional[AIEvaluationService] = None


def get_ai_evaluation_service() -> AIEvaluationService:
    global _instance
    if _instance is None:
        _instance = AIEvaluationService()
    return _instance
