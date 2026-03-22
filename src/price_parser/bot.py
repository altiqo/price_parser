from __future__ import annotations

from html import escape
from pathlib import Path

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
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

MENU_TEXT = (
    "\u0411\u043e\u0442 \u0434\u043b\u044f \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433\u0430 \u0446\u0435\u043d \u0433\u043e\u0442\u043e\u0432.\n\n"
    "\u0427\u0442\u043e \u043c\u043e\u0436\u043d\u043e \u0434\u0435\u043b\u0430\u0442\u044c:\n"
    "- \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441: /add <\u0437\u0430\u043f\u0440\u043e\u0441> | <wb,ozon,ym>\n"
    "- \u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0439 \u043a\u043d\u043e\u043f\u043a\u043e\u0439 \u043d\u0438\u0436\u0435\n"
    "- \u041f\u0440\u043e\u0432\u0435\u0440\u044f\u0442\u044c, \u0443\u0434\u0430\u043b\u044f\u0442\u044c \u0438 \u0441\u0442\u0440\u043e\u0438\u0442\u044c \u0433\u0440\u0430\u0444\u0438\u043a\u0438 \u0447\u0435\u0440\u0435\u0437 \u043a\u043d\u043e\u043f\u043a\u0438\n"
    "- \u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c \u0432\u0441\u0435 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u044f \u043e\u0434\u043d\u043e\u0439 \u043a\u043d\u043e\u043f\u043a\u043e\u0439"
)


def build_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="\u041c\u043e\u0438 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u044f"), KeyboardButton(text="\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441")],
            [KeyboardButton(text="\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0432\u0441\u0435"), KeyboardButton(text="\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0435")],
            [KeyboardButton(text="\u041f\u043e\u043c\u043e\u0449\u044c")],
        ],
        resize_keyboard=True,
        input_field_placeholder="\u0412\u044b\u0431\u0435\u0440\u0438 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u0438\u043b\u0438 \u0432\u0432\u0435\u0434\u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u0443",
    )


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
    async def start_handler(message: Message) -> None:
        await message.answer(MENU_TEXT, reply_markup=build_main_menu())

    @dp.message(Command("help"))
    @dp.message(F.text == "\u041f\u043e\u043c\u043e\u0449\u044c")
    async def help_handler(message: Message) -> None:
        await start_handler(message)

    @dp.message(Command("add"))
    async def add_handler(message: Message, command: CommandObject) -> None:
        if not command.args or "|" not in command.args:
            await message.answer(
                "\u0424\u043e\u0440\u043c\u0430\u0442: /add <\u043f\u043e\u0438\u0441\u043a\u043e\u0432\u044b\u0439 \u0437\u0430\u043f\u0440\u043e\u0441> | <wb,ozon,ym>\n"
                "\u041f\u0440\u0438\u043c\u0435\u0440: /add netis nx31 | wb,ozon,ym",
                reply_markup=build_main_menu(),
            )
            return
        query, raw_marketplaces = [item.strip() for item in command.args.split("|", maxsplit=1)]
        if not query:
            await message.answer("\u041d\u0443\u0436\u0435\u043d \u0442\u0435\u043a\u0441\u0442 \u043f\u043e\u0438\u0441\u043a\u043e\u0432\u043e\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0430.", reply_markup=build_main_menu())
            return

        marketplaces = parse_marketplaces(raw_marketplaces)
        await db.add_target(message.chat.id, query, marketplaces)
        targets = await db.list_targets(message.chat.id)
        position = _find_position(targets, query, marketplaces)
        await message.answer(
            f"\u0414\u043e\u0431\u0430\u0432\u0438\u043b \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0432 \u0441\u043f\u0438\u0441\u043e\u043a.\n"
            f"\u041f\u043e\u0437\u0438\u0446\u0438\u044f: {position}\n"
            f"\u0417\u0430\u043f\u0440\u043e\u0441: {query}\n"
            f"\u041f\u043b\u043e\u0449\u0430\u0434\u043a\u0438: {', '.join(item.value for item in marketplaces)}",
            reply_markup=build_main_menu(),
        )

    @dp.message(F.text == "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441")
    async def add_hint_handler(message: Message) -> None:
        await message.answer(
            "\u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u043e\u0441\u0430:\n"
            "/add <\u043f\u043e\u0438\u0441\u043a\u043e\u0432\u044b\u0439 \u0437\u0430\u043f\u0440\u043e\u0441> | <wb,ozon,ym>\n\n"
            "\u041f\u0440\u0438\u043c\u0435\u0440:\n"
            "/add cudy wr3000s | wb,ozon,ym",
            reply_markup=build_main_menu(),
        )

    @dp.message(Command("list"))
    @dp.message(F.text == "\u041c\u043e\u0438 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u044f")
    async def list_handler(message: Message) -> None:
        await _send_targets_overview(message, db)

    @dp.message(Command("check"))
    async def check_handler(message: Message, command: CommandObject) -> None:
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _send_check_result(message, db, monitoring, target)

    @dp.message(F.text == "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0432\u0441\u0435")
    async def check_all_handler(message: Message) -> None:
        targets = await db.list_targets(message.chat.id)
        if not targets:
            await message.answer("\u0421\u043f\u0438\u0441\u043e\u043a \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0439 \u043f\u0443\u0441\u0442.", reply_markup=build_main_menu())
            return

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

    @dp.message(Command("chart"))
    async def chart_handler(message: Message, command: CommandObject) -> None:
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _send_chart(message, db, chart_service, target)

    @dp.message(Command("delete"))
    async def delete_handler(message: Message, command: CommandObject) -> None:
        target = await _resolve_target_from_text(message, command.args, db)
        if target is None:
            return
        await _delete_target(message, db, charts_dir, target)
        await _send_targets_overview(message, db)

    @dp.message(Command("clear"))
    @dp.message(F.text == "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0435")
    async def clear_handler(message: Message) -> None:
        targets = await db.list_targets(message.chat.id)
        if not targets:
            await message.answer("\u0421\u043f\u0438\u0441\u043e\u043a \u0443\u0436\u0435 \u043f\u0443\u0441\u0442.", reply_markup=build_main_menu())
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="\u0414\u0430, \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0435", callback_data="clear:confirm"),
                    InlineKeyboardButton(text="\u041e\u0442\u043c\u0435\u043d\u0430", callback_data="clear:cancel"),
                ]
            ]
        )
        await message.answer("\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0435 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u044f \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u0447\u0430\u0442\u0430?", reply_markup=keyboard)

    @dp.callback_query(F.data == "targets:refresh")
    async def refresh_targets_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await _send_targets_overview(callback.message, db)

    @dp.callback_query(F.data == "clear:cancel")
    async def clear_cancel_callback(callback: CallbackQuery) -> None:
        await callback.answer("\u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e")
        if callback.message:
            await callback.message.edit_text("\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u043e.")

    @dp.callback_query(F.data == "clear:confirm")
    async def clear_confirm_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        removed = await db.clear_targets(callback.message.chat.id)
        for file in charts_dir.glob("target_*.png"):
            file.unlink(missing_ok=True)
        await callback.message.edit_text(f"\u0423\u0434\u0430\u043b\u0438\u043b \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u044f: {removed} \u0448\u0442.")
        await _send_targets_overview(callback.message, db)

    @dp.callback_query(F.data.startswith("target:noop:"))
    async def noop_callback(callback: CallbackQuery) -> None:
        await callback.answer()

    @dp.callback_query(F.data.startswith("target:check:"))
    async def check_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer("\u0417\u0430\u043f\u0440\u043e\u0441 \u0443\u0436\u0435 \u0443\u0434\u0430\u043b\u0435\u043d.", reply_markup=build_main_menu())
            return
        await _send_check_result(callback.message, db, monitoring, target)

    @dp.callback_query(F.data.startswith("target:chart:"))
    async def chart_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer("\u0417\u0430\u043f\u0440\u043e\u0441 \u0443\u0436\u0435 \u0443\u0434\u0430\u043b\u0435\u043d.", reply_markup=build_main_menu())
            return
        await _send_chart(callback.message, db, chart_service, target)

    @dp.callback_query(F.data.startswith("target:delete:"))
    async def delete_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if not callback.message:
            return
        target = await db.get_target(int(callback.data.rsplit(":", 1)[1]), callback.message.chat.id)
        if target is None:
            await callback.message.answer("\u0417\u0430\u043f\u0440\u043e\u0441 \u0443\u0436\u0435 \u0443\u0434\u0430\u043b\u0435\u043d.", reply_markup=build_main_menu())
            return
        await _delete_target(callback.message, db, charts_dir, target)
        await _send_targets_overview(callback.message, db)

    @dp.message(F.text)
    async def fallback_handler(message: Message) -> None:
        await message.answer("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 \u043a\u043d\u043e\u043f\u043a\u0438 \u043c\u0435\u043d\u044e \u0438\u043b\u0438 /help.", reply_markup=build_main_menu())

    return dp


async def _send_targets_overview(message: Message, db: Database) -> None:
    targets = await db.list_targets(message.chat.id)
    if not targets:
        await message.answer("\u0421\u043f\u0438\u0441\u043e\u043a \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0439 \u043f\u0443\u0441\u0442.", reply_markup=build_main_menu())
        return

    lines = []
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for index, target in enumerate(targets, start=1):
        price = (
            f"{target.last_notified_price:.2f} RUB"
            if target.last_notified_price is not None
            else "\u0435\u0449\u0435 \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )
        lines.append(
            f"{index}. {target.query}\n"
            f"\u041f\u043b\u043e\u0449\u0430\u0434\u043a\u0438: {', '.join(item.value for item in target.marketplaces)}\n"
            f"\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u043c\u0438\u043d\u0438\u043c\u0443\u043c: {price}"
        )
        keyboard_rows.append([
            InlineKeyboardButton(text=f"{index}. {_short_query(target.query)}", callback_data=f"target:noop:{target.id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c", callback_data=f"target:check:{target.id}"),
            InlineKeyboardButton(text="\u0413\u0440\u0430\u0444\u0438\u043a", callback_data=f"target:chart:{target.id}"),
            InlineKeyboardButton(text="\u0423\u0434\u0430\u043b\u0438\u0442\u044c", callback_data=f"target:delete:{target.id}"),
        ])

    keyboard_rows.append([
        InlineKeyboardButton(text="\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a", callback_data="targets:refresh"),
        InlineKeyboardButton(text="\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0435", callback_data="clear:confirm"),
    ])

    await message.answer(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


async def _send_check_result(
    message: Message,
    db: Database,
    monitoring: MonitoringService,
    target: TrackTarget,
) -> None:
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
        await message.answer("\u0414\u043b\u044f \u0433\u0440\u0430\u0444\u0438\u043a\u0430 \u043d\u0443\u0436\u043d\u043e \u043c\u0438\u043d\u0438\u043c\u0443\u043c 2 \u0437\u0430\u043c\u0435\u0440\u0430.", reply_markup=build_main_menu())
        return
    image_path = chart_service.build_chart(target, snapshots)
    await message.answer_photo(FSInputFile(image_path), reply_markup=build_main_menu())


async def _delete_target(message: Message, db: Database, charts_dir: Path, target: TrackTarget) -> None:
    removed = await db.delete_target(target.id, message.chat.id)
    if not removed:
        await message.answer("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441.", reply_markup=build_main_menu())
        return
    chart_path = charts_dir / f"target_{target.id}.png"
    if chart_path.exists():
        chart_path.unlink()
    await message.answer(f"\u0423\u0434\u0430\u043b\u0438\u043b \u0437\u0430\u043f\u0440\u043e\u0441: {target.query}", reply_markup=build_main_menu())


async def _resolve_target_from_text(message: Message, raw: str | None, db: Database) -> TrackTarget | None:
    if not raw or not raw.strip().isdigit():
        await message.answer("\u041d\u0443\u0436\u0435\u043d \u043d\u043e\u043c\u0435\u0440 \u0438\u0437 \u0441\u043f\u0438\u0441\u043a\u0430, \u043d\u0430\u043f\u0440\u0438\u043c\u0435\u0440: /check 1", reply_markup=build_main_menu())
        return None
    index = int(raw.strip())
    targets = await db.list_targets(message.chat.id)
    if 1 <= index <= len(targets):
        return targets[index - 1]
    target = await db.get_target(index, message.chat.id)
    if target is not None:
        return target
    await message.answer("\u0422\u0430\u043a\u043e\u0439 \u044d\u043b\u0435\u043c\u0435\u043d\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 \u0441\u043f\u0438\u0441\u043a\u0435.", reply_markup=build_main_menu())
    return None


def _short_query(value: str, limit: int = 28) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _find_position(targets: list[TrackTarget], query: str, marketplaces: list[Marketplace]) -> int:
    for index, target in enumerate(targets, start=1):
        if target.query == query and target.marketplaces == marketplaces:
            return index
    return 1


def _format_target_report(index: int | None, target: TrackTarget, result: CheckResult | None) -> str:
    prefix = f"#{index} " if index is not None else ""
    title_line = f"<b>{escape(prefix + target.query)}</b>"
    if result is None:
        return (
            f"{title_line}\n"
            f"<i>\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0440\u0435\u043b\u0435\u0432\u0430\u043d\u0442\u043d\u044b\u0435 \u043f\u0440\u0435\u0434\u043b\u043e\u0436\u0435\u043d\u0438\u044f.</i>\n"
            f"\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u0437\u0430\u043f\u0440\u043e\u0441 \u0438\u043b\u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438 \u043f\u043e\u0437\u0436\u0435."
        )

    cheapest = result.cheapest
    summary = (
        f"\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u043c\u0438\u043d\u0438\u043c\u0443\u043c: <b>{cheapest.price:.2f} {escape(cheapest.currency)}</b> "
        f"\u043d\u0430 <b>{escape(_marketplace_label(cheapest.marketplace))}</b>"
    )

    market_lines: list[str] = []
    for marketplace in sorted(target.marketplaces, key=lambda item: item.value):
        offer = result.per_marketplace.get(marketplace)
        label = _marketplace_label(marketplace)
        if offer is not None:
            market_lines.append(
                f"- <b>{escape(label)}</b>: {offer.price:.2f} {escape(offer.currency)} "
                f"<a href=\"{escape(offer.url, quote=True)}\">\u0441\u0441\u044b\u043b\u043a\u0430</a>"
            )
            continue
        error = result.errors.get(marketplace, "\u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445")
        market_lines.append(f"- <b>{escape(label)}</b>: {escape(error)}")

    return (
        f"{title_line}\n"
        f"{summary}\n"
        f"\u0422\u043e\u0432\u0430\u0440: <a href=\"{escape(cheapest.url, quote=True)}\">{escape(cheapest.title)}</a>\n\n"
        f"<b>\u041c\u0438\u043d\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0435 \u0446\u0435\u043d\u044b \u043f\u043e \u043c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441\u0430\u043c</b>\n"
        + "\n".join(market_lines)
    )


def _marketplace_label(marketplace: Marketplace) -> str:
    labels = {
        Marketplace.WB: "Wildberries",
        Marketplace.OZON: "Ozon",
        Marketplace.YANDEX_MARKET: "Yandex Market",
    }
    return labels.get(marketplace, marketplace.value)
