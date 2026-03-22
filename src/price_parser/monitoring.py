from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterable

from aiogram import Bot

from .db import Database
from .marketplaces import MarketplaceClient, MarketplaceError
from .models import CheckResult, Offer, TrackTarget

logger = logging.getLogger(__name__)


class MonitoringService:
    def __init__(
        self,
        db: Database,
        bot: Bot,
        marketplace_clients: Iterable[MarketplaceClient],
        poll_interval_seconds: int,
    ) -> None:
        self._db = db
        self._bot = bot
        self._clients = {client.marketplace: client for client in marketplace_clients}
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._cooldowns: dict[str, float] = {}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def check_target(self, target: TrackTarget) -> CheckResult | None:
        all_offers: list[Offer] = []
        per_marketplace: dict = {}
        errors: dict = {}
        for marketplace in target.marketplaces:
            client = self._clients.get(marketplace)
            if client is None:
                errors[marketplace] = 'клиент не настроен'
                continue
            if self._is_on_cooldown(marketplace.value):
                errors[marketplace] = 'временный cooldown после блокировки'
                logger.info("Skip %s because cooldown is active", marketplace.value)
                continue
            try:
                offers = await client.search(target.query)
            except MarketplaceError as exc:
                logger.warning("Marketplace parsing error for %s: %s", marketplace, exc)
                errors[marketplace] = str(exc)
                self._apply_cooldown(marketplace.value, str(exc))
                continue
            except Exception:
                logger.exception("Unexpected marketplace error for %s", marketplace)
                errors[marketplace] = 'неожиданная ошибка'
                continue
            if offers:
                per_marketplace[marketplace] = min(offers, key=lambda item: item.price)
                all_offers.extend(offers)
            else:
                errors[marketplace] = 'нет релевантных предложений'

        if not all_offers:
            return None

        cheapest = min(all_offers, key=lambda item: item.price)
        await self._db.save_snapshot(
            target_id=target.id,
            price=cheapest.price,
            currency=cheapest.currency,
            title=cheapest.title,
            url=cheapest.url,
            marketplace=cheapest.marketplace,
            seller=cheapest.seller,
        )
        return CheckResult(
            cheapest=cheapest,
            per_marketplace=per_marketplace,
            errors=errors,
        )

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_seconds)
            try:
                await self._run_iteration()
            except Exception:
                logger.exception("Monitoring iteration failed")

    async def _run_iteration(self) -> None:
        for target in await self._db.list_active_targets():
            result = await self.check_target(target)
            if result is None:
                continue
            cheapest = result.cheapest
            should_notify = (
                target.last_notified_price is None
                or cheapest.price < target.last_notified_price
            )
            if not should_notify:
                continue
            await self._db.update_last_notified_price(target.id, cheapest.price)
            await self._bot.send_message(
                target.chat_id,
                self._build_notification_text(target, result),
                disable_web_page_preview=True,
            )

    def _is_on_cooldown(self, marketplace: str) -> bool:
        return self._cooldowns.get(marketplace, 0) > time.monotonic()

    def _apply_cooldown(self, marketplace: str, message: str) -> None:
        lowered = message.lower()
        if '429' in lowered or 'rate limit' in lowered:
            self._cooldowns[marketplace] = time.monotonic() + 180
        elif '403' in lowered or 'blocked' in lowered:
            self._cooldowns[marketplace] = time.monotonic() + 900

    @staticmethod
    def _build_notification_text(target: TrackTarget, result: CheckResult) -> str:
        offer = result.cheapest
        seller = f"\nПродавец: {offer.seller}" if offer.seller else ""
        lines = []
        for marketplace in sorted(target.marketplaces, key=lambda item: item.value):
            item = result.per_marketplace.get(marketplace)
            if item is not None:
                lines.append(f"- {marketplace.value}: {item.price:.2f} {item.currency} | {item.url}")
                continue
            error = result.errors.get(marketplace, 'нет данных')
            lines.append(f"- {marketplace.value}: {error}")
        marketplace_block = (
            f"\nМинимумы по площадкам:\n" + "\n".join(lines)
            if lines
            else ""
        )
        return (
            f"Нашел новую минимальную цену по запросу #{target.id}: {target.query}\n"
            f"Маркетплейс: {offer.marketplace.value}\n"
            f"Товар: {offer.title}\n"
            f"Цена: {offer.price:.2f} {offer.currency}{seller}"
            f"{marketplace_block}\n"
            f"Ссылка: {offer.url}"
        )
