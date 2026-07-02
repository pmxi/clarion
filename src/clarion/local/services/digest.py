"""Read-side queries for the daily story digest pages."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from clarion.digest.text import source_domain
from clarion.local.database import LocalDatabase


class DigestReadService:
    def __init__(self, db: LocalDatabase):
        self.db = db

    def available_days(self) -> List[date]:
        with self.db.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT day FROM story ORDER BY day DESC")
            return [r["day"] for r in cur.fetchall()]

    def day_stats(self, day: date) -> Dict[str, Any]:
        with self.db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS stories,
                       COALESCE(SUM(article_count), 0) AS articles,
                       MAX(built_at) AS built_at
                FROM story WHERE day = %s
                """,
                (day,),
            )
            return dict(cur.fetchone())

    def lang_counts(self, day: date, top: int = 8) -> List[Tuple[str, int]]:
        with self.db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT lang, COUNT(*) AS n FROM story
                WHERE day = %s AND lang IS NOT NULL
                GROUP BY lang ORDER BY n DESC LIMIT %s
                """,
                (day, top),
            )
            return [(r["lang"], r["n"]) for r in cur.fetchall()]

    def top_stories(
        self,
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
        with self.db.conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def story_count(self, day: date, lang: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM story WHERE day = %s"
        params: List[Any] = [day]
        if lang:
            sql += " AND lang = %s"
            params.append(lang)
        with self.db.conn.cursor() as cur:
            cur.execute(sql, params)
            return int(cur.fetchone()["n"])

    def members_for(
        self, story_ids: List[int], per_story: int = 12
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Top member articles (by similarity to the story centroid) for
        each listed story, with a display domain attached."""
        if not story_ids:
            return {}
        with self.db.conn.cursor() as cur:
            cur.execute(
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
            )
            out: Dict[int, List[Dict[str, Any]]] = {}
            for r in cur.fetchall():
                m = dict(r)
                m["domain"] = source_domain(m["url"], m["stream_name"])
                out.setdefault(int(m["story_id"]), []).append(m)
            return out
