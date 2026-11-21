from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


class FakeTomTomResponse:
    ok = True

    def json(self):
        return {
            "results": [
                {
                    "address": {"municipality": "Bangalore", "freeformAddress": "MG Road, Bangalore"},
                    "poi": {"name": "MG Road"},
                    "position": {"lat": 12.975, "lon": 77.606},
                }
            ]
        }


def test_location_search_without_configured_provider_makes_no_external_request(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "TOMTOM_API_KEY", None)
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))
    response = client.get("/api/search-location?q=Central%20Road&city=Pune")
    assert response.status_code == 200
    assert response.json()["locations"] == []
    assert response.json()["source"] == "unavailable"
    assert calls == []


def test_tomtom_city_search_normalizes_bengaluru_alias_and_uses_mock(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "TOMTOM_API_KEY", "test-only-key")
    monkeypatch.setattr(
        main,
        "tomtom_get",
        lambda product, url, **kwargs: (calls.append((product, url, kwargs)) or FakeTomTomResponse()),
    )
    monkeypatch.setattr(
        main.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Unexpected live request")),
    )

    response = client.get("/api/search-location?q=MG%20Road&city=Bengaluru")

    assert response.status_code == 200
    assert response.json()["locations"][0]["city"] == "Bangalore"
    assert calls[0][0] == "search"
    assert "Bengaluru" in calls[0][1]
