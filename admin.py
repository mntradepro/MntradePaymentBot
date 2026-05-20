from __future__ import annotations

import csv
import html
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import db

router = Router()


DEFAULT_TEXTS = {
    "welcome": {
        "lv": (
            "Laipni lūgts MNtradepro VIP Treideru čatā 🚀\n\n"
            "💎 Šeit tu iegūsi piekļuvi slēgtai treideru community ar:\n\n"
            "✅ AI signāliem\n"
            "✅ Tirgus analītiku\n"
            "✅ Idejām darījumiem\n"
            "✅ Atbalstu un pieredzes apmaiņu\n"
            "✅ Papildu materiāliem un jaunumiem\n\n"
            "Izvēlies sev piemērotāko plānu un pievienojies VIP čatam 👇\n\n"
            "Atgādinājums: signāli un analītika nav finanšu konsultācija. Lēmumus par darījumiem pieņem pats."
        ),
        "en": (
            "Welcome to the MNtradepro VIP Traders Chat 🚀\n\n"
            "💎 Here you get access to a private trading community with:\n\n"
            "✅ AI signals\n"
            "✅ Market analysis\n"
            "✅ Trade ideas\n"
            "✅ Support and experience sharing\n"
            "✅ Extra materials and updates\n\n"
            "Choose the plan that fits you and join the VIP chat 👇\n\n"
            "Reminder: signals and analysis are not financial advice. You make your own trading decisions."
        ),
        "ru": (
            "Добро пожаловать в VIP чат трейдеров MNtradepro 🚀\n\n"
            "💎 Здесь ты получишь доступ к закрытому трейдерскому community с:\n\n"
            "✅ AI сигналами\n"
            "✅ Аналитикой рынка\n"
            "✅ Идеями для сделок\n"
            "✅ Поддержкой и обменом опытом\n"
            "✅ Дополнительными материалами и новостями\n\n"
            "Выбери подходящий план и присоединяйся к VIP чату 👇\n\n"
            "Напоминание: сигналы и аналитика не являются финансовой консультацией. Решения по сделкам принимаешь ты сам."
        ),
    },
    "courses_text": {
        "lv": "Izvēlies kursu, lai apskatītu detaļas un apmaksas iespējas:",
        "en": "Choose a course to see details and payment options:",
        "ru": "Выбери курс, чтобы посмотреть детали и способы оплаты:",
    },
}

DEFAULT_TEXTS.update({
    "vip_intro": {
        "lv": "💎 *Izvēlies VIP čatu:*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski piesaistīs piekļuvi pēc tava e-pasta.",
        "en": "💎 *Choose VIP chat:*\n\nPurchase happens on the website. After payment the bot will link access by your e-mail.",
        "ru": "💎 *Выбери VIP чат:*\n\nПокупка происходит на сайте. После оплаты бот автоматически привяжет доступ по твоему e-mail.",
    },
    "scanner_text": {
        "lv": "📡 *Tirgus Skaneris/AI signāli*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski iedos jaunu piekļuvi.",
        "en": "📡 *Market Scanner/AI Signals*\n\nPurchase happens on the website. After payment the bot will grant access automatically.",
        "ru": "📡 *Сканер рынка/AI сигналы*\n\nПокупка происходит на сайте. После оплаты бот автоматически выдаст доступ.",
    },
    "payment_success": {
        "lv": "✅ *Paldies! Jūsu abonements ir pagarināts.*\n\n📦 Produkts: *{name}*\n📅 Aktīvs līdz: *{expires}*",
        "en": "✅ *Thank you! Your subscription has been extended.*\n\n📦 Product: *{name}*\n📅 Active until: *{expires}*",
        "ru": "✅ *Спасибо! Ваша подписка продлена.*\n\n📦 Продукт: *{name}*\n📅 Активно до: *{expires}*",
    },
    "kick_message": {
        "lv": "😔 *Ar nožēlu paziņojam, ka šobrīd pieeja čatam Jums ir slēgta.*\n\nPriecāsimies Jūs redzēt atpakaļ.\n\nTiklīdz tiks saņemta apmaksa par abonēšanas pagarinājumu, Jums atnāks ziņa, un Jūs varēsiet iegūt jaunu linku, lai pievienotos čatam atpakaļ.",
        "en": "😔 *We are sorry to let you know that your access to the chat is currently closed.*\n\nWe will be glad to welcome you back.\n\nAs soon as payment for the subscription renewal is received, you will get a message and will be able to receive a new link to join the chat again.",
        "ru": "😔 *С сожалением сообщаем, что сейчас доступ в чат для вас закрыт.*\n\nБудем рады видеть вас снова.\n\nКак только поступит оплата за продление подписки, вам придёт сообщение, и вы сможете получить новую ссылку, чтобы снова присоединиться к чату.",
    },
    "grace_reminder": {
        "lv": "⚠️ Maksājums par abonementa pagarināšanu vēl nav saņemts.\n\nTava piekļuve beidzās: *{expires}*\nGrace periods: *{grace_days} dienas*\nAtlikušas aptuveni: *{days_left}* dienas.\n\nJa apmaksa neatnāks, bots pēc grace perioda beigām izņems tevi no čata.",
        "en": "⚠️ Payment for subscription renewal has not been received yet.\n\nYour access expired on: *{expires}*\nGrace period: *{grace_days} days*\nRoughly remaining: *{days_left}* days.\n\nIf no payment arrives, the bot will remove you from the chat after the grace period ends.",
        "ru": "⚠️ Оплата за продление подписки еще не получена.\n\nТвой доступ закончился: *{expires}*\nGrace period: *{grace_days} дней*\nОсталось примерно: *{days_left}* дней.\n\nЕсли оплата не поступит, бот удалит тебя из чата после окончания grace period.",
    },
})

TEXT_GROUPS = [
    ("welcome", "Welcome"),
    ("vip_intro", "VIP Intro"),
    ("scanner_text", "Scanner"),
    ("courses_text", "Courses"),
    ("payment_success", "Payment Success"),
    ("kick_message", "Kick Message"),
    ("grace_reminder", "Grace Reminder"),
]


class EditState(StatesGroup):
    waiting_text = State()
    waiting_price = State()
    waiting_checkout_url = State()


class FriendState(StatesGroup):
    waiting_id = State()
    waiting_remove_id = State()


class PromoState(StatesGroup):
    waiting_code = State()


class RevokeState(StatesGroup):
    waiting_id = State()


class BanState(StatesGroup):
    waiting_payload = State()


class GrantSubState(StatesGroup):
    waiting_payload = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def h(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt_dt(value, short=False) -> str:
    if not value:
        return "-"
    try:
        fmt = "%Y-%m-%d" if short else "%Y-%m-%d %H:%M"
        return datetime.fromisoformat(value).strftime(fmt)
    except Exception:
        return str(value)[:10 if short else 16]


def looks_like_email(value: str) -> bool:
    value = (value or "").strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def trim(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def setting_status(value, empty_label="empty") -> str:
    if value is None or str(value).strip() == "":
        return empty_label
    return "set"


async def checkout_effective_status(primary_key: str, fallback_key: str = None) -> str:
    primary = await db.get_setting(primary_key)
    if primary and str(primary).strip():
        return "set"
    if fallback_key:
        fallback = await db.get_setting(fallback_key)
        if fallback and str(fallback).strip():
            return "fallback"
    return "empty"


def back_kb(cb: str = "adm_main"):
    b = InlineKeyboardBuilder()
    b.button(text="Back", callback_data=cb)
    return b.as_markup()


async def effective_text(setting_prefix: str, lang: str) -> str:
    stored = await db.get_setting(f"{setting_prefix}_{lang}")
    if stored:
        return stored
    return DEFAULT_TEXTS.get(setting_prefix, {}).get(lang, "(default)")


async def render_text_group(callback: CallbackQuery, group_key: str, title: str):
    current_lv = await effective_text(group_key, "lv")
    current_en = await effective_text(group_key, "en")
    current_ru = await effective_text(group_key, "ru")
    text = (
        f"<b>{h(title)} Text</b>\n\n"
        "These are the effective texts users see right now.\n\n"
        f"LV:\n<code>{h(current_lv[:500])}</code>\n\n"
        f"EN:\n<code>{h(current_en[:500])}</code>\n\n"
        f"RU:\n<code>{h(current_ru[:500])}</code>"
    )
    b = InlineKeyboardBuilder()
    for code in ("lv", "en", "ru"):
        b.button(text=f"Edit {code.upper()}", callback_data=f"adm_text_edit_{group_key}_{code}")
    b.button(text="Reset All", callback_data=f"adm_text_reset_{group_key}")
    b.button(text="Back", callback_data="adm_texts")
    b.adjust(2, 2)
    await render(callback, text, b.as_markup())


def menu_kb():
    b = InlineKeyboardBuilder()
    for text, cb in [
        ("📊 Statistika", "adm_stats"),
        ("📈 Detalizēta", "adm_detailed_stats"),
        ("📜 Retention Logs", "adm_retention_logs"),
        ("👥 Lietotāji", "adm_users"),
        ("📩 Pending Purchases", "adm_pending_email_users"),
        ("💬 Čati", "adm_chats"),
        ("👋 Teksti", "adm_texts"),
        ("🏷️ Promo kodi", "adm_promo_menu"),
        ("💰 Mainīt cenas", "adm_edit_prices"),
        ("📤 Excel eksports", "adm_export_excel"),
        ("💾 DB Backup", "adm_backup"),
        ("🚫 Bans", "adm_bans"),
        ("🧾 Maksājumi", "adm_payments_menu"),
        ("🎁 Piešķirt abonementu", "adm_grant_sub"),
        ("⚙️ Settings", "adm_settings"),
        ("📣 Remarketing", "adm_stub"),
        ("📬 Marketing", "adm_stub"),
        ("🎟️ Giveaway", "adm_stub"),
        ("🏅 Loyalty Stats", "adm_stub"),
    ]:
        b.button(text=text, callback_data=cb)
    b.button(text="Check Chat Users", callback_data="adm_audit_chats")
    b.adjust(2)
    return b.as_markup()


def configured_chat_rows():
    return [
        ("LV VIP čats", "vip_chat_lv", config.CHAT_IDS.get("lv", config.CHAT_ID), config.CHAT_LINKS.get("lv", config.CHAT_LINK)),
        ("EN VIP čats", "vip_chat_en", config.CHAT_IDS.get("en", config.CHAT_ID), config.CHAT_LINKS.get("en", config.CHAT_LINK)),
        ("RU VIP čats", "vip_chat_ru", config.CHAT_IDS.get("ru", config.CHAT_ID), config.CHAT_LINKS.get("ru", config.CHAT_LINK)),
        ("Scanner čats", "scanner_chat", getattr(config, "SCANNER_CHAT_ID", 0), getattr(config, "SCANNER_CHAT_LINK", "")),
    ]


def managed_chat_webhook_key(item: dict) -> str:
    key = str(item.get("webhook_product_key") or "").strip()
    if key:
        return key
    chat_id = str(item.get("chat_id") or "").strip()
    return chat_id or "-"


def managed_chat_language(item: dict) -> str:
    key = managed_chat_webhook_key(item).lower()
    if key == "vip_chat_lv":
        return "LV"
    if key == "vip_chat_ru":
        return "RU"
    if key == "vip_chat_en":
        return "EN"
    if key == "scanner_chat":
        return "MULTI"
    return "-"


def subscription_products():
    return {
        "vip_chat_lv": ("VIP Chat LV", config.CHAT_IDS.get("lv", config.CHAT_ID), config.CHAT_LINKS.get("lv", config.CHAT_LINK)),
        "vip_chat_en": ("VIP Chat EN", config.CHAT_IDS.get("en", config.CHAT_ID), config.CHAT_LINKS.get("en", config.CHAT_LINK)),
        "vip_chat_ru": ("VIP Chat RU", config.CHAT_IDS.get("ru", config.CHAT_ID), config.CHAT_LINKS.get("ru", config.CHAT_LINK)),
        "scanner_chat": ("Scanner Chat", getattr(config, "SCANNER_CHAT_ID", 0), getattr(config, "SCANNER_CHAT_LINK", "")),
    }


async def audit_chat_choices(bot: Bot):
    by_chat = {}
    for label, product_key, chat_id, link in configured_chat_rows():
        if not chat_id:
            continue
        item = by_chat.setdefault(int(chat_id), {"chat_id": int(chat_id), "labels": [], "keys": [], "link": link or ""})
        item["labels"].append(label)
        item["keys"].append(product_key)
        if link and not item.get("link"):
            item["link"] = link
    for item in await db.get_managed_chats():
        chat_id = int(item.get("chat_id") or 0)
        if not chat_id:
            continue
        row = by_chat.setdefault(chat_id, {"chat_id": chat_id, "labels": [], "keys": [], "link": item.get("invite_link") or ""})
        row["labels"].append(item.get("title") or item.get("username") or str(chat_id))
        row["keys"].append(item.get("webhook_product_key") or str(chat_id))
        if item.get("invite_link") and not row.get("link"):
            row["link"] = item.get("invite_link")
    choices = []
    for row in by_chat.values():
        title = "Unknown"
        try:
            chat = await bot.get_chat(row["chat_id"])
            title = getattr(chat, "title", None) or getattr(chat, "username", None) or "OK"
        except Exception as e:
            title = str(e)[:80]
        row["title"] = title
        choices.append(row)
    choices.sort(key=lambda x: x.get("title") or str(x["chat_id"]))
    return choices


def audit_member_name(row: dict) -> str:
    username = row.get("username")
    first_name = row.get("first_name")
    if username:
        return "@" + str(username)
    if first_name:
        return str(first_name)
    return "ID " + str(row.get("user_id"))


def audit_is_friend_or_protected(row: dict) -> bool:
    status = str(row.get("status") or "").lower()
    return bool(row.get("is_friend")) or int(row.get("user_id") or 0) in config.ADMIN_IDS or status in {"administrator", "creator"}


async def refresh_audit_members(bot: Bot, chat_id: int):
    refreshed = []
    for user in await db.get_all_users_stats():
        user_id = int(user.get("user_id") or 0)
        if not user_id:
            continue
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member.status, "value", str(member.status or ""))
            if status in {"left", "kicked"}:
                await db.mark_chat_member_left(chat_id, user_id, status)
                continue
            tg_user = member.user
            await db.upsert_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                username=getattr(tg_user, "username", "") or user.get("username") or "",
                first_name=getattr(tg_user, "first_name", "") or user.get("first_name") or "",
                status=status,
                is_member=bool(getattr(member, "is_member", True)),
            )
        except Exception:
            continue
    for row in await db.get_chat_audit_members(chat_id):
        user_id = int(row.get("user_id") or 0)
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member.status, "value", str(member.status or ""))
            if status in {"left", "kicked"}:
                await db.mark_chat_member_left(chat_id, user_id, status)
                continue
            tg_user = member.user
            await db.upsert_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                username=getattr(tg_user, "username", "") or row.get("username") or "",
                first_name=getattr(tg_user, "first_name", "") or row.get("first_name") or "",
                status=status,
                is_member=bool(getattr(member, "is_member", True)),
            )
        except Exception:
            pass
    for row in await db.get_chat_audit_members(chat_id):
        if row.get("has_paid"):
            row["bucket"] = "paid"
        elif audit_is_friend_or_protected(row):
            row["bucket"] = "friend"
        else:
            row["bucket"] = "notpaid"
        refreshed.append(row)
    return refreshed


async def build_audit_report(bot: Bot, chat_id: int):
    rows = await refresh_audit_members(bot, chat_id)
    paid = [r for r in rows if r["bucket"] == "paid"]
    friends = [r for r in rows if r["bucket"] == "friend"]
    notpaid = [r for r in rows if r["bucket"] == "notpaid"]
    try:
        chat = await bot.get_chat(chat_id)
        title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat_id)
    except Exception:
        title = str(chat_id)
    try:
        tg_count = await bot.get_chat_member_count(chat_id)
    except Exception:
        tg_count = "-"
    notpaid_rows = "\n".join(
        f"- {h(audit_member_name(r))} | <code>{int(r.get('user_id') or 0)}</code> | {h(r.get('email') or '-')}"
        for r in notpaid[:15]
    ) or "-"
    paid_rows = "\n".join(
        f"- {h(audit_member_name(r))} | until {fmt_dt(r.get('paid_until'), True)}"
        for r in paid[:5]
    ) or "-"
    friend_rows = "\n".join(
        f"- {h(audit_member_name(r))}"
        for r in friends[:5]
    ) or "-"
    text = (
        f"<b>Chat user audit</b>\n"
        f"Chat: <b>{h(title)}</b>\n"
        f"TG ID: <code>{chat_id}</code>\n"
        f"Telegram member count: <b>{h(tg_count)}</b>\n"
        f"Known/scanned by bot: <b>{len(rows)}</b>\n\n"
        f"PAYED: <b>{len(paid)}</b>\n"
        f"Friends: <b>{len(friends)}</b>\n"
        f"NOTPAYED: <b>{len(notpaid)}</b>\n\n"
        f"<b>PAYED sample</b>\n{paid_rows}\n\n"
        f"<b>Friends/protected sample</b>\n{friend_rows}\n\n"
        f"<b>NOTPAYED</b>\n{notpaid_rows}\n\n"
        "Note: Telegram does not let bots export the full member list on demand. This report checks all DB users against this chat and also uses tracked chat members."
    )
    b = InlineKeyboardBuilder()
    if notpaid:
        b.button(text=f"KICK OUT ALL NOTPAYED ({len(notpaid)})", callback_data=f"adm_audit_kickall:{chat_id}")
        for row in notpaid[:20]:
            b.button(text=f"Kick {audit_member_name(row)[:24]}", callback_data=f"adm_audit_kick:{chat_id}:{int(row.get('user_id') or 0)}")
    b.button(text="Refresh", callback_data=f"adm_audit_scan:{chat_id}")
    b.button(text="Choose another chat", callback_data="adm_audit_chats")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    return text, b.as_markup(), {"paid": paid, "friends": friends, "notpaid": notpaid}


async def get_user_from_target(token: str):
    token = (token or "").strip()
    if token.lstrip("-").isdigit():
        return await db.get_user(int(token))
    return await db.get_user_by_username(token)


async def render(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(trim(text), reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        await callback.message.answer(trim(text), reply_markup=reply_markup, parse_mode="HTML")


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("*Admin Panel*", reply_markup=menu_kb(), parse_mode="Markdown")


@router.message(Command("helpadmin"))
async def admin_help(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Use /admin to open the English admin panel.")


@router.callback_query(F.data == "adm_main")
async def adm_main(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await render(callback, "<b>Admin Panel</b>", menu_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    s = await db.get_stats()
    plans = "\n".join(f"- {h(k or 'Unknown')}: <b>{v}</b>" for k, v in (s.get("by_plan") or {}).items()) or "No active plans."
    text = (
        "<b>Stats</b>\n\n"
        f"Total users: <b>{s.get('total_users', 0)}</b>\n"
        f"Active users: <b>{s.get('active', 0)}</b>\n"
        f"Never bought: <b>{s.get('never_bought', 0)}</b>\n"
        f"Expired: <b>{s.get('expired', 0)}</b>\n"
        f"Total revenue: <b>{s.get('total_revenue', 0):.2f}</b> USDT\n\n"
        f"<b>Active by plan</b>\n{plans}"
    )
    await render(callback, text, back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_detailed_stats")
async def adm_detailed_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    s = await db.get_detailed_stats()
    week = "\n".join(f"- {h(x['date'])}: {x['revenue']:.2f} USDT ({x['count']})" for x in s.get("week_data", [])) or "No data."
    top = "\n".join(f"- {h(x.get('plan_name') or 'Unknown')}: {x.get('cnt', 0)} / {x.get('rev', 0):.2f} USDT" for x in s.get("top_plans", [])[:10]) or "No plans."
    text = (
        "<b>Detailed Stats</b>\n\n"
        f"Unique buyers: <b>{s.get('unique_buyers', 0)}</b>\n"
        f"Repeat buyers: <b>{s.get('repeat_buyers', 0)}</b>\n"
        f"One-time buyers: <b>{s.get('one_time_buyers', 0)}</b>\n"
        f"Today revenue: <b>{s.get('today_revenue', 0):.2f}</b> USDT ({s.get('today_purchases', 0)} purchases)\n"
        f"Month revenue: <b>{s.get('month_revenue', 0):.2f}</b> USDT ({s.get('month_purchases', 0)} purchases)\n"
        f"Year revenue: <b>{s.get('year_revenue', 0):.2f}</b> USDT\n"
        f"ARPU: <b>{s.get('arpu', 0):.2f}</b> | Conversion: <b>{s.get('conversion', 0):.2f}%</b>\n\n"
        f"<b>Last 7 days</b>\n{week}\n\n<b>Top plans</b>\n{top}"
    )
    await render(callback, text, back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_retention_logs")
async def adm_retention_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    stats = await db.get_bot_event_stats()
    events = await db.get_recent_bot_events(20)
    rows = []
    for event in events:
        uname = "@" + event["username"] if event.get("username") else str(event.get("user_id") or "-")
        rows.append(f"- {h(event.get('event_type'))} | {h(uname)} | {fmt_dt(event.get('created_at'))}")
    recent = "\n".join(rows) or "No events."
    text = (
        "<b>Retention Logs</b>\n\n"
        f"Reminders today: <b>{stats.get('reminders_today', 0)}</b>\n"
        f"Reminders 7d: <b>{stats.get('reminders_7d', 0)}</b>\n"
        f"Expiry notices today: <b>{stats.get('expiry_today_notices', 0)}</b>\n"
        f"Kicked today: <b>{stats.get('kicked_today', 0)}</b>\n"
        f"Kicked 7d: <b>{stats.get('kicked_7d', 0)}</b>\n\n"
        f"<b>Recent events</b>\n{recent}"
    )
    await render(callback, text, back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    active = await db.get_users_with_active_subscriptions()
    registered = await db.get_registered_users()
    friends = await db.get_all_friends()
    friend_emails = await db.get_all_friend_emails()
    pending_email_subs = await db.get_all_pending_email_subscriptions()
    b = InlineKeyboardBuilder()
    b.button(text="ALL registered users", callback_data="adm_users_list_registered")
    b.button(text="ALL payed users", callback_data="adm_users_list_paid")
    b.button(text="ALL friends", callback_data="adm_users_list_friends")
    b.button(text="Add Friend", callback_data="adm_add_friend")
    b.button(text="Remove Friend", callback_data="adm_remove_friend")
    b.button(text="Revoke Subscription", callback_data="adm_revoke_sub")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    text = (
        "<b>Users overview</b>\n\n"
        f"Registered bot users: <b>{len(registered)}</b>\n"
        f"Active subscribers: <b>{len(active)}</b>\n"
        f"Friends by TG: <b>{len(friends)}</b>\n"
        f"Friend e-mails: <b>{len(friend_emails)}</b>\n"
        f"Pending paid e-mails without TG: <b>{len(pending_email_subs)}</b>\n\n"
        "Registered means the user linked an e-mail in the bot. It does not mean they paid."
    )
    await render(callback, text, b.as_markup())
    await callback.answer()


def user_label(row: dict) -> str:
    if row.get("username"):
        return "@" + str(row["username"])
    return str(row.get("user_id") or "-")


async def send_long_admin_list(message: Message, title: str, rows: list[str]):
    if not rows:
        await message.answer(f"<b>{h(title)}</b>\n\n-", parse_mode="HTML")
        return
    header = f"<b>{h(title)} ({len(rows)})</b>\n\n"
    chunk = header
    for index, row in enumerate(rows, 1):
        line = f"{index}. {row}\n"
        if len(chunk) + len(line) > 3600:
            await message.answer(chunk, parse_mode="HTML")
            chunk = ""
        chunk += line
    if chunk:
        await message.answer(chunk, parse_mode="HTML")


@router.callback_query(F.data == "adm_users_list_registered")
async def adm_users_list_registered(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    users = await db.get_registered_users()
    active = await db.get_users_with_active_subscriptions()
    active_ids = {int(u.get("user_id") or 0) for u in active}
    rows = [
        (
            f"{h(user_label(u))} | TG: <code>{int(u.get('user_id') or 0)}</code> | "
            f"email: <code>{h(u.get('email') or '-')}</code> | "
            f"reg: {fmt_dt(u.get('email_registered_at') or u.get('created_at'), True)} | "
            f"sub: {'active' if int(u.get('user_id') or 0) in active_ids else 'none'}"
        )
        for u in users
    ]
    await callback.answer("Sending registered users...")
    await send_long_admin_list(callback.message, "ALL registered bot users", rows)


@router.callback_query(F.data == "adm_users_list_paid")
async def adm_users_list_paid(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    users = await db.get_users_with_active_subscriptions()
    rows = []
    for u in users:
        subs = await db.get_active_user_subscriptions(u["user_id"])
        products = ", ".join(str(s.get("product_key") or "-") for s in subs) or "-"
        rows.append(
            f"{h(user_label(u))} | TG: <code>{int(u.get('user_id') or 0)}</code> | "
            f"email: <code>{h(u.get('email') or '-')}</code> | "
            f"subs: {int(u.get('active_subscription_count') or 0)} | "
            f"products: {h(products)} | nearest exp: {fmt_dt(u.get('nearest_subscription_expires_at'), True)}"
        )
    await callback.answer("Sending payed users...")
    await send_long_admin_list(callback.message, "ALL payed users", rows)


@router.callback_query(F.data == "adm_users_list_friends")
async def adm_users_list_friends(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    friends = await db.get_all_friends()
    friend_emails = await db.get_all_friend_emails()
    rows = [
        f"{h(user_label(u))} | TG: <code>{int(u.get('user_id') or 0)}</code> | email: <code>{h(u.get('email') or '-')}</code>"
        for u in friends
    ]
    rows.extend(f"email whitelist: <code>{h(x.get('email') or '-')}</code>" for x in friend_emails)
    await callback.answer("Sending friends...")
    await send_long_admin_list(callback.message, "ALL friends", rows)


@router.callback_query(F.data.startswith("adm_user_view_"))
async def adm_user_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    user = await db.get_user(int(callback.data.replace("adm_user_view_", "")))
    if not user:
        await callback.answer("User not found", show_alert=True)
        return
    subs = await db.get_active_user_subscriptions(user["user_id"])
    is_active_now = bool(subs)
    rows = "\n\n".join(
        (
            f"- <b>{h(s.get('product_name') or s.get('product_key') or 'Subscription')}</b>\n"
            f"  key: <code>{h(s.get('product_key') or '-')}</code>\n"
            f"  exp: {fmt_dt(s.get('expires_at'), True)}\n"
            f"  chat_id: <code>{h(str(s.get('chat_id', 0) or 0))}</code>\n"
            f"  chat_link: <code>{h((s.get('chat_link') or '-')[:120])}</code>"
        )
        for s in subs
    ) or "None"
    text = (
        f"<b>User {user['user_id']}</b>\n\n"
        f"Username: {h('@' + user['username']) if user.get('username') else '-'}\n"
        f"Email: {h(user.get('email') or '-')}\n"
        f"Language: {h(user.get('lang') or '-')}\n"
        f"Active now: <b>{'Yes' if is_active_now else 'No'}</b>\n"
        f"Friend: <b>{'Yes' if user.get('is_friend') else 'No'}</b>\n"
        f"Last seen: {fmt_dt(user.get('last_seen_at'))}\n\n"
        f"<b>Friend status</b>\n{'Listed in friends' if user.get('is_friend') else 'Not in friends'}\n\n"
        f"<b>Active subscriptions</b>\n{rows}"
    )
    await render(callback, text, back_kb("adm_users"))
    await callback.answer()


@router.callback_query(F.data == "adm_pending_email_users")
async def adm_pending_email_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    rows = await db.get_all_pending_email_subscriptions()
    uniq = len({(x.get("email") or "").lower() for x in rows if x.get("email")})
    text_rows = "\n\n".join(
        f"<b>{h(x.get('email') or '-')}</b>\n"
        f"Product: {h(x.get('product_key') or '-')}\n"
        f"Payment: {h(x.get('payment_system') or '-')}\n"
        f"Amount: {float(x.get('amount_usdt') or 0):.2f}\n"
        f"Bought: {fmt_dt(x.get('activated_at'))}\n"
        f"Active until: {fmt_dt(x.get('expires_at'), True)}"
        for x in rows[:25]
    ) or "No pending purchases."
    text = f"<b>Purchases without Telegram account</b>\n\nUnique e-mails: <b>{uniq}</b>\nActive pending purchases: <b>{len(rows)}</b>\n\n{text_rows}"
    await render(callback, text, back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_chats")
async def adm_chats(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    counts = await db.get_active_subscription_counts_by_chat()
    counts_by_key = await db.get_active_subscription_counts_by_product_key()
    managed = await db.get_managed_chats()
    managed_lines = []
    b = InlineKeyboardBuilder()
    if managed:
        for item in managed[:12]:
            chat_id = int(item.get("chat_id") or 0)
            hook_id = managed_chat_webhook_key(item)
            hook_count = counts_by_key.get(hook_id.lower(), 0)
            active_count = hook_count or counts.get(chat_id, 0)
            joined, title = "No", str(item.get("title") or item.get("username") or chat_id or "Unknown")
            try:
                chat = await bot.get_chat(chat_id)
                joined = "Yes"
                title = getattr(chat, "title", None) or getattr(chat, "username", None) or title
            except Exception as e:
                title = str(item.get("title") or title or str(e)[:80])
            managed_lines.append(
                f"<b>{h(str(item.get('title') or item.get('username') or chat_id))}</b>\n"
                f"ID: <code>{chat_id}</code>\n"
                f"Hook ID: <code>{h(hook_id)}</code>\n"
                f"Valoda: <b>{h(managed_chat_language(item))}</b>\n"
                f"Bot joined: <b>{joined}</b>\n"
                f"Chat: {h(title)}\n"
                f"Active subs: <b>{active_count}</b>\n"
                f"Link: <code>{h(item.get('invite_link') or '-')}</code>"
            )
            b.button(text=f"Delete {chat_id}", callback_data=f"adm_chat_delete_{chat_id}")
        b.button(text="Delete All Managed Chats", callback_data="adm_chat_delete_all")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    await render(
        callback,
        "<b>Managed chat DB</b>\n\n"
        + ("\n\n".join(managed_lines) or "No managed chats in DB.\n\nUse /STARTPAYMENT inside a target chat to add it here."),
        b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_chat_delete_") & ~F.data.startswith("adm_chat_delete_confirm_"))
async def adm_chat_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    chat_id = callback.data.replace("adm_chat_delete_", "")
    text = (
        "<b>Delete managed chat?</b>\n\n"
        f"Chat ID: <code>{h(chat_id)}</code>\n\n"
        "This removes the chat from the managed chat DB only. Configured .env chats will stay unchanged."
    )
    b = InlineKeyboardBuilder()
    b.button(text="Yes, delete", callback_data=f"adm_chat_delete_confirm_{chat_id}")
    b.button(text="Cancel", callback_data="adm_chats")
    b.adjust(1)
    await render(callback, text, b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("adm_chat_delete_confirm_"))
async def adm_chat_delete_confirm(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    chat_id_raw = callback.data.replace("adm_chat_delete_confirm_", "")
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        await callback.answer("Invalid chat id", show_alert=True)
        return
    await db.delete_managed_chat(chat_id)
    await callback.answer("Managed chat deleted")
    await adm_chats(callback, bot)


@router.callback_query(F.data == "adm_chat_delete_all")
async def adm_chat_delete_all(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "<b>Delete all managed chats?</b>\n\n"
        "This will clear the managed chat DB list and keep only configured .env chats.\n\n"
        "Are you sure?"
    )
    b = InlineKeyboardBuilder()
    b.button(text="Yes, delete all", callback_data="adm_chat_delete_all_confirm")
    b.button(text="Cancel", callback_data="adm_chats")
    b.adjust(1)
    await render(callback, text, b.as_markup())
    await callback.answer()


@router.callback_query(F.data == "adm_chat_delete_all_confirm")
async def adm_chat_delete_all_confirm(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    await db.delete_all_managed_chats()
    await callback.answer("All managed chats deleted")
    await adm_chats(callback, bot)


@router.callback_query(F.data == "adm_audit_chats")
async def adm_audit_chats(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    choices = await audit_chat_choices(bot)
    b = InlineKeyboardBuilder()
    for row in choices:
        label = f"{row.get('title') or row['chat_id']} | {', '.join(row.get('keys') or [])}"
        b.button(text=label[:60], callback_data=f"adm_audit_scan:{row['chat_id']}")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    await render(
        callback,
        "<b>Check chat users</b>\n\nChoose which chat to scan.\n\n"
        "The scan compares known Telegram chat members against active subscriptions and friends.",
        b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_audit_scan:"))
async def adm_audit_scan(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Scanning chat users...")
    text, kb, _ = await build_audit_report(bot, chat_id)
    await render(callback, text, kb)


async def kick_audit_user(bot: Bot, chat_id: int, user_id: int) -> bool:
    rows = await refresh_audit_members(bot, chat_id)
    target = next((r for r in rows if int(r.get("user_id") or 0) == user_id), None)
    if not target or target.get("bucket") != "notpaid":
        return False
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        await db.mark_chat_member_left(chat_id, user_id, "kicked_by_audit")
        await db.log_bot_event("audit_kick", user_id, meta=f"chat_id={chat_id}")
        return True
    except Exception:
        return False


@router.callback_query(F.data.startswith("adm_audit_kick:"))
async def adm_audit_kick(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    _, chat_raw, user_raw = callback.data.split(":", 2)
    chat_id = int(chat_raw)
    user_id = int(user_raw)
    ok = await kick_audit_user(bot, chat_id, user_id)
    await callback.answer("Kicked" if ok else "Not kicked: user is paid/friend/admin or no longer in chat", show_alert=not ok)
    text, kb, _ = await build_audit_report(bot, chat_id)
    await render(callback, text, kb)


@router.callback_query(F.data.startswith("adm_audit_kickall:"))
async def adm_audit_kickall(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Kicking NOTPAYED users...")
    _, _, buckets = await build_audit_report(bot, chat_id)
    kicked = 0
    failed = 0
    for row in buckets["notpaid"]:
        ok = await kick_audit_user(bot, chat_id, int(row.get("user_id") or 0))
        if ok:
            kicked += 1
        else:
            failed += 1
    text, kb, _ = await build_audit_report(bot, chat_id)
    await render(callback, f"<b>Kick all finished</b>\nKicked: <b>{kicked}</b>\nSkipped/failed: <b>{failed}</b>\n\n{text}", kb)


@router.callback_query(F.data == "adm_edit_welcome")
async def adm_edit_welcome(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await render_text_group(callback, "welcome", "Welcome")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_welcome_"))
async def adm_welcome_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    code = callback.data.replace("adm_welcome_", "")
    if code == "reset":
        for lang in ("lv", "en", "ru"):
            await db.set_setting(f"welcome_{lang}", "")
        await callback.answer("Welcome texts reset")
        await adm_edit_welcome(callback)
        return
    await state.set_state(EditState.waiting_text)
    await state.update_data(edit_key=f"welcome_{code}", return_cb="adm_edit_welcome")
    current = await effective_text("welcome", code)
    await render(
        callback,
        f"<b>Edit welcome text {code.upper()}</b>\n\n"
        f"Current effective text:\n<code>{h(current[:1600])}</code>\n\n"
        f"Send the new text in your next message.",
        back_kb("adm_edit_welcome"),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_edit_courses_text")
async def adm_edit_courses_text(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await render_text_group(callback, "courses_text", "Courses")
    await callback.answer()


@router.callback_query(F.data == "adm_texts")
async def adm_texts(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    lines = []
    for key, title in TEXT_GROUPS:
        lines.append(f"• <b>{h(title)}</b> — setting prefix: <code>{h(key)}</code>")
    b = InlineKeyboardBuilder()
    for key, title in TEXT_GROUPS:
        b.button(text=title, callback_data=f"adm_text_group_{key}")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2)
    await render(
        callback,
        "<b>Texts</b>\n\nChoose which user-facing text block you want to view or edit.\n\n" + "\n".join(lines),
        b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_text_group_"))
async def adm_text_group(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    group_key = callback.data.replace("adm_text_group_", "")
    title = next((title for key, title in TEXT_GROUPS if key == group_key), group_key)
    await render_text_group(callback, group_key, title)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_text_reset_"))
async def adm_text_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    group_key = callback.data.replace("adm_text_reset_", "")
    for lang in ("lv", "en", "ru"):
        await db.set_setting(f"{group_key}_{lang}", "")
    title = next((title for key, title in TEXT_GROUPS if key == group_key), group_key)
    await callback.answer(f"{title} texts reset")
    await render_text_group(callback, group_key, title)


@router.callback_query(F.data.startswith("adm_text_edit_"))
async def adm_text_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    payload = callback.data.replace("adm_text_edit_", "")
    group_key, code = payload.rsplit("_", 1)
    title = next((title for key, title in TEXT_GROUPS if key == group_key), group_key)
    await state.set_state(EditState.waiting_text)
    await state.update_data(edit_key=f"{group_key}_{code}", return_cb=f"adm_text_group_{group_key}")
    current = await effective_text(group_key, code)
    await render(
        callback,
        f"<b>Edit {h(title)} text {code.upper()}</b>\n\n"
        f"Current effective text:\n<code>{h(current[:1600])}</code>\n\n"
        f"Send the new text in your next message.",
        back_kb(f"adm_text_group_{group_key}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_courses_"))
async def adm_courses_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    code = callback.data.replace("adm_courses_", "")
    if code == "reset":
        for lang in ("lv", "en", "ru"):
            await db.set_setting(f"courses_text_{lang}", "")
        await callback.answer("Courses texts reset")
        await adm_edit_courses_text(callback)
        return
    await state.set_state(EditState.waiting_text)
    await state.update_data(edit_key=f"courses_text_{code}", return_cb="adm_edit_courses_text")
    current = await effective_text("courses_text", code)
    await render(
        callback,
        f"<b>Edit courses text {code.upper()}</b>\n\n"
        f"Current effective text:\n<code>{h(current[:1600])}</code>\n\n"
        f"Send the new text in your next message.",
        back_kb("adm_edit_courses_text"),
    )
    await callback.answer()


@router.message(EditState.waiting_text)
async def save_text_setting(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    await db.set_setting(data["edit_key"], message.text or "")
    return_cb = data.get("return_cb", "adm_main")
    await state.clear()
    await message.answer(f"Saved `{data['edit_key']}`", parse_mode="Markdown", reply_markup=back_kb(return_cb))


@router.callback_query(F.data == "adm_promo_menu")
async def adm_promo_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promos = await db.get_all_promo_codes()
    rows = "\n".join(
        f"- <b>{h(p.get('code'))}</b> | {p.get('discount_percent', 0)}% | plan: {h(p.get('plan_key') or 'any')} | used: {p.get('used_count', 0)} | max: {p.get('max_uses', 0)} | exp: {fmt_dt(p.get('expires_at'), True)}"
        for p in promos[:12]
    ) or "No promo codes."
    b = InlineKeyboardBuilder()
    b.button(text="Create Promo", callback_data="adm_promo_create")
    for p in promos[:8]:
        b.button(text=f"Delete {p.get('code')}", callback_data=f"adm_promo_delete_{p.get('code')}")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    await render(callback, f"<b>Promo Codes</b>\n\n{rows}", b.as_markup())
    await callback.answer()


@router.callback_query(F.data == "adm_promo_create")
async def adm_promo_create(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(PromoState.waiting_code)
    await render(callback, "<b>Create promo</b>\n\nSend:\n<code>CODE DISCOUNT [PLAN_KEY] [MAX_USES] [YYYY-MM-DD]</code>", back_kb("adm_promo_menu"))
    await callback.answer()


@router.message(PromoState.waiting_code)
async def save_promo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer("Invalid format.", reply_markup=back_kb("adm_promo_menu"))
        return
    try:
        discount = int(parts[1])
    except ValueError:
        await message.answer("Discount must be a whole number.", reply_markup=back_kb("adm_promo_menu"))
        return
    if discount <= 0 or discount > 100:
        await message.answer("Discount must be between 1 and 100.", reply_markup=back_kb("adm_promo_menu"))
        return
    code = parts[0].upper()
    plan_key = parts[2] if len(parts) > 2 else None
    if len(parts) > 3:
        try:
            max_uses = int(parts[3])
        except ValueError:
            await message.answer("Max uses must be a whole number.", reply_markup=back_kb("adm_promo_menu"))
            return
        if max_uses < 0:
            await message.answer("Max uses cannot be negative.", reply_markup=back_kb("adm_promo_menu"))
            return
    else:
        max_uses = 0
    expires_at = None
    if len(parts) > 4:
        try:
            expires_at = datetime.strptime(parts[4], "%Y-%m-%d").strftime("%Y-%m-%dT23:59:59")
        except ValueError:
            await message.answer("Expiry date must be a real date in YYYY-MM-DD format.", reply_markup=back_kb("adm_promo_menu"))
            return
    await db.create_promo_code(code, discount, plan_key=plan_key, max_uses=max_uses, expires_at=expires_at)
    await state.clear()
    await message.answer(f"Promo `{code}` created.", parse_mode="Markdown", reply_markup=back_kb("adm_promo_menu"))


@router.callback_query(F.data.startswith("adm_promo_delete_"))
async def delete_promo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    code = callback.data.replace("adm_promo_delete_", "").upper()
    await db.delete_promo_code(code)
    await callback.answer(f"Deleted {code}")
    await adm_promo_menu(callback)


def checkout_link_labels():
    return {
        "checkout_url_lv": "VIP chat button - Latvian",
        "checkout_url_en": "VIP chat button - English",
        "checkout_url_ru": "VIP chat button - Russian",
        "checkout_url_scanner_chat": "PRO Market Scanner/AI Signals button - fallback",
        "checkout_url_scanner_chat_lv": "PRO Market Scanner/AI Signals button - Latvian",
        "checkout_url_scanner_chat_en": "PRO Market Scanner/AI Signals button - English",
        "checkout_url_scanner_chat_ru": "PRO Market Scanner/AI Signals button - Russian",
        "course_checkout_url_mini_lv": "Mini course checkout button - Latvian course",
        "course_checkout_url_mini_en": "Mini course checkout button - English course",
        "course_checkout_url_mini_ru": "Mini course checkout button - Russian course",
        "course_checkout_url_basic_lv": "Basic course checkout button - Latvian course",
        "course_checkout_url_basic_en": "Basic course checkout button - English course",
        "course_checkout_url_basic_ru": "Basic course checkout button - Russian course",
        "course_checkout_url_full_lv": "Full course checkout button - Latvian course",
        "course_checkout_url_full_en": "Full course checkout button - English course",
        "course_checkout_url_full_ru": "Full course checkout button - Russian course",
        "course_checkout_url_autotrading_lv": "Autotrading course checkout button - Latvian course",
        "course_checkout_url_autotrading_en": "Autotrading course checkout button - English course",
        "course_checkout_url_autotrading_ru": "Autotrading course checkout button - Russian course",
        "course_checkout_url_vip_lv": "VIP mentoring course checkout button - Latvian course",
        "course_checkout_url_vip_en": "VIP mentoring course checkout button - English course",
        "course_checkout_url_vip_ru": "VIP mentoring course checkout button - Russian course",
    }


async def build_checkout_links_panel(prefix: str = ""):
    labels = checkout_link_labels()
    rows = []
    for key in (
        "checkout_url_lv",
        "checkout_url_en",
        "checkout_url_ru",
        "checkout_url_scanner_chat_lv",
        "checkout_url_scanner_chat_en",
        "checkout_url_scanner_chat_ru",
        "checkout_url_scanner_chat",
    ):
        fallback_key = "checkout_url_scanner_chat" if key.startswith("checkout_url_scanner_chat_") else None
        rows.append(f"<b>{h(labels.get(key, key))}</b>: <code>{h(await checkout_effective_status(key, fallback_key))}</code>")
    for course_key in config.COURSES.keys():
        for lang_code in ("lv", "en", "ru"):
            checkout_key = f"course_checkout_url_{course_key}_{lang_code}"
            fallback_key = f"course_checkout_url_{course_key}"
            rows.append(f"<b>{h(labels.get(checkout_key, checkout_key))}</b>: <code>{h(await checkout_effective_status(checkout_key, fallback_key))}</code>")
    b = InlineKeyboardBuilder()
    b.button(text="VIP button LV", callback_data="adm_link_checkout_url_lv")
    b.button(text="VIP button EN", callback_data="adm_link_checkout_url_en")
    b.button(text="VIP button RU", callback_data="adm_link_checkout_url_ru")
    b.button(text="Scanner LV", callback_data="adm_link_checkout_url_scanner_chat_lv")
    b.button(text="Scanner EN", callback_data="adm_link_checkout_url_scanner_chat_en")
    b.button(text="Scanner RU", callback_data="adm_link_checkout_url_scanner_chat_ru")
    b.button(text="Mini checkout LV", callback_data="adm_link_course_checkout_url_mini_lv")
    b.button(text="Mini checkout EN", callback_data="adm_link_course_checkout_url_mini_en")
    b.button(text="Mini checkout RU", callback_data="adm_link_course_checkout_url_mini_ru")
    b.button(text="Basic checkout LV", callback_data="adm_link_course_checkout_url_basic_lv")
    b.button(text="Basic checkout EN", callback_data="adm_link_course_checkout_url_basic_en")
    b.button(text="Basic checkout RU", callback_data="adm_link_course_checkout_url_basic_ru")
    b.button(text="Full checkout LV", callback_data="adm_link_course_checkout_url_full_lv")
    b.button(text="Full checkout EN", callback_data="adm_link_course_checkout_url_full_en")
    b.button(text="Full checkout RU", callback_data="adm_link_course_checkout_url_full_ru")
    b.button(text="Autotrading checkout LV", callback_data="adm_link_course_checkout_url_autotrading_lv")
    b.button(text="Autotrading checkout EN", callback_data="adm_link_course_checkout_url_autotrading_en")
    b.button(text="Autotrading checkout RU", callback_data="adm_link_course_checkout_url_autotrading_ru")
    b.button(text="VIP mentoring checkout LV", callback_data="adm_link_course_checkout_url_vip_lv")
    b.button(text="VIP mentoring checkout EN", callback_data="adm_link_course_checkout_url_vip_en")
    b.button(text="VIP mentoring checkout RU", callback_data="adm_link_course_checkout_url_vip_ru")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2)
    text = (
        "<b>Checkout links</b>\n\n"
        "Status shows whether a checkout URL is saved. Open a button to view or replace the full URL.\n\n"
        + "\n".join(rows)
    )
    if prefix:
        text = prefix + "\n\n" + text
    return text, b.as_markup()


@router.callback_query(F.data == "adm_edit_prices")
async def adm_edit_prices(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text, kb = await build_checkout_links_panel()
    await render(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_link_"))
async def adm_link_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.replace("adm_link_", "")
    labels = checkout_link_labels()
    await state.set_state(EditState.waiting_checkout_url)
    await state.update_data(edit_key=key)
    await render(
        callback,
        f"<b>Edit URL</b>\n\n"
        f"Product/button: <b>{h(labels.get(key, key))}</b>\n"
        f"Setting key: <code>{h(key)}</code>\n"
        f"Current: <code>{h(await db.get_setting(key) or '(empty)')}</code>\n\n"
        f"Send the new checkout URL for this exact button.",
        back_kb("adm_edit_prices"),
    )
    await callback.answer()


@router.message(EditState.waiting_checkout_url)
async def save_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    await db.set_setting(data["edit_key"], (message.text or "").strip())
    await state.clear()
    text, kb = await build_checkout_links_panel(f"<b>Saved</b> <code>{h(data['edit_key'])}</code>")
    await message.answer(trim(text), parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("adm_price_"))
async def adm_price_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.replace("adm_price_", "")
    labels = {
        "price_monthly": "VIP 1 month price",
        "course_price_mini": "Mini course price",
        "course_price_basic": "Basic course price",
        "course_price_full": "Full course price",
        "course_price_autotrading": "Autotrading course price",
        "course_price_vip": "VIP mentoring course price",
    }
    await state.set_state(EditState.waiting_price)
    await state.update_data(edit_key=key)
    await render(
        callback,
        f"<b>Edit price</b>\n\n"
        f"Product: <b>{h(labels.get(key, key))}</b>\n"
        f"Setting key: <code>{h(key)}</code>\n"
        f"Current: <code>{h(await db.get_setting(key) or '(default)')}</code>\n\n"
        f"Send the new numeric price.",
        back_kb("adm_edit_prices"),
    )
    await callback.answer()


@router.message(EditState.waiting_price)
async def save_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip().replace(",", ".")
    try:
        float(raw)
    except ValueError:
        await message.answer("Price must be numeric.", reply_markup=back_kb("adm_edit_prices"))
        return
    data = await state.get_data()
    await db.set_setting(data["edit_key"], raw)
    await state.clear()
    text, kb = await build_checkout_links_panel(f"<b>Saved</b> <code>{h(data['edit_key'])}</code> = <code>{h(raw)}</code>")
    await message.answer(trim(text), parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "adm_export_excel")
async def adm_export_excel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    rows = await db.get_all_users_for_export()
    if not rows:
        await callback.answer("No users to export", show_alert=True)
        return
    with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        headers = sorted({key for row in rows for key in row.keys()})
        writer = csv.writer(tmp)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row.get(hh, "") for hh in headers])
        path = tmp.name
    try:
        await callback.message.answer_document(FSInputFile(path), caption="Users export CSV")
        await callback.answer("CSV exported")
    finally:
        Path(path).unlink(missing_ok=True)


@router.callback_query(F.data == "adm_backup")
async def adm_backup(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    backup_path = await db.backup_db(str(Path(db.db_path).resolve().parent / "backup"))
    await callback.message.answer_document(FSInputFile(backup_path), caption="Database backup")
    await callback.answer("Backup created")


@router.callback_query(F.data == "adm_bans")
async def adm_bans(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    banned = await db.get_banned_users()
    rows = "\n".join(
        f"- {h('@' + u['username']) if u.get('username') else u['user_id']} | {h(u.get('reason') or '-')} | {fmt_dt(u.get('banned_at'))}"
        for u in banned[:20]
    ) or "No banned users."
    b = InlineKeyboardBuilder()
    b.button(text="Ban User", callback_data="adm_ban_user")
    for u in banned[:8]:
        b.button(text=f"Unban {u['user_id']}", callback_data=f"adm_unban_{u['user_id']}")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    await render(callback, f"<b>Banned users</b>\n\n{rows}", b.as_markup())
    await callback.answer()


@router.callback_query(F.data == "adm_ban_user")
async def adm_ban_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(BanState.waiting_payload)
    await render(callback, "<b>Ban user</b>\n\nSend:\n<code>USER_ID_OR_USERNAME reason text</code>", back_kb("adm_bans"))
    await callback.answer()


@router.message(BanState.waiting_payload)
async def save_ban(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if " " not in raw:
        await message.answer("Need target and reason.", reply_markup=back_kb("adm_bans"))
        return
    target, reason = raw.split(" ", 1)
    user = await get_user_from_target(target)
    if not user:
        await message.answer("User not found.", reply_markup=back_kb("adm_bans"))
        return
    await db.ban_user(user["user_id"], reason.strip(), message.from_user.id)
    await state.clear()
    await message.answer(f"Banned `{user['user_id']}`", parse_mode="Markdown", reply_markup=back_kb("adm_bans"))


@router.callback_query(F.data.startswith("adm_unban_"))
async def adm_unban(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await db.unban_user(int(callback.data.replace("adm_unban_", "")))
    await callback.answer("User unbanned")
    await adm_bans(callback)


@router.callback_query(F.data == "adm_payments_menu")
async def adm_payments_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    pending_email = await db.get_all_pending_email_subscriptions()
    pending_withdrawals = await db.get_pending_withdrawals()
    webhook_ready = bool(config.WEBHOOK_SECRET)
    text = (
        "<b>Website payments</b>\n\n"
        "Bot-side payment checking is disabled. Purchases are controlled by the website checkout webhook.\n\n"
        f"Webhook secret set: <b>{'Yes' if webhook_ready else 'No'}</b>\n"
        f"Webhook path: <code>{h(config.WEBHOOK_PATH)}</code>\n"
        f"Pending purchases without TG: <b>{len(pending_email)}</b>\n"
        f"Pending withdrawals: <b>{len(pending_withdrawals)}</b>\n\n"
        "Use Pending Purchases to see paid e-mails that have not pressed /start yet."
    )
    b = InlineKeyboardBuilder()
    b.button(text="Pending Purchases", callback_data="adm_pending_email_users")
    b.button(text="Checkout Links", callback_data="adm_edit_prices")
    b.button(text="Settings", callback_data="adm_settings")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(1)
    await render(callback, text, b.as_markup())
    await callback.answer()


@router.callback_query(F.data == "adm_settings")
async def adm_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "<b>Settings</b>\n\n"
        f"Support contact: <code>{h(config.SUPPORT_CONTACT)}</code>\n"
        f"Webhook path: <code>{h(config.WEBHOOK_PATH)}</code>\n"
        f"Webhook secret set: <b>{'Yes' if bool(config.WEBHOOK_SECRET) else 'No'}</b>\n"
        f"DB path: <code>{h(db.db_path)}</code>\n"
        f"Admin ids: <code>{h(', '.join(str(x) for x in config.ADMIN_IDS))}</code>"
    )
    await render(callback, text, back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_add_friend")
async def adm_add_friend(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(FriendState.waiting_id)
    await render(callback, "<b>Add friend</b>\n\nSend a Telegram user id, @username, or e-mail.", back_kb("adm_users"))
    await callback.answer()


@router.message(FriendState.waiting_id)
async def save_friend_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw_target = (message.text or "").strip()
    if looks_like_email(raw_target):
        affected = await db.add_friend_email(raw_target, message.from_user.id)
        user = await db.get_user_by_email(raw_target)
        await state.clear()
        if user:
            await message.answer(
                f"Friend e-mail added and user marked friend: `{raw_target.lower()}` -> `{user['user_id']}`",
                parse_mode="Markdown",
                reply_markup=back_kb("adm_users"),
            )
        else:
            await message.answer(
                f"Friend e-mail added: `{raw_target.lower()}`\nExisting users updated: `{affected}`\nWhen a user registers this e-mail, they will become friend automatically.",
                parse_mode="Markdown",
                reply_markup=back_kb("adm_users"),
            )
        return
    user = await get_user_from_target(raw_target)
    if not user and raw_target.lstrip("-").isdigit():
        await db.register_user_as_friend(int(raw_target))
        user = await db.get_user(int(raw_target))
    if not user:
        await message.answer("User not found.", reply_markup=back_kb("adm_users"))
        return
    if not user.get("is_friend"):
        await db.set_friend(user["user_id"], True)
    await state.clear()
    await message.answer(f"Friend added: `{user['user_id']}`", parse_mode="Markdown", reply_markup=back_kb("adm_users"))


@router.callback_query(F.data == "adm_remove_friend")
async def adm_remove_friend(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(FriendState.waiting_remove_id)
    await render(callback, "<b>Remove friend</b>\n\nSend a Telegram user id, @username, or e-mail.", back_kb("adm_users"))
    await callback.answer()


@router.message(FriendState.waiting_remove_id)
async def save_friend_remove(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw_target = (message.text or "").strip()
    if looks_like_email(raw_target):
        affected = await db.remove_friend_email(raw_target)
        await state.clear()
        await message.answer(
            f"Friend e-mail removed: `{raw_target.lower()}`\nExisting users updated: `{affected}`",
            parse_mode="Markdown",
            reply_markup=back_kb("adm_users"),
        )
        return
    user = await get_user_from_target(raw_target)
    if not user:
        await message.answer("User not found.", reply_markup=back_kb("adm_users"))
        return
    await db.set_friend(user["user_id"], False)
    await state.clear()
    await message.answer(f"Friend removed: `{user['user_id']}`", parse_mode="Markdown", reply_markup=back_kb("adm_users"))


@router.callback_query(F.data == "adm_revoke_sub")
async def adm_revoke_sub(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(RevokeState.waiting_id)
    await render(callback, "<b>Revoke subscription</b>\n\nSend a Telegram user id or @username.", back_kb("adm_users"))
    await callback.answer()


@router.message(RevokeState.waiting_id)
async def save_revoke(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    user = await get_user_from_target(message.text or "")
    if not user:
        await message.answer("User not found.", reply_markup=back_kb("adm_users"))
        return
    await db.deactivate_subscription(user["user_id"])
    await state.clear()
    await message.answer(f"Subscription revoked for `{user['user_id']}`", parse_mode="Markdown", reply_markup=back_kb("adm_users"))


@router.callback_query(F.data == "adm_grant_sub")
async def adm_grant_sub(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    product_list = "\n".join(f"- <code>{k}</code> = {h(v[0])}" for k, v in subscription_products().items())
    await state.set_state(GrantSubState.waiting_payload)
    await render(callback, f"<b>Grant subscription</b>\n\nSend:\n<code>USER_ID_OR_USERNAME PRODUCT_KEY DAYS</code>\n\nAvailable products:\n{product_list}", back_kb("adm_main"))
    await callback.answer()


@router.message(GrantSubState.waiting_payload)
async def save_grant_sub(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer("Invalid format. Need: USER PRODUCT_KEY DAYS", reply_markup=back_kb("adm_main"))
        return
    user = await get_user_from_target(parts[0])
    meta = subscription_products().get(parts[1].lower())
    if not user or not meta:
        await message.answer("User or product not found.", reply_markup=back_kb("adm_main"))
        return
    try:
        days = int(parts[2])
    except ValueError:
        await message.answer("Days must be a whole number.", reply_markup=back_kb("adm_main"))
        return
    if days <= 0:
        await message.answer("Days must be greater than 0.", reply_markup=back_kb("adm_main"))
        return
    product_key = parts[1].lower()
    now = datetime.utcnow()
    base_exp = now
    for sub in await db.get_active_user_subscriptions(user["user_id"]):
        if sub.get("product_key") != product_key or not sub.get("expires_at"):
            continue
        try:
            current_exp = datetime.fromisoformat(sub["expires_at"])
        except Exception:
            continue
        if current_exp > base_exp:
            base_exp = current_exp
    expires_at = base_exp + timedelta(days=days)
    name, chat_id, chat_link = meta
    tx_hash = f"admin_grant_{user['user_id']}_{product_key}_{int(now.timestamp())}"
    await db.activate_product_subscription(user["user_id"], user.get("username"), product_key, name, expires_at, tx_hash, 0.0, chat_id, chat_link, "admin")
    await state.clear()
    await message.answer(f"Granted `{product_key}` to `{user['user_id']}` until `{expires_at.strftime('%Y-%m-%d')}`", parse_mode="Markdown", reply_markup=back_kb("adm_main"))


@router.callback_query(F.data == "adm_stub")
async def adm_stub(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await render(callback, "<b>Temporarily disabled</b>\n\nThis section was left out of the cleanup so the admin panel can stay stable and readable. We can add it back cleanly next.", back_kb())
    await callback.answer()
