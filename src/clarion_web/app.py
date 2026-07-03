"""Clarion web UI: daily digest, live feed, stream management."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import Flask, Response, redirect, render_template, request, stream_with_context, url_for

from clarion.config import settings
from clarion.db import pool as db_pool
from clarion.db.migrate import ensure_schema
from clarion.db.stores import events as events_store
from clarion.db.stores import state as state_store
from clarion.db.stores import stories as stories_store
from clarion.db.stores import streams as streams_store
from clarion.digest.text import source_domain
from clarion.ingest.sources import describe_stream_rows, ensure_loaded
from clarion.ingest.sources import get as get_stream_spec
from clarion.logging import get_logger
from clarion.timeutils import utc_now

logger = get_logger(__name__)


def create_app(database_url: Optional[str] = None, debug: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.debug = debug
    app.config["DATABASE_URL"] = database_url or settings.require_database_url()

    db_pool.open_pool(app.config["DATABASE_URL"])
    with db_pool.connection() as conn:
        ensure_schema(conn)
        settings.load(conn)
    ensure_loaded()
    app.secret_key = settings.SESSION_SECRET or "clarion-local"

    @app.route("/")
    def dashboard():
        with db_pool.connection() as conn:
            last_check = state_store.get_last_check_time(conn)
            snapshot = {
                "processed_count": events_store.count(conn),
                "last_check": last_check,
                "monitoring_start": state_store.get_monitoring_start_time(conn),
                "recent": events_store.recent(conn, limit=25),
                "streams_count": len(streams_store.list_all(conn)),
                "health": _daemon_health(last_check),
            }
        return render_template("dashboard.html", **snapshot)

    @app.route("/digest")
    def digest_latest():
        with db_pool.connection() as conn:
            days = stories_store.available_days(conn)
        if not days:
            return render_template("digest.html", day=None)
        return redirect(url_for("digest_day", day=days[0].isoformat()))

    @app.route("/digest/<day>")
    def digest_day(day: str):
        try:
            day_val = date.fromisoformat(day)
        except ValueError:
            return redirect(url_for("digest_latest"))

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

        # Attach display domains; distinct top domains per story, ordered
        # by closeness to the story.
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

    @app.route("/events/stream")
    def events_stream():
        last_id_header = request.headers.get("Last-Event-ID")
        since_param = request.args.get("since")
        try:
            if last_id_header is not None:
                cursor = int(last_id_header)
            elif since_param is not None:
                cursor = int(since_param)
            else:
                with db_pool.connection() as conn:
                    cursor = events_store.latest_id(conn)
        except (ValueError, TypeError):
            cursor = 0

        generate = _sse_poll_loop(app.config["DATABASE_URL"], cursor)
        return Response(
            stream_with_context(generate)(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/live")
    def live_page():
        """Real-time multi-source traffic monitor."""
        return render_template("live.html")

    @app.route("/streams/activity")
    def streams_activity():
        """Per-stream emission stats over a recent window.

        Reads the last `window` rows of `event` (default 20k) and groups
        by stream_name. Cheap because the outer filter uses the `id`
        BTREE index.
        """
        try:
            window = min(max(int(request.args.get("window", "20000")), 1000), 200000)
        except (TypeError, ValueError):
            window = 20000

        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(id) FROM event")
                row = cur.fetchone()
                max_id = (row["max"] if isinstance(row, dict) else row[0]) or 0
                low_id = max(0, max_id - window)
                cur.execute(
                    """
                    SELECT
                        stream_name              AS stream,
                        source_type,
                        MAX(observed_at)         AS last_seen,
                        MIN(observed_at)         AS first_seen,
                        COUNT(*)                 AS n
                    FROM event
                    WHERE id > %s
                    GROUP BY 1, 2
                    ORDER BY n DESC
                    """,
                    (low_id,),
                )
                rows = cur.fetchall()
                cur.execute(
                    "SELECT COUNT(*) AS c FROM event WHERE id > %s", (low_id,),
                )
                total_row = cur.fetchone()
                total = (total_row["c"] if isinstance(total_row, dict) else total_row[0]) or 0

        # Compute rate per stream in items/min
        now = utc_now()
        activity: List[Dict[str, Any]] = []
        for r in rows:
            d = r if isinstance(r, dict) else {
                "stream": r[0], "source_type": r[1],
                "last_seen": r[2], "first_seen": r[3], "n": r[4],
            }
            first = d["first_seen"]
            last = d["last_seen"]
            window_secs = max(1.0, (last - first).total_seconds()) if (first and last) else 60.0
            rate_per_min = d["n"] * 60.0 / window_secs if window_secs > 0 else 0
            age_secs = (now - last).total_seconds() if last else None
            activity.append({
                "stream": d["stream"] or "(unknown)",
                "source_type": d["source_type"] or "?",
                "count": d["n"],
                "rate_per_min": rate_per_min,
                "last_seen": last,
                "age_secs": age_secs,
            })

        # Total rate estimate across the whole window
        if activity:
            window_first = min((a["last_seen"] for a in activity if a["last_seen"]), default=now)
            total_window_secs = max(1.0, (now - window_first).total_seconds())
            total_rate_per_sec = total / total_window_secs
        else:
            total_rate_per_sec = 0

        return render_template(
            "streams_activity.html",
            activity=activity,
            window=window,
            total=total,
            total_rate_per_sec=total_rate_per_sec,
            distinct_streams=len(activity),
        )

    @app.route("/streams")
    def streams_page():
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
            type_counts[r["stream_type"]] = type_counts.get(r["stream_type"], 0) + 1
            if r["enabled"]:
                enabled_count += 1
            if r["error"]:
                error_count += 1

        def keep(r) -> bool:
            if type_filter and r["stream_type"] != type_filter:
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

    @app.route("/streams/new")
    def new_stream_page():
        return render_template("new_stream.html")

    @app.route("/streams/new/rss", methods=["GET", "POST"])
    def new_rss_stream_page():
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
                        return redirect(url_for("streams_page"))

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

    @app.route("/streams/<name>/toggle", methods=["POST"])
    def toggle_stream(name: str):
        with db_pool.connection() as conn:
            streams_store.toggle(conn, name)
        return redirect(url_for("streams_page"))

    @app.route("/streams/<name>/delete", methods=["POST"])
    def delete_stream(name: str):
        with db_pool.connection() as conn:
            streams_store.delete(conn, name)
        return redirect(url_for("streams_page"))

    return app


def _daemon_health(last_check: Optional[datetime]) -> Dict[str, Any]:
    if last_check is None:
        return {"status": "never run", "ok": False}
    age_s = (utc_now() - last_check).total_seconds()
    threshold = max(3 * 60, 60)
    if age_s < threshold:
        return {"status": f"running (last check {int(age_s)}s ago)", "ok": True}
    return {"status": f"stale (last check {int(age_s)}s ago)", "ok": False}


def _row_to_sse_payload(row: Dict[str, Any]) -> tuple[str, str]:
    """Render an event row into the (event_type, payload_json) pair the
    SSE client expects."""
    payload: Dict[str, Any] = {
        "source_type": row.get("source_type"),
        "item_id": row.get("item_id"),
        "stream_name": row.get("stream_name"),
        "title": row.get("title"),
        "body": row.get("body"),
        "url": row.get("url"),
        "author": row.get("author"),
        "received_at": row.get("received_at").isoformat() if row.get("received_at") else None,
    }
    return "item_received", json.dumps(payload, default=str)


def _sse_poll_loop(database_url: str, cursor: int):
    """Each SSE client gets a dedicated connection outside the pool: the
    generator lives for the whole browser-tab lifetime and would starve a
    small pool."""

    def generate():
        nonlocal cursor
        yield "retry: 3000\n: connected\n\n"
        heartbeat_countdown = 30
        conn = db_pool.raw_connection(database_url)
        try:
            while True:
                rows = events_store.fetch_since(conn, cursor, limit=200)
                if rows:
                    for row in rows:
                        cursor = int(row["id"])
                        event_type, payload = _row_to_sse_payload(row)
                        yield _sse_frame(cursor, event_type, payload)
                    heartbeat_countdown = 30
                else:
                    heartbeat_countdown -= 1
                    if heartbeat_countdown <= 0:
                        yield ": keepalive\n\n"
                        heartbeat_countdown = 30
                time.sleep(0.5)
        finally:
            conn.close()

    return generate


def _sse_frame(event_id: int, event_type: str, payload_json: str) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload_json}\n\n"


def run(host: str = "127.0.0.1", port: int = 8765, debug: bool = False) -> None:
    app = create_app(debug=debug)
    app.run(host=host, port=port, debug=debug, threaded=True)


def main() -> None:
    import os

    host = os.getenv("CLARION_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("CLARION_WEB_PORT", "8765"))
    run(host=host, port=port)


if __name__ == "__main__":
    main()
