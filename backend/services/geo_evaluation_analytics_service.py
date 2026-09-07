# -*- coding: utf-8 -*-
"""GEO evaluation aggregation service.

The active monitor model uses four visible metrics:
- AI visibility score
- brand coverage rate
- recommendation ranking score
- sentiment score

Citation fields may still exist on records for historical compatibility, but
they are no longer part of aggregation, diagnosis, or UI metrics.
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import GeoEvaluationRecord, GeoPrompt, GeoPromptSet, Project, Client


DIRECT_BRAND_QUESTION_TYPES = {"reputation", "brand_awareness"}


class GeoEvaluationAnalyticsService:
    """Aggregate GEO evaluation records into monitor diagnostics."""

    def __init__(self, db: Session):
        self.db = db

    def _aggregate(
        self,
        records: List[GeoEvaluationRecord],
        *,
        company_name: Optional[str] = None,
        exclude_direct_brand_questions: bool = True,
    ) -> Dict[str, Any]:
        """Aggregate records into the active four-metric model."""
        valid = [r for r in records if r.success and r.answer]
        discovery_records = [
            r
            for r in valid
            if not exclude_direct_brand_questions or not self._is_direct_brand_question(r, company_name)
        ]
        discovery_total = len(discovery_records)
        sentiment_records = [r for r in valid if r.brand_mentioned]

        coverage_rate = 0
        ranking_score = 0
        if discovery_total:
            brand_mentioned_count = sum(1 for r in discovery_records if r.brand_mentioned)
            coverage_rate = round(brand_mentioned_count / discovery_total * 100, 2)

            ranking_scores = [r.ranking_score for r in discovery_records if r.ranking_score is not None]
            ranking_score = round(sum(ranking_scores) / len(ranking_scores), 2) if ranking_scores else 0

        if sentiment_records:
            sentiment_scores = [r.sentiment_score for r in sentiment_records if r.sentiment_score is not None]
            sentiment_score = round(sum(sentiment_scores) / len(sentiment_scores), 2) if sentiment_scores else 0
        else:
            sentiment_score = 0

        visibility_score = self._calc_visibility(coverage_rate, ranking_score, sentiment_score)

        return {
            "answer_count": len(records),
            "valid_count": discovery_total,
            "sentiment_valid_count": len(sentiment_records),
            "excluded_direct_count": len(valid) - len(discovery_records),
            "coverage_rate": coverage_rate,
            "ranking_score": ranking_score,
            "sentiment_score": sentiment_score,
            "visibility_score": visibility_score,
        }

    def _calc_visibility(self, coverage_rate: float, ranking_score: float, sentiment_score: float) -> int:
        """Calculate AI visibility from the three supporting metrics."""
        return round(coverage_rate * 0.40 + ranking_score * 0.35 + sentiment_score * 0.25)

    def _is_direct_brand_question(self, record: GeoEvaluationRecord, company_name: Optional[str] = None) -> bool:
        """Return True when the question itself names the target brand."""
        prompt = getattr(record, "prompt", None)
        question_type = getattr(prompt, "question_type", None)
        if not question_type:
            question_type = getattr(record, "question_type", None)
        if question_type in DIRECT_BRAND_QUESTION_TYPES:
            return True

        if not company_name:
            return False
        question = getattr(record, "question", "") or getattr(prompt, "question", "") or ""
        normalized_question = self._normalize_brand_text(question)
        normalized_company = self._normalize_brand_text(company_name)
        return bool(normalized_company and normalized_company in normalized_question)

    def _normalize_brand_text(self, text: str) -> str:
        return "".join(ch for ch in str(text).lower() if ch.isalnum())

    def get_client_config(self, client_id: int) -> Dict[str, Any]:
        """Get client evaluation config and baseline coverage status."""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return {"client_id": client_id, "error": "公司不存在"}

        prompt_set = (
            self.db.query(GeoPromptSet)
            .filter(GeoPromptSet.client_id == client_id, GeoPromptSet.status.in_(["active", "frozen"]))
            .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
            .first()
        )

        active_prompt_set = None
        active_prompt_ids: set[int] = set()
        if prompt_set:
            active_prompt_ids = {
                row[0]
                for row in self.db.query(GeoPrompt.id)
                .filter(
                    GeoPrompt.prompt_set_id == prompt_set.id,
                    GeoPrompt.status == "active",
                )
                .all()
            }
            active_prompt_set = {
                "id": prompt_set.id,
                "question_count": prompt_set.question_count,
                "question_distribution": prompt_set.question_distribution,
                "status": prompt_set.status,
                "frozen_at": prompt_set.frozen_at.isoformat() if prompt_set.frozen_at else None,
                "version": prompt_set.version,
            }

        all_platforms = ["doubao", "qianwen", "deepseek"]
        platform_statuses = []
        for platform in all_platforms:
            records = (
                self.db.query(GeoEvaluationRecord)
                .filter(
                    GeoEvaluationRecord.client_id == client_id,
                    GeoEvaluationRecord.platform == platform,
                    GeoEvaluationRecord.phase == "baseline",
                )
                .all()
            )
            attempted_ids = {r.prompt_id for r in records if r.prompt_id in active_prompt_ids}
            successful_ids = {
                r.prompt_id for r in records if r.prompt_id in active_prompt_ids and r.success and r.answer
            }
            baseline_at = None
            if records:
                times = [r.asked_at for r in records if r.asked_at]
                if times:
                    baseline_at = max(times).isoformat()
            platform_statuses.append(
                {
                    "platform": platform,
                    "has_baseline": len(successful_ids) > 0,
                    "baseline_count": len(successful_ids),
                    "attempted_count": len(attempted_ids),
                    "failed_count": len(attempted_ids - successful_ids),
                    "unmeasured_count": len(active_prompt_ids - attempted_ids),
                    "recheck_eligible_count": len(successful_ids),
                    "baseline_at": baseline_at,
                }
            )

        baseline_platforms = [p for p in platform_statuses if p["has_baseline"]]
        if not baseline_platforms:
            status = "none"
        elif len(baseline_platforms) == len(all_platforms):
            status = "complete"
        else:
            status = "partial"

        return {
            "client_id": client_id,
            "company_name": client.company_name or client.name,
            "active_prompt_set": active_prompt_set,
            "baseline_status": {
                "status": status,
                "platforms": platform_statuses,
            },
        }

    def get_client_diagnosis(self, client_id: int, days: int = 7) -> Dict[str, Any]:
        """Compare baseline and current GEO evaluation records for a client."""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.warning(f"[GeoAnalytics] 诊断失败：公司不存在 client_id={client_id}")
            return {"error": "公司不存在"}

        prompt_set = (
            self.db.query(GeoPromptSet)
            .filter(GeoPromptSet.client_id == client_id, GeoPromptSet.status.in_(["active", "frozen"]))
            .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
            .first()
        )

        schema_version = "1.0.0"
        baseline_query = self.db.query(GeoEvaluationRecord).filter(
            GeoEvaluationRecord.client_id == client_id,
            GeoEvaluationRecord.phase == "baseline",
            GeoEvaluationRecord.schema_version == schema_version,
        )
        if prompt_set:
            baseline_query = baseline_query.filter(GeoEvaluationRecord.prompt_set_id == prompt_set.id)
        baseline_records = baseline_query.all()

        beijing_now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
        start_date = beijing_now - timedelta(days=days)
        current_query = self.db.query(GeoEvaluationRecord).filter(
            GeoEvaluationRecord.client_id == client_id,
            GeoEvaluationRecord.phase == "ongoing",
            GeoEvaluationRecord.created_at >= start_date,
            GeoEvaluationRecord.schema_version == schema_version,
        )
        if prompt_set:
            current_query = current_query.filter(GeoEvaluationRecord.prompt_set_id == prompt_set.id)
        current_records = current_query.all()

        all_platforms = ["doubao", "qianwen", "deepseek"]
        comparable_platforms = []
        baseline_only_platforms = []
        current_only_platforms = []
        missing_baseline_platforms = []

        paired_keys = {
            (r.platform, r.prompt_id) for r in baseline_records if r.prompt_id is not None and r.success and r.answer
        } & {(r.platform, r.prompt_id) for r in current_records if r.prompt_id is not None and r.success and r.answer}

        for platform in all_platforms:
            has_baseline = any(r.platform == platform and r.success and r.answer for r in baseline_records)
            has_current = any(r.platform == platform and r.success and r.answer for r in current_records)
            has_pairs = any(key[0] == platform for key in paired_keys)
            if has_pairs:
                comparable_platforms.append(platform)
            elif has_baseline:
                baseline_only_platforms.append(platform)
            elif has_current:
                current_only_platforms.append(platform)
            if not has_baseline:
                missing_baseline_platforms.append(platform)

        comparable_baseline_records = [r for r in baseline_records if (r.platform, r.prompt_id) in paired_keys]
        comparable_current_records = [r for r in current_records if (r.platform, r.prompt_id) in paired_keys]
        company_name = client.company_name or client.name
        baseline = self._aggregate(comparable_baseline_records or baseline_records, company_name=company_name)
        current = self._aggregate(comparable_current_records or current_records, company_name=company_name)
        current["window_days"] = days

        current_sufficient = bool(comparable_platforms) and current["valid_count"] > 0
        if current_sufficient:
            vis_before = baseline["visibility_score"]
            vis_after = current["visibility_score"]
            vis_delta = round(vis_after - vis_before, 2)
            delta = {
                "coverage_pp": round(current["coverage_rate"] - baseline["coverage_rate"], 2),
                "ranking_score_delta": round(current["ranking_score"] - baseline["ranking_score"], 2),
                "sentiment_score_delta": round(current["sentiment_score"] - baseline["sentiment_score"], 2),
                "visibility_score_before": vis_before,
                "visibility_score_after": vis_after,
                "visibility_score_delta": vis_delta,
                "verdict": self._verdict(vis_delta, current["valid_count"]),
            }
        else:
            delta = {
                "coverage_pp": None,
                "ranking_score_delta": None,
                "sentiment_score_delta": None,
                "visibility_score_before": baseline["visibility_score"] if baseline["valid_count"] else None,
                "visibility_score_after": None,
                "visibility_score_delta": None,
                "verdict": "数据不足" if baseline["valid_count"] == 0 else "样本不足",
            }

        platform_names = {"doubao": "豆包", "qianwen": "通义千问", "deepseek": "DeepSeek"}
        by_platform = []
        for platform in all_platforms:
            baseline_platform_records = [r for r in baseline_records if r.platform == platform]
            current_platform_records = [r for r in current_records if r.platform == platform]
            platform_pairs = {key for key in paired_keys if key[0] == platform}
            if platform_pairs:
                baseline_platform_records = [
                    r for r in baseline_platform_records if (r.platform, r.prompt_id) in platform_pairs
                ]
                current_platform_records = [
                    r for r in current_platform_records if (r.platform, r.prompt_id) in platform_pairs
                ]
            by_platform.append(
                {
                    "platform": platform,
                    "platform_name": platform_names.get(platform, platform),
                    "baseline": self._aggregate(baseline_platform_records, company_name=company_name),
                    "current": self._aggregate(current_platform_records, company_name=company_name),
                    "baseline_count": len(baseline_platform_records),
                    "current_count": len(current_platform_records),
                }
            )

        by_question_type = []
        type_groups: Dict[str, Dict[str, List[GeoEvaluationRecord]]] = {}
        for record in baseline_records + current_records:
            prompt = self.db.query(GeoPrompt).filter(GeoPrompt.id == record.prompt_id).first()
            if not prompt:
                continue
            question_type = prompt.question_type or "recommendation"
            type_groups.setdefault(question_type, {"baseline": [], "current": []})
            if record.phase == "baseline":
                type_groups[question_type]["baseline"].append(record)
            else:
                type_groups[question_type]["current"].append(record)

        type_labels = {
            "recommendation": "供应商推荐类",
            "scenario": "场景找供应商类",
            "comparison": "采购选型类",
            "business_understanding": "业务理解类",
            "brand_awareness": "品牌认知型",
            "reputation": "口碑评价类",
        }
        for question_type, groups in sorted(type_groups.items()):
            by_question_type.append(
                {
                    "question_type": question_type,
                    "label": type_labels.get(question_type, question_type),
                    "baseline": self._aggregate(
                        groups["baseline"],
                        company_name=company_name,
                        exclude_direct_brand_questions=False,
                    ),
                    "current": self._aggregate(
                        groups["current"],
                        company_name=company_name,
                        exclude_direct_brand_questions=False,
                    ),
                    "baseline_count": len(groups["baseline"]),
                    "current_count": len(groups["current"]),
                }
            )

        by_round = []
        for round_no in [1, 2, 3]:
            baseline_round_records = [r for r in baseline_records if r.round_no == round_no]
            current_round_records = [r for r in current_records if r.round_no == round_no]
            by_round.append(
                {
                    "round": round_no,
                    "baseline": self._aggregate(baseline_round_records, company_name=company_name),
                    "current": self._aggregate(current_round_records, company_name=company_name),
                    "baseline_count": len(baseline_round_records),
                    "current_count": len(current_round_records),
                }
            )

        prompt_set_info = None
        if prompt_set:
            prompt_set_info = {
                "id": prompt_set.id,
                "question_count": prompt_set.question_count,
                "question_distribution": prompt_set.question_distribution,
                "frozen_at": prompt_set.frozen_at.isoformat() if prompt_set.frozen_at else None,
                "version": prompt_set.version,
            }

        logger.info(
            f"[GeoAnalytics] 客户诊断完成: client_id={client_id} company={company_name} "
            f"baseline={len(baseline_records)}条 current={len(current_records)}条 "
            f"comparable_platforms={comparable_platforms} verdict={delta.get('verdict')} "
            f"vis_delta={delta.get('visibility_score_delta')}"
        )
        return {
            "client_id": client_id,
            "company_name": company_name,
            "prompt_set": prompt_set_info,
            "comparable_platforms": comparable_platforms,
            "baseline_only_platforms": baseline_only_platforms,
            "current_only_platforms": current_only_platforms,
            "missing_baseline_platforms": missing_baseline_platforms,
            "baseline": baseline,
            "current": current,
            "delta": delta,
            "by_platform": by_platform,
            "by_question_type": by_question_type,
            "by_round": by_round,
        }

    def get_client_records(
        self,
        client_id: int,
        phase: Optional[str] = None,
        platform: Optional[str] = None,
        question_type: Optional[str] = None,
        brand_mentioned: Optional[bool] = None,
        own_source_cited: Optional[bool] = None,
        sentiment: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 20,
        skip: int = 0,
    ) -> Dict[str, Any]:
        """Get client evidence records. Citation fields are returned only as raw legacy data."""
        query = self.db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.client_id == client_id)

        if phase:
            query = query.filter(GeoEvaluationRecord.phase == phase)
        if platform:
            query = query.filter(GeoEvaluationRecord.platform == platform)
        if brand_mentioned is not None:
            query = query.filter(GeoEvaluationRecord.brand_mentioned == brand_mentioned)
        if own_source_cited is not None:
            query = query.filter(GeoEvaluationRecord.own_source_cited == own_source_cited)
        if sentiment:
            query = query.filter(GeoEvaluationRecord.sentiment == sentiment)
        if success is not None:
            query = query.filter(GeoEvaluationRecord.success == success)
        if question_type:
            query = query.join(GeoPrompt).filter(GeoPrompt.question_type == question_type)

        total = query.count()
        records = query.order_by(GeoEvaluationRecord.created_at.desc()).offset(skip).limit(limit).all()

        items = []
        for record in records:
            prompt = self.db.query(GeoPrompt).filter(GeoPrompt.id == record.prompt_id).first()
            items.append(
                {
                    "id": record.id,
                    "run_id": record.run_id,
                    "client_id": record.client_id,
                    "project_id": record.project_id,
                    "related_project_name": record.related_project_name,
                    "platform": record.platform,
                    "phase": record.phase,
                    "round_no": record.round_no,
                    "question": record.question,
                    "answer": record.answer,
                    "success": record.success,
                    "error_message": record.error_message,
                    "brand_mentioned": record.brand_mentioned,
                    "matched_names": record.matched_names,
                    "is_recommended": record.is_recommended,
                    "recommendation_rank": record.recommendation_rank,
                    "ranking_score": record.ranking_score,
                    "citation_supported": record.citation_supported,
                    "citation_status": record.citation_status,
                    "capture_method": record.capture_method,
                    "own_source_cited": record.own_source_cited,
                    "cited_urls": record.cited_urls,
                    "raw_citations": record.raw_citations,
                    "sentiment": record.sentiment,
                    "sentiment_score": record.sentiment_score,
                    "visibility_score": record.visibility_score,
                    "evidence": record.evidence,
                    "question_type": prompt.question_type if prompt else None,
                    "asked_at": record.asked_at.isoformat() if record.asked_at else None,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                }
            )

        return {"total": total, "items": items, "limit": limit, "skip": skip}

    # ==================== 项目级别（兼容旧接口，内部路由到公司级别） ====================

    def get_config(self, project_id: int) -> Dict[str, Any]:
        """Get project evaluation config and baseline coverage status."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"project_id": project_id, "error": "项目不存在"}

        prompt_set = (
            self.db.query(GeoPromptSet)
            .filter(GeoPromptSet.project_id == project_id, GeoPromptSet.status.in_(["active", "frozen"]))
            .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
            .first()
        )

        active_prompt_set = None
        if prompt_set:
            active_prompt_set = {
                "id": prompt_set.id,
                "question_count": prompt_set.question_count,
                "status": prompt_set.status,
                "frozen_at": prompt_set.frozen_at.isoformat() if prompt_set.frozen_at else None,
                "version": prompt_set.version,
            }

        all_platforms = ["doubao", "qianwen", "deepseek"]
        platform_statuses = []
        for platform in all_platforms:
            records = (
                self.db.query(GeoEvaluationRecord)
                .filter(
                    GeoEvaluationRecord.project_id == project_id,
                    GeoEvaluationRecord.platform == platform,
                    GeoEvaluationRecord.phase == "baseline",
                    GeoEvaluationRecord.success == True,  # noqa: E712
                )
                .all()
            )
            baseline_at = None
            if records:
                times = [r.asked_at for r in records if r.asked_at]
                if times:
                    baseline_at = max(times).isoformat()
            platform_statuses.append(
                {
                    "platform": platform,
                    "has_baseline": len(records) > 0,
                    "baseline_count": len(records),
                    "baseline_at": baseline_at,
                }
            )

        baseline_platforms = [p for p in platform_statuses if p["has_baseline"]]
        if not baseline_platforms:
            status = "none"
        elif len(baseline_platforms) == len(all_platforms):
            status = "complete"
        else:
            status = "partial"

        return {
            "project_id": project_id,
            "project_name": project.name,
            "company_name": project.company_name,
            "active_prompt_set": active_prompt_set,
            "baseline_status": {
                "status": status,
                "platforms": platform_statuses,
            },
        }

    def get_diagnosis(self, project_id: int, days: int = 7) -> Dict[str, Any]:
        """Compare baseline and current GEO evaluation records."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.warning(f"[GeoAnalytics] 诊断失败：项目不存在 project_id={project_id}")
            return {"error": "项目不存在"}

        prompt_set = (
            self.db.query(GeoPromptSet)
            .filter(GeoPromptSet.project_id == project_id, GeoPromptSet.status.in_(["active", "frozen"]))
            .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
            .first()
        )

        schema_version = "1.0.0"
        baseline_query = self.db.query(GeoEvaluationRecord).filter(
            GeoEvaluationRecord.project_id == project_id,
            GeoEvaluationRecord.phase == "baseline",
            GeoEvaluationRecord.schema_version == schema_version,
        )
        if prompt_set:
            baseline_query = baseline_query.filter(GeoEvaluationRecord.prompt_set_id == prompt_set.id)
        baseline_records = baseline_query.all()

        beijing_now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
        start_date = beijing_now - timedelta(days=days)
        current_query = self.db.query(GeoEvaluationRecord).filter(
            GeoEvaluationRecord.project_id == project_id,
            GeoEvaluationRecord.phase == "ongoing",
            GeoEvaluationRecord.created_at >= start_date,
            GeoEvaluationRecord.schema_version == schema_version,
        )
        if prompt_set:
            current_query = current_query.filter(GeoEvaluationRecord.prompt_set_id == prompt_set.id)
        current_records = current_query.all()

        all_platforms = ["doubao", "qianwen", "deepseek"]
        comparable_platforms = []
        baseline_only_platforms = []
        current_only_platforms = []
        missing_baseline_platforms = []

        for platform in all_platforms:
            has_baseline = any(r.platform == platform and r.success and r.answer for r in baseline_records)
            has_current = any(r.platform == platform and r.success and r.answer for r in current_records)
            if has_baseline and has_current:
                comparable_platforms.append(platform)
            elif has_baseline:
                baseline_only_platforms.append(platform)
            elif has_current:
                current_only_platforms.append(platform)
            if not has_baseline:
                missing_baseline_platforms.append(platform)

        comparable_baseline_records = [r for r in baseline_records if r.platform in comparable_platforms]
        comparable_current_records = [r for r in current_records if r.platform in comparable_platforms]
        company_name = project.company_name
        baseline = self._aggregate(comparable_baseline_records or baseline_records, company_name=company_name)
        current = self._aggregate(comparable_current_records or current_records, company_name=company_name)
        current["window_days"] = days

        current_sufficient = bool(comparable_platforms) and current["valid_count"] > 0
        if current_sufficient:
            vis_before = baseline["visibility_score"]
            vis_after = current["visibility_score"]
            vis_delta = round(vis_after - vis_before, 2)
            delta = {
                "coverage_pp": round(current["coverage_rate"] - baseline["coverage_rate"], 2),
                "ranking_score_delta": round(current["ranking_score"] - baseline["ranking_score"], 2),
                "sentiment_score_delta": round(current["sentiment_score"] - baseline["sentiment_score"], 2),
                "visibility_score_before": vis_before,
                "visibility_score_after": vis_after,
                "visibility_score_delta": vis_delta,
                "verdict": self._verdict(vis_delta, current["valid_count"]),
            }
        else:
            delta = {
                "coverage_pp": None,
                "ranking_score_delta": None,
                "sentiment_score_delta": None,
                "visibility_score_before": baseline["visibility_score"] if baseline["valid_count"] else None,
                "visibility_score_after": None,
                "visibility_score_delta": None,
                "verdict": "数据不足" if baseline["valid_count"] == 0 else "样本不足",
            }

        platform_names = {"doubao": "豆包", "qianwen": "通义千问", "deepseek": "DeepSeek"}
        by_platform = []
        for platform in all_platforms:
            baseline_platform_records = [r for r in baseline_records if r.platform == platform]
            current_platform_records = [r for r in current_records if r.platform == platform]
            by_platform.append(
                {
                    "platform": platform,
                    "platform_name": platform_names.get(platform, platform),
                    "baseline": self._aggregate(baseline_platform_records, company_name=company_name),
                    "current": self._aggregate(current_platform_records, company_name=company_name),
                    "baseline_count": len(baseline_platform_records),
                    "current_count": len(current_platform_records),
                }
            )

        by_question_type = []
        type_groups: Dict[str, Dict[str, List[GeoEvaluationRecord]]] = {}
        for record in baseline_records + current_records:
            if not record.prompt:
                continue
            question_type = record.prompt.question_type or "recommendation"
            type_groups.setdefault(question_type, {"baseline": [], "current": []})
            if record.phase == "baseline":
                type_groups[question_type]["baseline"].append(record)
            else:
                type_groups[question_type]["current"].append(record)

        type_labels = {
            "recommendation": "供应商推荐类",
            "scenario": "场景找供应商类",
            "comparison": "采购选型类",
            "business_understanding": "业务理解类",
            "brand_awareness": "品牌认知型",
            "reputation": "口碑评价类",
        }
        for question_type, groups in sorted(type_groups.items()):
            by_question_type.append(
                {
                    "question_type": question_type,
                    "label": type_labels.get(question_type, question_type),
                    "baseline": self._aggregate(
                        groups["baseline"],
                        company_name=company_name,
                        exclude_direct_brand_questions=False,
                    ),
                    "current": self._aggregate(
                        groups["current"],
                        company_name=company_name,
                        exclude_direct_brand_questions=False,
                    ),
                    "baseline_count": len(groups["baseline"]),
                    "current_count": len(groups["current"]),
                }
            )

        by_round = []
        for round_no in [1, 2, 3]:
            baseline_round_records = [r for r in baseline_records if r.round_no == round_no]
            current_round_records = [r for r in current_records if r.round_no == round_no]
            by_round.append(
                {
                    "round": round_no,
                    "baseline": self._aggregate(baseline_round_records, company_name=company_name),
                    "current": self._aggregate(current_round_records, company_name=company_name),
                    "baseline_count": len(baseline_round_records),
                    "current_count": len(current_round_records),
                }
            )

        prompt_set_info = None
        if prompt_set:
            prompt_set_info = {
                "id": prompt_set.id,
                "question_count": prompt_set.question_count,
                "frozen_at": prompt_set.frozen_at.isoformat() if prompt_set.frozen_at else None,
                "version": prompt_set.version,
            }

        logger.info(
            f"[GeoAnalytics] 项目诊断完成: project_id={project_id} project={project.name} "
            f"baseline={len(baseline_records)}条 current={len(current_records)}条 "
            f"comparable_platforms={comparable_platforms} verdict={delta.get('verdict')} "
            f"vis_delta={delta.get('visibility_score_delta')}"
        )
        return {
            "project_id": project_id,
            "project_name": project.name,
            "company_name": project.company_name,
            "prompt_set": prompt_set_info,
            "comparable_platforms": comparable_platforms,
            "baseline_only_platforms": baseline_only_platforms,
            "current_only_platforms": current_only_platforms,
            "missing_baseline_platforms": missing_baseline_platforms,
            "baseline": baseline,
            "current": current,
            "delta": delta,
            "by_platform": by_platform,
            "by_question_type": by_question_type,
            "by_round": by_round,
        }

    def get_records(
        self,
        project_id: int,
        phase: Optional[str] = None,
        platform: Optional[str] = None,
        question_type: Optional[str] = None,
        brand_mentioned: Optional[bool] = None,
        own_source_cited: Optional[bool] = None,
        sentiment: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 20,
        skip: int = 0,
    ) -> Dict[str, Any]:
        """Get evidence records. Citation fields are returned only as raw legacy data."""
        query = self.db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.project_id == project_id)

        if phase:
            query = query.filter(GeoEvaluationRecord.phase == phase)
        if platform:
            query = query.filter(GeoEvaluationRecord.platform == platform)
        if brand_mentioned is not None:
            query = query.filter(GeoEvaluationRecord.brand_mentioned == brand_mentioned)
        if own_source_cited is not None:
            query = query.filter(GeoEvaluationRecord.own_source_cited == own_source_cited)
        if sentiment:
            query = query.filter(GeoEvaluationRecord.sentiment == sentiment)
        if success is not None:
            query = query.filter(GeoEvaluationRecord.success == success)
        if question_type:
            query = query.join(GeoPrompt).filter(GeoPrompt.question_type == question_type)

        total = query.count()
        records = query.order_by(GeoEvaluationRecord.created_at.desc()).offset(skip).limit(limit).all()

        items = []
        for record in records:
            items.append(
                {
                    "id": record.id,
                    "run_id": record.run_id,
                    "platform": record.platform,
                    "phase": record.phase,
                    "round_no": record.round_no,
                    "question": record.question,
                    "answer": record.answer,
                    "success": record.success,
                    "error_message": record.error_message,
                    "brand_mentioned": record.brand_mentioned,
                    "matched_names": record.matched_names,
                    "is_recommended": record.is_recommended,
                    "recommendation_rank": record.recommendation_rank,
                    "ranking_score": record.ranking_score,
                    "citation_supported": record.citation_supported,
                    "citation_status": record.citation_status,
                    "capture_method": record.capture_method,
                    "own_source_cited": record.own_source_cited,
                    "cited_urls": record.cited_urls,
                    "raw_citations": record.raw_citations,
                    "sentiment": record.sentiment,
                    "sentiment_score": record.sentiment_score,
                    "visibility_score": record.visibility_score,
                    "evidence": record.evidence,
                    "question_type": record.prompt.question_type if record.prompt else None,
                    "asked_at": record.asked_at.isoformat() if record.asked_at else None,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                }
            )

        return {"total": total, "items": items, "limit": limit, "skip": skip}

    def _verdict(self, vis_delta: float, sample_count: int) -> str:
        """Return diagnosis verdict based on visibility delta."""
        if sample_count < 30:
            return "样本不足"
        if vis_delta >= 10:
            return "显著提升"
        if vis_delta >= 3:
            return "轻微提升"
        if vis_delta >= -3:
            return "基本持平"
        return "下降"

    # ==================== 竞品与来源分析 ====================

    def get_client_competitor_analysis(
        self,
        client_id: int,
        phase: Optional[str] = None,
        platform: Optional[str] = None,
        top_domains: int = 15,
    ) -> Dict[str, Any]:
        """竞品与来源分析：品牌提及份额 + 引用域名榜 + 自有来源引用率。

        复用测评判卷时落库的 cited_domains / matched_names / own_source_cited 字段，
        做纯读聚合，不改动四指标诊断模型。
        """
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return {"error": "公司不存在"}

        company_name = (client.company_name or client.name or "").strip()
        own_domain = self._extract_domain(client.website)
        own_key = self._normalize_brand_text(company_name)

        # 竞品观察名单来自提示词级配置（geo_prompts.competitor_names）
        watch_names: set = set()
        for (names,) in (
            self.db.query(GeoPrompt.competitor_names)
            .filter(GeoPrompt.client_id == client_id, GeoPrompt.competitor_names.isnot(None))
            .all()
        ):
            for name in names or []:
                if isinstance(name, str) and name.strip():
                    watch_names.add(name.strip())

        query = self.db.query(GeoEvaluationRecord).filter(
            GeoEvaluationRecord.client_id == client_id,
            GeoEvaluationRecord.success == True,  # noqa: E712
            GeoEvaluationRecord.answer.isnot(None),
        )
        if phase:
            query = query.filter(GeoEvaluationRecord.phase == phase)
        if platform:
            query = query.filter(GeoEvaluationRecord.platform == platform)
        records = query.all()
        total = len(records)

        brand_counter: Counter = Counter()
        domain_counter: Counter = Counter()
        own_cited = 0
        platform_stats: Dict[str, Dict[str, Any]] = {}

        for r in records:
            names = {n.strip() for n in (r.matched_names or []) if isinstance(n, str) and n.strip()}
            domains = {d.strip().lower() for d in (r.cited_domains or []) if isinstance(d, str) and d.strip()}
            brand_counter.update(names)
            domain_counter.update(domains)
            if r.own_source_cited:
                own_cited += 1

            stat = platform_stats.setdefault(
                r.platform,
                {"total": 0, "own_cited": 0, "mentions": Counter(), "domains": Counter()},
            )
            stat["total"] += 1
            if r.own_source_cited:
                stat["own_cited"] += 1
            stat["mentions"].update(names)
            stat["domains"].update(domains)

        def _brand_row(name: str, count: int) -> Dict[str, Any]:
            norm = self._normalize_brand_text(name)
            # 公司全称与回答中的简称互为包含即视为我方（如「XX有限公司」vs「XX」）
            is_own = bool(own_key) and bool(norm) and (own_key in norm or norm in own_key)
            return {
                "name": name,
                "mentions": count,
                "share": round(count / total * 100, 1) if total else 0,
                "is_own": is_own,
                "is_competitor": name in watch_names and not is_own,
            }

        brand_shares = sorted(
            (_brand_row(n, c) for n, c in brand_counter.items()),
            key=lambda x: (-x["mentions"], x["name"]),
        )
        domain_rows = [
            {
                "domain": d,
                "citations": c,
                "share": round(c / total * 100, 1) if total else 0,
                "is_own": d == own_domain,
            }
            for d, c in domain_counter.most_common(max(1, top_domains))
        ]

        platform_names = {"doubao": "豆包", "qianwen": "通义千问", "deepseek": "DeepSeek"}
        by_platform = []
        for p, stat in sorted(platform_stats.items(), key=lambda kv: -kv[1]["total"]):
            by_platform.append(
                {
                    "platform": p,
                    "platform_name": platform_names.get(p, p),
                    "total": stat["total"],
                    "own_source_cited": stat["own_cited"],
                    "own_source_rate": round(stat["own_cited"] / stat["total"] * 100, 1) if stat["total"] else 0,
                    "top_names": [_brand_row(n, c) for n, c in stat["mentions"].most_common(5)],
                    "top_domains": [{"domain": d, "citations": c} for d, c in stat["domains"].most_common(8)],
                }
            )

        return {
            "client_id": client_id,
            "company_name": company_name,
            "own_domain": own_domain,
            "competitor_watchlist": sorted(watch_names),
            "total_records": total,
            "own_source_cited_count": own_cited,
            "own_source_rate": round(own_cited / total * 100, 1) if total else 0,
            "brand_shares": brand_shares,
            "top_domains": domain_rows,
            "by_platform": by_platform,
        }

    @staticmethod
    def _extract_domain(url: Optional[str]) -> Optional[str]:
        """Extract bare domain from a website URL, e.g. https://a.b.com/x -> a.b.com."""
        if not url or not str(url).strip():
            return None
        text = str(url).strip().lower()
        text = re.sub(r"^https?://", "", text)
        text = text.split("/", 1)[0].split(":", 1)[0]
        return text or None
