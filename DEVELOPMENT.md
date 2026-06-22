# TODO

## Data sources
- Figure out X (Twitter) scraping — the most valuable source we haven't unlocked.
- Figure out Instagram scraping.

## Architecture follow-ups
- Stand up a read API (cursor feed over `event.id` + filtered query + search)
  so aggregator apps stop depending on direct Postgres access. Today
  `clarion_web` reads Postgres directly — the deliberate "shared Postgres now,
  API later" call.
- Fix the `.env` naming drift: it still points at the legacy
  `sentinel_user@.../sentinel` DB, but the live database is
  `clarion_user@.../clarion`. (Untracked file, holds the password — update by
  hand.)
- Migrate the live `oracle` deployment off the legacy Sentinel names: checkout
  path, the now-two systemd units (`clarion` + `clarion-web`), environment
  path, Postgres database, and Postgres role.
- Clean the inert `item_classified` SSE handlers and the permanently-empty
  "IMPORTANT" column left in `clarion_web` `dashboard.html` / `live.html` after
  classification was removed.
- One-time DB cleanup for obsolete rows/settings: legacy `email` stream rows,
  `RESEND_*` / `EMAIL_FROM_*` / `EMAIL_NOTIFICATION_TO` settings, and the
  disabled `bluesky-firehose` stream row.
- Add smoke tests for stream registration, CLI stream choices, and the
  `clarion_web` route map. The refactor relied on manual checks.

## Future
- If newsworthiness ranking is wanted again, reintroduce ML scoring /
  classification as a **separate** concern/service (was: logistic regression
  -> local LLM -> API LLM). It was removed from the collector when Clarion
  narrowed to pure news collection.

## Notes
- Postgres lives on the `oracle` SSH host: `ssh -L 5433:localhost:5432 oracle`.
