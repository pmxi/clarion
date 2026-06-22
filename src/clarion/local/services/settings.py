"""Local app setup service."""

from __future__ import annotations

import secrets

from clarion.local.database import LocalDatabase


class LocalSetupService:
    def __init__(self, db: LocalDatabase):
        self.db = db

    def initialize(self) -> None:
        if not self.db.get_app_setting("SESSION_SECRET"):
            self.db.set_app_setting("SESSION_SECRET", secrets.token_hex(32))
