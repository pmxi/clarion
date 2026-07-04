"""Stream management pages."""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, redirect, render_template, request, url_for

from clarion.db import pool as db_pool
from clarion.db.stores import events as events_store
from clarion.db.stores import streams as streams_store
from clarion.ingest.streams import describe_stream_rows
from clarion.ingest.streams import get as get_stream_spec
from clarion.timeutils import utc_now

bp = Blueprint("streams", __name__)


@bp.route("/streams")
def index():
    with db_pool.connection() as conn:
        rows = describe_stream_rows(streams_store.list_all(conn))

    # Filters
    q = (request.args.get("q") or "").strip().lower()
    type_filter = (request.args.get("type") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()  # 'enabled'|'disabled'|'error'

    type_counts: dict[str, int] = {}
    enabled_count = 0
    error_count = 0
    for r in rows:
        type_counts[r["source_type"]] = type_counts.get(r["source_type"], 0) + 1
        if r["enabled"]:
            enabled_count += 1
        if r["error"]:
            error_count += 1

    def keep(r) -> bool:
        if type_filter and r["source_type"] != type_filter:
            return False
        if status == "enabled" and not r["enabled"]:
            return False
        if status == "disabled" and r["enabled"]:
            return False
        if status == "error" and not r["error"]:
            return False
        if q:
            hay = (r["name"] + " " + (r["detail"] or "")).lower()
            if q not in hay:
                return False
        return True

    filtered = [r for r in rows if keep(r)]

    # Pagination
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 100
    total = len(filtered)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    page_rows = filtered[start:start + per_page]

    return render_template(
        "streams.html",
        streams=page_rows,
        page=page,
        pages=pages,
        total=total,
        grand_total=len(rows),
        type_counts=sorted(type_counts.items(), key=lambda kv: -kv[1]),
        enabled_count=enabled_count,
        error_count=error_count,
        q=q,
        type_filter=type_filter,
        status=status,
    )


@bp.route("/streams/activity")
def activity():
    """Per-stream emission stats over a recent window of `event` rows
    (default 20k)."""
    try:
        window = min(max(int(request.args.get("window", "20000")), 1000), 200000)
    except (TypeError, ValueError):
        window = 20000

    with db_pool.connection() as conn:
        low_id = max(0, events_store.latest_id(conn) - window)
        rows = events_store.activity_since(conn, low_id)
        total = events_store.count_since(conn, low_id)

    # Compute rate per stream in items/min
    now = utc_now()
    activity_rows: List[Dict[str, Any]] = []
    for d in rows:
        first = d["first_seen"]
        last = d["last_seen"]
        window_secs = max(1.0, (last - first).total_seconds()) if (first and last) else 60.0
        rate_per_min = d["n"] * 60.0 / window_secs if window_secs > 0 else 0
        age_secs = (now - last).total_seconds() if last else None
        activity_rows.append({
            "stream": d["stream_name"] or "(unknown)",
            "source_type": d["source_type"] or "?",
            "count": d["n"],
            "rate_per_min": rate_per_min,
            "last_seen": last,
            "age_secs": age_secs,
        })

    # Total rate estimate across the whole window
    if activity_rows:
        window_first = min(
            (a["last_seen"] for a in activity_rows if a["last_seen"]), default=now
        )
        total_window_secs = max(1.0, (now - window_first).total_seconds())
        total_rate_per_sec = total / total_window_secs
    else:
        total_rate_per_sec = 0

    return render_template(
        "streams_activity.html",
        activity=activity_rows,
        window=window,
        total=total,
        total_rate_per_sec=total_rate_per_sec,
        distinct_streams=len(activity_rows),
    )


@bp.route("/streams/new")
def new():
    return render_template("new_stream.html")


@bp.route("/streams/new/rss", methods=["GET", "POST"])
def new_rss():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        feed_url = request.form.get("feed_url", "").strip()
        poll_str = request.form.get("poll_seconds", "300").strip()

        errors: List[str] = []
        if not name:
            errors.append("Pick a friendly name for this stream.")
        if not feed_url:
            errors.append("Feed URL is required.")
        try:
            poll_seconds = int(poll_str)
        except ValueError:
            errors.append(f"Poll interval must be a number (got {poll_str!r}).")
            poll_seconds = 300

        with db_pool.connection() as conn:
            if name and streams_store.get(conn, name):
                errors.append(
                    f"You already have a stream named {name!r}. Pick a different name."
                )
            if not errors:
                try:
                    config = get_stream_spec("rss").config_cls(
                        feed_url=feed_url, poll_seconds=poll_seconds
                    )
                except Exception as exc:
                    errors.append(f"Invalid config: {exc}")
                    config = None
                if config is not None:
                    streams_store.add(conn, name, "rss", config.model_dump_json())
                    return redirect(url_for("streams.index"))

        return render_template(
            "new_rss_stream.html",
            errors=errors,
            form={"name": name, "feed_url": feed_url, "poll_seconds": poll_str},
        )

    return render_template(
        "new_rss_stream.html",
        errors=[],
        form={"name": "", "feed_url": "", "poll_seconds": "300"},
    )


@bp.route("/streams/<name>/toggle", methods=["POST"])
def toggle(name: str):
    with db_pool.connection() as conn:
        streams_store.toggle(conn, name)
    return redirect(url_for("streams.index"))


@bp.route("/streams/<name>/delete", methods=["POST"])
def delete(name: str):
    with db_pool.connection() as conn:
        streams_store.delete(conn, name)
    return redirect(url_for("streams.index"))
