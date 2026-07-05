"""Route tests for the digest reader. The db layer is stubbed out so
these run without Postgres."""

from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest

DAYS = [date(2026, 7, 4), date(2026, 7, 3)]
TOTAL = 60


@contextmanager
def _fake_connection():
    yield None


def _story(i: int) -> dict:
    return {
        "id": i,
        "title": f"Story {i}",
        "event_count": 5,
        "source_count": 3,
        "lang": "en",
        "rep_url": f"https://example{i}.com/a",
        "rep_received_at": datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
    }


def _members(conn, ids, per_story=12):
    return {
        i: [
            # The representative article itself: must not repeat as a bullet.
            {
                "story_id": i,
                "title": f"Story {i}",
                "url": f"https://example{i}.com/a",
                "stream_name": f"stream-{i}",
                "received_at": None,
                "similarity": 1.0,
            },
            {
                "story_id": i,
                "title": f"Story {i} covered elsewhere",
                "url": f"https://other{i}.org/b",
                "stream_name": f"other-{i}",
                "received_at": None,
                "similarity": 0.9,
            },
            # A syndicated copy of the previous headline: must be deduped.
            {
                "story_id": i,
                "title": f"Story {i} covered elsewhere",
                "url": f"https://syndicated{i}.net/c",
                "stream_name": f"synd-{i}",
                "received_at": None,
                "similarity": 0.8,
            },
        ]
        for i in ids
    }


def _stub_stores(monkeypatch, days):
    from clarion.db import pool as db_pool
    from clarion.db.stores import stories as stories_store

    stories = [_story(i) for i in range(1, TOTAL + 1)]
    monkeypatch.setattr(db_pool, "connection", _fake_connection)
    monkeypatch.setattr(stories_store, "available_days", lambda conn: list(days))
    monkeypatch.setattr(
        stories_store,
        "story_count",
        lambda conn, day: len(stories),
    )
    monkeypatch.setattr(
        stories_store,
        "top_stories",
        lambda conn, day, limit=50: stories[:limit],
    )
    monkeypatch.setattr(stories_store, "members_for", _members)
    monkeypatch.setattr(
        stories_store,
        "day_stats",
        lambda conn, day: {
            "stories": len(stories),
            "events": 300,
            "built_at": datetime(2026, 7, 5, 7, 0, tzinfo=timezone.utc),
        },
    )


@pytest.fixture
def client(monkeypatch):
    from clarion.web.app import create_app

    _stub_stores(monkeypatch, DAYS)
    app = create_app()
    app.testing = True
    return app.test_client()


def test_no_digests_yet(monkeypatch):
    from clarion.web.app import create_app

    _stub_stores(monkeypatch, days=[])
    resp = create_app().test_client().get("/")
    assert resp.status_code == 200
    assert b"No digests yet" in resp.data


def test_root_redirects_to_latest_day(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/2026-07-04")


def test_day_page_renders_story_cards(client):
    html = client.get("/2026-07-04").data.decode()
    assert "Story 1" in html
    assert "example1.com" in html  # representative domain
    assert "Story 1 covered elsewhere" in html  # member headline
    assert "other1.org" in html  # member domain
    assert "3 sources" in html
    # The representative article appears only as the card title, not
    # again in the member list.
    assert html.count("https://example1.com/a") == 1
    # Syndicated copies of a member headline are deduped by title.
    assert html.count("Story 1 covered elsewhere") == 1
    assert "syndicated1.net" not in html


def test_day_nav_links_adjacent_days(client):
    html = client.get("/2026-07-04").data.decode()
    assert "/2026-07-03" in html  # older
    html = client.get("/2026-07-03").data.decode()
    assert "/2026-07-04" in html  # newer


def test_front_page_caps_stories_and_offers_show_all(client):
    html = client.get("/2026-07-04").data.decode()
    assert "Story 50" in html
    assert "Story 51" not in html
    assert f"Show all {TOTAL} stories" in html


def test_show_all_renders_the_whole_day(client):
    html = client.get("/2026-07-04?all=1").data.decode()
    assert f"Story {TOTAL}" in html
    assert "Show all" not in html


def test_unknown_or_invalid_day_is_404(client):
    assert client.get("/2026-01-01").status_code == 404
    assert client.get("/not-a-date").status_code == 404
