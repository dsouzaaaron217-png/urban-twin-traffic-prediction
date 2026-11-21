import pytest


@pytest.fixture(autouse=True)
def disable_live_provider_calls(monkeypatch):
    """Keep the suite offline while allowing tests to explicitly mock requests.get."""
    import main

    monkeypatch.setattr(main, "TOMTOM_API_KEY", "test-key")

    def blocked_request(*_args, **_kwargs):
        raise AssertionError("A test attempted an unmocked external provider request")

    monkeypatch.setattr(main.requests, "get", blocked_request)
