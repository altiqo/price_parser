from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode

from .db import Database
from .marketplaces import MarketplaceClient, MarketplaceError
from .models import CheckResult, Offer, TrackTarget

logger = logging.getLogger(__name__)

_SCHEDULE_POLL_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class MonitoringSchedule:
    poll_interval_seconds: int
    daily_report_enabled: bool
    daily_report_time: dt_time
    schedule_timezone: str


class MonitoringService:
    def __init__(
        self,
        db: Database,
        bot: Bot,
        marketplace_clients: Iterable[MarketplaceClient],
        poll_interval_seconds: int,
        daily_report_enabled: bool,
        daily_report_time: dt_time,
        schedule_timezone: ZoneInfo,
    ) -> None:
        self._db = db
        self._bot = bot
        self._clients = {client.marketplace: client for client in marketplace_clients}
        self._default_poll_interval_seconds = poll_interval_seconds
        self._default_daily_report_enabled = daily_report_enabled
        self._default_daily_report_time = daily_report_time
        self._schedule_timezone = schedule_timezone
        self._scheduler_task: asyncio.Task | None = None
        self._cooldowns: dict[str, float] = {}
        self._run_lock = asyncio.Lock()
        self._schedule_updated = asyncio.Event()
        self._last_check_runs: dict[int, float] = {}
        self._last_daily_report_dates: dict[int, date] = {}

    def start(self) -> None:
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._run_scheduler_loop())

    async def stop(self) -> None:
        if self._scheduler_task is None:
            return
        self._scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._scheduler_task
        self._scheduler_task = None

    async def load_schedule_settings(self) -> None:
        poll_interval_value = await self._db.get_app_setting("schedule.poll_interval_seconds")
        if poll_interval_value is not None:
            self._default_poll_interval_seconds = self._validate_poll_interval_seconds(int(poll_interval_value))

        daily_report_enabled_value = await self._db.get_app_setting("schedule.daily_report_enabled")
        if daily_report_enabled_value is not None:
            self._default_daily_report_enabled = daily_report_enabled_value.strip().lower() in {"1", "true", "yes", "on"}

        daily_report_time_value = await self._db.get_app_setting("schedule.daily_report_time")
        if daily_report_time_value is not None:
            self._default_daily_report_time = self._parse_report_time(daily_report_time_value)

        self._schedule_updated.set()

    async def get_schedule(self, chat_id: int) -> MonitoringSchedule:
        return await self._get_chat_schedule(chat_id)

    async def set_poll_interval_seconds(self, chat_id: int, seconds: int) -> MonitoringSchedule:
        validated = self._validate_poll_interval_seconds(seconds)
        await self._db.set_chat_setting(chat_id, "schedule.poll_interval_seconds", str(validated))
        self._schedule_updated.set()
        return await self.get_schedule(chat_id)

    async def set_daily_report_time(self, chat_id: int, report_time: dt_time) -> MonitoringSchedule:
        normalized = dt_time(hour=report_time.hour, minute=report_time.minute)
        await self._db.set_chat_setting(chat_id, "schedule.daily_report_time", normalized.strftime("%H:%M"))
        self._schedule_updated.set()
        return await self.get_schedule(chat_id)

    async def set_daily_report_enabled(self, chat_id: int, enabled: bool) -> MonitoringSchedule:
        await self._db.set_chat_setting(chat_id, "schedule.daily_report_enabled", "true" if enabled else "false")
        self._schedule_updated.set()
        return await self.get_schedule(chat_id)

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
            available_offers = [offer for offer in offers if offer.is_available]
            if available_offers:
                per_marketplace[marketplace] = min(available_offers, key=lambda item: item.price)
                all_offers.extend(available_offers)
                continue
            if offers:
                errors[marketplace] = 'нет предложений в наличии'
                continue
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

    async def _run_scheduler_loop(self) -> None:
        while True:
            changed = await self._wait_for_schedule_update(_SCHEDULE_POLL_INTERVAL_SECONDS)
            try:
                await self._run_scheduled_tasks()
            except Exception:
                logger.exception("Monitoring iteration failed")
            if changed:
                continue

    async def _run_scheduled_tasks(self) -> None:
        async with self._run_lock:
            active_targets = await self._db.list_active_targets()
            targets_by_chat: dict[int, list[TrackTarget]] = defaultdict(list)
            for target in active_targets:
                targets_by_chat[target.chat_id].append(target)

            active_chat_ids = set(targets_by_chat)
            self._last_check_runs = {
                chat_id: value for chat_id, value in self._last_check_runs.items() if chat_id in active_chat_ids
            }
            self._last_daily_report_dates = {
                chat_id: value for chat_id, value in self._last_daily_report_dates.items() if chat_id in active_chat_ids
            }

            now_monotonic = time.monotonic()
            now_local = datetime.now(self._schedule_timezone)
            for chat_id, chat_targets in targets_by_chat.items():
                schedule = await self._get_chat_schedule(chat_id)
                if self._should_run_monitoring(chat_id, schedule, now_monotonic):
                    await self._run_chat_monitoring(chat_id, chat_targets)
                    self._last_check_runs[chat_id] = now_monotonic
                if self._should_send_daily_report(chat_id, schedule, now_local):
                    await self._send_chat_daily_report(chat_id, chat_targets)
                    self._last_daily_report_dates[chat_id] = now_local.date()

    async def _run_iteration(self) -> None:
        async with self._run_lock:
            active_targets = await self._db.list_active_targets()
            targets_by_chat: dict[int, list[TrackTarget]] = defaultdict(list)
            for target in active_targets:
                targets_by_chat[target.chat_id].append(target)
            for chat_id, chat_targets in targets_by_chat.items():
                await self._run_chat_monitoring(chat_id, chat_targets)

    async def _run_chat_monitoring(self, chat_id: int, targets: list[TrackTarget]) -> None:
        for target in targets:
            previous_price = target.last_notified_price
            result = await self.check_target(target)
            if result is None:
                continue
            cheapest = result.cheapest
            should_notify = previous_price is not None and cheapest.price < previous_price
            await self._db.update_last_notified_price(target.id, cheapest.price)
            if not should_notify:
                continue
            await self._bot.send_message(
                chat_id,
                self._build_notification_text(target, result, previous_price),
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
            )

    async def _send_chat_daily_report(self, chat_id: int, targets: list[TrackTarget]) -> None:
        schedule = await self._get_chat_schedule(chat_id)
        report = await self._build_daily_report(targets, schedule)
        await self._bot.send_message(
            chat_id,
            report,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )

    async def _build_daily_report(
        self,
        targets: list[TrackTarget],
        schedule: MonitoringSchedule | None = None,
    ) -> str:
        if schedule is None:
            chat_id = targets[0].chat_id if targets else 0
            schedule = await self.get_schedule(chat_id)
        lines = ["🗓 <b>Ежедневная сводка по ценам</b>"]
        for index, target in enumerate(targets, start=1):
            previous_price = target.last_notified_price
            result = await self.check_target(target)
            if result is None:
                lines.append(
                    f"\n<b>{index}. {escape(target.query)}</b>\n"
                    "⚠️ Не удалось получить актуальные цены"
                )
                continue

            current_price = result.cheapest.price
            trend = self._format_price_change(previous_price, current_price)
            lines.append(
                f"\n<b>{index}. {escape(target.query)}</b>\n"
                f"💰 {_format_price(current_price)} {escape(result.cheapest.currency)}\n"
                f"🛍 {escape(result.cheapest.marketplace.value)}\n"
                f"📈 {trend}\n"
                f"🔗 {escape(result.cheapest.url)}"
            )
            await self._db.update_last_notified_price(target.id, current_price)

        now = datetime.now(self._schedule_timezone).strftime("%d.%m.%Y %H:%M")
        lines.append(f"\n⏰ Сформировано: {escape(now)} ({escape(schedule.schedule_timezone)})")
        return "\n".join(lines)

    async def _get_chat_schedule(self, chat_id: int) -> MonitoringSchedule:
        poll_interval_value = await self._db.get_chat_setting(chat_id, "schedule.poll_interval_seconds")
        daily_report_enabled_value = await self._db.get_chat_setting(chat_id, "schedule.daily_report_enabled")
        daily_report_time_value = await self._db.get_chat_setting(chat_id, "schedule.daily_report_time")

        poll_interval_seconds = (
            self._validate_poll_interval_seconds(int(poll_interval_value))
            if poll_interval_value is not None
            else self._default_poll_interval_seconds
        )
        daily_report_enabled = (
            daily_report_enabled_value.strip().lower() in {"1", "true", "yes", "on"}
            if daily_report_enabled_value is not None
            else self._default_daily_report_enabled
        )
        daily_report_time = (
            self._parse_report_time(daily_report_time_value)
            if daily_report_time_value is not None
            else self._default_daily_report_time
        )
        return MonitoringSchedule(
            poll_interval_seconds=poll_interval_seconds,
            daily_report_enabled=daily_report_enabled,
            daily_report_time=daily_report_time,
            schedule_timezone=self._schedule_timezone.key,
        )

    def _should_run_monitoring(
        self,
        chat_id: int,
        schedule: MonitoringSchedule,
        now_monotonic: float,
    ) -> bool:
        last_run = self._last_check_runs.get(chat_id)
        if last_run is None:
            self._last_check_runs[chat_id] = now_monotonic
            return False
        return now_monotonic - last_run >= schedule.poll_interval_seconds

    def _should_send_daily_report(
        self,
        chat_id: int,
        schedule: MonitoringSchedule,
        now_local: datetime,
    ) -> bool:
        if not schedule.daily_report_enabled:
            return False
        last_sent_date = self._last_daily_report_dates.get(chat_id)
        if last_sent_date == now_local.date():
            return False
        scheduled_today = datetime.combine(
            now_local.date(),
            schedule.daily_report_time,
            tzinfo=self._schedule_timezone,
        )
        return now_local >= scheduled_today

    def _is_on_cooldown(self, marketplace: str) -> bool:
        return self._cooldowns.get(marketplace, 0) > time.monotonic()

    def _apply_cooldown(self, marketplace: str, message: str) -> None:
        lowered = message.lower()
        if '429' in lowered or 'rate limit' in lowered:
            self._cooldowns[marketplace] = time.monotonic() + 180
        elif '403' in lowered or 'blocked' in lowered:
            self._cooldowns[marketplace] = time.monotonic() + 900

    async def _wait_for_schedule_update(self, timeout_seconds: float | None = None) -> bool:
        if timeout_seconds is None:
            await self._schedule_updated.wait()
            self._schedule_updated.clear()
            return True
        try:
            await asyncio.wait_for(self._schedule_updated.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return False
        self._schedule_updated.clear()
        return True

    @staticmethod
    def _build_notification_text(target: TrackTarget, result: CheckResult, previous_price: float | None) -> str:
        offer = result.cheapest
        seller = f"\n🏪 <b>Продавец:</b> {escape(offer.seller)}" if offer.seller else ""
        lines = []
        for marketplace in sorted(target.marketplaces, key=lambda item: item.value):
            item = result.per_marketplace.get(marketplace)
            if item is not None:
                lines.append(
                    f"• <b>{escape(marketplace.value)}</b>: {item.price:.2f} {escape(item.currency)} | {escape(item.url)}"
                )
                continue
            error = escape(result.errors.get(marketplace, 'нет данных'))
            lines.append(f"• <b>{escape(marketplace.value)}</b>: {error}")
        marketplace_block = (
            f"\n\n📊 <b>Минимумы по площадкам</b>\n" + "\n".join(lines)
            if lines
            else ""
        )
        change_block = (
            f"\n📉 <b>Изменение:</b> {_format_price(previous_price - offer.price)} {escape(offer.currency)}"
            if previous_price is not None
            else ""
        )
        return (
            f"🔔 <b>Новая минимальная цена</b>\n\n"
            f"🧾 <b>Запрос #{target.id}:</b> {escape(target.query)}\n"
            f"🛍 <b>Маркетплейс:</b> {escape(offer.marketplace.value)}\n"
            f"🔗 <b>Товар:</b> {escape(offer.title)}\n"
            f"💰 <b>Цена:</b> {offer.price:.2f} {escape(offer.currency)}{change_block}{seller}"
            f"{marketplace_block}\n\n"
            f"Открыть: {escape(offer.url)}"
        )

    @staticmethod
    def _format_price_change(previous_price: float | None, current_price: float) -> str:
        if previous_price is None:
            return "первый замер"
        delta = current_price - previous_price
        if delta < 0:
            return f"цена снизилась на {_format_price(abs(delta))} RUB"
        if delta > 0:
            return f"цена выросла на {_format_price(delta)} RUB"
        return "без изменений"

    @staticmethod
    def _validate_poll_interval_seconds(value: int) -> int:
        if value < 3600:
            raise ValueError("Интервал проверки не может быть меньше 1 часа")
        return value

    @staticmethod
    def _parse_report_time(value: str) -> dt_time:
        try:
            hour_text, minute_text = value.strip().split(":", maxsplit=1)
            hour = int(hour_text)
            minute = int(minute_text)
        except ValueError as exc:
            raise ValueError("Время отчета должно быть в формате HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Время отчета должно быть в формате HH:MM")
        return dt_time(hour=hour, minute=minute)


def _format_price(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")
