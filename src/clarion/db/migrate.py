"""Schema application — the only place DDL runs.

Called once per process startup (collector, web, `clarion init`) and by
`clarion db migrate`. Connection-time DDL (the old LocalDatabase applied
schema.sql on every instantiation, i.e. every web request) is gone.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import DictRow

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 5

# Conditional renames that bring a pre-v5 database up to the vocabulary
# schema.sql now uses. schema.sql alone can't rename (its DDL is all
# IF NOT EXISTS), so these run first. Each is a no-op once applied;
# drop the block when every deployment is past v4.
_RENAMES = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'stream'
                 AND column_name = 'stream_type') THEN
        ALTER TABLE stream RENAME COLUMN stream_type TO source_type;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'story'
                 AND column_name = 'article_count') THEN
        ALTER TABLE story RENAME COLUMN article_count TO event_count;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'story_article') THEN
        ALTER TABLE story_article RENAME TO story_event;
    END IF;
END $$;
ALTER INDEX IF EXISTS story_article_event_idx RENAME TO story_event_event_id_idx;

-- Orphaned since the classifier's removal; only the pre-v5 collector still
-- named it in INSERTs, and the v5 deploy replaces that collector.
ALTER TABLE event DROP COLUMN IF EXISTS score;
"""


def ensure_schema(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(_RENAMES)
    conn.execute(SCHEMA_PATH.read_bytes())
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', %s) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
