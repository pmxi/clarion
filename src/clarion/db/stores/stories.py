"""Daily story digest tables (`story`, `story_article`).

Writes are per-day replacements (delete day + reinsert in one
transaction), matching the digest builder's idempotent-rebuild contract.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import DictRow

_STORY_CHUNK = 500


# ----- write ---------------------------------------------------------------


def replace_day(conn: psycopg.Connection[DictRow], day: date, stories: List[Dict[str, Any]]) -> None:
    """Replace one day's stories. Each story dict carries title,
    rep_event_id, article_count, source_count, lang, and members —
    a list of (event_id, similarity) pairs."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM story WHERE day = %s", (day,))
            id_by_rep: Dict[int, int] = {}
            for lo in range(0, len(stories), _STORY_CHUNK):
                chunk = stories[lo : lo + _STORY_CHUNK]
                placeholders = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(chunk))
                flat: List[Any] = []
                for s in chunk:
                    flat.extend((day, s["title"], s["rep_event_id"],
                                 s["article_count"], s["source_count"], s["lang"]))
                cur.execute(
                    f"""
                    INSERT INTO story (day, title, rep_event_id, article_count,
                                       source_count, lang)
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
                "COPY story_article (story_id, event_id, similarity) FROM STDIN"
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
               COALESCE(SUM(article_count), 0) AS articles,
               MAX(built_at) AS built_at
        FROM story WHERE day = %s
        """,
        (day,),
    ).fetchone()
    return dict(row) if row else {}


def lang_counts(conn: psycopg.Connection[DictRow], day: date, top: int = 8) -> List[Tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT lang, COUNT(*) AS n FROM story
        WHERE day = %s AND lang IS NOT NULL
        GROUP BY lang ORDER BY n DESC LIMIT %s
        """,
        (day, top),
    ).fetchall()
    return [(r["lang"], r["n"]) for r in rows]


def top_stories(
    conn: psycopg.Connection[DictRow],
    day: date,
    lang: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    sql = """
        SELECT s.id, s.title, s.article_count, s.source_count, s.lang,
               e.url AS rep_url, e.received_at AS rep_received_at
        FROM story s
        JOIN event e ON e.id = s.rep_event_id
        WHERE s.day = %s
    """
    params: List[Any] = [day]
    if lang:
        sql += " AND s.lang = %s"
        params.append(lang)
    sql += " ORDER BY s.source_count DESC, s.article_count DESC, s.id LIMIT %s OFFSET %s"
    params.extend((limit, offset))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def story_count(conn: psycopg.Connection[DictRow], day: date, lang: Optional[str] = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM story WHERE day = %s"
    params: List[Any] = [day]
    if lang:
        sql += " AND lang = %s"
        params.append(lang)
    row = conn.execute(sql, params).fetchone()
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
            FROM story_article sa
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
