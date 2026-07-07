"""`clarion status` — collector health at a glance."""

from __future__ import annotations

import argparse

from clarion.cli.common import database_label, open_pool
from clarion.db.stores import events as events_store
from clarion.db.stores import monitoring as monitoring_store
from clarion.db.stores import streams as streams_store
from clarion.timeutils import utc_now


def cmd_status(_args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        started = monitoring_store.get_monitoring_start_time(conn)
        last_check = monitoring_store.get_last_check_time(conn)
        total = events_store.count(conn)
        n_streams = len(streams_store.list_all(conn))
        latest = events_store.recent(conn, limit=5)
        cursor = monitoring_store.get_digest_cursor(conn)
        latest_id = events_store.latest_id(conn)

    print(f"Database:  {database_label()}")
    print(f"Streams:   {n_streams} configured")
    print(f"Events:    {total}")
    if started:
        print(f"Collector: first started {started:%Y-%m-%d %H:%M:%S}Z")
    if last_check is None:
        print("Heartbeat: none recorded — has `clarion run` ever emitted?")
    else:
        age = int((utc_now() - last_check).total_seconds())
        print(f"Heartbeat: {age}s since the collector last emitted")
    if cursor is None:
        print("Digest:    daemon has never run")
    else:
        print(f"Digest:    cursor {latest_id - cursor} events behind the stream")
    if latest:
        print("Latest:")
        for e in latest:
            print(f"  {e['observed_at']:%H:%M:%S}Z  [{e['stream_name']}]  {e['title'][:70]}")


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "status", help="Collector health: streams, events, heartbeat"
    ).set_defaults(func=cmd_status)
