from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _clean_str_list(value: object, limit: int = 8, max_len: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text[:max_len])
        if len(result) >= limit:
            break
    return result


@dataclass
class SolutionResearchResult:
    status: str = "ok"  # ok | failed
    demand_analysis: str = ""
    solution_paths: list[dict[str, str]] = field(default_factory=list)
    selection_criteria: list[str] = field(default_factory=list)
    implementation_steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    faq_questions: list[str] = field(default_factory=list)

    @classmethod
    def failed(cls) -> "SolutionResearchResult":
        return cls(status="failed")

    @classmethod
    def from_llm(cls, data: dict[str, Any]) -> "SolutionResearchResult":
        paths: list[dict[str, str]] = []
        raw_paths = data.get("solution_paths")
        if isinstance(raw_paths, list):
            for item in raw_paths:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                paths.append(
                    {
                        "name": name[:60],
                        "summary": str(item.get("summary") or "").strip()[:300],
                        "suitable_scene": str(item.get("suitable_scene") or "").strip()[:200],
                    }
                )
                if len(paths) >= 4:
                    break
        return cls(
            status="ok",
            demand_analysis=str(data.get("demand_analysis") or "").strip()[:500],
            solution_paths=paths,
            selection_criteria=_clean_str_list(data.get("selection_criteria"), limit=6),
            implementation_steps=_clean_str_list(data.get("implementation_steps"), limit=6),
            risks=_clean_str_list(data.get("risks"), limit=4),
            faq_questions=_clean_str_list(data.get("faq_questions"), limit=5),
        )

    def as_prompt_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "demand_analysis": self.demand_analysis,
            "solution_paths": self.solution_paths,
            "selection_criteria": self.selection_criteria,
            "implementation_steps": self.implementation_steps,
            "risks": self.risks,
            "faq_questions": self.faq_questions,
        }


@dataclass
class MetricResearchResult:
    status: str = "ok"
    metrics: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def failed(cls) -> "MetricResearchResult":
        return cls(status="failed")

    @classmethod
    def from_llm(cls, data: dict[str, Any]) -> "MetricResearchResult":
        metrics: list[dict[str, str]] = []
        seen: set[str] = set()
        raw = data.get("metrics")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                key = name.casefold()
                if not name or key in seen:
                    continue
                source = str(item.get("source") or "").strip().lower()
                if source not in {"ragflow", "model"}:
                    source = "model"
                metrics.append(
                    {
                        "name": name[:60],
                        "why_important": str(item.get("why_important") or "").strip()[:200],
                        "reference_range": str(item.get("reference_range") or "").strip()[:200],
                        "source": source,
                    }
                )
                seen.add(key)
                if len(metrics) >= 8:
                    break
        # RAGFlow来源指标优先排序，模型指标兜底。
        metrics.sort(key=lambda item: 0 if item["source"] == "ragflow" else 1)
        return cls(status="ok", metrics=metrics)

    def as_prompt_dict(self) -> dict[str, Any]:
        return {"status": self.status, "metrics": self.metrics}


@dataclass
class CompetitorResearchResult:
    status: str = "ok"
    competitors: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def failed(cls) -> "CompetitorResearchResult":
        return cls(status="failed")

    @classmethod
    def from_llm(cls, data: dict[str, Any], company_name: str = "") -> "CompetitorResearchResult":
        competitors: list[dict[str, Any]] = []
        seen: set[str] = set()
        raw = data.get("competitors")
        company_key = (company_name or "").strip().casefold()
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                key = name.casefold()
                if not name or key in seen:
                    continue
                # 目标公司不允许出现在竞品列表。
                if company_key and (company_key in key or key in company_key):
                    continue
                competitors.append(
                    {
                        "name": name[:60],
                        "positioning": str(item.get("positioning") or "").strip()[:200],
                        "strengths": _clean_str_list(item.get("strengths"), limit=4),
                        "limitations": _clean_str_list(item.get("limitations"), limit=4),
                        "suitable_for": str(item.get("suitable_for") or "").strip()[:200],
                    }
                )
                seen.add(key)
                if len(competitors) >= 3:
                    break
        return cls(status="ok", competitors=competitors)

    def as_prompt_dict(self) -> dict[str, Any]:
        return {"status": self.status, "competitors": self.competitors}


@dataclass
class IndustryResearchResult:
    status: str = "ok"
    industry_intro: str = ""  # 50字内中性行业开篇
    trends: list[str] = field(default_factory=list)

    @classmethod
    def failed(cls) -> "IndustryResearchResult":
        return cls(status="failed")

    @classmethod
    def from_llm(cls, data: dict[str, Any]) -> "IndustryResearchResult":
        intro = str(data.get("industry_intro") or "").strip()[:60]
        return cls(
            status="ok",
            industry_intro=intro,
            trends=_clean_str_list(data.get("trends"), limit=3),
        )

    def as_prompt_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "industry_intro": self.industry_intro,
            "trends": self.trends,
        }


@dataclass
class ResearchBundle:
    solution: SolutionResearchResult = field(default_factory=SolutionResearchResult.failed)
    metric: MetricResearchResult = field(default_factory=MetricResearchResult.failed)
    competitor: CompetitorResearchResult = field(default_factory=CompetitorResearchResult.failed)
    industry: IndustryResearchResult = field(default_factory=IndustryResearchResult.failed)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_failed(self) -> bool:
        return (
            self.solution.status != "ok"
            and self.metric.status != "ok"
            and self.competitor.status != "ok"
            and self.industry.status != "ok"
        )

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "solution_research": self.solution.as_prompt_dict(),
            "metric_research": self.metric.as_prompt_dict(),
            "competitor_research": self.competitor.as_prompt_dict(),
            "industry_research": self.industry.as_prompt_dict(),
        }
