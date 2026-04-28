import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
@dp.callback_query(F.data == "get_access_links")
async def get_access_links(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    active_subs = await db.get_active_user_subscriptions(user_id)
    if not active_subs:
        await callback.answer(
            ui_text(
                lang,
                "Tev nav aktÄ«vu piekÄ¼uvju.",
                "Ð£ Ñ‚ÐµÐ±Ñ Ð½ÐµÑ‚ Ð°ÐºÑ‚Ð¸Ð²Ð½Ñ‹Ñ… Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð¾Ð².",
                "You do not have any active access.",
            ),
            show_alert=True,
        )
        return

    rows = []
    for sub in active_subs:
        try:
            expires_at = datetime.fromisoformat(sub["expires_at"])
        except Exception:
            continue
        product_meta = resolve_subscription_product(sub.get("product_key") or "", lang)
        if not product_meta and (sub.get("chat_id") or sub.get("chat_link")):
            product_meta = {
                "product_key": sub.get("product_key") or "website_subscription",
                "chat_id": sub.get("chat_id", 0) or 0,
                "chat_link": sub.get("chat_link", "") or "",
            }
        invite = await invite_text_for_product(user_id, lang, product_meta, expires_at)
        if not invite:
            continue
        product_name = sub.get("product_name") or sub.get("product_key") or "Access"
        rows.append(
            ui_text(
                lang,
                f"ðŸ“¦ *{product_name}*\nðŸ“… AktÄ«vs lÄ«dz: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                f"ðŸ“¦ *{product_name}*\nðŸ“… ÐÐºÑ‚Ð¸Ð²Ð½Ð¾ Ð´Ð¾: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                f"ðŸ“¦ *{product_name}*\nðŸ“… Active until: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
            )
        )

    if not rows:
        await callback.answer(
            ui_text(
                lang,
                "NeizdevÄs izveidot piekÄ¼uves linku.",
                "ÐÐµ ÑƒÐ´Ð°Ð»Ð¾ÑÑŒ ÑÐ¾Ð·Ð´Ð°Ñ‚ÑŒ ÑÑÑ‹Ð»ÐºÑƒ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°.",
                "Failed to create an access link.",
            ),
            show_alert=True,
        )
        return

    text = ui_text(
        lang,
        "ðŸ”— *Tavi jaunie piekÄ¼uves linki*\n\n",
        "ðŸ”— *Ð¢Ð²Ð¾Ð¸ Ð½Ð¾Ð²Ñ‹Ðµ ÑÑÑ‹Ð»ÐºÐ¸ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°*\n\n",
        "ðŸ”— *Your new access links*\n\n",
    ) + "\n\n".join(rows)
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer(
        ui_text(
            lang,
            "Jaunie linki nosÅ«tÄ«ti.",
            "ÐÐ¾Ð²Ñ‹Ðµ ÑÑÑ‹Ð»ÐºÐ¸ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð»ÐµÐ½Ñ‹.",
            "Fresh access links sent.",
        )
    )

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REFERRAL_BONUS_DAYS = 10  # Chat subscription bonus
SUPPORTED_LANGS = ("ru", "en", "lv")
DEFAULT_LANG = "lv"
VIP_CHANNEL_LANGS = ("lv", "ru")
VIP_CHANNEL_LABELS = {
    "lv": "🇱🇻 Latviešu",
    "ru": "🇷🇺 Русский",
}
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

TEXTS = {
    "ru": {
        "welcome": "👋 Привет, {name}!\n\n🔐 Это эксклюзивный платный чат трейдеров.\n\n📋 *Выбери свой тарифный план:*",
        "active_sub": "👋 Привет, {name}!\n\n✅ Подписка активна до *{expires}*\n📦 Тариф: *{plan}*\n⏳ Осталось: *{days}* дн.",
        "inactive_welcome": "👋 Привет, {name}!\n\n❌ Сейчас у тебя нет активной подписки.\n\n📋 *Выбери продукт:*",
        "inactive_welcome_note": "❌ Сейчас у тебя нет активной подписки.",
        "choose_plan": "📋 *Выбери свой тарифный план:*",
        "payment_title": "{emoji} *{name}*\n\n💰 Цена: *{price}* ({usdt} USDT)\n📅 Срок: *{days} дней*\n\n━━━━━━━━━━━━━━━━\n📤 Отправь ровно *{usdt} USDT (BEP-20)* на:\n\n`{wallet}`\n\n━━━━━━━━━━━━━━━━\n⚠️ Важно:\n• Только *USDT BEP-20* (сеть BSC)\n• Сумма: *{usdt} USDT*\n• После отправки нажми кнопку ниже",
        "paid_ok": "✅ *Платёж подтверждён!*\n\n📦 Тариф: *{name}*\n📅 Активен до: *{expires}*\n🔖 TX: `{tx}`",
        "paid_fail": "❌ *Платёж не найден*\n\nУбедись что отправил ровно *{usdt} USDT (BEP-20)*",
        "status_active": "🟢 *Статус подписки*\n\n📅 Истекает: {expires}\n⏳ Осталось: {days} дней\n📦 Тариф: {plan}",
        "status_none": "❌ У тебя нет активной подписки.\n\nИспользуй /start чтобы купить.",
        "remind_3": "⚠️ *Подписка истекает через 3 дня!*\n\n📅 Дата: {expires}\n\nПродли подписку:",
        "remind_1": "🚨 *Подписка истекает ЗАВТРА!*\n\n📅 Дата: {expires}\n\nПродли:",
        "kicked": "😔 *Подписка истекла*\n\nТы был удалён из канала.\nДля восстановления купи подписку:",
        "btn_paid": "✅ Я оплатил",
        "btn_qr": "📷 QR код",
        "btn_back": "🔙 Назад",
        "qr_caption": "📷 *QR код для оплаты*\n\n📋 Адрес: `{wallet}`\n💰 Сумма: *{usdt} USDT (BEP-20)*\n⚠️ Отсканируй QR → введи сумму вручную: *{usdt} USDT*\n🔗 Сеть: *BSC (BEP-20)*",
        "invite": "\n\n🔗 [Вступить в канал]({link})",
        
        "referral_info": "👥 *Реферальная программа*\n\n🎁 За каждую покупку друга ты получаешь *+10 бонусных дней*.\n\n📌 Твоя ссылка:\n`{ref_link}`\n\n📊 Приглашено: *{count}*\n🎁 Получено бонусов: *{bonuses}*",
        
        "my_referrals": "👥 *Мои рефералы*\n\n📊 Всего: *{count}*\n🎁 Бонусов: *{bonuses}* × 10 дней\n📅 Итого: *{total_days}* дней\n\n{referral_list}",
        "my_referrals_empty": "👥 *Мои рефералы*\n\nТы ещё никого не пригласил.",
        "referral_row_bonus": "✅ {name} — бонус получен",
        "referral_row_pending": "⏳ {name} — ожидает оплаты",
        "referral_bonus_received": "🎉 *Бонус получен!*\n\nТвой друг оформил подписку — тебе *+10 дней*!\n📅 Активна до: *{expires}*",
        
        "referral_earnings": "🎁 *Бонусные дни referral*\n\nReferral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_button": "🎁 Бонусные дни",
        "earnings_button": "📊 История referral",
        "withdrawal_history_button": "📜 История bonus days",
        "earnings_list": "🎁 *История referral*\n\nПрограмма referral теперь работает только с бонусными днями.",
        "earnings_empty": "🎁 *История referral*\n\nПрограмма referral теперь работает только с бонусными днями.",
        "earnings_row": "• {date} — {name}",
        "withdrawal_request": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_enter_address": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_confirm": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_submitted": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_approved": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_rejected": "🎁 Referral программа теперь использует только бонусные дни для чатов.",
        "withdrawal_history": "🎁 *История referral*\n\nПрограмма referral теперь работает только с бонусными днями.",
        "withdrawal_history_empty": "🎁 *История referral*\n\nПрограмма referral теперь работает только с бонусными днями.",
        "withdrawal_row_pending": "⏳ Referral bonus days",
        "withdrawal_row_approved": "✅ Referral bonus days",
        "withdrawal_row_rejected": "❌ Referral bonus days",
        "withdrawal_error_banned": "❌ Денежные выплаты больше недоступны.",
        "withdrawal_error_pending": "ℹ️ Referral программа теперь работает только с бонусными днями.",
        "withdrawal_error_min": "ℹ️ Referral программа теперь работает только с бонусными днями.",
        "withdrawal_error_no_email": "ℹ️ Referral программа теперь работает только с бонусными днями.",
        "withdrawal_error_rate_limit": "ℹ️ Referral программа теперь работает только с бонусными днями.",
        "referral_welcome": "👋 Тебя пригласил друг!\n\n🎁 Когда ты совершишь покупку, друг получит *+10 бонусных дней*.\n\n🔐 Выбери продукт:",
        
        "help": "📖 *Команды:*\n\n/start — Начать\n/status — Статус\n/renew — Продлить\n/language — Язык\n/support — Поддержка\n/id — Мой ID\n/loyalty — Лояльность\n/help — Справка",
        "support": "📩 *Поддержка*\n\nЕсли есть вопросы, напиши: https://t.me/mntrade_support",
        "auto_found": "✅ *Платёж найден автоматически!*\n\n📦 Тариф: *{name}*\n📅 Активен до: *{expires}*\n🔖 TX: `{tx}`\n\n_Обнаружен фоновой проверкой._",
        "upsell": "💡 *Специальное предложение!*\n\nТвоя подписка *{plan}* скоро заканчивается.\n\n🔥 Перейди на *годовой план* — экономия *{save}%*!\n💰 Цена: *{yearly_price} USDT* вместо {monthly_x12}",
    },
    "en": {
        "welcome": "👋 Hello, {name}!\n\n🔐 This is an exclusive paid traders chat.\n\n📋 *Choose your subscription plan:*",
        "active_sub": "👋 Hello, {name}!\n\n✅ Subscription active until *{expires}*\n📦 Plan: *{plan}*\n⏳ Days left: *{days}*",
        "inactive_welcome": "👋 Hello, {name}!\n\n❌ You do not have an active subscription right now.\n\n📋 *Choose a product:*",
        "inactive_welcome_note": "❌ You do not have an active subscription right now.",
        "choose_plan": "📋 *Choose your subscription plan:*",
        "payment_title": "{emoji} *{name}*\n\n💰 Price: *{price}* ({usdt} USDT)\n📅 Duration: *{days} days*\n\n━━━━━━━━━━━━━━━━\n📤 Send exactly *{usdt} USDT (BEP-20)* to:\n\n`{wallet}`\n\n━━━━━━━━━━━━━━━━\n⚠️ Only *USDT BEP-20* (BSC)\n• Amount: *{usdt} USDT*\n• Press button after sending",
        "paid_ok": "✅ *Payment confirmed!*\n\n📦 Plan: *{name}*\n📅 Active until: *{expires}*\n🔖 TX: `{tx}`",
        "paid_fail": "❌ *Payment not found*\n\nMake sure you sent exactly *{usdt} USDT (BEP-20)*",
        "status_active": "🟢 *Subscription*\n\n📅 Expires: {expires}\n⏳ Days left: {days}\n📦 Plan: {plan}",
        "status_none": "❌ No active subscription.\n\nUse /start to purchase.",
        "remind_3": "⚠️ *Subscription expires in 3 days!*\n\n📅 {expires}\n\nRenew:",
        "remind_1": "🚨 *Expires TOMORROW!*\n\n📅 {expires}\n\nRenew now:",
        "kicked": "😔 *Subscription expired*\n\nYou were removed. Purchase to restore:",
        "btn_paid": "✅ I have paid",
        "btn_qr": "📷 QR Code",
        "btn_back": "🔙 Back",
        "qr_caption": "📷 *QR Code*\n\n📋 Address: `{wallet}`\n💰 Amount: *{usdt} USDT (BEP-20)*\n⚠️ Scan QR → enter *{usdt} USDT*\n🔗 Network: *BSC (BEP-20)*",
        "invite": "\n\n🔗 [Join channel]({link})",
        
        "referral_info": "👥 *Referral Program*\n\n🎁 For every friend purchase you receive *+10 bonus days*.\n\n📌 Your link:\n`{ref_link}`\n\n📊 Invited: *{count}*\n🎁 Bonuses received: *{bonuses}*",
        
        "my_referrals": "👥 *My Referrals*\n\n📊 Total: *{count}*\n🎁 Bonuses: *{bonuses}* × 10 days\n📅 Total: *{total_days}* days\n\n{referral_list}",
        "my_referrals_empty": "👥 *My Referrals*\n\nYou haven't invited anyone yet.",
        "referral_row_bonus": "✅ {name} — bonus received",
        "referral_row_pending": "⏳ {name} — waiting",
        "referral_bonus_received": "🎉 *Bonus received!*\n\nYour friend subscribed — *+10 days*!\n📅 Active until: *{expires}*",
        
        "referral_earnings": "🎁 *Referral Bonus Days*\n\nThe referral program now uses only bonus days for chats.",
        "withdrawal_button": "🎁 Bonus days",
        "earnings_button": "📊 Referral history",
        "withdrawal_history_button": "📜 Bonus day history",
        "earnings_list": "🎁 *Referral History*\n\nThe referral program now works only with bonus days.",
        "earnings_empty": "🎁 *Referral History*\n\nThe referral program now works only with bonus days.",
        "earnings_row": "• {date} — {name}",
        "withdrawal_request": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_enter_address": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_confirm": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_submitted": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_approved": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_rejected": "🎁 The referral program now uses only bonus days for chats.",
        "withdrawal_history": "🎁 *Referral History*\n\nThe referral program now works only with bonus days.",
        "withdrawal_history_empty": "🎁 *Referral History*\n\nThe referral program now works only with bonus days.",
        "withdrawal_row_pending": "⏳ Referral bonus days",
        "withdrawal_row_approved": "✅ Referral bonus days",
        "withdrawal_row_rejected": "❌ Referral bonus days",
        "withdrawal_error_banned": "❌ Cash payouts are no longer available.",
        "withdrawal_error_pending": "ℹ️ The referral program now works only with bonus days.",
        "withdrawal_error_min": "ℹ️ The referral program now works only with bonus days.",
        "withdrawal_error_no_email": "ℹ️ The referral program now works only with bonus days.",
        "withdrawal_error_rate_limit": "ℹ️ The referral program now works only with bonus days.",
        "referral_welcome": "👋 Invited by a friend!\n\n🎁 When you make a purchase, your friend gets *+10 bonus days*.\n\n🔐 Choose a product:",
        
        "help": "📖 *Commands:*\n\n/start — Start\n/status — Status\n/renew — Renew\n/language — Language\n/support — Support\n/id — My ID\n/loyalty — Loyalty\n/help — Help",
        "support": "📩 *Support*\n\nIf you have questions, write: https://t.me/mntrade_support",
        "auto_found": "✅ *Payment found automatically!*\n\n📦 Plan: *{name}*\n📅 Until: *{expires}*\n🔖 TX: `{tx}`\n\n_Detected by background check._",
        "upsell": "💡 *Special offer!*\n\nYour *{plan}* is ending soon.\n\n🔥 Upgrade to *yearly* — save *{save}%*!\n💰 Price: *{yearly_price} USDT* instead of {monthly_x12}",
    }
}

TEXTS["ru"]["referral_info"] = (
    "👥 *Реферальная программа*\n\n"
    f"🎁 За каждого друга, который оформит покупку: *+{REFERRAL_BONUS_DAYS} дней* бесплатного доступа.\n\n"
    "📌 Твоя ссылка:\n`{ref_link}`\n\n"
    "📊 Приглашено: *{count}*\n🎁 Получено бонусов: *{bonuses}*"
)
TEXTS["en"]["referral_info"] = (
    "👥 *Referral Program*\n\n"
    f"🎁 For every friend who makes a purchase: *+{REFERRAL_BONUS_DAYS} free days*.\n\n"
    "📌 Your link:\n`{ref_link}`\n\n"
    "📊 Invited: *{count}*\n🎁 Bonuses received: *{bonuses}*"
)
TEXTS["ru"]["referral_welcome"] = "👋 Тебя пригласил друг!\n\n🎁 Когда ты оформишь покупку, друг получит *+10 дней* доступа.\n\n🔐 Выбери продукт:"
TEXTS["en"]["referral_welcome"] = "👋 Invited by a friend!\n\n🎁 When you make a purchase, your friend gets *+10 free days*.\n\n🔐 Choose a product:"
TEXTS["lv"] = {
    **TEXTS["en"],
    "welcome": "👋 Sveiks, {name}!\n\n🔐 Šis ir slēgts maksas treideru community.\n\n📋 *Izvēlies abonementa plānu:*",
    "active_sub": "👋 Sveiks, {name}!\n\n✅ Abonements aktīvs līdz *{expires}*\n📦 Plāns: *{plan}*\n⏳ Atlikušas dienas: *{days}*",
    "inactive_welcome": "👋 Sveiks, {name}!\n\n❌ Tev šobrīd nav aktīva abonementa.\n\n📋 *Izvēlies produktu:*",
    "inactive_welcome_note": "❌ Tev šobrīd nav aktīva abonementa.",
    "choose_plan": "📋 *Izvēlies abonementa plānu:*",
    "payment_title": "{emoji} *{name}*\n\n💰 Cena: *{price}* ({usdt} USDT)\n📅 Termiņš: *{days} dienas*\n\n━━━━━━━━━━━━━━━━\n📤 Nosūti tieši *{usdt} USDT (BEP-20)* uz:\n\n`{wallet}`\n\n━━━━━━━━━━━━━━━━\n⚠️ Tikai *USDT BEP-20* (BSC)\n• Summa: *{usdt} USDT*\n• Pēc maksājuma nospied pogu zemāk",
    "paid_ok": "✅ *Maksājums apstiprināts!*\n\n📦 Plāns: *{name}*\n📅 Aktīvs līdz: *{expires}*\n🔖 TX: `{tx}`",
    "paid_fail": "❌ *Maksājums nav atrasts*\n\nPārliecinies, ka nosūtīji tieši *{usdt} USDT (BEP-20)*",
    "status_active": "🟢 *Abonements*\n\n📅 Beidzas: {expires}\n⏳ Atlikušas dienas: {days}\n📦 Plāns: {plan}",
    "status_none": "❌ Tev nav aktīva abonementa.\n\nIzmanto /start, lai iegādātos piekļuvi.",
    "btn_paid": "✅ Es samaksāju",
    "btn_qr": "📷 QR kods",
    "btn_back": "🔙 Atpakaļ",
    "qr_caption": "📷 *QR kods maksājumam*\n\n📋 Adrese: `{wallet}`\n💰 Summa: *{usdt} USDT (BEP-20)*\n⚠️ Noskenē QR un ievadi summu manuāli: *{usdt} USDT*\n🔗 Tīkls: *BSC (BEP-20)*",
    "invite": "\n\n🔗 [Pievienoties kanālam]({link})",
    "referral_info": "👥 *Referral programma*\n\n🎁 Par katru draugu, kurš veic pirkumu: *+10 bezmaksas dienas*.\n\n📌 Tava saite:\n`{ref_link}`\n\n📊 Uzaicināti: *{count}*\n🎁 Bonusi saņemti: *{bonuses}*",
    "my_referrals": "👥 *Mani referrals*\n\n📊 Kopā: *{count}*\n🎁 Bonusi: *{bonuses}* × 10 dienas\n📅 Kopā: *{total_days}* dienas\n\n{referral_list}",
    "my_referrals_empty": "👥 *Mani referrals*\n\nTu vēl nevienu neesi uzaicinājis.",
    "referral_row_bonus": "✅ {name} — bonuss saņemts",
    "referral_row_pending": "⏳ {name} — gaida pirkumu",
    "referral_bonus_received": "🎉 *Bonuss saņemts!*\n\nTavs draugs veica pirkumu — tev *+10 dienas*!\n📅 Aktīvs līdz: *{expires}*",
    "referral_earnings": "🎁 *Referral bonusu dienas*\n\nReferral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_button": "🎁 Bonusu dienas",
    "earnings_button": "📊 Referral vēsture",
    "withdrawal_history_button": "📜 Bonusu dienu vēsture",
    "earnings_list": "🎁 *Referral vēsture*\n\nReferral programma tagad strādā tikai ar bonusu dienām.",
    "earnings_empty": "🎁 *Referral vēsture*\n\nReferral programma tagad strādā tikai ar bonusu dienām.",
    "earnings_row": "• {date} — {name}",
    "withdrawal_request": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_enter_address": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_confirm": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_submitted": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_approved": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_rejected": "🎁 Referral programma tagad izmanto tikai bonusu dienas čatiem.",
    "withdrawal_history": "🎁 *Referral vēsture*\n\nReferral programma tagad strādā tikai ar bonusu dienām.",
    "withdrawal_history_empty": "🎁 *Referral vēsture*\n\nReferral programma tagad strādā tikai ar bonusu dienām.",
    "withdrawal_row_pending": "⏳ Referral bonusu dienas",
    "withdrawal_row_approved": "✅ Referral bonusu dienas",
    "withdrawal_row_rejected": "❌ Referral bonusu dienas",
    "withdrawal_error_banned": "❌ Naudas izmaksas vairs nav pieejamas.",
    "withdrawal_error_pending": "ℹ️ Referral programma tagad strādā tikai ar bonusu dienām.",
    "withdrawal_error_min": "ℹ️ Referral programma tagad strādā tikai ar bonusu dienām.",
    "withdrawal_error_no_email": "ℹ️ Referral programma tagad strādā tikai ar bonusu dienām.",
    "withdrawal_error_rate_limit": "ℹ️ Referral programma tagad strādā tikai ar bonusu dienām.",
    "referral_welcome": "👋 Tevi uzaicināja draugs!\n\n🎁 Kad tu veiksi pirkumu, draugs saņems *+10 bezmaksas dienas*.\n\n🔐 Izvēlies produktu:",
    "help": "📖 *Komandas:*\n\n/start — Sākt\n/status — Statuss\n/renew — Pagarināt\n/language — Valoda\n/support — Atbalsts\n/id — Mans ID\n/loyalty — Lojalitāte\n/help — Palīdzība",
    "support": "📩 *Atbalsts*\n\nJa rodas jautājumi raksti https://t.me/mntrade_support",
}

def t(lang, key, **kw):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, key)
    return text.format(**kw) if kw else text

async def inactive_welcome_text(lang, name):
    custom_welcome = await db.get_setting(f"welcome_{lang}")
    if custom_welcome:
        return (
            custom_welcome.replace("{name}", name)
            + "\n\n"
            + t(lang, "inactive_welcome_note")
        )
    return t(lang, "inactive_welcome", name=name)


async def build_active_access_text(user_id: int, lang: str, name: str = None) -> str:
    user = await db.get_user(user_id)
    active_subs = await db.get_active_user_subscriptions(user_id)
    if not active_subs:
        return ""
    if name is None:
        name = md_escape((user or {}).get("first_name") or "Trader")

    if lang == "lv":
        header = f"👋 *Sveiks, {name}!*\n\n✅ *Aktīvās piekļuves:*"
    elif lang == "ru":
        header = f"👋 *Привет, {name}!*\n\n✅ *Активные подписки:*"
    else:
        header = f"👋 *Hello, {name}!*\n\n✅ *Active subscriptions:*"

    rows = []
    nearest_days = None
    now = datetime.utcnow()
    for sub in active_subs:
        try:
            expires_dt = datetime.fromisoformat(sub["expires_at"])
        except Exception:
            continue
        days_left = max(0, (expires_dt - now).days)
        if nearest_days is None or days_left < nearest_days:
            nearest_days = days_left
        product_name = sub.get("product_name") or sub.get("product_key") or "—"
        rows.append(f"• *{product_name}* — {expires_dt.strftime('%d.%m.%Y')} ({days_left}d)")

    loyalty_data = await db.get_user_loyalty(user_id)
    if not loyalty_data:
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
    current_tier = loyalty_data.get('current_tier', 'rookie')
    tier_data = config.LOYALTY_TIERS.get(current_tier, {})
    tier_emoji = tier_data.get('emoji', '🌱')
    tier_tag = tier_data.get('tag', 'Rookie')
    if lang == "lv":
        loyalty_line = f"\n\n{tier_emoji} Lojalitātes līmenis: *{tier_tag}*"
    elif lang == "ru":
        loyalty_line = f"\n\n{tier_emoji} Уровень лояльности: *{tier_tag}*"
    else:
        loyalty_line = f"\n\n{tier_emoji} Loyalty level: *{tier_tag}*"

    urgency = ""
    if nearest_days is not None and nearest_days <= 3:
        if nearest_days == 0:
            urgency = ui_text(lang, "\n\n🚨 *Viena no piekļuvēm beidzas šodien!*", "\n\n🚨 *Одна из подписок истекает сегодня!*", "\n\n🚨 *One of your subscriptions expires today!*")
        else:
            urgency = ui_text(
                lang,
                f"\n\n⚠️ *Tuvākā piekļuve beidzas pēc {nearest_days} dienām!*",
                f"\n\n⚠️ *Ближайшая подписка истекает через {nearest_days} дн.*",
                f"\n\n⚠️ *Your nearest subscription expires in {nearest_days} days!*"
            )

    return header + "\n\n" + "\n".join(rows) + loyalty_line + urgency


async def build_active_home_view(user_id: int, lang: str, name: str = None):
    active_subs = await db.get_active_user_subscriptions(user_id)
    if not active_subs:
        return "", active_keyboard(lang)
    nearest_days = None
    now = datetime.utcnow()
    for sub in active_subs:
        try:
            expires_dt = datetime.fromisoformat(sub["expires_at"])
        except Exception:
            continue
        days_left = max(0, (expires_dt - now).days)
        if nearest_days is None or days_left < nearest_days:
            nearest_days = days_left
    kb = _urgency_keyboard(lang) if nearest_days is not None and nearest_days <= 3 else active_keyboard(lang)
    return await build_active_access_text(user_id, lang, name), kb

async def get_bonus_eligible_chat_subscriptions(user_id: int):
    subs = await db.get_active_user_subscriptions(user_id)
    return [s for s in subs if int(s.get("chat_id") or 0) != 0]

async def build_referral_overview_text(user_id: int, lang: str) -> str:
    bot_me = await bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{user_id}"
    ref_count = await db.get_referral_count(user_id)
    bonus_count = await db.get_referral_bonus_count(user_id)
    bonus_days_balance = await db.get_referral_bonus_days_balance(user_id)
    return ui_text(
        lang,
        (
            "👥 *Referral programma*\n\n"
            f"📌 Tava saite:\n`{ref_link}`\n\n"
            f"📊 Uzaicināti: *{ref_count}*\n"
            f"✅ Draugi ar saņemtu bonusu: *{bonus_count}*\n"
            f"🎁 Pieejamās bonusu dienas: *{bonus_days_balance}*\n\n"
            f"Par katru draugu, kurš veic pirkumu, tu saņem *+{REFERRAL_BONUS_DAYS} bonusu dienas*.\n"
            "Bonusu dienas vari izmantot pats un izvēlēties, kuram aktīvajam čatam tās pielikt."
        ),
        (
            "👥 *Реферальная программа*\n\n"
            f"📌 Твоя ссылка:\n`{ref_link}`\n\n"
            f"📊 Приглашено: *{ref_count}*\n"
            f"✅ Друзья с начисленным бонусом: *{bonus_count}*\n"
            f"🎁 Доступно бонусных дней: *{bonus_days_balance}*\n\n"
            f"За каждого друга, который совершит покупку, ты получаешь *+{REFERRAL_BONUS_DAYS} бонусных дней*.\n"
            "Бонусные дни ты используешь сам и выбираешь, к какому активному чату их применить."
        ),
        (
            "👥 *Referral Program*\n\n"
            f"📌 Your link:\n`{ref_link}`\n\n"
            f"📊 Invited: *{ref_count}*\n"
            f"✅ Friends with granted bonus: *{bonus_count}*\n"
            f"🎁 Available bonus days: *{bonus_days_balance}*\n\n"
            f"For every friend who makes a purchase, you get *+{REFERRAL_BONUS_DAYS} bonus days*.\n"
            "You can use those bonus days yourself and choose which active chat to apply them to."
        ),
    )

def ui_text(lang, lv, ru, en):
    if lang == "lv":
        return lv
    if lang == "ru":
        return ru
    return en

def back_button_text(lang):
    return "🔙 " + ui_text(lang, "Atpakaļ", "Назад", "Back")

def paid_button_text(lang):
    return "✅ " + ui_text(lang, "Es samaksāju", "Я оплатил", "I paid")

def menu_button(emoji, label):
    return f"{emoji}  {label}"

def market_scanner_label(lang):
    return ui_text(lang, "Tirgus Skaneris/AI signāli", "Сканер рынка/AI сигналы", "Market Scanner/AI Signals")

def email_binding_notice(lang):
    return ui_text(
        lang,
        "E-pasts piesaista tavu piekļuvi un pirkumus no mājaslapas - tāpēc norādi derīgu epastu.",
        "E-mail привязывает твой доступ и покупки с сайта - поэтому укажи действительный e-mail.",
        "E-mail links your access and website purchases - so enter a valid e-mail.",
    )

def md_escape(text):
    if not text: return ""
    for ch in ['*','_','`','[',']']: text = text.replace(ch, f'\\{ch}')
    return text

def chat_id_for_lang(lang):
    return config.chat_id_for_lang(lang) if hasattr(config, "chat_id_for_lang") else config.CHAT_ID

def chat_link_for_lang(lang):
    return config.chat_link_for_lang(lang) if hasattr(config, "chat_link_for_lang") else config.CHAT_LINK

async def checkout_url_for_lang(lang):
    return (await db.get_setting(f"checkout_url_{lang}")) or ""


async def checkout_url_for_course(course_key):
    return (await db.get_setting(f"course_checkout_url_{course_key}")) or ""


async def checkout_url_for_subscription_product(product_key: str, user_lang: str) -> str:
    key = normalize_subscription_product_key(product_key, user_lang)
    if key == "vip_chat_lv":
        return (await db.get_setting("checkout_url_lv")) or ""
    if key == "vip_chat_ru":
        return (await db.get_setting("checkout_url_ru")) or ""
    return (await db.get_setting(f"checkout_url_{key}")) or ""


def normalize_subscription_product_key(product_key: str, user_lang: str) -> str:
    key = (product_key or "").strip().lower()
    aliases = {
        "vip_lv": "vip_chat_lv",
        "vip_chat_lv": "vip_chat_lv",
        "vip_ru": "vip_chat_ru",
        "vip_chat_ru": "vip_chat_ru",
        "scanner": "scanner_chat",
        "scanner_chat": "scanner_chat",
        "market_scanner": "scanner_chat",
        "monthly": "vip_chat_ru" if user_lang == "ru" else "vip_chat_lv",
    }
    return aliases.get(key, key)


def resolve_subscription_product(product_key: str, user_lang: str) -> dict:
    key = normalize_subscription_product_key(product_key, user_lang)
    catalog = {
        "vip_chat_lv": {
            "chat_id": config.CHAT_IDS.get("lv", config.CHAT_ID),
            "chat_link": config.CHAT_LINKS.get("lv", config.CHAT_LINK),
            "name": {"lv": "VIP Treideru čats", "ru": "VIP чат трейдеров (LV)", "en": "VIP Traders Chat (LV)"},
        },
        "vip_chat_ru": {
            "chat_id": config.CHAT_IDS.get("ru", config.CHAT_ID),
            "chat_link": config.CHAT_LINKS.get("ru", config.CHAT_LINK),
            "name": {"lv": "VIP Treideru čats (RU)", "ru": "VIP чат трейдеров", "en": "VIP Traders Chat (RU)"},
        },
        "scanner_chat": {
            "chat_id": getattr(config, "SCANNER_CHAT_ID", 0),
            "chat_link": getattr(config, "SCANNER_CHAT_LINK", "https://t.me/promarketscanner"),
            "name": {"lv": "Tirgus Skaneris/AI signāli", "ru": "Сканер рынка/AI сигналы", "en": "Market Scanner/AI Signals"},
        },
    }
    meta = catalog.get(key)
    if not meta:
        return {}
    return {"product_key": key, **meta}


async def invite_text_for_product(user_id: int, lang: str, product_meta: dict, expires_at: datetime) -> str:
    if not product_meta:
        return ""
    chat_id = int(product_meta.get("chat_id") or 0)
    chat_link = product_meta.get("chat_link") or ""
    if chat_id:
        try:
            await bot.unban_chat_member(chat_id, user_id)
        except Exception:
            pass
        try:
            link = await bot.create_chat_invite_link(chat_id, member_limit=1, expire_date=int((expires_at + timedelta(days=7)).timestamp()))
            return t(lang, "invite", link=link.invite_link)
        except Exception:
            pass
    return f"\n\n📢 {chat_link}" if chat_link else ""


async def attach_pending_email_purchases(user_id: int, email: str, lang: str, username: str = ""):
    pending_subs = await db.get_pending_email_subscriptions(email)
    if not pending_subs:
        return []
    activated = []
    for sub in pending_subs:
        try:
            expires_at = datetime.fromisoformat(sub["expires_at"])
        except Exception:
            continue
        await db.activate_product_subscription(
            user_id=user_id,
            username=username,
            product_key=sub.get("product_key") or "website_subscription",
            product_name=sub.get("product_name") or sub.get("product_key") or "Website Purchase",
            expires_at=expires_at,
            tx_hash=sub.get("tx_hash") or f"claimed:{sub.get('id')}",
            amount_usdt=0.0,
            chat_id=sub.get("chat_id", 0) or 0,
            chat_link=sub.get("chat_link", "") or "",
            payment_system=sub.get("payment_system", "") or "webhook",
        )
        await db.deactivate_pending_email_subscription(sub["id"])
        product_meta = resolve_subscription_product(sub.get("product_key") or "", lang)
        if not product_meta and (sub.get("chat_id") or sub.get("chat_link")):
            product_meta = {
                "product_key": sub.get("product_key") or "website_subscription",
                "chat_id": sub.get("chat_id", 0) or 0,
                "chat_link": sub.get("chat_link", "") or "",
                "name": {
                    "lv": sub.get("product_name") or sub.get("product_key") or "Piekļuve",
                    "ru": sub.get("product_name") or sub.get("product_key") or "Доступ",
                    "en": sub.get("product_name") or sub.get("product_key") or "Access",
                },
            }
        try:
            invite = await invite_text_for_product(user_id, lang, product_meta, expires_at)
            if invite:
                product_name = sub.get("product_name") or sub.get("product_key") or "Access"
                invite_text = ui_text(
                    lang,
                    f"✅ Atrasta iepriekšēja apmaksa: *{product_name}*\n📅 Aktīvs līdz: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                    f"✅ Найдена предыдущая оплата: *{product_name}*\n📅 Активно до: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                    f"✅ Previous purchase found: *{product_name}*\n📅 Active until: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                )
                await bot.send_message(user_id, invite_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to send claimed invite to user {user_id}: {e}")
            await notify_admins_error(f"claim_notify user={user_id} product={sub.get('product_key')}", e)
        activated.append(sub)
    return activated

def lang_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data="lang_ru")
    b.button(text="🇬🇧 English", callback_data="lang_en")
    b.button(text="🇱🇻 Latviešu", callback_data="lang_lv")
    b.adjust(2, 1)
    return b.as_markup()

def main_menu_keyboard(lang):
    """Galvenā izvēlne — vienots dizains"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("💎", "VIP Treideru čats"), callback_data="vip_chat_plans")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("💎", "VIP чат трейдеров"), callback_data="vip_chat_plans")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("💎", "VIP Traders Chat"), callback_data="vip_chat_plans")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def plans_keyboard(lang):
    """VIP kanāla valodas izvēle. Pirkums notiek mājaslapā."""
    b = InlineKeyboardBuilder()
    for code in VIP_CHANNEL_LANGS:
        b.button(text=VIP_CHANNEL_LABELS[code], callback_data=f"vip_checkout_{code}")
    b.button(text=back_button_text(lang), callback_data="back_to_main")
    b.adjust(1)
    return b.as_markup()


async def vip_channel_keyboard(lang):
    b = InlineKeyboardBuilder()
    for code in VIP_CHANNEL_LANGS:
        url = await checkout_url_for_lang(code)
        if url:
            b.button(text=VIP_CHANNEL_LABELS[code], url=url)
        else:
            b.button(text=VIP_CHANNEL_LABELS[code], callback_data=f"vip_checkout_{code}")
    b.button(text=back_button_text(lang), callback_data="back_to_main")
    b.adjust(1)
    return b.as_markup()


def active_keyboard(lang):
    """Keyboard aktīvajiem abonentiem — vienots dizains"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🔄", "Mainīt / pagarināt plānu"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Mans lojalitātes līmenis"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🔄", "Сменить / продлить тариф"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Мой уровень лояльности"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🔄", "Change / Renew Plan"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()

# ─── FIRST-TIME LANGUAGE SELECTION ───

class RegistrationEmailState(StatesGroup):
    waiting_email = State()

def _first_time_lang_keyboard(ref_param=None):
    """Valodas izvēle jaunajiem lietotājiem"""
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺  Русский", callback_data="first_lang_ru")
    b.button(text="🇬🇧  English", callback_data="first_lang_en")
    b.button(text="🇱🇻  Latviešu", callback_data="first_lang_lv")
    b.adjust(2, 1)
    return b.as_markup()


def _is_registered_user(user):
    return bool(user and (user.get("email") or "").strip())


@dp.callback_query(F.data.startswith("first_lang_"))
async def first_lang_selected(callback: CallbackQuery, state: FSMContext):
    """Jauns lietotājs izvēlējās valodu — startē onboarding"""
    lang = callback.data.replace("first_lang_", "")
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    user_id = callback.from_user.id
    await db.set_user_lang(user_id, lang)
    name = md_escape(callback.from_user.first_name)
    
    # Dzēst valodas izvēles ziņu
    try:
        await callback.message.delete()
    except:
        pass
    
    if lang == "lv":
        text = (
            "📧 *Ievadi savu e-pastu*\n\n"
            "Pie šī e-pasta tiks piesaistīts abonements un piekļuve. Pēc maksājuma mājaslapā bots pirkumu pārbaudīs pēc šī e-pasta.\n\n"
            "_Atsūti e-pastu vienā ziņā:_"
        )
    elif lang == "ru":
        text = (
            "📧 *Укажи свой e-mail*\n\n"
            "К нему будет привязана подписка и доступ. После оплаты на сайте бот сверит покупку по этому e-mail.\n\n"
            "_Отправь e-mail одним сообщением:_"
        )
    else:
        text = (
            "📧 *Enter your e-mail*\n\n"
            "Your subscription and access will be linked to it. After website payment the bot will verify the purchase by this e-mail.\n\n"
            "_Send your e-mail as one message:_"
        )
    await state.set_state(RegistrationEmailState.waiting_email)
    await state.update_data(reg_lang=lang, reg_name=name)
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.message(RegistrationEmailState.waiting_email)
async def registration_receive_email(message: Message, state: FSMContext):
    email = (message.text or "").strip().lower()
    data = await state.get_data()
    lang = data.get("reg_lang", "ru")
    name = data.get("reg_name", md_escape(message.from_user.first_name))
    if "@" not in email or "." not in email or len(email) < 5:
        await message.answer("❌ " + ("Nepareizs e-pasta formāts. Pamēģini vēlreiz:" if lang == "lv" else ("Неверный e-mail. Попробуй ещё:" if lang == "ru" else "Invalid e-mail. Try again:")))
        return
    await db.set_user_lang(message.from_user.id, lang)
    await db.set_user_email(message.from_user.id, email)
    claimed = await attach_pending_email_purchases(message.from_user.id, email, lang, message.from_user.username or "")
    uname = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    await notify_admins(
        "📧 *Lietotājs piesaistīja e-pastu*\n\n"
        f"👤 {uname} (`{message.from_user.id}`)\n"
        f"📧 `{email}`\n"
        f"📦 Aktivizēti gaidošie pirkumi: *{len(claimed)}*"
    )
    await state.clear()
    await message.answer(("✅ E-pasts saglabāts." if lang == "lv" else ("✅ E-mail сохранён." if lang == "ru" else "✅ E-mail saved.")), parse_mode="Markdown")
    if claimed:
        await message.answer(ui_text(lang, f"âœ… Atrasti iepriekÅ¡Ä“ji pirkumi pÄ“c e-pasta. AktivizÄ“tas {len(claimed)} piekÄ¼uves.", f"âœ… ÐÐ°Ð¹Ð´ÐµÐ½Ñ‹ Ñ€Ð°Ð½ÐµÐµ Ð¾Ð¿Ð»Ð°Ñ‡ÐµÐ½Ð½Ñ‹Ðµ Ð¿Ð¾ÐºÑƒÐ¿ÐºÐ¸ Ð¿Ð¾ e-mail. ÐÐºÑ‚Ð¸Ð²Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð¾Ð²: {len(claimed)}.", f"âœ… Previous purchases were found for this e-mail. Activated accesses: {len(claimed)}."), parse_mode="Markdown")
    await _send_onboarding(message, lang, name)


# ─── ONBOARDING FLOW ───

async def _send_onboarding(message, lang, name):
    """3 ziņu karuselis jaunajiem lietotājiem"""
    if lang == "lv":
        msg1 = (
            f"👋 *Sveiks, {name}!*\n\n"
            f"Laipni lūgts *MNtradepro*! 🚀\n\n"
            f"💎 *VIP Treideru čats*\n"
            f"Slēgta community ar signāliem, analītiku un atbalstu.\n"
            f"Izvēlies plānu un pievienojies!"
        )
        msg2 = (
            f"📚 *MNtradepro kursi*\n\n"
            f"No iesācēja līdz pārliecinātam treiderim — soli pa solim.\n"
            f"Audzē zināšanas un izmanto community pieredzi."
        )
        msg3 = (
            f"🏆 *Lojalitātes programma*\n\n"
            f"Jo ilgāk esi community biedrs, jo lielākus bonusus iegūsti:\n"
            f"🔥 Audzē savu statusu ar aktivitāti\n"
            f"🎁 Saņem bezmaksas bonusa dienas\n"
            f"🎓 Atbloķē papildu privilēģijas aktīvākajiem biedriem\n\n"
            f"Sāc tagad! 👇"
        )
    elif lang == "ru":
        # Ziņa 1 — VIP čats
        msg1 = (
            f"👋 *Привет, {name}!*\n\n"
            f"Добро пожаловать в *MNtradepro*! 🚀\n\n"
            f"💎 *VIP чат трейдеров*\n"
            f"Закрытое сообщество с сигналами, аналитикой и поддержкой от профессионалов.\n"
            f"Выбирай тариф и присоединяйся!"
        )
        # Ziņa 2 — Kursi
        msg2 = (
            f"📚 *Курсы MNtradepro Academy*\n\n"
            f"От новичка до профи — пошаговое обучение трейдингу.\n"
            f"Каждый нюанс может принести тебе серьёзные деньги! 💰"
        )
        # Ziņa 3 — Loyalty
        msg3 = (
            f"🏆 *Программа лояльности*\n\n"
            f"Чем дольше ты в community — тем больше бонусов получаешь:\n"
            f"🔥 Расти в статусе через активность\n"
            f"🎁 Получай бесплатные бонусные дни\n"
            f"🎓 Открывай дополнительные привилегии для топ-участников\n\n"
            f"Начни прямо сейчас! 👇"
        )
    else:
        msg1 = (
            f"👋 *Hi, {name}!*\n\n"
            f"Welcome to *MNtradepro*! 🚀\n\n"
            f"💎 *VIP Traders Chat*\n"
            f"Exclusive community with signals, analytics and professional support.\n"
            f"Pick a plan and join!"
        )
        msg2 = (
            f"📚 *MNtradepro Academy Courses*\n\n"
            f"From beginner to pro — step-by-step trading education.\n"
            f"Every detail can bring you serious money! 💰"
        )
        msg3 = (
            f"🏆 *Loyalty Program*\n\n"
            f"The longer you stay in the community — the bigger bonuses you unlock:\n"
            f"🔥 Grow your status through activity\n"
            f"🎁 Earn free bonus days\n"
            f"🎓 Unlock extra perks for top members\n\n"
            f"Start now! 👇"
        )
    
    await message.answer(msg1, parse_mode="Markdown")
    await asyncio.sleep(0.5)
    await message.answer(msg2, parse_mode="Markdown")
    await asyncio.sleep(0.5)
    await message.answer(msg3, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")


def _urgency_keyboard(lang):
    """Keyboard ar urgency — Pagarināt tagad pogu augšā"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🚨", "Pagarināt tagad!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Mans lojalitātes līmenis"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🚨", "Продлить сейчас!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Мой уровень лояльности"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🚨", "Renew Now!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def active_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🔗", "Saņemt piekļuves linku"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Mainīt / pagarināt plānu"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Mans lojalitātes līmenis"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🔗", "Получить ссылку доступа"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Сменить / продлить тариф"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "Мой уровень лояльности"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🔗", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Change / Renew Plan"), callback_data="vip_chat_plans")
        b.button(text=menu_button("💎", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def _urgency_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🚨", "Pagarināt tagad!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Saņemt piekļuves linku"), callback_data="get_access_links")
        b.button(text=menu_button("💎", "Mans lojalitātes līmenis"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🚨", "Продлить сейчас!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Получить ссылку доступа"), callback_data="get_access_links")
        b.button(text=menu_button("💎", "Мой уровень лояльности"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🚨", "Renew Now!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("💎", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


async def _send_referral_reminder(user_id, lang):
    """Nosūta referral reminder 5 min pēc maksājuma"""
    return
    await asyncio.sleep(300)  # 5 minūtes
    try:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        if lang == "ru":
            text = (
                f"💡 *Кстати!*\n\n"
                f"Пригласи друга — и получай бонусные дни:\n\n"
                f"🎁 За каждую покупку друга тебе начисляется *+{config.REFERRAL_BONUS_DAYS} бонусных дней*\n"
                f"📅 Ты сам выбираешь, к какому активному чату их применить.\n\n"
                f"📌 Твоя ссылка:\n`{ref_link}`"
            )
        else:
            text = (
                f"💡 *By the way!*\n\n"
                f"Invite a friend and collect bonus days:\n\n"
                f"🎁 For every friend purchase you receive *+{config.REFERRAL_BONUS_DAYS} bonus days*\n"
                f"📅 You choose which active chat to apply them to.\n\n"
                f"📌 Your link:\n`{ref_link}`"
            )
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Referral reminder failed for {user_id}: {e}")


# ─── HANDLERS ───

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    args = message.text.split()
    ref_param = args[1] if len(args) > 1 else None
    tg_lang = (message.from_user.language_code or DEFAULT_LANG)[:2]
    auto_lang = tg_lang if tg_lang in SUPPORTED_LANGS else DEFAULT_LANG
    existing_user = await db.get_user(user_id)
    await db.register_user(user_id, message.from_user.username, message.from_user.first_name, auto_lang)
    if not existing_user:
        uname = f"@{message.from_user.username}" if message.from_user.username else f"ID {user_id}"
        await notify_admins(
            "🆕 *Jauns lietotājs botā*\n\n"
            f"👤 {uname} (`{user_id}`)\n"
            f"🌐 Valoda: `{auto_lang}`"
        )
    if ref_param and ref_param.startswith("ref_"):
        try:
            rid = ref_param[4:]
            if rid.isdigit() and len(rid) <= 12:
                referrer_id = int(rid)
                if referrer_id != user_id and referrer_id > 0:
                    if not await db.get_referral_by_referred(user_id):
                        await db.register_referral(referrer_id, user_id)
        except (ValueError, OverflowError): pass
    user = await db.get_user(user_id)
    name = md_escape(message.from_user.first_name)
    lang = user.get("lang", auto_lang) if user else auto_lang
    has_registered_email = _is_registered_user(user)
    
    # Reģistrācija = DB ieraksts ar e-pastu. Ja e-pasts jau ir, neprasām to atkārtoti.
    if not has_registered_email:
        # Ja TG ID jau eksistē DB, valodu vairs neprasām — tikai trūkstošo e-pastu.
        if existing_user:
            if lang == "lv":
                text = (
                    "📧 *Ievadi savu e-pastu*\n\n"
                    f"{email_binding_notice(lang)}\n\n"
                    "_Atsūti e-pastu vienā ziņā:_"
                )
            elif lang == "ru":
                text = (
                    "📧 *Укажи свой e-mail*\n\n"
                    f"{email_binding_notice(lang)}\n\n"
                    "_Отправь e-mail одним сообщением:_"
                )
            else:
                text = (
                    "📧 *Enter your e-mail*\n\n"
                    f"{email_binding_notice(lang)}\n\n"
                    "_Send your e-mail as one message:_"
                )
            await state.set_state(RegistrationEmailState.waiting_email)
            await state.update_data(reg_lang=lang, reg_name=name)
            await message.answer(text, parse_mode="Markdown")
            return
        await message.answer(
            "🌐 Izvēlies valodu / Choose language / Выбери язык:",
            reply_markup=_first_time_lang_keyboard(ref_param)
        )
        return
    active_subs = await db.get_active_user_subscriptions(user_id)
    if active_subs:
        welcome_text, kb = await build_active_home_view(user_id, lang, name)
        await message.answer(welcome_text, reply_markup=kb, parse_mode="Markdown")
        return
        expires_dt = datetime.fromisoformat(user['expires_at'])
        expires = expires_dt.strftime("%d.%m.%Y")
        days_left = max(0, (expires_dt - datetime.utcnow()).days)
        plan_name = user.get('plan_name', '—')
        
        # Loyalty info
        loyalty_data = await db.get_user_loyalty(user_id)
        if not loyalty_data:
            await db.update_user_loyalty(user_id, 'rookie', 0)
            loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
        
        current_tier = loyalty_data.get('current_tier', 'rookie')
        consecutive_months = loyalty_data.get('consecutive_months', 0)
        tier_data = config.LOYALTY_TIERS.get(current_tier, {})
        tier_emoji = tier_data.get('emoji', '🌱')
        tier_tag = tier_data.get('tag', 'Rookie')
        tier_discount = tier_data.get('chat_discount', 0)
        
        # Urgency trigger
        urgency = ""
        if days_left <= 3 and days_left > 0:
            if lang == "ru":
                urgency = f"\n\n⚠️ *Внимание! До окончания подписки {days_left} {'день' if days_left == 1 else 'дня'}!*"
            elif lang == "lv":
                urgency = f"\n\n⚠️ *Uzmanību! Līdz abonementa beigām palikušas {days_left} {'diena' if days_left == 1 else 'dienas'}!*"
            else:
                urgency = f"\n\n⚠️ *Warning! Only {days_left} day{'s' if days_left != 1 else ''} left!*"
        elif days_left == 0:
            if lang == "ru":
                urgency = "\n\n🚨 *Подписка заканчивается сегодня!*"
            elif lang == "lv":
                urgency = "\n\n🚨 *Abonements beidzas šodien!*"
            else:
                urgency = "\n\n🚨 *Subscription expires today!*"
        
        # Nākamā līmeņa info ar % gamification
        next_tier_info = ""
        for tier_name in ['active', 'pro', 'elite', 'master', 'legend']:
            ti = config.LOYALTY_TIERS[tier_name]
            if consecutive_months < ti['min_months']:
                months_left = ti['min_months'] - consecutive_months
                next_bonus = ti.get('bonus_days', 0)
                next_discount = ti.get('chat_discount', 0)
                next_emoji = ti.get('emoji', '')
                next_tag = ti.get('tag', '')
                target_months = ti['min_months']
                progress_pct = int((consecutive_months / target_months) * 100) if target_months > 0 else 0
                if lang == "ru":
                    next_tier_info = (
                        f"\n\n🎯 Следующий: {next_emoji} *{next_tag}* — {progress_pct}% пройдено\n"
                        f"🎁 +{next_bonus} дн. бесплатно, скидка {next_discount}%"
                    )
                elif lang == "lv":
                    next_tier_info = (
                        f"\n\n🎯 Nākamais: {next_emoji} *{next_tag}* — {progress_pct}% pabeigts\n"
                        f"🎁 +{next_bonus} bezmaksas dienas, {next_discount}% atlaide"
                    )
                else:
                    next_tier_info = (
                        f"\n\n🎯 Next: {next_emoji} *{next_tag}* — {progress_pct}% complete\n"
                        f"🎁 +{next_bonus} days free, {next_discount}% off"
                    )
                break
        
        if lang == "ru":
            loyalty_line = f"\n\n{tier_emoji} Уровень: *{tier_tag}*" + (f" ({tier_discount}% скидка)" if tier_discount > 0 else "")
        elif lang == "lv":
            loyalty_line = f"\n\n{tier_emoji} Līmenis: *{tier_tag}*" + (f" ({tier_discount}% atlaide)" if tier_discount > 0 else "")
        else:
            loyalty_line = f"\n\n{tier_emoji} Level: *{tier_tag}*" + (f" ({tier_discount}% discount)" if tier_discount > 0 else "")
        
        welcome_text = t(lang, "active_sub", name=name, expires=expires, plan=plan_name, days=days_left) + loyalty_line + next_tier_info + urgency
        
        # Ja urgency — pievienot speciālu keyboard ar "Pagarināt tagad" pogu augšā
        if days_left <= 3:
            kb = _urgency_keyboard(lang)
        else:
            kb = active_keyboard(lang)
        await message.answer(welcome_text, reply_markup=kb, parse_mode="Markdown")
    else:
        referral = await db.get_referral_by_referred(user_id) if ref_param else None
        
        welcome_text = await inactive_welcome_text(lang, name)
        await message.answer(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("lang_"))
async def lang_selected(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    if lang not in SUPPORTED_LANGS: lang = DEFAULT_LANG
    await db.set_user_lang(callback.from_user.id, lang)
    name = md_escape(callback.from_user.first_name)
    user = await db.get_user(callback.from_user.id)
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    if active_subs:
        text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif user and user.get("expires_at") and datetime.fromisoformat(user["expires_at"]) > datetime.utcnow():
        expires_dt = datetime.fromisoformat(user["expires_at"]); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        # Custom welcome no DB (tāpat kā cmd_start)
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("id"))
async def cmd_id(message: Message):
    """Parāda lietotāja Telegram ID"""
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        text = f"🆔 *Tavs Telegram ID:*\n\n`{message.from_user.id}`\n\n_Nokopē un nosūti adminam, ja nepieciešams._"
    elif lang == "ru":
        text = f"🆔 *Твой Telegram ID:*\n\n`{message.from_user.id}`\n\n_Скопируй и отправь админу если нужно._"
    else:
        text = f"🆔 *Your Telegram ID:*\n\n`{message.from_user.id}`\n\n_Copy and send to admin if needed._"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await message.answer(t(lang, "help"), parse_mode="Markdown")

@dp.message(Command("language"))
async def cmd_language(message: Message):
    await message.answer("🌐 Izvēlies valodu / Choose language / Выбери язык:", reply_markup=lang_keyboard())

@dp.message(Command("support"))
async def cmd_support(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await message.answer(t(lang, "support", contact=config.SUPPORT_CONTACT))

@dp.callback_query(F.data == "user_support")
async def cb_support(callback: CallbackQuery):
    await callback.answer()
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.answer(t(lang, "support", contact=config.SUPPORT_CONTACT))

@dp.callback_query(F.data == "market_scanner")
async def cb_market_scanner(callback: CallbackQuery):
    await callback.answer()
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if not (user and user.get("email")):
        await callback.message.answer(
            ui_text(
                lang,
                "📧 Vispirms iestati e-pastu botā. Pēc pirkuma piekļuve tiks piesaistīta pēc šī e-pasta.",
                "📧 Сначала укажи e-mail в боте. После покупки доступ будет привязан по этому e-mail.",
                "📧 Please set your e-mail first. After purchase access will be linked by this e-mail.",
            )
        )
        return
    checkout_url = await checkout_url_for_subscription_product("scanner_chat", lang)
    text = ui_text(
        lang,
        "📡 *Tirgus Skaneris/AI signāli*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski iedos jaunu piekļuvi.",
        "📡 *Сканер рынка/AI сигналы*\n\nПокупка происходит на сайте. После оплаты бот автоматически выдаст доступ.",
        "📡 *Market Scanner/AI Signals*\n\nPurchase happens on the website. After payment the bot will grant access automatically.",
    )
    b = InlineKeyboardBuilder()
    if checkout_url:
        b.button(text=ui_text(lang, "💳 Maksāt ar karti / banku / crypto", "💳 Оплатить картой / банком / crypto", "💳 Pay with card / bank / crypto"), url=checkout_url)
    else:
        b.button(text=ui_text(lang, "💳 Maksāt ar karti / banku / crypto", "💳 Оплатить картой / банком / crypto", "💳 Pay with card / bank / crypto"), callback_data="scanner_checkout_missing")
    b.button(text=back_button_text(lang), callback_data="back_to_main")
    b.adjust(1)
    await callback.message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "scanner_checkout_missing")
async def scanner_checkout_missing(callback: CallbackQuery):
    await callback.answer("Scanner checkout links vēl nav iestatīts admin panelī.", show_alert=True)

@dp.message(Command("status"))
async def cmd_status(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    active_subs = await db.get_active_user_subscriptions(message.from_user.id)
    if active_subs:
        rows = []
        for sub in active_subs:
            expires = datetime.fromisoformat(sub["expires_at"])
            days = max(0, (expires - datetime.utcnow()).days)
            rows.append(f"• *{sub.get('product_name', sub.get('product_key', '—'))}* — {expires.strftime('%d.%m.%Y')} ({days}d)")
        header = ui_text(lang, "🟢 *Aktīvās piekļuves:*", "🟢 *Активные подписки:*", "🟢 *Active subscriptions:*")
        await message.answer(header + "\n\n" + "\n".join(rows), parse_mode="Markdown")
        return
    if not user or not user.get('expires_at'):
        await message.answer(t(lang, "status_none"), parse_mode="Markdown"); return
    expires = datetime.fromisoformat(user['expires_at'])
    if expires > datetime.utcnow():
        await message.answer(t(lang, "status_active", expires=expires.strftime('%d.%m.%Y'), days=max(0, (expires - datetime.utcnow()).days), plan=user.get('plan_name', '—')), parse_mode="Markdown")
    else:
        await message.answer(t(lang, "status_none"), parse_mode="Markdown")

@dp.message(Command("renew"))
async def cmd_renew(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    text = "💎 *Izvēlies VIP čatu:*" if lang == "lv" else ("💎 *Выбери VIP чат:*" if lang == "ru" else "💎 *Choose VIP chat:*")
    await message.answer(text, reply_markup=await vip_channel_keyboard(lang), parse_mode="Markdown")

@dp.message(Command("referral"))
async def cmd_referral(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await message.answer(
        ui_text(
            lang,
            "ℹ️ Referral sistēma šobrīd ir izslēgta.",
            "ℹ️ Referral система сейчас отключена.",
            "ℹ️ The referral system is currently disabled.",
        )
    )

@dp.callback_query(F.data == "ref_main")
async def ref_main(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.edit_text(
        ui_text(
            lang,
            "ℹ️ Referral sistēma šobrīd ir izslēgta.",
            "ℹ️ Referral система сейчас отключена.",
            "ℹ️ The referral system is currently disabled.",
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_my_link")
async def ref_my_link(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.edit_text(
        ui_text(
            lang,
            "ℹ️ Referral sistēma šobrīd ir izslēgta.",
            "ℹ️ Referral система сейчас отключена.",
            "ℹ️ The referral system is currently disabled.",
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_my_list")
async def ref_my_list(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.edit_text(
        ui_text(
            lang,
            "ℹ️ Referral sistēma šobrīd ir izslēgta.",
            "ℹ️ Referral система сейчас отключена.",
            "ℹ️ The referral system is currently disabled.",
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_back_start")
async def ref_back_start(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    if active_subs:
        text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
        expires_dt = datetime.fromisoformat(user['expires_at']); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "ref_use_bonus")
async def ref_use_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.answer(
        ui_text(
            lang,
            "Referral sistēma šobrīd ir izslēgta.",
            "Referral система сейчас отключена.",
            "The referral system is currently disabled.",
        ),
        show_alert=True
    )
    await callback.message.edit_text(
        ui_text(
            lang,
            "ℹ️ Referral sistēma šobrīd ir izslēgta.",
            "ℹ️ Referral система сейчас отключена.",
            "ℹ️ The referral system is currently disabled.",
        )
    )

@dp.callback_query(F.data.startswith("ref_apply_bonus_"))
async def ref_apply_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.answer(
        ui_text(
            lang,
            "Referral sistēma šobrīd ir izslēgta.",
            "Referral система сейчас отключена.",
            "The referral system is currently disabled.",
        ),
        show_alert=True
    )

# ─── USER SETTINGS ───

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loyalty_system import LoyaltySystem
from cron_jobs import setup_loyalty_cron


class UserSettingsState(StatesGroup):
    waiting_email = State()

def settings_text(lang, email, selected=False):
    email_display = email if email else ui_text(lang, "— nav norādīts", "— не указан", "— not set")
    check = " ✅" if selected else ""
    if lang == "lv":
        return (
            "⚙️ *Iestatījumi*\n\n"
            f"🌐 Valoda: *Latviešu*{check}\n"
            f"📧 E-pasts: *{email_display}*\n\n"
            f"{email_binding_notice(lang)}\n\n"
            "Izvēlies, ko mainīt:"
        )
    if lang == "ru":
        return (
            "⚙️ *Настройки*\n\n"
            f"🌐 Язык: *Русский*{check}\n"
            f"📧 E-mail: *{email_display}*\n\n"
            f"{email_binding_notice(lang)}\n\n"
            "Выбери, что изменить:"
        )
    return (
        "⚙️ *Settings*\n\n"
        f"🌐 Language: *English*{check}\n"
        f"📧 E-mail: *{email_display}*\n\n"
        f"{email_binding_notice(lang)}\n\n"
        "Choose what to change:"
    )

@dp.callback_query(F.data == "user_settings")
async def user_settings(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    email = user.get("email", "") if user else ""
    text = settings_text(lang, email)

    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data="settings_lang_ru")
    b.button(text="🇬🇧 English", callback_data="settings_lang_en")
    b.button(text="🇱🇻 Latviešu", callback_data="settings_lang_lv")
    email_btn = "📧 " + ui_text(lang, "Ievadīt e-pastu", "Указать e-mail", "Set e-mail")
    b.button(text=email_btn, callback_data="settings_email")
    b.button(text=back_button_text(lang), callback_data="settings_back")
    b.adjust(2, 1, 1, 1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("settings_lang_"))
async def settings_lang(callback: CallbackQuery):
    lang = callback.data.replace("settings_lang_", "")
    if lang not in SUPPORTED_LANGS: lang = DEFAULT_LANG
    await db.set_user_lang(callback.from_user.id, lang)
    # Rāda atjaunotu settings
    user = await db.get_user(callback.from_user.id)
    email = user.get("email", "") if user else ""
    text = settings_text(lang, email, selected=True)
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data="settings_lang_ru")
    b.button(text="🇬🇧 English", callback_data="settings_lang_en")
    b.button(text="🇱🇻 Latviešu", callback_data="settings_lang_lv")
    b.button(text="📧 " + ui_text(lang, "Ievadīt e-pastu", "Указать e-mail", "Set e-mail"), callback_data="settings_email")
    b.button(text=back_button_text(lang), callback_data="settings_back")
    b.adjust(2, 1, 1, 1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "settings_email")
async def settings_email(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        text = (
            "📧 *Ievadi savu e-pastu:*\n\n"
            f"{email_binding_notice(lang)}\n\n"
            "_Atsūti savu e-pastu ziņā:_\n\n"
            "/cancel lai atceltu"
        )
    elif lang == "ru":
        text = (
            "📧 *Укажи свой e-mail:*\n\n"
            f"{email_binding_notice(lang)}\n\n"
            "_Отправь свой e-mail сообщением:_\n\n"
            "/cancel для отмены"
        )
    else:
        text = (
            "📧 *Enter your e-mail:*\n\n"
            f"{email_binding_notice(lang)}\n\n"
            "_Send your e-mail as a message:_\n\n"
            "/cancel to cancel"
        )
    await state.set_state(UserSettingsState.waiting_email)
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@dp.message(UserSettingsState.waiting_email)
async def receive_email(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ui_text(lang, "Atcelts", "Отменено", "Cancelled"))
        return
    email = message.text.strip()
    # Vienkārša validācija
    if "@" not in email or "." not in email or len(email) < 5:
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ("Nepareizs e-pasta formāts. Pamēģini vēlreiz:" if lang == "lv" else ("Неверный формат e-mail. Попробуй ещё:" if lang == "ru" else "Invalid e-mail format. Try again:")))
        return
    await state.clear()
    await db.set_user_email(message.from_user.id, email)
    claimed = await attach_pending_email_purchases(message.from_user.id, email, "lv", message.from_user.username or "")
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        await message.answer(f"✅ E-pasts saglabāts: *{email}*", parse_mode="Markdown")
    elif lang == "ru":
        await message.answer(f"✅ E-mail сохранён: *{email}*", parse_mode="Markdown")
    else:
        await message.answer(f"✅ E-mail saved: *{email}*", parse_mode="Markdown")


    if claimed:
        await message.answer(ui_text(lang, f"âœ… Atrasti ieprÅ¡Ä“ji pirkumi pÄ“c e-pasta. AktivizÄ“tas {len(claimed)} piekÄ¼uves.", f"âœ… ÐÐ°Ð¹Ð´ÐµÐ½Ñ‹ Ñ€Ð°Ð½ÐµÐµ Ð¾Ð¿Ð»Ð°Ñ‡ÐµÐ½Ð½Ñ‹Ðµ Ð¿Ð¾ÐºÑƒÐ¿ÐºÐ¸ Ð¿Ð¾ e-mail. ÐÐºÑ‚Ð¸Ð²Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð¾Ð²: {len(claimed)}.", f"âœ… Previous purchases were found for this e-mail. Activated accesses: {len(claimed)}."), parse_mode="Markdown")

@dp.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    has_active = bool(active_subs) or (user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow())
    if active_subs:
        text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif has_active:
        expires = datetime.fromisoformat(user['expires_at']).strftime("%d.%m.%Y")
        expires_dt = datetime.fromisoformat(user['expires_at']); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()


class GiveawayEmailState(StatesGroup):
    waiting_email = State()


async def _giveaway_settings():
    """Nolasīt giveaway settings no DB (admin var mainīt)"""
    winners_raw = await db.get_setting("giveaway_winners_count")
    days_raw = await db.get_setting("giveaway_prize_days")
    winners_count = int(winners_raw) if winners_raw and winners_raw.isdigit() else 1
    prize_days = int(days_raw) if days_raw and days_raw.isdigit() else 14
    return winners_count, prize_days


@dp.callback_query(F.data == "giveaway_join")
async def giveaway_join(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await user_lang(callback.from_user.id)
    await callback.answer(
        ui_text(
            lang,
            "Giveaway pašlaik ir izslēgts.",
            "Розыгрыш сейчас отключён.",
            "Giveaway is currently disabled.",
        ),
        show_alert=True,
    )
    return

    # Legacy giveaway flow left below, currently disabled.
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    email = user.get("email", "") if user else ""
    now = datetime.utcnow()
    current_month = now.strftime("%Y-%m")
    _, prize_days = await _giveaway_settings()

    # PĀRBAUDE: aktīvs abonements
    has_active = user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > now
    if not has_active:
        if lang == "ru":
            text = (
                "🎟 *Розыгрыш месяца*\n\n"
                "⚠️ Для участия в розыгрыше необходима *активная подписка*.\n\n"
                f"🏆 Приз: *+{prize_days} дней* бесплатного доступа к чату!\n\n"
                "📋 Оформи подписку и возвращайся!"
            )
        elif lang == "lv":
            text = (
                "🎟 *Mēneša izloze*\n\n"
                "⚠️ Lai piedalītos izlozē, nepieciešams *aktīvs abonements*.\n\n"
                f"🏆 Balva: *+{prize_days} dienas* bezmaksas piekļuvei čatam!\n\n"
                "📋 Noformē abonementu un atgriezies!"
            )
        else:
            text = (
                "🎟 *Monthly Giveaway*\n\n"
                "⚠️ An *active subscription* is required to participate.\n\n"
                f"🏆 Prize: *+{prize_days} days* of free chat access!\n\n"
                "📋 Subscribe and come back!"
            )
        b = InlineKeyboardBuilder()
        b.button(text=back_button_text(lang), callback_data="settings_back")
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
        await callback.answer()
        return

    # Ja nav e-pasta — obligāti jānorāda
    if not email:
        if lang == "ru":
            text = (
                "🎟 *Розыгрыш месяца*\n\n"
                f"Каждый месяц среди подписчиков разыгрывается *+{prize_days} дней* бесплатного доступа!\n\n"
                "⚠️ Для участия нужно указать *e-mail*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "📧 _Отправь свой e-mail сообщением:_\n"
                "/cancel для отмены"
            )
        elif lang == "lv":
            text = (
                "🎟 *Mēneša izloze*\n\n"
                f"Katru mēnesi abonenti var laimēt *+{prize_days} dienas* bezmaksas piekļuvi!\n\n"
                "⚠️ Lai piedalītos, jānorāda *e-pasts*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "📧 _Atsūti savu e-pastu ziņā:_\n"
                "/cancel lai atceltu"
            )
        else:
            text = (
                "🎟 *Monthly Giveaway*\n\n"
                f"Every month subscribers can win *+{prize_days} days* of free access!\n\n"
                "⚠️ To participate you need to provide your *e-mail*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "📧 _Send your e-mail as a message:_\n"
                "/cancel to cancel"
            )
        await state.set_state(GiveawayEmailState.waiting_email)
        await state.update_data(giveaway_month=current_month)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return

    # Pārbaudām vai jau pieteicies šomēnes
    already = await db.is_giveaway_entered(user_id, current_month)
    if already:
        count = await db.get_giveaway_count(current_month)
        if lang == "ru":
            text = (
                "🎟 *Розыгрыш месяца*\n\n"
                "✅ Ты уже участвуешь в розыгрыше этого месяца!\n\n"
                f"👥 Участников: *{count}*\n"
                "📅 Розыгрыш: *1 числа следующего месяца*\n"
                f"🏆 Приз: *+{prize_days} дней* бесплатного доступа\n\n"
                "🍀 Удачи!"
            )
        elif lang == "lv":
            text = (
                "🎟 *Mēneša izloze*\n\n"
                "✅ Tu jau piedalies šī mēneša izlozē!\n\n"
                f"👥 Dalībnieki: *{count}*\n"
                "📅 Izloze: *nākamā mēneša 1. datumā*\n"
                f"🏆 Balva: *+{prize_days} dienas* bezmaksas piekļuvei\n\n"
                "🍀 Lai veicas!"
            )
        else:
            text = (
                "🎟 *Monthly Giveaway*\n\n"
                "✅ You're already entered for this month!\n\n"
                f"👥 Participants: *{count}*\n"
                "📅 Drawing: *1st of next month*\n"
                f"🏆 Prize: *+{prize_days} days* free access\n\n"
                "🍀 Good luck!"
            )
        b = InlineKeyboardBuilder()
        b.button(text=back_button_text(lang), callback_data="settings_back")
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
        await callback.answer()
        return

    # Pieteikties
    await db.enter_giveaway(user_id, current_month)
    count = await db.get_giveaway_count(current_month)
    if lang == "ru":
        text = (
            "🎟 *Розыгрыш месяца*\n\n"
            "🎉 *Ты успешно зарегистрирован!*\n\n"
            f"👥 Участников: *{count}*\n"
            "📅 Розыгрыш: *1 числа следующего месяца*\n"
            f"🏆 Приз: *+{prize_days} дней* бесплатного доступа\n\n"
            "🍀 Удачи!"
        )
    elif lang == "lv":
        text = (
            "🎟 *Mēneša izloze*\n\n"
            "🎉 *Tu esi veiksmīgi reģistrēts!*\n\n"
            f"👥 Dalībnieki: *{count}*\n"
            "📅 Izloze: *nākamā mēneša 1. datumā*\n"
            f"🏆 Balva: *+{prize_days} dienas* bezmaksas piekļuvei\n\n"
            "🍀 Lai veicas!"
        )
    else:
        text = (
            "🎟 *Monthly Giveaway*\n\n"
            "🎉 *You're registered!*\n\n"
            f"👥 Participants: *{count}*\n"
            "📅 Drawing: *1st of next month*\n"
            f"🏆 Prize: *+{prize_days} days* free access\n\n"
            "🍀 Good luck!"
        )
    b = InlineKeyboardBuilder()
    b.button(text=back_button_text(lang), callback_data="settings_back")
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.message(GiveawayEmailState.waiting_email)
async def giveaway_receive_email(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ui_text(lang, "Atcelts", "Отменено", "Cancelled"))
        return
    email = message.text.strip()
    if "@" not in email or "." not in email or len(email) < 5:
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ui_text(lang, "Nepareizs e-pasta formāts. Pamēģini vēlreiz:", "Неверный формат e-mail. Попробуй ещё:", "Invalid e-mail format. Try again:"))
        return

    data = await state.get_data()
    month = data.get("giveaway_month", datetime.utcnow().strftime("%Y-%m"))
    await state.clear()

    user_id = message.from_user.id
    await db.set_user_email(user_id, email)
    await attach_pending_email_purchases(user_id, email, "lv", message.from_user.username or "")
    await db.enter_giveaway(user_id, month)
    count = await db.get_giveaway_count(month)
    _, prize_days = await _giveaway_settings()

    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "ru":
        text = (
            f"✅ E-mail сохранён: *{email}*\n\n"
            "🎟 *Ты зарегистрирован в розыгрыше!*\n\n"
            f"👥 Участников: *{count}*\n"
            "📅 Розыгрыш: *1 числа следующего месяца*\n"
            f"🏆 Приз: *+{prize_days} дней* бесплатного доступа\n\n"
            "🍀 Удачи!"
        )
    elif lang == "lv":
        text = (
            f"✅ E-pasts saglabāts: *{email}*\n\n"
            "🎟 *Tu esi reģistrēts izlozei!*\n\n"
            f"👥 Dalībnieki: *{count}*\n"
            "📅 Izloze: *nākamā mēneša 1. datumā*\n"
            f"🏆 Balva: *+{prize_days} dienas* bezmaksas piekļuvei\n\n"
            "🍀 Lai veicas!"
        )
    else:
        text = (
            f"✅ E-mail saved: *{email}*\n\n"
            "🎟 *You're registered for the giveaway!*\n\n"
            f"👥 Participants: *{count}*\n"
            "📅 Drawing: *1st of next month*\n"
            f"🏆 Prize: *+{prize_days} days* free access\n\n"
            "🍀 Good luck!"
        )
    await message.answer(text, parse_mode="Markdown")


# ─── PROMO CODE (USER) ───


class WithdrawalState(StatesGroup):
    waiting_email = State()
    waiting_address = State()
    waiting_confirm = State()


class PromoCodeState(StatesGroup):
    waiting_code = State()


@dp.callback_query(F.data.startswith("promo_for_"))
async def promo_enter(callback: CallbackQuery, state: FSMContext):
    """promo_for_plan_monthly, promo_for_course_mini utt."""
    target = callback.data.replace("promo_for_", "")  # plan_monthly vai course_mini
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.set_state(PromoCodeState.waiting_code)
    await state.update_data(promo_target=target)
    if lang == "ru":
        text = "🎟 *Введи промокод:*\n\n/cancel для отмены"
    elif lang == "lv":
        text = "🎟 *Ievadi promokodu:*\n\n/cancel lai atceltu"
    else:
        text = "🎟 *Enter promo code:*\n\n/cancel to cancel"
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@dp.message(PromoCodeState.waiting_code)
async def promo_apply(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ui_text(lang, "Atcelts", "Отменено", "Cancelled"))
        return

    code = message.text.strip().upper()
    data = await state.get_data()
    target = data.get("promo_target", "")
    await state.clear()

    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    user_id = message.from_user.id

    # Pārbaudīt kodu DB
    promo = await db.get_promo_code(code)
    if not promo:
        await message.answer("❌ " + ui_text(lang, "Promokods nav atrasts.", "Промокод не найден.", "Promo code not found."))
        return

    # Pārbaudīt derīgumu
    if promo.get("max_uses") and promo.get("max_uses") > 0 and promo.get("used_count", 0) >= promo["max_uses"]:
        await message.answer("❌ " + ui_text(lang, "Promokods ir izlietots.", "Промокод исчерпан.", "Promo code exhausted."))
        return

    if promo.get("expires_at"):
        try:
            exp = datetime.fromisoformat(promo["expires_at"])
            if exp < datetime.utcnow():
                await message.answer("❌ " + ui_text(lang, "Promokodam beidzies termiņš.", "Промокод истёк.", "Promo code expired."))
                return
        except: pass

    # Pārbaudīt vai promo attiecas uz šo plānu/kursu
    promo_plan = promo.get("plan_key")
    is_course = target.startswith("course_")

    if promo_plan:
        # None = visiem, "all_courses" = visiem kursiem
        if promo_plan == "all_courses":
            if not is_course:
                await message.answer("❌ " + ui_text(lang, "Promokods der tikai kursiem.", "Промокод только для курсов.", "Promo code is for courses only."))
                return
        elif promo_plan != target:
            await message.answer("❌ " + ui_text(lang, "Promokods neder šim produktam.", "Промокод не подходит для этого продукта.", "Promo code not valid for this product."))
            return

    discount = promo.get("discount_percent", 0)

    # Noteikt cenu
    if is_course:
        ckey = target.replace("course_", "")
        item = config.COURSES.get(ckey)
        if not item: await message.answer("❌"); return
        saved = await db.get_setting(f"course_price_{ckey}")
        base_price = float(saved) if saved else item['price_usdt']
    else:
        pkey = target.replace("plan_", "") if target.startswith("plan_") else target
        item = config.PLANS.get(pkey)
        if not item: await message.answer("❌"); return
        saved = await db.get_setting(f"price_{pkey}")
        base_price = float(saved) if saved else item['price_usdt']

    # Piemērot atlaidi
    discounted = round(base_price * (1 - discount / 100), 2)
    unique_amount = await _get_unique_amount(target, user_id, discounted)

    if is_course:
        await db.set_pending_payment(user_id, target, unique_amount)
    else:
        pkey = target.replace("plan_", "") if target.startswith("plan_") else target
        await db.set_pending_payment(user_id, pkey, unique_amount)

    # Atzīmē kā aktīvu lietotāja promokodu; izlietojam tikai pēc veiksmīga pirkuma
    await db.apply_promo_to_user(user_id, code)

    name = item['name'][lang] if isinstance(item['name'], dict) else item['name']
    if lang == "ru":
        text = (
            f"🎟 *Промокод `{code}` применён!*\n\n"
            f"{'📚 Курс' if is_course else '📋 Тариф'}: *{name}*\n"
            f"💰 Цена: ~{base_price}~ → *{unique_amount} USDT* (-{discount}%)\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Отправь *{unique_amount} USDT (BEP-20)* на:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"⚠️ Только *USDT BEP-20* (BSC)"
        )
    else:
        text = (
            f"🎟 *Promo code `{code}` applied!*\n\n"
            f"{'📚 Course' if is_course else '📋 Plan'}: *{name}*\n"
            f"💰 Price: ~{base_price}~ → *{unique_amount} USDT* (-{discount}%)\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"⚠️ Only *USDT BEP-20* (BSC)"
        )

    b = InlineKeyboardBuilder()
    if is_course:
        b.button(text=paid_button_text(lang), callback_data=f"check_{target}")
    else:
        pkey = target.replace("plan_", "") if target.startswith("plan_") else target
        b.button(text=paid_button_text(lang), callback_data=f"check_{pkey}")
    b.button(text=back_button_text(lang), callback_data="settings_back")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ─── COURSES ───

class CourseEmailState(StatesGroup):
    waiting_email = State()


def _format_eur_price(value):
    value = float(value)
    return f"{value:.0f} EUR" if value == int(value) else f"{value} EUR"


def _course_ui_lang(lang):
    return "ru" if lang == "ru" else "lv"


@dp.callback_query(F.data == "courses_menu")
async def courses_menu(callback: CallbackQuery):
    """Kursu izvēlne - uzreiz rāda kursus"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    
    if ui_lang == "lv":
        text = (
            "📚 *MNtradepro kursi*\n\n"
            "Izvēlies kursu, lai apskatītu detaļas un apmaksas iespējas:"
        )
    elif ui_lang == "ru":
        text = (
            "📚 *Курсы MNtradepro*\n\n"
            "Выбери курс, чтобы узнать детали и способы оплаты:"
        )
    else:
        text = (
            "📚 *MNtradepro Courses*\n\n"
            "Choose a course to see details and payment options:"
        )
    
    b = InlineKeyboardBuilder()
    # Rādām visus kursus
    for key, course in config.COURSES.items():
        saved_price = await db.get_setting(f"course_price_{key}")
        if saved_price:
            try:
                p = float(saved_price)
                price_str = _format_eur_price(p)
            except:
                price_str = course['price_usd']
        else:
            price_str = course['price_usd']
        name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
        b.button(text=f"{course['emoji']} {name} — {price_str}", callback_data=f"course_info_{key}")
    
    b.button(text="🔙 " + ("Atpakaļ" if ui_lang == "lv" else "Назад"), callback_data="settings_back")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("course_info_"))
async def course_info_menu(callback: CallbackQuery):
    """Rāda kursa info un payment metodes"""
    course_key = callback.data.replace("course_info_", "")
    course = config.COURSES.get(course_key)
    if not course:
        await callback.answer("❌")
        return
    
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    
    saved_price = await db.get_setting(f"course_price_{course_key}")
    price = float(saved_price) if saved_price else course['price_usdt']
    price_str = _format_eur_price(price)
    
    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    
    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Cena: *{price_str}*\n\n"
            "📖 Detalizēts kursa apraksts un programma ir pieejama MNtradepro mājaslapā.\n\n"
            "Izvēlies apmaksas veidu:"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Цена: *{price_str}*\n\n"
            "📖 Подробное описание курса и программу "
            "можно посмотреть на сайте MNtradepro.\n\n"
            "Выбери способ оплаты:"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Price: *{price_str}*\n\n"
            "📖 Detailed course description and curriculum "
            "available on MNtradepro website.\n\n"
            "Choose payment method:"
        )
    
    checkout_url = await checkout_url_for_course(course_key)
    
    b = InlineKeyboardBuilder()
    if checkout_url:
        b.button(text="💳 " + ("Maksāt ar karti / banku / crypto" if ui_lang == "lv" else "Оплатить картой / банком / crypto"), url=checkout_url)
    else:
        b.button(text="💳 " + ("Maksāt ar karti / banku / crypto" if ui_lang == "lv" else "Оплатить картой / банком / crypto"), callback_data=f"course_checkout_missing_{course_key}")
    b.button(text="🔙 " + ("Atpakaļ" if ui_lang == "lv" else "Назад"), callback_data="courses_menu")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("course_checkout_missing_"))
async def course_checkout_missing(callback: CallbackQuery):
    await callback.answer("Checkout links šim kursam vēl nav iestatīts admin panelī.", show_alert=True)


@dp.callback_query(F.data.startswith("course_crypto_"))
async def course_crypto_selected(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    await callback.answer(
        ui_text(
            lang,
            "Kursu crypto apmaksa botā vairs netiek izmantota. Izmanto kursa checkout pogu.",
            "Crypto-оплата курсов в боте больше не используется. Используй checkout-кнопку курса.",
            "Course crypto payment inside the bot is no longer used. Please use the course checkout button.",
        ),
        show_alert=True,
    )
    return
    """User izvēlējās crypto payment konkrētam kursam"""
    course_key = callback.data.replace("course_crypto_", "")
    course = config.COURSES.get(course_key)
    if not course:
        await callback.answer("❌")
        return
    
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""
    
    # Pārbauda email
    if not email:
        if ui_lang == "lv":
            text = (
                "📚 *Kursa iegāde*\n\n"
                "⚠️ Kursa iegādei nepieciešams *e-pasts* — tas tiks izmantots kā tavs piekļuves e-pasts.\n\n"
                "📧 _Atsūti savu e-pastu:_\n/cancel lai atceltu"
            )
        elif ui_lang == "ru":
            text = (
                "📚 *Покупка курса*\n\n"
                "⚠️ Для покупки курса необходимо указать *e-mail* — "
                "он будет использован как логин в обучающей платформе.\n\n"
                "📧 _Отправь свой e-mail:_\n/cancel для отмены"
            )
        else:
            text = (
                "📚 *Course Purchase*\n\n"
                "⚠️ An *e-mail* is required to purchase a course — "
                "it will be used as your login for the learning platform.\n\n"
                "📧 _Send your e-mail:_\n/cancel to cancel"
            )
        await state.set_state(CourseEmailState.waiting_email)
        await state.update_data(selected_course=course_key)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return
    
    # Ir email - rādām payment
    await _show_course_payment(callback, course_key, email, lang)


async def _show_course_payment(callback, course_key, email, lang):
    """Rāda crypto payment info konkrētam kursam"""
    course = config.COURSES.get(course_key)
    if not course:
        return
    ui_lang = _course_ui_lang(lang)
    
    user_id = callback.from_user.id
    
    # Cena
    saved_price = await db.get_setting(f"course_price_{course_key}")
    base_price = float(saved_price) if saved_price else course['price_usdt']
    
    # FIX: Ja jau ir pending ar šo kursu — reuse
    pending_key = f"course_{course_key}"
    existing_pending = await db.get_pending_payment(user_id)
    if existing_pending and existing_pending.get("plan_key") == pending_key and existing_pending.get("amount_usdt"):
        unique_amount = float(existing_pending["amount_usdt"])
    else:
        unique_amount = await _get_unique_amount(pending_key, user_id, base_price)
        await db.set_pending_payment(user_id, pending_key, unique_amount)
    
    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    
    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Cena: *{unique_amount} USDT*\n"
            f"📧 E-pasts: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Nosūti *{unique_amount} USDT (BEP-20)* uz:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Tikai *USDT BEP-20* (BSC tīkls)\n"
            f"Pēc apmaksas nospied pogu zemāk"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Цена: *{unique_amount} USDT*\n"
            f"📧 Логин: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Отправь *{unique_amount} USDT (BEP-20)* на:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Только *USDT BEP-20* (сеть BSC)\n"
            f"После оплаты нажми кнопку ниже"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Price: *{unique_amount} USDT*\n"
            f"📧 Login: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Only *USDT BEP-20* (BSC network)\n"
            f"After payment press the button below"
        )
    
    b = InlineKeyboardBuilder()
    b.button(text="✅ " + ("Esmu apmaksājis" if ui_lang == "lv" else "Я оплатил"), callback_data=f"check_course_{course_key}")
    b.button(text="🔙 " + ("Atpakaļ" if ui_lang == "lv" else "Назад"), callback_data=f"course_info_{course_key}")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "courses_crypto")
async def courses_crypto(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""

    # E-pasts obligāts kursiem
    if not email:
        if ui_lang == "lv":
            text = (
                "📚 *Kursa iegāde*\n\n"
                "⚠️ Kursa iegādei nepieciešams *e-pasts* — tas tiks izmantots kā tavs piekļuves e-pasts.\n\n"
                "📧 _Atsūti savu e-pastu:_\n/cancel lai atceltu"
            )
        elif ui_lang == "ru":
            text = (
                "📚 *Покупка курса*\n\n"
                "⚠️ Для покупки курса необходимо указать *e-mail* — "
                "он будет использован как логин в обучающей платформе.\n\n"
                "📧 _Отправь свой e-mail:_\n/cancel для отмены"
            )
        else:
            text = (
                "📚 *Course Purchase*\n\n"
                "⚠️ An *e-mail* is required to purchase a course — "
                "it will be used as your login for the learning platform.\n\n"
                "📧 _Send your e-mail:_\n/cancel to cancel"
            )
        await state.set_state(CourseEmailState.waiting_email)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return

    # Ir e-pasts — rādām kursu izvēlni
    await _show_courses_list(callback, lang)
    await callback.answer()


@dp.callback_query(F.data == "courses_crypto_after_email")
async def courses_crypto_after(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await _show_courses_list(callback, lang)
    await callback.answer()


async def _show_courses_list(callback, lang):
    ui_lang = _course_ui_lang(lang)
    if ui_lang == "lv":
        text = "📚 *Izvēlies kursu:*"
    elif ui_lang == "ru":
        text = "📚 *Выбери курс:*"
    else:
        text = "📚 *Choose a course:*"
    b = InlineKeyboardBuilder()
    for key, course in config.COURSES.items():
        # Cena no DB settings vai config
        saved_price = await db.get_setting(f"course_price_{key}")
        if saved_price:
            try:
                p = float(saved_price)
                price_str = _format_eur_price(p)
            except: price_str = course['price_usd']
        else:
            price_str = course['price_usd']
        name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
        b.button(text=f"{course['emoji']} {name} — {price_str}", callback_data=f"course_{key}")
    b.button(text="🔙 " + ("Atpakaļ" if ui_lang == "lv" else "Назад"), callback_data="courses_menu")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.message(CourseEmailState.waiting_email)
async def course_receive_email(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    await message.answer(
        ui_text(
            lang,
            "Kursu pirkumi tagad notiek tikai caur mājaslapas checkout. E-pastu vari mainīt iestatījumos.",
            "Покупки курсов теперь работают только через checkout на сайте. E-mail можно менять в настройках.",
            "Course purchases now work only through website checkout. You can still change your e-mail in settings.",
        )
    )
    return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌")
        return
    
    email = message.text.strip()
    if "@" not in email or "." not in email or len(email) < 5:
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("❌ " + ("Nepareizs e-pasts. Pamēģini vēlreiz:" if lang == "lv" else ("Неверный e-mail. Попробуй:" if lang == "ru" else "Invalid e-mail. Try:")))
        return
    
    data = await state.get_data()
    selected_course = data.get("selected_course")
    await state.clear()
    
    await db.set_user_email(message.from_user.id, email)
    await attach_pending_email_purchases(message.from_user.id, email, "lv", message.from_user.username or "")
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    
    if lang == "lv":
        confirm_text = f"✅ E-pasts saglabāts: *{email}*"
    elif lang == "ru":
        confirm_text = f"✅ E-mail сохранён: *{email}*"
    else:
        confirm_text = f"✅ E-mail saved: *{email}*"
    
    await message.answer(confirm_text, parse_mode="Markdown")
    
    # Ja ir izvēlēts kurss, rādām payment
    if selected_course:
        # Create a callback mock to reuse _show_course_payment
        class CallbackMock:
            def __init__(self, msg, user_id):
                self.message = msg
                self.from_user = type('obj', (object,), {'id': user_id})
            async def answer(self): pass
        
        # Send payment info
        await _show_course_payment(CallbackMock(message, message.from_user.id), selected_course, email, lang)


@dp.callback_query(F.data.startswith("course_"))
async def course_selected(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    await callback.answer(
        ui_text(
            lang,
            "Šī vecā kursa apmaksas poga vairs netiek izmantota. Atver kursu no jaunās izvēlnes un izmanto checkout.",
            "Эта старая кнопка оплаты курса больше не используется. Открой курс из нового меню и используй checkout.",
            "This old course payment button is no longer used. Open the course from the new menu and use checkout.",
        ),
        show_alert=True,
    )
    return
    course_key = callback.data.replace("course_", "")
    course = config.COURSES.get(course_key)
    if not course: await callback.answer("❌"); return

    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""

    if not email:
        await callback.answer("⚠️ Nepieciešams e-pasts!" if ui_lang == "lv" else "⚠️ Нужен e-mail!", show_alert=True)
        return

    # Cena no DB
    saved_price = await db.get_setting(f"course_price_{course_key}")
    base_price = float(saved_price) if saved_price else course['price_usdt']

    # Unikāla summa (slot sistēma)
    unique_amount = await _get_unique_amount(f"course_{course_key}", user_id, base_price)
    await db.set_pending_payment(user_id, f"course_{course_key}", unique_amount)

    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Cena: *{unique_amount} USDT*\n"
            f"📧 E-pasts: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Nosūti *{unique_amount} USDT (BEP-20)* uz:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Tikai *USDT BEP-20* (BSC tīkls)\n"
            f"Pēc apmaksas nospied pogu zemāk"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Цена: *{unique_amount} USDT*\n"
            f"📧 Логин: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Отправь *{unique_amount} USDT (BEP-20)* на:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Только *USDT BEP-20* (сеть BSC)\n"
            f"После оплаты нажми кнопку ниже"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Price: *{unique_amount} USDT*\n"
            f"📧 Login: *{email}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Only *USDT BEP-20* (BSC network)\n"
            f"After payment press the button below"
        )
    b = InlineKeyboardBuilder()
    b.button(text="✅ " + ("Esmu apmaksājis" if ui_lang == "lv" else "Я оплатил"), callback_data=f"check_course_{course_key}")
    b.button(text="🔙 " + ("Atpakaļ" if ui_lang == "lv" else "Назад"), callback_data="courses_crypto")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("check_course_"))
async def check_course_payment(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    await callback.answer(
        ui_text(
            lang,
            "Vecā kursa maksājuma pārbaude ir izņemta. Kursu pirkumi tagad nāk tikai no mājaslapas webhook.",
            "Старая проверка оплаты курса удалена. Покупки курсов теперь приходят только через webhook сайта.",
            "The old course payment check has been removed. Course purchases now arrive only through the website webhook.",
        ),
        show_alert=True,
    )
    return
    course_key = callback.data.replace("check_course_", "")
    course = config.COURSES.get(course_key)
    if not course: await callback.answer("❌"); return

    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else "?"
    username = callback.from_user.username or ""

    pending = await db.get_pending_payment(user_id)
    if not pending or not pending.get("amount_usdt"):
        await callback.answer(ui_text(lang, "⚠️ Nav gaidoša maksājuma", "⚠️ Нет ожидающего платежа", "⚠️ No pending payment"), show_alert=True); return
    expected = float(pending["amount_usdt"])

    await callback.answer("⏳...")
    msg = await callback.message.edit_text("⏳ *" + ui_text(lang, "Pārbaudu...", "Проверяю...", "Checking...") + "*", parse_mode="Markdown")

    tx = await check_payment(config.CRYPTO_WALLET, expected, user_id)
    if tx:
        name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
        name_ru = course['name']['ru'] if isinstance(course['name'], dict) else course['name']
        await db.delete_pending_payment(user_id)

        # Saglabāt pirkumu UN iegūt purchase_id
        purchase_id = await db.add_course_purchase(user_id, username, course_key, name_ru, expected, tx, email)
        active_promo_code = await db.get_user_active_promo(user_id)
        if active_promo_code:
            await db.use_promo_code(active_promo_code)
            await db.clear_user_promo(user_id)

        ref = await db.get_referral_by_referred(user_id)
        if ref and False:
            pass
        # ═══════════════════════════════════════════════════════════════

        if lang == "ru":
            text = (
                f"✅ *Оплата подтверждена!*\n\n"
                f"📚 Курс: *{name}*\n"
                f"🔖 TX: `{tx}`\n\n"
                f"🙏 Спасибо за покупку!\n"
                f"Ваши данные доступа к обучающей платформе будут "
                f"отправлены после проверки и подтверждения оплаты."
            )
        elif lang == "lv":
            text = (
                f"✅ *Maksājums apstiprināts!*\n\n"
                f"📚 Kurss: *{name}*\n"
                f"🔖 TX: `{tx}`\n\n"
                f"🙏 Paldies par pirkumu!\n"
                f"Piekļuves dati mācību platformai tiks nosūtīti "
                f"pēc maksājuma pārbaudes un apstiprināšanas."
            )
        else:
            text = (
                f"✅ *Payment confirmed!*\n\n"
                f"📚 Course: *{name}*\n"
                f"🔖 TX: `{tx}`\n\n"
                f"🙏 Thank you for your purchase!\n"
                f"Your access credentials for the learning platform "
                f"will be sent after payment verification and confirmation."
            )
        await msg.edit_text(text, parse_mode="Markdown")

        # Admin paziņojums
        admin_text = (
            f"📚 *Jauns kursa pirkums!*\n\n"
            f"👤 @{username} (`{user_id}`)\n"
            f"📧 E-mail: `{email}`\n"
            f"📚 Kurss: *{name_ru}*\n"
            f"💰 Summa: *{expected} USDT*\n"
            f"🔖 TX: `{tx}`"
        )
        for aid in config.ADMIN_IDS:
            try: await bot.send_message(aid, admin_text, parse_mode="Markdown")
            except: pass

        # Referral bonus wallet arī par kursa pirkumu
        ref = await db.get_referral_by_referred(user_id)
        if ref and not ref.get("bonus_given"):
            referrer = await db.get_user(ref["referrer_id"])
            if referrer:
                new_balance_days = await db.add_referral_bonus_days(
                    ref["referrer_id"],
                    REFERRAL_BONUS_DAYS,
                    note=f"referred_course_purchase:{user_id}"
                )
                await db.mark_referral_bonus_given(user_id)
                rlang = referrer.get("lang", "ru")
                try:
                    await bot.send_message(
                        ref["referrer_id"],
                        ui_text(
                            rlang,
                            (
                                "🎉 *Referral bonuss saņemts!*\n\n"
                                f"Tavs draugs veica pirkumu, un tev piešķirtas *+{REFERRAL_BONUS_DAYS} bonusu dienas*.\n"
                                f"Tagad tavā balansā ir *{new_balance_days}* bonusu dienas.\n\n"
                                "Atver referral sadaļu un izvēlies, kuram aktīvajam čatam tās pielikt."
                            ),
                            (
                                "🎉 *Реферальный бонус получен!*\n\n"
                                f"Твой друг совершил покупку, и тебе начислено *+{REFERRAL_BONUS_DAYS} бонусных дней*.\n"
                                f"Теперь на твоем балансе *{new_balance_days}* бонусных дней.\n\n"
                                "Открой раздел referral и выбери, к какому активному чату их применить."
                            ),
                            (
                                "🎉 *Referral bonus received!*\n\n"
                                f"Your friend made a purchase and you received *+{REFERRAL_BONUS_DAYS} bonus days*.\n"
                                f"You now have *{new_balance_days}* bonus days in your balance.\n\n"
                                "Open the referral section and choose which active chat to apply them to."
                            ),
                        ),
                        parse_mode="Markdown")
                except: pass
    else:
        if lang == "ru":
            text = f"❌ *Платёж не найден*\n\nУбедись что отправил *{expected} USDT (BEP-20)*"
        else:
            text = f"❌ *Payment not found*\n\nMake sure you sent *{expected} USDT (BEP-20)*"
        b = InlineKeyboardBuilder()
        b.button(text="🔄 " + ui_text(lang, "Pārbaudīt vēlreiz", "Проверить снова", "Check again"), callback_data=f"check_course_{course_key}")
        b.button(text=back_button_text(lang), callback_data="courses_crypto")
        b.adjust(1)
        await msg.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ─── DEBUG / ERROR NOTIFICATIONS ───
async def notify_admins(text: str, parse_mode: str = "Markdown"):
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, text, parse_mode=parse_mode)
        except Exception:
            pass


async def notify_admins_error(context: str, error: str):
    """Sūta admin paziņojumu par kļūdu"""
    text = f"⚠️ *Bota kļūda*\n\n📍 `{context}`\n❌ `{str(error)[:500]}`"
    await notify_admins(text, parse_mode="Markdown")


# ─── FIX #3: SLOT NO DB ───
async def _get_unique_amount(plan_key, user_id, base_price):
    mem_slots = [amt for uid, amt in _active_payment_sessions.items() if isinstance(amt, float) and uid != user_id]
    db_slots = await db.get_active_pending_amounts(plan_key)
    taken = set(mem_slots + db_slots)
    slot = 0
    while True:
        c = round(base_price + slot * 0.01, 2)
        if c not in taken: return c
        slot += 1

# ─── PLAN/PAYMENT ───
@dp.callback_query(F.data.startswith("plan_"))
async def plan_selected(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    text = ui_text(
        lang,
        "Šī apmaksas metode vairs netiek izmantota. Izmanto mājaslapas checkout pogas.",
        "Этот способ оплаты больше не используется. Используй checkout-кнопки сайта.",
        "This payment method is no longer used. Please use the website checkout buttons.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("❌", show_alert=True); return
    plan = config.PLANS[plan_key]
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    if not (user and user.get("email")):
        await callback.message.edit_text(
            "📧 " + ("Vispirms iestati e-pastu. Tas ir vajadzīgs, lai piesaistītu piekļuvi." if lang == "lv" else ("Сначала укажи e-mail в настройках. Он нужен для привязки доступа." if lang == "ru" else "Please set your e-mail in Settings first. It is needed to link your access.")),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    saved = await db.get_setting(f"price_{plan_key}")
    base = float(saved) if saved else plan['price_usdt']
    
    # FIX: Ja lietotājam jau ir pending ar šo pašu plānu — NEĢENERĒT jaunu summu
    existing_pending = await db.get_pending_payment(user_id)
    if existing_pending and existing_pending.get("plan_key") == plan_key and existing_pending.get("amount_usdt"):
        unique_amount = float(existing_pending["amount_usdt"])
        logger.info(f"[plan_selected] Reuse existing pending: user={user_id} amount={unique_amount}")
    else:
        unique_amount = await _get_unique_amount(plan_key, user_id, base)
        await db.set_pending_payment(user_id, plan_key, unique_amount)
    
    plan_name = plan['name'][lang] if isinstance(plan['name'], dict) else plan['name']
    await callback.message.edit_text(
        t(lang, "payment_title", emoji=plan['emoji'], name=plan_name, price=plan['price_usd'],
          usdt=unique_amount, days=plan['days'] if plan['days'] < 36500 else "∞", wallet=config.CRYPTO_WALLET),
        reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
    
    # Admin paziņojums par jaunu pending payment
    uname = f"@{callback.from_user.username}" if callback.from_user.username else f"ID {user_id}"
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"🔔 *Jauns maksājums gaida!*\n\n"
                f"👤 {uname} (`{user_id}`)\n"
                f"📦 {plan['emoji']} {plan_name}\n"
                f"💰 *{unique_amount} USDT*\n"
                f"⏱ Taimeris: 15 min",
                parse_mode="Markdown")
        except: pass
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment_cb(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    text = ui_text(
        lang,
        "Automātiskā crypto pārbaude ir izņemta. Pirkums tagad notiek tikai caur mājaslapu un webhook.",
        "Автопроверка crypto удалена. Теперь покупка работает только через сайт и webhook.",
        "Automatic crypto checking has been removed. Purchases now work only via website checkout and webhook.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("❌", show_alert=True); return
    user_id = callback.from_user.id
    if user_id in _active_payment_sessions:
        await callback.answer("⏳ Pārbaude jau notiek!", show_alert=True); return
    plan = dict(config.PLANS[plan_key])
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    pending = await db.get_pending_payment(user_id)
    if pending and pending.get("amount_usdt"):
        expected = float(pending["amount_usdt"])
    else:
        saved = await db.get_setting(f"price_{plan_key}")
        base = float(saved) if saved else plan['price_usdt']
        expected = await _get_unique_amount(plan_key, user_id, base)
        await db.set_pending_payment(user_id, plan_key, expected)
    plan['price_usdt'] = expected
    await callback.answer()
    start_text = (
        f"⏳ *{ui_text(lang, 'Pārbaudu maksājumu', 'Проверяю платёж', 'Checking payment')}...*\n\n"
        f"⏱ {ui_text(lang, 'Atlicis', 'Осталось', 'Time left')}: *15:00*\n\n"
        f"{ui_text(lang, 'Bots automātiski pārbauda ik pēc 10 sekundēm', 'Бот автоматически проверяет каждые 10 секунд', 'Auto-checking every 10 sec')}"
    )
    try:
        await callback.message.edit_text(start_text, parse_mode="Markdown"); msg = callback.message
    except Exception:
        msg = await callback.message.answer(start_text, parse_mode="Markdown")
    _active_payment_sessions[user_id] = expected
    asyncio.create_task(_confirm_payment(user_id, plan_key, plan, lang, msg, callback.from_user.username or ""))

# ─── UNIVERSĀLA AKTIVIZĀCIJA ───
async def _do_activate(user_id, plan_key, plan, lang, username, tx_hash, amount):
    now = datetime.utcnow()
    product_meta = resolve_subscription_product(plan_key, lang)
    canonical_key = product_meta.get("product_key", plan_key)
    plan_name_save = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    if product_meta and isinstance(product_meta.get("name"), dict):
        plan_name_save = product_meta["name"].get("ru", plan_name_save)
        plan_name_loc = product_meta["name"].get(lang, plan_name_save)
    else:
        plan_name_loc = plan['name'].get(lang, plan_name_save) if isinstance(plan['name'], dict) else plan['name']
    active_subs = await db.get_active_user_subscriptions(user_id)
    current_same = next((s for s in active_subs if s.get("product_key") == canonical_key), None)
    if current_same and current_same.get("expires_at"):
        cur_exp = datetime.fromisoformat(current_same["expires_at"])
        new_exp = (cur_exp if cur_exp > now else now) + timedelta(days=plan['days'])
    else:
        new_exp = now + timedelta(days=plan['days'])
    await db.activate_product_subscription(
        user_id=user_id,
        username=username,
        product_key=canonical_key,
        product_name=plan_name_save,
        expires_at=new_exp,
        tx_hash=tx_hash,
        amount_usdt=amount,
        chat_id=product_meta.get("chat_id", 0) if product_meta else 0,
        chat_link=product_meta.get("chat_link", "") if product_meta else "",
        payment_system="webhook" if tx_hash.startswith("webhook:") else ""
    )
    active_promo_code = await db.get_user_active_promo(user_id)
    if active_promo_code:
        await db.use_promo_code(active_promo_code)
        await db.clear_user_promo(user_id)
    winback_bonus_days = 0
    active_winback = await db.get_active_winback_offer(user_id)
    if active_winback and product_meta and int(product_meta.get("chat_id") or 0) != 0:
        bonus_days = int(active_winback.get("bonus_days") or 0)
        bonus_exp = await db.extend_product_subscription(user_id, canonical_key, bonus_days)
        if bonus_exp:
            winback_bonus_days = bonus_days
            new_exp = bonus_exp
            await db.redeem_winback_offer(user_id, tx_hash)
            bonus_text = ui_text(
                lang,
                f"🎁 *Atgriešanās bonuss aktivizēts!*\n\nTev pievienotas *+{bonus_days} bezmaksas dienas*.\n📅 Aktīvs līdz: *{new_exp.strftime('%d.%m.%Y')}*",
                f"🎁 *Win-back бонус активирован!*\n\nТебе добавлено *+{bonus_days} бесплатных дней*.\n📅 Активно до: *{new_exp.strftime('%d.%m.%Y')}*",
                f"🎁 *Win-back bonus activated!*\n\nYou received *+{bonus_days} free days*.\n📅 Active until: *{new_exp.strftime('%d.%m.%Y')}*",
            )
            try:
                await bot.send_message(user_id, bonus_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to send winback bonus notice {user_id}: {e}")
    # Referral bonus days
    ref = await db.get_referral_by_referred(user_id)
    if ref and not ref.get("bonus_given"):
        referrer = await db.get_user(ref["referrer_id"])
        if referrer:
            new_balance_days = await db.add_referral_bonus_days(
                ref["referrer_id"],
                REFERRAL_BONUS_DAYS,
                note=f"referred_user_purchase:{user_id}"
            )
            await db.mark_referral_bonus_given(user_id)
            ref_lang = referrer.get("lang", "ru")
            if ref_lang == "ru":
                ref_text = (
                    f"🎁 *Бонус за друга!*\n\n"
                    f"Твой реферал оформил подписку.\n"
                    f"Тебе начислено *+{REFERRAL_BONUS_DAYS} бонусных дней*.\n"
                    f"Теперь доступно: *{new_balance_days}* дней.\n\n"
                    "Используй их сам и выбери, к какому активному чату применить бонус."
                )
            elif ref_lang == "lv":
                ref_text = (
                    f"🎁 *Bonuss par draugu!*\n\n"
                    f"Tavs referral noformēja abonementu.\n"
                    f"Tev ieskaitītas *+{REFERRAL_BONUS_DAYS} bonusu dienas*.\n"
                    f"Tagad pieejams: *{new_balance_days}* dienas.\n\n"
                    "Izmanto tās pats un izvēlies, kuram aktīvajam čatam pielikt bonusu."
                )
            else:
                ref_text = (
                    f"🎁 *Referral bonus!*\n\n"
                    f"Your referral purchased a subscription.\n"
                    f"You received *+{REFERRAL_BONUS_DAYS} bonus days*.\n"
                    f"You now have: *{new_balance_days}* days available.\n\n"
                    "Use them yourself and choose which active chat should receive the bonus."
                )
            try:
                await bot.send_message(ref["referrer_id"], ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {ref['referrer_id']}: {e}")

    # Legacy referral branch kept disabled for compatibility
    ref = await db.get_referral_by_referred(user_id)
    if False and ref and not ref.get("bonus_given"):
        referrer = await db.get_user(ref["referrer_id"])
        if referrer:
            # 1. Give +10 days bonus
            rb = datetime.fromisoformat(referrer['expires_at']) if referrer.get('expires_at') else now
            bexp = (rb if rb > now else now) + timedelta(days=REFERRAL_BONUS_DAYS)
            await db.activate_product_subscription(user_id=ref["referrer_id"], username=referrer.get("username"), product_key=referrer.get("plan_key") or "referral_bonus", product_name=f"Referral Bonus +{REFERRAL_BONUS_DAYS}d", expires_at=bexp, tx_hash=f"ref_bonus_{user_id}_{int(now.timestamp())}", chat_id=0, chat_link="")
            await db.mark_referral_bonus_given(user_id)
            ref_lang = referrer.get("lang", "ru")
            if ref_lang == "ru":
                ref_text = f"🎁 *Бонус за друга!*\n\nТвой реферал оформил подписку.\nТебе добавлено *+{REFERRAL_BONUS_DAYS} дней* бесплатного доступа."
            elif ref_lang == "lv":
                ref_text = f"🎁 *Bonuss par draugu!*\n\nTavs referral noformēja abonementu.\nTev pievienotas *+{REFERRAL_BONUS_DAYS} bezmaksas dienas*."
            else:
                ref_text = f"🎁 *Referral bonus!*\n\nYour referral purchased a subscription.\nYou received *+{REFERRAL_BONUS_DAYS} free days*."
            try:
                await bot.send_message(ref["referrer_id"], ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {ref['referrer_id']}: {e}")
            uname = f"@{username}" if username else f"ID {user_id}"
            for aid in config.ADMIN_IDS:
                try: await bot.send_message(aid, f"ðŸ’° *Jauns maksÄjums!*\n\nðŸ‘¤ {uname} (`{user_id}`)\nðŸ“¦ *{plan_name_loc}*\nðŸ’µ *{amount} USDT*\nðŸ“… LÄ«dz: *{new_exp.strftime('%d.%m.%Y')}*\nðŸ”– TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
                except: pass
            return new_exp, plan_name_loc, product_meta
    # Admin notify
    uname = f"@{username}" if username else f"ID {user_id}"
    for aid in config.ADMIN_IDS:
        try:
            extra = f"\n🎁 Win-back bonuss: *+{winback_bonus_days} d.*" if winback_bonus_days else ""
            await bot.send_message(aid, f"💰 *Jauns maksājums!*\n\n👤 {uname} (`{user_id}`)\n📦 *{plan_name_loc}*\n💵 *{amount} USDT*\n📅 Līdz: *{new_exp.strftime('%d.%m.%Y')}*{extra}\n🔖 TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
        except: pass
    return new_exp, plan_name_loc, product_meta

# Pēc veiksmīga payment — nosūtīt referral reminder pēc 5 min
async def _post_payment_actions(user_id, lang):
    """Darbības pēc veiksmīga maksājuma — referral reminder"""
    asyncio.create_task(_send_referral_reminder(user_id, lang))

async def _confirm_payment(user_id, plan_key, plan, lang, msg, username):
    logger.info("Legacy _confirm_payment call skipped; website checkout + webhook flow is active.")
    return
    elapsed = 0
    try:
        for _ in range(PAYMENT_MAX_ATTEMPTS):
            await asyncio.sleep(PAYMENT_POLL_INTERVAL)
            elapsed += PAYMENT_POLL_INTERVAL
            remaining = PAYMENT_TIMEOUT_SEC - elapsed
            paid = await check_payment(config.CRYPTO_WALLET, plan['price_usdt'], user_id)
            if paid:
                new_exp, plan_name_loc, product_meta = await _do_activate(user_id, plan_key, plan, lang, username, paid, plan['price_usdt'])
                inv = await invite_text_for_product(user_id, lang, product_meta, new_exp)
                txt = t(lang, "paid_ok", name=plan_name_loc, expires=new_exp.strftime('%d.%m.%Y'), tx=paid[:20]) + inv
                try: await msg.edit_text(txt, parse_mode="Markdown")
                except: await bot.send_message(user_id, txt, parse_mode="Markdown")
                await _post_payment_actions(user_id, lang)
                return
            if elapsed % 30 == 0 and remaining > 0:
                m, s = remaining // 60, remaining % 60
                try: await msg.edit_text(f"⏳ *{ui_text(lang, 'Pārbaudu maksājumu', 'Проверяю платёж', 'Checking')}...*\n\n⏱ {ui_text(lang, 'Atlicis', 'Осталось', 'Left')}: *{m}:{s:02d}*\n\n{ui_text(lang, 'Automātiska pārbaude ik pēc 10 sekundēm', 'Автоматическая проверка каждые 10 секунд', 'Auto-check every 10 sec')}", parse_mode="Markdown")
                except: pass
        timeout_txt = ui_text(
            lang,
            "❌ *Laiks beidzās (15 min)*\n\nJa nosūtīji maksājumu, pagaidi - bots to pārbauda fonā ik pēc 3 min.",
            "❌ *Время вышло (15 мин)*\n\nЕсли отправил — подожди, бот проверяет фоном каждые 3 мин.",
            "❌ *Timeout (15 min)*\n\nIf sent — wait, bot checks background every 3 min."
        )
        try: await msg.edit_text(timeout_txt, reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
        except: await bot.send_message(user_id, timeout_txt, reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
    except asyncio.CancelledError: pass
    except Exception as e: logger.error(f"Payment poll error user={user_id}: {e}", exc_info=True)
    finally: _active_payment_sessions.pop(user_id, None)

@dp.callback_query(F.data == "vip_chat_plans")
async def show_vip_chat_plans(callback: CallbackQuery):
    """Parāda pieejamos VIP čatus. Pirkums notiek mājaslapā."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if not (user and user.get("email")):
        text = (
            "📧 Vispirms iestati e-pastu. Pēc pirkuma mājaslapa sūtīs webhook, un bots piekļuvi atradīs tieši pēc šī e-pasta."
            if lang == "lv" else
            ("📧 Сначала укажи e-mail. После покупки сайт отправит webhook, и бот найдёт доступ именно по этому e-mail."
             if lang == "ru" else
             "📧 Please set your e-mail first. After purchase the website will send a webhook, and the bot will match access by this e-mail.")
        )
        await callback.message.edit_text(text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
        await callback.answer()
        return
    text = (
        "💎 *Izvēlies VIP čatu:*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski piesaistīs piekļuvi pēc tava e-pasta."
        if lang == "lv" else
        ("💎 *Выбери VIP чат:*\n\nПокупка происходит на сайте. После оплаты бот автоматически привяжет доступ по твоему e-mail."
         if lang == "ru" else
         "💎 *Choose VIP chat:*\n\nPurchase happens on the website. After payment the bot will link access by your e-mail.")
    )
    await callback.message.edit_text(text, reply_markup=await vip_channel_keyboard(lang), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("vip_checkout_"))
async def vip_checkout_missing_or_open(callback: CallbackQuery):
    code = callback.data.replace("vip_checkout_", "")
    user = await db.get_user(callback.from_user.id)
    if not (user and user.get("email")):
        await callback.answer("Vispirms iestati e-pastu botā.", show_alert=True)
        return
    url = await checkout_url_for_lang(code)
    if url:
        b = InlineKeyboardBuilder()
        b.button(text="Atvērt checkout" if code == "lv" else "Открыть checkout", url=url)
        b.adjust(1)
        await callback.message.answer("Checkout links:", reply_markup=b.as_markup())
        await callback.answer()
        return
    await callback.answer("Checkout links šai pogai vēl nav iestatīts admin panelī.", show_alert=True)


@dp.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery):
    """Atpakaļ uz galveno izvēlni"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    
    # Pārbauda vai ir aktīva subscription
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    if active_subs:
        text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
        expires_dt = datetime.fromisoformat(user['expires_at'])
        text = t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=max(0, (expires_dt - datetime.utcnow()).days))
        await callback.message.edit_text(text, reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        # Neaktīviem - main_menu
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    
    await callback.answer()


@dp.callback_query(F.data == "back_plans")
async def back_to_plans(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    text = "💎 *Izvēlies VIP čatu:*" if lang == "lv" else ("💎 *Выбери VIP чат:*" if lang == "ru" else "💎 *Choose VIP chat:*")
    await callback.message.edit_text(text, reply_markup=await vip_channel_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("qr_"))
async def show_qr_code(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    text = ui_text(
        lang,
        "QR crypto apmaksa vairs nav aktīva. Izmanto checkout pogas botā.",
        "QR crypto оплата больше не активна. Используй checkout-кнопки в боте.",
        "QR crypto payment is no longer active. Use the checkout buttons in the bot.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("❌", show_alert=True); return
    plan = config.PLANS[plan_key]
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    pending = await db.get_pending_payment(callback.from_user.id)
    usdt = pending["amount_usdt"] if pending else plan['price_usdt']
    await callback.answer()
    try:
        import qrcode, io
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
        qr.add_data(config.CRYPTO_WALLET); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        from aiogram.types import BufferedInputFile
        b = InlineKeyboardBuilder()
        b.button(text=t(lang, "btn_paid"), callback_data=f"check_{plan_key}"); b.adjust(1)
        await callback.message.answer_photo(BufferedInputFile(buf.getvalue(), filename="qr.png"), caption=t(lang, "qr_caption", usdt=usdt, wallet=config.CRYPTO_WALLET), reply_markup=b.as_markup(), parse_mode="Markdown")
    except ImportError:
        await callback.answer(f"📋 {config.CRYPTO_WALLET}", show_alert=True)

# ─── FIX #2: AUTO-CHECK FONS ───
async def auto_check_pending_payments():
    return
    pending = await db.get_all_pending_payments()
    for p in pending:
        uid, amount, pk = p['user_id'], p['amount_usdt'], p['plan_key']
        if uid in _active_payment_sessions: continue

        is_course = pk.startswith("course_")
        if not is_course and pk not in config.PLANS: continue
        if is_course:
            ckey = pk.replace("course_", "")
            if ckey not in config.COURSES: continue

        try:
            tx = await check_payment(config.CRYPTO_WALLET, amount, uid)
            if tx:
                user = await db.get_user(uid)
                lang = user.get("lang", "ru") if user else "ru"
                username = user.get("username", "") if user else ""

                if is_course:
                    # Kursa pirkums
                    ckey = pk.replace("course_", "")
                    course = config.COURSES[ckey]
                    cname = course['name']['ru'] if isinstance(course['name'], dict) else course['name']
                    email = user.get("email", "?") if user else "?"
                    await db.add_course_purchase(uid, username, ckey, cname, amount, tx, email)
                    await db.delete_pending_payment(uid)
                    if lang == "ru":
                        msg = f"✅ *Оплата курса подтверждена!*\n\n📚 {cname}\n🔖 TX: `{tx[:20]}`\n\n🙏 Данные доступа будут отправлены после проверки."
                    else:
                        msg = f"✅ *Course payment confirmed!*\n\n📚 {cname}\n🔖 TX: `{tx[:20]}`\n\n🙏 Access credentials will be sent after verification."
                    try: await bot.send_message(uid, msg, parse_mode="Markdown")
                    except: pass
                    # Admin
                    for aid in config.ADMIN_IDS:
                        try: await bot.send_message(aid, f"📚 *Kursa pirkums (auto):*\n👤 @{username} (`{uid}`)\n📧 `{email}`\n📚 {cname}\n💰 {amount} USDT\n🔖 `{tx[:20]}`", parse_mode="Markdown")
                        except: pass
                else:
                    # Čata abonements
                    plan = config.PLANS[pk]
                    new_exp, pname, product_meta = await _do_activate(uid, pk, plan, lang, username, tx, amount)
                    inv = await invite_text_for_product(uid, lang, product_meta, new_exp)
                    await bot.send_message(uid, t(lang, "auto_found", name=pname, expires=new_exp.strftime('%d.%m.%Y'), tx=tx[:20]) + inv, parse_mode="Markdown")

                logger.info(f"[AUTO-CHECK] user={uid} TX={tx[:20]} plan={pk}")
        except Exception as e:
            logger.error(f"[AUTO-CHECK] {uid}: {e}")
            await notify_admins_error(f"auto_check user={uid}", e)

# ─── SCHEDULER JOBS ───
async def check_expiring_subscriptions():
    now = datetime.utcnow()
    for db_ in [3, 1, 0]:
        for user in await db.get_expiring_users(now + timedelta(days=db_)):
            if await db.reminder_already_sent(user['user_id'], db_): continue
            try:
                lang = user.get("lang", "ru")
                exp_str = datetime.fromisoformat(user['expires_at']).strftime('%d.%m.%Y')
                key = f"reminder_{db_}d_{lang}"
                text = await db.get_setting(key)
                if text:
                    text = text.format(expires=exp_str)
                elif db_ == 3:
                    text = t(lang, "remind_3", expires=exp_str)
                elif db_ == 1:
                    text = t(lang, "remind_1", expires=exp_str)
                else:
                    text = f"⏰ *Subscription expires TODAY!*\n\n📅 {exp_str}\n\nRenew now:" if lang == "en" else f"⏰ *Подписка истекает СЕГОДНЯ!*\n\n📅 Дата: {exp_str}\n\nПродли сейчас:"
                await bot.send_message(user['user_id'], text, reply_markup=plans_keyboard(lang), parse_mode="Markdown")
                await db.mark_reminder_sent(user['user_id'], db_)
                await db.log_bot_event("reminder_sent", user['user_id'], meta=f"days_before={db_}")
                if db_ == 0:
                    username = f"@{user['username']}" if user.get("username") else f"ID {user['user_id']}"
                    admin_text = (
                        "⏰ *Abonements beidzas šodien*\n\n"
                        f"👤 {username} (`{user['user_id']}`)\n"
                        f"📦 {user.get('plan_name', '—')}\n"
                        f"📅 {exp_str}"
                    )
                    for admin_id in config.ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, admin_text, parse_mode="Markdown")
                        except Exception:
                            pass
                    await db.log_bot_event("expiry_today_notice", user['user_id'], meta=f"expires={exp_str}")
            except Exception as e: logger.error(f"Reminder {user['user_id']}: {e}")

async def send_upsell_offers():
    for user in await db.get_users_expiring_soon(days=5):
        if user.get("plan_key") != "monthly": continue
        if await db.reminder_already_sent(user['user_id'], 99): continue
        try:
            lang = user.get("lang", "ru")
            m, y = config.PLANS.get("monthly"), config.PLANS.get("yearly")
            if not m or not y: continue
            mx12 = round(m['price_usdt'] * 12, 2)
            save = round((1 - y['price_usdt'] / mx12) * 100)
            if save <= 0: continue
            pn = m['name'][lang] if isinstance(m['name'], dict) else m['name']
            b = InlineKeyboardBuilder()
            yn = y['name'][lang] if isinstance(y['name'], dict) else y['name']
            b.button(text=f"🔥 {yn}", callback_data="plan_yearly"); b.adjust(1)
            await bot.send_message(
                user['user_id'],
                t(
                    lang,
                    "upsell",
                    plan=pn,
                    save=save,
                    yearly_price=y['price_usdt'],
                    monthly_x12=mx12,
                ),
                reply_markup=b.as_markup(),
                parse_mode="Markdown",
            )
            await db.mark_reminder_sent(user['user_id'], 99)
        except Exception as e: logger.error(f"Upsell {user['user_id']}: {e}")

async def kick_expired_users():
    for user in await db.get_expired_chat_subscriptions():
        if user.get("is_friend"): continue
        # ADMIN AIZSARDZĪBA — nekad nebanoj adminus
        if user['user_id'] in config.ADMIN_IDS:
            logger.info(f"Skip admin {user['user_id']} — cannot kick admin")
            continue
        try:
            chat_id = int(user.get("chat_id") or 0)
            if chat_id:
                try:
                    await bot.ban_chat_member(chat_id, user['user_id'])
                    await bot.unban_chat_member(chat_id, user['user_id'])
                except Exception as e:
                    logger.warning(f"Kick failed chat={chat_id} user={user['user_id']}: {e}")
            await db.mark_subscription_inactive(user['id'])
            try: await bot.send_message(user['user_id'], t(user.get("lang","ru"), "kicked"), reply_markup=plans_keyboard(user.get("lang","ru")), parse_mode="Markdown")
            except: pass
            username = f"@{user['username']}" if user.get("username") else f"ID {user['user_id']}"
            expires_at = user.get("expires_at", "")
            admin_text = (
                "🚫 *Lietotājs izmests no čata*\n\n"
                f"👤 {username} (`{user['user_id']}`)\n"
                f"📦 {user.get('product_name', user.get('plan_name', '—'))}\n"
                f"📅 Abonements beidzās: `{expires_at}`\n\n"
                "ℹ️ Marketing ziņas šim lietotājam joprojām var tikt sūtītas no DB segmentiem."
            )
            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, admin_text, parse_mode="Markdown")
                except Exception:
                    pass
            await db.log_bot_event("expired_kick", user['user_id'], meta=f"expires={expires_at}")
        except Exception as e: logger.error(f"Kick {user['user_id']}: {e}")

async def run_monthly_giveaway():
    """Automātiska izloze — 1. datumā, iepriekšējā mēneša dalībnieki"""
    import random
    now = datetime.utcnow()
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    participants = await db.get_giveaway_participants(prev_month)
    if not participants:
        logger.info(f"[GIVEAWAY] Nav dalībnieku par {prev_month}")
        return

    winners_count, prize_days = await _giveaway_settings()
    winners_count = min(winners_count, len(participants))

    winners = random.sample(participants, winners_count)

    month_names_ru = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
    month_idx = int(prev_month.split("-")[1]) - 1

    winner_names = []
    for w in winners:
        wid = w['user_id']
        wuser = await db.get_user(wid)
        wname = f"@{wuser['username']}" if wuser and wuser.get('username') else f"ID {wid}"
        wlang = wuser.get("lang", "ru") if wuser else "ru"
        winner_names.append(wname)

        # Piešķirt dienas — pat ja abonements beidzies
        if wuser and wuser.get('expires_at'):
            exp = datetime.fromisoformat(wuser['expires_at'])
        else:
            exp = now
        new_exp = (exp if exp > now else now) + timedelta(days=prize_days)

        await db.activate_subscription(
            user_id=wid, username=wuser.get("username") if wuser else None,
            plan_key="giveaway", plan_name=f"Giveaway +{prize_days}d",
            expires_at=new_exp, tx_hash=f"giveaway_{prev_month}_{wid}"
        )

        # Invite link ja abonements bija beidzies
        invite_text = ""
        if not (wuser and wuser.get('expires_at') and datetime.fromisoformat(wuser['expires_at']) > now):
            try:
                link = await bot.create_chat_invite_link(chat_id_for_lang(wlang), member_limit=1, expire_date=int((new_exp + timedelta(days=7)).timestamp()))
                invite_text = f"\n\n🔗 [{ui_text(wlang, 'Pievienoties čatam', 'Вступить в чат', 'Join chat')}]({link.invite_link})"
            except Exception:
                invite_text = f"\n\n📢 {chat_link_for_lang(wlang)}"

        # Privātā ziņa uzvarētājam — custom vai default
        custom_winner_text = await db.get_setting(f"giveaway_winner_text_{wlang}")
        if custom_winner_text:
            private_text = custom_winner_text.replace("{days}", str(prize_days)).replace("{expires}", new_exp.strftime('%d.%m.%Y'))
        elif wlang == "ru":
            private_text = (
                "🎉🎉🎉 *ПОЗДРАВЛЯЕМ!*\n\n"
                "🏆 Ты выиграл в ежемесячном розыгрыше!\n"
                f"🎁 Приз: *+{prize_days} дней* бесплатного доступа к чату!\n\n"
                f"📅 Подписка активна до: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "🎟 Участвуй в розыгрыше следующего месяца!"
            )
        elif wlang == "lv":
            private_text = (
                "🎉🎉🎉 *APSVEICAM!*\n\n"
                "🏆 Tu uzvarēji ikmēneša izlozē!\n"
                f"🎁 Balva: *+{prize_days} dienas* bezmaksas piekļuvei čatam!\n\n"
                f"📅 Abonements aktīvs līdz: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "🎟 Piedalies arī nākamā mēneša izlozē!"
            )
        else:
            private_text = (
                "🎉🎉🎉 *CONGRATULATIONS!*\n\n"
                "🏆 You won the monthly giveaway!\n"
                f"🎁 Prize: *+{prize_days} days* of free chat access!\n\n"
                f"📅 Subscription active until: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "🎟 Join next month's giveaway!"
            )
        try:
            await bot.send_message(wid, private_text + invite_text, parse_mode="Markdown")
        except Exception:
            pass

    await db.set_setting(f"giveaway_winner_{prev_month}", ",".join(str(w['user_id']) for w in winners))

    # Kanāla paziņojums — valoda no settings
    winners_str = ", ".join(winner_names)
    chat_lang = await db.get_setting("giveaway_chat_lang") or "ru"

    month_names_en = ["January","February","March","April","May","June","July","August","September","October","November","December"]

    if chat_lang == "en":
        channel_text = (
            f"🎟 *{month_names_en[month_idx]} Giveaway Results!*\n\n"
            f"👥 Participants: *{len(participants)}*\n"
            f"🏆 {'Winners' if winners_count > 1 else 'Winner'}: *{winners_str}*\n"
            f"🎁 Prize: *+{prize_days} days* of free access!\n\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🎟 *Want to join next month's giveaway?*\n"
            "Press «Monthly Giveaway» button in the bot!\n\n"
            "🍀 Good luck everyone!"
        )
    else:
        channel_text = (
            f"🎟 *Результаты розыгрыша {month_names_ru[month_idx]}!*\n\n"
            f"👥 Участников: *{len(participants)}*\n"
            f"🏆 {'Победители' if winners_count > 1 else 'Победитель'}: *{winners_str}*\n"
            f"🎁 Приз: *+{prize_days} дней* бесплатного доступа!\n\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🎟 *Хочешь участвовать в следующем розыгрыше?*\n"
            "Нажми кнопку «Розыгрыш месяца» в боте!\n\n"
            "🍀 Удачи всем!"
        )
    try:
        await bot.send_message(config.CHAT_ID, channel_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[GIVEAWAY] Channel msg: {e}")

    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"🎟 *Giveaway {prev_month}:*\n\n"
                f"👥 Dalībnieki: *{len(participants)}*\n"
                f"🏆 Uzvarētāji: *{winners_str}*\n"
                f"🎁 +{prize_days} dienas",
                parse_mode="Markdown")
        except Exception:
            pass

    logger.info(f"[GIVEAWAY] {prev_month}: {len(winners)} winners from {len(participants)}")


# Legacy naudas referral sadaļas aizvietotas ar bonusu dienu maku
@dp.callback_query(F.data == "ref_earnings_page")
async def show_earnings_page(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    text = await build_referral_overview_text(callback.from_user.id, lang)
    text += ui_text(
        lang,
        "\n\nℹ️ Šobrīd referral programma izmanto tikai bonusu dienas. Naudas izmaksas vairs nav pieejamas.",
        "\n\nℹ️ Сейчас referral программа использует только бонусные дни. Денежные выплаты больше недоступны.",
        "\n\nℹ️ The referral program now uses bonus days only. Cash payouts are no longer available.",
    )
    await callback.message.edit_text(text, reply_markup=referral_keyboard_with_earnings(lang), parse_mode="Markdown")
    await callback.answer()


# Legacy callbacks no longer expose cash earnings
@dp.callback_query(F.data == "ref_earnings_list")
async def show_earnings_list(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.answer(
        ui_text(
            lang,
            "Referral programma tagad izmanto tikai bonusu dienas.",
            "Referral программа теперь использует только бонусные дни.",
            "The referral program now uses bonus days only.",
        ),
        show_alert=True,
    )
    await callback.message.edit_text(
        await build_referral_overview_text(callback.from_user.id, lang),
        reply_markup=referral_keyboard_with_earnings(lang),
        parse_mode="Markdown",
    )


# Legacy withdrawal flow disabled
@dp.callback_query(F.data == "ref_withdraw")
async def start_withdrawal(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.clear()
    await callback.answer(
        ui_text(
            lang,
            "Naudas izmaksas vairs nav pieejamas. Referral programma tagad dod tikai bonusu dienas čatiem.",
            "Денежные выплаты больше недоступны. Referral программа теперь дает только бонусные дни для чатов.",
            "Cash payouts are no longer available. The referral program now gives only bonus days for chats.",
        ),
        show_alert=True,
    )


# Withdrawal email handler
@dp.message(WithdrawalState.waiting_email)
async def withdrawal_receive_email(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.clear()
    await message.answer(
        ui_text(
            lang,
            "Referral izmaksas ir izslēgtas. Tagad pieejamas tikai bonusu dienas čatiem.",
            "Referral выплаты отключены. Теперь доступны только бонусные дни для чатов.",
            "Referral payouts are disabled. Only bonus days for chats are available now.",
        )
    )


# Withdrawal address handler
@dp.message(WithdrawalState.waiting_address)
async def withdrawal_receive_address(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.clear()
    await message.answer(
        ui_text(
            lang,
            "Referral izmaksas ir izslēgtas. Tagad pieejamas tikai bonusu dienas čatiem.",
            "Referral выплаты отключены. Теперь доступны только бонусные дни для чатов.",
            "Referral payouts are disabled. Only bonus days for chats are available now.",
        )
    )


# Withdrawal confirm
@dp.callback_query(F.data == "withdraw_confirm")
async def withdrawal_confirm(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.clear()
    await callback.message.edit_text(
        ui_text(
            lang,
            "ℹ️ Referral izmaksas vairs nav pieejamas. Tagad tiek izmantotas tikai bonusu dienas čatiem.",
            "ℹ️ Referral выплаты больше недоступны. Теперь используются только бонусные дни для чатов.",
            "ℹ️ Referral payouts are no longer available. Only bonus days for chats are used now.",
        )
    )
    await callback.answer()


# Withdrawal cancel
@dp.callback_query(F.data == "withdraw_cancel")
async def withdrawal_cancel(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await state.clear()
    await callback.message.edit_text(
        ui_text(
            lang,
            "Atcelts. Referral sadaļā tagad tiek izmantotas tikai bonusu dienas.",
            "Отменено. В referral разделе теперь используются только бонусные дни.",
            "Cancelled. The referral section now uses bonus days only.",
        )
    )
    await callback.answer()


# Withdrawal history
@dp.callback_query(F.data == "ref_withdraw_history")
async def show_withdrawal_history(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.edit_text(
        await build_referral_overview_text(callback.from_user.id, lang),
        reply_markup=referral_keyboard_with_earnings(lang),
        parse_mode="Markdown",
    )
    await callback.answer(
        ui_text(
            lang,
            "Izmaksu vēsture vairs netiek izmantota, jo referral programma tagad strādā ar bonusu dienām.",
            "История выплат больше не используется, потому что referral программа теперь работает с бонусными днями.",
            "Withdrawal history is no longer used because the referral program now works with bonus days.",
        ),
        show_alert=True,
    )




# ═══════════════════════════════════════════════════════════════
# LOYALTY HANDLERS (embedded from bot_loyalty_addon.py)
# ═══════════════════════════════════════════════════════════════

@dp.message(Command("loyalty"))
async def show_loyalty_status(message: Message):
    """Show user's loyalty progress"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await message.answer("❌ User not found")
        return
    
    lang = user.get('lang', 'ru')
    
    # Get loyalty data
    loyalty_data = await db.get_user_loyalty(user_id)
    
    if not loyalty_data:
        # Initialize
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
    
    current_tier = loyalty_data.get('current_tier', 'rookie')
    consecutive_months = loyalty_data.get('consecutive_months', 0)
    
    tier_data = config.LOYALTY_TIERS[current_tier]
    emoji = tier_data.get('emoji', '')
    tag = tier_data.get('tag', current_tier)
    discount = tier_data.get('chat_discount', 0)
    
    # Find next tier
    next_tier = None
    for tier_name in ['active', 'pro', 'elite', 'master', 'legend']:
        tier_info = config.LOYALTY_TIERS[tier_name]
        if consecutive_months < tier_info['min_months']:
            next_tier = tier_name
            break
    
    # Build progress bar
    if next_tier:
        next_tier_data = config.LOYALTY_TIERS[next_tier]
        target_months = next_tier_data['min_months']
        progress = consecutive_months / target_months
        bar_length = 20
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        months_left = target_months - consecutive_months
    else:
        # Already Legend
        bar = "█" * 20
        months_left = 0
    
    if lang == 'ru':
        text = f"""📊 Твой Прогресс Лояльности

{emoji} *{tag.upper()}* ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} месяцев
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Следующий: {next_emoji} *{next_tag.upper()}*
📅 До цели: {months_left} {'месяц' if months_left == 1 else 'месяца' if months_left < 5 else 'месяцев'}! 🔥

🎁 Получишь:
   • +{next_bonus} дней бесплатно
   • {next_discount}% скидка (против {discount}%)
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up курс (100$ стоимость)"
        
        else:
            text += f"""
🔱 *ТЫ ДОСТИГ МАКСИМУМА!*
👑 Legend статус - высшее достижение!

Спасибо за {consecutive_months} месяцев лояльности! 🏆"""
        
        text += "\n\n💡 *Продолжай продлять - сохраняй статус!*"
    
    else:  # EN
        text = f"""📊 Your Loyalty Progress

{emoji} *{tag.upper()}* ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} months
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Next: {next_emoji} *{next_tag.upper()}*
📅 Time left: {months_left} {'month' if months_left == 1 else 'months'}! 🔥

🎁 You'll get:
   • +{next_bonus} days free
   • {next_discount}% discount (vs {discount}%)
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up course (100$ value)"
        
        else:
            text += f"""
🔱 *YOU REACHED THE TOP!*
👑 Legend status - ultimate achievement!

Thank you for {consecutive_months} months of loyalty! 🏆"""
        
        text += "\n\n💡 *Keep renewing - maintain your status!*"
    
    if lang == 'ru':
        text = (
            f"📊 *Твой прогресс лояльности*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} месяцев\n\n"
            "🎁 Чем дольше активна подписка, тем больше бесплатных дней ты получаешь."
        )
    elif lang == 'lv':
        text = (
            f"📊 *Tavs lojalitātes progress*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} mēneši\n\n"
            "🎁 Jo ilgāk abonements ir aktīvs, jo vairāk bezmaksas bonusa dienu tu atbloķē."
        )
    else:
        text = (
            f"📊 *Your Loyalty Progress*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} months\n\n"
            "🎁 The longer your subscription stays active, the more free bonus days you unlock."
        )

    b = InlineKeyboardBuilder()
    b.button(text="💎 " + ui_text(lang, "Pagarināt", "Продлить", "Renew"),
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "loyalty_status")
async def loyalty_status_callback(callback: CallbackQuery):
    """Handle loyalty status button from main menu"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await callback.answer("❌ User not found")
        return
    
    lang = user.get('lang', 'ru')
    
    # Get loyalty data
    loyalty_data = await db.get_user_loyalty(user_id)
    
    if not loyalty_data:
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
    
    current_tier = loyalty_data.get('current_tier', 'rookie')
    consecutive_months = loyalty_data.get('consecutive_months', 0)
    
    tier_data = config.LOYALTY_TIERS[current_tier]
    emoji = tier_data.get('emoji', '🌱')
    tag = tier_data.get('tag', 'Rookie')
    discount = tier_data.get('chat_discount', 0)
    
    # Find next tier
    next_tier = None
    target_months = 0
    for tier_name in ['active', 'pro', 'elite', 'master', 'legend']:
        tier_info = config.LOYALTY_TIERS[tier_name]
        if consecutive_months < tier_info['min_months']:
            next_tier = tier_name
            target_months = tier_info['min_months']
            break
    
    # Build progress bar ar %
    if next_tier:
        progress = consecutive_months / target_months if target_months > 0 else 0
        progress_pct = int(progress * 100)
        bar_length = 15
        filled = int(progress * bar_length)
        bar = "▓" * filled + "░" * (bar_length - filled)
        months_left = target_months - consecutive_months
    else:
        bar = "▓" * 15
        months_left = 0
        progress_pct = 100
    
    if lang == 'ru':
        discount_text = f" — скидка *{discount}%*" if discount > 0 else ""
        text = (
            f"🏆 *Твой уровень лояльности*\n\n"
            f"{emoji} *{tag.upper()}*{discount_text}\n"
            f"{bar} *{progress_pct}%*\n"
        )
        
        if next_tier:
            next_data = config.LOYALTY_TIERS[next_tier]
            next_emoji = next_data['emoji']
            next_tag = next_data['tag']
            next_discount = next_data['chat_discount']
            next_bonus = next_data['bonus_days']
            
            text += (
                f"\n━━━━━━━━━━━━━━━━\n\n"
                f"🎯 *Следующий уровень:* {next_emoji} {next_tag}\n"
                f"📅 Осталось: *{months_left}* {_months_ru(months_left)}\n\n"
                f"🎁 *Что ты получишь:*\n"
                f"   • +{next_bonus} дней бесплатного доступа\n"
                f"   • Постоянная скидка {next_discount}%\n"
                f"   • Статус {next_emoji} {next_tag}"
            )
            if next_tier == 'elite':
                text += "\n   • 🎓 Бесплатный Power Up курс ($100)"
            
            text += (
                f"\n\n━━━━━━━━━━━━━━━━\n"
                f"💡 *Продолжай подписку — прогресс копится!*"
            )
            
            # Course upsell priekš Rookie un Active
            if current_tier in ('rookie', 'active'):
                text += (
                    f"\n\n🔥 *Хочешь быстрее расти?*\n"
                    f"Пройди курс и прокачай свой трейдинг!"
                )
        else:
            text += (
                f"\n━━━━━━━━━━━━━━━━\n\n"
                f"🔱 *ТЫ НА ВЕРШИНЕ!*\n"
                f"Максимальная скидка *{discount}%* на всё!\n\n"
                f"🙏 Спасибо за *{consecutive_months}* месяцев с нами! 🏆"
            )
    
    else:  # EN
        discount_text = f" — *{discount}%* discount" if discount > 0 else ""
        text = (
            f"🏆 *Your Loyalty Level*\n\n"
            f"{emoji} *{tag.upper()}*{discount_text}\n"
            f"{bar} *{progress_pct}%*\n"
        )
        
        if next_tier:
            next_data = config.LOYALTY_TIERS[next_tier]
            next_emoji = next_data['emoji']
            next_tag = next_data['tag']
            next_discount = next_data['chat_discount']
            next_bonus = next_data['bonus_days']
            
            text += (
                f"\n━━━━━━━━━━━━━━━━\n\n"
                f"🎯 *Next level:* {next_emoji} {next_tag}\n"
                f"📅 *{months_left}* month{'s' if months_left != 1 else ''} to go\n\n"
                f"🎁 *You'll unlock:*\n"
                f"   • +{next_bonus} days free access\n"
                f"   • Permanent {next_discount}% discount\n"
                f"   • {next_emoji} {next_tag} status"
            )
            if next_tier == 'elite':
                text += "\n   • 🎓 Free Power Up course ($100)"
            
            text += (
                f"\n\n━━━━━━━━━━━━━━━━\n"
                f"💡 *Keep your subscription active to progress!*"
            )
            
            if current_tier in ('rookie', 'active'):
                text += (
                    f"\n\n🔥 *Want to grow faster?*\n"
                    f"Take a course and level up your trading!"
                )
        else:
            text += (
                f"\n━━━━━━━━━━━━━━━━\n\n"
                f"🔱 *YOU'RE AT THE TOP!*\n"
                f"Maximum *{discount}%* discount on everything!\n\n"
                f"🙏 Thank you for *{consecutive_months}* months with us! 🏆"
            )
    
    if lang == 'ru':
        text = (
            f"🏆 *Твой уровень лояльности*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} *{progress_pct}%*\n\n"
            "🎁 Лояльность теперь даёт бонусные бесплатные дни за длительную активную подписку."
        )
    elif lang == 'lv':
        text = (
            f"🏆 *Tavs lojalitātes līmenis*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} *{progress_pct}%*\n\n"
            "🎁 Lojalitāte tagad dod bezmaksas bonusa dienas par ilgstoši aktīvu abonementu."
        )
    else:
        text = (
            f"🏆 *Your Loyalty Level*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} *{progress_pct}%*\n\n"
            "🎁 Loyalty now rewards long active subscriptions with free bonus days."
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📋  " + ui_text(lang, "Visi līmeņi un bonusi", "Все уровни и бонусы", "All levels & rewards"),
             callback_data="loyalty_tiers_info")
    # Course upsell poga priekš Rookie/Active
    if current_tier in ('rookie', 'active'):
        b.button(text="🔥  " + ui_text(lang, "Kursi — uzlabo tradingu!", "Курсы — прокачай трейдинг!", "Courses — level up!"),
                 callback_data="courses_menu")
    b.button(text=back_button_text(lang),
             callback_data="settings_back")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()



def _months_ru(n):
    """Mēnešu locījums krievu valodā"""
    if n % 10 == 1 and n % 100 != 11:
        return "месяц"
    elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "месяца"
    return "месяцев"


@dp.callback_query(F.data == "loyalty_tiers_info")
async def loyalty_tiers_info(callback: CallbackQuery):
    """Parādīt visu līmeņu aprakstu ar bonusiem"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get('lang', 'ru') if user else 'ru'
    
    loyalty_data = await db.get_user_loyalty(callback.from_user.id)
    current_tier = loyalty_data.get('current_tier', 'rookie') if loyalty_data else 'rookie'
    
    tier_order = ['rookie', 'active', 'pro', 'elite', 'master', 'legend']
    
    if lang == 'ru':
        text = "📋 *Все уровни лояльности*\n\nЧем дольше подписка — тем больше привилегий!\n"
    elif lang == 'lv':
        text = "📋 *Visi lojalitātes līmeņi*\n\nJo ilgāk abonē, jo vairāk bonusu!\n"
    else:
        text = "📋 *All Loyalty Levels*\n\nThe longer you subscribe — the more rewards!\n"
    
    for tier_name in tier_order:
        td = config.LOYALTY_TIERS[tier_name]
        em = td['emoji']
        tg = td['tag']
        disc = td['chat_discount']
        bonus = td['bonus_days']
        min_m = td['min_months']
        
        is_current = (tier_name == current_tier)
        marker = ui_text(lang, " ◀ TU ESI ŠEIT", " ◀ ТЫ ЗДЕСЬ", " ◀ YOU") if is_current else ""
        
        text += f"\n━━━━━━━━━━━━━━━━\n"
        text += f"{em} *{tg.upper()}*{marker}\n"
        
        if lang == 'ru':
            if min_m == 0:
                text += "📅 Старт\n"
            else:
                text += f"📅 После {min_m} {_months_ru(min_m)} подписки\n"
            if disc > 0:
                text += f"💰 Скидка: *{disc}%* на всё\n"
            if bonus > 0:
                text += f"🎁 Бонус: *+{bonus} дней* бесплатно\n"
            if td.get('free_course'):
                text += f"🎓 Бесплатный Power Up курс ($100)\n"
        elif lang == 'lv':
            if min_m == 0:
                text += "📅 Sākuma līmenis\n"
            else:
                text += f"📅 Pēc {min_m} mēnešu abonementa\n"
            if disc > 0:
                text += f"💰 Atlaide: *{disc}%* visam\n"
            if bonus > 0:
                text += f"🎁 Bonuss: *+{bonus} dienas* bezmaksas\n"
            if td.get('free_course'):
                text += f"🎓 Bezmaksas Power Up kurss ($100)\n"
        else:
            if min_m == 0:
                text += "📅 Starting level\n"
            else:
                text += f"📅 After {min_m} months\n"
            if disc > 0:
                text += f"💰 Discount: *{disc}%* on everything\n"
            if bonus > 0:
                text += f"🎁 Bonus: *+{bonus} days* free\n"
            if td.get('free_course'):
                text += f"🎓 Free Power Up course ($100)\n"
    
    text += "\n━━━━━━━━━━━━━━━━\n"
    if lang == 'ru':
        text += "\n💡 *Твой прогресс сохраняется пока подписка активна!*"
    elif lang == 'lv':
        text += "\n💡 *Tavs progress saglabājas, kamēr abonements ir aktīvs!*"
    else:
        text += "\n💡 *Your progress is saved while subscription is active!*"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text=back_button_text(lang), callback_data="loyalty_status")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "my_promo_codes")
async def show_promo_codes(callback: CallbackQuery):
    """Show user's active promo codes"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru')
    
    # Get active coupons
    coupons = await db.get_active_coupons(user_id)
    
    if not coupons:
        text = "❌ " + ui_text(lang, "Tev nav aktīvu promokodu", "У тебя нет активных промокодов", "You have no active promo codes")
        b = InlineKeyboardBuilder()
        b.button(text=back_button_text(lang), callback_data="loyalty_main")
        b.adjust(1)
        await callback.message.edit_text(text, reply_markup=b.as_markup())
        await callback.answer()
        return
    
    if lang == 'ru':
        text = "💳 *ТВОИ ПРОМОКОДЫ*\n\n"
    elif lang == 'lv':
        text = "💳 *TAVI PROMOKODI*\n\n"
    else:
        text = "💳 *YOUR PROMO CODES*\n\n"
    
    keyboard = InlineKeyboardBuilder()
    
    for coupon in coupons:
        code = coupon['code']
        discount = coupon['discount_percent']
        coupon_type = coupon['coupon_type']
        applies_to = coupon['applies_to']
        expires_at = coupon.get('expires_at')
        max_uses = coupon.get('max_uses')
        times_used = coupon.get('times_used', 0)
        
        text += "━━━━━━━━━━━━━━━━\n\n"
        
        # Type-specific header
        if coupon_type == 'loyalty_tier':
            text += f"🎯 *{ui_text(lang, 'Lojalitātes atlaide', 'Скидка лояльности', 'Loyalty Discount')}*\n\n"
        
        elif coupon_type == 'reminder_bonus':
            text += f"🎁 *{ui_text(lang, 'Atgādinājuma bonuss', 'Бонус-напоминание', 'Reminder Bonus')}*\n\n"
        
        elif coupon_type == 'winback':
            text += f"🔙 *{ui_text(lang, 'Laipni atpakaļ', 'С возвращением', 'Welcome Back')}*\n\n"
        
        elif coupon_type == 'survey':
            text += f"📊 *{ui_text(lang, 'Aptaujas balva', 'Награда за опрос', 'Survey Reward')}*\n\n"
        
        # Code
        if lang == 'ru':
            text += f"Код: `{code}`\n"
            text += f"Скидка: *{discount}%*\n"
        elif lang == 'lv':
            text += f"Kods: `{code}`\n"
            text += f"Atlaide: *{discount}%*\n"
        else:
            text += f"Code: `{code}`\n"
            text += f"Discount: *{discount}%*\n"
        
        # Applies to
        if applies_to == 'all':
            text += ui_text(lang, "Der: visiem plāniem + kursiem\n", "Применяется: Все планы + курсы\n", "Applies to: All plans + courses\n")
        elif applies_to == 'chat':
            text += ui_text(lang, "Der: tikai plāniem\n", "Применяется: Только планы\n", "Applies to: Plans only\n")
        elif applies_to == 'courses':
            text += ui_text(lang, "Der: tikai kursiem\n", "Применяется: Только курсы\n", "Applies to: Courses only\n")
        
        # Expiry
        if expires_at:
            expiry_dt = datetime.fromisoformat(expires_at)
            time_left = expiry_dt - datetime.utcnow()
            
            if time_left.total_seconds() > 0:
                hours_left = int(time_left.total_seconds() / 3600)
                if lang == 'ru':
                    text += f"Истекает: ⏰ через {hours_left} часов\n"
                elif lang == 'lv':
                    text += f"Beidzas: ⏰ pēc {hours_left} stundām\n"
                else:
                    text += f"Expires: ⏰ in {hours_left} hours\n"
        else:
            # Tier-based
            if lang == 'ru':
                text += f"Действует: Пока статус активен\n"
            elif lang == 'lv':
                text += f"Derīgs: kamēr statuss ir aktīvs\n"
            else:
                text += f"Valid: While status active\n"
        
        # Uses
        if max_uses:
            remaining = max_uses - times_used
            if lang == 'ru':
                text += f"Осталось: {remaining} использование\n"
            elif lang == 'lv':
                text += f"Atlicis: {remaining} lietojums\n"
            else:
                text += f"Remaining: {remaining} use(s)\n"
        else:
            if lang == 'ru':
                text += f"Использований: Безлимит ♾\n"
            elif lang == 'lv':
                text += f"Lietojumi: bez limita ♾\n"
            else:
                text += f"Uses: Unlimited ♾\n"
        
        text += "\n"
        
        # Copy button
        keyboard.button(
            text=f"📋 {code[:20]}{'...' if len(code) > 20 else ''}",
            callback_data=f"copy_{code}"
        )
    
    text += "━━━━━━━━━━━━━━━━\n\n"
    
    if lang == 'ru':
        text += "ℹ️ Используй промокод при оплате\n   для получения скидки"
    elif lang == 'lv':
        text += "ℹ️ Izmanto promokodu apmaksas laikā,\n   lai saņemtu atlaidi"
    else:
        text += "ℹ️ Use promo code at checkout\n   to get your discount"
    
    keyboard.button(text=back_button_text(lang), callback_data="loyalty_main")
    keyboard.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
    await callback.answer()



@dp.callback_query(F.data == "loyalty_main")
async def loyalty_main_back(callback: CallbackQuery):
    """Назад no promo kodiem uz loyalty status — reuse loyalty_status_callback"""
    await loyalty_status_callback(callback)


@dp.callback_query(F.data == "start_back")
async def start_back_callback(callback: CallbackQuery):
    """Назад uz galveno menu"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    has_active = bool(active_subs) or (user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow())
    if active_subs:
        welcome_text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=kb, parse_mode="Markdown")
    elif has_active:
        expires_dt = datetime.fromisoformat(user['expires_at'])
        days_left = max(0, (expires_dt - datetime.utcnow()).days)
        loyalty_data = await db.get_user_loyalty(callback.from_user.id)
        if not loyalty_data:
            await db.update_user_loyalty(callback.from_user.id, 'rookie', 0)
            loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
        current_tier = loyalty_data.get('current_tier', 'rookie')
        tier_data = config.LOYALTY_TIERS.get(current_tier, {})
        tier_emoji = tier_data.get('emoji', '🌱')
        tier_tag = tier_data.get('tag', 'Rookie')
        tier_discount = tier_data.get('chat_discount', 0)
        if lang == "ru":
            loyalty_line = f"\n\n{tier_emoji} Уровень: *{tier_tag}*" + (f" ({tier_discount}% скидка)" if tier_discount > 0 else "")
        elif lang == "lv":
            loyalty_line = f"\n\n{tier_emoji} Līmenis: *{tier_tag}*" + (f" ({tier_discount}% atlaide)" if tier_discount > 0 else "")
        else:
            loyalty_line = f"\n\n{tier_emoji} Level: *{tier_tag}*" + (f" ({tier_discount}% discount)" if tier_discount > 0 else "")
        welcome_text = t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=days_left) + loyalty_line
        await callback.message.edit_text(welcome_text, reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("copy_"))
async def copy_coupon_code(callback: CallbackQuery):
    """Handle coupon code copy"""
    code = callback.data[5:]  # Remove "copy_"
    
    # Just show in answer popup
    await callback.answer(f"✅ {code}", show_alert=True, cache_time=1)


@dp.callback_query(F.data == "winback_survey")
async def show_winback_survey(callback: CallbackQuery):
    """Show win-back survey"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru')
    
    if lang == 'ru':
        text = """📊 Почему ушёл? Помоги нам стать лучше!

Выбери причину (или напиши свою):"""
    elif lang == 'lv':
        text = """📊 Kāpēc aizgāji? Palīdzi mums kļūt labākiem!

Izvēlies iemeslu vai uzraksti savu:"""
    else:
        text = """📊 Why did you leave? Help us improve!

Choose a reason (or write your own):"""
    
    b = InlineKeyboardBuilder()
    
    if lang == 'ru':
        b.button(text="💸 Слишком дорого", callback_data="survey_expensive")
        b.button(text="📉 Мало контента", callback_data="survey_content")
        b.button(text="⏰ Нет времени", callback_data="survey_time")
        b.button(text="❓ Не понял как пользоваться", callback_data="survey_confused")
        b.button(text="📝 Другое (напиши)", callback_data="survey_custom")
    elif lang == 'lv':
        b.button(text="💸 Pārāk dārgi", callback_data="survey_expensive")
        b.button(text="📉 Par maz vērtības", callback_data="survey_content")
        b.button(text="⏰ Nav laika", callback_data="survey_time")
        b.button(text="❓ Nesapratu, kā lietot", callback_data="survey_confused")
        b.button(text="📝 Cits iemesls", callback_data="survey_custom")
    else:
        b.button(text="💸 Too expensive", callback_data="survey_expensive")
        b.button(text="📉 Not enough value", callback_data="survey_content")
        b.button(text="⏰ No time", callback_data="survey_time")
        b.button(text="❓ Didn't understand", callback_data="survey_confused")
        b.button(text="📝 Other (write)", callback_data="survey_custom")
    
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup())
    await callback.answer()



class SurveyCustomState(StatesGroup):
    waiting_text = State()


@dp.callback_query(F.data.startswith("survey_"))
async def handle_survey_response(callback: CallbackQuery, state: FSMContext):
    """Handle survey response"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru')
    
    response_type = callback.data[7:]  # Remove "survey_"
    
    if response_type == 'custom':
        if lang == 'ru':
            text = "📝 *Напиши свою причину:*\n\n/cancel для отмены"
        elif lang == 'lv':
            text = "📝 *Uzraksti savu iemeslu:*\n\n/cancel lai atceltu"
        else:
            text = "📝 *Write your reason:*\n\n/cancel to cancel"
        await state.set_state(SurveyCustomState.waiting_text)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return
    
    # Generate reward coupon
    coupon_code = await loyalty_system.generate_winback_coupon(user_id, survey_response=True)
    
    # Save response
    await db.save_survey_response(user_id, response_type, coupon_code)
    
    if lang == 'ru':
        text = f"""🎁 *Спасибо за ответ!*

Твоя награда:
💳 Код: `{coupon_code}`
💰 Скидка: *20%* на всё
⏰ Действует: 24 часа

Используй при оплате!

[💎 Перейти к тарифам]"""
    elif lang == 'lv':
        text = f"""🎁 *Paldies par atbildi!*

Tava balva:
💳 Kods: `{coupon_code}`
💰 Atlaide: *20%* visam
⏰ Derīgs: 24 stundas

Izmanto apmaksas laikā!

[💎 Pāriet uz tarifiem]"""
    else:
        text = f"""🎁 *Thanks for your feedback!*

Your reward:
💳 Code: `{coupon_code}`
💰 Discount: *20%* on everything
⏰ Valid: 24 hours

Use at checkout!

[💎 Go to plans]"""
    
    b = InlineKeyboardBuilder()
    b.button(text=ui_text(lang, "💎 Tarifi", "💎 Тарифы", "💎 Plans"),
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer("✅")


@dp.message(SurveyCustomState.waiting_text)
async def survey_custom_text(message: Message, state: FSMContext):
    """Saņem custom survey atbildi"""
    user = await db.get_user(message.from_user.id)
    lang = user.get('lang', 'ru') if user else 'ru'
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ " + ui_text(lang, "Atcelts", "Отменено", "Cancelled"))
        return
    
    user_id = message.from_user.id
    custom_text = message.text[:500]  # Limitēt garumu
    await state.clear()
    
    coupon_code = await loyalty_system.generate_winback_coupon(user_id, survey_response=True)
    await db.save_survey_response(user_id, custom_text, coupon_code)
    
    if lang == 'ru':
        text = (
            f"🎁 *Спасибо за ответ!*\n\n"
            f"Твоя награда:\n"
            f"💳 Код: `{coupon_code}`\n"
            f"💰 Скидка: *20%* на всё\n"
            f"⏰ Действует: 24 часа"
        )
    elif lang == 'lv':
        text = (
            f"🎁 *Paldies par atbildi!*\n\n"
            f"Tava balva:\n"
            f"💳 Kods: `{coupon_code}`\n"
            f"💰 Atlaide: *20%* visam\n"
            f"⏰ Derīgs: 24 stundas"
        )
    else:
        text = (
            f"🎁 *Thank you for your feedback!*\n\n"
            f"Your reward:\n"
            f"💳 Code: `{coupon_code}`\n"
            f"💰 Discount: *20%* on everything\n"
            f"⏰ Valid: 24 hours"
        )
    
    b = InlineKeyboardBuilder()
    b.button(text=ui_text(lang, "💎 Tarifi", "💎 Тарифы", "💎 Plans"), callback_data="vip_chat_plans")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")




def _verify_webhook_request(raw_body: bytes, request: web.Request) -> bool:
    if not config.WEBHOOK_SECRET:
        logger.error("WEBHOOK_SECRET is not configured; rejecting purchase webhook")
        return False
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if hmac.compare_digest(provided_secret, config.WEBHOOK_SECRET):
        return True
    provided_sig = request.headers.get("X-Webhook-Signature", "")
    expected_sig = hmac.new(config.WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided_sig, expected_sig)


def _webhook_plan_from_payload(payload: dict):
    product_key = str(payload.get("product_key") or payload.get("product") or "").strip()
    days_raw = payload.get("subscription_days") or payload.get("days") or payload.get("duration_days")
    if product_key in config.PLANS:
        plan = dict(config.PLANS[product_key])
    else:
        if not days_raw:
            return None, None, "unknown_product"
        plan = {
            "name": {"ru": product_key or "Website subscription", "en": product_key or "Website subscription"},
            "days": int(days_raw),
            "price_usdt": float(payload.get("amount") or 0),
            "emoji": "🌐",
        }
    if days_raw:
        plan["days"] = int(days_raw)
    return product_key or "website_subscription", plan, None


async def website_purchase_webhook(request: web.Request):
    raw_body = await request.read()
    if not _verify_webhook_request(raw_body, request):
        return web.json_response({
            "ok": False,
            "status": "unauthorized",
            "error": "unauthorized",
            "message": "Webhook signature check failed.",
        }, status=401)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return web.json_response({
            "ok": False,
            "status": "invalid_json",
            "error": "invalid_json",
            "message": "Request body is not valid JSON.",
        }, status=400)

    email = str(payload.get("email") or payload.get("user_email") or "").strip().lower()
    payment_system = str(payload.get("payment_system") or payload.get("payment_method") or "").strip()
    event_id = str(payload.get("event_id") or payload.get("order_id") or payload.get("payment_id") or "").strip()
    amount = float(payload.get("amount") or payload.get("amount_usd") or payload.get("amount_usdt") or 0)
    product_key, plan, plan_error = _webhook_plan_from_payload(payload)

    if not email or "@" not in email:
        return web.json_response({
            "ok": False,
            "status": "email_required",
            "error": "email_required",
            "message": "A valid e-mail is required in webhook payload.",
        }, status=400)
    if plan_error:
        return web.json_response({
            "ok": False,
            "status": "invalid_product",
            "error": plan_error,
            "message": f"Webhook payload could not be mapped to a valid product: {plan_error}.",
        }, status=400)
    if not event_id:
        event_id = hashlib.sha256(raw_body).hexdigest()
    event_key = f"{payment_system or 'website'}:{event_id}"
    tx_hash = f"webhook:{event_key}"
    payload_json = json.dumps(payload, ensure_ascii=False)
    claimed = await db.claim_webhook_event(event_key, email, product_key, payment_system, payload_json)
    if not claimed:
        user = await db.get_user_by_email(email)
        response = {
            "ok": True,
            "status": "duplicate",
            "duplicate": True,
            "message": "Webhook was already received and processed earlier.",
            "telegram_linked": bool(user),
            "email": email,
            "product_key": product_key,
            "event_id": event_id,
        }
        if user:
            response["telegram_user_id"] = user["user_id"]
            if user.get("username"):
                response["telegram_username"] = user["username"]
        return web.json_response(response)

    user = await db.get_user_by_email(email)
    if not user:
        product_meta = resolve_subscription_product(product_key, "lv")
        pending_existing = await db.get_pending_email_subscription(email, product_key)
        now = datetime.utcnow()
        if pending_existing and pending_existing.get("expires_at"):
            try:
                current_exp = datetime.fromisoformat(pending_existing["expires_at"])
            except Exception:
                current_exp = now
            pending_expires = (current_exp if current_exp > now else now) + timedelta(days=plan.get("days", 0))
        else:
            pending_expires = now + timedelta(days=plan.get("days", 0))
        try:
            await db.activate_pending_email_subscription(
                email=email,
                product_key=product_key,
                product_name=plan["name"]["ru"] if isinstance(plan.get("name"), dict) else plan.get("name", product_key),
                expires_at=pending_expires,
                tx_hash=tx_hash,
                chat_id=product_meta.get("chat_id", 0) if product_meta else 0,
                chat_link=product_meta.get("chat_link", "") if product_meta else "",
                payment_system=payment_system or "webhook",
            )
        except Exception:
            await notify_admins_error(f"webhook_pending_save {email} {product_key}", "Failed to save pending e-mail purchase")
            await db.delete_webhook_event(event_key)
            raise
        for aid in config.ADMIN_IDS:
            try:
                await bot.send_message(aid, f"⚠️ *Webhook purchase without bot user*\n\n📧 `{email}`\n📦 `{product_key}`\n💳 `{payment_system}`", parse_mode="Markdown")
            except Exception:
                pass
        return web.json_response({
            "ok": True,
            "status": "pending_email_claim",
            "message": "Purchase was received and saved by e-mail. It will be attached when the user registers in the bot with this e-mail.",
            "telegram_linked": False,
            "email": email,
            "product_key": product_key,
            "event_id": event_id,
            "expires_at": pending_expires.isoformat(),
        })

    lang = user.get("lang", "ru")
    username = user.get("username") or ""
    try:
        new_exp, plan_name, product_meta = await _do_activate(user["user_id"], product_key, plan, lang, username, tx_hash, amount)
    except Exception:
        await notify_admins_error(f"webhook_activate user={user['user_id']} product={product_key}", "Failed to activate purchase from webhook")
        await db.delete_webhook_event(event_key)
        raise

    try:
        invite = await invite_text_for_product(user["user_id"], lang, product_meta, new_exp)
        await bot.send_message(user["user_id"], t(lang, "paid_ok", name=plan_name, expires=new_exp.strftime("%d.%m.%Y"), tx=event_id[:20]) + invite, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Failed to notify webhook buyer {user['user_id']}: {e}")
        await notify_admins_error(f"webhook_notify_user user={user['user_id']} product={product_key}", e)

    return web.json_response({
        "ok": True,
        "status": "processed",
        "message": "Webhook received and purchase processed successfully.",
        "telegram_linked": True,
        "telegram_user_id": user["user_id"],
        "telegram_username": user.get("username") or "",
        "email": email,
        "product_key": product_key,
        "event_id": event_id,
        "expires_at": new_exp.isoformat(),
    })


async def webhook_health(request: web.Request):
    return web.json_response({"ok": True})


async def start_webhook_server():
    app = web.Application()
    app.router.add_get("/health", webhook_health)
    app.router.add_post(config.WEBHOOK_PATH, website_purchase_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBHOOK_HOST, config.WEBHOOK_PORT)
    await site.start()
    logger.info(f"Webhook server started on {config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}{config.WEBHOOK_PATH}")
    return runner


async def main():
    await db.init()
    webhook_runner = await start_webhook_server()
    
    # ═══════════════════════════════════════════════════════════════
    # LOYALTY SYSTEM INITIALIZATION
    # ═══════════════════════════════════════════════════════════════
    loyalty_system = LoyaltySystem(config, db)
    
    # Include loyalty routers
    
    
    # Configure loyalty router dependencies

    
    # Configure admin loyalty router dependencies
        
    # Middleware to pass dependencies
    @dp.update.outer_middleware()
    async def inject_loyalty_deps(handler, event, data):
        data['db'] = db
        data['config'] = config
        data['loyalty_system'] = loyalty_system
        return await handler(event, data)
    
    # Setup loyalty cron jobs uz globālo scheduler
    try:
        setup_loyalty_cron(scheduler, bot, db, config, loyalty_system)
        logger.info("✅ Loyalty cron jobs pievienoti")
    except Exception as e:
        logger.error(f"❌ Loyalty cron kļūda: {e}")

    # Admini automātiski ir friend listā
    for admin_id in config.ADMIN_IDS:
        await db.register_user_as_friend(admin_id)
    for pk, plan in config.PLANS.items():
        sp = await db.get_setting(f"price_{pk}")
        if sp:
            try:
                p = float(sp); plan['price_usdt'] = p
                plan['price_usd'] = f"{p:.0f}€" if p == int(p) else f"{p}€"
            except: pass
    old_course_defaults = {
        "mini": 25.0,
        "basic": 75.0,
        "full": 150.0,
        "autotrading": 200.0,
        "vip": 5000.0,
    }
    for ck, course in config.COURSES.items():
        sp = await db.get_setting(f"course_price_{ck}")
        if sp:
            try:
                saved_price = float(sp)
                if saved_price == old_course_defaults.get(ck):
                    await db.set_setting(f"course_price_{ck}", str(course["price_usdt"]))
            except Exception:
                pass
    from admin import router as admin_router
    dp.include_router(admin_router)
    scheduler.add_job(check_expiring_subscriptions, 'cron', hour=10, minute=0)
    scheduler.add_job(send_upsell_offers, 'cron', hour=11, minute=0)
    scheduler.add_job(kick_expired_users, 'interval', hours=1)
    # Giveaway — katra mēneša 1. datumā plkst 12:00 UTC
    scheduler.add_job(run_monthly_giveaway, 'cron', day=1, hour=12, minute=0)
    scheduler.start()
    logger.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        await webhook_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
