"""Story tables (`story`, `story_event`).

Two writers, disjoint in time: the digest daemon grows stories
incrementally (stable ids) inside its active window, and the backfill
builder replaces whole past days (delete day + reinsert).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Sequence, Tuple

import psycopg
from psycopg.rows import DictRow

_STORY_CHUNK = 500


# ----- incremental (digest daemon) ------------------------------------------


def insert_story(
    conn: psycopg.Connection[DictRow],
    *,
    day: date,
    title: str,
    rep_event_id: int,
    event_count: int,
    source_count: int,
    centroid: bytes,
    first_seen_at: datetime,
    last_seen_at: datetime,
) -> int:
    row = conn.execute(
        """
        INSERT INTO story (day, title, rep_event_id, event_count,
                           source_count, centroid, first_seen_at, last_seen_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (day, title, rep_event_id, event_count, source_count,
         centroid, first_seen_at, last_seen_at),
    ).fetchone()
    assert row is not None  # INSERT ... RETURNING always yields one row
    return int(row["id"])


def update_story(
    conn: psycopg.Connection[DictRow],
    story_id: int,
    *,
    title: str,
    rep_event_id: int,
    event_count: int,
    source_count: int,
    centroid: bytes,
    last_seen_at: datetime,
) -> None:
    conn.execute(
        """
        UPDATE story SET title=%s, rep_event_id=%s, event_count=%s,
                         source_count=%s, centroid=%s, last_seen_at=%s
        WHERE id=%s
        """,
        (title, rep_event_id, event_count, source_count,
         centroid, last_seen_at, story_id),
    )


def add_members(
    conn: psycopg.Connection[DictRow],
    rows: Sequence[Tuple[int, int, float]],
) -> None:
    """(story_id, event_id, similarity) inserts; replays are ignored."""
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO story_event (story_id, event_id, similarity) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )


def absorb_story(
    conn: psycopg.Connection[DictRow], winner_id: int, loser_id: int
) -> None:
    """Move the loser's members to the winner and delete the loser.
    The caller updates the winner's rollup separately."""
    conn.execute(
        "UPDATE story_event SET story_id=%s WHERE story_id=%s",
        (winner_id, loser_id),
    )
    conn.execute("DELETE FROM story WHERE id=%s", (loser_id,))


def active_stories(
    conn: psycopg.Connection[DictRow], since: datetime
) -> List[Dict[str, Any]]:
    """Stories still inside the daemon's window, for restart rebuild."""
    rows = conn.execute(
        """
        SELECT id, day, title, rep_event_id, event_count, source_count,
               centroid, first_seen_at, last_seen_at
        FROM story
        WHERE last_seen_at >= %s AND centroid IS NOT NULL
        ORDER BY id
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def all_members(
    conn: psycopg.Connection[DictRow], story_ids: List[int]
) -> Dict[int, List[Dict[str, Any]]]:
    """Every member of the listed stories, with the event fields the
    daemon needs to rebuild in-memory state (domains, rep tracking)."""
    if not story_ids:
        return {}
    rows = conn.execute(
        """
        SELECT se.story_id, se.event_id, se.similarity,
               e.title, e.url, e.stream_name, e.observed_at
        FROM story_event se
        JOIN event e ON e.id = se.event_id
        WHERE se.story_id = ANY(%s)
        ORDER BY se.story_id, se.event_id
        """,
        (story_ids,),
    ).fetchall()
    out: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["story_id"]), []).append(dict(r))
    return out


# ----- write ---------------------------------------------------------------


def replace_day(conn: psycopg.Connection[DictRow], day: date, stories: List[Dict[str, Any]]) -> None:
    """Replace one day's stories. Each story dict carries title,
    rep_event_id, event_count, source_count, and members — a list of
    (event_id, similarity) pairs."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM story WHERE day = %s", (day,))
            id_by_rep: Dict[int, int] = {}
            for lo in range(0, len(stories), _STORY_CHUNK):
                chunk = stories[lo : lo + _STORY_CHUNK]
                placeholders = ",".join(["(%s,%s,%s,%s,%s)"] * len(chunk))
                flat: List[Any] = []
                for s in chunk:
                    flat.extend((day, s["title"], s["rep_event_id"],
                                 s["event_count"], s["source_count"]))
                cur.execute(
                    f"""
                    INSERT INTO story (day, title, rep_event_id, event_count,
                                       source_count)
                    VALUES {placeholders}
                    RETURNING id, rep_event_id
                    """,
                    flat,
                )
                # rep_event_id is unique per story (the medoid is a member,
                # and members are disjoint), so it keys the id mapping.
                for r in cur.fetchall():
                    id_by_rep[int(r["rep_event_id"])] = int(r["id"])
            with cur.copy(
                "COPY story_event (story_id, event_id, similarity) FROM STDIN"
            ) as copy:
                for s in stories:
                    sid = id_by_rep[s["rep_event_id"]]
                    for event_id, sim in s["members"]:
                        copy.write_row((sid, event_id, sim))


# ----- read ----------------------------------------------------------------


def available_days(conn: psycopg.Connection[DictRow]) -> List[date]:
    rows = conn.execute("SELECT DISTINCT day FROM story ORDER BY day DESC").fetchall()
    return [r["day"] for r in rows]


def day_stats(conn: psycopg.Connection[DictRow], day: date) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS stories,
               COALESCE(SUM(event_count), 0) AS events,
               MAX(last_seen_at) AS updated
        FROM story WHERE day = %s
        """,
        (day,),
    ).fetchone()
    return dict(row) if row else {}


def top_stories(
    conn: psycopg.Connection[DictRow], day: date, limit: int = 50
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.event_count, s.source_count,
               e.url AS rep_url, e.received_at AS rep_received_at
        FROM story s
        JOIN event e ON e.id = s.rep_event_id
        WHERE s.day = %s
        ORDER BY s.source_count DESC, s.event_count DESC, s.id
        LIMIT %s
        """,
        (day, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def story_count(conn: psycopg.Connection[DictRow], day: date) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM story WHERE day = %s", (day,)
    ).fetchone()
    return int(row["n"]) if row else 0


def members_for(
    conn: psycopg.Connection[DictRow], story_ids: List[int], per_story: int = 12
) -> Dict[int, List[Dict[str, Any]]]:
    """Top member articles (by similarity to the story centroid) for each
    listed story."""
    if not story_ids:
        return {}
    rows = conn.execute(
        """
        SELECT story_id, title, url, stream_name, received_at, similarity
        FROM (
            SELECT sa.story_id, e.title, e.url, e.stream_name,
                   e.received_at, sa.similarity,
                   ROW_NUMBER() OVER (
                       PARTITION BY sa.story_id
                       ORDER BY sa.similarity DESC, e.id
                   ) AS rn
            FROM story_event sa
            JOIN event e ON e.id = sa.event_id
            WHERE sa.story_id = ANY(%s)
        ) ranked
        WHERE rn <= %s
        ORDER BY story_id, similarity DESC
        """,
        (story_ids, per_story),
    ).fetchall()
    out: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["story_id"]), []).append(dict(r))
    return out
