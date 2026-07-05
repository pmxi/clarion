"""Daily story digest pages."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from clarion.db import pool as db_pool
from clarion.db.stores import stories as stories_store
from clarion.digest.text import source_domain

bp = Blueprint("digest", __name__)


@bp.route("/digest")
def latest():
    with db_pool.connection() as conn:
        days = stories_store.available_days(conn)
    if not days:
        return render_template("digest.html", day=None)
    return redirect(url_for("digest.day", day=days[0].isoformat()))


@bp.route("/digest/<day>")
def day(day: str):
    try:
        day_val = date.fromisoformat(day)
    except ValueError:
        return redirect(url_for("digest.latest"))

    lang = (request.args.get("lang") or "").strip().lower() or None
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 50
    offset = (page - 1) * per_page

    with db_pool.connection() as conn:
        days = stories_store.available_days(conn)
        stats = stories_store.day_stats(conn, day_val)
        total = stories_store.story_count(conn, day_val, lang=lang)
        stories = stories_store.top_stories(
            conn, day_val, lang=lang, limit=per_page, offset=offset
        )
        members = stories_store.members_for(conn, [s["id"] for s in stories])
        langs = stories_store.lang_counts(conn, day_val)

    # Attach display domains; distinct top domains per story, ordered by
    # closeness to the story.
    for mlist in members.values():
        for m in mlist:
            m["domain"] = source_domain(m["url"], m["stream_name"])
    for s in stories:
        seen: list[str] = []
        for m in members.get(s["id"], []):
            if m["domain"] not in seen:
                seen.append(m["domain"])
        s["top_domains"] = seen[:6]

    prev_day = next((d for d in days if d < day_val), None)
    next_day = next((d for d in reversed(days) if d > day_val), None)
    pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "digest.html",
        day=day_val,
        stories=stories,
        members=members,
        stats=stats,
        langs=langs,
        lang=lang,
        page=page,
        pages=pages,
        total=total,
        offset=offset,
        prev_day=prev_day,
        next_day=next_day,
    )
