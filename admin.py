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


def trim(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def back_kb(cb: str = "adm_main"):
    b = InlineKeyboardBuilder()
    b.button(text="Back", callback_data=cb)
    return b.as_markup()


async def effective_text(setting_prefix: str, lang: str) -> str:
    stored = await db.get_setting(f"{setting_prefix}_{lang}")
    if stored:
        return stored
    return DEFAULT_TEXTS.get(setting_prefix, {}).get(lang, "(default)")


def menu_kb():
    b = InlineKeyboardBuilder()
    for text, cb in [
        ("Stats", "adm_stats"),
        ("Detailed Stats", "adm_detailed_stats"),
        ("Retention Logs", "adm_retention_logs"),
        ("Users", "adm_users"),
        ("Pending Purchases", "adm_pending_email_users"),
        ("Chats", "adm_chats"),
        ("Welcome Text", "adm_edit_welcome"),
        ("Courses Text", "adm_edit_courses_text"),
        ("Promo Codes", "adm_promo_menu"),
        ("Checkout Links", "adm_edit_prices"),
        ("Export CSV", "adm_export_excel"),
        ("DB Backup", "adm_backup"),
        ("Bans", "adm_bans"),
        ("Payments", "adm_payments_menu"),
        ("Grant Subscription", "adm_grant_sub"),
        ("Settings", "adm_settings"),
        ("Remarketing", "adm_stub"),
        ("Marketing", "adm_stub"),
        ("Giveaway", "adm_stub"),
        ("Loyalty Stats", "adm_stub"),
    ]:
        b.button(text=text, callback_data=cb)
    b.adjust(2)
    return b.as_markup()


def configured_chat_rows():
    rows = [
        ("VIP Default", config.CHAT_ID, config.CHAT_LINK),
        ("VIP LV", config.CHAT_IDS.get("lv", 0), config.CHAT_LINKS.get("lv", "")),
        ("VIP EN", config.CHAT_IDS.get("en", 0), config.CHAT_LINKS.get("en", "")),
        ("VIP RU", config.CHAT_IDS.get("ru", 0), config.CHAT_LINKS.get("ru", "")),
        ("Scanner", getattr(config, "SCANNER_CHAT_ID", 0), getattr(config, "SCANNER_CHAT_LINK", "")),
    ]
    seen, out = set(), []
    for label, chat_id, link in rows:
        if chat_id and chat_id not in seen:
            seen.add(chat_id)
            out.append((label, int(chat_id), link or ""))
    return out


def subscription_products():
    return {
        "vip_chat_lv": ("VIP Chat LV", config.CHAT_IDS.get("lv", config.CHAT_ID), config.CHAT_LINKS.get("lv", config.CHAT_LINK)),
        "vip_chat_en": ("VIP Chat EN", config.CHAT_IDS.get("en", config.CHAT_ID), config.CHAT_LINKS.get("en", config.CHAT_LINK)),
        "vip_chat_ru": ("VIP Chat RU", config.CHAT_IDS.get("ru", config.CHAT_ID), config.CHAT_LINKS.get("ru", config.CHAT_LINK)),
        "scanner_chat": ("Scanner Chat", getattr(config, "SCANNER_CHAT_ID", 0), getattr(config, "SCANNER_CHAT_LINK", "")),
    }


async def get_user_from_target(token: str):
    token = (token or "").strip()
    if token.lstrip("-").isdigit():
        return await db.get_user(int(token))
    return await db.get_user_by_username(token)


async def render(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(trim(text), reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
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
    active = await db.get_all_active_users()
    registered = await db.get_registered_users()
    friends = await db.get_all_friends()
    reg = "\n".join(
        f"- {h('@' + u['username']) if u.get('username') else u['user_id']} | {h(u.get('email') or '-')} | reg. {fmt_dt(u.get('email_registered_at') or u.get('created_at'), True)} | exp. {fmt_dt(u.get('expires_at'), True)}"
        for u in registered[:12]
    ) or "-"
    act = "\n".join(
        f"- {h('@' + u['username']) if u.get('username') else u['user_id']} | {h(u.get('plan_name') or '-')} | exp. {fmt_dt(u.get('expires_at'), True)}"
        for u in active[:20]
    ) or "-"
    fr = "\n".join(f"- {h('@' + u['username']) if u.get('username') else u['user_id']}" for u in friends[:10]) or "-"
    b = InlineKeyboardBuilder()
    b.button(text="Add Friend", callback_data="adm_add_friend")
    b.button(text="Remove Friend", callback_data="adm_remove_friend")
    b.button(text="Revoke Subscription", callback_data="adm_revoke_sub")
    for u in registered[:8]:
        b.button(text=f"@{u['username']}" if u.get("username") else str(u["user_id"]), callback_data=f"adm_user_view_{u['user_id']}")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    text = f"<b>Registered ({len(registered)})</b>\n{reg}\n\n<b>Active ({len(active)})</b>\n{act}\n\n<b>Friends ({len(friends)})</b>\n{fr}"
    await render(callback, text, b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("adm_user_view_"))
async def adm_user_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    user = await db.get_user(int(callback.data.replace("adm_user_view_", "")))
    if not user:
        await callback.answer("User not found", show_alert=True)
        return
    subs = await db.get_active_user_subscriptions(user["user_id"])
    rows = "\n".join(f"- {h(s.get('product_name') or s.get('product_key'))} | exp. {fmt_dt(s.get('expires_at'), True)} | chat {s.get('chat_id', 0)}" for s in subs) or "None"
    text = (
        f"<b>User {user['user_id']}</b>\n\n"
        f"Username: {h('@' + user['username']) if user.get('username') else '-'}\n"
        f"Email: {h(user.get('email') or '-')}\n"
        f"Language: {h(user.get('lang') or '-')}\n"
        f"Active: <b>{'Yes' if user.get('is_active') else 'No'}</b>\n"
        f"Friend: <b>{'Yes' if user.get('is_friend') else 'No'}</b>\n"
        f"Last seen: {fmt_dt(user.get('last_seen_at'))}\n\n"
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
        f"<b>{h(x.get('email') or '-')}</b>\nProduct: {h(x.get('product_key') or '-')}\nPayment: {h(x.get('payment_system') or '-')}\nBought: {fmt_dt(x.get('created_at'))}\nActive until: {fmt_dt(x.get('expires_at'), True)}"
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
    managed = await db.get_managed_chats()
    rows = list(configured_chat_rows())
    seen = {chat_id for _, chat_id, _ in rows}
    for item in managed:
        chat_id = int(item.get("chat_id") or 0)
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        label = f"Managed: {item.get('title') or item.get('username') or chat_id}"
        rows.append((label, chat_id, item.get("invite_link") or ""))
    lines = []
    for label, chat_id, link in rows:
        joined, title = "No", "Unknown"
        try:
            chat = await bot.get_chat(chat_id)
            joined = "Yes"
            title = getattr(chat, "title", None) or getattr(chat, "username", None) or "OK"
        except Exception as e:
            title = str(e)[:80]
        lines.append(f"<b>{h(label)}</b>\nID: <code>{chat_id}</code>\nBot joined: <b>{joined}</b>\nChat: {h(title)}\nActive subs: <b>{counts.get(chat_id, 0)}</b>\nLink: <code>{h(link or '-')}</code>")
    await render(callback, "<b>Configured chats</b>\n\n" + ("\n\n".join(lines) or "No chats configured."), back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm_edit_welcome")
async def adm_edit_welcome(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    current_lv = await effective_text("welcome", "lv")
    current_en = await effective_text("welcome", "en")
    current_ru = await effective_text("welcome", "ru")
    text = (
        "<b>Welcome Text</b>\n\n"
        "These are the effective texts users see right now.\n\n"
        f"LV:\n<code>{h(current_lv[:500])}</code>\n\n"
        f"EN:\n<code>{h(current_en[:500])}</code>\n\n"
        f"RU:\n<code>{h(current_ru[:500])}</code>"
    )
    b = InlineKeyboardBuilder()
    for code in ("lv", "en", "ru"):
        b.button(text=f"Edit {code.upper()}", callback_data=f"adm_welcome_{code}")
    b.button(text="Reset All", callback_data="adm_welcome_reset")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2, 2)
    await render(callback, text, b.as_markup())
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
    current_lv = await effective_text("courses_text", "lv")
    current_en = await effective_text("courses_text", "en")
    current_ru = await effective_text("courses_text", "ru")
    text = (
        "<b>Courses Text</b>\n\n"
        "These are the effective texts users see right now.\n\n"
        f"LV:\n<code>{h(current_lv[:500])}</code>\n\n"
        f"EN:\n<code>{h(current_en[:500])}</code>\n\n"
        f"RU:\n<code>{h(current_ru[:500])}</code>"
    )
    b = InlineKeyboardBuilder()
    for code in ("lv", "en", "ru"):
        b.button(text=f"Edit {code.upper()}", callback_data=f"adm_courses_{code}")
    b.button(text="Reset All", callback_data="adm_courses_reset")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2, 2)
    await render(callback, text, b.as_markup())
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
    code = parts[0].upper()
    plan_key = parts[2] if len(parts) > 2 else None
    max_uses = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    expires_at = parts[4] + "T23:59:59" if len(parts) > 4 else None
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


@router.callback_query(F.data == "adm_edit_prices")
async def adm_edit_prices(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    labels = {
        "checkout_url_lv": "VIP chat button - Latvian",
        "checkout_url_en": "VIP chat button - English",
        "checkout_url_ru": "VIP chat button - Russian",
        "checkout_url_scanner_chat": "PRO Market Scanner/AI Signals button",
        "price_monthly": "VIP 1 month price",
        "course_price_mini": "Mini course price",
        "course_checkout_url_mini_lv": "Mini course checkout button - Latvian course",
        "course_checkout_url_mini_en": "Mini course checkout button - English course",
        "course_checkout_url_mini_ru": "Mini course checkout button - Russian course",
        "course_price_basic": "Basic course price",
        "course_checkout_url_basic_lv": "Basic course checkout button - Latvian course",
        "course_checkout_url_basic_en": "Basic course checkout button - English course",
        "course_checkout_url_basic_ru": "Basic course checkout button - Russian course",
        "course_price_full": "Full course price",
        "course_checkout_url_full_lv": "Full course checkout button - Latvian course",
        "course_checkout_url_full_en": "Full course checkout button - English course",
        "course_checkout_url_full_ru": "Full course checkout button - Russian course",
        "course_price_autotrading": "Autotrading course price",
        "course_checkout_url_autotrading_lv": "Autotrading course checkout button - Latvian course",
        "course_checkout_url_autotrading_en": "Autotrading course checkout button - English course",
        "course_checkout_url_autotrading_ru": "Autotrading course checkout button - Russian course",
        "course_price_vip": "VIP mentoring course price",
        "course_checkout_url_vip_lv": "VIP mentoring course checkout button - Latvian course",
        "course_checkout_url_vip_en": "VIP mentoring course checkout button - English course",
        "course_checkout_url_vip_ru": "VIP mentoring course checkout button - Russian course",
    }
    rows = []
    for key in ("checkout_url_lv", "checkout_url_en", "checkout_url_ru", "checkout_url_scanner_chat", "price_monthly"):
        rows.append(f"<b>{h(labels.get(key, key))}</b>\n<code>{h(key)}</code> = <code>{h(await db.get_setting(key) or '(empty)')}</code>")
    for course_key in config.COURSES.keys():
        price_key = f"course_price_{course_key}"
        rows.append(f"<b>{h(labels.get(price_key, price_key))}</b>\n<code>{h(price_key)}</code> = <code>{h(await db.get_setting(price_key) or '(default)')}</code>")
        for lang_code in ("lv", "en", "ru"):
            checkout_key = f"course_checkout_url_{course_key}_{lang_code}"
            rows.append(f"<b>{h(labels.get(checkout_key, checkout_key))}</b>\n<code>{h(checkout_key)}</code> = <code>{h(await db.get_setting(checkout_key) or '(empty)')}</code>")
    b = InlineKeyboardBuilder()
    b.button(text="VIP button LV", callback_data="adm_link_checkout_url_lv")
    b.button(text="VIP button EN", callback_data="adm_link_checkout_url_en")
    b.button(text="VIP button RU", callback_data="adm_link_checkout_url_ru")
    b.button(text="Scanner button", callback_data="adm_link_checkout_url_scanner_chat")
    b.button(text="VIP monthly price", callback_data="adm_price_price_monthly")
    b.button(text="Mini price", callback_data="adm_price_course_price_mini")
    b.button(text="Mini checkout LV", callback_data="adm_link_course_checkout_url_mini_lv")
    b.button(text="Mini checkout EN", callback_data="adm_link_course_checkout_url_mini_en")
    b.button(text="Mini checkout RU", callback_data="adm_link_course_checkout_url_mini_ru")
    b.button(text="Basic price", callback_data="adm_price_course_price_basic")
    b.button(text="Basic checkout LV", callback_data="adm_link_course_checkout_url_basic_lv")
    b.button(text="Basic checkout EN", callback_data="adm_link_course_checkout_url_basic_en")
    b.button(text="Basic checkout RU", callback_data="adm_link_course_checkout_url_basic_ru")
    b.button(text="Full price", callback_data="adm_price_course_price_full")
    b.button(text="Full checkout LV", callback_data="adm_link_course_checkout_url_full_lv")
    b.button(text="Full checkout EN", callback_data="adm_link_course_checkout_url_full_en")
    b.button(text="Full checkout RU", callback_data="adm_link_course_checkout_url_full_ru")
    b.button(text="Autotrading price", callback_data="adm_price_course_price_autotrading")
    b.button(text="Autotrading checkout LV", callback_data="adm_link_course_checkout_url_autotrading_lv")
    b.button(text="Autotrading checkout EN", callback_data="adm_link_course_checkout_url_autotrading_en")
    b.button(text="Autotrading checkout RU", callback_data="adm_link_course_checkout_url_autotrading_ru")
    b.button(text="VIP mentoring price", callback_data="adm_price_course_price_vip")
    b.button(text="VIP mentoring checkout LV", callback_data="adm_link_course_checkout_url_vip_lv")
    b.button(text="VIP mentoring checkout EN", callback_data="adm_link_course_checkout_url_vip_en")
    b.button(text="VIP mentoring checkout RU", callback_data="adm_link_course_checkout_url_vip_ru")
    b.button(text="Back", callback_data="adm_main")
    b.adjust(2)
    await render(
        callback,
        "<b>Checkout links and prices</b>\n\n"
        "Use the labels below exactly like this:\n"
        "- VIP chat button - Latvian = link for the Latvian VIP chat purchase button\n"
        "- VIP chat button - English = link for the English VIP chat purchase button\n"
        "- VIP chat button - Russian = link for the Russian VIP chat purchase button\n"
        "- PRO Market Scanner/AI Signals button = link for the scanner product button\n"
        "- Course checkout button - Latvian/English/Russian = link for that exact course language button after the user chooses the course language\n\n"
        + "\n".join(rows),
        b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_link_"))
async def adm_link_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.replace("adm_link_", "")
    labels = {
        "checkout_url_lv": "VIP chat button - Latvian",
        "checkout_url_en": "VIP chat button - English",
        "checkout_url_ru": "VIP chat button - Russian",
        "checkout_url_scanner_chat": "PRO Market Scanner/AI Signals button",
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
    await message.answer(f"Saved `{data['edit_key']}`", parse_mode="Markdown", reply_markup=back_kb("adm_edit_prices"))


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
    await message.answer(f"Saved `{data['edit_key']}` = `{raw}`", parse_mode="Markdown", reply_markup=back_kb("adm_edit_prices"))


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
    await callback.message.answer_document(FSInputFile(path), caption="Users export CSV")
    await callback.answer("CSV exported")


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
    s = await db.get_detailed_stats()
    pending_crypto = await db.get_all_pending_payments()
    pending_email = await db.get_all_pending_email_subscriptions()
    pending_withdrawals = await db.get_pending_withdrawals()
    text = (
        "<b>Payments overview</b>\n\n"
        f"Total revenue: <b>{s.get('total_revenue', 0):.2f}</b> USDT\n"
        f"Total purchases: <b>{s.get('total_purchases', 0)}</b>\n"
        f"Today revenue: <b>{s.get('today_revenue', 0):.2f}</b> USDT\n"
        f"Today purchases: <b>{s.get('today_purchases', 0)}</b>\n"
        f"Pending old crypto payments: <b>{len(pending_crypto)}</b>\n"
        f"Pending purchases without TG: <b>{len(pending_email)}</b>\n"
        f"Pending withdrawals: <b>{len(pending_withdrawals)}</b>"
    )
    await render(callback, text, back_kb())
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
    await render(callback, "<b>Add friend</b>\n\nSend a Telegram user id or @username.", back_kb("adm_users"))
    await callback.answer()


@router.message(FriendState.waiting_id)
async def save_friend_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    user = await get_user_from_target(message.text or "")
    if not user:
        await message.answer("User not found.", reply_markup=back_kb("adm_users"))
        return
    await db.set_friend(user["user_id"], True)
    await state.clear()
    await message.answer(f"Friend added: `{user['user_id']}`", parse_mode="Markdown", reply_markup=back_kb("adm_users"))


@router.callback_query(F.data == "adm_remove_friend")
async def adm_remove_friend(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(FriendState.waiting_remove_id)
    await render(callback, "<b>Remove friend</b>\n\nSend a Telegram user id or @username.", back_kb("adm_users"))
    await callback.answer()


@router.message(FriendState.waiting_remove_id)
async def save_friend_remove(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    user = await get_user_from_target(message.text or "")
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
    expires_at = datetime.utcnow() + timedelta(days=days)
    name, chat_id, chat_link = meta
    tx_hash = f"admin_grant_{user['user_id']}_{parts[1].lower()}_{int(datetime.utcnow().timestamp())}"
    await db.activate_product_subscription(user["user_id"], user.get("username"), parts[1].lower(), name, expires_at, tx_hash, 0.0, chat_id, chat_link, "admin")
    await state.clear()
    await message.answer(f"Granted `{parts[1].lower()}` to `{user['user_id']}` until `{expires_at.strftime('%Y-%m-%d')}`", parse_mode="Markdown", reply_markup=back_kb("adm_main"))


@router.callback_query(F.data == "adm_stub")
async def adm_stub(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await render(callback, "<b>Temporarily disabled</b>\n\nThis section was left out of the cleanup so the admin panel can stay stable and readable. We can add it back cleanly next.", back_kb())
    await callback.answer()
