# -*- coding: utf-8 -*-
"""Reports API integration tests against the running PostgreSQL-backed app."""

from typing import Any, Dict, Optional

import pytest
import requests


class TestReportsAPI:
    """Verify the current authenticated reports API contract."""

    @pytest.fixture(autouse=True)
    def _runtime(self, backend_server, api_auth_headers):
        self.base_url = f"{backend_server}/api/reports"
        self.headers = api_auth_headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        response = requests.request(
            method,
            f"{self.base_url}{endpoint}",
            params=params,
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def test_get_stats_success(self):
        response = self._make_request("GET", "/stats")

        required_fields = {
            "total_articles",
            "common_articles",
            "geo_articles",
            "publish_success_rate",
            "publish_success_count",
            "publish_total_count",
            "keyword_hit_rate",
            "keyword_hit_count",
            "keyword_check_count",
            "company_hit_rate",
            "company_hit_count",
            "company_check_count",
        }
        assert required_fields <= response.keys()
        assert isinstance(response["total_articles"], int)
        assert isinstance(response["publish_success_rate"], float)
        assert 0 <= response["publish_success_rate"] <= 100

    def test_get_stats_with_project_filter(self):
        response = self._make_request("GET", "/stats", {"project_id": 99999, "days": 7})
        assert response["total_articles"] == 0

    def test_get_stats_with_days_filter(self):
        response_7 = self._make_request("GET", "/stats", {"days": 7})
        response_30 = self._make_request("GET", "/stats", {"days": 30})
        assert response_30["total_articles"] >= response_7["total_articles"]

    def test_get_stats_empty_data(self):
        response = self._make_request("GET", "/stats", {"project_id": 0})
        assert response["total_articles"] == 0
        assert response["publish_success_rate"] == 0.0
        assert response["keyword_hit_rate"] == 0.0
        assert response["company_hit_rate"] == 0.0

    def test_get_article_stats_success(self):
        response = self._make_request("GET", "/article-stats")
        assert set(response) == {"total", "generating", "completed", "published", "failed", "ready_to_publish"}
        assert all(isinstance(value, int) for value in response.values())

    def test_get_article_stats_with_project_filter(self):
        response = self._make_request("GET", "/article-stats", {"project_id": 99999})
        assert response["total"] == 0

    def test_get_overview_success(self):
        response = self._make_request("GET", "/overview")
        assert set(response) == {"total_keywords", "keyword_found", "company_found", "overall_hit_rate"}
        assert isinstance(response["total_keywords"], int)
        assert 0 <= response["overall_hit_rate"] <= 100

    def test_reports_require_authentication(self):
        response = requests.get(f"{self.base_url}/stats", timeout=10)
        assert response.status_code == 401
