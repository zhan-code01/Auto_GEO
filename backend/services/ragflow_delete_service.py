# -*- coding: utf-8 -*-
"""Helpers for deleting RAGFlow datasets before clearing local cache rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from loguru import logger


@dataclass
class RagflowDeleteResult:
    dataset_id: str
    success: bool
    message: str = ""


class RagflowDatasetDeleteError(RuntimeError):
    def __init__(self, failures: list[RagflowDeleteResult]):
        self.failures = failures
        message = "; ".join(f"{item.dataset_id}: {item.message}" for item in failures)
        super().__init__(message or "RAGFlow dataset delete failed")


def _normalize_dataset_ids(dataset_ids: Iterable[str | None]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in dataset_ids:
        dataset_id = str(raw or "").strip()
        if not dataset_id or dataset_id in seen:
            continue
        normalized.append(dataset_id)
        seen.add(dataset_id)
    return normalized


def _is_successful_delete(result: dict) -> bool:
    code = result.get("code")
    if code is None or code == 0:
        return True

    # If RAGFlow says the dataset is already gone, local cache cleanup should
    # still be allowed; there is no remote data left to preserve.
    message = str(result.get("message") or "").lower()
    not_found_markers = ("404", "not found", "not exist", "does not exist", "不存在")
    return any(marker in message for marker in not_found_markers)


def delete_ragflow_datasets(dataset_ids: Iterable[str | None]) -> list[RagflowDeleteResult]:
    """Delete datasets from RAGFlow and raise if any remote deletion fails."""
    ids = _normalize_dataset_ids(dataset_ids)
    if not ids:
        return []

    from backend.services.ragflow_client import get_ragflow_client

    ragflow_client = get_ragflow_client()
    if not ragflow_client.is_configured():
        raise RagflowDatasetDeleteError(
            [
                RagflowDeleteResult(dataset_id=dataset_id, success=False, message="RAGFlow is not configured")
                for dataset_id in ids
            ]
        )

    results: list[RagflowDeleteResult] = []
    failures: list[RagflowDeleteResult] = []
    for dataset_id in ids:
        result = ragflow_client.delete_dataset(dataset_id)
        ok = _is_successful_delete(result)
        item = RagflowDeleteResult(
            dataset_id=dataset_id,
            success=ok,
            message=str(result.get("message") or result.get("data") or ""),
        )
        results.append(item)
        if ok:
            logger.info("RAGFlow dataset deleted before local cleanup: {}", dataset_id)
        else:
            failures.append(item)

    if failures:
        raise RagflowDatasetDeleteError(failures)
    return results
