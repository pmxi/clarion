"""Live traffic monitor + the SSE event stream feeding it."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, render_template, request, stream_with_context

from clarion.db import pool as db_pool
from clarion.db.stores import events as events_store
from clarion.web import sse

bp = Blueprint("live", __name__)


@bp.route("/live")
def page():
    """Real-time multi-source traffic monitor."""
    return render_template("live.html")


@bp.route("/events/stream")
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

    generate = sse.poll_loop(current_app.config["DATABASE_URL"], cursor)
    return Response(
        stream_with_context(generate)(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
