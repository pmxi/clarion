"""Local app setup service."""

from __future__ import annotations

import secrets

from clarion.local.config import settings
from clarion.local.database import LocalDatabase


class LocalSetupService:
    def __init__(self, db: LocalDatabase):
        self.db = db

    def initialize(
        self,
        *,
        llm_api_key: str,
        llm_model: str,
        telegram_bot_token: str = "",
        telegram_bot_username: str = "",
        max_lookback_hours: str = "24",
    ) -> None:
        if not llm_api_key:
            raise ValueError("LLM_API_KEY is required.")
        self.db.set_app_setting("LLM_API_KEY", llm_api_key)
        self.db.set_app_setting("LLM_MODEL", llm_model or settings.LLM_MODEL)
        self.db.set_app_setting("MAX_LOOKBACK_HOURS", max_lookback_hours)
        if telegram_bot_token:
            self.db.set_app_setting("TELEGRAM_BOT_TOKEN", telegram_bot_token)
        if telegram_bot_username:
            self.db.set_app_setting("TELEGRAM_BOT_USERNAME", telegram_bot_username.lstrip("@"))
        if not self.db.get_app_setting("SESSION_SECRET"):
            self.db.set_app_setting("SESSION_SECRET", secrets.token_hex(32))
