"""A reader for the daily digest.

One job: render the stories that `clarion digest build` wrote for a day
as a page of cards, newest day first. Stateless — no accounts, no
read-tracking, nothing to administer. Streams and collector operations
live in the `clarion` CLI; this process only reads the story tables.
"""

from __future__ import annotations

import os
from datetime import date

from flask import Flask, abort, redirect, render_template, request, url_for

from clarion.config import settings
from clarion.db import open_pool_with_schema
from clarion.db import pool as db_pool
from clarion.db.stores import stories as stories_store
from clarion.digest.text import normalize_title, source_domain

TOP_STORIES = 50  # cards on a day page before "show all"
MEMBERS_PER_CARD = 5  # member headlines shown under a story title


def _distinct_members(story: dict, members: list[dict]) -> list[dict]:
    """Member headlines that add something. Syndicated copies repeat the
    same title across domains, and the representative headline is already
    the card title — both are noise under a card."""
    seen = {normalize_title(story["title"]).lower()}
    out: list[dict] = []
    for m in members:
        key = normalize_title(m["title"]).lower()
        if m["url"] == story["rep_url"] or key in seen:
            continue
        seen.add(key)
        m["domain"] = source_domain(m["url"], m["stream_name"])
        out.append(m)
        if len(out) == MEMBERS_PER_CARD:
            break
    return out


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def latest():
        with db_pool.connection() as conn:
            days = stories_store.available_days(conn)
        if not days:
            return render_template("digest.html", day=None)
        return redirect(url_for("day_page", day_str=days[0].isoformat()))

    @app.get("/<day_str>")
    def day_page(day_str: str):
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            abort(404)
        show_all = request.args.get("all") == "1"

        with db_pool.connection() as conn:
            days = stories_store.available_days(conn)
            if day not in days:
                abort(404)
            total = stories_store.story_count(conn, day)
            limit = total if show_all else TOP_STORIES
            stories = stories_store.top_stories(conn, day, limit=limit)
            members = stories_store.members_for(conn, [s["id"] for s in stories])
            stats = stories_store.day_stats(conn, day)

        for s in stories:
            s["domain"] = source_domain(s["rep_url"], "")
            s["members"] = _distinct_members(s, members.get(s["id"], []))

        # `days` is newest-first; the adjacent digests for the nav links.
        newer = next((d for d in reversed(days) if d > day), None)
        older = next((d for d in days if d < day), None)

        return render_template(
            "digest.html",
            day=day,
            stories=stories,
            total=total,
            stats=stats,
            show_all=show_all,
            newer=newer,
            older=older,
        )

    return app


def main() -> None:
    open_pool_with_schema(settings.require_database_url())
    port = int(os.environ.get("CLARION_WEB_PORT", "8766"))
    create_app().run(host="127.0.0.1", port=port)
