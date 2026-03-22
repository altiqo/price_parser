from __future__ import annotations

from datetime import time as dt_time
from html import escape
from pathlib import Path

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .charting import ChartService
from .db import Database
from .models import CheckResult, Marketplace, TrackTarget
from .monitoring import MonitoringService

BTN_LIST = "📋 Мои отслеживания"
BTN_ADD = "➕ Добавить запрос"
BTN_CHECK_ALL = "🔎 Проверить все"
BTN_CLEAR_ALL = "🧹 Очистить все"
BTN_SCHEDULE = "⚙️ Расписание"
BTN_HELP = "❓ Помощь"

MENU_TEXT = (
    "🤖 <b>Price Parser Bot</b>\n\n"
    "Следи за ценами на <b>Wildberries</b>, <b>Ozon</b> и <b>Yandex Market</b> без ручной проверки.\n\n"
    "<b>Что умеет бот:</b>\n"
    "• добавлять отслеживания по обычному поисковому запросу\n"
    "• показывать актуальный минимум по каждой площадке\n"
    "• хранить историю цен и строить график\n"
    "• автоматически проверять цены и присылать уведомление, если минимум снизился\n"
    "• отправлять ежедневную сводку по отслеживаниям\n\n"
    "<b>Быстрый старт:</b>\n"
    "• нажми <b>«Добавить запрос»</b> и просто отправь название товара\n"
    "• открой <b>«Расписание»</b>, чтобы менять автопроверку и время сводки прямо в Telegram\n"
    "• или используй команду <code>/add cudy wr3000s | wb,ozon,ym</code>"
)

HELP_TEXT = (
    "❓ <b>Как пользоваться ботом</b>\n\n"
    "• <b>Добавить запрос</b> — бот сам спросит, что искать и на каких площадках\n"
    "• <b>Мои отслеживания</b> — откроет список с кнопками проверки, графика и удаления\n"
    "• <b>Проверить все</b> — вручную обновит цены по всем запросам\n"
    "• <b>Расписание</b> — покажет текущие настройки мониторинга и команды изменения\n"
    "• <b>Очистить все</b> — удалит все отслеживания в этом чате\n"
    "• автопроверка выполняется по расписанию, а раз в день приходит общая сводка\n\n"
    "<b>Команды расписания:</b>\n"
    "• <code>/schedule</code> — показать текущее расписание\n"
    "• <code>/schedule interval 3h</code> — изменить интервал проверки\n"
    "• <code>/schedule report_time 09:30</code> — изменить время сводки\n"
    "• <code>/schedule report on</code> — включить ежедневную сводку\n"
    "• <code>/schedule report off</code> — выключить ежедневную сводку\n"
    "• минимальный интервал проверки: <b>1 час</b>\n\n"
    "<b>Команды:</b>\n"
    "• <code>/add &lt;запрос&gt; | &lt;wb,ozon,ym&gt;</code>\n"
    "• <code>/list</code>\n"
    "• <code>/check 1</code>\n"
    "• <code>/chart 1</code>\n"
    "• <code>/delete 1</code>\n"
    "• <code>/clear</code>\n"
    "• <code>/schedule</code>\n"
    "• <code>/cancel</code>"
)


class AddTargetStates(StatesGroup):
    waiting_query = State()
    choosing_marketplaces = State()


def build_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_LIST), KeyboardButton(text=BTN_ADD)],
            [KeyboardButton(text=BTN_CHECK_ALL), KeyboardButton(text=BTN_SCHEDULE)],
            [KeyboardButton(text=BTN_CLEAR_ALL)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие или отправь команду",
    )


def build_home_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_ADD, callback_data="menu:add"),
                InlineKeyboardButton(text=BTN_LIST, callback_data="menu:list"),
            ],
            [
                InlineKeyboardButton(text=BTN_CHECK_ALL, callback_data="menu:check_all"),
                InlineKeyboardButton(text=BTN_SCHEDULE, callback_data="menu:schedule"),
            ],
            [InlineKeyboardButton(text=BTN_CLEAR_ALL, callback_data="menu:clear")],
        ]
    )


def build_marketplace_selector(selected: list[Marketplace]) -> InlineKeyboardMarkup:
    def button(marketplace: Marketplace) -> InlineKeyboardButton:
        is_selected = marketplace in selected
        prefix = "✅" if is_selected else "▫️"
        return InlineKeyboardButton(
            text=f"{prefix} {_marketplace_label(marketplace)}",
            callback_data=f"add:toggle:{marketplace.value}",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button(Marketplace.WB), button(Marketplace.OZON)],
            [button(Marketplace.YANDEX_MARKET)],
            [
                InlineKeyboardButton(text="💾 Сохранить", callback_data="add:save"),
                InlineKeyboardButton(text="✖️ Отмена", callback_data="add:cancel"),
            ],
        ]
    )


def build_post_add_actions(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Проверить сейчас", callback_data=f"target:check:{target_id}")],
            [
                InlineKeyboardButton(text="📋 Открыть список", callback_data="menu:list"),
                InlineKeyboardButton(text="➕ Добавить еще", callback_data="menu:add"),
            ],
        ]
    )


def build_targets_keyboard(targets: list[TrackTarget]) -> InlineKeyboardMarkup:
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for index, target in enumerate(targets, start=1):
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🔎 {index}. {_short_query(target.query, 20)}",
                    callback_data=f"target:check:{target.id}",
                ),
                InlineKeyboardButton(text="📈", callback_data=f"target:chart:{target.id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"target:delete:{target.id}"),
            ]
        )
    keyboard_rows.append(
        [
            InlineKeyboardButton(text="➕ Добавить", callback_data="menu:add"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="targets:refresh"),
        ]
    )
    keyboard_rows.append([InlineKeyboardButton(text="🧹 Очистить все", callback_data="menu:clear")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def parse_marketplaces(raw: str | None) -> list[Marketplace]:
    if not raw:
        return [Marketplace.WB, Marketplace.OZON, Marketplace.YANDEX_MARKET]
    mapping = {
        "wb": Marketplace.WB,
        "ozon": Marketplace.OZON,
        "ym": Marketplace.YANDEX_MARKET,
        "yandex": Marketplace.YANDEX_MARKET,
        "market": Marketplace.YANDEX_MARKET,
    }
    marketplaces: list[Marketplace] = []
    for token in raw.split(","):
        normalized = token.strip().lower()
        marketplace = mapping.get(normalized)
        if marketplace and marketplace not in marketplaces:
            marketplaces.append(marketplace)
    return marketplaces or [Marketplace.WB, Marketplace.OZON, Marketplace.YANDEX_MARKET]


def build_dispatcher(
    db: Database,
    monitoring: MonitoringService,
    chart_service: ChartService,
    charts_dir: Path,
) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("start"))
    @dp.message(Command("menu"))
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _send_home_message(message, MENU_TEXT)

    @dp.message(Command("help"))
    @dp.message(F.text.in_({BTN_HELP, "Помощь"}))
    async def help_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _send_home_message(message, HELP_TEXT)

    @dp.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        if await state.get_state() is None:
            await message.answer(
                "ℹ️ Сейчас нет активного сценария. Можно воспользоваться меню ниже.",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return
        await state.clear()
        await message.answer(
            "✖️ <b>Действие отменено.</b>\n\nМожно выбрать другой пункт меню.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )

    @dp.message(Command("add"))
    async def add_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        if not command.args:
            await _start_add_flow(message, state)
            return

        parts = [item.strip() for item in command.args.split("|", maxsplit=1)]
        query = parts[0]
        raw_marketplaces = parts[1] if len(parts) > 1 else None
        if not query:
            await message.answer(
                "⚠️ <b>Нужен текст поискового запроса.</b>\n\nПример: <code>/add cudy wr3000s | wb,ozon,ym</code>",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return

        await state.clear()
        marketplaces = parse_marketplaces(raw_marketplaces)
        target_id = await db.add_target(message.chat.id, query, marketplaces)
        targets = await db.list_targets(message.chat.id)
        position = _find_position(targets, target_id)
        await message.answer(
            _format_add_success_text(query, marketplaces, position),
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )

    @dp.message(F.text.in_({BTN_ADD, "Добавить запрос"}))
    async def add_hint_handler(message: Message, state: FSMContext) -> None:
        await _start_add_flow(message, state)

    @dp.message(StateFilter(AddTargetStates.waiting_query), F.text)
    async def add_query_input_handler(message: Message, state: FSMContext) -> None:
        query = message.text.strip()
        if not query:
            await message.answer(
                "⚠️ <b>Запрос пустой.</b>\n\nОтправь название товара, например: <code>cudy wr3000s</code>",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return

        marketplaces = [Marketplace.WB, Marketplace.OZON, Marketplace.YANDEX_MARKET]
        await state.update_data(query=query, marketplaces=[item.value for item in marketplaces])
        await state.set_state(AddTargetStates.choosing_marketplaces)
        await message.answer(
            _format_marketplace_selector_text(query, marketplaces),
            reply_markup=build_marketplace_selector(marketplaces),
            parse_mode=ParseMode.HTML,
        )

    @dp.message(StateFilter(AddTargetStates.choosing_marketplaces))
    async def add_marketplace_input_hint(message: Message) -> None:
        await message.answer(
            "👆 <b>Выбери площадки кнопками под предыдущим сообщением</b>, затем нажми <b>«Сохранить»</b>.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )

    @dp.callback_query(F.data == "menu:add")
    async def menu_add_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if callback.message:
            await _start_add_flow(callback.message, state)

    @dp.callback_query(F.data == "menu:list")
    async def menu_list_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await _send_targets_overview(callback.message, db)

    @dp.callback_query(F.data == "menu:check_all")
    async def menu_check_all_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await _check_all_targets(callback.message, db, monitoring)

    @dp.callback_query(F.data == "menu:schedule")
    async def menu_schedule_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await _send_schedule_overview(callback.message, monitoring)

    @dp.callback_query(F.data == "menu:clear")
    async def menu_clear_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await _send_clear_confirmation(callback.message, db)

    @dp.callback_query(StateFilter(AddTargetStates.choosing_marketplaces), F.data.startswith("add:toggle:"))
    async def add_toggle_marketplace_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if not callback.message:
            return
        data = await state.get_data()
        query = str(data.get("query") or "").strip()
        current = _deserialize_marketplaces(data.get("marketplaces"))
        marketplace_value = callback.data.rsplit(":", 1)[1]
        marketplace = Marketplace(marketplace_value)
        if marketplace in current:
            current = [item for item in current if item != marketplace]
        else:
            current.append(marketplace)
        current = _normalize_marketplace_order(current)
        await state.update_data(marketplaces=[item.value for item in current])
        await callback.message.edit_text(
            _format_marketplace_selector_text(query, current),
            reply_markup=build_marketplace_selector(current),
            parse_mode=ParseMode.HTML,
        )

    @dp.callback_query(StateFilter(AddTargetStates.choosing_marketplaces), F.data == "add:save")
    async def add_save_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if not callback.message:
            return
        data = await state.get_data()
        query = str(data.get("query") or "").strip()
        marketplaces = _deserialize_marketplaces(data.get("marketplaces"))
        if not query:
            await state.set_state(AddTargetStates.waiting_query)
            await callback.message.edit_text(
                "⚠️ <b>Не удалось сохранить запрос.</b>\n\nОтправь название товара еще раз.",
                parse_mode=ParseMode.HTML,
            )
            return
        if not marketplaces:
            await callback.answer("Выбери хотя бы одну площадку", show_alert=True)
            return

        target_id = await db.add_target(callback.message.chat.id, query, marketplaces)
        targets = await db.list_targets(callback.message.chat.id)
        position = _find_position(targets, target_id)
        await state.clear()
        await callback.message.edit_text(
            _format_add_success_text(query, marketplaces, position),
            reply_markup=build_post_add_actions(target_id),
            parse_mode=ParseMode.HTML,
        )

    @dp.callback_query(StateFilter(AddTargetStates.waiting_query, AddTargetStates.choosing_marketplaces), F.data == "add:cancel")
    async def add_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                "✖️ <b>Добавление запроса отменено.</b>",
                reply_markup=build_home_actions(),
                parse_mode=ParseMode.HTML,
            )

    @dp.message(Command("list"))
    @dp.message(F.text.in_({BTN_LIST, "Мои отслеживания"}))
    async def list_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _send_targets_overview(message, db)

    @dp.message(Command("check"))
    async def check_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        await state.clear()
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _send_check_result(message, db, monitoring, target)

    @dp.message(F.text.in_({BTN_CHECK_ALL, "Проверить все"}))
    async def check_all_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _check_all_targets(message, db, monitoring)

    @dp.message(Command("schedule"))
    async def schedule_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        await state.clear()
        await _handle_schedule_command(message, monitoring, command.args)

    @dp.message(F.text.in_({BTN_SCHEDULE, "Расписание"}))
    async def schedule_menu_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _send_schedule_overview(message, monitoring)

    @dp.message(Command("chart"))
    async def chart_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        await state.clear()
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _send_chart(message, db, chart_service, target)

    @dp.message(Command("delete"))
    async def delete_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        await state.clear()
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _delete_target(message, db, charts_dir, target)
        await _send_targets_overview(message, db)

    @dp.message(Command("clear"))
    @dp.message(F.text.in_({BTN_CLEAR_ALL, "Удалить все"}))
    async def clear_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await _send_clear_confirmation(message, db)

    @dp.callback_query(F.data == "targets:refresh")
    async def refresh_targets_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await _send_targets_overview(callback.message, db)

    @dp.callback_query(F.data == "clear:cancel")
    async def clear_cancel_callback(callback: CallbackQuery) -> None:
        await callback.answer("Отменено")
        if callback.message:
            await callback.message.edit_text(
                "👌 <b>Удаление отменено.</b>",
                reply_markup=build_home_actions(),
                parse_mode=ParseMode.HTML,
            )

    @dp.callback_query(F.data == "clear:confirm")
    async def clear_confirm_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        removed = await db.clear_targets(callback.message.chat.id)
        for file in charts_dir.glob("target_*.png"):
            file.unlink(missing_ok=True)
        await callback.message.edit_text(
            f"🧹 <b>Отслеживания удалены:</b> {removed}",
            parse_mode=ParseMode.HTML,
        )
        await _send_targets_overview(callback.message, db)

    @dp.callback_query(F.data.startswith("target:check:"))
    async def check_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer(
                "⚠️ <b>Запрос уже удален.</b>",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return
        await _send_check_result(callback.message, db, monitoring, target)

    @dp.callback_query(F.data.startswith("target:chart:"))
    async def chart_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer(
                "⚠️ <b>Запрос уже удален.</b>",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return
        await _send_chart(callback.message, db, chart_service, target)

    @dp.callback_query(F.data.startswith("target:delete:"))
    async def delete_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer(
                "⚠️ <b>Запрос уже удален.</b>",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return
        await _delete_target(callback.message, db, charts_dir, target)
        await _send_targets_overview(callback.message, db)

    @dp.message(F.text)
    async def fallback_handler(message: Message) -> None:
        await message.answer(
            "🤝 <b>Не понял команду.</b>\n\nИспользуй кнопки меню ниже или отправь <code>/help</code>.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )

    return dp


async def _send_home_message(message: Message, text: str) -> None:
    await message.answer(
        text,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )
    await message.answer(
        "✨ <b>Быстрые действия</b>",
        reply_markup=build_home_actions(),
        parse_mode=ParseMode.HTML,
    )


async def _start_add_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddTargetStates.waiting_query)
    await message.answer(
        "🧾 <b>Новый запрос</b>\n\n"
        "Отправь название товара одним сообщением.\n\n"
        "Например: <code>cudy wr3000s</code>\n\n"
        "Если передумаешь, отправь <code>/cancel</code>.",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def _handle_schedule_command(message: Message, monitoring: MonitoringService, raw_args: str | None) -> None:
    args = (raw_args or "").strip()
    if not args:
        await _send_schedule_overview(message, monitoring)
        return

    parts = args.split()
    action = parts[0].lower()
    try:
        if action == "interval":
            if len(parts) != 2:
                raise ValueError("Используй формат: /schedule interval 3h")
            seconds = _parse_interval_to_seconds(parts[1])
            schedule = await monitoring.set_poll_interval_seconds(message.chat.id, seconds)
            await message.answer(
                _format_schedule_updated_text("Интервал автопроверки для этого чата обновлен.", schedule),
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return

        if action == "report_time":
            if len(parts) != 2:
                raise ValueError("Используй формат: /schedule report_time 09:30")
            report_time = _parse_schedule_time(parts[1])
            schedule = await monitoring.set_daily_report_time(message.chat.id, report_time)
            await message.answer(
                _format_schedule_updated_text("Время ежедневной сводки для этого чата обновлено.", schedule),
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return

        if action == "report":
            if len(parts) != 2:
                raise ValueError("Используй формат: /schedule report on")
            enabled = _parse_toggle(parts[1])
            schedule = await monitoring.set_daily_report_enabled(message.chat.id, enabled)
            status_text = "Ежедневная сводка для этого чата включена." if enabled else "Ежедневная сводка для этого чата отключена."
            await message.answer(
                _format_schedule_updated_text(status_text, schedule),
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.HTML,
            )
            return
    except ValueError as exc:
        await message.answer(
            f"⚠️ <b>{escape(str(exc))}</b>",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        "⚠️ <b>Неизвестная команда расписания.</b>\n\n"
        "Доступно:\n"
        "• <code>/schedule</code>\n"
        "• <code>/schedule interval 3h</code>\n"
        "• <code>/schedule report_time 09:30</code>\n"
        "• <code>/schedule report on</code>",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def _send_schedule_overview(message: Message, monitoring: MonitoringService) -> None:
    schedule = await monitoring.get_schedule(message.chat.id)
    await message.answer(
        _format_schedule_text(schedule),
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def _send_targets_overview(message: Message, db: Database) -> None:
    targets = await db.list_targets(message.chat.id)
    if not targets:
        await message.answer(
            "📭 <b>Список отслеживаний пуст.</b>\n\nНажми <b>«Добавить запрос»</b>, чтобы начать.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    lines = ["📋 <b>Мои отслеживания</b>\n"]
    for index, target in enumerate(targets, start=1):
        price = (
            f"{_format_price(target.last_notified_price)} RUB"
            if target.last_notified_price is not None
            else "еще нет замеров"
        )
        lines.append(
            f"<b>{index}. {escape(target.query)}</b>\n"
            f"🛍 <b>Площадки:</b> {escape(_format_marketplaces(target.marketplaces))}\n"
            f"💰 <b>Последний минимум:</b> {escape(price)}"
        )

    await message.answer(
        "\n\n".join(lines),
        reply_markup=build_targets_keyboard(targets),
        parse_mode=ParseMode.HTML,
    )


async def _check_all_targets(message: Message, db: Database, monitoring: MonitoringService) -> None:
    targets = await db.list_targets(message.chat.id)
    if not targets:
        await message.answer(
            "📭 <b>Список отслеживаний пуст.</b>",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        "⏳ <b>Проверяю все отслеживания...</b>",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )

    reports: list[str] = []
    for index, target in enumerate(targets, start=1):
        result = await monitoring.check_target(target)
        if result is not None:
            await db.update_last_notified_price(target.id, result.cheapest.price)
        reports.append(_format_target_report(index, target, result))

    await message.answer(
        "\n\n".join(reports),
        reply_markup=build_main_menu(),
        disable_web_page_preview=True,
        parse_mode=ParseMode.HTML,
    )


async def _send_check_result(
    message: Message,
    db: Database,
    monitoring: MonitoringService,
    target: TrackTarget,
) -> None:
    await message.answer(
        f"⏳ <b>Проверяю:</b> {escape(target.query)}",
        parse_mode=ParseMode.HTML,
    )
    result = await monitoring.check_target(target)
    await message.answer(
        _format_target_report(None, target, result),
        disable_web_page_preview=True,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )
    if result is not None:
        await db.update_last_notified_price(target.id, result.cheapest.price)


async def _send_chart(message: Message, db: Database, chart_service: ChartService, target: TrackTarget) -> None:
    snapshots = await db.list_snapshots(target.id)
    if len(snapshots) < 2:
        await message.answer(
            "📉 <b>Пока мало данных для графика.</b>\n\nНужно минимум 2 замера цены.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return
    image_path = chart_service.build_chart(target, snapshots)
    await message.answer_photo(
        FSInputFile(image_path),
        caption=f"📈 <b>История цены</b>\n\n{escape(target.query)}",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def _delete_target(message: Message, db: Database, charts_dir: Path, target: TrackTarget) -> None:
    removed = await db.delete_target(target.id, message.chat.id)
    if not removed:
        await message.answer(
            "⚠️ <b>Не удалось удалить запрос.</b>",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return
    chart_path = charts_dir / f"target_{target.id}.png"
    if chart_path.exists():
        chart_path.unlink()
    await message.answer(
        f"🗑 <b>Запрос удален:</b>\n{escape(target.query)}",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def _send_clear_confirmation(message: Message, db: Database) -> None:
    targets = await db.list_targets(message.chat.id)
    if not targets:
        await message.answer(
            "📭 <b>Удалять нечего.</b>\n\nСписок отслеживаний уже пуст.",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧹 Да, удалить все", callback_data="clear:confirm"),
                InlineKeyboardButton(text="↩️ Отмена", callback_data="clear:cancel"),
            ]
        ]
    )
    await message.answer(
        f"⚠️ <b>Удалить все отслеживания?</b>\n\nСейчас в списке: <b>{len(targets)}</b>.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def _resolve_target_from_text(message: Message, raw: str | None, db: Database) -> TrackTarget | None:
    if not raw or not raw.strip().isdigit():
        await message.answer(
            "🔢 <b>Нужен номер из списка.</b>\n\nПример: <code>/check 1</code>",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.HTML,
        )
        return None
    index = int(raw.strip())
    targets = await db.list_targets(message.chat.id)
    if 1 <= index <= len(targets):
        return targets[index - 1]
    target = await db.get_target(index, message.chat.id)
    if target is not None:
        return target
    await message.answer(
        "⚠️ <b>Такой элемент не найден.</b>",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.HTML,
    )
    return None


def _short_query(value: str, limit: int = 28) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _find_position(targets: list[TrackTarget], target_id: int) -> int:
    for index, target in enumerate(targets, start=1):
        if target.id == target_id:
            return index
    return 1


def _format_target_report(index: int | None, target: TrackTarget, result: CheckResult | None) -> str:
    prefix = f"{index}. " if index is not None else ""
    title_line = f"🧾 <b>{escape(prefix + target.query)}</b>"
    if result is None:
        return (
            f"{title_line}\n\n"
            "⚠️ <i>Не удалось получить релевантные предложения.</i>\n"
            "Попробуй уточнить запрос или повторить проверку позже."
        )

    cheapest = result.cheapest
    summary = (
        f"💰 <b>Текущий минимум:</b> {_format_price(cheapest.price)} {escape(cheapest.currency)}\n"
        f"🛍 <b>Площадка:</b> {escape(_marketplace_label(cheapest.marketplace))}\n"
        f"🔗 <b>Товар:</b> <a href=\"{escape(cheapest.url, quote=True)}\">{escape(cheapest.title)}</a>"
    )

    market_lines: list[str] = []
    for marketplace in sorted(target.marketplaces, key=lambda item: item.value):
        offer = result.per_marketplace.get(marketplace)
        label = _marketplace_label(marketplace)
        if offer is not None:
            market_lines.append(
                f"• <b>{escape(label)}</b>: {_format_price(offer.price)} {escape(offer.currency)} "
                f"(<a href=\"{escape(offer.url, quote=True)}\">открыть</a>)"
            )
            continue
        error = _humanize_error(result.errors.get(marketplace, "нет данных"))
        market_lines.append(f"• <b>{escape(label)}</b>: {escape(error)}")

    return (
        f"{title_line}\n\n"
        f"{summary}\n\n"
        f"📊 <b>Минимумы по площадкам</b>\n"
        + "\n".join(market_lines)
    )


def _format_add_success_text(query: str, marketplaces: list[Marketplace], position: int) -> str:
    return (
        "✅ <b>Отслеживание добавлено</b>\n\n"
        f"🧾 <b>Запрос:</b> {escape(query)}\n"
        f"🛍 <b>Площадки:</b> {escape(_format_marketplaces(marketplaces))}\n"
        f"📍 <b>Позиция в списке:</b> {position}"
    )


def _format_marketplace_selector_text(query: str, marketplaces: list[Marketplace]) -> str:
    selected = _format_marketplaces(marketplaces) if marketplaces else "ничего не выбрано"
    return (
        "🛍 <b>Выбор площадок</b>\n\n"
        f"🧾 <b>Запрос:</b> {escape(query)}\n"
        f"✅ <b>Сейчас выбрано:</b> {escape(selected)}\n\n"
        "Нажимай на кнопки ниже, чтобы включать и выключать площадки."
    )


def _format_schedule_text(schedule) -> str:
    report_status = "включена" if schedule.daily_report_enabled else "выключена"
    interval_hours = schedule.poll_interval_seconds / 3600
    interval_text = (
        f"{int(interval_hours)} ч"
        if interval_hours.is_integer()
        else f"{interval_hours:.1f} ч"
    )
    return (
        "⚙️ <b>Текущее расписание для этого чата</b>\n\n"
        f"🔁 <b>Автопроверка:</b> каждые {escape(interval_text)} "
        f"({schedule.poll_interval_seconds} сек)\n"
        f"🗓 <b>Ежедневная сводка:</b> {escape(report_status)}\n"
        f"⏰ <b>Время сводки:</b> {schedule.daily_report_time.strftime('%H:%M')}\n"
        f"🌍 <b>Часовой пояс:</b> {escape(schedule.schedule_timezone)}\n\n"
        "<b>Команды:</b>\n"
        "• <code>/schedule interval 3h</code>\n"
        "• <code>/schedule interval 7200</code>\n"
        "• <code>/schedule report_time 09:30</code>\n"
        "• <code>/schedule report on</code>\n"
        "• <code>/schedule report off</code>"
    )


def _format_schedule_updated_text(title: str, schedule) -> str:
    return f"✅ <b>{escape(title)}</b>\n\n{_format_schedule_text(schedule)}"


def _deserialize_marketplaces(raw: object) -> list[Marketplace]:
    if not isinstance(raw, list):
        return []
    marketplaces: list[Marketplace] = []
    for item in raw:
        try:
            marketplace = Marketplace(str(item))
        except ValueError:
            continue
        if marketplace not in marketplaces:
            marketplaces.append(marketplace)
    return _normalize_marketplace_order(marketplaces)


def _normalize_marketplace_order(marketplaces: list[Marketplace]) -> list[Marketplace]:
    ordered: list[Marketplace] = []
    for marketplace in [Marketplace.WB, Marketplace.OZON, Marketplace.YANDEX_MARKET]:
        if marketplace in marketplaces:
            ordered.append(marketplace)
    return ordered


def _format_marketplaces(marketplaces: list[Marketplace]) -> str:
    return ", ".join(_marketplace_label(item) for item in marketplaces)


def _format_price(price: float | None) -> str:
    if price is None:
        return "0.00"
    return f"{price:,.2f}".replace(",", " ")


def _humanize_error(message: str) -> str:
    lowered = message.lower()
    if "cooldown" in lowered:
        return "временная пауза после блокировки"
    if "blocked" in lowered:
        return "маркетплейс временно заблокировал запрос"
    if "captcha" in lowered:
        return "маркетплейс запросил капчу"
    return message


def _marketplace_label(marketplace: Marketplace) -> str:
    labels = {
        Marketplace.WB: "Wildberries",
        Marketplace.OZON: "Ozon",
        Marketplace.YANDEX_MARKET: "Yandex Market",
    }
    return labels.get(marketplace, marketplace.value)


def _parse_interval_to_seconds(value: str) -> int:
    raw = value.strip().lower()
    if raw.endswith("h"):
        amount = float(raw[:-1])
        seconds = int(amount * 3600)
    elif raw.endswith("m"):
        amount = float(raw[:-1])
        seconds = int(amount * 60)
    else:
        seconds = int(raw)
    if seconds < 3600:
        raise ValueError("Интервал проверки не может быть меньше 1 часа")
    return seconds


def _parse_schedule_time(value: str) -> dt_time:
    try:
        hour_text, minute_text = value.strip().split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("Время должно быть в формате HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Время должно быть в формате HH:MM")
    return dt_time(hour=hour, minute=minute)


def _parse_toggle(value: str) -> bool:
    raw = value.strip().lower()
    if raw in {"on", "true", "1", "yes", "enable", "enabled", "вкл"}:
        return True
    if raw in {"off", "false", "0", "no", "disable", "disabled", "выкл"}:
        return False
    raise ValueError("Используй on/off для включения или выключения сводки")
