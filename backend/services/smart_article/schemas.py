from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


INTENT_TYPES = {
    "provider",
    "selection",
    "solution",
    "comparison",
    "scenario",
    "implementation",
    "risk",
    "manual",
}
CONTEXT_TYPES = {"general", "industry", "region"}
QUERY_KINDS = {"project_identity", "user_need", "capability_match", "region_verification"}


@dataclass
class ProjectContext:
    project_id: int
    user_id: int
    company_name: str
    project_name: str
    domain_keyword: str
    industry: str = ""
    location: str = ""
    project_description: str = ""
    client_description: str = ""
    website: str = ""
    allowed_regions: list[str] = field(default_factory=list)
    blocked_regions: list[str] = field(default_factory=list)
    client: Any = None
    project: Any = None


@dataclass
class PlannedQuestion:
    question: str
    intent_type: str
    context_type: str
    brand_entry_reason: str = ""
    retrieval_terms: list[str] = field(default_factory=list)


@dataclass
class QuerySpec:
    text: str
    kind: str
    purpose: str

    def as_dict(self) -> dict[str, str]:
        return {"text": self.text, "kind": self.kind, "purpose": self.purpose}


@dataclass
class KnowledgeResult:
    status: str
    chunks: list[dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    initial_queries: list[QuerySpec] = field(default_factory=list)
    retrieval_queries: list[QuerySpec] = field(default_factory=list)
    retrieval_rounds: int = 0
    query_rewrite_used: bool = False
    raw_count: int = 0
    valid_count: int = 0
    dataset_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GeneratedArticle:
    title: str
    content: str
    references: list[dict[str, Any]] = field(default_factory=list)
