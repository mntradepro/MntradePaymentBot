import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database import db
from crypto_checker import check_payment

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
        "inactive_welcome": "👋 Привет, {name}!\n\n❌ Сейчас у тебя нет активной подписки.\n\n👥 Приглашай друзей и получай бесплатный доступ к чату и курсам!\n\n📋 *Выбери продукт:*",
        "inactive_welcome_note": "❌ Сейчас у тебя нет активной подписки.\n\n👥 Приглашай друзей и получай бесплатный доступ к чату и курсам!",
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
        
        # JAUNAS REFERRAL EARNINGS TEKSTI
        "referral_info": "👥 *Реферальная программа*\n\n🎁 За подписку на чат: *+10 дней* + *20% комиссия*\n💰 За покупку курса: *+15% комиссия*\n\n📌 Твоя ссылка:\n`{ref_link}`\n\n📊 Приглашено: *{count}*\n🎁 Бонусов подписки: *{bonuses}* × 10 дней\n💵 Доступно для вывода: *{balance}$*",
        
        "my_referrals": "👥 *Мои рефералы*\n\n📊 Всего: *{count}*\n🎁 Бонусов: *{bonuses}* × 10 дней\n📅 Итого: *{total_days}* дней\n\n{referral_list}",
        "my_referrals_empty": "👥 *Мои рефералы*\n\nТы ещё никого не пригласил.",
        "referral_row_bonus": "✅ {name} — бонус получен",
        "referral_row_pending": "⏳ {name} — ожидает оплаты",
        "referral_bonus_received": "🎉 *Бонус получен!*\n\nТвой друг оформил подписку — тебе *+10 дней*!\n📅 Активна до: *{expires}*",
        
        # WITHDRAWAL TEKSTI
        "referral_earnings": "💰 *Реферальные доходы*\n\n💵 Доступно для вывода: *{balance}$*\n📊 Всего заработано: *{total}$*\n💸 Выведено: *{withdrawn}$*\n\n━━━━━━━━━━━━━━━━\n\n🎯 *Как это работает:*\n• За каждый купленный курс твоим рефералом ты получаешь *15% комиссии*\n• Минимальная сумма для вывода: *{min}$*\n• Все выплаты обрабатываются вручную администрацией",
        
        "withdrawal_button": "💸 Вывести средства",
        "earnings_button": "📊 История доходов",
        "withdrawal_history_button": "📜 История выплат",
        
        "earnings_list": "📊 *История доходов*\n\n{list}\n\n💵 Итого: *{total}$*",
        "earnings_empty": "📊 *История доходов*\n\nПока нет доходов.\nПригласи друзей и зарабатывай!",
        "earnings_row": "• {date} — {name}\n  💰 {amount}$ → 15% = *{commission}$*",
        
        "withdrawal_request": "💸 *Запрос на вывод*\n\n💵 Доступно: *{balance}$*\n\n⚠️ Для вывода необходимо:\n1. Указать e-mail\n2. Указать крипто-адрес (BEP-20)\n3. Минимум *{min}$*\n\n📧 _Отправь свой e-mail:_\n/cancel для отмены",
        
        "withdrawal_enter_address": "💸 *Вывод средств*\n\n💵 Сумма: *{amount}$*\n📧 E-mail: {email}\n\n📋 Теперь отправь адрес кошелька *(BEP-20 USDT)*:\n\n⚠️ Проверь адрес внимательно!\n/cancel для отмены",
        
        "withdrawal_confirm": "💸 *Подтверждение вывода*\n\n💵 Сумма: *{amount}$*\n📧 E-mail: {email}\n📋 Адрес: `{address}`\n\n⚠️ Проверь все данные!\nПосле подтверждения заявка будет отправлена администрации.",
        
        "withdrawal_submitted": "✅ *Заявка отправлена!*\n\n💵 Сумма: *{amount}$*\n📋 Адрес: `{address}`\n\n⏳ Заявка будет обработана администрацией в течение 24-48 часов.\n\nТы получишь уведомление о статусе.",
        
        "withdrawal_approved": "🎉 *Выплата одобрена!*\n\n💵 Сумма: *{amount}$*\n📋 Адрес: `{address}`\n\n✅ Средства будут отправлены в ближайшее время.\n{notes}",
        
        "withdrawal_rejected": "❌ *Выплата отклонена*\n\n💵 Сумма: *{amount}$*\n\n📝 Причина: {reason}",
        
        "withdrawal_history": "📜 *История выплат*\n\n{list}",
        "withdrawal_history_empty": "📜 *История выплат*\n\nПока нет выплат.",
        "withdrawal_row_pending": "⏳ {date} — *{amount}$* (ожидает)",
        "withdrawal_row_approved": "✅ {date} — *{amount}$* (одобрено)",
        "withdrawal_row_rejected": "❌ {date} — *{amount}$* (отклонено)",
        
        "withdrawal_error_banned": "❌ Вывод средств недоступен.",
        "withdrawal_error_pending": "⚠️ У тебя уже есть активная заявка на вывод.\nДождись её обработки.",
        "withdrawal_error_min": "❌ Минимальная сумма для вывода: *{min}$*\nТвой баланс: *{balance}$*",
        "withdrawal_error_no_email": "❌ Для вывода необходимо указать e-mail.",
        "withdrawal_error_rate_limit": "⚠️ Слишком много запросов.\nПопробуй позже.",
        
        "referral_welcome": "👋 Тебя пригласил друг!\n\n🎁 Подписка → друг получит *10 дней* + *20% комиссии*\n💰 Курс → друг получит *15% комиссии*\n\n🔐 Выбери план:",
        
        "help": "📖 *Команды:*\n\n/start — Начать\n/status — Статус\n/renew — Продлить\n/referral — Рефералы\n/language — Язык\n/support — Поддержка\n/id — Мой ID\n/loyalty — Лояльность\n/help — Справка",
        "support": "📩 *Поддержка*\n\nНапиши нам: {contact}\n\nОпиши проблему и приложи TX хеш.",
        "auto_found": "✅ *Платёж найден автоматически!*\n\n📦 Тариф: *{name}*\n📅 Активен до: *{expires}*\n🔖 TX: `{tx}`\n\n_Обнаружен фоновой проверкой._",
        "upsell": "💡 *Специальное предложение!*\n\nТвоя подписка *{plan}* скоро заканчивается.\n\n🔥 Перейди на *годовой план* — экономия *{save}%*!\n💰 Цена: *{yearly_price} USDT* вместо {monthly_x12}",
    },
    "en": {
        "welcome": "👋 Hello, {name}!\n\n🔐 This is an exclusive paid traders chat.\n\n📋 *Choose your subscription plan:*",
        "active_sub": "👋 Hello, {name}!\n\n✅ Subscription active until *{expires}*\n📦 Plan: *{plan}*\n⏳ Days left: *{days}*",
        "inactive_welcome": "👋 Hello, {name}!\n\n❌ You do not have an active subscription right now.\n\n👥 Invite friends and get free access to the chat and courses!\n\n📋 *Choose a product:*",
        "inactive_welcome_note": "❌ You do not have an active subscription right now.\n\n👥 Invite friends and get free access to the chat and courses!",
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
        
        # NEW REFERRAL EARNINGS TEXTS
        "referral_info": "👥 *Referral Program*\n\n🎁 For chat subscription: *+10 days* + *20% commission*\n💰 For course purchase: *+15% commission*\n\n📌 Your link:\n`{ref_link}`\n\n📊 Invited: *{count}*\n🎁 Subscription bonuses: *{bonuses}* × 10 days\n💵 Available for withdrawal: *{balance}$*",
        
        "my_referrals": "👥 *My Referrals*\n\n📊 Total: *{count}*\n🎁 Bonuses: *{bonuses}* × 10 days\n📅 Total: *{total_days}* days\n\n{referral_list}",
        "my_referrals_empty": "👥 *My Referrals*\n\nYou haven't invited anyone yet.",
        "referral_row_bonus": "✅ {name} — bonus received",
        "referral_row_pending": "⏳ {name} — waiting",
        "referral_bonus_received": "🎉 *Bonus received!*\n\nYour friend subscribed — *+10 days*!\n📅 Active until: *{expires}*",
        
        # WITHDRAWAL TEXTS
        "referral_earnings": "💰 *Referral Earnings*\n\n💵 Available for withdrawal: *{balance}$*\n📊 Total earned: *{total}$*\n💸 Withdrawn: *{withdrawn}$*\n\n━━━━━━━━━━━━━━━━\n\n🎯 *How it works:*\n• For each course purchased by your referral you get *15% commission*\n• Minimum withdrawal: *{min}$*\n• All payouts processed manually by admin",
        
        "withdrawal_button": "💸 Withdraw funds",
        "earnings_button": "📊 Earnings history",
        "withdrawal_history_button": "📜 Withdrawal history",
        
        "earnings_list": "📊 *Earnings History*\n\n{list}\n\n💵 Total: *{total}$*",
        "earnings_empty": "📊 *Earnings History*\n\nNo earnings yet.\nInvite friends and earn!",
        "earnings_row": "• {date} — {name}\n  💰 {amount}$ → 15% = *{commission}$*",
        
        "withdrawal_request": "💸 *Withdrawal Request*\n\n💵 Available: *{balance}$*\n\n⚠️ Requirements:\n1. Provide e-mail\n2. Provide crypto address (BEP-20)\n3. Minimum *{min}$*\n\n📧 _Send your e-mail:_\n/cancel to cancel",
        
        "withdrawal_enter_address": "💸 *Withdrawal*\n\n💵 Amount: *{amount}$*\n📧 E-mail: {email}\n\n📋 Now send wallet address *(BEP-20 USDT)*:\n\n⚠️ Check address carefully!\n/cancel to cancel",
        
        "withdrawal_confirm": "💸 *Confirm Withdrawal*\n\n💵 Amount: *{amount}$*\n📧 E-mail: {email}\n📋 Address: `{address}`\n\n⚠️ Check all details!\nAfter confirmation request will be sent to admin.",
        
        "withdrawal_submitted": "✅ *Request submitted!*\n\n💵 Amount: *{amount}$*\n📋 Address: `{address}`\n\n⏳ Request will be processed within 24-48 hours.\n\nYou'll be notified about status.",
        
        "withdrawal_approved": "🎉 *Payout approved!*\n\n💵 Amount: *{amount}$*\n📋 Address: `{address}`\n\n✅ Funds will be sent shortly.\n{notes}",
        
        "withdrawal_rejected": "❌ *Payout rejected*\n\n💵 Amount: *{amount}$*\n\n📝 Reason: {reason}",
        
        "withdrawal_history": "📜 *Withdrawal History*\n\n{list}",
        "withdrawal_history_empty": "📜 *Withdrawal History*\n\nNo withdrawals yet.",
        "withdrawal_row_pending": "⏳ {date} — *{amount}$* (pending)",
        "withdrawal_row_approved": "✅ {date} — *{amount}$* (approved)",
        "withdrawal_row_rejected": "❌ {date} — *{amount}$* (rejected)",
        
        "withdrawal_error_banned": "❌ Withdrawal unavailable.",
        "withdrawal_error_pending": "⚠️ You already have an active withdrawal request.\nPlease wait for processing.",
        "withdrawal_error_min": "❌ Minimum withdrawal: *{min}$*\nYour balance: *{balance}$*",
        "withdrawal_error_no_email": "❌ E-mail required for withdrawal.",
        "withdrawal_error_rate_limit": "⚠️ Too many requests.\nTry later.",
        
        "referral_welcome": "👋 Invited by a friend!\n\n🎁 Subscription → friend gets *10 days* + *20% commission*\n💰 Course → friend gets *15% commission*\n\n🔐 Choose plan:",
        
        "help": "📖 *Commands:*\n\n/start — Start\n/status — Status\n/renew — Renew\n/referral — Referrals\n/language — Language\n/support — Support\n/id — My ID\n/loyalty — Loyalty\n/help — Help",
        "support": "📩 *Support*\n\nContact: {contact}\n\nDescribe issue, include TX hash.",
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
    "inactive_welcome": "👋 Sveiks, {name}!\n\n❌ Tev šobrīd nav aktīva abonementa.\n\n👥 Uzaicini draugus un dabū bezmaksas piekļuvi chatam un kursiem!\n\n📋 *Izvēlies produktu:*",
    "inactive_welcome_note": "❌ Tev šobrīd nav aktīva abonementa.\n\n👥 Uzaicini draugus un dabū bezmaksas piekļuvi chatam un kursiem!",
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
    "referral_earnings": "💰 *Referral ienākumi*\n\n💵 Pieejams izmaksai: *{balance}$*\n📊 Kopā nopelnīts: *{total}$*\n💸 Izmaksāts: *{withdrawn}$*\n\n━━━━━━━━━━━━━━━━\n\n🎯 *Kā tas strādā:*\n• Par katru kursa pirkumu no tava referral saņem *15% komisiju*\n• Minimālā izmaksas summa: *{min}$*\n• Izmaksas manuāli apstrādā administrācija",
    "withdrawal_button": "💸 Izņemt līdzekļus",
    "earnings_button": "📊 Ienākumu vēsture",
    "withdrawal_history_button": "📜 Izmaksu vēsture",
    "earnings_list": "📊 *Ienākumu vēsture*\n\n{list}\n\n💵 Kopā: *{total}$*",
    "earnings_empty": "📊 *Ienākumu vēsture*\n\nPagaidām ienākumu nav.\nUzaicini draugus un pelni!",
    "earnings_row": "• {date} — {name}\n  💰 {amount}$ → 15% = *{commission}$*",
    "withdrawal_request": "💸 *Izmaksas pieprasījums*\n\n💵 Pieejams: *{balance}$*\n\n⚠️ Izmaksai nepieciešams:\n1. Norādīt e-pastu\n2. Norādīt crypto adresi (BEP-20)\n3. Minimums *{min}$*\n\n📧 _Atsūti savu e-pastu:_\n/cancel lai atceltu",
    "withdrawal_enter_address": "💸 *Izmaksa*\n\n💵 Summa: *{amount}$*\n📧 E-pasts: {email}\n\n📋 Tagad atsūti maka adresi *(BEP-20 USDT)*:\n\n⚠️ Rūpīgi pārbaudi adresi!\n/cancel lai atceltu",
    "withdrawal_confirm": "💸 *Izmaksas apstiprinājums*\n\n💵 Summa: *{amount}$*\n📧 E-pasts: {email}\n📋 Adrese: `{address}`\n\n⚠️ Pārbaudi visus datus!\nPēc apstiprinājuma pieprasījums tiks nosūtīts administrācijai.",
    "withdrawal_submitted": "✅ *Pieprasījums nosūtīts!*\n\n💵 Summa: *{amount}$*\n📋 Adrese: `{address}`\n\n⏳ Pieprasījums tiks apstrādāts 24-48 stundu laikā.\n\nTu saņemsi paziņojumu par statusu.",
    "withdrawal_approved": "🎉 *Izmaksa apstiprināta!*\n\n💵 Summa: *{amount}$*\n📋 Adrese: `{address}`\n\n✅ Līdzekļi drīz tiks nosūtīti.\n{notes}",
    "withdrawal_rejected": "❌ *Izmaksa noraidīta*\n\n💵 Summa: *{amount}$*\n\n📝 Iemesls: {reason}",
    "withdrawal_history": "📜 *Izmaksu vēsture*\n\n{list}",
    "withdrawal_history_empty": "📜 *Izmaksu vēsture*\n\nPagaidām izmaksu nav.",
    "withdrawal_row_pending": "⏳ {date} — *{amount}$* (gaida)",
    "withdrawal_row_approved": "✅ {date} — *{amount}$* (apstiprināta)",
    "withdrawal_row_rejected": "❌ {date} — *{amount}$* (noraidīta)",
    "withdrawal_error_banned": "❌ Izmaksa nav pieejama.",
    "withdrawal_error_pending": "⚠️ Tev jau ir aktīvs izmaksas pieprasījums.\nLūdzu sagaidi apstrādi.",
    "withdrawal_error_min": "❌ Minimālā izmaksas summa: *{min}$*\nTavs atlikums: *{balance}$*",
    "withdrawal_error_no_email": "❌ Izmaksai nepieciešams e-pasts.",
    "withdrawal_error_rate_limit": "⚠️ Pārāk daudz pieprasījumu.\nPamēģini vēlāk.",
    "referral_welcome": "👋 Tevi uzaicināja draugs!\n\n🎁 Kad tu veiksi pirkumu, draugs saņems *+10 bezmaksas dienas*.\n\n🔐 Izvēlies produktu:",
    "help": "📖 *Komandas:*\n\n/start — Sākt\n/status — Statuss\n/renew — Pagarināt\n/referral — Referrals\n/language — Valoda\n/support — Atbalsts\n/id — Mans ID\n/loyalty — Lojalitāte\n/help — Palīdzība",
    "support": "📩 *Atbalsts*\n\nRaksti: {contact}\n\nApraksti problēmu un pievieno TX hash, ja tāds ir.",
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

_active_payment_sessions = {}
PAYMENT_TIMEOUT_SEC = 15 * 60
PAYMENT_POLL_INTERVAL = 10
PAYMENT_MAX_ATTEMPTS = PAYMENT_TIMEOUT_SEC // PAYMENT_POLL_INTERVAL

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
        b.button(text="💎  VIP Treideru čats", callback_data="vip_chat_plans")
        b.button(text="📚  MNtradepro kursi", callback_data="courses_menu")
        b.button(text="👥  Uzaicini draugu", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Ikmēneša izloze", callback_data="giveaway_join")
        b.button(text="⚙️  Iestatījumi", callback_data="user_settings")
        b.button(text="📩  Atbalsts", callback_data="user_support")
    elif lang == "ru":
        b.button(text="💎  VIP чат трейдеров", callback_data="vip_chat_plans")
        b.button(text="📚  Курсы MNtradepro Academy", callback_data="courses_menu")
        b.button(text="👥  Приглашай и зарабатывай", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Розыгрыш призов", callback_data="giveaway_join")
        b.button(text="⚙️  Настройки", callback_data="user_settings")
        b.button(text="📩  Поддержка", callback_data="user_support")
    else:
        b.button(text="💎  VIP Traders Chat", callback_data="vip_chat_plans")
        b.button(text="📚  MNtradepro Courses", callback_data="courses_menu")
        b.button(text="👥  Invite & Earn", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Monthly Giveaway", callback_data="giveaway_join")
        b.button(text="⚙️  Settings", callback_data="user_settings")
        b.button(text="📩  Support", callback_data="user_support")
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
        b.button(text="🔄  Mainīt / pagarināt plānu", callback_data="vip_chat_plans")
        b.button(text="💎  Mans lojalitātes līmenis", callback_data="loyalty_status")
        b.button(text="📚  MNtradepro kursi", callback_data="courses_menu")
        b.button(text="👥  Uzaicini draugu", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Ikmēneša izloze", callback_data="giveaway_join")
        b.button(text="⚙️  Iestatījumi", callback_data="user_settings")
        b.button(text="📩  Atbalsts", callback_data="user_support")
    elif lang == "ru":
        b.button(text="🔄  Сменить / продлить тариф", callback_data="vip_chat_plans")
        b.button(text="💎  Мой уровень лояльности", callback_data="loyalty_status")
        b.button(text="📚  Курсы MNtradepro Academy", callback_data="courses_menu")
        b.button(text="👥  Приглашай и зарабатывай", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Розыгрыш призов", callback_data="giveaway_join")
        b.button(text="⚙️  Настройки", callback_data="user_settings")
        b.button(text="📩  Поддержка", callback_data="user_support")
    else:
        b.button(text="🔄  Change / Renew Plan", callback_data="vip_chat_plans")
        b.button(text="💎  My Loyalty Level", callback_data="loyalty_status")
        b.button(text="📚  MNtradepro Courses", callback_data="courses_menu")
        b.button(text="👥  Invite & Earn", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="🎟  Monthly Giveaway", callback_data="giveaway_join")
        b.button(text="⚙️  Settings", callback_data="user_settings")
        b.button(text="📩  Support", callback_data="user_support")
    b.adjust(1)
    return b.as_markup()

def payment_keyboard(plan_key, lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_paid"), callback_data=f"check_{plan_key}")
    b.button(text=t(lang, "btn_qr"), callback_data=f"qr_{plan_key}")
    b.button(text=t(lang, "btn_back"), callback_data="back_plans")
    b.adjust(2, 1)
    return b.as_markup()

def referral_keyboard(lang):
    b = InlineKeyboardBuilder()
    b.button(text="🔗 " + ui_text(lang, "Mana referral saite", "Моя реф. ссылка", "My Ref Link"), callback_data="ref_my_link")
    b.button(text="👥 " + ui_text(lang, "Mani referrals", "Мои рефералы", "My Referrals"), callback_data="ref_my_list")
    b.button(text=back_button_text(lang), callback_data="ref_back_start")
    b.adjust(2, 1)
    return b.as_markup()

def referral_keyboard_with_earnings(lang):
    """Referral keyboard ar earnings"""
    b = InlineKeyboardBuilder()
    b.button(text="👥 " + ui_text(lang, "Mani referrals", "Мои рефералы", "My referrals"), callback_data="ref_my_list")
    b.button(text=back_button_text(lang), callback_data="settings_back")
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
    await state.clear()
    await message.answer(("✅ E-pasts saglabāts." if lang == "lv" else ("✅ E-mail сохранён." if lang == "ru" else "✅ E-mail saved.")), parse_mode="Markdown")
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
        b.button(text="🚨  Pagarināt tagad!", callback_data="vip_chat_plans")
        b.button(text="💎  Mans lojalitātes līmenis", callback_data="loyalty_status")
        b.button(text="📚  MNtradepro kursi", callback_data="courses_menu")
        b.button(text="👥  Uzaicini draugu", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="⚙️  Iestatījumi", callback_data="user_settings")
        b.button(text="📩  Atbalsts", callback_data="user_support")
    elif lang == "ru":
        b.button(text="🚨  Продлить сейчас!", callback_data="vip_chat_plans")
        b.button(text="💎  Мой уровень лояльности", callback_data="loyalty_status")
        b.button(text="📚  Курсы MNtradepro Academy", callback_data="courses_menu")
        b.button(text="👥  Приглашай и зарабатывай", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="⚙️  Настройки", callback_data="user_settings")
        b.button(text="📩  Поддержка", callback_data="user_support")
    else:
        b.button(text="🚨  Renew Now!", callback_data="vip_chat_plans")
        b.button(text="💎  My Loyalty Level", callback_data="loyalty_status")
        b.button(text="📚  MNtradepro Courses", callback_data="courses_menu")
        b.button(text="👥  Invite & Earn", callback_data="ref_main")
        b.button(text="📡  Pro Market Scanner", url="https://t.me/promarketscanner")
        b.button(text="⚙️  Settings", callback_data="user_settings")
        b.button(text="📩  Support", callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


async def _send_referral_reminder(user_id, lang):
    """Nosūta referral reminder 5 min pēc maksājuma"""
    await asyncio.sleep(300)  # 5 minūtes
    try:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        if lang == "ru":
            text = (
                f"💡 *Кстати!*\n\n"
                f"Пригласи друга — и вы оба получите бонус:\n\n"
                f"🎁 Твой друг: скидка на первую подписку\n"
                f"💰 Ты: *комиссия {config.REFERRAL_COMMISSION_CHAT}%* с каждой покупки друга\n"
                f"📅 Плюс *+{config.REFERRAL_BONUS_DAYS} дней* бесплатно!\n\n"
                f"📌 Твоя ссылка:\n`{ref_link}`"
            )
        else:
            text = (
                f"💡 *By the way!*\n\n"
                f"Invite a friend — you both get a bonus:\n\n"
                f"🎁 Your friend: discount on first subscription\n"
                f"💰 You: *{config.REFERRAL_COMMISSION_CHAT}% commission* on every purchase\n"
                f"📅 Plus *+{config.REFERRAL_BONUS_DAYS} days* free!\n\n"
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
                    "Pie šī e-pasta tiks piesaistīta piekļuve un mājaslapas pirkumi.\n\n"
                    "_Atsūti e-pastu vienā ziņā:_"
                )
            elif lang == "ru":
                text = (
                    "📧 *Укажи свой e-mail*\n\n"
                    "К нему будет привязан доступ и покупки с сайта.\n\n"
                    "_Отправь e-mail одним сообщением:_"
                )
            else:
                text = (
                    "📧 *Enter your e-mail*\n\n"
                    "Your access and website purchases will be linked to it.\n\n"
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
    if user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
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
        
        if referral:
            await message.answer(t(lang, "referral_welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
        else:
            welcome_text = await inactive_welcome_text(lang, name)
            await message.answer(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("lang_"))
async def lang_selected(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    if lang not in SUPPORTED_LANGS: lang = DEFAULT_LANG
    await db.set_user_lang(callback.from_user.id, lang)
    name = md_escape(callback.from_user.first_name)
    user = await db.get_user(callback.from_user.id)
    if user and user.get("expires_at") and datetime.fromisoformat(user["expires_at"]) > datetime.utcnow():
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
    await message.answer(t(lang, "support", contact=config.SUPPORT_CONTACT), parse_mode="Markdown")

@dp.callback_query(F.data == "user_support")
async def cb_support(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.answer(t(lang, "support", contact=config.SUPPORT_CONTACT), parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("status"))
async def cmd_status(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
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
    if lang == "lv":
        text = (
            "👥 *Referral programma*\n\n"
            "🎁 Saņem bezmaksas piekļuves dienas par katru aktīvu draugu!\n\n"
            "Uzaicini draugu ar savu unikālo saiti. Tiklīdz viņš veic pirkumu, "
            "tu saņem *10 dienas* piekļuvei kā bonusu.\n\n"
            "🚀 Jo vairāk aktīvu draugu — jo ilgāks tavs bonusa periods."
        )
    elif lang == "ru":
        text = (
            "👥 *Реферальная программа*\n\n"
            "🎁 Получай бесплатный доступ за каждого активного друга!\n\n"
            "Пригласи друга по своей уникальной ссылке. Как только он оформит подписку, "
            "ты получишь *10 дней* доступа к чату в подарок!\n\n"
            "🚀 Чем больше друзей — тем дольше твой бесплатный период."
        )
    else:
        text = (
            "👥 *Referral Program*\n\n"
            "🎁 Get free access for every active friend!\n\n"
            "Invite a friend using your unique link. As soon as they subscribe, "
            "you'll receive *10 days* of free chat access as a gift!\n\n"
            "🚀 The more friends — the longer your free period."
        )
    await message.answer(text, reply_markup=referral_keyboard(lang), parse_mode="Markdown")

@dp.callback_query(F.data == "ref_main")
async def ref_main(callback: CallbackQuery):
    """Referral main - ar earnings info"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    bot_me = await bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{user_id}"
    
    ref_count = await db.get_referral_count(user_id)
    bonus_count = await db.get_referral_bonus_count(user_id)
    balance = await db.get_referral_balance(user_id)
    
    text = t(lang, "referral_info",
        ref_link=ref_link,
        count=ref_count,
        bonuses=bonus_count,
        balance=f"{balance:.2f}"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=referral_keyboard_with_earnings(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_my_link")
async def ref_my_link(callback: CallbackQuery):
    uid = callback.from_user.id
    user = await db.get_user(uid)
    lang = user.get("lang", "ru") if user else "ru"
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    try:
        balance = await db.get_referral_balance(uid)
    except:
        balance = 0.0
    await callback.message.edit_text(t(lang, "referral_info", ref_link=ref_link, count=await db.get_referral_count(uid), bonuses=await db.get_referral_bonus_count(uid), balance=f"{balance:.2f}"), reply_markup=referral_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "ref_my_list")
async def ref_my_list(callback: CallbackQuery):
    uid = callback.from_user.id
    user = await db.get_user(uid)
    lang = user.get("lang", "ru") if user else "ru"
    referrals = await db.get_my_referrals(uid)
    if not referrals:
        await callback.message.edit_text(t(lang, "my_referrals_empty"), reply_markup=referral_keyboard(lang), parse_mode="Markdown")
        await callback.answer(); return
    lines = [t(lang, "referral_row_bonus" if r.get("bonus_given") else "referral_row_pending", name=f"@{r['username']}" if r.get("username") else (r.get("first_name") or f"ID {r['referred_id']}")) for r in referrals]
    bonuses = sum(1 for r in referrals if r.get("bonus_given"))
    await callback.message.edit_text(t(lang, "my_referrals", count=len(referrals), bonuses=bonuses, total_days=bonuses*REFERRAL_BONUS_DAYS, referral_list="\n".join(lines)), reply_markup=referral_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "ref_back_start")
async def ref_back_start(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    if user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
        expires_dt = datetime.fromisoformat(user['expires_at']); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "—"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

# ─── USER SETTINGS ───

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loyalty_system import LoyaltySystem
from cron_jobs import setup_loyalty_cron


class UserSettingsState(StatesGroup):
    waiting_email = State()

@dp.callback_query(F.data == "user_settings")
async def user_settings(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    email = user.get("email", "") if user else ""

    if lang == "lv":
        email_display = email if email else "— nav norādīts"
        text = (
            "⚙️ *Iestatījumi*\n\n"
            f"🌐 Valoda: *Latviešu*\n"
            f"📧 E-pasts: *{email_display}*\n\n"
            "E-pasts piesaista tavu piekļuvi un pirkumus no mājaslapas.\n\n"
            "Izvēlies, ko mainīt:"
        )
    elif lang == "ru":
        email_display = email if email else "— не указан"
        text = (
            "⚙️ *Настройки*\n\n"
            f"🌐 Язык: *Русский*\n"
            f"📧 E-mail: *{email_display}*\n\n"
            "🤔 *Зачем указывать почту?*\n"
            "🎁 Скидки и акции на подписку чата и курсы обучения\n"
            "🎟 Участие в ежемесячном розыгрыше продления абонемента!\n\n"
            "Выбери что изменить:"
        )
    else:
        email_display = email if email else "— not set"
        text = (
            "⚙️ *Settings*\n\n"
            f"🌐 Language: *English*\n"
            f"📧 E-mail: *{email_display}*\n\n"
            "🤔 *Why provide your e-mail?*\n"
            "🎁 Discounts and offers on chat subscription and courses\n"
            "🎟 Monthly subscription extension giveaway!\n\n"
            "Choose what to change:"
        )

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
    email_display = email if email else ("— nav norādīts" if lang == "lv" else ("— не указан" if lang == "ru" else "— not set"))
    if lang == "lv":
        text = (
            "⚙️ *Iestatījumi*\n\n"
            "🌐 Valoda: *Latviešu* ✅\n"
            f"📧 E-pasts: *{email_display}*\n\n"
            "E-pasts piesaista tavu piekļuvi un pirkumus no mājaslapas."
        )
    elif lang == "ru":
        text = (
            "⚙️ *Настройки*\n\n"
            "🌐 Язык: *Русский* ✅\n"
            f"📧 E-mail: *{email_display}*\n\n"
            "🤔 *Зачем указывать почту?*\n"
            "🎁 Скидки и акции на подписку чата и курсы обучения\n"
            "🎟 Участие в ежемесячном розыгрыше продления абонемента!"
        )
    else:
        text = (
            "⚙️ *Settings*\n\n"
            "🌐 Language: *English* ✅\n"
            f"📧 E-mail: *{email_display}*\n\n"
            "🤔 *Why provide your e-mail?*\n"
            "🎁 Discounts and offers on chat subscription and courses\n"
            "🎟 Monthly subscription extension giveaway!"
        )
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
            "Šis e-pasts tiks izmantots, lai piesaistītu tavu piekļuvi un mājaslapas pirkumus.\n\n"
            "_Atsūti savu e-pastu ziņā:_\n\n"
            "/cancel lai atceltu"
        )
    elif lang == "ru":
        text = (
            "📧 *Укажи свой e-mail:*\n\n"
            "🤔 *Зачем указывать почту?*\n"
            "🎁 Скидки и акции на подписку чата и курсы обучения\n"
            "🎟 Участие в ежемесячном розыгрыше продления абонемента!\n\n"
            "_Отправь свой e-mail сообщением:_\n\n"
            "/cancel для отмены"
        )
    else:
        text = (
            "📧 *Enter your e-mail:*\n\n"
            "🤔 *Why provide your e-mail?*\n"
            "🎁 Discounts and offers on chat subscription and training courses\n"
            "🎟 Monthly subscription extension giveaway!\n\n"
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
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        await message.answer(f"✅ E-pasts saglabāts: *{email}*", parse_mode="Markdown")
    elif lang == "ru":
        await message.answer(f"✅ E-mail сохранён: *{email}*", parse_mode="Markdown")
    else:
        await message.answer(f"✅ E-mail saved: *{email}*", parse_mode="Markdown")


@dp.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    has_active = user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow()
    if has_active:
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
                "🤔 *Зачем указывать почту?*\n"
                "🎁 Скидки и акции на подписку чата и курсы обучения\n"
                "🎟 Участие в ежемесячном розыгрыше!\n\n"
                "📧 _Отправь свой e-mail сообщением:_\n"
                "/cancel для отмены"
            )
        elif lang == "lv":
            text = (
                "🎟 *Mēneša izloze*\n\n"
                f"Katru mēnesi abonenti var laimēt *+{prize_days} dienas* bezmaksas piekļuvi!\n\n"
                "⚠️ Lai piedalītos, jānorāda *e-pasts*.\n\n"
                "🤔 *Kāpēc norādīt e-pastu?*\n"
                "🎁 Atlaides abonementam un kursiem\n"
                "🎟 Dalība ikmēneša izlozē!\n\n"
                "📧 _Atsūti savu e-pastu ziņā:_\n"
                "/cancel lai atceltu"
            )
        else:
            text = (
                "🎟 *Monthly Giveaway*\n\n"
                f"Every month subscribers can win *+{prize_days} days* of free access!\n\n"
                "⚠️ To participate you need to provide your *e-mail*.\n\n"
                "🤔 *Why provide your e-mail?*\n"
                "🎁 Discounts on subscription and courses\n"
                "🎟 Monthly giveaway participation!\n\n"
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

    # Atzīmēt kodu kā izmantotu
    await db.use_promo_code(code)

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
        await callback.answer("⚠️ No pending payment", show_alert=True); return
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

        # ═══════════════════════════════════════════════════════════════
        # REFERRAL COMMISSION 15%
        # ═══════════════════════════════════════════════════════════════
        ref = await db.get_referral_by_referred(user_id)
        if ref and False:
            referrer_id = ref['referrer_id']
            commission = round(expected * (config.REFERRAL_COMMISSION_COURSES / 100), 2)
            
            await db.add_referral_earning(
                referrer_id=referrer_id,
                referred_id=user_id,
                purchase_id=purchase_id,
                course_key=course_key,
                amount_usd=expected,
                commission_usd=commission
            )
            
            # Paziņo referrer
            try:
                referrer = await db.get_user(referrer_id)
                ref_lang = referrer.get("lang", "ru") if referrer else "ru"
                ref_balance = await db.get_referral_balance(referrer_id)
                
                if ref_lang == "ru":
                    ref_text = (
                        f"💰 *Новый доход!*\n\n"
                        f"Твой реферал купил курс *{name_ru}*\n"
                        f"💵 Твоя комиссия: *{commission}$*\n\n"
                        f"📊 Доступно для вывода: *{ref_balance:.2f}$*"
                    )
                else:
                    ref_text = (
                        f"💰 *New earning!*\n\n"
                        f"Your referral purchased *{name_ru}* course\n"
                        f"💵 Your commission: *{commission}$*\n\n"
                        f"📊 Available for withdrawal: *{ref_balance:.2f}$*"
                    )
                
                await bot.send_message(referrer_id, ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {referrer_id}: {e}")
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

        # Referral bonus +10 dienas arī par kursu pirkumu
        ref = await db.get_referral_by_referred(user_id)
        if ref and not ref.get("bonus_given"):
            now = datetime.utcnow()
            referrer = await db.get_user(ref["referrer_id"])
            if referrer:
                rb = datetime.fromisoformat(referrer['expires_at']) if referrer.get('expires_at') else now
                bexp = (rb if rb > now else now) + timedelta(days=REFERRAL_BONUS_DAYS)
                await db.activate_subscription(
                    user_id=ref["referrer_id"], username=referrer.get("username"),
                    plan_key=referrer.get("plan_key") or "referral_bonus",
                    plan_name=f"Referral Bonus +{REFERRAL_BONUS_DAYS}d",
                    expires_at=bexp, tx_hash=f"ref_course_{user_id}_{int(now.timestamp())}"
                )
                await db.mark_referral_bonus_given(user_id)
                rlang = referrer.get("lang", "ru")
                try:
                    await bot.send_message(ref["referrer_id"],
                        t(rlang, "referral_bonus_received", expires=bexp.strftime("%d.%m.%Y")),
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

async def notify_admins_error(context: str, error: str):
    """Sūta admin paziņojumu par kļūdu"""
    text = f"⚠️ *Bota kļūda*\n\n📍 `{context}`\n❌ `{str(error)[:500]}`"
    for aid in config.ADMIN_IDS:
        try: await bot.send_message(aid, text, parse_mode="Markdown")
        except: pass


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
    start_text = f"⏳ *{'Проверяю платёж' if lang == 'ru' else 'Checking payment'}...*\n\n⏱ {'Осталось' if lang == 'ru' else 'Time left'}: *15:00*\n\n{'Бот автоматически проверяет каждые 10 секунд' if lang == 'ru' else 'Auto-checking every 10 sec'}"
    try:
        await callback.message.edit_text(start_text, parse_mode="Markdown"); msg = callback.message
    except Exception:
        msg = await callback.message.answer(start_text, parse_mode="Markdown")
    _active_payment_sessions[user_id] = expected
    asyncio.create_task(_confirm_payment(user_id, plan_key, plan, lang, msg, callback.from_user.username or ""))

# ─── UNIVERSĀLA AKTIVIZĀCIJA ───
async def _do_activate(user_id, plan_key, plan, lang, username, tx_hash, amount):
    now = datetime.utcnow()
    user = await db.get_user(user_id)
    if user and user.get('expires_at'):
        cur_exp = datetime.fromisoformat(user['expires_at'])
        new_exp = (cur_exp if cur_exp > now else now) + timedelta(days=plan['days'])
    else:
        new_exp = now + timedelta(days=plan['days'])
    plan_name_save = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    plan_name_loc = plan['name'].get(lang, plan_name_save) if isinstance(plan['name'], dict) else plan['name']
    await db.activate_subscription(user_id=user_id, username=username, plan_key=plan_key, plan_name=plan_name_save, expires_at=new_exp, tx_hash=tx_hash, amount_usdt=amount)
    # Referral bonus + commission
    ref = await db.get_referral_by_referred(user_id)
    if ref and not ref.get("bonus_given"):
        referrer = await db.get_user(ref["referrer_id"])
        if referrer:
            # 1. Give +10 days bonus
            rb = datetime.fromisoformat(referrer['expires_at']) if referrer.get('expires_at') else now
            bexp = (rb if rb > now else now) + timedelta(days=REFERRAL_BONUS_DAYS)
            await db.activate_subscription(user_id=ref["referrer_id"], username=referrer.get("username"), plan_key=referrer.get("plan_key") or "referral_bonus", plan_name=f"Referral Bonus +{REFERRAL_BONUS_DAYS}d", expires_at=bexp, tx_hash=f"ref_bonus_{user_id}_{int(now.timestamp())}")
            await db.mark_referral_bonus_given(user_id)
            ref_lang = referrer.get("lang", "ru")
            ref_text = (
                f"🎁 *Бонус за друга!*\n\nТвой реферал оформил подписку.\nТебе добавлено *+{REFERRAL_BONUS_DAYS} дней* бесплатного доступа."
                if ref_lang == "ru"
                else f"🎁 *Referral bonus!*\n\nYour referral purchased a subscription.\nYou received *+{REFERRAL_BONUS_DAYS} free days*."
            )
            try:
                await bot.send_message(ref["referrer_id"], ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {ref['referrer_id']}: {e}")
            uname = f"@{username}" if username else f"ID {user_id}"
            for aid in config.ADMIN_IDS:
                try: await bot.send_message(aid, f"ðŸ’° *Jauns maksÄjums!*\n\nðŸ‘¤ {uname} (`{user_id}`)\nðŸ“¦ *{plan_name_loc}*\nðŸ’µ *{amount} USDT*\nðŸ“… LÄ«dz: *{new_exp.strftime('%d.%m.%Y')}*\nðŸ”– TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
                except: pass
            return new_exp, plan_name_loc
            
            # 2. Give 20% commission (chat subscription)
            commission = round(amount * (config.REFERRAL_COMMISSION_CHAT / 100), 2)
            # Create a pseudo purchase_id (using payment_history id would be better, but we use timestamp as workaround)
            pseudo_purchase_id = int(now.timestamp())
            await db.add_referral_earning(
                referrer_id=ref["referrer_id"],
                referred_id=user_id,
                purchase_id=pseudo_purchase_id,
                course_key=f"chat_{plan_key}",
                amount_usd=amount,
                commission_usd=commission,
                earning_type="chat"
            )
            
            # Notify referrer
            ref_lang = referrer.get("lang", "ru")
            ref_balance = await db.get_referral_balance(ref["referrer_id"])
            if ref_lang == "ru":
                ref_text = (
                    f"💰 *Новый доход!*\n\n"
                    f"Твой реферал купил подписку на чат\n"
                    f"🎁 Бонус: *+{REFERRAL_BONUS_DAYS} дней*\n"
                    f"💵 Комиссия: *{commission}$* (20%)\n\n"
                    f"📊 Доступно для вывода: *{ref_balance:.2f}$*"
                )
            else:
                ref_text = (
                    f"💰 *New earning!*\n\n"
                    f"Your referral purchased chat subscription\n"
                    f"🎁 Bonus: *+{REFERRAL_BONUS_DAYS} days*\n"
                    f"💵 Commission: *{commission}$* (20%)\n\n"
                    f"📊 Available for withdrawal: *{ref_balance:.2f}$*"
                )
            try:
                await bot.send_message(ref["referrer_id"], ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {ref['referrer_id']}: {e}")
    # Admin notify
    uname = f"@{username}" if username else f"ID {user_id}"
    for aid in config.ADMIN_IDS:
        try: await bot.send_message(aid, f"💰 *Jauns maksājums!*\n\n👤 {uname} (`{user_id}`)\n📦 *{plan_name_loc}*\n💵 *{amount} USDT*\n📅 Līdz: *{new_exp.strftime('%d.%m.%Y')}*\n🔖 TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
        except: pass
    return new_exp, plan_name_loc

# Pēc veiksmīga payment — nosūtīt referral reminder pēc 5 min
async def _post_payment_actions(user_id, lang):
    """Darbības pēc veiksmīga maksājuma — referral reminder"""
    asyncio.create_task(_send_referral_reminder(user_id, lang))

async def _confirm_payment(user_id, plan_key, plan, lang, msg, username):
    elapsed = 0
    try:
        for _ in range(PAYMENT_MAX_ATTEMPTS):
            await asyncio.sleep(PAYMENT_POLL_INTERVAL)
            elapsed += PAYMENT_POLL_INTERVAL
            remaining = PAYMENT_TIMEOUT_SEC - elapsed
            paid = await check_payment(config.CRYPTO_WALLET, plan['price_usdt'], user_id)
            if paid:
                new_exp, plan_name_loc = await _do_activate(user_id, plan_key, plan, lang, username, paid, plan['price_usdt'])
                try:
                    link = await bot.create_chat_invite_link(chat_id_for_lang(lang), member_limit=1, expire_date=int((new_exp + timedelta(days=7)).timestamp()))
                    inv = t(lang, "invite", link=link.invite_link)
                except: inv = f"\n\n📢 {chat_link_for_lang(lang)}"
                txt = t(lang, "paid_ok", name=plan_name_loc, expires=new_exp.strftime('%d.%m.%Y'), tx=paid[:20]) + inv
                try: await msg.edit_text(txt, parse_mode="Markdown")
                except: await bot.send_message(user_id, txt, parse_mode="Markdown")
                await _post_payment_actions(user_id, lang)
                return
            if elapsed % 30 == 0 and remaining > 0:
                m, s = remaining // 60, remaining % 60
                try: await msg.edit_text(f"⏳ *{'Проверяю платёж' if lang == 'ru' else 'Checking'}...*\n\n⏱ {'Осталось' if lang == 'ru' else 'Left'}: *{m}:{s:02d}*\n\n{'Автоматическая проверка каждые 10 секунд' if lang == 'ru' else 'Auto-check every 10 sec'}", parse_mode="Markdown")
                except: pass
        timeout_txt = "❌ *Время вышло (15 мин)*\n\nЕсли отправил — подожди, бот проверяет фоном каждые 3 мин." if lang == "ru" else "❌ *Timeout (15 min)*\n\nIf sent — wait, bot checks background every 3 min."
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
    if user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
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
                    new_exp, pname = await _do_activate(uid, pk, plan, lang, username, tx, amount)
                    try:
                        link = await bot.create_chat_invite_link(chat_id_for_lang(lang), member_limit=1, expire_date=int((new_exp+timedelta(days=7)).timestamp()))
                        inv = t(lang, "invite", link=link.invite_link)
                    except: inv = f"\n\n📢 {chat_link_for_lang(lang)}"
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
    for user in await db.get_expired_users():
        if user.get("is_friend"): continue
        # ADMIN AIZSARDZĪBA — nekad nebanoj adminus
        if user['user_id'] in config.ADMIN_IDS:
            logger.info(f"Skip admin {user['user_id']} — cannot kick admin")
            continue
        try:
            chat_ids = config.all_chat_ids() if hasattr(config, "all_chat_ids") else [config.CHAT_ID]
            for chat_id in chat_ids:
                try:
                    await bot.ban_chat_member(chat_id, user['user_id'])
                    await bot.unban_chat_member(chat_id, user['user_id'])
                except Exception as e:
                    logger.warning(f"Kick failed chat={chat_id} user={user['user_id']}: {e}")
            await db.deactivate_subscription(user['user_id'])
            try: await bot.send_message(user['user_id'], t(user.get("lang","ru"), "kicked"), reply_markup=plans_keyboard(user.get("lang","ru")), parse_mode="Markdown")
            except: pass
            username = f"@{user['username']}" if user.get("username") else f"ID {user['user_id']}"
            expires_at = user.get("expires_at", "")
            admin_text = (
                "🚫 *Lietotājs izmests no čata*\n\n"
                f"👤 {username} (`{user['user_id']}`)\n"
                f"📦 {user.get('plan_name', '—')}\n"
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
                link = await bot.create_chat_invite_link(chat_id_for_lang(lang), member_limit=1, expire_date=int((new_exp + timedelta(days=7)).timestamp()))
                invite_text = f"\n\n🔗 [{('Вступить в чат' if wlang == 'ru' else 'Join chat')}]({link.invite_link})"
            except Exception:
                invite_text = f"\n\n📢 {chat_link_for_lang(lang)}"

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




# Modificētā referral_keyboard ar earnings support
def referral_keyboard_with_earnings(lang):
    b = InlineKeyboardBuilder()
    b.button(text="👥 " + ui_text(lang, "Mani referrals", "Мои рефералы", "My referrals"), callback_data="ref_my_list")
    b.button(text=back_button_text(lang), callback_data="settings_back")
    b.adjust(1)
    return b.as_markup()


# JAUNA - Earnings page ar withdrawal opcijām
@dp.callback_query(F.data == "ref_earnings_page")
async def show_earnings_page(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    # Balance info
    balance = await db.get_referral_balance(user_id)
    total_earned = await db.get_total_referral_earnings(user_id)
    
    # Withdrawn summa
    history = await db.get_user_withdrawal_history(user_id)
    withdrawn = sum(w['amount_usd'] for w in history if w['status'] == 'approved')
    
    text = t(lang, "referral_earnings",
        balance=f"{balance:.2f}",
        total=f"{total_earned:.2f}",
        withdrawn=f"{withdrawn:.2f}",
        min=config.MIN_WITHDRAWAL_AMOUNT
    )
    
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "withdrawal_button"), callback_data="ref_withdraw")
    b.button(text=t(lang, "earnings_button"), callback_data="ref_earnings_list")
    b.button(text=t(lang, "withdrawal_history_button"), callback_data="ref_withdraw_history")
    b.button(text="🔙 " + t(lang, "btn_back"), callback_data="ref_main")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# Earnings list
@dp.callback_query(F.data == "ref_earnings_list")
async def show_earnings_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    earnings = await db.get_referral_earnings_list(user_id)
    
    if not earnings:
        text = t(lang, "earnings_empty")
    else:
        rows = []
        total = 0
        for e in earnings[:20]:
            date = datetime.fromisoformat(e['earned_at']).strftime('%d.%m.%Y')
            ref_name = e.get('referred_username') or e.get('referred_first_name') or f"ID{e['referred_id']}"
            rows.append(t(lang, "earnings_row",
                date=date,
                name=ref_name,
                amount=f"{e['amount_usd']:.2f}",
                commission=f"{e['commission_usd']:.2f}"
            ))
            total += e['commission_usd']
        
        list_str = "\n\n".join(rows)
        text = t(lang, "earnings_list", list=list_str, total=f"{total:.2f}")
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙 " + t(lang, "btn_back"), callback_data="ref_earnings_page")
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# Withdrawal start
@dp.callback_query(F.data == "ref_withdraw")
async def start_withdrawal(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    # Security checks
    if await db.is_user_banned(user_id):
        await callback.answer(t(lang, "withdrawal_error_banned"), show_alert=True)
        return
    
    if await db.has_pending_withdrawal(user_id):
        await callback.answer(t(lang, "withdrawal_error_pending"), show_alert=True)
        return
    
    balance = await db.get_referral_balance(user_id)
    if balance < config.MIN_WITHDRAWAL_AMOUNT:
        await callback.answer(
            t(lang, "withdrawal_error_min", min=config.MIN_WITHDRAWAL_AMOUNT, balance=f"{balance:.2f}"),
            show_alert=True
        )
        return
    
    # Rate limit
    recent_count = await db.count_recent_withdrawal_requests(user_id, hours=24)
    if recent_count >= 3:
        await callback.answer(t(lang, "withdrawal_error_rate_limit"), show_alert=True)
        await db.add_fraud_alert(user_id, "withdrawal_rate_limit", f"{recent_count} requests in 24h")
        return
    
    email = user.get('email', '') if user else ''
    
    if not email:
        await state.set_state(WithdrawalState.waiting_email)
        await state.update_data(withdrawal_amount=balance)
        text = t(lang, "withdrawal_request", balance=f"{balance:.2f}", min=config.MIN_WITHDRAWAL_AMOUNT)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
    else:
        await state.set_state(WithdrawalState.waiting_address)
        await state.update_data(withdrawal_amount=balance, withdrawal_email=email)
        text = t(lang, "withdrawal_enter_address", amount=f"{balance:.2f}", email=email)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()


# Withdrawal email handler
@dp.message(WithdrawalState.waiting_email)
async def withdrawal_receive_email(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ " + ("Отменено" if True else "Cancelled"))
        return
    
    email = message.text.strip()
    if "@" not in email or "." not in email or len(email) < 5:
        await message.answer("❌ " + ("Неверный e-mail. Попробуй:" if True else "Invalid email. Try:"))
        return
    
    await db.set_user_email(message.from_user.id, email)
    
    data = await state.get_data()
    balance = data.get('withdrawal_amount', 0)
    
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    
    await state.set_state(WithdrawalState.waiting_address)
    await state.update_data(withdrawal_email=email)
    
    text = t(lang, "withdrawal_enter_address", amount=f"{balance:.2f}", email=email)
    await message.answer(text, parse_mode="Markdown")


# Withdrawal address handler
@dp.message(WithdrawalState.waiting_address)
async def withdrawal_receive_address(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌")
        return
    
    address = message.text.strip()
    
    if len(address) < 20 or ' ' in address:
        await message.answer("❌ " + ("Неверный адрес" if True else "Invalid address"))
        return
    
    data = await state.get_data()
    balance = data.get('withdrawal_amount', 0)
    email = data.get('withdrawal_email', '')
    
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    
    await state.update_data(withdrawal_address=address)
    
    text = t(lang, "withdrawal_confirm", amount=f"{balance:.2f}", email=email, address=address)
    
    b = InlineKeyboardBuilder()
    b.button(text="✅ " + ("Подтвердить" if lang == "ru" else "Confirm"), callback_data="withdraw_confirm")
    b.button(text="❌ " + ("Отменить" if lang == "ru" else "Cancel"), callback_data="withdraw_cancel")
    b.adjust(2)
    
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# Withdrawal confirm
@dp.callback_query(F.data == "withdraw_confirm")
async def withdrawal_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    user_id = callback.from_user.id
    amount = data.get('withdrawal_amount', 0)
    email = data.get('withdrawal_email', '')
    address = data.get('withdrawal_address', '')
    
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    balance = await db.get_referral_balance(user_id)
    if balance < amount:
        await callback.message.edit_text("❌ Insufficient funds")
        return
    
    request_id = await db.create_withdrawal_request(user_id, amount, address, email)
    
    text = t(lang, "withdrawal_submitted", amount=f"{amount:.2f}", address=address)
    await callback.message.edit_text(text, parse_mode="Markdown")
    
    username = callback.from_user.username or ""
    admin_text = (
        f"💸 *Jauns withdrawal request #{request_id}*\n\n"
        f"👤 @{username} (`{user_id}`)\n"
        f"💵 Summa: *{amount:.2f}$*\n"
        f"📧 E-mail: `{email}`\n"
        f"📋 Adrese: `{address}`\n\n"
        f"Izmanto /admin lai apstiprinātu/noraidītu"
    )
    
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode="Markdown")
        except:
            pass
    
    await callback.answer()


# Withdrawal cancel
@dp.callback_query(F.data == "withdraw_cancel")
async def withdrawal_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Cancelled")
    await callback.answer()


# Withdrawal history
@dp.callback_query(F.data == "ref_withdraw_history")
async def show_withdrawal_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    
    history = await db.get_user_withdrawal_history(user_id)
    
    if not history:
        text = t(lang, "withdrawal_history_empty")
    else:
        rows = []
        for w in history[:10]:
            date = datetime.fromisoformat(w['requested_at']).strftime('%d.%m.%Y')
            status = w['status']
            amount = w['amount_usd']
            
            if status == 'pending':
                row = t(lang, "withdrawal_row_pending", date=date, amount=f"{amount:.2f}")
            elif status == 'approved':
                row = t(lang, "withdrawal_row_approved", date=date, amount=f"{amount:.2f}")
            else:
                row = t(lang, "withdrawal_row_rejected", date=date, amount=f"{amount:.2f}")
            
            rows.append(row)
        
        list_str = "\n".join(rows)
        text = t(lang, "withdrawal_history", list=list_str)
    
    b = InlineKeyboardBuilder()
    b.button(text="🔙 " + t(lang, "btn_back"), callback_data="ref_earnings_page")
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()




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
    else:
        text = (
            f"📊 *Your Loyalty Progress*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} months\n\n"
            "🎁 The longer your subscription stays active, the more free bonus days you unlock."
        )

    b = InlineKeyboardBuilder()
    b.button(text="💎 " + ("Продлить" if lang == 'ru' else "Renew"), 
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
    else:
        text = (
            f"🏆 *Your Loyalty Level*\n\n"
            f"{emoji} *{tag.upper()}*\n"
            f"{bar} *{progress_pct}%*\n\n"
            "🎁 Loyalty now rewards long active subscriptions with free bonus days."
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📋  " + ("Все уровни и бонусы" if lang == 'ru' else "All levels & rewards"),
             callback_data="loyalty_tiers_info")
    # Course upsell poga priekš Rookie/Active
    if current_tier in ('rookie', 'active'):
        b.button(text="🔥  " + ("Курсы — прокачай трейдинг!" if lang == 'ru' else "Courses — level up!"),
                 callback_data="courses_menu")
    b.button(text="🔙  " + ("Назад" if lang == 'ru' else "Back"),
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
        marker = " ◀ ТЫ ЗДЕСЬ" if is_current and lang == 'ru' else (" ◀ YOU" if is_current else "")
        
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
    else:
        text += "\n💡 *Your progress is saved while subscription is active!*"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔙 " + ("Назад" if lang == 'ru' else "Back"), callback_data="loyalty_status")
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
        text = "❌ " + ("У тебя нет активных промокодов" if lang == 'ru' else "You have no active promo codes")
        b = InlineKeyboardBuilder()
        b.button(text="🔙 " + ("Назад" if lang == 'ru' else "Back"), callback_data="loyalty_main")
        b.adjust(1)
        await callback.message.edit_text(text, reply_markup=b.as_markup())
        await callback.answer()
        return
    
    if lang == 'ru':
        text = "💳 *ТВОИ ПРОМОКОДЫ*\n\n"
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
            if lang == 'ru':
                text += f"🎯 *Loyalty Discount*\n\n"
            else:
                text += f"🎯 *Loyalty Discount*\n\n"
        
        elif coupon_type == 'reminder_bonus':
            if lang == 'ru':
                text += f"🎁 *Reminder Bonus*\n\n"
            else:
                text += f"🎁 *Reminder Bonus*\n\n"
        
        elif coupon_type == 'winback':
            if lang == 'ru':
                text += f"🔙 *Welcome Back*\n\n"
            else:
                text += f"🔙 *Welcome Back*\n\n"
        
        elif coupon_type == 'survey':
            if lang == 'ru':
                text += f"📊 *Survey Reward*\n\n"
            else:
                text += f"📊 *Survey Reward*\n\n"
        
        # Code
        if lang == 'ru':
            text += f"Код: `{code}`\n"
            text += f"Скидка: *{discount}%*\n"
        else:
            text += f"Code: `{code}`\n"
            text += f"Discount: *{discount}%*\n"
        
        # Applies to
        if applies_to == 'all':
            text += ("Применяется: Все планы + курсы\n" if lang == 'ru' else "Applies to: All plans + courses\n")
        elif applies_to == 'chat':
            text += ("Применяется: Только планы\n" if lang == 'ru' else "Applies to: Plans only\n")
        elif applies_to == 'courses':
            text += ("Применяется: Только курсы\n" if lang == 'ru' else "Applies to: Courses only\n")
        
        # Expiry
        if expires_at:
            expiry_dt = datetime.fromisoformat(expires_at)
            time_left = expiry_dt - datetime.utcnow()
            
            if time_left.total_seconds() > 0:
                hours_left = int(time_left.total_seconds() / 3600)
                if lang == 'ru':
                    text += f"Истекает: ⏰ через {hours_left} часов\n"
                else:
                    text += f"Expires: ⏰ in {hours_left} hours\n"
        else:
            # Tier-based
            if lang == 'ru':
                text += f"Действует: Пока статус активен\n"
            else:
                text += f"Valid: While status active\n"
        
        # Uses
        if max_uses:
            remaining = max_uses - times_used
            if lang == 'ru':
                text += f"Осталось: {remaining} использование\n"
            else:
                text += f"Remaining: {remaining} use(s)\n"
        else:
            if lang == 'ru':
                text += f"Использований: Безлимит ♾\n"
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
    else:
        text += "ℹ️ Use promo code at checkout\n   to get your discount"
    
    keyboard.button(text=("🔙 Назад" if lang == 'ru' else "🔙 Back"), 
                   callback_data="loyalty_main")
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
    has_active = user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow()
    if has_active:
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
    
    # Log win-back usage
    await db.log_winback_usage(user_id)
    
    if lang == 'ru':
        text = f"""🎁 *Спасибо за ответ!*

Твоя награда:
💳 Код: `{coupon_code}`
💰 Скидка: *20%* на всё
⏰ Действует: 24 часа

Используй при оплате!

[💎 Перейти к тарифам]"""
    else:
        text = f"""🎁 *Thanks for your feedback!*

Your reward:
💳 Code: `{coupon_code}`
💰 Discount: *20%* on everything
⏰ Valid: 24 hours

Use at checkout!

[💎 Go to plans]"""
    
    b = InlineKeyboardBuilder()
    b.button(text=("💎 Тарифы" if lang == 'ru' else "💎 Plans"), 
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer("✅")


@dp.message(SurveyCustomState.waiting_text)
async def survey_custom_text(message: Message, state: FSMContext):
    """Saņem custom survey atbildi"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌")
        return
    
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru') if user else 'ru'
    custom_text = message.text[:500]  # Limitēt garumu
    await state.clear()
    
    coupon_code = await loyalty_system.generate_winback_coupon(user_id, survey_response=True)
    await db.save_survey_response(user_id, custom_text, coupon_code)
    await db.log_winback_usage(user_id)
    
    if lang == 'ru':
        text = (
            f"🎁 *Спасибо за ответ!*\n\n"
            f"Твоя награда:\n"
            f"💳 Код: `{coupon_code}`\n"
            f"💰 Скидка: *20%* на всё\n"
            f"⏰ Действует: 24 часа"
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
    b.button(text=("💎 Тарифы" if lang == 'ru' else "💎 Plans"), callback_data="vip_chat_plans")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")




def _verify_webhook_request(raw_body: bytes, request: web.Request) -> bool:
    if not config.WEBHOOK_SECRET:
        return True
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
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    email = str(payload.get("email") or payload.get("user_email") or "").strip().lower()
    payment_system = str(payload.get("payment_system") or payload.get("payment_method") or "").strip()
    event_id = str(payload.get("event_id") or payload.get("order_id") or payload.get("payment_id") or "").strip()
    amount = float(payload.get("amount") or payload.get("amount_usd") or payload.get("amount_usdt") or 0)
    product_key, plan, plan_error = _webhook_plan_from_payload(payload)

    if not email or "@" not in email:
        return web.json_response({"ok": False, "error": "email_required"}, status=400)
    if plan_error:
        return web.json_response({"ok": False, "error": plan_error}, status=400)
    if not event_id:
        event_id = hashlib.sha256(raw_body).hexdigest()
    event_key = f"{payment_system or 'website'}:{event_id}"
    tx_hash = f"webhook:{event_key}"

    if await db.webhook_event_exists(event_key):
        return web.json_response({"ok": True, "duplicate": True})

    user = await db.get_user_by_email(email)
    if not user:
        for aid in config.ADMIN_IDS:
            try:
                await bot.send_message(aid, f"⚠️ *Webhook purchase without bot user*\n\n📧 `{email}`\n📦 `{product_key}`\n💳 `{payment_system}`", parse_mode="Markdown")
            except Exception:
                pass
        return web.json_response({"ok": False, "error": "email_not_registered"}, status=404)

    lang = user.get("lang", "ru")
    username = user.get("username") or ""
    await db.save_webhook_event(event_key, email, product_key, payment_system, json.dumps(payload, ensure_ascii=False))
    new_exp, plan_name = await _do_activate(user["user_id"], product_key, plan, lang, username, tx_hash, amount)

    try:
        try:
            link = await bot.create_chat_invite_link(chat_id_for_lang(lang), member_limit=1, expire_date=int((new_exp + timedelta(days=7)).timestamp()))
            invite = t(lang, "invite", link=link.invite_link)
        except Exception:
            invite = f"\n\n📢 {chat_link_for_lang(lang)}"
        await bot.send_message(user["user_id"], t(lang, "paid_ok", name=plan_name, expires=new_exp.strftime("%d.%m.%Y"), tx=event_id[:20]) + invite, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Failed to notify webhook buyer {user['user_id']}: {e}")

    return web.json_response({
        "ok": True,
        "telegram_user_id": user["user_id"],
        "email": email,
        "product_key": product_key,
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
    scheduler.add_job(auto_check_pending_payments, 'interval', minutes=3)
    scheduler.add_job(db.cleanup_old_pending, 'interval', hours=1)
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
