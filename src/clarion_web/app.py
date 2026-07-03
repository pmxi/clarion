"""Clarion web UI: app factory wiring the blueprints together."""

from __future__ import annotations

from typing import Optional

from flask import Flask

from clarion.config import settings
from clarion.db import pool as db_pool
from clarion.db.migrate import ensure_schema
from clarion.ingest.sources import ensure_loaded
from clarion.logging import get_logger

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

    from clarion_web.views import dashboard, digest, live, streams

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(digest.bp)
    app.register_blueprint(live.bp)
    app.register_blueprint(streams.bp)

    return app


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
