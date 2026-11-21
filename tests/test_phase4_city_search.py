from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return [
            {"display_name": "Central Pune Road, Pune", "lat": "18.52", "lon": "73.85", "address": {"city": "Pune", "road": "Central Pune Road"}},
            {"display_name": "Central Mumbai Road, Mumbai", "lat": "19.07", "lon": "72.87", "address": {"city": "Mumbai", "road": "Central Mumbai Road"}},
        ]


def test_location_search_can_be_limited_to_city_without_live_provider(monkeypatch):
    monkeypatch.setattr(main, "TOMTOM_API_KEY", None)
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: FakeResponse())
    response = client.get("/api/search-location?q=Central%20Road&city=Pune")
    assert response.status_code == 200
    assert len(response.json()["locations"]) == 1
    assert response.json()["locations"][0]["city"] == "Pune"
