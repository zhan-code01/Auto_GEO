# -*- coding: utf-8 -*-
"""Scheduler API integration tests against the running PostgreSQL-backed app."""

from typing import Any, Dict, Optional

import pytest
import requests


class TestSchedulerAPI:
    """Verify the current authenticated scheduler API contract."""

    @pytest.fixture(autouse=True)
    def _runtime(self, backend_server, api_auth_headers):
        self.base_url = f"{backend_server}/api/scheduler"
        self.headers = api_auth_headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        expect_status: Optional[int] = None,
    ) -> Any:
        response = requests.request(
            method,
            f"{self.base_url}{endpoint}",
            params=params,
            json=json_body,
            headers=self.headers,
            timeout=10,
        )
        if expect_status is not None:
            assert response.status_code == expect_status, response.text
        else:
            response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    def test_list_jobs_success(self):
        body = self._make_request("GET", "/jobs")
        assert isinstance(body, list)
        for item in body:
            assert {"id", "name", "task_key", "cron_expression", "is_active"} <= set(item.keys())

    def test_list_jobs_requires_authentication(self):
        response = requests.get(f"{self.base_url}/jobs", timeout=10)
        assert response.status_code == 401

    def test_update_unknown_job_returns_not_found(self):
        body = {"cron_expression": "0 0 * * *", "is_active": True}
        self._make_request("PUT", "/jobs/99999999", json_body=body)