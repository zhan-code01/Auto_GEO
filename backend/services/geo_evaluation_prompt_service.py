# -*- coding: utf-8 -*-
"""
GEO 测评问题集服务

生成、保存、冻结、读取测评问题集。
公司级别粒度，支持指定项目名称生成业务问题。
默认生成 100 个测评问题：60 供应商推荐、15 场景找供应商、15 采购选型、5 品牌认知、5 口碑评价。
"""

import json
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from backend.database.models import (
    Client,
    GeoEvaluationRecord,
    GeoPrompt,
    GeoPromptSet,
    Keyword,
    Project,
    SmartArticleQuestion,
)
from backend.services.geo_evaluation_llm_prompt_generator import GeoEvaluationLLMPromptGenerator
from loguru import logger


# 默认问题类型分布（100 题）。
# 收录监控衡量的是“AI 是否会把目标公司纳入回答”，纯知识问答通常不会自然推荐公司，
# 因此默认不再生成 business_understanding，避免把无关问题计入可见性指标。
DEFAULT_DISTRIBUTION = {
    "recommendation": 60,
    "scenario": 15,
    "comparison": 15,
    "business_understanding": 0,
    "brand_awareness": 5,
    "reputation": 5,
}

# For a GEO evaluation set, most neutral questions should exercise the
# company's real services/products rather than generic industry phrasing.
DEFAULT_PROJECT_TERM_QUESTION_COUNT = 75

TYPE_LABELS = {
    "recommendation": "供应商推荐类",
    "scenario": "场景需求类",
    "comparison": "采购选型类",
    "business_understanding": "业务理解类",
    "brand_awareness": "品牌认知型",
    "reputation": "口碑评价类",
}

# 地域问题比例：只影响推荐/对比/场景型问题，口碑与品牌认知不随机加地域。
REGIONAL_QUESTION_RATIOS = {
    "recommendation": 0.40,
    "comparison": 0.30,
    "scenario": 0.30,
}

CITY_REGION_EXPANSIONS = {
    # 直辖市
    "北京": ["北京", "京津冀", "华北", "全国"],
    "天津": ["天津", "京津冀", "华北", "全国"],
    "上海": ["上海", "长三角", "华东", "全国"],
    "重庆": ["重庆", "成渝", "西南", "全国"],
    # 省会/自治区首府/特别行政区/台湾省会
    "石家庄": ["石家庄", "河北", "京津冀", "华北", "全国"],
    "太原": ["太原", "山西", "华北", "全国"],
    "呼和浩特": ["呼和浩特", "内蒙古", "华北", "全国"],
    "沈阳": ["沈阳", "辽宁", "东北", "全国"],
    "长春": ["长春", "吉林", "东北", "全国"],
    "哈尔滨": ["哈尔滨", "黑龙江", "东北", "全国"],
    "南京": ["南京", "江苏", "长三角", "华东", "全国"],
    "杭州": ["杭州", "浙江", "长三角", "华东", "全国"],
    "合肥": ["合肥", "安徽", "长三角", "华东", "全国"],
    "福州": ["福州", "福建", "海峡西岸", "华东", "全国"],
    "南昌": ["南昌", "江西", "华东", "全国"],
    "济南": ["济南", "山东", "华东", "全国"],
    "郑州": ["郑州", "河南", "中原", "华中", "全国"],
    "武汉": ["武汉", "湖北", "长江中游", "华中", "全国"],
    "长沙": ["长沙", "湖南", "长江中游", "华中", "全国"],
    "广州": ["广州", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "南宁": ["南宁", "广西", "华南", "全国"],
    "海口": ["海口", "海南", "华南", "全国"],
    "成都": ["成都", "四川", "成渝", "西南", "全国"],
    "贵阳": ["贵阳", "贵州", "西南", "全国"],
    "昆明": ["昆明", "云南", "西南", "全国"],
    "拉萨": ["拉萨", "西藏", "西南", "全国"],
    "西安": ["西安", "陕西", "关中平原", "西北", "全国"],
    "兰州": ["兰州", "甘肃", "西北", "全国"],
    "西宁": ["西宁", "青海", "西北", "全国"],
    "银川": ["银川", "宁夏", "西北", "全国"],
    "乌鲁木齐": ["乌鲁木齐", "新疆", "西北", "全国"],
    "台北": ["台北", "台湾", "华东", "全国"],
    "香港": ["香港", "粤港澳大湾区", "华南", "全国"],
    "澳门": ["澳门", "粤港澳大湾区", "华南", "全国"],
    # 高频非省会城市与重点城市群节点
    "深圳": ["深圳", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "佛山": ["佛山", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "东莞": ["东莞", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "珠海": ["珠海", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "苏州": ["苏州", "江苏", "长三角", "华东", "全国"],
    "无锡": ["无锡", "江苏", "长三角", "华东", "全国"],
    "常州": ["常州", "江苏", "长三角", "华东", "全国"],
    "宁波": ["宁波", "浙江", "长三角", "华东", "全国"],
    "温州": ["温州", "浙江", "华东", "全国"],
    "厦门": ["厦门", "福建", "海峡西岸", "华东", "全国"],
    "泉州": ["泉州", "福建", "海峡西岸", "华东", "全国"],
    "青岛": ["青岛", "山东", "华东", "全国"],
    "烟台": ["烟台", "山东", "华东", "全国"],
    "大连": ["大连", "辽宁", "东北", "全国"],
    "唐山": ["唐山", "河北", "京津冀", "华北", "全国"],
    "保定": ["保定", "河北", "京津冀", "华北", "全国"],
    "廊坊": ["廊坊", "河北", "京津冀", "华北", "全国"],
}

PROVINCE_REGION_EXPANSIONS = {
    "北京": ["北京", "京津冀", "华北", "全国"],
    "天津": ["天津", "京津冀", "华北", "全国"],
    "上海": ["上海", "长三角", "华东", "全国"],
    "重庆": ["重庆", "成渝", "西南", "全国"],
    "河北": ["河北", "京津冀", "华北", "全国"],
    "山西": ["山西", "华北", "全国"],
    "内蒙古": ["内蒙古", "华北", "全国"],
    "辽宁": ["辽宁", "东北", "全国"],
    "吉林": ["吉林", "东北", "全国"],
    "黑龙江": ["黑龙江", "东北", "全国"],
    "江苏": ["江苏", "长三角", "华东", "全国"],
    "浙江": ["浙江", "长三角", "华东", "全国"],
    "安徽": ["安徽", "长三角", "华东", "全国"],
    "福建": ["福建", "海峡西岸", "华东", "全国"],
    "江西": ["江西", "华东", "全国"],
    "山东": ["山东", "华东", "全国"],
    "河南": ["河南", "中原", "华中", "全国"],
    "湖北": ["湖北", "长江中游", "华中", "全国"],
    "湖南": ["湖南", "长江中游", "华中", "全国"],
    "广东": ["广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
    "广西": ["广西", "华南", "全国"],
    "海南": ["海南", "华南", "全国"],
    "四川": ["四川", "西南", "全国"],
    "贵州": ["贵州", "西南", "全国"],
    "云南": ["云南", "西南", "全国"],
    "西藏": ["西藏", "西南", "全国"],
    "陕西": ["陕西", "关中平原", "西北", "全国"],
    "甘肃": ["甘肃", "西北", "全国"],
    "青海": ["青海", "西北", "全国"],
    "宁夏": ["宁夏", "西北", "全国"],
    "新疆": ["新疆", "西北", "全国"],
    "台湾": ["台湾", "华东", "全国"],
    "香港": ["香港", "粤港澳大湾区", "华南", "全国"],
    "澳门": ["澳门", "粤港澳大湾区", "华南", "全国"],
}

KNOWN_REGIONS = sorted(
    {
        "国内",
        "全国",
        "华东",
        "华南",
        "华中",
        "华北",
        "东北",
        "西南",
        "西北",
        "长三角",
        "珠三角",
        "粤港澳大湾区",
        "京津冀",
        "成渝",
        "长江中游",
        "中原",
        "关中平原",
        "海峡西岸",
        "一线城市",
        *CITY_REGION_EXPANSIONS.keys(),
        *PROVINCE_REGION_EXPANSIONS.keys(),
    },
    key=len,
    reverse=True,
)


class GeoEvaluationPromptService:
    """GEO 测评问题集管理（公司级别）"""

    def __init__(self, db: Session):
        self.db = db

    # ==================== 查询方法 ====================

    def get_active_prompt_set(self, client_id: int) -> Optional[GeoPromptSet]:
        """获取公司当前活跃/冻结的问题集"""
        return (
            self.db.query(GeoPromptSet)
            .filter(
                GeoPromptSet.client_id == client_id,
                GeoPromptSet.status.in_(["active", "frozen"]),
            )
            .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
            .first()
        )

    def get_prompt_set(self, prompt_set_id: int) -> Optional[GeoPromptSet]:
        """根据 ID 获取问题集"""
        return self.db.query(GeoPromptSet).filter(GeoPromptSet.id == prompt_set_id).first()

    def get_prompts(
        self,
        prompt_set_id: int,
        question_type: Optional[str] = None,
    ) -> List[GeoPrompt]:
        """获取问题集中的问题列表"""
        q = self.db.query(GeoPrompt).filter(
            GeoPrompt.prompt_set_id == prompt_set_id,
            GeoPrompt.status == "active",
        )
        if question_type:
            q = q.filter(GeoPrompt.question_type == question_type)
        return q.order_by(GeoPrompt.question_type, GeoPrompt.sort_order).all()

    def sync_smart_article_questions(
        self,
        client_id: int,
        created_by: Optional[int] = None,
    ) -> Optional[GeoPromptSet]:
        """Expose every active smart-article question in the client's monitor.

        Synchronizing only prepares the question pool. It never creates an
        evaluation run or asks an AI platform. Existing linked prompts are kept
        immutable so historical baseline/current records continue to reference
        the exact text that was asked.
        """
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return None

        questions = (
            self.db.query(SmartArticleQuestion, Project)
            .join(Project, Project.id == SmartArticleQuestion.project_id)
            .filter(
                Project.client_id == client_id,
                Project.status == 1,
                SmartArticleQuestion.is_deleted.is_(False),
            )
            .order_by(SmartArticleQuestion.created_at.asc(), SmartArticleQuestion.id.asc())
            .all()
        )
        existing = self.get_active_prompt_set(client_id)
        if not questions:
            return existing

        source_name = "smart_article_question_pool"
        if existing and existing.generation_model != source_name:
            existing.status = "archived"
            self.db.flush()
            existing = None

        if not existing:
            latest_version = (
                self.db.query(GeoPromptSet.version)
                .filter(GeoPromptSet.client_id == client_id)
                .order_by(GeoPromptSet.version.desc(), GeoPromptSet.id.desc())
                .first()
            )
            now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
            existing = GeoPromptSet(
                client_id=client_id,
                name=f"{client.company_name or client.name} 智能文章问题测评集",
                question_count=0,
                question_distribution={},
                generation_model=source_name,
                generation_prompt=json.dumps(
                    {"source": source_name, "auto_run": False},
                    ensure_ascii=False,
                ),
                status="active",
                version=(latest_version[0] + 1) if latest_version else 1,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            self.db.add(existing)
            self.db.flush()

        linked_ids = {
            row[0]
            for row in self.db.query(GeoPrompt.smart_article_question_id)
            .filter(
                GeoPrompt.prompt_set_id == existing.id,
                GeoPrompt.smart_article_question_id.is_not(None),
            )
            .all()
        }
        next_order = (
            self.db.query(GeoPrompt)
            .filter(GeoPrompt.prompt_set_id == existing.id)
            .count()
        )
        added = 0
        for question, project in questions:
            if question.id in linked_ids:
                continue
            self.db.add(
                GeoPrompt(
                    prompt_set_id=existing.id,
                    client_id=client_id,
                    project_id=question.project_id,
                    smart_article_question_id=question.id,
                    related_project_name=project.name,
                    question=question.question,
                    question_type=self._smart_question_type(question.intent_type),
                    intent_tags=[question.intent_type] if question.intent_type else [],
                    sort_order=next_order + added,
                    status="active",
                )
            )
            added += 1

        self.db.flush()
        active_prompts = self.get_prompts(existing.id)
        distribution: Dict[str, int] = {}
        for prompt in active_prompts:
            distribution[prompt.question_type] = distribution.get(prompt.question_type, 0) + 1
        existing.question_count = len(active_prompts)
        existing.question_distribution = distribution
        existing.updated_at = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
        self.db.commit()
        if added:
            logger.info("[PromptService] 公司 {} 同步新增智能文章问题 {} 条", client_id, added)
        return existing

    def get_platform_question_statuses(self, prompt_set_id: int) -> Dict[int, Dict[str, Dict[str, bool]]]:
        """Return attempted/success flags per prompt and platform."""
        rows = (
            self.db.query(GeoEvaluationRecord)
            .filter(
                GeoEvaluationRecord.prompt_set_id == prompt_set_id,
                GeoEvaluationRecord.prompt_id.is_not(None),
            )
            .all()
        )
        statuses: Dict[int, Dict[str, Dict[str, bool]]] = {}
        for record in rows:
            prompt_status = statuses.setdefault(record.prompt_id, {})
            platform_status = prompt_status.setdefault(
                record.platform,
                {"baseline_attempted": False, "baseline_success": False, "ongoing_success": False},
            )
            if record.phase == "baseline":
                platform_status["baseline_attempted"] = True
                if record.success and record.answer:
                    platform_status["baseline_success"] = True
            elif record.phase == "ongoing" and record.success and record.answer:
                platform_status["ongoing_success"] = True
        return statuses

    @staticmethod
    def _smart_question_type(intent_type: Optional[str]) -> str:
        return {
            "provider": "recommendation",
            "selection": "comparison",
            "comparison": "comparison",
            "scenario": "scenario",
            "solution": "business_understanding",
            "implementation": "business_understanding",
            "risk": "business_understanding",
        }.get(str(intent_type or "").lower(), "recommendation")

    # ==================== 生成方法 ====================

    def generate_prompt_set(
        self,
        client_id: int,
        created_by: Optional[int] = None,
        project_id: Optional[int] = None,
        question_count: int = 100,
        distribution: Optional[Dict[str, int]] = None,
        competitors: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """生成测评问题集（公司级别）

        Args:
            client_id: 公司ID
            created_by: 创建者用户ID
            project_id: 可选，关联项目ID（用于生成业务维度问题）
            question_count: 问题总数（默认 100）
            distribution: 问题类型分布，默认为 60/15/15/0/5/5
            competitors: 竞品名称列表
            overwrite: 是否覆盖已有 frozen 问题集

        Returns:
            {success, prompt_set_id, prompts_count, message}
        """
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return {"success": False, "message": "公司不存在"}

        # 业务术语池：项目行业、领域关键词、项目名、已蒸馏关键词都可作为“项目名称/业务名”进入测评问题。
        project_terms = self._collect_project_terms(client_id=client_id, project_id=project_id)

        company_name = client.company_name or client.name
        industry = self._resolve_industry_label(client.industry, project_terms)
        if not industry and not project_terms:
            return {
                "success": False,
                "message": (
                    "公司缺少可用于生成测评问题的业务画像，请先补充公司行业、项目领域关键词或蒸馏关键词后再生成"
                ),
            }
        input_errors = self._evaluation_input_errors(client=client, project_id=project_id)
        if input_errors:
            return {
                "success": False,
                "message": "测评问题生成前资料不完整：" + "；".join(input_errors),
            }

        # 检查是否已有 frozen 问题集
        existing = self.get_active_prompt_set(client_id)
        if existing and existing.status == "frozen" and not overwrite:
            return {
                "success": False,
                "message": "公司已有冻结的问题集，如需重新生成请使用 overwrite=true",
            }

        # 归档旧问题集
        if overwrite:
            (
                self.db.query(GeoPromptSet)
                .filter(
                    GeoPromptSet.client_id == client_id,
                    GeoPromptSet.status.in_(["active", "frozen"]),
                )
                .update({"status": "archived"}, synchronize_session=False)
            )

        # 使用默认分布或自定义分布
        dist = distribution or DEFAULT_DISTRIBUTION
        # 确保总和为 question_count
        total_dist = sum(dist.values())
        if total_dist != question_count:
            # 按比例调整
            scale = question_count / total_dist
            dist = {k: round(v * scale) for k, v in dist.items()}
            # 确保总和正确
            diff = question_count - sum(dist.values())
            dist["recommendation"] += diff  # 调整供应商推荐类补足差额

        # 获取公司信息
        region_profile = self._build_region_profile(client.location)

        # 获取竞品
        competitor_list = competitors or []

        # 生成问题。模板结果始终作为兜底；LLM 增强成功时才替换最终问题集。
        template_prompts_data = self._generate_questions(
            company_name=company_name,
            industry=industry,
            distribution=dist,
            competitors=competitor_list,
            project_terms=project_terms,
            region_profile=region_profile,
        )
        prompts_data = template_prompts_data
        generation_model = "template"
        generation_mode = "template"

        candidate_distribution = self._candidate_distribution(dist)
        candidate_prompts_data = self._generate_questions(
            company_name=company_name,
            industry=industry,
            distribution=candidate_distribution,
            competitors=competitor_list,
            project_terms=project_terms,
            region_profile=region_profile,
        )
        llm_generator = GeoEvaluationLLMPromptGenerator()
        llm_prompts_data = llm_generator.generate(
            company_name=company_name,
            industry=industry,
            distribution=dist,
            competitors=competitor_list,
            project_terms=project_terms,
            candidates=candidate_prompts_data,
            allowed_regions=region_profile["allowed_regions"],
            blocked_regions=region_profile["blocked_regions"],
        )
        if llm_prompts_data:
            prompts_data = llm_prompts_data
            generation_model = llm_generator.model
            generation_mode = "llm_enhanced"
        elif llm_generator.is_configured():
            generation_model = f"{llm_generator.model}:template_fallback"
            generation_mode = "template_fallback"

        # 创建问题集
        beijing_now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
        prompt_set = GeoPromptSet(
            client_id=client_id,
            project_id=project_id,
            name=f"{company_name} GEO 测评问题集",
            question_count=len(prompts_data),
            question_distribution=dist,
            generation_model=generation_model,
            generation_prompt=json.dumps(
                {
                    "generation_mode": generation_mode,
                    "llm_model": llm_generator.model if llm_generator.is_configured() else None,
                    "candidate_count": len(candidate_prompts_data),
                    "industry": industry,
                    "project_terms": project_terms[:30],
                    "region_profile": region_profile,
                },
                ensure_ascii=False,
            ),
            status="active",
            version=(existing.version + 1) if existing else 1,
            created_by=created_by,
            created_at=beijing_now,
            updated_at=beijing_now,
        )
        self.db.add(prompt_set)
        self.db.flush()

        # 写入问题
        for i, pd in enumerate(prompts_data):
            prompt = GeoPrompt(
                prompt_set_id=prompt_set.id,
                client_id=client_id,
                project_id=project_id,
                related_project_name=pd.get("related_project_name"),
                question=pd["question"],
                question_type=pd["question_type"],
                intent_tags=pd.get("intent_tags"),
                competitor_names=pd.get("competitor_names"),
                sort_order=i,
                status="active",
            )
            self.db.add(prompt)

        self.db.commit()

        logger.info(f"[PromptService] 公司 {client_id} 生成问题集 id={prompt_set.id}，共 {len(prompts_data)} 条")
        return {
            "success": True,
            "prompt_set_id": prompt_set.id,
            "prompts_count": len(prompts_data),
            "distribution": dist,
            "generation_model": generation_model,
            "generation_mode": generation_mode,
            "message": f"测评问题集已生成，共 {len(prompts_data)} 个问题",
        }

    def freeze_prompt_set(self, prompt_set_id: int) -> Dict[str, Any]:
        """冻结问题集（建立 baseline 前必须调用）"""
        prompt_set = self.db.query(GeoPromptSet).filter(GeoPromptSet.id == prompt_set_id).first()
        if not prompt_set:
            return {"success": False, "message": "问题集不存在"}

        beijing_now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
        prompt_set.status = "frozen"
        prompt_set.frozen_at = beijing_now
        self.db.commit()

        logger.info(f"[PromptService] 问题集 id={prompt_set_id} 已冻结")
        return {"success": True, "message": "问题集已冻结"}

    # ==================== 问题生成（模板方式） ====================

    def _collect_project_terms(self, client_id: int, project_id: Optional[int] = None) -> List[str]:
        """Collect project/business terms used by most neutral GEO prompts.

        Sources are ordered from concrete to broad: project names, domain keywords,
        and persisted distilled keywords.
        """
        query = self.db.query(Project).filter(Project.status == 1)
        if project_id:
            query = query.filter(Project.id == project_id, Project.client_id == client_id)
        else:
            query = query.filter(Project.client_id == client_id)

        projects = query.order_by(Project.updated_at.desc().nullslast(), Project.id.desc()).limit(30).all()
        terms: List[str] = []
        project_ids: List[int] = []

        for project in projects:
            project_ids.append(project.id)
            for value in (project.industry, project.domain_keyword, project.name):
                cleaned = self._clean_term(value)
                if cleaned:
                    terms.append(cleaned)

        if project_ids:
            keywords = (
                self.db.query(Keyword.keyword)
                .filter(
                    Keyword.project_id.in_(project_ids),
                    Keyword.status == "active",
                    Keyword.keyword_type.in_(["keyword", "question"]),
                )
                .order_by(Keyword.created_at.desc())
                .limit(50)
                .all()
            )
            terms.extend(self._clean_term(row[0]) for row in keywords)

        return self._dedupe_terms(terms)[:30]

    def _evaluation_input_errors(self, client: Client, project_id: Optional[int] = None) -> List[str]:
        errors: List[str] = []

        if not self._clean_term(client.company_name or client.name):
            errors.append("请填写公司名称")
        if not self._clean_term(client.location):
            errors.append("请填写公司所在地")
        if not self._resolve_industry_label(client.industry, []):
            errors.append("请填写所属行业")

        project_query = self.db.query(Project).filter(Project.status == 1)
        if project_id:
            project_query = project_query.filter(Project.id == project_id, Project.client_id == client.id)
        else:
            project_query = project_query.filter(Project.client_id == client.id)
        projects = project_query.all()

        if project_id and not projects:
            errors.append("指定项目不存在或未关联当前公司")
            return errors
        if not projects:
            errors.append("请先创建项目")
            return errors

        complete_project_ids = [
            project.id
            for project in projects
            if self._clean_term(project.name)
            and self._clean_term(project.company_name)
            and self._clean_term(project.domain_keyword)
        ]
        if not complete_project_ids:
            errors.append("请补充项目名称、项目公司名称和领域关键词")
            return errors

        keyword_count = (
            self.db.query(Keyword)
            .filter(
                Keyword.project_id.in_(complete_project_ids),
                Keyword.status == "active",
                Keyword.keyword_type.in_(["keyword", "question"]),
            )
            .count()
        )
        if keyword_count <= 0:
            errors.append("请先完成关键词蒸馏，确保项目下已有有效关键词")

        return errors

    def _clean_term(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip().strip("，。！？?；;、,. ")
        if len(text) > 40:
            return None
        return text or None

    def _resolve_industry_label(self, industry: Optional[str], project_terms: Optional[List[str]] = None) -> str:
        """Resolve the safest domain label for generic templates.

        We intentionally avoid fake fallbacks such as "本地生活服务": if the client
        industry is missing, prefer concrete project/keyword terms; if neither is
        available, callers can block generation or use a neutral placeholder.
        """
        cleaned_industry = self._clean_term(industry)
        if cleaned_industry and cleaned_industry not in {"行业", "服务", "本地生活服务"}:
            return cleaned_industry

        question_markers = ("哪家", "推荐", "怎么样", "如何", "？", "?")
        for term in project_terms or []:
            cleaned = self._clean_term(term)
            if cleaned and not any(marker in cleaned for marker in question_markers):
                return cleaned
        return ""

    def _dedupe_terms(self, terms: List[Optional[str]]) -> List[str]:
        seen = set()
        result = []
        for term in terms:
            if not term:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(term)
        return result

    def _build_region_profile(self, location: Optional[str]) -> Dict[str, Any]:
        """Build the controlled region pool used by GEO prompt generation."""
        cleaned = self._clean_term(location)
        if not cleaned:
            allowed = ["全国", "国内"]
        else:
            normalized = cleaned.replace("市", "").replace("省", "").strip()
            matched_city = next((city for city in CITY_REGION_EXPANSIONS if city in cleaned or city == normalized), None)
            matched_province = next(
                (province for province in PROVINCE_REGION_EXPANSIONS if province in cleaned or province == normalized),
                None,
            )
            allowed = (
                CITY_REGION_EXPANSIONS.get(matched_city or "")
                or PROVINCE_REGION_EXPANSIONS.get(matched_province or "")
            )
            if not allowed:
                allowed = [normalized, "全国"]

        allowed = self._dedupe_terms(allowed)
        blocked = [region for region in KNOWN_REGIONS if region not in allowed and region not in {"国内", "全国"}]

        weighted_regions: List[str] = []
        for index, region in enumerate(allowed):
            weight = max(1, 4 - index)
            weighted_regions.extend([region] * weight)

        return {
            "location": cleaned,
            "allowed_regions": allowed,
            "blocked_regions": blocked,
            "weighted_regions": weighted_regions or allowed,
        }

    def _should_use_region(self, question_type: str, index: int, count: int) -> bool:
        regional_count = round(count * REGIONAL_QUESTION_RATIOS.get(question_type, 0))
        return index < regional_count

    def _pick_region(self, region_profile: Dict[str, Any]) -> str:
        regions = region_profile.get("weighted_regions") or region_profile.get("allowed_regions") or ["全国"]
        return random.choice(regions)

    def _pick_template(self, templates: List[str], *, use_region: bool) -> str:
        matching = [template for template in templates if ("{region}" in template) == use_region]
        if matching:
            return random.choice(matching)
        return random.choice(templates)

    def _filter_region_questions(self, questions: List[Dict[str, Any]], region_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        blocked = set(region_profile.get("blocked_regions") or [])
        if not blocked:
            return questions
        return [
            item
            for item in questions
            if item.get("question_type") in {"brand_awareness", "reputation"}
            or not any(region and region in item.get("question", "") for region in blocked)
        ]

    def _project_term_budget(self, total_questions: int, available_terms: int) -> int:
        if available_terms <= 0:
            return 0
        if total_questions >= 100:
            return DEFAULT_PROJECT_TERM_QUESTION_COUNT
        return max(1, round(total_questions * DEFAULT_PROJECT_TERM_QUESTION_COUNT / 100))

    def _split_project_term_budget(self, distribution: Dict[str, int], total_budget: int) -> Dict[str, int]:
        if total_budget <= 0:
            return {"recommendation": 0, "scenario": 0, "comparison": 0, "business_understanding": 0}

        weights = {"recommendation": 9, "scenario": 4, "comparison": 3, "business_understanding": 2}
        budgets = {
            key: min(distribution.get(key, 0), round(total_budget * weight / sum(weights.values())))
            for key, weight in weights.items()
        }

        diff = total_budget - sum(budgets.values())
        order = ["recommendation", "scenario", "comparison", "business_understanding"]
        index = 0
        while diff > 0 and any(budgets[key] < distribution.get(key, 0) for key in order):
            key = order[index % len(order)]
            if budgets[key] < distribution.get(key, 0):
                budgets[key] += 1
                diff -= 1
            index += 1
        while diff < 0:
            key = max(budgets, key=budgets.get)
            budgets[key] -= 1
            diff += 1

        return budgets

    def _candidate_distribution(self, distribution: Dict[str, int]) -> Dict[str, int]:
        """Build an oversized local candidate pool for LLM rewrite/fallback."""
        return {
            question_type: max(count + 5, count * 2)
            for question_type, count in distribution.items()
            if count > 0
        }

    def _generate_questions(
        self,
        company_name: str,
        industry: str,
        distribution: Dict[str, int],
        competitors: List[str],
        project_terms: List[str],
        region_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """生成测评问题（模板方式）

        Args:
            company_name: 公司名称
            industry: 行业
            distribution: 问题类型分布
            competitors: 竞品名称列表
            project_terms: 项目/业务术语列表（项目名、领域关键词、蒸馏关键词）

        Returns:
            问题列表
        """
        questions = []
        region_profile = region_profile or self._build_region_profile(None)
        project_budget = self._project_term_budget(sum(distribution.values()), len(project_terms))
        project_budgets = self._split_project_term_budget(distribution, project_budget)

        # —— 供应商推荐类（60%） ——
        questions.extend(self._generate_recommendation_questions(
            company_name=company_name,
            industry=industry,
            count=distribution.get("recommendation", 0),
            project_terms=project_terms,
            project_count=project_budgets["recommendation"],
            region_profile=region_profile,
        ))

        # —— 场景找供应商类（15%） ——
        questions.extend(self._generate_scenario_questions(
            industry=industry,
            count=distribution.get("scenario", 0),
            project_terms=project_terms,
            project_count=project_budgets["scenario"],
            region_profile=region_profile,
        ))

        # —— 采购选型类（15%） ——
        questions.extend(self._generate_comparison_questions(
            industry=industry,
            count=distribution.get("comparison", 0),
            competitors=competitors,
            project_terms=project_terms,
            project_count=project_budgets["comparison"],
            region_profile=region_profile,
        ))

        # —— 业务理解类（10%） ——
        questions.extend(self._generate_business_understanding_questions(
            industry=industry,
            count=distribution.get("business_understanding", 0),
            project_terms=project_terms,
            project_count=project_budgets["business_understanding"],
        ))

        # —— 品牌认知型（5%） ——
        questions.extend(self._generate_brand_awareness_questions(
            company_name=company_name,
            count=distribution.get("brand_awareness", 0),
        ))

        # —— 口碑评价类（5%） ——
        questions.extend(self._generate_reputation_questions(
            company_name=company_name,
            industry=industry,
            count=distribution.get("reputation", 0),
        ))

        return self._filter_region_questions(questions, region_profile)

    def _generate_recommendation_questions(
        self,
        company_name: str,
        industry: str,
        count: int,
        project_terms: List[str],
        project_count: int = 0,
        region_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """生成推荐型问题。

        问题必须具备“找服务商/推荐公司”的意图，避免生成只会得到知识解释的泛问题。
        """
        questions = []

        # 纯行业模板（不涉及具体项目）
        generic_templates = [
            "{region}有哪些值得推荐的{industry}服务商？",
            "{region}{industry}领域的头部公司有哪些？",
            "做{industry}的公司中，哪家性价比高？",
            "推荐几家{region}专业的{industry}公司？",
            "如果想做{industry}，找哪家服务商比较好？",
            "{industry}服务市场有哪些知名品牌？",
            "如何选择一家靠谱的{industry}公司？",
            "{region}做{industry}做得好的企业有哪些？",
            "{industry}行业有哪些值得信赖的服务商？",
            "国内{industry}领域有哪些优秀的企业？",
        ]

        # 涉及项目/业务的模板
        project_templates = [
            "{region}做{project}的服务商有哪些推荐？",
            "做{project}这个业务的公司哪家比较专业？",
            "{project}服务在{region}找哪家公司比较好？",
            "找{region}做{project}的供应商，有推荐吗？",
            "采购{project}时，有哪些靠谱供应商或公司可以考虑？",
            "{project}长期合作供应商哪类公司更值得优先了解？",
        ]

        industry_name = self._resolve_industry_label(industry, project_terms) or "该公司主营业务"
        region_profile = region_profile or self._build_region_profile(None)

        for i in range(count):
            use_project = project_terms and i < project_count
            use_region = self._should_use_region("recommendation", i, count)

            if use_project:
                project_name = project_terms[i % len(project_terms)]
                template = self._pick_template(project_templates, use_region=use_region)
                region = self._pick_region(region_profile)
                q = template.format(
                    project=project_name,
                    region=region,
                    industry=industry_name,
                )
                questions.append({
                    "question": q,
                    "question_type": "recommendation",
                    "related_project_name": project_name,
                    "intent_tags": ["推荐", "服务商", "业务咨询"],
                })
            else:
                template = self._pick_template(generic_templates, use_region=use_region)
                region = self._pick_region(region_profile)
                q = template.format(region=region, industry=industry_name)
                questions.append({
                    "question": q,
                    "question_type": "recommendation",
                    "related_project_name": None,
                    "intent_tags": ["推荐", "服务商"],
                })

        return questions

    def _generate_comparison_questions(
        self,
        industry: str,
        count: int,
        competitors: List[str],
        project_terms: List[str],
        project_count: int = 0,
        region_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """生成选型对比型问题"""
        questions = []

        templates = [
            "{industry}服务商应该从哪些维度对比？有哪些靠谱公司可以参考？",
            "{region}{industry}公司怎么判断哪家更靠谱？推荐几家可对比的服务商",
            "选择{industry}服务商时，技术能力、案例和价格哪个更重要？有哪些公司值得看？",
            "{industry}解决方案供应商有哪些常见差异？哪些服务商综合表现比较好？",
            "国内头部{industry}公司各有什么优势？如何对比选择？",
            "{industry}行业主要玩家有哪些？它们之间有什么区别？",
            "在{region}做{industry}的公司里，哪家的案例更丰富？",
            "如何评估一家{industry}公司的专业程度？看哪些指标？",
            "{industry}服务商的报价差异大吗？怎么选性价比高的？",
            "对比{industry}服务商时，服务质量和价格如何平衡？",
        ]

        # 涉及项目的模板
        project_templates = [
            "{project}服务各家公司报价差异大吗？哪些供应商值得对比？",
            "{project}这个业务在{region}有哪些公司在做？哪家口碑好？",
            "做{project}的公司，技术实力和服务质量应该怎么对比？",
            "采购{project}时，哪些服务商更适合长期合作？",
        ]

        industry_name = self._resolve_industry_label(industry, project_terms) or "该公司主营业务"
        competitor_str = "、".join(competitors[:3]) if competitors else None
        region_profile = region_profile or self._build_region_profile(None)

        for i in range(count):
            use_project = project_terms and i < project_count
            use_region = self._should_use_region("comparison", i, count)

            if use_project:
                project_name = project_terms[i % len(project_terms)]
                template = self._pick_template(project_templates, use_region=use_region)
                region = self._pick_region(region_profile)
                q = template.format(project=project_name, region=region, industry=industry_name)
                questions.append({
                    "question": q,
                    "question_type": "comparison",
                    "related_project_name": project_name,
                    "intent_tags": ["对比", "选型", "业务咨询"],
                    "competitor_names": competitors[:3] if competitors else [],
                })
            else:
                template = self._pick_template(templates, use_region=use_region)
                region = self._pick_region(region_profile)
                q = template.format(region=region, industry=industry_name)
                if competitor_str:
                    q = q.replace("靠谱公司", f"靠谱公司（比如{competitor_str}）")
                questions.append({
                    "question": q,
                    "question_type": "comparison",
                    "related_project_name": None,
                    "intent_tags": ["对比", "选型"],
                    "competitor_names": competitors[:3] if competitors else [],
                })

        return questions

    def _generate_scenario_questions(
        self,
        industry: str,
        count: int,
        project_terms: List[str],
        project_count: int = 0,
        region_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """生成场景型问题"""
        questions = []

        templates = [
            "企业想做{industry}项目，应该找哪类服务商比较稳妥？",
            "预算有限时，{industry}服务商有哪些靠谱选择？",
            "中型企业选择{industry}服务，哪些公司更适合长期合作？",
            "{industry}项目从规划到落地，找什么样的公司更靠谱？",
            "企业在{region}做{industry}，有哪些服务商案例可以参考？",
            "{industry}服务落地难度高，应该优先了解哪些供应商？",
            "采购{industry}服务时，哪些公司能提供完整解决方案？",
            "{region}{industry}项目需要稳定交付，有哪些公司值得了解？",
        ]

        # 涉及项目的模板
        project_templates = [
            "企业想采购{project}，有哪些服务商或供应商值得了解？",
            "{project}这类业务在{region}有哪些主要公司在做？",
            "企业想做{project}项目，应该找哪类公司合作？",
            "{project}项目需要稳定交付，哪些供应商更靠谱？",
            "在{industry}行业里，{project}这类业务有哪些代表性服务商？",
        ]

        industry_name = self._resolve_industry_label(industry, project_terms) or "该公司主营业务"
        region_profile = region_profile or self._build_region_profile(None)

        for i in range(count):
            use_project = project_terms and i < project_count
            use_region = self._should_use_region("scenario", i, count)

            if use_project:
                project_name = project_terms[i % len(project_terms)]
                template = self._pick_template(project_templates, use_region=use_region)
                region = self._pick_region(region_profile)
                q = template.format(project=project_name, region=region, industry=industry_name)
                questions.append({
                    "question": q,
                    "question_type": "scenario",
                    "related_project_name": project_name,
                    "intent_tags": ["场景", "解决方案", "业务咨询"],
                })
            else:
                template = self._pick_template(templates, use_region=use_region)
                q = template.format(industry=industry_name, region=self._pick_region(region_profile))
                questions.append({
                    "question": q,
                    "question_type": "scenario",
                    "related_project_name": None,
                    "intent_tags": ["场景", "解决方案"],
                })

        return questions

    def _generate_reputation_questions(
        self,
        company_name: str,
        industry: str,
        count: int,
    ) -> List[Dict[str, Any]]:
        """生成口碑型问题（直接问公司）"""
        questions = []

        templates = [
            "{company}做{industry}怎么样？",
            "{company}靠谱吗？",
            "{company}服务口碑如何？",
            "{company}在{industry}行业排名怎么样？",
            "{company}的专业能力和服务态度好吗？",
            "有人了解{company}吗？合作过的人来说说怎么样？",
            "{company}的{industry}业务做得好不好？",
            "和{company}合作做{industry}项目，靠谱吗？",
            "{company}在行业内的评价如何？",
            "选择{company}做{industry}服务，有风险吗？",
        ]

        industry_name = self._resolve_industry_label(industry, []) or "该公司主营业务"

        for i in range(count):
            template = random.choice(templates)
            q = template.format(company=company_name, industry=industry_name)
            questions.append({
                "question": q,
                "question_type": "reputation",
                "related_project_name": None,
                "intent_tags": ["口碑", "评价"],
            })

        return questions

    def _generate_business_understanding_questions(
        self,
        industry: str,
        count: int,
        project_terms: List[str],
        project_count: int = 0,
    ) -> List[Dict[str, Any]]:
        """生成业务理解类问题。

        仅在用户自定义分布启用时生成，且保持采购/供应商评估意图。
        """
        questions = []

        templates = [
            "采购{industry}服务时，应该重点对比哪些供应商能力？",
            "选择{industry}公司时，哪些资质和案例最能说明实力？",
            "{industry}服务商的交付能力和售后保障怎么评估？",
            "长期合作{industry}供应商，应该优先看哪些公司能力？",
            "企业采购{industry}时，怎样筛选靠谱服务商？",
        ]

        project_templates = [
            "采购{project}时，哪些供应商能力最值得重点评估？",
            "判断{project}供应商是否专业，应该重点看哪些公司案例？",
            "{project}的稳定供货和品质控制，哪些服务商更值得了解？",
            "客户采购{project}时，怎样筛选靠谱供应商？",
            "长期合作{project}供应商，需要重点关注哪些公司能力？",
        ]

        industry_name = self._resolve_industry_label(industry, project_terms) or "该公司主营业务"

        for i in range(count):
            use_project = project_terms and i < project_count
            if use_project:
                project_name = project_terms[i % len(project_terms)]
                template = random.choice(project_templates)
                q = template.format(project=project_name, industry=industry_name)
                questions.append({
                    "question": q,
                    "question_type": "business_understanding",
                    "related_project_name": project_name,
                    "intent_tags": ["业务理解", "知识问答", "采购认知"],
                })
            else:
                template = random.choice(templates)
                q = template.format(industry=industry_name)
                questions.append({
                    "question": q,
                    "question_type": "business_understanding",
                    "related_project_name": None,
                    "intent_tags": ["业务理解", "知识问答"],
                })

        return questions

    def _generate_brand_awareness_questions(
        self,
        company_name: str,
        count: int,
    ) -> List[Dict[str, Any]]:
        """生成品牌认知型问题（直接问公司是什么）"""
        questions = []

        templates = [
            "{company}是一家什么公司？",
            "{company}主要做什么？",
            "{company}的总部在哪里？",
            "{company}成立多久了？",
            "{company}有哪些核心业务？",
            "{company}规模大吗？有多少员工？",
            "{company}有没有官网？主营业务是什么？",
            "{company}属于什么类型的企业？",
            "{company}的客户群体是哪些人？",
            "{company}在行业里有什么特色？",
        ]

        for i in range(count):
            template = random.choice(templates)
            q = template.format(company=company_name)
            questions.append({
                "question": q,
                "question_type": "brand_awareness",
                "related_project_name": None,
                "intent_tags": ["品牌认知", "公司介绍"],
            })

        return questions
