import json
import socket
import threading
import time

import mongomock
import pytest
import uvicorn

from app import main


@pytest.fixture(scope="session")
def base_url():
    """Serve the real app (static frontend + routes) on a free port, backed by mongomock."""
    original = main.db.get_client
    main.db.get_client = lambda uri: mongomock.MongoClient()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    main.db.get_client = original


PLACES = [
    {
        "name": "Apotek Sehat", "category": "pharmacy", "distance_m": 120,
        "location": {"lat": -6.9170, "lng": 107.6190}, "phone": "+62 21 555 1111",
        "opening_hours": "Mo-Su 08:00-21:00", "rating": None, "gojek_link": None, "source": "osm",
    },
    {
        "name": "Kopi Kenangan", "category": "cafe", "distance_m": 1350,
        "location": {"lat": -6.9200, "lng": 107.6200}, "phone": None,
        "opening_hours": None, "rating": None, "gojek_link": None, "source": "osm",
    },
]


@pytest.fixture
def mock_api(page):
    """Replace /api/places with a canned response; returns a dict recording the requests seen."""
    state = {"requests": [], "status": 200, "body": None, "delay": 0}

    def handler(route):
        state["requests"].append(route.request.url)
        if state["delay"]:
            page.wait_for_timeout(state["delay"] * 1000)
        body = state["body"] if state["body"] is not None else {
            "query": {}, "partial": False, "results": PLACES,
        }
        route.fulfill(status=state["status"], content_type="application/json", body=json.dumps(body))

    page.route("**/api/places?*", handler)
    # Keep tests hermetic: don't fetch map tiles from OpenStreetMap.
    page.route("**/*.tile.openstreetmap.org/**", lambda route: route.abort())
    return state
