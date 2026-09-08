# -*- coding: utf-8 -*-
"""Projects API integration tests against the running PostgreSQL-backed app."""

from typing import Any, Dict, Optional

import pytest
import requests


class TestProjectsAPI:
    """Verify the current authenticated projects API contract."""

    @pytest.fixture(autouse=True)
    def _runtime(self, backend_server, api_auth_headers):
        self.base_url = f"{backend_server}/api/keywords"
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
        if response.status_code == 204:
            return None
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    def test_list_projects_success(self):
        body = self._make_request("GET", "/projects")
        assert isinstance(body, list)
        for item in body:
            assert {"id", "name", "company_name", "status"} <= set(item.keys())

    def test_list_projects_requires_authentication(self):
        response = requests.get(f"{self.base_url}/projects", timeout=10)
        assert response.status_code == 401

    def test_create_get_update_delete_project_flow(self):
        unique = "IntegrationProj"
        create_body = {
            "client_id": None,
            "name": unique,
            "company_name": "Integration Co.",
            "domain_keyword": "auto_geo",
            "description": "integration test",
            "industry": "test",
        }
        created = self._make_request("POST", "/projects", json_body=create_body, expect_status=201)
        project_id = created["id"]
        try:
            fetched = self._make_request("GET", f"/projects/{project_id}")
            assert fetched["id"] == project_id
            assert fetched["name"] == unique

            update_body = {**create_body, "description": "updated"}
            updated = self._make_request("PUT", f"/projects/{project_id}", json_body=update_body)
            assert updated["description"] == "updated"
        finally:
            self._make_request("DELETE", f"/projects/{project_id}")

    def test_get_unknown_project_returns_error(self):
        self._make_request("GET", "/projects/99999999", expect_status=404)