import concurrent.futures
from unittest.mock import Mock

import pytest

from services import tomtom_quota as quota


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(quota, "DB_PATH", tmp_path / "usage.sqlite3")


def test_reservation_persists_after_reinitialization(isolated_db):
    quota.reserve_request("search")
    assert quota.get_quota_status()["search"]["used"] == 1

    quota._initialize_database()

    assert quota.get_quota_status()["search"]["used"] == 1


def test_concurrent_reservations_are_all_counted(isolated_db):
    reservation_count = 64
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: quota.reserve_request("search"), range(reservation_count)))

    assert quota.get_quota_status()["search"]["used"] == reservation_count


def test_disabled_routing_does_not_send_http_request(isolated_db, monkeypatch):
    mocked_get = Mock()
    monkeypatch.setattr(quota.requests, "get", mocked_get)

    with pytest.raises(quota.TomTomQuotaExceeded):
        quota.tomtom_get("routing", "https://api.tomtom.com/test", params={"key": "mock-key"})

    mocked_get.assert_not_called()


def test_tomtom_get_uses_mocked_http_after_reservation(isolated_db, monkeypatch):
    mocked_response = Mock()
    mocked_get = Mock(return_value=mocked_response)
    monkeypatch.setattr(quota.requests, "get", mocked_get)

    response = quota.tomtom_get(
        "search", "https://api.tomtom.com/test", params={"key": "mock-key"}
    )

    assert response is mocked_response
    assert quota.get_quota_status()["search"]["used"] == 1
    mocked_get.assert_called_once()

def test_request_error_redacts_api_key(isolated_db, monkeypatch):
    import requests

    mocked_get = Mock(side_effect=requests.RequestException(
        "request failed for https://api.tomtom.com/test?key=mock-key"
    ))
    monkeypatch.setattr(quota.requests, "get", mocked_get)

    with pytest.raises(requests.RequestException) as error:
        quota.tomtom_get(
            "search",
            "https://api.tomtom.com/test",
            params={"key": "mock-key"},
        )

    assert "mock-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_response_url_redacts_api_key(isolated_db, monkeypatch):
    mocked_response = Mock()
    mocked_response.url = "https://api.tomtom.com/test?key=mock-key"
    mocked_get = Mock(return_value=mocked_response)
    monkeypatch.setattr(quota.requests, "get", mocked_get)

    quota.tomtom_get(
        "search",
        "https://api.tomtom.com/test",
        params={"key": "mock-key"},
    )

    assert "mock-key" not in mocked_response.url
    assert "[REDACTED]" in mocked_response.url
