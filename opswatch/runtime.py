from __future__ import annotations

import asyncio
import logging
import time

from opswatch.backup.manager import BackupManager
from opswatch.bot.manager import BotManager
from opswatch.config import AppConfig
from opswatch.connectors import load_connectors
from opswatch.core.metrics import MetricStore
from opswatch.core.notifier import Notifier
from opswatch.core.pipeline import EventPipeline
from opswatch.core.scheduler import Scheduler
from opswatch.core.sources import SourceService
from opswatch.db import Database
from opswatch.i18n import ts
from opswatch.security import Crypto, LoginThrottle
from opswatch.services.bootstrap import bootstrap
from opswatch.services.chat import ChatService
from opswatch.services.settings import SettingsStore

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, config: AppConfig, start_bot: bool = True, start_scheduler: bool = True) -> None:
        self.config = config
        self.start_bot = start_bot
        self.start_scheduler = start_scheduler
        self.db = Database(config.database_url)
        self.crypto = Crypto(config.secret_key)
        self.settings = SettingsStore(
            self.db,
            self.crypto,
            env_overrides={
                "telegram_token": config.telegram_token,
                "telegram_api_url": config.telegram_api_url,
                "public_url": config.public_url,
            },
        )
        self.bot = BotManager(self)
        self.notifier = Notifier(self.db, self.settings, self.crypto, lambda: self.bot)
        self.pipeline = EventPipeline(self.db, self.settings, self.notifier)
        self.metrics = MetricStore(self.db)
        self.sources = SourceService(self.db, self.crypto, self.settings, self.pipeline, config.tmp_dir, self.metrics)
        self.backups = BackupManager(
            self.db, self.crypto, self.settings, self.sources, self.pipeline, lambda: self.bot, config
        )
        self.chat = ChatService(self.db, self.settings, self.crypto, lambda: self.bot)
        self.scheduler = Scheduler(self)
        self.throttle = LoginThrottle()
        self.started_at = time.time()
        self._bot_task: asyncio.Task | None = None

    async def start(self) -> None:
        load_connectors(self.config.plugins_dir)
        await self.db.create_all()
        await bootstrap(self.db, self.config.admin_username, self.config.admin_password)
        await self.settings.load()
        await self.chat.start()
        await self.notifier.start()
        if self.start_scheduler:
            await self.scheduler.start()
        if self.start_bot:
            self._bot_task = asyncio.create_task(self.bot.start(), name="opswatch-bot-start")
        log.info(ts("OpsWatch запущен, данные: %s"), self.config.data_dir)

    async def restart_bot(self) -> None:
        if self.start_bot:
            await self.bot.start()

    async def stop(self) -> None:
        if self._bot_task is not None and not self._bot_task.done():
            self._bot_task.cancel()
        await self.chat.stop()
        await self.bot.stop()
        await self.scheduler.stop()
        await self.notifier.stop()
        await self.db.dispose()
