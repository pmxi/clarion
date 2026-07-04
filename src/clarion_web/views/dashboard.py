"""Collector status dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from flask import Blueprint, render_template

from clarion.db import pool as db_pool
from clarion.db.stores import events as events_store
from clarion.db.stores import state as state_store
from clarion.db.stores import streams as streams_store
from clarion.timeutils import utc_now

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    with db_pool.connection() as conn:
        last_check = state_store.get_last_check_time(conn)
        snapshot = {
            "event_count": events_store.count(conn),
            "last_check": last_check,
            "monitoring_start": state_store.get_monitoring_start_time(conn),
            "recent": events_store.recent(conn, limit=25),
            "streams_count": len(streams_store.list_all(conn)),
            "health": _collector_health(last_check),
        }
    return render_template("dashboard.html", **snapshot)


def _collector_health(last_check: Optional[datetime]) -> Dict[str, Any]:
    if last_check is None:
        return {"status": "never run", "ok": False}
    age_s = (utc_now() - last_check).total_seconds()
    threshold = max(3 * 60, 60)
    if age_s < threshold:
        return {"status": f"running (last check {int(age_s)}s ago)", "ok": True}
    return {"status": f"stale (last check {int(age_s)}s ago)", "ok": False}
