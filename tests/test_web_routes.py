"""Route-map smoke test. Needs a reachable Postgres (DATABASE_URL);
skipped otherwise, since the app factory loads settings from the DB."""

import os

import pytest

EXPECTED_ROUTES = {
    "/",
    "/live",
    "/streams",
    "/streams/activity",
    "/streams/new",
    "/streams/new/rss",
    "/streams/<name>/toggle",
    "/streams/<name>/delete",
    "/digest",
    "/digest/<day>",
    "/events/stream",
}


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs DATABASE_URL")
def test_route_map_complete():
    from clarion_web.app import create_app

    app = create_app(database_url=os.environ["DATABASE_URL"])
    rules = {r.rule for r in app.url_map.iter_rules() if r.endpoint != "static"}
    missing = EXPECTED_ROUTES - rules
    assert not missing, f"routes disappeared: {missing}"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs DATABASE_URL")
def test_key_pages_render():
    from clarion_web.app import create_app

    app = create_app(database_url=os.environ["DATABASE_URL"])
    client = app.test_client()
    for path in ("/", "/live", "/streams", "/streams/new", "/streams/new/rss"):
        assert client.get(path).status_code == 200, path
    assert client.get("/digest").status_code in (200, 302)
