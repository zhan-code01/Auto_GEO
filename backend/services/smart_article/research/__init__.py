"""四个独立LLM研究角色（方案/指标/竞品/行业），共用现有模型，仅并行LLM网络调用。"""

from .coordinator import SmartArticleResearchCoordinator
from .industry_researcher import IndustryResearcher
from .schemas import (
    CompetitorResearchResult,
    IndustryResearchResult,
    MetricResearchResult,
    ResearchBundle,
    SolutionResearchResult,
)

__all__ = [
    "SmartArticleResearchCoordinator",
    "ResearchBundle",
    "SolutionResearchResult",
    "MetricResearchResult",
    "CompetitorResearchResult",
    "IndustryResearchResult",
    "IndustryResearcher",
]
