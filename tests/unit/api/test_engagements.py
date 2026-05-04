import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.auth import get_current_buyer_org_id
from app.core.database import get_db
from app.main import app

TEST_BUYER_ORG_ID = "org-unit-test-abc-123"


def _make_engagement(name: str = "Acme DD") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name=name,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        buyer_org_id=TEST_BUYER_ORG_ID,
    )


def _db_override():
    yield AsyncMock()


class TestListEngagementsUnit:
    def setup_method(self):
        app.dependency_overrides[get_current_buyer_org_id] = lambda: TEST_BUYER_ORG_ID
        app.dependency_overrides[get_db] = _db_override
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_filters_by_buyer_org_id(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([], 0)
        mock_repo_class.return_value = mock_repo

        self.client.get("/api/engagements")

        mock_repo.list_by_buyer_org.assert_called_once_with(
            TEST_BUYER_ORG_ID, limit=20, offset=0
        )

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_passes_pagination_params(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([], 0)
        mock_repo_class.return_value = mock_repo

        self.client.get("/api/engagements?limit=5&offset=10")

        mock_repo.list_by_buyer_org.assert_called_once_with(
            TEST_BUYER_ORG_ID, limit=5, offset=10
        )

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_returns_paginated_response(self, mock_repo_class):
        engagement = _make_engagement()
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([engagement], 1)
        mock_repo_class.return_value = mock_repo

        response = self.client.get("/api/engagements")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Acme DD"
        assert body["items"][0]["status"] == "active"

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_empty_list_when_no_engagements(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([], 0)
        mock_repo_class.return_value = mock_repo

        response = self.client.get("/api/engagements")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_default_pagination_values(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([], 0)
        mock_repo_class.return_value = mock_repo

        response = self.client.get("/api/engagements")

        body = response.json()
        assert body["limit"] == 20
        assert body["offset"] == 0
