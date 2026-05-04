import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.auth import get_current_buyer_org_id
from app.core.database import get_db
from app.main import app

TEST_BUYER_ORG_ID = "org-integration-xyz-456"


def _auth_override():
    return TEST_BUYER_ORG_ID


def _db_override():
    yield AsyncMock()


def _make_engagement(name: str = "Integration Engagement") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        name=name,
        status="active",
        created_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        buyer_org_id=TEST_BUYER_ORG_ID,
    )


class TestListEngagementsIntegration:
    def setup_method(self):
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_authenticated_returns_200(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([_make_engagement()], 1)
        mock_repo_class.return_value = mock_repo
        app.dependency_overrides[get_current_buyer_org_id] = _auth_override
        app.dependency_overrides[get_db] = _db_override

        response = self.client.get("/api/engagements")

        assert response.status_code == 200

    def test_unauthenticated_returns_401(self):
        response = self.client.get("/api/engagements")

        assert response.status_code == 401

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_empty_list_for_org_with_no_engagements(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([], 0)
        mock_repo_class.return_value = mock_repo
        app.dependency_overrides[get_current_buyer_org_id] = _auth_override
        app.dependency_overrides[get_db] = _db_override

        response = self.client.get("/api/engagements")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    @patch("app.api.routes.engagements.EngagementRepository")
    def test_response_schema_fields(self, mock_repo_class):
        mock_repo = AsyncMock()
        mock_repo.list_by_buyer_org.return_value = ([_make_engagement()], 1)
        mock_repo_class.return_value = mock_repo
        app.dependency_overrides[get_current_buyer_org_id] = _auth_override
        app.dependency_overrides[get_db] = _db_override

        response = self.client.get("/api/engagements?limit=10&offset=0")

        body = response.json()
        assert "items" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body
        assert body["limit"] == 10
        assert body["offset"] == 0
        item = body["items"][0]
        assert "id" in item
        assert "name" in item
        assert "status" in item
        assert "created_at" in item
