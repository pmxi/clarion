# Clarion — vision & roadmap

## Vision

News arrives faster than a person can follow it. Publisher sites, RSS feeds,
news sitemaps, and social platforms all carry fragments of the same evolving
story.

Clarion monitors those sources, surfaces consequential developments quickly,
and suppresses routine noise. The goal: keep up with a large information flow
without watching every feed.

The product is the daily digest. The collector and dashboard exist to feed it.

## Todo

After deploying the July-2026 simplification: run the one-time manual
DROPs listed in DEPLOYMENT.md ("Running a migration") — app_setting,
schema_meta, the three unused event indexes, story.lang.

Decide: `event.body` and `event.author` are written but nothing reads
them. Keep collecting (raw material for future features: search,
summarization) or stop writing them too.

Backfill the digest gap (2026-07-02 through 2026-07-06) from a laptop:
`uv run clarion digest build --day YYYY-MM-DD`, one day at a time.

Postgres backups are not wired up; `event` and `stream` are
irreplaceable.

devcontainer is out of date

Not planned
- X scraping
- Insta scraping