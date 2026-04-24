from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
from html import escape as html_escape
import logging

from config import config
from database import db

logger = logging.getLogger(__name__)
router = Router()

MAX_TG_TEXT_LEN = 4000


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _safe_text(value) -> str:
    return html_escape(str(value if value is not None else ""))


def _trim_for_telegram(text: str, limit: int = MAX_TG_TEXT_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class EditState(StatesGroup):
    waiting_text = State()
    waiting_price = State()
    waiting_checkout_url = State()


class FriendState(StatesGroup):
    waiting_id = State()
    waiting_remove_id = State()


class PromoState(StatesGroup):
    waiting_code = State()
    waiting_discount = State()
    waiting_plan = State()
    waiting_max_uses = State()
    waiting_expiry = State()


class MarketingState(StatesGroup):
    waiting_text = State()

class RevokeState(StatesGroup):
    waiting_id = State()


def admin_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Statistika", callback_data="adm_stats")
    builder.button(text="📈 Detalizēta", callback_data="adm_detailed_stats")
    builder.button(text="📜 Retention Logs", callback_data="adm_retention_logs")
    builder.button(text="👥 Lietotāji", callback_data="adm_users")
    builder.button(text="👋 Welcome teksts", callback_data="adm_edit_welcome")
    builder.button(text="📚 Kursu teksts", callback_data="adm_edit_courses_text")
    builder.button(text="⚙️ Remarketing", callback_data="adm_marketing_remarketing")
    builder.button(text="📤 Marketing", callback_data="adm_send_marketing")
    builder.button(text="🏷 Promo kodi", callback_data="adm_promo_menu")
    builder.button(text="🔗 Checkout linki", callback_data="adm_edit_prices")
    builder.button(text="📥 Excel eksports", callback_data="adm_export_excel")
    builder.button(text="🎟 Giveaway", callback_data="adm_giveaway")
    builder.button(text="💾 DB Backup", callback_data="adm_backup")
    builder.button(text="💸 Withdrawals", callback_data="adm_withdrawals")
    builder.button(text="🚫 Bans", callback_data="adm_bans")
    builder.button(text="📊 Loyalty Stats", callback_data="adm_loyalty_stats")
    builder.button(text="🧾 Maksājumi", callback_data="adm_payments_menu")
    builder.button(text="🎁 Piešķirt abonementu", callback_data="adm_grant_sub")
    builder.button(text="⚙️ Settings", callback_data="adm_settings")
    builder.adjust(2)
    return builder.as_markup()


def back_kb(cb: str = "adm_main"):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Atpakaļ", callback_data=cb)
    return builder.as_markup()


# ─── MAIN ADMIN ───

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 *Admin Panel*", reply_markup=admin_menu_kb(), parse_mode="Markdown")


@router.message(Command("helpadmin"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = (
        "🛠 *Admin komandas:*\n\n"
        "📋 *Panelis:*\n"
        "/admin — Atvērt admin paneli\n"
        "/helpadmin — Šī palīdzība\n\n"
        "👥 *Lietotāju pārvaldība:*\n"
        "/add\\_user `[user_id] [days]` — Manuāli pievienot abonementu\n"
        "/remove\\_user `[user_id]` — Noņemt abonementu un izmest\n\n"
        "🔍 *Diagnostika:*\n"
        "/debug\\_payment — BSC RPC pārbaude, pending, pēdējie TX\n"
        "/fix\\_payment `[amount]` — Labot nepareizas summas payment history\n\n"
        "📊 *Admin paneļa pogas:*\n"
        "• 📊 Statistika — pamata skaitļi\n"
        "• 📈 Detalizēta — ieņēmumi, konversija, ARPU, grafiks\n"
        "• 👥 Lietotāji — aktīvie, draugi, atņemt abonementu\n"
        "• 👋 Welcome teksts — rediģēt /start ziņu (RU/EN)\n"
        "• ⚙️ Remarketing — rediģēt reminder / win-back tekstus un dienas\n"
        "• 📤 Marketing — sūtīt ziņas dažādām grupām\n"
        "• 🏷 Promo kodi — izveidot/dzēst atlaižu kodus\n"
        "• 💰 Cenas — mainīt plānu cenas\n"
        "• 📥 Excel — eksportēt lietotāju datus\n"
        "• 💾 Backup — lejupielādēt DB failu"
    )
    await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data == "adm_main")
async def adm_main(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("🛠 *Admin Panel*", reply_markup=admin_menu_kb(), parse_mode="Markdown")
    await callback.answer()


# ─── BASIC STATS ───

# Plānu nosaukumu tulkošana admin panelī
PLAN_NAME_MAP = {
    "1 Месяц": "1 Mēnesis", "Полгода": "Pusgads",
    "1 Год": "1 Gads", "Навсегда": "Mūžīgi",
    "1 Month": "1 Mēnesis", "6 Months": "Pusgads",
    "1 Year": "1 Gads", "Lifetime": "Mūžīgi",
}
def plan_lv(name):
    return PLAN_NAME_MAP.get(name, name)


@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    s = await db.get_stats()
    plan_text = "\n".join([f"  • {plan_lv(k)}: {v}" for k, v in s['by_plan'].items()]) or "  —"
    text = (
        f"📊 *Statistika*\n\n"
        f"👥 Kopā lietotāji: *{s['total_users']}*\n"
        f"✅ Aktīvie abonenti: *{s['active']}*\n"
        f"👀 Nepirkušie: *{s['never_bought']}*\n"
        f"❌ Beidzies: *{s['expired']}*\n\n"
        f"💰 Kopā ieņēmumi: *{s['total_revenue']:.2f} USDT*\n\n"
        f"📦 Pa plāniem:\n{plan_text}"
    )
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    await callback.answer()


# ─── DETAILED STATS ───

@router.callback_query(F.data == "adm_detailed_stats")
async def adm_detailed_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    s = await db.get_detailed_stats()
    ref_stats = await db.get_referral_stats()

    # Nedēļas grafiks (vienkāršs teksta grafiks)
    week_chart = ""
    max_rev = max((d['revenue'] for d in s['week_data']), default=1) or 1
    for d in s['week_data']:
        bars = int((d['revenue'] / max_rev) * 8) if max_rev > 0 else 0
        bar_str = "█" * bars + "░" * (8 - bars)
        week_chart += f"  `{d['date']}` {bar_str} *{d['revenue']:.0f}* ({d['count']})\n"

    # Top plāni
    top_text = ""
    for p in s['top_plans'][:5]:
        top_text += f"  • {plan_lv(p['plan_name'])}: {p['cnt']}x = *{p['rev']:.0f} USDT*\n"

    text = (
        f"📈 *Detalizēta Statistika*\n\n"
        f"━━━ 💵 *Ieņēmumi* ━━━\n"
        f"📅 Šodien: *{s['today_revenue']:.2f} USDT* ({s['today_purchases']} pirkumi)\n"
        f"📅 Šomēnes: *{s['month_revenue']:.2f} USDT* ({s['month_purchases']} pirk.)\n"
        f"📅 Šogad: *{s['year_revenue']:.2f} USDT*\n"
        f"📅 Kopā: *{s['total_revenue']:.2f} USDT*\n\n"
        f"━━━ 👥 *Pircēji* ━━━\n"
        f"🛒 Unikālie maksātāji: *{s['unique_buyers']}*\n"
        f"🔄 Atkārtotie (2+ pirk.): *{s['repeat_buyers']}*\n"
        f"1️⃣ Tikai 1x pircēji: *{s['one_time_buyers']}*\n"
        f"📊 Konversija: *{s['conversion']:.1f}%*\n"
        f"💰 Vid. pirkums (ARPU): *{s['arpu']:.2f} USDT*\n\n"
        f"━━━ 📊 *Pēdējās 7 dienas* ━━━\n"
        f"{week_chart}\n"
        f"━━━ 🏆 *Top plāni* ━━━\n"
        f"{top_text}\n"
        f"━━━ 📉 *Citi* ━━━\n"
        f"❌ Aizgājuši (churn): *{s['churned']}*\n"
        f"🆕 Jaunie šodien: *{s['new_today']}*\n"
        f"⏰ Reminderi šodien: *{s['reminders_today']}*\n"
        f"⏰ Reminderi 7d: *{s['reminders_7d']}*\n"
        f"📣 Beidzas šodien paziņojumi: *{s['expiry_today_notices']}*\n"
        f"🚫 Izmesti šodien: *{s['kicked_today']}*\n"
        f"🚫 Izmesti 7d: *{s['kicked_7d']}*\n\n"
        f"━━━ 👥 *Referrals* ━━━\n"
        f"📨 Kopā atnākuši no ref: *{ref_stats['total_referrals']}*\n"
        f"💰 No tiem veikuši pirkumu: *{ref_stats['paid_referrals']}*"
    )
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "adm_retention_logs")
async def adm_retention_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    events = await db.get_recent_bot_events(30)
    stats = await db.get_bot_event_stats()

    type_map = {
        "reminder_sent": "⏰ Reminder",
        "expiry_today_notice": "📣 Beidzas šodien",
        "expired_kick": "🚫 Kick",
    }

    rows = []
    for event in events:
        event_type = type_map.get(event.get("event_type"), event.get("event_type", "?"))
        username = f"@{event['username']}" if event.get("username") else f"ID {event.get('user_id', '?')}"
        plan_name = event.get("plan_name") or "—"
        created_at = (event.get("created_at") or "")[:16].replace("T", " ")
        meta = event.get("meta") or ""
        rows.append(f"• {event_type} | {username} | {plan_name} | {created_at}\n  {meta}")

    text = (
        f"📜 *Retention Logs*\n\n"
        f"⏰ Reminderi šodien: *{stats['reminders_today']}*\n"
        f"📣 Beidzas šodien: *{stats['expiry_today_notices']}*\n"
        f"🚫 Kicki šodien: *{stats['kicked_today']}*\n\n"
        f"{chr(10).join(rows) if rows else 'Nav notikumu.'}"
    )

    await callback.message.edit_text(
        _trim_for_telegram(text),
        reply_markup=back_kb("adm_main"),
        parse_mode="Markdown"
    )
    await callback.answer()


# ─── USERS ───

@router.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    users = await db.get_all_active_users()
    registered = await db.get_registered_users()
    friends = await db.get_all_friends()

    builder = InlineKeyboardBuilder()
    builder.button(text="👫 Pievienot draugu", callback_data="adm_add_friend")
    builder.button(text="❌ Noņemt draugu", callback_data="adm_remove_friend")
    builder.button(text="🚫 Atņemt abonementu", callback_data="adm_revoke_sub")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_main")
    builder.adjust(2, 1, 1)

    lines = []
    for u in users[:20]:
        expires_at = u.get("expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
            except ValueError:
                exp = expires_at
        else:
            exp = "∞"

        uname = f"@{u['username']}" if u.get("username") else str(u["user_id"])
        friend_tag = " 👫" if u.get("is_friend") else ""
        plan_name = u.get("plan_name") or "?"
        lines.append(
            f"• {_safe_text(uname)}{friend_tag} — {_safe_text(plan_name)} → {_safe_text(exp)}"
        )

    reg_lines = []
    for u in registered[:10]:
        status = "Aktīvs" if u.get("is_active") and u.get("expires_at") and u.get("expires_at") > datetime.utcnow().isoformat() else "Neaktīvs"
        exp = (u.get("expires_at") or "—")[:10]
        email = u.get("email") or "—"
        registered_at = (u.get("email_registered_at") or u.get("created_at") or "—")[:10]
        uname = f"@{u['username']}" if u.get("username") else str(u["user_id"])
        reg_lines.append(f"• {_safe_text(uname)} | {_safe_text(email)} | reg. {_safe_text(registered_at)} | {status} | līdz {_safe_text(exp)}")

    text = (
        f"👥 <b>Reģistrētie ({len(registered)}):</b>\n"
        + ("\n".join(reg_lines) if reg_lines else "—")
        + f"\n\n✅ <b>Aktīvie ({len(users)}):</b>\n"
        + ("\n".join(lines) if lines else "—")
    )
    if len(registered) > 10:
        text += f"\n...un vēl {len(registered) - 10} reģistrēti"
    if len(users) > 20:
        text += f"\n...un vēl {len(users) - 20}"
    if friends:
        friend_lines = [
            f"• {_safe_text('@' + f['username'])} 👫"
            if f.get("username")
            else f"• {_safe_text(f['user_id'])} 👫"
            for f in friends[:10]
        ]
        text += f"\n\n👫 <b>Draugi ({len(friends)}):</b>\n" + "\n".join(friend_lines)

    await callback.message.edit_text(
        _trim_for_telegram(text),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()
    return


# ─── FRIENDS ───

@router.callback_query(F.data == "adm_add_friend")
async def adm_add_friend(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(FriendState.waiting_id)
    await callback.message.edit_text(
        "👫 *Pievienot draugu*\n\nIevadi *@username* vai *user\\_id*:\n/cancel lai atceltu", parse_mode="Markdown"
    )
    await callback.answer()


@router.message(FriendState.waiting_id)
async def adm_receive_friend_id(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return

    raw = message.text.strip()
    user_id = None
    username = None

    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        found = await db.get_user_by_username(raw)
        if found:
            user_id = found["user_id"]
            username = found.get("username")
        else:
            await message.answer(f"❌ `{raw}` nav atrasts. Lietotājam jāuzsāk bots.", parse_mode="Markdown")
            return
    else:
        user_id = int(raw)

    await state.clear()
    await db.register_user_as_friend(user_id, username)
    try:
        link = await bot.create_chat_invite_link(config.CHAT_ID, member_limit=1)
        await bot.send_message(user_id, f"👋 Tev ir bezmaksas piekļuve kanālam!\n\n🔗 {link.invite_link}")
        notify = "✅ Invite nosūtīts."
    except Exception as e:
        notify = f"⚠️ Neizdevās nosūtīt: {e}"

    display = f"@{username}" if username else str(user_id)
    await message.answer(f"👫 *{display}* pievienots!\n\n{notify}", reply_markup=admin_menu_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "adm_remove_friend")
async def adm_remove_friend(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    friends = await db.get_all_friends()
    if not friends:
        await callback.message.edit_text("Nav draugu.", reply_markup=back_kb("adm_users"))
        await callback.answer()
        return
    await state.set_state(FriendState.waiting_remove_id)
    lines = "\n".join([f"• @{f['username']} ({f['user_id']})" if f.get('username') else f"• {f['user_id']}" for f in friends])
    await callback.message.edit_text(f"❌ *Noņemt draugu*\n\n{lines}\n\nIevadi @username vai ID:\n/cancel", parse_mode="Markdown")
    await callback.answer()


@router.message(FriendState.waiting_remove_id)
async def adm_receive_remove_friend(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    raw = message.text.strip()
    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        found = await db.get_user_by_username(raw)
        if not found:
            await message.answer(f"❌ `{raw}` nav atrasts.", parse_mode="Markdown")
            return
        user_id = found["user_id"]
        display = f"@{found.get('username', raw)}"
    else:
        user_id = int(raw)
        display = str(user_id)

    await state.clear()
    await db.set_friend(user_id, False)
    await message.answer(f"✅ *{display}* noņemts.", reply_markup=admin_menu_kb(), parse_mode="Markdown")


# ─── REVOKE SUBSCRIPTION ───

@router.callback_query(F.data == "adm_revoke_sub")
async def adm_revoke_sub(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    users = await db.get_all_active_users()
    if not users:
        await callback.message.edit_text("Nav aktīvo abonentu.", reply_markup=back_kb("adm_users"))
        await callback.answer()
        return

    await state.set_state(RevokeState.waiting_id)
    lines = []
    for u in users[:25]:
        uname = f"@{u['username']}" if u.get('username') else str(u['user_id'])
        exp = datetime.fromisoformat(u['expires_at']).strftime('%d.%m') if u.get('expires_at') else '?'
        lines.append(f"• {uname} ({u['user_id']}) — {u.get('plan_name','?')} → {exp}")

    text = (
        f"🚫 *Atņemt abonementu*\n\n"
        f"Aktīvie abonenti:\n" + "\n".join(lines) +
        f"\n\nIevadi *@username* vai *user\\_id* kam atņemt:\n"
        f"_Lietotājs tiks izmests no kanāla un abonements deaktivizēts._\n\n"
        f"/cancel lai atceltu"
    )
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@router.message(RevokeState.waiting_id)
async def adm_receive_revoke_id(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return

    raw = message.text.strip()
    user_id = None
    display = raw

    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        found = await db.get_user_by_username(raw)
        if not found:
            await message.answer(f"❌ `{raw}` nav atrasts datubāzē.", parse_mode="Markdown")
            return
        user_id = found["user_id"]
        display = f"@{found.get('username', raw)}"
    else:
        try:
            user_id = int(raw)
            display = str(user_id)
        except ValueError:
            await message.answer("❌ Nepareizs formāts.")
            return

    await state.clear()

    is_target_admin = user_id in config.ADMIN_IDS

    # 1. Deaktivizēt DB
    await db.deactivate_subscription(user_id)

    # 2. Izmest no kanāla (BET NE ADMINU)
    kicked = False
    if is_target_admin:
        kicked_msg = "ℹ️ Admins — nav izmests no kanāla (tikai DB deaktivizēts)"
    else:
        try:
            await bot.ban_chat_member(config.CHAT_ID, user_id)
            await bot.unban_chat_member(config.CHAT_ID, user_id)
            kicked = True
            kicked_msg = "✅ Izmests no kanāla"
        except Exception as e:
            logger.error(f"Revoke kick error {user_id}: {e}")
            kicked_msg = "⚠️ Neizdevās izmest no kanāla"

    # 3. Paziņot lietotājam
    notified = False
    try:
        user = await db.get_user(user_id)
        lang = user.get("lang", "ru") if user else "ru"
        if lang == "ru":
            text = "🚫 *Ваша подписка была аннулирована администратором.*\n\nЕсли считаете это ошибкой — обратитесь в поддержку."
        else:
            text = "🚫 *Your subscription has been revoked by admin.*\n\nIf you think this is a mistake — contact support."
        await bot.send_message(user_id, text, parse_mode="Markdown")
        notified = True
    except Exception:
        pass

    status = []
    status.append("✅ Abonements deaktivizēts")
    status.append(kicked_msg)
    status.append("✅ Lietotājs informēts" if notified else "⚠️ Neizdevās nosūtīt ziņu")

    await message.answer(
        f"🚫 *Abonements atņemts: {display}*\n\n" + "\n".join(status),
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )


# ─── PROMO CODES ───

@router.callback_query(F.data == "adm_promo_menu")
async def adm_promo_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promos = await db.get_all_promo_codes()
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Izveidot kodu", callback_data="adm_promo_create")
    if promos:
        builder.button(text="🗑 Dzēst kodu", callback_data="adm_promo_delete")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_main")
    builder.adjust(2, 1)

    if promos:
        lines = []
        for p in promos:
            pk = p.get('plan_key') or 'visi'
            uses = f"{p['used_count']}/{p['max_uses']}" if p.get('max_uses') else f"{p['used_count']}/∞"
            exp = ""
            if p.get('expires_at'):
                exp = f" | līdz {p['expires_at'][:10]}"
            lines.append(f"• {p['code']} — {p['discount_percent']}% | {pk} | {uses}{exp}")
        text = "🏷 Promo kodi\n\n" + "\n".join(lines)
    else:
        text = "🏷 Promo kodi\n\nNav neviena promo koda."

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "adm_promo_create")
async def adm_promo_create(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(PromoState.waiting_code)
    await callback.message.edit_text(
        "🏷 *Jauns promo kods*\n\n"
        "Ievadi kodu (piem. WELCOME20):\n\n"
        "/cancel lai atceltu", parse_mode="Markdown"
    )
    await callback.answer()


@router.message(PromoState.waiting_code)
async def promo_receive_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    code = message.text.strip().upper()
    # Pārbaudīt vai jau eksistē
    existing = await db.get_promo_code(code)
    if existing:
        await message.answer(f"❌ Kods {code} jau eksistē! Izvēlies citu.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(PromoState.waiting_discount)
    await message.answer(f"Kods: *{code}*\n\nIevadi atlaidi % (piem. 20 = 20% off):", parse_mode="Markdown")


@router.message(PromoState.waiting_discount)
async def promo_receive_discount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    try:
        discount = int(message.text.strip())
        if not 1 <= discount <= 99:
            raise ValueError
    except ValueError:
        await message.answer("❌ Ievadi skaitli 1-99")
        return

    await state.update_data(discount=discount)
    await state.set_state(PromoState.waiting_plan)

    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Visiem (plāni + kursi)", callback_data="promo_plan_all")
    builder.button(text="📚 Visiem kursiem", callback_data="promo_plan_all_courses")
    for key in config.PLANS:
        name = config.PLANS[key]['name']['ru']
        builder.button(text=f"{config.PLANS[key]['emoji']} {name}", callback_data=f"promo_plan_{key}")
    for key in config.COURSES:
        name = config.COURSES[key]['name']['ru']
        builder.button(text=f"{config.COURSES[key]['emoji']} {name}", callback_data=f"promo_plan_course_{key}")
    builder.adjust(1)
    await message.answer(f"Atlaide: *{discount}%*\n\nKuram:", reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("promo_plan_"))
async def promo_plan_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    plan_key = callback.data.replace("promo_plan_", "")
    if plan_key == "all":
        plan_key = None
    elif plan_key == "all_courses":
        plan_key = "all_courses"

    await state.update_data(plan_key=plan_key)
    await state.set_state(PromoState.waiting_max_uses)
    await callback.message.edit_text(
        "Cik reizes var izmantot? (0 = neierobežoti)\n\nIevadi skaitli:", parse_mode="Markdown"
    )
    await callback.answer()


@router.message(PromoState.waiting_max_uses)
async def promo_receive_max_uses(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    try:
        max_uses = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Ievadi skaitli")
        return

    await state.update_data(max_uses=max_uses)
    await state.set_state(PromoState.waiting_expiry)

    builder = InlineKeyboardBuilder()
    builder.button(text="♾ Bez limita", callback_data="promo_exp_none")
    builder.button(text="7 dienas", callback_data="promo_exp_7")
    builder.button(text="14 dienas", callback_data="promo_exp_14")
    builder.button(text="30 dienas", callback_data="promo_exp_30")
    builder.button(text="90 dienas", callback_data="promo_exp_90")
    builder.adjust(1)
    await message.answer("Cik dienas kods derīgs?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("promo_exp_"))
async def promo_exp_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    exp_val = callback.data.replace("promo_exp_", "")

    expires_at = None
    if exp_val != "none":
        days = int(exp_val)
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()

    data = await state.get_data()
    await state.clear()

    await db.create_promo_code(
        code=data['promo_code'],
        discount_percent=data['discount'],
        plan_key=data.get('plan_key'),
        max_uses=data.get('max_uses', 0),
        expires_at=expires_at
    )

    plan_text = data.get('plan_key') or 'visi'
    uses_text = str(data.get('max_uses', 0)) if data.get('max_uses', 0) > 0 else '∞'
    exp_text = expires_at[:10] if expires_at else '♾ bez limita'
    await callback.message.edit_text(
        f"✅ *Promo kods izveidots!*\n\n"
        f"🏷 Kods: *{data['promo_code']}*\n"
        f"💰 Atlaide: *{data['discount']}%*\n"
        f"📦 Kam: *{plan_text}*\n"
        f"🔢 Max: *{uses_text}*\n"
        f"📅 Derīgs: *{exp_text}*",
        reply_markup=admin_menu_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "adm_promo_delete")
async def adm_promo_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promos = await db.get_all_promo_codes()
    if not promos:
        await callback.answer("Nav kodu ko dzēst", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for p in promos:
        builder.button(text=f"🗑 {p['code']} ({p['discount_percent']}%)", callback_data=f"adm_promo_del_{p['code']}")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_promo_menu")
    builder.adjust(1)
    await callback.message.edit_text("Izvēlies kodu ko dzēst:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("adm_promo_del_"))
async def adm_promo_del_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    code = callback.data.replace("adm_promo_del_", "")
    await db.delete_promo_code(code)
    await callback.message.edit_text(f"✅ Kods *{code}* dzēsts.", reply_markup=admin_menu_kb(), parse_mode="Markdown")
    await callback.answer()


# ─── EDIT WELCOME ───

class WelcomeState(StatesGroup):
    waiting_text = State()

@router.callback_query(F.data == "adm_edit_welcome")
async def adm_edit_welcome(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Welcome (RU)", callback_data="adm_welcome_ru")
    builder.button(text="🇬🇧 Welcome (EN)", callback_data="adm_welcome_en")
    builder.button(text="🔄 Atiestatīt uz default", callback_data="adm_welcome_reset")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_main")
    builder.adjust(2, 1, 1)

    cur_ru = await db.get_setting("welcome_ru") or "— (default)"
    cur_en = await db.get_setting("welcome_en") or "— (default)"

    await callback.message.edit_text(
        f"👋 *Welcome teksta rediģēšana*\n\n"
        f"Šo tekstu redzēs jauni lietotāji nospiežot /start.\n\n"
        f"💡 Var izmantot `{{name}}` — tiks aizvietots ar lietotāja vārdu.\n"
        f"Var izmantot Markdown: *bold*, \\_italic\\_\n\n"
        f"🇷🇺 *Pašreizējais RU:*\n{cur_ru[:200]}{'...' if len(cur_ru) > 200 else ''}\n\n"
        f"🇬🇧 *Pašreizējais EN:*\n{cur_en[:200]}{'...' if len(cur_en) > 200 else ''}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_welcome_"))
async def adm_welcome_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang_code = callback.data.replace("adm_welcome_", "")

    if lang_code == "reset":
        await db.set_setting("welcome_ru", "")
        await db.set_setting("welcome_en", "")
        await callback.message.edit_text(
            "✅ Welcome teksti atiestatīti uz default.\n\nTagad tiks izmantoti iebūvētie teksti.",
            reply_markup=back_kb("adm_edit_welcome")
        )
        await callback.answer()
        return

    current = await db.get_setting(f"welcome_{lang_code}") or "— (default)"
    await state.set_state(WelcomeState.waiting_text)
    await state.update_data(welcome_lang=lang_code)
    await callback.message.edit_text(
        f"✏️ *Welcome teksts ({'RU' if lang_code == 'ru' else 'EN'})*\n\n"
        f"Pašreizējais:\n{current}\n\n"
        f"📝 Atsūti jauno tekstu:\n"
        f"💡 `{{name}}` = lietotāja vārds\n"
        f"/cancel lai atceltu",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(WelcomeState.waiting_text)
async def adm_receive_welcome(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    data = await state.get_data()
    lang_code = data.get("welcome_lang", "ru")
    await db.set_setting(f"welcome_{lang_code}", message.text)
    await state.clear()
    await message.answer(
        f"✅ *Welcome teksts ({lang_code.upper()}) saglabāts!*\n\n"
        f"Jaunais teksts:\n{message.text[:300]}",
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )


# ─── EDIT COURSES TEXT ───

class CoursesTextState(StatesGroup):
    waiting_text = State()

@router.callback_query(F.data == "adm_edit_courses_text")
async def adm_edit_courses_text(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    cur_ru = await db.get_setting("courses_text_ru") or "— (default)"
    cur_en = await db.get_setting("courses_text_en") or "— (default)"
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Kursu teksts (RU)", callback_data="adm_ctext_ru")
    b.button(text="🇬🇧 Kursu teksts (EN)", callback_data="adm_ctext_en")
    b.button(text="🔄 Atiestatīt uz default", callback_data="adm_ctext_reset")
    b.button(text="🔙 Atpakaļ", callback_data="adm_main")
    b.adjust(2, 1, 1)
    await callback.message.edit_text(
        f"📚 *Kursu teksta rediģēšana*\n\n"
        f"Šo tekstu redzēs lietotāji nospiežot Kursi pogu.\n\n"
        f"🇷🇺 *RU:* {cur_ru[:150]}{'...' if len(cur_ru) > 150 else ''}\n\n"
        f"🇬🇧 *EN:* {cur_en[:150]}{'...' if len(cur_en) > 150 else ''}",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("adm_ctext_"))
async def adm_ctext_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    lang_code = callback.data.replace("adm_ctext_", "")
    if lang_code == "reset":
        await db.set_setting("courses_text_ru", "")
        await db.set_setting("courses_text_en", "")
        await callback.message.edit_text("✅ Kursu teksti atiestatīti uz default.", reply_markup=back_kb("adm_edit_courses_text"))
        await callback.answer(); return
    current = await db.get_setting(f"courses_text_{lang_code}") or "— (default)"
    await state.set_state(CoursesTextState.waiting_text)
    await state.update_data(ctext_lang=lang_code)
    await callback.message.edit_text(
        f"📚 *Kursu teksts ({lang_code.upper()})*\n\n"
        f"Pašreizējais:\n{current[:300]}\n\n"
        f"📝 Atsūti jauno tekstu:\n/cancel lai atceltu", parse_mode="Markdown"
    )
    await callback.answer()

@router.message(CoursesTextState.waiting_text)
async def adm_receive_ctext(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb()); return
    data = await state.get_data()
    lang_code = data.get("ctext_lang", "ru")
    await db.set_setting(f"courses_text_{lang_code}", message.text)
    await state.clear()
    await message.answer(f"✅ Kursu teksts ({lang_code.upper()}) saglabāts!", reply_markup=admin_menu_kb())


# ─── EDIT REMINDERS ───

@router.callback_query(F.data == "adm_edit_reminders")
async def adm_edit_reminders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await adm_marketing_remarketing(callback)
    return


@router.callback_query(F.data.startswith("adm_edit_reminder_"))
async def adm_edit_reminder_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    legacy_key = callback.data.replace("adm_edit_reminder_", "")
    legacy_map = {
        "3d_ru": "remarketing_reminder_3_ru",
        "3d_en": "remarketing_reminder_3_en",
        "1d_ru": "remarketing_reminder_1_ru",
        "1d_en": "remarketing_reminder_1_en",
    }
    key = legacy_map.get(legacy_key)
    if not key:
        await callback.answer("Nav atbalstīts", show_alert=True)
        return
    current = await db.get_setting(key) or "—"
    await state.set_state(EditState.waiting_text)
    await state.update_data(edit_key=key)
    await callback.message.edit_text(f"✏️ *Pašreizējais:*\n\n{current}\n\n📝 Ievadi jauno tekstu:\n/cancel", parse_mode="Markdown")
    await callback.answer()


# ─── MARKETING — PAPLAŠINĀTS ───

def marketing_audience_kb(counts: dict):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"📢 Visi ({counts['all']})", callback_data="mkt_aud_all")
    builder.button(text=f"✅ Aktīvie ({counts['active']})", callback_data="mkt_aud_active")
    builder.button(text=f"👀 Nepirkušie ({counts['never_bought']})", callback_data="mkt_aud_never_bought")
    builder.button(text=f"🆕 Nekad nav saņēmuši ({counts['never_messaged']})", callback_data="mkt_aud_never_messaged")
    builder.button(text=f"❌ Beidzies 1-5d ({counts['expired_5']})", callback_data="mkt_aud_expired_5")
    builder.button(text=f"❌ Beidzies 5+d ({counts['expired_old']})", callback_data="mkt_aud_expired_old")
    builder.button(text=f"1️⃣ 1x pircēji ({counts['one_time']})", callback_data="mkt_aud_one_time")
    builder.button(text=f"⏰ Beigsies 7d ({counts['expiring_soon']})", callback_data="mkt_aud_expiring_soon")
    builder.button(text=f"👋 Ref nepircēji ({counts['ref_pending']})", callback_data="mkt_aud_ref_pending")
    builder.button(text="⚙️ Remarketing", callback_data="adm_marketing_remarketing")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_main")
    builder.adjust(1)
    return builder.as_markup()


def remarketing_settings_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 30d LV", callback_data="adm_edit_remarket_remarketing_reminder_30_lv")
    builder.button(text="📅 30d RU", callback_data="adm_edit_remarket_remarketing_reminder_30_ru")
    builder.button(text="📅 30d EN", callback_data="adm_edit_remarket_remarketing_reminder_30_en")
    builder.button(text="⚠️ 7d LV", callback_data="adm_edit_remarket_remarketing_reminder_7_lv")
    builder.button(text="⚠️ 7d RU", callback_data="adm_edit_remarket_remarketing_reminder_7_ru")
    builder.button(text="⚠️ 7d EN", callback_data="adm_edit_remarket_remarketing_reminder_7_en")
    builder.button(text="⚠️ 3d LV", callback_data="adm_edit_remarket_remarketing_reminder_3_lv")
    builder.button(text="⚠️ 3d RU", callback_data="adm_edit_remarket_remarketing_reminder_3_ru")
    builder.button(text="⚠️ 3d EN", callback_data="adm_edit_remarket_remarketing_reminder_3_en")
    builder.button(text="🚨 1d LV", callback_data="adm_edit_remarket_remarketing_reminder_1_lv")
    builder.button(text="🚨 1d RU", callback_data="adm_edit_remarket_remarketing_reminder_1_ru")
    builder.button(text="🚨 1d EN", callback_data="adm_edit_remarket_remarketing_reminder_1_en")
    builder.button(text="💔 Winback LV", callback_data="adm_edit_remarket_remarketing_winback_lv")
    builder.button(text="💔 Winback RU", callback_data="adm_edit_remarket_remarketing_winback_ru")
    builder.button(text="💔 Winback EN", callback_data="adm_edit_remarket_remarketing_winback_en")
    builder.button(text="⏱ Trigger dienas", callback_data="adm_edit_remarket_remarketing_winback_trigger_days")
    builder.button(text="🎁 Bonus dienas", callback_data="adm_edit_remarket_remarketing_winback_bonus_days")
    builder.button(text="⌛ Offer stundas", callback_data="adm_edit_remarket_remarketing_offer_hours")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_send_marketing")
    builder.adjust(3, 3, 3, 3, 3, 3, 1)
    return builder.as_markup()


@router.callback_query(F.data == "adm_send_marketing")
async def adm_send_marketing_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    now = datetime.utcnow()
    all_users = await db.get_all_users_stats()
    active = [u for u in all_users if u.get("is_active") and u.get("expires_at") and datetime.fromisoformat(u["expires_at"]) > now]
    never_bought = [u for u in all_users if not u.get("plan_key") or u.get("plan_key") == ""]
    never_messaged = await db.get_never_messaged_users()
    expired_5 = await db.get_expired_within_days(1, 5)
    expired_old = await db.get_expired_older_than_days(5)
    one_time = await db.get_one_time_buyers()
    expiring_soon = await db.get_users_expiring_soon(7)
    ref_pending = await db.get_referral_active_users()

    counts = {
        "all": len(all_users), "active": len(active), "never_bought": len(never_bought),
        "never_messaged": len(never_messaged), "expired_5": len(expired_5), "expired_old": len(expired_old),
        "one_time": len(one_time), "expiring_soon": len(expiring_soon), "ref_pending": len(ref_pending),
    }

    await callback.message.edit_text(
        "📤 *Marketing — Auditorija*\n\n"
        "Izvēlies grupu → ievadi tekstu → izsūtīts!",
        reply_markup=marketing_audience_kb(counts), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "adm_marketing_remarketing")
async def adm_marketing_remarketing(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    trigger_days = await db.get_setting("remarketing_winback_trigger_days") or str(config.WINBACK_TRIGGER_DAYS)
    bonus_days = await db.get_setting("remarketing_winback_bonus_days") or "7"
    offer_hours = await db.get_setting("remarketing_offer_hours") or "72"
    text = (
        "⚙️ *Marketing -> Remarketing*\n\n"
        "Šeit vari redzēt un rediģēt automātiskos retention / win-back tekstus.\n\n"
        "⏰ *Kad sūtas:*\n"
        "• 30d / 7d / 3d / 1d reminderi — katru dienu plkst. 10:00 UTC\n"
        f"• Win-back — pēc *{trigger_days}* dienām kopš abonements beidzies\n\n"
        "🎁 *Pašreizējais win-back piedāvājums:*\n"
        f"• Bonus dienas tekstā: *{bonus_days}*\n"
        f"• Piedāvājuma ilgums: *{offer_hours}h*\n\n"
        "💡 Tekstos vari lietot mainīgos:\n"
        "`{bonus_days}` `{coupon_block}` `{tier_block}` `{tier_name}` `{tier_discount}`\n"
        "`{yearly_discount}` `{course_discount}` `{offer_hours}`"
    )
    await callback.message.edit_text(text, reply_markup=remarketing_settings_kb(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("mkt_aud_"))
async def mkt_audience_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    audience = callback.data.replace("mkt_aud_", "")
    labels = {
        "all": "📢 Visi", "active": "✅ Aktīvie", "never_bought": "👀 Nepirkušie",
        "never_messaged": "🆕 Nekad nav saņēmuši", "expired_5": "❌ Beidzies 1-5d",
        "expired_old": "❌ Beidzies 5+d", "one_time": "1️⃣ 1x pircēji",
        "expiring_soon": "⏰ Beigsies 7d", "ref_pending": "👋 Ref nepircēji",
    }
    await state.set_state(MarketingState.waiting_text)
    await state.update_data(audience=audience)
    await callback.message.edit_text(
        f"✏️ *Auditorija:* {labels.get(audience)}\n\n📝 Ievadi ziņu:\n/cancel", parse_mode="Markdown"
    )
    await callback.answer()


@router.message(MarketingState.waiting_text)
async def mkt_receive_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return

    data = await state.get_data()
    audience = data.get("audience")
    text = message.text
    await state.clear()

    now = datetime.utcnow()
    if audience == "all":
        users = await db.get_all_users_stats()
    elif audience == "active":
        all_u = await db.get_all_users_stats()
        users = [u for u in all_u if u.get("is_active") and u.get("expires_at") and datetime.fromisoformat(u["expires_at"]) > now]
    elif audience == "never_bought":
        all_u = await db.get_all_users_stats()
        users = [u for u in all_u if not u.get("plan_key") or u.get("plan_key") == ""]
    elif audience == "never_messaged":
        users = await db.get_never_messaged_users()
    elif audience == "expired_5":
        users = await db.get_expired_within_days(1, 5)
    elif audience == "expired_old":
        users = await db.get_expired_older_than_days(5)
    elif audience == "one_time":
        users = await db.get_one_time_buyers()
    elif audience == "expiring_soon":
        users = await db.get_users_expiring_soon(7)
    elif audience == "ref_pending":
        users = await db.get_referral_active_users()
    else:
        users = []

    await message.answer(f"⏳ Sūtu *{len(users)}* cilvēkiem...", parse_mode="Markdown")

    from bot import plans_keyboard
    sent, failed = 0, 0
    campaign = f"manual_{audience}_{int(now.timestamp())}"

    for user in users:
        try:
            await message.bot.send_message(
                user['user_id'], text, reply_markup=plans_keyboard(user.get("lang", "ru")), parse_mode="Markdown"
            )
            await db.mark_marketing_sent(user['user_id'], campaign)
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ *Nosūtīts: {sent}* | ❌ *Neizdevās: {failed}*", reply_markup=admin_menu_kb(), parse_mode="Markdown")


# ─── RECEIVE TEXT (reminders/marketing settings) ───

@router.callback_query(F.data.startswith("adm_edit_remarket"))
async def adm_edit_remarket_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.replace("adm_edit_remarket_", "")
    current = await db.get_setting(key) or "—"
    await state.set_state(EditState.waiting_text)
    await state.update_data(edit_key=key)
    await callback.message.edit_text(f"✏️ *Pašreizējais:*\n\n{current}\n\n📝 Ievadi jauno:\n/cancel", parse_mode="Markdown")
    await callback.answer()


@router.message(EditState.waiting_text)
async def adm_receive_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    data = await state.get_data()
    key = data.get("edit_key")
    if not key:
        await state.clear()
        await message.answer("❌ Nav atrasta rediģējamā vērtība.", reply_markup=admin_menu_kb())
        return

    numeric_settings = {
        "remarketing_winback_trigger_days",
        "remarketing_winback_bonus_days",
        "remarketing_offer_hours",
        "remarketing_reminder_bonus_days",
        "remarket_after_expire_days",
    }
    value = (message.text or "").strip()
    if key in numeric_settings:
        if not value.isdigit():
            await message.answer("❌ Šeit jāievada vesels skaitlis.", parse_mode=None)
            return
        if int(value) < 0:
            await message.answer("❌ Skaitlim jābūt 0 vai lielākam.", parse_mode=None)
            return
    else:
        value = message.text

    await db.set_setting(key, value)
    await state.clear()
    await message.answer(f"✅ Saglabāts! `{key}`", reply_markup=admin_menu_kb(), parse_mode="Markdown")


# ─── EDIT PRICES ───

@router.callback_query(F.data == "adm_edit_prices")
async def adm_edit_prices(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    lv_url = await db.get_setting("checkout_url_lv") or "— nav iestatīts"
    ru_url = await db.get_setting("checkout_url_ru") or "— nav iestatīts"
    scanner_url = await db.get_setting("checkout_url_scanner_chat") or "— nav iestatīts"
    course_lines = []
    builder = InlineKeyboardBuilder()
    builder.button(text="🇱🇻 Latviešu checkout links", callback_data="adm_checkout_lv")
    builder.button(text="🇷🇺 Русский checkout links", callback_data="adm_checkout_ru")
    builder.button(text="📡 Scanner checkout links", callback_data="adm_checkout_scanner_chat")
    for key, course in config.COURSES.items():
        name = course["name"].get("lv") if isinstance(course.get("name"), dict) else course.get("name", key)
        url = await db.get_setting(f"course_checkout_url_{key}") or "— nav iestatīts"
        course_lines.append(f"• {name}: `{url}`")
        builder.button(text=f"📚 {name}", callback_data=f"adm_checkout_course_{key}")
    builder.button(text="🔙 Atpakaļ", callback_data="adm_main")
    builder.adjust(1)
    await callback.message.edit_text(
        "🔗 *Checkout linki*\n\n"
        "Šie linki tiek izmantoti pogām, kur lietotājs tiek virzīts uz mājaslapas checkout. Pēc apmaksas mājaslapa sūta webhook botam.\n\n"
        "*VIP čati:*\n"
        f"🇱🇻 LV: `{lv_url}`\n"
        f"🇷🇺 RU: `{ru_url}`\n"
        f"📡 Scanner: `{scanner_url}`\n\n"
        "*Kursi:*\n"
        + "\n".join(course_lines),
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_checkout_"))
async def adm_checkout_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    checkout_code = callback.data.replace("adm_checkout_", "")
    if checkout_code in ("lv", "ru"):
        setting_key = f"checkout_url_{checkout_code}"
        title = f"VIP checkout links ({checkout_code.upper()})"
    elif checkout_code == "scanner_chat":
        setting_key = "checkout_url_scanner_chat"
        title = "Scanner checkout links"
    elif checkout_code.startswith("course_"):
        course_key = checkout_code.replace("course_", "")
        course = config.COURSES.get(course_key)
        if not course:
            await callback.answer("Nav", show_alert=True)
            return
        name = course["name"].get("lv") if isinstance(course.get("name"), dict) else course.get("name", course_key)
        setting_key = f"course_checkout_url_{course_key}"
        title = f"Kursa checkout links: {name}"
    else:
        await callback.answer("Nav", show_alert=True)
        return
    current = await db.get_setting(setting_key) or "— nav iestatīts"
    await state.set_state(EditState.waiting_checkout_url)
    await state.update_data(checkout_setting_key=setting_key, checkout_title=title)
    await callback.message.edit_text(
        f"🔗 *{title}*\n\n"
        f"Pašreizējais:\n`{current}`\n\n"
        "Ievadi jauno mājaslapas checkout linku:\n/cancel",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(EditState.waiting_checkout_url)
async def adm_receive_checkout_url(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    url = message.text.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        await message.answer("❌ Ievadi pilnu linku, piemēram `https://...`", parse_mode="Markdown")
        return
    data = await state.get_data()
    setting_key = data.get("checkout_setting_key") or "checkout_url_lv"
    title = data.get("checkout_title") or setting_key
    await db.set_setting(setting_key, url)
    await state.clear()
    await message.answer(f"✅ {title} saglabāts:\n{url}", reply_markup=admin_menu_kb())


@router.callback_query(F.data.startswith("adm_cprice_"))
async def adm_course_price_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    ckey = callback.data.replace("adm_cprice_", "")
    course = config.COURSES.get(ckey)
    if not course: await callback.answer("Nav"); return
    name = course['name']['ru'] if isinstance(course['name'], dict) else course['name']
    saved = await db.get_setting(f"course_price_{ckey}")
    price = float(saved) if saved else course['price_usdt']
    await state.set_state(EditState.waiting_price)
    await state.update_data(price_plan_key=f"course_{ckey}", is_course=True)
    await callback.message.edit_text(f"📚 *{name}*\n\nPašreizējā: *{price:g} EUR*\n\nIevadi jauno cenu:\n/cancel", parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_price_"))
async def adm_price_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    plan_key = callback.data.replace("adm_price_", "")
    plan = config.PLANS.get(plan_key)
    if not plan:
        await callback.answer("Nav", show_alert=True)
        return
    name = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    await state.set_state(EditState.waiting_price)
    await state.update_data(price_plan_key=plan_key)
    await callback.message.edit_text(
        f"💰 *{name}*\n\nPašreizējā: *{plan.get('price_usdt', 0)} USDT*\n\nIevadi jauno cenu:\n/cancel", parse_mode="Markdown"
    )
    await callback.answer()


@router.message(EditState.waiting_price)
async def adm_receive_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    try:
        new_price = float(message.text.replace(",", "."))
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Ievadi skaitli, piem. `15.50`", parse_mode="Markdown")
        return

    data = await state.get_data()
    plan_key = data.get("price_plan_key")
    is_course = data.get("is_course", False)

    if is_course:
        ckey = plan_key.replace("course_", "")
        course = config.COURSES.get(ckey)
        if not course:
            await state.clear(); return
        old_price = course['price_usdt']
        course['price_usdt'] = new_price
        course['price_usd'] = f"{new_price:.0f} EUR" if new_price == int(new_price) else f"{new_price} EUR"
        await db.set_setting(f"course_price_{ckey}", str(new_price))
        await state.clear()
        await message.answer(f"✅ *Kursa cena mainīta!*\n\n{old_price:g} EUR → *{new_price:g} EUR*", reply_markup=admin_menu_kb(), parse_mode="Markdown")
        return

    plan = config.PLANS.get(plan_key)
    if not plan:
        await state.clear()
        return

    old_price = plan['price_usdt']
    plan['price_usdt'] = new_price
    plan['price_usd'] = f"{new_price:.0f}$" if new_price == int(new_price) else f"{new_price}$"
    await db.set_setting(f"price_{plan_key}", str(new_price))
    await state.clear()
    await message.answer(
        f"✅ *Cena mainīta!*\n\n{old_price} → *{new_price} USDT*", reply_markup=admin_menu_kb(), parse_mode="Markdown"
    )


# ─── GIVEAWAY ADMIN ───

class GiveawayAdminState(StatesGroup):
    waiting_winners = State()
    waiting_days = State()
    waiting_text_lang = State()
    waiting_text = State()

@router.callback_query(F.data == "adm_giveaway")
async def adm_giveaway(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    now = datetime.utcnow()
    current_month = now.strftime("%Y-%m")
    count = await db.get_giveaway_count(current_month)

    winners_raw = await db.get_setting("giveaway_winners_count")
    days_raw = await db.get_setting("giveaway_prize_days")
    chat_lang = await db.get_setting("giveaway_chat_lang") or "ru"
    winners_count = int(winners_raw) if winners_raw and winners_raw.isdigit() else 1
    prize_days = int(days_raw) if days_raw and days_raw.isdigit() else 14

    custom_ru = await db.get_setting("giveaway_winner_text_ru")
    custom_en = await db.get_setting("giveaway_winner_text_en")

    text = (
        f"🎟 *Giveaway iestatījumi*\n\n"
        f"📅 Šī mēneša dalībnieki: *{count}*\n"
        f"🏆 Uzvarētāju skaits: *{winners_count}*\n"
        f"📅 Balvas dienas: *{prize_days}*\n"
        f"💬 Čata paziņojuma valoda: *{chat_lang.upper()}*\n"
        f"⏰ Izloze: *Katra mēneša 1. datumā 14:00 (Rīgas)*\n\n"
        f"📝 Custom winner teksts RU: {'✅ Iestatīts' if custom_ru else '— default'}\n"
        f"📝 Custom winner teksts EN: {'✅ Iestatīts' if custom_en else '— default'}"
    )
    b = InlineKeyboardBuilder()
    b.button(text=f"🏆 Uzvarētāju sk. ({winners_count})", callback_data="adm_gw_winners")
    b.button(text=f"📅 Balvas dienas ({prize_days})", callback_data="adm_gw_days")
    b.button(text=f"💬 Čata valoda ({chat_lang.upper()})", callback_data="adm_gw_chat_lang")
    b.button(text="📝 Winner teksts (RU)", callback_data="adm_gw_text_ru")
    b.button(text="📝 Winner teksts (EN)", callback_data="adm_gw_text_en")
    b.button(text="🔄 Atiestatīt tekstus", callback_data="adm_gw_reset_text")
    b.button(text="🔙 Atpakaļ", callback_data="adm_main")
    b.adjust(2, 1, 2, 1, 1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "adm_gw_chat_lang")
async def adm_gw_chat_lang(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    current = await db.get_setting("giveaway_chat_lang") or "ru"
    new_lang = "en" if current == "ru" else "ru"
    await db.set_setting("giveaway_chat_lang", new_lang)
    await callback.answer(f"✅ Čata valoda: {new_lang.upper()}")
    # Refresh giveaway menu
    await adm_giveaway(callback)

@router.callback_query(F.data == "adm_gw_winners")
async def adm_gw_winners(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(GiveawayAdminState.waiting_winners)
    await callback.message.edit_text(
        "🏆 *Cik uzvarētāju katru mēnesi?*\n\nIevadi skaitli (piem. 1, 2, 3):\n/cancel lai atceltu",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(GiveawayAdminState.waiting_winners)
async def gw_receive_winners(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb()); return
    try:
        n = int(message.text.strip())
        if n < 1: raise ValueError
    except ValueError:
        await message.answer("❌ Ievadi pozitīvu skaitli."); return
    await state.clear()
    await db.set_setting("giveaway_winners_count", str(n))
    await message.answer(f"✅ Uzvarētāju skaits: *{n}*", reply_markup=admin_menu_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "adm_gw_days")
async def adm_gw_days(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(GiveawayAdminState.waiting_days)
    await callback.message.edit_text(
        "📅 *Cik dienas balvā?*\n\nIevadi skaitli (piem. 14, 30):\n/cancel lai atceltu",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(GiveawayAdminState.waiting_days)
async def gw_receive_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb()); return
    try:
        d = int(message.text.strip())
        if d < 1: raise ValueError
    except ValueError:
        await message.answer("❌ Ievadi pozitīvu skaitli."); return
    await state.clear()
    await db.set_setting("giveaway_prize_days", str(d))
    await message.answer(f"✅ Balvas dienas: *{d}*", reply_markup=admin_menu_kb(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("adm_gw_text_"))
async def adm_gw_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    lang_code = callback.data.replace("adm_gw_text_", "")
    current = await db.get_setting(f"giveaway_winner_text_{lang_code}") or "— default"
    await state.set_state(GiveawayAdminState.waiting_text)
    await state.update_data(gw_text_lang=lang_code)
    await callback.message.edit_text(
        f"📝 *Winner teksts ({lang_code.upper()})*\n\n"
        f"Pašreizējais:\n{current[:300]}\n\n"
        f"💡 Mainīgie: `{{days}}` = dienas, `{{expires}}` = datums\n\n"
        f"Ievadi jauno tekstu:\n/cancel lai atceltu",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(GiveawayAdminState.waiting_text)
async def gw_receive_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb()); return
    data = await state.get_data()
    lang_code = data.get("gw_text_lang", "ru")
    await state.clear()
    await db.set_setting(f"giveaway_winner_text_{lang_code}", message.text)
    await message.answer(f"✅ Winner teksts ({lang_code.upper()}) saglabāts!", reply_markup=admin_menu_kb())

@router.callback_query(F.data == "adm_gw_reset_text")
async def adm_gw_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await db.set_setting("giveaway_winner_text_ru", "")
    await db.set_setting("giveaway_winner_text_en", "")
    await callback.message.edit_text("✅ Winner teksti atiestatīti uz default.", reply_markup=back_kb("adm_giveaway"))
    await callback.answer()


# ─── DB BACKUP ───

@router.callback_query(F.data == "adm_backup")
async def adm_backup(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer("⏳ Gatavoju backup...")
    try:
        path = await db.backup_db()
        from aiogram.types import FSInputFile
        await callback.message.answer_document(
            FSInputFile(path), caption=f"💾 *DB Backup*\n\n`{path}`", parse_mode="Markdown"
        )
    except Exception as e:
        await callback.message.answer(f"❌ Backup kļūda: `{e}`", parse_mode="Markdown")


# ─── EXCEL EXPORT ───

@router.callback_query(F.data == "adm_export_excel")
async def adm_export_excel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("⏳ Gatavoju Excel...", parse_mode="Markdown")
    await callback.answer()

    try:
        import xlsxwriter
        import io

        users = await db.get_all_users_for_export()
        stats = await db.get_stats()
        referrals = await db.get_referrals_for_export()
        paid_users = [u for u in users if u.get("total_purchases", 0) > 0]

        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})

        hdr = wb.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': '#FFFFFF', 'border': 1, 'align': 'center', 'font_name': 'Arial', 'font_size': 10})
        alt = wb.add_format({'bg_color': '#D6E4F0', 'border': 1, 'font_name': 'Arial', 'font_size': 9})
        nrm = wb.add_format({'bg_color': '#FFFFFF', 'border': 1, 'font_name': 'Arial', 'font_size': 9})

        # Lapa 1: Visi
        ws1 = wb.add_worksheet("Visi lietotāji")
        ws1.freeze_panes(1, 0)
        headers1 = ["User ID", "Username", "Vārds", "Valoda", "Plāns", "Statuss", "Aktivizēts", "Beidzas", "TX", "Pirkumi", "Tērēts", "Reģistrēts"]
        for c, h in enumerate(headers1):
            ws1.write(0, c, h, hdr)
            ws1.set_column(c, c, 14)
        ws1.autofilter(0, 0, 0, len(headers1) - 1)
        for i, u in enumerate(users):
            fmt = alt if i % 2 == 0 else nrm
            row = [u.get("user_id"), f"@{u['username']}" if u.get("username") else "—", u.get("first_name") or "—",
                   (u.get("lang") or "ru").upper(), u.get("plan_name") or "Nav", "Aktīvs" if u.get("is_active") else "Neaktīvs",
                   (u.get("activated_at") or "")[:10] or "—", (u.get("expires_at") or "")[:10] or "—",
                   u.get("tx_hash") or "—", u.get("total_purchases", 0), round(float(u.get("total_spent") or 0), 2),
                   (u.get("created_at") or "")[:10] or "—"]
            for c, v in enumerate(row):
                ws1.write(i + 1, c, v, fmt)

        wb.close()
        buf.seek(0)

        from aiogram.types import BufferedInputFile
        filename = f"export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
        await callback.message.answer_document(
            BufferedInputFile(buf.getvalue(), filename=filename),
            caption=f"📥 *Excel: {len(users)} lietotāji, {len(paid_users)} maksātāji*", parse_mode="Markdown"
        )
        await callback.message.edit_text("🛠 *Admin Panel*", reply_markup=admin_menu_kb(), parse_mode="Markdown")

    except ImportError:
        await callback.message.edit_text("❌ Instalē: `pip install xlsxwriter`", reply_markup=back_kb(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Excel error: {e}")
        await callback.message.edit_text(f"❌ Kļūda: `{e}`", reply_markup=back_kb(), parse_mode="Markdown")


# ─── DEBUG PAYMENT ───

@router.message(Command("debug_payment"))
async def debug_payment(message: Message):
    if not is_admin(message.from_user.id):
        return

    import aiohttp
    wallet = config.CRYPTO_WALLET
    wallet_topic = "0x" + wallet.lower().replace("0x", "").zfill(64)

    text = f"🔍 *Debug: BSC pārbaude*\n\n📋 Wallet:\n`{wallet}`\n📋 USDT Contract:\n`{config.USDT_CONTRACT}`\n\n"

    # Test MegaNode first
    api_key = getattr(config, 'MEGANODE_API_KEY', '')
    if api_key:
        try:
            url = f"https://bsc-mainnet.nodereal.io/v1/{api_key}"
            async with aiohttp.ClientSession() as session:
                resp = await session.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=aiohttp.ClientTimeout(total=10))
                data = await resp.json()
            if "result" in data:
                block = int(data["result"], 16)
                text += f"✅ MegaNode: bloks *{block}*\n"
            else:
                text += f"❌ MegaNode kļūda: `{data.get('error', data)}`\n"
        except Exception as e:
            text += f"❌ MegaNode: `{e}`\n"
    else:
        text += "⚠️ MEGANODE\\_API\\_KEY nav iestatīts\n"

    # Test BSC RPC
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post("https://bsc-dataseed.binance.org/", json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=aiohttp.ClientTimeout(total=10))
            data = await resp.json()
        if "result" in data:
            block = int(data["result"], 16)
            text += f"✅ RPC: bloks *{block}*\n"
        else:
            text += f"❌ RPC kļūda: `{data}`\n"
    except Exception as e:
        text += f"❌ RPC: `{e}`\n"

    # Pending
    pending = await db.get_all_pending_payments()
    text += f"\n*Pending ({len(pending)}):*\n"
    for p in pending[:5]:
        text += f"• user={p['user_id']} plan={p['plan_key']} amt={p['amount_usdt']}\n"
    if not pending:
        text += "ℹ️ Nav gaidu\n"

    # Used TX
    async with __import__('aiosqlite').connect(db.db_path) as conn:
        conn.row_factory = __import__('aiosqlite').Row
        async with conn.execute("SELECT tx_hash, user_id FROM used_transactions ORDER BY rowid DESC LIMIT 5") as cur:
            used = [dict(r) for r in await cur.fetchall()]
    text += f"\n*Pēdējie TX:*\n"
    for u in used:
        text += f"• `{u['tx_hash'][:20]}...` user={u['user_id']}\n"
    if not used:
        text += "ℹ️ Nav TX\n"

    await message.answer(text, parse_mode="Markdown")


# ─── MANUAL ADD/REMOVE ───

@router.message(Command("add_user"))
async def add_user_manual(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Izmantošana: /add\\_user [user\\_id] [days]", parse_mode="Markdown")
        return
    try:
        user_id, days = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("❌ Nepareizi parametri.")
        return
    expires = datetime.utcnow() + timedelta(days=days)
    await db.activate_subscription(user_id=user_id, username=None, plan_key="manual",
        plan_name=f"Manual ({days}d)", expires_at=expires,
        tx_hash=f"manual_{user_id}_{int(datetime.utcnow().timestamp())}", amount_usdt=0)
    try:
        link = await bot.create_chat_invite_link(config.CHAT_ID, member_limit=1)
        await bot.send_message(user_id, f"✅ Доступ активирован до {expires.strftime('%d.%m.%Y')}\n\n🔗 {link.invite_link}")
    except Exception:
        pass
    await message.answer(f"✅ Lietotājs {user_id} pievienots uz {days} dienām.")


@router.message(Command("remove_user"))
async def remove_user_manual(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Izmantošana: /remove\\_user [user\\_id]", parse_mode="Markdown")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Nepareizs user_id")
        return
    await db.deactivate_subscription(user_id)
    try:
        await bot.ban_chat_member(config.CHAT_ID, user_id)
        await bot.unban_chat_member(config.CHAT_ID, user_id)
    except Exception:
        pass
    await message.answer(f"✅ {user_id} noņemts.")


@router.message(Command("fix_payment"))
async def fix_payment(message: Message):
    """Labot payment_history summu. Lietošana: /fix_payment [amount]
    Uzstāda VISIEM payment_history kur amount_usdt=10.0 (nepareizā migrācija)"""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "Izmantošana: /fix\\_payment `[correct_amount]`\n\n"
            "Piemērs: `/fix_payment 0.1`\n"
            "Uzstādīs 0.1 USDT visiem ierakstiem kur tagad ir 10.0\n\n"
            "⚠️ Izmanto tikai ja migrācija uzlika nepareizu summu!",
            parse_mode="Markdown"
        )
        return
    try:
        correct = float(parts[1].replace(",", "."))
    except ValueError:
        await message.answer("❌ Nepareizs skaitlis")
        return

    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        # Atrast cik ierakstu ir ar 10.0
        async with conn.execute("SELECT COUNT(*) FROM payment_history WHERE amount_usdt = 10.0") as cur:
            count = (await cur.fetchone())[0]
        if count == 0:
            await message.answer("ℹ️ Nav ierakstu ar 10.0 USDT. Nav ko labot.")
            return
        await conn.execute("UPDATE payment_history SET amount_usdt = ? WHERE amount_usdt = 10.0", (correct,))
        await conn.commit()

    await message.answer(
        f"✅ Izlaboti *{count}* ieraksti: 10.0 → *{correct} USDT*",
        parse_mode="Markdown"
    )

class WithdrawalActionState(StatesGroup):
    waiting_notes = State()
    waiting_rejection_reason = State()


@router.callback_query(F.data == "adm_withdrawals")
async def admin_withdrawals_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    pending = await db.get_pending_withdrawals()
    if pending:
        w = pending[0]
        user_id = w["user_id"]
        username = w.get("username", "Unknown")
        amount = w["amount_usd"]
        address = w["wallet_address"]
        email = w["email"]
        req_id = w["id"]
        requested = datetime.fromisoformat(w["requested_at"]).strftime("%d.%m.%Y %H:%M")

        earnings = await db.get_earnings_breakdown_for_withdrawal(user_id, req_id)
        earnings_text = ""
        for e in earnings[:5]:
            ref_name = e.get("referred_username", f"ID{e['referred_id']}")
            earnings_text += f"• {_safe_text(ref_name)}: {e['commission_usd']:.2f}$\n"
        if len(earnings) > 5:
            earnings_text += f"...un vēl {len(earnings) - 5}\n"

        total_earned = sum(e["commission_usd"] for e in earnings)
        safe_text = (
            f"💸 <b>Withdrawal Request #{req_id}</b>\n\n"
            f"👤 {_safe_text('@' + username)} ({_safe_text(user_id)})\n"
            f"💵 Summa: <b>{amount:.2f}$</b>\n"
            f"📧 {_safe_text(email)}\n"
            f"📋 Adrese:\n<code>{_safe_text(address)}</code>\n"
            f"📅 Pieprasīts: {_safe_text(requested)}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Earnings ({len(earnings)} purchases):</b>\n{earnings_text}\n"
            f"💰 Kopā nopelnīts: <b>{total_earned:.2f}$</b>\n\n"
            f"⏳ Pending: {len(pending)} pieprasījumi"
        )

        b = InlineKeyboardBuilder()
        b.button(text="✅ Apstiprināt", callback_data=f"adm_withdraw_approve_{req_id}")
        b.button(text="❌ Noraidīt", callback_data=f"adm_withdraw_reject_{req_id}")
        if len(pending) > 1:
            b.button(text="⏭ Nākamais", callback_data="adm_withdraw_pending")
        b.button(text="🔙 Atpakaļ", callback_data="adm_withdrawals")
        b.adjust(2, 1, 1)

        await callback.message.edit_text(
            _trim_for_telegram(safe_text),
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    history = await db.get_all_withdrawal_history()
    if history:
        rows = []
        for w in history[:20]:
            date = datetime.fromisoformat(w["processed_at"]).strftime("%d.%m")
            status_emoji = "✅" if w["status"] == "approved" else "❌"
            username = w.get("username", "Unknown")
            rows.append(f"{status_emoji} {_safe_text(date)} — {_safe_text('@' + username)} — {w['amount_usd']:.0f}$")

        safe_text = "<b>Withdrawal History</b>\n\n" + "\n".join(rows)
        b = InlineKeyboardBuilder()
        b.button(text="🔙 Atpakaļ", callback_data="adm_withdrawals")

        await callback.message.edit_text(
            _trim_for_telegram(safe_text),
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = (
        f"💸 <b>Withdrawal Management</b>\n\n"
        f"⏳ Pending: <b>{len(pending)}</b>\n"
        f"✅ Processed (last 30): <b>{len(history[:30])}</b>"
    )

    b = InlineKeyboardBuilder()
    b.button(text=f"⏳ Pending ({len(pending)})", callback_data="adm_withdraw_pending")
    b.button(text="📜 History", callback_data="adm_withdraw_history")
    b.button(text="🔙 Atpakaļ", callback_data="adm_main")
    b.adjust(2, 1)

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()
    return


@router.callback_query(F.data == "adm_withdraw_pending")
async def admin_pending_withdrawals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    pending = await db.get_pending_withdrawals()
    if pending:
        w = pending[0]
        user_id = w["user_id"]
        username = w.get("username", "Unknown")
        amount = w["amount_usd"]
        address = w["wallet_address"]
        email = w["email"]
        req_id = w["id"]
        requested = datetime.fromisoformat(w["requested_at"]).strftime("%d.%m.%Y %H:%M")

        earnings = await db.get_earnings_breakdown_for_withdrawal(user_id, req_id)
        earnings_text = ""
        for e in earnings[:5]:
            ref_name = e.get("referred_username", f"ID{e['referred_id']}")
            earnings_text += f"• {_safe_text(ref_name)}: {e['commission_usd']:.2f}$\n"
        if len(earnings) > 5:
            earnings_text += f"...un vēl {len(earnings) - 5}\n"

        total_earned = sum(e["commission_usd"] for e in earnings)
        safe_text = (
            f"💸 <b>Withdrawal Request #{req_id}</b>\n\n"
            f"👤 {_safe_text('@' + username)} ({_safe_text(user_id)})\n"
            f"💵 Summa: <b>{amount:.2f}$</b>\n"
            f"📧 {_safe_text(email)}\n"
            f"📋 Adrese:\n<code>{_safe_text(address)}</code>\n"
            f"📅 Pieprasīts: {_safe_text(requested)}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Earnings ({len(earnings)} purchases):</b>\n{earnings_text}\n"
            f"💰 Kopā nopelnīts: <b>{total_earned:.2f}$</b>\n\n"
            f"⏳ Pending: {len(pending)} pieprasījumi"
        )

        b = InlineKeyboardBuilder()
        b.button(text="✅ Apstiprināt", callback_data=f"adm_withdraw_approve_{req_id}")
        b.button(text="❌ Noraidīt", callback_data=f"adm_withdraw_reject_{req_id}")
        if len(pending) > 1:
            b.button(text="⏭ Nākamais", callback_data="adm_withdraw_pending")
        b.button(text="🔙 Atpakaļ", callback_data="adm_withdrawals")
        b.adjust(2, 1, 1)

        await callback.message.edit_text(
            _trim_for_telegram(safe_text),
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return


@router.callback_query(F.data.startswith("adm_withdraw_approve_"))
async def admin_approve_withdrawal(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    req_id = int(callback.data.split("_")[-1])
    
    # Iegūst request info
    request = await db.get_withdrawal_request(req_id)
    if not request or request['status'] != 'pending':
        await callback.answer("❌ Request nav atrasts vai jau procesēts", show_alert=True)
        return
    
    # Lūdz notes (optional)
    await state.set_state(WithdrawalActionState.waiting_notes)
    await state.update_data(action="approve", request_id=req_id)
    
    text = (
        f"✅ *Approve Withdrawal #{req_id}*\n\n"
        f"💵 {request['amount_usd']:.2f}$ → `{request['wallet_address']}`\n\n"
        f"📝 Ievadi piezīmes (vai /skip):"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_withdraw_reject_"))
async def admin_reject_withdrawal(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    req_id = int(callback.data.split("_")[-1])
    
    request = await db.get_withdrawal_request(req_id)
    if not request or request['status'] != 'pending':
        await callback.answer("❌ Request nav atrasts", show_alert=True)
        return
    
    await state.set_state(WithdrawalActionState.waiting_rejection_reason)
    await state.update_data(request_id=req_id)
    
    text = (
        f"❌ *Reject Withdrawal #{req_id}*\n\n"
        f"💵 {request['amount_usd']:.2f}$\n\n"
        f"📝 Ievadi noraidīšanas iemeslu:"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@router.message(WithdrawalActionState.waiting_notes)
async def receive_approval_notes(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    await state.clear()
    
    req_id = data['request_id']
    notes = message.text if message.text != "/skip" else ""
    
    # Approve
    await db.approve_withdrawal(req_id, message.from_user.id, notes)
    
    # Iegūst request info lai paziņotu user
    request = await db.get_withdrawal_request(req_id)
    user_id = request['user_id']
    amount = request['amount_usd']
    address = request['wallet_address']
    
    # Paziņo user
    try:
        user = await db.get_user(user_id)
        lang = user.get("lang", "ru") if user else "ru"
        
        notes_text = f"\n\n📝 {notes}" if notes else ""
        
        if lang == "ru":
            user_text = (
                f"🎉 *Выплата одобрена!*\n\n"
                f"💵 Сумма: *{amount:.2f}$*\n"
                f"📋 Адрес: `{address}`\n\n"
                f"✅ Средства будут отправлены в ближайшее время.{notes_text}"
            )
        else:
            user_text = (
                f"🎉 *Payout approved!*\n\n"
                f"💵 Amount: *{amount:.2f}$*\n"
                f"📋 Address: `{address}`\n\n"
                f"✅ Funds will be sent shortly.{notes_text}"
            )
        
        from bot import bot
        await bot.send_message(user_id, user_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await message.answer(
        f"✅ Withdrawal #{req_id} approved!\n💸 {amount:.2f}$ → {address[:20]}...",
        parse_mode="Markdown"
    )


@router.message(WithdrawalActionState.waiting_rejection_reason)
async def receive_rejection_reason(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    await state.clear()
    
    req_id = data['request_id']
    reason = message.text
    
    # Reject
    await db.reject_withdrawal(req_id, message.from_user.id, reason)
    
    # Paziņo user
    request = await db.get_withdrawal_request(req_id)
    user_id = request['user_id']
    amount = request['amount_usd']
    
    try:
        user = await db.get_user(user_id)
        lang = user.get("lang", "ru") if user else "ru"
        
        if lang == "ru":
            user_text = (
                f"❌ *Выплата отклонена*\n\n"
                f"💵 Сумма: *{amount:.2f}$*\n\n"
                f"📝 Причина: {reason}"
            )
        else:
            user_text = (
                f"❌ *Payout rejected*\n\n"
                f"💵 Amount: *{amount:.2f}$*\n\n"
                f"📝 Reason: {reason}"
            )
        
        from bot import bot
        await bot.send_message(user_id, user_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await message.answer(f"❌ Withdrawal #{req_id} rejected.\nReason: {reason}")


@router.callback_query(F.data == "adm_withdraw_history")
async def admin_withdrawal_history(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    history = await db.get_all_withdrawal_history()
    
    if not history:
        text = "📜 *Withdrawal History*\n\nNav vēstures."
    else:
        rows = []
        for w in history[:20]:
            date = datetime.fromisoformat(w['processed_at']).strftime('%d.%m')
            status_emoji = "✅" if w['status'] == 'approved' else "❌"
            username = w.get('username', 'Unknown')
            rows.append(f"{status_emoji} {date} — @{username} — {w['amount_usd']:.0f}$")
        
        text = "📜 *Withdrawal History*\n\n" + "\n".join(rows)
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Atpakaļ", callback_data="adm_withdrawals")
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# BAN MANAGEMENT
# ═══════════════════════════════════════════════════════════════
class BanState(StatesGroup):
    waiting_user_id = State()
    waiting_reason = State()
    waiting_unban_id = State()


@router.callback_query(F.data == "adm_bans")
async def admin_bans_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    banned = await db.get_banned_users()
    
    text = f"🚫 *Ban Management*\n\n📊 Bloķēti: *{len(banned)}*"
    
    b = InlineKeyboardBuilder()
    b.button(text="🚫 Ban lietotāju", callback_data="adm_ban_user")
    b.button(text="✅ Unban lietotāju", callback_data="adm_unban_user")
    b.button(text="📋 Saraksts", callback_data="adm_ban_list")
    b.button(text="🔙 Atpakaļ", callback_data="adm_main")
    b.adjust(2, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "adm_ban_user")
async def start_ban_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(BanState.waiting_user_id)
    await callback.message.edit_text("🚫 *Ban lietotāju*\n\nIevadi user_id:", parse_mode="Markdown")
    await callback.answer()


@router.message(BanState.waiting_user_id)
async def receive_ban_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Nepareizs ID")
        return
    
    await state.update_data(ban_user_id=user_id)
    await state.set_state(BanState.waiting_reason)
    await message.answer(f"🚫 Ban user {user_id}\n\nIevadi iemeslu:")


@router.message(BanState.waiting_reason)
async def receive_ban_reason(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    await state.clear()
    
    user_id = data['ban_user_id']
    reason = message.text
    
    await db.ban_user(user_id, reason, message.from_user.id)
    await message.answer(f"✅ User {user_id} banned.\nReason: {reason}")


@router.callback_query(F.data == "adm_unban_user")
async def start_unban_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(BanState.waiting_unban_id)
    await callback.message.edit_text("✅ *Unban lietotāju*\n\nIevadi user_id:", parse_mode="Markdown")
    await callback.answer()


@router.message(BanState.waiting_unban_id)
async def receive_unban_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Nepareizs ID")
        return
    
    await db.unban_user(user_id)
    await message.answer(f"✅ User {user_id} unbanned")


@router.callback_query(F.data == "adm_ban_list")
async def show_ban_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    banned = await db.get_banned_users()
    
    if not banned:
        text = "📋 *Banned Users*\n\nNav bloķēto lietotāju."
    else:
        rows = []
        for b in banned[:20]:
            username = b.get('username', 'Unknown')
            reason = b.get('reason', 'No reason')[:30]
            rows.append(f"• @{username} (`{b['user_id']}`)\n  {reason}")
        
        text = "📋 *Banned Users*\n\n" + "\n\n".join(rows)
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Atpakaļ", callback_data="adm_bans")
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# ADMIN LOYALTY HANDLERS
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_loyalty_stats")
async def show_loyalty_stats(callback: CallbackQuery):
    """Show loyalty statistics dashboard"""
    
    # Get stats no user_loyalty tabulas
    users_by_tier = await db.get_users_by_tier()
    total_bonuses = await db.get_total_bonuses_given()
    
    # Count courses granted
    all_courses = await db.fetch_all("SELECT COUNT(*) as count FROM course_grants")
    courses_count = all_courses[0]['count'] if all_courses else 0
    
    # Kopējais aktīvo lietotāju skaits
    now = datetime.utcnow().isoformat()
    all_active = await db.fetch_all(
        "SELECT COUNT(*) as count FROM users WHERE is_active = 1 AND expires_at > ?", (now,)
    )
    total_active = all_active[0]['count'] if all_active else 0
    
    # Kopējais reģistrēto lietotāju skaits
    all_users = await db.fetch_all("SELECT COUNT(*) as count FROM users")
    total_registered = all_users[0]['count'] if all_users else 0
    
    # Lietotāji user_loyalty tabulā
    loyalty_tracked = await db.fetch_all("SELECT COUNT(*) as count FROM user_loyalty")
    tracked_count = loyalty_tracked[0]['count'] if loyalty_tracked else 0
    
    # Build tier distribution — pieskaitīt netracked lietotājus kā rookie
    tier_counts = {tier: 0 for tier in config.LOYALTY_TIERS.keys()}
    for row in users_by_tier:
        if row['current_tier'] in tier_counts:
            tier_counts[row['current_tier']] = row['count']
    
    # Lietotāji kas nav user_loyalty tabulā = rookie
    untracked = total_active - tracked_count
    if untracked > 0:
        tier_counts['rookie'] += untracked
    
    total_in_tiers = sum(tier_counts.values())
    
    text = "📊 *LOYALTY STATISTIKA*\n\n━━━━━━━━━━━━━━━━\n\n👥 *Sadalījums pa līmeņiem:*\n"
    
    for tier_name in ['legend', 'master', 'elite', 'pro', 'active', 'rookie']:
        tier_data = config.LOYALTY_TIERS[tier_name]
        emoji = tier_data.get('emoji', '')
        count = tier_counts.get(tier_name, 0)
        percentage = (count / total_in_tiers * 100) if total_in_tiers > 0 else 0
        
        bar_length = 15
        filled = int(percentage / 100 * bar_length)
        bar = "▓" * filled + "░" * (bar_length - filled)
        
        text += f"\n{emoji} *{tier_name.upper()}*: {count} ({percentage:.0f}%)\n{bar}\n"
    
    text += (
        f"\n━━━━━━━━━━━━━━━━\n\n"
        f"💰 Bonus dienas piešķirtas: *{total_bonuses}*\n"
        f"🎓 Kursi dāvināti: *{courses_count}*\n"
        f"✅ Aktīvie abonenti: *{total_active}*\n"
        f"👥 Reģistrēti kopā: *{total_registered}*\n"
        f"📊 Loyalty tracked: *{tracked_count}*/{total_active}"
    )
    
    b = InlineKeyboardBuilder()
    b.button(text="🏷  Pending Tags", callback_data="adm_pending_tags")
    b.button(text="🎟  Coupons", callback_data="adm_coupons_stats")
    b.button(text="📋  Survey Responses", callback_data="adm_survey_responses")
    b.button(text="🔍  Kanāla audits", callback_data="adm_channel_audit")
    b.button(text="🔙  Atpakaļ", callback_data="adm_main")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "adm_channel_audit")
async def channel_audit(callback: CallbackQuery, bot: Bot):
    """Pārbauda kanāla dalībniekus pret DB — atrast 'ghost' lietotājus"""
    if not is_admin(callback.from_user.id):
        return
    
    await callback.answer("⏳ Pārbaudu kanāla dalībniekus...")
    
    # Iegūt visus aktīvos no DB
    now = datetime.utcnow().isoformat()
    active_users = await db.fetch_all(
        "SELECT user_id, username, plan_name, expires_at, is_friend FROM users WHERE is_active = 1 AND expires_at > ?",
        (now,)
    )
    friends = await db.fetch_all(
        "SELECT user_id, username FROM users WHERE is_friend = 1"
    )
    all_db_users = await db.fetch_all("SELECT user_id, username, is_active, is_friend, plan_key FROM users")
    
    active_ids = {u['user_id'] for u in active_users}
    friend_ids = {f['user_id'] for f in friends}
    
    # Pārbaudīt katru DB lietotāju vai ir kanālā
    in_channel = []
    not_in_channel = []
    ghosts = []  # Kanālā bet nav ne aktīvs ne friend
    
    for u in all_db_users:
        uid = u['user_id']
        try:
            member = await bot.get_chat_member(config.CHAT_ID, uid)
            is_member = member.status in ('member', 'administrator', 'creator')
        except:
            is_member = False
        
        if is_member and uid not in active_ids and uid not in friend_ids:
            ghosts.append(u)
    
    # Neaktīvie kas nav kanālā bet ir DB
    no_sub = [u for u in all_db_users if u['user_id'] not in active_ids and u['user_id'] not in friend_ids and not u.get('plan_key')]
    
    text = (
        f"🔍 *Kanāla audits*\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"✅ Aktīvie abonenti: *{len(active_ids)}*\n"
        f"👫 Friends: *{len(friend_ids)}*\n"
        f"👥 Reģistrēti DB: *{len(all_db_users)}*\n\n"
    )
    
    if ghosts:
        text += f"⚠️ *Kanālā BEZ abonementa/friend ({len(ghosts)}):*\n\n"
        for g in ghosts[:15]:
            uname = f"@{g['username']}" if g.get('username') else f"ID {g['user_id']}"
            text += f"  • {uname} (`{g['user_id']}`)\n"
        if len(ghosts) > 15:
            text += f"  ... un vēl {len(ghosts) - 15}\n"
        text += "\n_Šie lietotāji ir kanālā bet nav ne aktīvi ne friend sarakstā._\n"
    else:
        text += "✅ *Nav ghost lietotāju — viss kārtībā!*\n"
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙  Atpakaļ", callback_data="adm_loyalty_stats")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "adm_pending_tags")
async def show_pending_tags(callback: CallbackQuery):
    """Show pending tag updates"""
    
    pending = await db.get_pending_tag_updates()
    if pending:
        safe_text = f"<b>PENDING TAG UPDATES</b>\n\nTotal: {len(pending)} users\n\n"
        safe_text += "━━━━━━━━━━━━━━━━\n\n"
        b = InlineKeyboardBuilder()

        for user_row in pending[:10]:
            user_id = user_row["user_id"]
            username = user_row.get("username", f"user_{user_id}")
            tier = user_row["tier"]
            tag_name = user_row["tag_name"]
            tier_data = config.LOYALTY_TIERS.get(tier, {})
            emoji = tier_data.get("emoji", "")

            safe_text += f"{emoji} <b>{_safe_text('@' + username)}</b>\n"
            safe_text += f"   Tag: {_safe_text(tag_name)}\n"
            safe_text += f"   User ID: {_safe_text(user_id)}\n\n"
            b.button(text=f"✅ {username}", callback_data=f"tag_done_{user_id}")

        if len(pending) > 10:
            safe_text += f"\n... and {len(pending) - 10} more\n\n"

        safe_text += (
            "━━━━━━━━━━━━━━━━\n\n"
            "<b>How to set tags:</b>\n"
            "1. Open Telegram -> VIP Chat\n"
            "2. Find user -> View Profile\n"
            "3. Edit -> Member tag\n"
            "4. Set tag as shown above\n"
            "5. Click the button here\n"
        )

        b.button(text="✅ Mark All Done", callback_data="tag_done_all")
        b.button(text="🔙 Back", callback_data="adm_loyalty_stats")
        b.adjust(1)

        await callback.message.edit_text(
            _trim_for_telegram(safe_text),
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return



@router.callback_query(F.data.startswith("tag_done_"))
async def mark_tag_done(callback: CallbackQuery):
    """Mark tag as set"""
    
    if callback.data == "tag_done_all":
        # Mark all as done
        pending = await db.get_pending_tag_updates()
        for user_row in pending:
            await db.mark_tag_updated(user_row['user_id'])
        
        await callback.answer(f"✅ Marked {len(pending)} tags as done")
    else:
        # Mark single user
        user_id = int(callback.data[9:])  # Remove "tag_done_"
        await db.mark_tag_updated(user_id)
        await callback.answer("✅ Tag marked as set!")
    
    # Refresh view
    await show_pending_tags(callback)


@router.callback_query(F.data == "adm_coupons_stats")
async def show_coupons_stats(callback: CallbackQuery):
    """Show coupon statistics — izmanto loyalty_promo_codes tabulu"""
    
    # Aktīvie kuponi (used=0, nav beidzies termiņš)
    now = datetime.utcnow().isoformat()
    active = await db.fetch_all(
        "SELECT COUNT(*) as count FROM loyalty_promo_codes WHERE used = 0 AND expires_at > ?", (now,)
    )
    total_active = active[0]['count'] if active else 0
    
    # Izmantotie
    used = await db.fetch_all("SELECT COUNT(*) as count FROM loyalty_promo_codes WHERE used = 1")
    total_used = used[0]['count'] if used else 0
    
    # Beigušies
    expired = await db.fetch_all(
        "SELECT COUNT(*) as count FROM loyalty_promo_codes WHERE used = 0 AND expires_at <= ?", (now,)
    )
    total_expired = expired[0]['count'] if expired else 0
    
    text = (
        f"🎟 *Promo kodu statistika*\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"✅ Aktīvie: *{total_active}*\n"
        f"🔄 Izmantotie: *{total_used}*\n"
        f"⏰ Beigušies: *{total_expired}*\n"
        f"📊 Kopā: *{total_active + total_used + total_expired}*\n\n"
        f"━━━━━━━━━━━━━━━━"
    )
    
    b = InlineKeyboardBuilder()
    b.button(text="🔍  Skatīt aktīvos", callback_data="adm_view_coupons")
    b.button(text="🗑  Dzēst beigušos", callback_data="adm_cleanup_coupons")
    b.button(text="🔙  Atpakaļ", callback_data="adm_loyalty_stats")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "adm_view_coupons")
async def adm_view_coupons(callback: CallbackQuery):
    """Skatīt aktīvos kuponus"""
    if not is_admin(callback.from_user.id): return
    now = datetime.utcnow().isoformat()
    coupons = await db.fetch_all("""
        SELECT lpc.*, u.username FROM loyalty_promo_codes lpc
        LEFT JOIN users u ON u.user_id = lpc.user_id
        WHERE lpc.used = 0 AND lpc.expires_at > ?
        ORDER BY lpc.created_at DESC LIMIT 20
    """, (now,))
    
    if not coupons:
        await callback.answer("Nav aktīvu kuponu", show_alert=True)
        return
    
    text = f"🔍 *Aktīvie kuponi ({len(coupons)}):*\n\n"
    for c in coupons:
        uname = f"@{c['username']}" if c.get('username') else f"ID {c['user_id']}"
        text += f"• `{c['code']}` — {c['discount_percent']}% → {uname}\n"
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙  Atpakaļ", callback_data="adm_coupons_stats")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "adm_create_coupon")
async def adm_create_coupon(callback: CallbackQuery):
    """Pārnovirza uz esošo promo kodu izveidošanu"""
    if not is_admin(callback.from_user.id): return
    # Izmantojam esošo promo sistēmu
    await callback.answer("Izmanto 🏷 Promo kodi pogu admin panelī", show_alert=True)


@router.callback_query(F.data == "adm_export_survey")
async def adm_export_survey(callback: CallbackQuery):
    """Eksportēt survey atbildes"""
    if not is_admin(callback.from_user.id): return
    responses = await db.get_survey_responses(limit=100)
    if not responses:
        await callback.answer("Nav atbilžu", show_alert=True)
        return
    text = "📊 *Survey atbildes (teksts):*\n\n"
    for r in responses[:15]:
        uname = f"@{r['username']}" if r.get('username') else f"ID {r['user_id']}"
        resp = (r.get('response_text', '') or '')[:100]
        text += f"• {uname}: _{resp}_\n"
    b = InlineKeyboardBuilder()
    b.button(text="🔙  Atpakaļ", callback_data="adm_survey_responses")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()



@router.callback_query(F.data == "adm_cleanup_coupons")
async def cleanup_coupons(callback: CallbackQuery):
    """Manually trigger coupon cleanup"""
    
    await db.cleanup_expired_coupons()
    await callback.answer("✅ Expired coupons cleaned up!")
    await show_coupons_stats(callback)


@router.callback_query(F.data == "adm_survey_responses")
async def show_survey_responses(callback: CallbackQuery):
    """Show recent survey responses"""
    
    responses = await db.get_survey_responses(limit=20)
    if responses:
        safe_text = "<b>SURVEY RESPONSES</b>\n\n"
        safe_text += f"Last {len(responses)} responses:\n\n"
        safe_text += "━━━━━━━━━━━━━━━━\n\n"

        for resp in responses[:10]:
            username = resp.get("username", "Unknown")
            response_type = resp["response_type"]
            custom_text = resp.get("custom_text")
            created_at = resp["created_at"]

            dt = datetime.fromisoformat(created_at)
            date_str = dt.strftime("%d.%m %H:%M")

            if response_type == "expensive":
                icon = "💸"
                reason = "Too expensive"
            elif response_type == "content":
                icon = "📉"
                reason = "Not enough value"
            elif response_type == "time":
                icon = "⏰"
                reason = "No time"
            elif response_type == "confused":
                icon = "❓"
                reason = "Didn't understand"
            else:
                icon = "📝"
                reason = "Custom"

            safe_text += f"{icon} <b>{_safe_text('@' + username)}</b> - {_safe_text(date_str)}\n"
            safe_text += f"   {_safe_text(reason)}\n"
            if custom_text:
                preview = custom_text[:50] + ("..." if len(custom_text) > 50 else "")
                safe_text += f"   💬 <i>{_safe_text(preview)}</i>\n"
            safe_text += "\n"

        if len(responses) > 10:
            safe_text += f"... and {len(responses) - 10} more\n\n"

        safe_text += "━━━━━━━━━━━━━━━━\n"

        b = InlineKeyboardBuilder()
        b.button(text="🔙 Back", callback_data="adm_loyalty_stats")
        b.adjust(1)
        await callback.message.edit_text(
            _trim_for_telegram(safe_text),
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return


@router.callback_query(F.data == "adm_settings")
async def show_admin_settings(callback: CallbackQuery):
    """Show admin settings"""
    
    # Get current public lang
    pub_lang = await db.get_setting('public_announcement_lang') or 'ru'
    flag_map = {'ru': '🇷🇺', 'en': '🇬🇧', 'lv': '🇱🇻'}
    safe_text = (
        "⚙️ <b>BOT SETTINGS</b>\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📢 <b>Public Announcements Language</b>\n\n"
        f"Current: {flag_map.get(pub_lang, '🇷🇺')} <b>{_safe_text(pub_lang.upper())}</b>\n\n"
        "Used for tier achievements in VIP chat.\n"
        "Private messages stay in user's language.\n\n"
        "━━━━━━━━━━━━━━━━"
    )

    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский (RU)", callback_data="set_pub_lang_ru")
    b.button(text="🇬🇧 English (EN)", callback_data="set_pub_lang_en")
    b.button(text="🇱🇻 Latviešu (LV)", callback_data="set_pub_lang_lv")
    b.button(text="🔙 Back", callback_data="adm_main")
    b.adjust(1)

    await callback.message.edit_text(safe_text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()
    return



@router.callback_query(F.data.startswith("set_pub_lang_"))
async def set_public_language(callback: CallbackQuery):
    """Set public announcement language"""
    
    lang = callback.data[13:]  # Remove "set_pub_lang_"
    
    await db.set_setting('public_announcement_lang', lang)
    
    await callback.answer(f"✅ Public language set to {lang.upper()}")
    await show_admin_settings(callback)


@router.message(Command("admin_set_tier"))
async def admin_set_tier_command(message: Message):
    """Manually set user's tier
    Usage: /admin_set_tier @username tier_name"""
    
    parts = message.text.split()
    
    if len(parts) < 3:
        await message.answer("Usage: /admin_set_tier @username tier_name")
        return
    
    username = parts[1].replace('@', '')
    tier = parts[2].lower()
    
    if tier not in config.LOYALTY_TIERS:
        await message.answer(f"❌ Invalid tier. Valid: {', '.join(config.LOYALTY_TIERS.keys())}")
        return
    
    # Find user by username
    user = await db.fetch_one("SELECT user_id FROM users WHERE username = ?", (username,))
    
    if not user:
        await message.answer(f"❌ User @{username} not found")
        return
    
    user_id = user['user_id']
    
    # Update tier
    await db.update_user_loyalty(user_id, tier, 0)
    
    tier_data = config.LOYALTY_TIERS[tier]
    emoji = tier_data.get('emoji', '')
    
    await message.answer(f"✅ Set @{username} tier to {emoji} {tier}")



@router.message(Command("admin_add_days"))
async def admin_add_days_command(message: Message):
    """Manually add bonus days
    Usage: /admin_add_days @username days"""
    
    parts = message.text.split()
    
    if len(parts) < 3:
        await message.answer("Usage: /admin_add_days @username days")
        return
    
    username = parts[1].replace('@', '')
    
    try:
        days = int(parts[2])
    except ValueError:
        await message.answer("❌ Days must be a number")
        return
    
    # Find user
    user = await db.fetch_one("SELECT user_id FROM users WHERE username = ?", (username,))
    
    if not user:
        await message.answer(f"❌ User @{username} not found")
        return
    
    user_id = user['user_id']
    
    # Add days
    await db.add_bonus_days(user_id, days, "Admin manual bonus")
    
    await message.answer(f"✅ Added {days} days to @{username}")


# ─── MAKSĀJUMU VĒSTURE ───

@router.callback_query(F.data == "adm_payments_menu")
async def adm_payments_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    b = InlineKeyboardBuilder()
    b.button(text="📅  Šodien", callback_data="adm_pay_today")
    b.button(text="📅  7 dienas", callback_data="adm_pay_7d")
    b.button(text="📅  30 dienas", callback_data="adm_pay_30d")
    b.button(text="📅  Viss laiks", callback_data="adm_pay_all")
    b.button(text="🔙  Atpakaļ", callback_data="adm_main")
    b.adjust(2, 2, 1)
    await callback.message.edit_text("🧾 *Maksājumu vēsture*\n\nIzvēlies periodu:", reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_pay_"))
async def adm_payments_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    
    period = callback.data.replace("adm_pay_", "")
    now = datetime.utcnow()
    
    if period == "today":
        since = now.strftime("%Y-%m-%d")
        title = "Šodien"
    elif period == "7d":
        since = (now - timedelta(days=7)).isoformat()
        title = "7 dienas"
    elif period == "30d":
        since = (now - timedelta(days=30)).isoformat()
        title = "30 dienas"
    else:
        since = "2020-01-01"
        title = "Viss laiks"

    payments = await db.fetch_all("""
        SELECT ph.*, u.username, u.email
        FROM payment_history ph
        LEFT JOIN users u ON u.user_id = ph.user_id
        WHERE ph.paid_at >= ?
        ORDER BY ph.paid_at DESC
        LIMIT 50
    """, (since,))

    if not payments:
        text = f"🧾 <b>Maksājumi — {title}</b>\n\nNav maksājumu šajā periodā."
    else:
        total = sum(float(p.get("amount_usdt", 0) or 0) for p in payments)
        text = f"🧾 <b>Maksājumi — {title}</b>\n\n💰 Kopā: <b>{total:.2f} USDT</b> ({len(payments)} maks.)\n\n"

        for p in payments[:20]:
            uname = f"@{p['username']}" if p.get("username") else f"ID {p['user_id']}"
            amount = float(p.get("amount_usdt", 0) or 0)
            plan = p.get("plan_name", p.get("plan_key", "?"))
            date = (p.get("paid_at", "") or "")[:16]
            email = p.get("email", "")
            tx = (p.get("tx_hash", "") or "")[:16]

            text += "━━━━━━━━━━━━━━━━\n"
            text += f"👤 {_safe_text(uname)}\n"
            text += f"📦 {_safe_text(plan)} — <b>{amount:.2f} USDT</b>\n"
            text += f"📅 {_safe_text(date)}\n"
            if email:
                text += f"📧 {_safe_text(email)}\n"
            if tx:
                text += f"🔖 {_safe_text(tx)}...\n"

        if len(payments) > 20:
            text += f"\n... un vēl {len(payments) - 20} maks."

    b = InlineKeyboardBuilder()
    b.button(text="🔙  Atpakaļ", callback_data="adm_payments_menu")
    b.adjust(1)
    await callback.message.edit_text(
        _trim_for_telegram(text),
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()
    return


# ─── PIEŠĶIRT ABONEMENTU ───

class GrantSubState(StatesGroup):
    waiting_plan = State()
    waiting_user = State()


@router.callback_query(F.data == "adm_grant_sub")
async def adm_grant_sub_start(callback: CallbackQuery):
    """Piešķirt abonementu — izvēlēties tarifu"""
    if not is_admin(callback.from_user.id): return
    
    b = InlineKeyboardBuilder()
    for key, plan in config.PLANS.items():
        name = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
        b.button(text=f"{plan['emoji']}  {name} ({plan['days']} d.)", callback_data=f"grant_plan_{key}")
    b.button(text="🔙  Atpakaļ", callback_data="adm_main")
    b.adjust(1)
    
    await callback.message.edit_text(
        "🎁 *Piešķirt abonementu*\n\nIzvēlies tarifu:",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grant_plan_"))
async def adm_grant_plan_selected(callback: CallbackQuery, state: FSMContext):
    """Tarifs izvēlēts — tagad ievadīt @niku vai ID"""
    if not is_admin(callback.from_user.id): return
    
    plan_key = callback.data.replace("grant_plan_", "")
    if plan_key not in config.PLANS:
        await callback.answer("❌ Nav tāda tarifa", show_alert=True)
        return
    
    plan = config.PLANS[plan_key]
    name = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    
    await state.set_state(GrantSubState.waiting_user)
    await state.update_data(grant_plan_key=plan_key)
    
    await callback.message.edit_text(
        f"🎁 *Piešķirt: {plan['emoji']} {name}* ({plan['days']} dienas)\n\n"
        f"Ievadi *@username* vai *user\\_id*:\n"
        f"/cancel lai atceltu",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(GrantSubState.waiting_user)
async def adm_grant_receive_user(message: Message, state: FSMContext, bot: Bot):
    """Saņem lietotāja @niku vai ID un piešķir abonementu"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Atcelts.", reply_markup=admin_menu_kb())
        return
    
    data = await state.get_data()
    plan_key = data.get("grant_plan_key")
    await state.clear()
    
    if not plan_key or plan_key not in config.PLANS:
        await message.answer("❌ Kļūda — tarifs nav atrasts.", reply_markup=admin_menu_kb())
        return
    
    plan = config.PLANS[plan_key]
    
    # Atrast lietotāju
    raw = message.text.strip()
    user_id = None
    display = raw
    
    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        found = await db.get_user_by_username(raw)
        if found:
            user_id = found["user_id"]
            display = f"@{found.get('username', raw)}"
        else:
            await message.answer(
                f"❌ `{raw}` nav atrasts. Lietotājam jāuzsāk bots (/start).",
                parse_mode="Markdown", reply_markup=admin_menu_kb()
            )
            return
    else:
        try:
            user_id = int(raw)
            display = str(user_id)
        except ValueError:
            await message.answer("❌ Nepareizs formāts.", reply_markup=admin_menu_kb())
            return
    
    # Piešķirt abonementu
    now = datetime.utcnow()
    user = await db.get_user(user_id)
    if user and user.get('expires_at'):
        cur_exp = datetime.fromisoformat(user['expires_at'])
        new_exp = (cur_exp if cur_exp > now else now) + timedelta(days=plan['days'])
    else:
        new_exp = now + timedelta(days=plan['days'])
    
    plan_name = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    
    await db.activate_subscription(
        user_id=user_id,
        username=user.get('username') if user else None,
        plan_key=plan_key,
        plan_name=plan_name,
        expires_at=new_exp,
        tx_hash=f"admin_grant_{user_id}_{int(now.timestamp())}",
        amount_usdt=0
    )
    
    # Nosūtīt invite link lietotājam
    invite_status = ""
    try:
        link = await bot.create_chat_invite_link(config.CHAT_ID, member_limit=1)
        ulang = user.get('lang', 'ru') if user else 'ru'
        if ulang == 'ru':
            user_msg = (
                f"🎁 *Подписка активирована!*\n\n"
                f"📦 Тариф: *{plan_name}*\n"
                f"📅 Активна до: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                f"🔗 [Вступить в канал]({link.invite_link})"
            )
        else:
            user_msg = (
                f"🎁 *Subscription activated!*\n\n"
                f"📦 Plan: *{plan_name}*\n"
                f"📅 Active until: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                f"🔗 [Join channel]({link.invite_link})"
            )
        await bot.send_message(user_id, user_msg, parse_mode="Markdown")
        invite_status = "✅ Lietotājs informēts + invite nosūtīts"
    except Exception as e:
        invite_status = f"⚠️ Neizdevās nosūtīt: {e}"
    
    await message.answer(
        f"🎁 *Abonements piešķirts!*\n\n"
        f"👤 {display} (`{user_id}`)\n"
        f"📦 {plan['emoji']} {plan_name}\n"
        f"📅 Līdz: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
        f"{invite_status}",
        reply_markup=admin_menu_kb(), parse_mode="Markdown"
    )
