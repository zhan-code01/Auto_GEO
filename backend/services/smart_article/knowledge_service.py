from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from backend.services.geo_knowledge_service import GeoKnowledgeService
from .query_builder import build_queries
from .query_rewriter import SmartArticleQueryRewriter
from .schemas import KnowledgeResult, PlannedQuestion, ProjectContext, QuerySpec


class SmartArticleKnowledgeService:
    def __init__(self, db: Session, rewriter: SmartArticleQueryRewriter | None = None):
        self.db = db
        self.geo_service = GeoKnowledgeService(db)
        self.rewriter = rewriter or SmartArticleQueryRewriter()

    def retrieve_product_summary(self, context: ProjectContext, max_chars: int = 1500) -> str:
        """问题生成前的轻量RAGFlow查询。

        提取产品解决的问题、核心功能、适用客户、行业和场景相关片段，拼成摘要文本。
        查不到或任何异常都返回空字符串，不阻断问题生成。
        """
        try:
            dataset_ids = self.geo_service.resolve_dataset_ids(context.client)
            if not dataset_ids:
                return ""
            if not self.geo_service.ragflow or not self.geo_service.ragflow.is_configured():
                return ""
            queries = [
                f"{context.project_name} 解决什么问题",
                f"{context.project_name} 核心功能",
                f"{context.domain_keyword} 适用客户 行业",
                f"{context.domain_keyword} 应用场景",
            ]
            chunks = self.geo_service.retrieve_chunks(dataset_ids, queries)
            valid = self.geo_service.dedupe_and_rank_chunks(chunks)
            if not valid:
                return ""
            summary = self.geo_service.format_rag_context(valid[:6])
            return summary[:max_chars]
        except Exception as exc:  # noqa: BLE001
            logger.warning("智能文章问题生成前RAGFlow轻量查询失败，降级为基础资料生成: {}", exc)
            return ""

    async def retrieve(self, context: ProjectContext, planned: PlannedQuestion) -> KnowledgeResult:
        initial = build_queries(context, planned)
        dataset_ids = self.geo_service.resolve_dataset_ids(context.client)
        if not dataset_ids:
            return KnowledgeResult(
                status="empty", initial_queries=initial, retrieval_queries=initial, retrieval_rounds=0,
                dataset_ids=[], warnings=["当前客户没有可用RAGFlow数据集"],
            )
        if not self.geo_service.ragflow or not self.geo_service.ragflow.is_configured():
            return KnowledgeResult(
                status="empty", initial_queries=initial, retrieval_queries=initial, retrieval_rounds=0,
                dataset_ids=dataset_ids, warnings=["RAGFlow未配置"],
            )

        first_chunks = self._retrieve(dataset_ids, initial)
        valid = self.geo_service.dedupe_and_rank_chunks(first_chunks)
        if valid:
            return self._result("available", initial, initial, valid, dataset_ids, 1, False, len(first_chunks))

        retry_queries: list[QuerySpec]
        rewritten = False
        try:
            retry_queries = await self.rewriter.rewrite(context, planned, initial)
            rewritten = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("智能文章Query改写失败，使用确定性兜底: {}", exc)
            retry_queries = self.rewriter.fallback(context, planned)

        # Always include a company/project identity query in the second round.
        second_queries = list(retry_queries)
        identity = QuerySpec(f"{context.company_name} {context.project_name}", "project_identity", "第二轮宽检索")
        if identity.text.casefold() not in {item.text.casefold() for item in second_queries}:
            second_queries.append(identity)
        second_chunks = self._retrieve(dataset_ids, second_queries)
        valid_second = self.geo_service.dedupe_and_rank_chunks(second_chunks)
        all_queries = initial + second_queries
        if valid_second:
            return self._result("available", initial, all_queries, valid_second, dataset_ids, 2, rewritten, len(first_chunks) + len(second_chunks))
        return self._result("empty", initial, all_queries, [], dataset_ids, 2, rewritten, len(first_chunks) + len(second_chunks), ["两轮检索均无有效知识片段"])

    def _retrieve(self, dataset_ids: list[str], queries: list[QuerySpec]) -> list[dict]:
        try:
            return self.geo_service.retrieve_chunks(dataset_ids, [item.text for item in queries])
        except Exception as exc:  # noqa: BLE001
            logger.warning("智能文章RAGFlow检索异常: {}", exc)
            return []

    def _result(
        self,
        status: str,
        initial: list[QuerySpec],
        queries: list[QuerySpec],
        chunks: list[dict],
        dataset_ids: list[str],
        rounds: int,
        rewritten: bool,
        raw_count: int,
        warnings: list[str] | None = None,
    ) -> KnowledgeResult:
        return KnowledgeResult(
            status=status,
            chunks=chunks[:12],
            context_text=self.geo_service.format_rag_context(chunks[:12]) if chunks else "",
            initial_queries=initial,
            retrieval_queries=queries,
            retrieval_rounds=rounds,
            query_rewrite_used=rewritten,
            raw_count=raw_count,
            valid_count=min(len(chunks), 12),
            dataset_ids=dataset_ids,
            warnings=warnings or [],
        )
