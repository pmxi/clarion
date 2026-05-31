# TODO

Figure out X scraping. That's the most valuable data source we haven't unlocked.

https://huggingface.co/Qwen/Qwen3-Embedding-0.6B

Improve cascade classifier to be
    logistic regression -> local LLM -> API LLM

Figure out Instagram scraping.

## Clarion split follow-ups

- Remove the inactive hosted runtime or define its future. Keeping it duplicates
  the web app, stream service, monitor, preferences, and Telegram listener.
- Add a one-time database cleanup for legacy `email` stream rows and obsolete
  `RESEND_*`, `EMAIL_FROM_*`, and `EMAIL_NOTIFICATION_TO` settings.
- Migrate the live `oracle` checkout, systemd unit, environment path, Postgres
  database, and Postgres role from the legacy Sentinel names to Clarion.
- Add smoke tests for stream registration, CLI stream choices, and the local
  web route map. The split currently relies on manual checks.


uv run hf auth login


ssh -L 5433:localhost:5432 oracle
oracle is the ssh host where the postgres db lives.

Rename database tables to use singular nouns and to be more clear.

Collapse the hosted / local split and make MVP.
