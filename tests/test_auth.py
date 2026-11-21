import os
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from main import app
from auth import get_role, require_admin

client = TestClient(app)


def test_auth_anonymous_is_viewer():
    """Anonymous requests (no X-API-Key) get viewer role."""
    role = get_role(x_api_key=None)
    assert role == "viewer"


def test_auth_invalid_key_raises_401():
    """Supplying an invalid or unrecognized key raises 401 Unauthorized, never silently downgraded."""
    with patch.dict(os.environ, {"API_KEY": "valid-secret-key"}):
        with pytest.raises(Exception) as exc_info:
            get_role(x_api_key="wrong-key")
        assert "401" in str(exc_info.value) or exc_info.value.status_code == 401


def test_auth_valid_admin_key():
    """Supplying matching API_KEY gives admin role."""
    with patch.dict(os.environ, {"API_KEY": "valid-secret-key"}):
        role = get_role(x_api_key="valid-secret-key")
        assert role == "admin"


def test_require_admin_when_server_key_unset():
    """If API_KEY is unset on the server, admin endpoints return 503 (configuration error), never open."""
    with patch.dict(os.environ, {}, clear=True):
        if "API_KEY" in os.environ:
            del os.environ["API_KEY"]
        with pytest.raises(Exception) as exc_info:
            require_admin(x_api_key=None)
        assert exc_info.value.status_code == 503

        with pytest.raises(Exception) as exc_info:
            require_admin(x_api_key="some-key")
        assert exc_info.value.status_code == 503


def test_require_admin_when_key_missing_or_invalid():
    """When API_KEY is configured, missing or invalid keys return 401."""
    with patch.dict(os.environ, {"API_KEY": "supersecret"}):
        # Missing header
        with pytest.raises(Exception) as exc_info:
            require_admin(x_api_key=None)
        assert exc_info.value.status_code == 401

        # Invalid key
        with pytest.raises(Exception) as exc_info:
            require_admin(x_api_key="bad-token")
        assert exc_info.value.status_code == 401

        # Valid key succeeds
        assert require_admin(x_api_key="supersecret") == "admin"


def test_admin_endpoint_integration():
    """Test actual endpoint access through client with various auth states."""
    # 1. Unset API_KEY on server -> 503
    with patch.dict(os.environ, {}, clear=True):
        if "API_KEY" in os.environ:
            del os.environ["API_KEY"]
        resp = client.post("/api/model/retrain")
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"].lower()

    # 2. Configured API_KEY, missing header -> 401
    with patch.dict(os.environ, {"API_KEY": "my-secret-key"}):
        resp = client.post("/api/model/retrain")
        assert resp.status_code == 401
        assert "required" in resp.json()["detail"].lower()

        # 3. Configured API_KEY, wrong header -> 401
        resp = client.post("/api/model/retrain", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

        # 4. Configured API_KEY, valid header -> executes route (blocked by Phase 1/2 readiness gate or proceeds)
        resp = client.post("/api/model/retrain", headers={"X-API-Key": "my-secret-key"})
        assert resp.status_code == 200
