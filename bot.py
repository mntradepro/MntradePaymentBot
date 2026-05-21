import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.types import ChatMemberUpdated, Message, CallbackQuery
from aiogram.filters import Command, CommandStart
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

REFERRAL_BONUS_DAYS = 0
SUPPORTED_LANGS = ("ru", "en", "lv")
DEFAULT_LANG = "lv"
SUBSCRIPTION_GRACE_DAYS = 5
VIP_CHAT_PRICE_LABEL = "9.90 EUR"
SCANNER_PRICE_LABEL = "15 EUR"
VIP_CHANNEL_LANGS = ("lv", "ru")
VIP_CHANNEL_LABELS = {
    "lv": f"🇱🇻 Latviešu — {VIP_CHAT_PRICE_LABEL}",
    "ru": f"🇷🇺 Русский — {VIP_CHAT_PRICE_LABEL}",
}
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()


class PublicChatPrivacyGuard(BaseMiddleware):
    allowed_group_commands = {"startpayment", "deletepayment"}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            chat = getattr(event, "chat", None)
            text = (getattr(event, "text", None) or "").strip()
            if chat and getattr(chat, "type", "private") != "private" and text.startswith("/"):
                command = text.split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").lower()
                if command not in self.allowed_group_commands:
                    return
        elif isinstance(event, CallbackQuery):
            message = getattr(event, "message", None)
            chat = getattr(message, "chat", None) if message else None
            if chat and getattr(chat, "type", "private") != "private":
                try:
                    await event.answer("Open the bot in private chat.", show_alert=True)
                except Exception:
                    pass
                return
        return await handler(event, data)


dp.message.middleware(PublicChatPrivacyGuard())
dp.callback_query.middleware(PublicChatPrivacyGuard())

TEXTS = {
    "ru": {
        "welcome": "ðŸ‘‹ ÐŸÑ€Ð¸Ð²ÐµÑ‚, {name}!\n\nðŸ” Ð­Ñ‚Ð¾ ÑÐºÑÐºÐ»ÑŽÐ·Ð¸Ð²Ð½Ñ‹Ð¹ Ð¿Ð»Ð°Ñ‚Ð½Ñ‹Ð¹ Ñ‡Ð°Ñ‚ Ñ‚Ñ€ÐµÐ¹Ð´ÐµÑ€Ð¾Ð².\n\nðŸ“‹ *Ð’Ñ‹Ð±ÐµÑ€Ð¸ ÑÐ²Ð¾Ð¹ Ñ‚Ð°Ñ€Ð¸Ñ„Ð½Ñ‹Ð¹ Ð¿Ð»Ð°Ð½:*",
        "active_sub": "ðŸ‘‹ ÐŸÑ€Ð¸Ð²ÐµÑ‚, {name}!\n\nâœ… ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð°ÐºÑ‚Ð¸Ð²Ð½Ð° Ð´Ð¾ *{expires}*\nðŸ“¦ Ð¢Ð°Ñ€Ð¸Ñ„: *{plan}*\nâ³ ÐžÑÑ‚Ð°Ð»Ð¾ÑÑŒ: *{days}* Ð´Ð½.",
        "inactive_welcome": "ðŸ‘‹ ÐŸÑ€Ð¸Ð²ÐµÑ‚, {name}!\n\nâŒ Ð¡ÐµÐ¹Ñ‡Ð°Ñ Ñƒ Ñ‚ÐµÐ±Ñ Ð½ÐµÑ‚ Ð°ÐºÑ‚Ð¸Ð²Ð½Ð¾Ð¹ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸.\n\nðŸ“‹ *Ð’Ñ‹Ð±ÐµÑ€Ð¸ Ð¿Ñ€Ð¾Ð´ÑƒÐºÑ‚:*",
        "inactive_welcome_note": "âŒ Ð¡ÐµÐ¹Ñ‡Ð°Ñ Ñƒ Ñ‚ÐµÐ±Ñ Ð½ÐµÑ‚ Ð°ÐºÑ‚Ð¸Ð²Ð½Ð¾Ð¹ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸.",
        "choose_plan": "ðŸ“‹ *Ð’Ñ‹Ð±ÐµÑ€Ð¸ ÑÐ²Ð¾Ð¹ Ñ‚Ð°Ñ€Ð¸Ñ„Ð½Ñ‹Ð¹ Ð¿Ð»Ð°Ð½:*",
        "payment_title": "{emoji} *{name}*\n\nðŸ’° Ð¦ÐµÐ½Ð°: *{price}* ({usdt} USDT)\nðŸ“… Ð¡Ñ€Ð¾Ðº: *{days} Ð´Ð½ÐµÐ¹*\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ“¤ ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ Ñ€Ð¾Ð²Ð½Ð¾ *{usdt} USDT (BEP-20)* Ð½Ð°:\n\n`{wallet}`\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nâš ï¸ Ð’Ð°Ð¶Ð½Ð¾:\nâ€¢ Ð¢Ð¾Ð»ÑŒÐºÐ¾ *USDT BEP-20* (ÑÐµÑ‚ÑŒ BSC)\nâ€¢ Ð¡ÑƒÐ¼Ð¼Ð°: *{usdt} USDT*\nâ€¢ ÐŸÐ¾ÑÐ»Ðµ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²ÐºÐ¸ Ð½Ð°Ð¶Ð¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑƒ Ð½Ð¸Ð¶Ðµ",
        "paid_ok": "âœ… *ÐŸÐ»Ð°Ñ‚Ñ‘Ð¶ Ð¿Ð¾Ð´Ñ‚Ð²ÐµÑ€Ð¶Ð´Ñ‘Ð½!*\n\nðŸ“¦ Ð¢Ð°Ñ€Ð¸Ñ„: *{name}*\nðŸ“… ÐÐºÑ‚Ð¸Ð²ÐµÐ½ Ð´Ð¾: *{expires}*\nðŸ”– TX: `{tx}`",
        "paid_fail": "âŒ *ÐŸÐ»Ð°Ñ‚Ñ‘Ð¶ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½*\n\nÐ£Ð±ÐµÐ´Ð¸ÑÑŒ Ñ‡Ñ‚Ð¾ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð¸Ð» Ñ€Ð¾Ð²Ð½Ð¾ *{usdt} USDT (BEP-20)*",
        "status_active": "ðŸŸ¢ *Ð¡Ñ‚Ð°Ñ‚ÑƒÑ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸*\n\nðŸ“… Ð˜ÑÑ‚ÐµÐºÐ°ÐµÑ‚: {expires}\nâ³ ÐžÑÑ‚Ð°Ð»Ð¾ÑÑŒ: {days} Ð´Ð½ÐµÐ¹\nðŸ“¦ Ð¢Ð°Ñ€Ð¸Ñ„: {plan}",
        "status_none": "âŒ Ð£ Ñ‚ÐµÐ±Ñ Ð½ÐµÑ‚ Ð°ÐºÑ‚Ð¸Ð²Ð½Ð¾Ð¹ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸.\n\nÐ˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ /start Ñ‡Ñ‚Ð¾Ð±Ñ‹ ÐºÑƒÐ¿Ð¸Ñ‚ÑŒ.",
        "remind_3": "âš ï¸ *ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ÑÑ‚ÐµÐºÐ°ÐµÑ‚ Ñ‡ÐµÑ€ÐµÐ· 3 Ð´Ð½Ñ!*\n\nðŸ“… Ð”Ð°Ñ‚Ð°: {expires}\n\nÐŸÑ€Ð¾Ð´Ð»Ð¸ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑƒ:",
        "remind_1": "ðŸš¨ *ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ÑÑ‚ÐµÐºÐ°ÐµÑ‚ Ð—ÐÐ’Ð¢Ð Ð!*\n\nðŸ“… Ð”Ð°Ñ‚Ð°: {expires}\n\nÐŸÑ€Ð¾Ð´Ð»Ð¸:",
        "kicked": "ðŸ˜” *ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ÑÑ‚ÐµÐºÐ»Ð°*\n\nÐ¢Ñ‹ Ð±Ñ‹Ð» ÑƒÐ´Ð°Ð»Ñ‘Ð½ Ð¸Ð· ÐºÐ°Ð½Ð°Ð»Ð°.\nÐ”Ð»Ñ Ð²Ð¾ÑÑÑ‚Ð°Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ñ ÐºÑƒÐ¿Ð¸ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑƒ:",
        "btn_paid": "âœ… Ð¯ Ð¾Ð¿Ð»Ð°Ñ‚Ð¸Ð»",
        "btn_qr": "ðŸ“· QR ÐºÐ¾Ð´",
        "btn_back": "ðŸ”™ ÐÐ°Ð·Ð°Ð´",
        "qr_caption": "ðŸ“· *QR ÐºÐ¾Ð´ Ð´Ð»Ñ Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹*\n\nðŸ“‹ ÐÐ´Ñ€ÐµÑ: `{wallet}`\nðŸ’° Ð¡ÑƒÐ¼Ð¼Ð°: *{usdt} USDT (BEP-20)*\nâš ï¸ ÐžÑ‚ÑÐºÐ°Ð½Ð¸Ñ€ÑƒÐ¹ QR â†’ Ð²Ð²ÐµÐ´Ð¸ ÑÑƒÐ¼Ð¼Ñƒ Ð²Ñ€ÑƒÑ‡Ð½ÑƒÑŽ: *{usdt} USDT*\nðŸ”— Ð¡ÐµÑ‚ÑŒ: *BSC (BEP-20)*",
        "invite": "\n\nðŸ”— [Ð’ÑÑ‚ÑƒÐ¿Ð¸Ñ‚ÑŒ Ð² ÐºÐ°Ð½Ð°Ð»]({link})",
        
        "referral_info": "ðŸ‘¥ *Ð ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ð°Ñ Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð°*\n\nðŸŽ Ð—Ð° ÐºÐ°Ð¶Ð´ÑƒÑŽ Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ Ð´Ñ€ÑƒÐ³Ð° Ñ‚Ñ‹ Ð¿Ð¾Ð»ÑƒÑ‡Ð°ÐµÑˆÑŒ *+10 Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ñ… Ð´Ð½ÐµÐ¹*.\n\nðŸ“Œ Ð¢Ð²Ð¾Ñ ÑÑÑ‹Ð»ÐºÐ°:\n`{ref_link}`\n\nðŸ“Š ÐŸÑ€Ð¸Ð³Ð»Ð°ÑˆÐµÐ½Ð¾: *{count}*\nðŸŽ ÐŸÐ¾Ð»ÑƒÑ‡ÐµÐ½Ð¾ Ð±Ð¾Ð½ÑƒÑÐ¾Ð²: *{bonuses}*",
        
        "my_referrals": "ðŸ‘¥ *ÐœÐ¾Ð¸ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»Ñ‹*\n\nðŸ“Š Ð’ÑÐµÐ³Ð¾: *{count}*\nðŸŽ Ð‘Ð¾Ð½ÑƒÑÐ¾Ð²: *{bonuses}* Ã— 10 Ð´Ð½ÐµÐ¹\nðŸ“… Ð˜Ñ‚Ð¾Ð³Ð¾: *{total_days}* Ð´Ð½ÐµÐ¹\n\n{referral_list}",
        "my_referrals_empty": "ðŸ‘¥ *ÐœÐ¾Ð¸ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»Ñ‹*\n\nÐ¢Ñ‹ ÐµÑ‰Ñ‘ Ð½Ð¸ÐºÐ¾Ð³Ð¾ Ð½Ðµ Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑÐ¸Ð».",
        "referral_row_bonus": "âœ… {name} â€” Ð±Ð¾Ð½ÑƒÑ Ð¿Ð¾Ð»ÑƒÑ‡ÐµÐ½",
        "referral_row_pending": "â³ {name} â€” Ð¾Ð¶Ð¸Ð´Ð°ÐµÑ‚ Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹",
        "referral_bonus_received": "ðŸŽ‰ *Ð‘Ð¾Ð½ÑƒÑ Ð¿Ð¾Ð»ÑƒÑ‡ÐµÐ½!*\n\nÐ¢Ð²Ð¾Ð¹ Ð´Ñ€ÑƒÐ³ Ð¾Ñ„Ð¾Ñ€Ð¼Ð¸Ð» Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑƒ â€” Ñ‚ÐµÐ±Ðµ *+10 Ð´Ð½ÐµÐ¹*!\nðŸ“… ÐÐºÑ‚Ð¸Ð²Ð½Ð° Ð´Ð¾: *{expires}*",
        
        "referral_earnings": "ðŸŽ *Ð‘Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ referral*\n\nReferral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_button": "ðŸŽ Ð‘Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸",
        "earnings_button": "ðŸ“Š Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ referral",
        "withdrawal_history_button": "ðŸ“œ Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ bonus days",
        "earnings_list": "ðŸŽ *Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ referral*\n\nÐŸÑ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° referral Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "earnings_empty": "ðŸŽ *Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ referral*\n\nÐŸÑ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° referral Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "earnings_row": "â€¢ {date} â€” {name}",
        "withdrawal_request": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_enter_address": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_confirm": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_submitted": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_approved": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_rejected": "ðŸŽ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
        "withdrawal_history": "ðŸŽ *Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ referral*\n\nÐŸÑ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° referral Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "withdrawal_history_empty": "ðŸŽ *Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ referral*\n\nÐŸÑ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° referral Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "withdrawal_row_pending": "â³ Referral bonus days",
        "withdrawal_row_approved": "âœ… Referral bonus days",
        "withdrawal_row_rejected": "âŒ Referral bonus days",
        "withdrawal_error_banned": "âŒ Ð”ÐµÐ½ÐµÐ¶Ð½Ñ‹Ðµ Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹.",
        "withdrawal_error_pending": "â„¹ï¸ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "withdrawal_error_min": "â„¹ï¸ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "withdrawal_error_no_email": "â„¹ï¸ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "withdrawal_error_rate_limit": "â„¹ï¸ Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
        "referral_welcome": "ðŸ‘‹ Ð¢ÐµÐ±Ñ Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑÐ¸Ð» Ð´Ñ€ÑƒÐ³!\n\nðŸŽ ÐšÐ¾Ð³Ð´Ð° Ñ‚Ñ‹ ÑÐ¾Ð²ÐµÑ€ÑˆÐ¸ÑˆÑŒ Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ, Ð´Ñ€ÑƒÐ³ Ð¿Ð¾Ð»ÑƒÑ‡Ð¸Ñ‚ *+10 Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ñ… Ð´Ð½ÐµÐ¹*.\n\nðŸ” Ð’Ñ‹Ð±ÐµÑ€Ð¸ Ð¿Ñ€Ð¾Ð´ÑƒÐºÑ‚:",
        
        "help": "ðŸ“– *ÐšÐ¾Ð¼Ð°Ð½Ð´Ñ‹:*\n\n/start â€” ÐÐ°Ñ‡Ð°Ñ‚ÑŒ\n/status â€” Ð¡Ñ‚Ð°Ñ‚ÑƒÑ\n/renew â€” ÐŸÑ€Ð¾Ð´Ð»Ð¸Ñ‚ÑŒ\n/language â€” Ð¯Ð·Ñ‹Ðº\n/support â€” ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°\n/id â€” ÐœÐ¾Ð¹ ID\n/loyalty â€” Ð›Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚ÑŒ\n/help â€” Ð¡Ð¿Ñ€Ð°Ð²ÐºÐ°",
        "support": "ðŸ“© *ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°*\n\nÐ•ÑÐ»Ð¸ ÐµÑÑ‚ÑŒ Ð²Ð¾Ð¿Ñ€Ð¾ÑÑ‹, Ð½Ð°Ð¿Ð¸ÑˆÐ¸: https://t.me/mntrade_support",
        "auto_found": "âœ… *ÐŸÐ»Ð°Ñ‚Ñ‘Ð¶ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸!*\n\nðŸ“¦ Ð¢Ð°Ñ€Ð¸Ñ„: *{name}*\nðŸ“… ÐÐºÑ‚Ð¸Ð²ÐµÐ½ Ð´Ð¾: *{expires}*\nðŸ”– TX: `{tx}`\n\n_ÐžÐ±Ð½Ð°Ñ€ÑƒÐ¶ÐµÐ½ Ñ„Ð¾Ð½Ð¾Ð²Ð¾Ð¹ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ¾Ð¹._",
        "upsell": "ðŸ’¡ *Ð¡Ð¿ÐµÑ†Ð¸Ð°Ð»ÑŒÐ½Ð¾Ðµ Ð¿Ñ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ!*\n\nÐ¢Ð²Ð¾Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ° *{plan}* ÑÐºÐ¾Ñ€Ð¾ Ð·Ð°ÐºÐ°Ð½Ñ‡Ð¸Ð²Ð°ÐµÑ‚ÑÑ.\n\nðŸ”¥ ÐŸÐµÑ€ÐµÐ¹Ð´Ð¸ Ð½Ð° *Ð³Ð¾Ð´Ð¾Ð²Ð¾Ð¹ Ð¿Ð»Ð°Ð½* â€” ÑÐºÐ¾Ð½Ð¾Ð¼Ð¸Ñ *{save}%*!\nðŸ’° Ð¦ÐµÐ½Ð°: *{yearly_price} USDT* Ð²Ð¼ÐµÑÑ‚Ð¾ {monthly_x12}",
    },
    "en": {
        "welcome": "ðŸ‘‹ Hello, {name}!\n\nðŸ” This is an exclusive paid traders chat.\n\nðŸ“‹ *Choose your subscription plan:*",
        "active_sub": "ðŸ‘‹ Hello, {name}!\n\nâœ… Subscription active until *{expires}*\nðŸ“¦ Plan: *{plan}*\nâ³ Days left: *{days}*",
        "inactive_welcome": "ðŸ‘‹ Hello, {name}!\n\nâŒ You do not have an active subscription right now.\n\nðŸ“‹ *Choose a product:*",
        "inactive_welcome_note": "âŒ You do not have an active subscription right now.",
        "choose_plan": "ðŸ“‹ *Choose your subscription plan:*",
        "payment_title": "{emoji} *{name}*\n\nðŸ’° Price: *{price}* ({usdt} USDT)\nðŸ“… Duration: *{days} days*\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ“¤ Send exactly *{usdt} USDT (BEP-20)* to:\n\n`{wallet}`\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nâš ï¸ Only *USDT BEP-20* (BSC)\nâ€¢ Amount: *{usdt} USDT*\nâ€¢ Press button after sending",
        "paid_ok": "âœ… *Payment confirmed!*\n\nðŸ“¦ Plan: *{name}*\nðŸ“… Active until: *{expires}*\nðŸ”– TX: `{tx}`",
        "paid_fail": "âŒ *Payment not found*\n\nMake sure you sent exactly *{usdt} USDT (BEP-20)*",
        "status_active": "ðŸŸ¢ *Subscription*\n\nðŸ“… Expires: {expires}\nâ³ Days left: {days}\nðŸ“¦ Plan: {plan}",
        "status_none": "âŒ No active subscription.\n\nUse /start to purchase.",
        "remind_3": "âš ï¸ *Subscription expires in 3 days!*\n\nðŸ“… {expires}\n\nRenew:",
        "remind_1": "ðŸš¨ *Expires TOMORROW!*\n\nðŸ“… {expires}\n\nRenew now:",
        "kicked": "ðŸ˜” *Subscription expired*\n\nYou were removed. Purchase to restore:",
        "btn_paid": "âœ… I have paid",
        "btn_qr": "ðŸ“· QR Code",
        "btn_back": "ðŸ”™ Back",
        "qr_caption": "ðŸ“· *QR Code*\n\nðŸ“‹ Address: `{wallet}`\nðŸ’° Amount: *{usdt} USDT (BEP-20)*\nâš ï¸ Scan QR â†’ enter *{usdt} USDT*\nðŸ”— Network: *BSC (BEP-20)*",
        "invite": "\n\nðŸ”— [Join channel]({link})",
        
        "referral_info": "ðŸ‘¥ *Referral Program*\n\nðŸŽ For every friend purchase you receive *+10 bonus days*.\n\nðŸ“Œ Your link:\n`{ref_link}`\n\nðŸ“Š Invited: *{count}*\nðŸŽ Bonuses received: *{bonuses}*",
        
        "my_referrals": "ðŸ‘¥ *My Referrals*\n\nðŸ“Š Total: *{count}*\nðŸŽ Bonuses: *{bonuses}* Ã— 10 days\nðŸ“… Total: *{total_days}* days\n\n{referral_list}",
        "my_referrals_empty": "ðŸ‘¥ *My Referrals*\n\nYou haven't invited anyone yet.",
        "referral_row_bonus": "âœ… {name} â€” bonus received",
        "referral_row_pending": "â³ {name} â€” waiting",
        "referral_bonus_received": "ðŸŽ‰ *Bonus received!*\n\nYour friend subscribed â€” *+10 days*!\nðŸ“… Active until: *{expires}*",
        
        "referral_earnings": "ðŸŽ *Referral Bonus Days*\n\nThe referral program now uses only bonus days for chats.",
        "withdrawal_button": "ðŸŽ Bonus days",
        "earnings_button": "ðŸ“Š Referral history",
        "withdrawal_history_button": "ðŸ“œ Bonus day history",
        "earnings_list": "ðŸŽ *Referral History*\n\nThe referral program now works only with bonus days.",
        "earnings_empty": "ðŸŽ *Referral History*\n\nThe referral program now works only with bonus days.",
        "earnings_row": "â€¢ {date} â€” {name}",
        "withdrawal_request": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_enter_address": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_confirm": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_submitted": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_approved": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_rejected": "ðŸŽ The referral program now uses only bonus days for chats.",
        "withdrawal_history": "ðŸŽ *Referral History*\n\nThe referral program now works only with bonus days.",
        "withdrawal_history_empty": "ðŸŽ *Referral History*\n\nThe referral program now works only with bonus days.",
        "withdrawal_row_pending": "â³ Referral bonus days",
        "withdrawal_row_approved": "âœ… Referral bonus days",
        "withdrawal_row_rejected": "âŒ Referral bonus days",
        "withdrawal_error_banned": "âŒ Cash payouts are no longer available.",
        "withdrawal_error_pending": "â„¹ï¸ The referral program now works only with bonus days.",
        "withdrawal_error_min": "â„¹ï¸ The referral program now works only with bonus days.",
        "withdrawal_error_no_email": "â„¹ï¸ The referral program now works only with bonus days.",
        "withdrawal_error_rate_limit": "â„¹ï¸ The referral program now works only with bonus days.",
        "referral_welcome": "ðŸ‘‹ Invited by a friend!\n\nðŸŽ When you make a purchase, your friend gets *+10 bonus days*.\n\nðŸ” Choose a product:",
        
        "help": "ðŸ“– *Commands:*\n\n/start â€” Start\n/status â€” Status\n/renew â€” Renew\n/language â€” Language\n/support â€” Support\n/id â€” My ID\n/loyalty â€” Loyalty\n/help â€” Help",
        "support": "ðŸ“© *Support*\n\nIf you have questions, write: https://t.me/mntrade_support",
        "auto_found": "âœ… *Payment found automatically!*\n\nðŸ“¦ Plan: *{name}*\nðŸ“… Until: *{expires}*\nðŸ”– TX: `{tx}`\n\n_Detected by background check._",
        "upsell": "ðŸ’¡ *Special offer!*\n\nYour *{plan}* is ending soon.\n\nðŸ”¥ Upgrade to *yearly* â€” save *{save}%*!\nðŸ’° Price: *{yearly_price} USDT* instead of {monthly_x12}",
    }
}

TEXTS["ru"]["referral_info"] = (
    "ðŸ‘¥ *Ð ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ð°Ñ Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð°*\n\n"
    f"ðŸŽ Ð—Ð° ÐºÐ°Ð¶Ð´Ð¾Ð³Ð¾ Ð´Ñ€ÑƒÐ³Ð°, ÐºÐ¾Ñ‚Ð¾Ñ€Ñ‹Ð¹ Ð¾Ñ„Ð¾Ñ€Ð¼Ð¸Ñ‚ Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ: *+{REFERRAL_BONUS_DAYS} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°.\n\n"
    "ðŸ“Œ Ð¢Ð²Ð¾Ñ ÑÑÑ‹Ð»ÐºÐ°:\n`{ref_link}`\n\n"
    "ðŸ“Š ÐŸÑ€Ð¸Ð³Ð»Ð°ÑˆÐµÐ½Ð¾: *{count}*\nðŸŽ ÐŸÐ¾Ð»ÑƒÑ‡ÐµÐ½Ð¾ Ð±Ð¾Ð½ÑƒÑÐ¾Ð²: *{bonuses}*"
)
TEXTS["en"]["referral_info"] = (
    "ðŸ‘¥ *Referral Program*\n\n"
    f"ðŸŽ For every friend who makes a purchase: *+{REFERRAL_BONUS_DAYS} free days*.\n\n"
    "ðŸ“Œ Your link:\n`{ref_link}`\n\n"
    "ðŸ“Š Invited: *{count}*\nðŸŽ Bonuses received: *{bonuses}*"
)
TEXTS["ru"]["referral_welcome"] = "ðŸ‘‹ Ð¢ÐµÐ±Ñ Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑÐ¸Ð» Ð´Ñ€ÑƒÐ³!\n\nðŸŽ ÐšÐ¾Ð³Ð´Ð° Ñ‚Ñ‹ Ð¾Ñ„Ð¾Ñ€Ð¼Ð¸ÑˆÑŒ Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ, Ð´Ñ€ÑƒÐ³ Ð¿Ð¾Ð»ÑƒÑ‡Ð¸Ñ‚ *+10 Ð´Ð½ÐµÐ¹* Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°.\n\nðŸ” Ð’Ñ‹Ð±ÐµÑ€Ð¸ Ð¿Ñ€Ð¾Ð´ÑƒÐºÑ‚:"
TEXTS["en"]["referral_welcome"] = "ðŸ‘‹ Invited by a friend!\n\nðŸŽ When you make a purchase, your friend gets *+10 free days*.\n\nðŸ” Choose a product:"
TEXTS["lv"] = {
    **TEXTS["en"],
    "welcome": "ðŸ‘‹ Sveiks, {name}!\n\nðŸ” Å is ir slÄ“gts maksas treideru community.\n\nðŸ“‹ *IzvÄ“lies abonementa plÄnu:*",
    "active_sub": "ðŸ‘‹ Sveiks, {name}!\n\nâœ… Abonements aktÄ«vs lÄ«dz *{expires}*\nðŸ“¦ PlÄns: *{plan}*\nâ³ AtlikuÅ¡as dienas: *{days}*",
    "inactive_welcome": "ðŸ‘‹ Sveiks, {name}!\n\nâŒ Tev Å¡obrÄ«d nav aktÄ«va abonementa.\n\nðŸ“‹ *IzvÄ“lies produktu:*",
    "inactive_welcome_note": "âŒ Tev Å¡obrÄ«d nav aktÄ«va abonementa.",
    "choose_plan": "ðŸ“‹ *IzvÄ“lies abonementa plÄnu:*",
    "payment_title": "{emoji} *{name}*\n\nðŸ’° Cena: *{price}* ({usdt} USDT)\nðŸ“… TermiÅ†Å¡: *{days} dienas*\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ“¤ NosÅ«ti tieÅ¡i *{usdt} USDT (BEP-20)* uz:\n\n`{wallet}`\n\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nâš ï¸ Tikai *USDT BEP-20* (BSC)\nâ€¢ Summa: *{usdt} USDT*\nâ€¢ PÄ“c maksÄjuma nospied pogu zemÄk",
    "paid_ok": "âœ… *MaksÄjums apstiprinÄts!*\n\nðŸ“¦ PlÄns: *{name}*\nðŸ“… AktÄ«vs lÄ«dz: *{expires}*\nðŸ”– TX: `{tx}`",
    "paid_fail": "âŒ *MaksÄjums nav atrasts*\n\nPÄrliecinies, ka nosÅ«tÄ«ji tieÅ¡i *{usdt} USDT (BEP-20)*",
    "status_active": "ðŸŸ¢ *Abonements*\n\nðŸ“… Beidzas: {expires}\nâ³ AtlikuÅ¡as dienas: {days}\nðŸ“¦ PlÄns: {plan}",
    "status_none": "âŒ Tev nav aktÄ«va abonementa.\n\nIzmanto /start, lai iegÄdÄtos piekÄ¼uvi.",
    "btn_paid": "âœ… Es samaksÄju",
    "btn_qr": "ðŸ“· QR kods",
    "btn_back": "ðŸ”™ AtpakaÄ¼",
    "qr_caption": "ðŸ“· *QR kods maksÄjumam*\n\nðŸ“‹ Adrese: `{wallet}`\nðŸ’° Summa: *{usdt} USDT (BEP-20)*\nâš ï¸ NoskenÄ“ QR un ievadi summu manuÄli: *{usdt} USDT*\nðŸ”— TÄ«kls: *BSC (BEP-20)*",
    "invite": "\n\nðŸ”— [Pievienoties kanÄlam]({link})",
    "referral_info": "ðŸ‘¥ *Referral programma*\n\nðŸŽ Par katru draugu, kurÅ¡ veic pirkumu: *+10 bezmaksas dienas*.\n\nðŸ“Œ Tava saite:\n`{ref_link}`\n\nðŸ“Š UzaicinÄti: *{count}*\nðŸŽ Bonusi saÅ†emti: *{bonuses}*",
    "my_referrals": "ðŸ‘¥ *Mani referrals*\n\nðŸ“Š KopÄ: *{count}*\nðŸŽ Bonusi: *{bonuses}* Ã— 10 dienas\nðŸ“… KopÄ: *{total_days}* dienas\n\n{referral_list}",
    "my_referrals_empty": "ðŸ‘¥ *Mani referrals*\n\nTu vÄ“l nevienu neesi uzaicinÄjis.",
    "referral_row_bonus": "âœ… {name} â€” bonuss saÅ†emts",
    "referral_row_pending": "â³ {name} â€” gaida pirkumu",
    "referral_bonus_received": "ðŸŽ‰ *Bonuss saÅ†emts!*\n\nTavs draugs veica pirkumu â€” tev *+10 dienas*!\nðŸ“… AktÄ«vs lÄ«dz: *{expires}*",
    "referral_earnings": "ðŸŽ *Referral bonusu dienas*\n\nReferral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_button": "ðŸŽ Bonusu dienas",
    "earnings_button": "ðŸ“Š Referral vÄ“sture",
    "withdrawal_history_button": "ðŸ“œ Bonusu dienu vÄ“sture",
    "earnings_list": "ðŸŽ *Referral vÄ“sture*\n\nReferral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "earnings_empty": "ðŸŽ *Referral vÄ“sture*\n\nReferral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "earnings_row": "â€¢ {date} â€” {name}",
    "withdrawal_request": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_enter_address": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_confirm": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_submitted": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_approved": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_rejected": "ðŸŽ Referral programma tagad izmanto tikai bonusu dienas Äatiem.",
    "withdrawal_history": "ðŸŽ *Referral vÄ“sture*\n\nReferral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "withdrawal_history_empty": "ðŸŽ *Referral vÄ“sture*\n\nReferral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "withdrawal_row_pending": "â³ Referral bonusu dienas",
    "withdrawal_row_approved": "âœ… Referral bonusu dienas",
    "withdrawal_row_rejected": "âŒ Referral bonusu dienas",
    "withdrawal_error_banned": "âŒ Naudas izmaksas vairs nav pieejamas.",
    "withdrawal_error_pending": "â„¹ï¸ Referral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "withdrawal_error_min": "â„¹ï¸ Referral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "withdrawal_error_no_email": "â„¹ï¸ Referral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "withdrawal_error_rate_limit": "â„¹ï¸ Referral programma tagad strÄdÄ tikai ar bonusu dienÄm.",
    "referral_welcome": "ðŸ‘‹ Tevi uzaicinÄja draugs!\n\nðŸŽ Kad tu veiksi pirkumu, draugs saÅ†ems *+10 bezmaksas dienas*.\n\nðŸ” IzvÄ“lies produktu:",
    "help": "ðŸ“– *Komandas:*\n\n/start â€” SÄkt\n/status â€” Statuss\n/renew â€” PagarinÄt\n/language â€” Valoda\n/support â€” Atbalsts\n/id â€” Mans ID\n/loyalty â€” LojalitÄte\n/help â€” PalÄ«dzÄ«ba",
    "support": "ðŸ“© *Atbalsts*\n\nJa rodas jautÄjumi raksti https://t.me/mntrade_support",
}

# Clean runtime overrides for RU/EN user-facing texts.
TEXTS["ru"].update({
    "welcome": "👋 Привет, {name}!\n\n🔐 Это закрытое платное community трейдеров.\n\n📋 *Выбери план подписки:*",
    "active_sub": "👋 Привет, {name}!\n\n✅ Подписка активна до *{expires}*\n📦 План: *{plan}*\n⏳ Осталось дней: *{days}*",
    "inactive_welcome": "👋 Привет, {name}!\n\n❌ Сейчас у тебя нет активной подписки.\n\n📋 *Выбери продукт:*",
    "inactive_welcome_note": "❌ Сейчас у тебя нет активной подписки.",
    "choose_plan": "📋 *Выбери план подписки:*",
    "paid_ok": "✅ *Спасибо! Ваша подписка продлена.*\n\n📦 Продукт: *{name}*\n📅 Активно до: *{expires}*",
    "status_active": "🟢 *Подписка*\n\n📅 Истекает: {expires}\n⏳ Осталось дней: {days}\n📦 План: {plan}",
    "status_none": "❌ У тебя нет активной подписки.\n\nИспользуй /start, чтобы купить доступ.",
    "btn_back": "🔙 Назад",
    "support": "📩 *Поддержка*\n\nЕсли есть вопросы, напиши: https://t.me/mntrade_support",
    "kicked": "😔 *С сожалением сообщаем, что сейчас доступ в чат для вас закрыт.*\n\nБудем рады видеть вас снова.\n\nКак только поступит оплата за продление подписки, вам придёт сообщение, и вы сможете получить новую ссылку, чтобы снова присоединиться к чату.",
})

TEXTS["en"].update({
    "welcome": "👋 Hello, {name}!\n\n🔐 This is a private paid traders community.\n\n📋 *Choose your subscription plan:*",
    "active_sub": "👋 Hello, {name}!\n\n✅ Subscription active until *{expires}*\n📦 Plan: *{plan}*\n⏳ Days left: *{days}*",
    "inactive_welcome": "👋 Hello, {name}!\n\n❌ You do not have an active subscription right now.\n\n📋 *Choose a product:*",
    "inactive_welcome_note": "❌ You do not have an active subscription right now.",
    "choose_plan": "📋 *Choose your subscription plan:*",
    "paid_ok": "✅ *Thank you! Your subscription has been extended.*\n\n📦 Product: *{name}*\n📅 Active until: *{expires}*",
    "status_active": "🟢 *Subscription*\n\n📅 Expires: {expires}\n⏳ Days left: {days}\n📦 Plan: {plan}",
    "status_none": "❌ You do not have an active subscription.\n\nUse /start to purchase access.",
    "btn_back": "🔙 Back",
    "support": "📩 *Support*\n\nIf you have questions, write: https://t.me/mntrade_support",
    "kicked": "😔 *We are sorry to let you know that your access to the chat is currently closed.*\n\nWe will be glad to welcome you back.\n\nAs soon as payment for the subscription renewal is received, you will get a message and will be able to receive a new link to join the chat again.",
})

# Clean runtime overrides for user-facing labels/texts after earlier encoding damage.
VIP_CHANNEL_LABELS["lv"] = "🇱🇻 Latviešu"
VIP_CHANNEL_LABELS["ru"] = "🇷🇺 Русский"

TEXTS["lv"].update({
    "welcome": "👋 Sveiks, {name}!\n\n🔐 Šis ir slēgts maksas treideru community.\n\n📋 *Izvēlies abonementa plānu:*",
    "active_sub": "👋 Sveiks, {name}!\n\n✅ Abonements aktīvs līdz *{expires}*\n📦 Plāns: *{plan}*\n⏳ Atlikušas dienas: *{days}*",
    "inactive_welcome": "👋 Sveiks, {name}!\n\n❌ Tev šobrīd nav aktīva abonementa.\n\n📋 *Izvēlies produktu:*",
    "inactive_welcome_note": "❌ Tev šobrīd nav aktīva abonementa.",
    "choose_plan": "📋 *Izvēlies abonementa plānu:*",
    "paid_ok": "✅ *Paldies! Jūsu abonements ir pagarināts.*\n\n📦 Produkts: *{name}*\n📅 Aktīvs līdz: *{expires}*",
    "status_active": "🟢 *Abonements*\n\n📅 Beidzas: {expires}\n⏳ Atlikušas dienas: {days}\n📦 Plāns: {plan}",
    "status_none": "❌ Tev nav aktīva abonementa.\n\nIzmanto /start, lai iegādātos piekļuvi.",
    "btn_back": "🔙 Atpakaļ",
    "support": "📩 *Atbalsts*\n\nJa rodas jautājumi, raksti: https://t.me/mntrade_support",
    "kicked": "😔 *Ar nožēlu paziņojam, ka šobrīd pieeja čatam Jums ir slēgta.*\n\nPriecāsimies Jūs redzēt atpakaļ.\n\nTiklīdz tiks saņemta apmaksa par abonēšanas pagarinājumu, Jums atnāks ziņa, un Jūs varēsiet iegūt jaunu linku, lai pievienotos čatam atpakaļ.",
})

TEXTS["ru"].update({
    "referral_info": (
        "👥 *Реферальная программа*\n\n"
        "📌 Поделись своей ссылкой. Сейчас автоматические бонусные дни отключены."
    ),
    "referral_welcome": (
        "👋 Тебя пригласил друг!\n\n"
        "🔐 Выбери продукт:"
    ),
    "help": "📘 *Команды:*\n\n/start — Старт\n/status — Статус\n/language — Язык\n/support — Поддержка\n/id — Мой ID\n/help — Помощь",
})

TEXTS["en"].update({
    "referral_info": (
        "👥 *Referral Program*\n\n"
        "📌 Share your link. Automatic bonus days are currently disabled."
    ),
    "referral_welcome": (
        "👋 Invited by a friend!\n\n"
        "🔐 Choose a product:"
    ),
    "help": "📘 *Commands:*\n\n/start — Start\n/status — Status\n/language — Language\n/support — Support\n/id — My ID\n/help — Help",
})

TEXTS["lv"].update({
    "referral_info": (
        "👥 *Referral programma*\n\n"
        "📌 Dalies ar savu saiti. Automātiskās bonusu dienas pašlaik ir izslēgtas."
    ),
    "referral_welcome": (
        "👋 Tevi uzaicināja draugs!\n\n"
        "🔐 Izvēlies produktu:"
    ),
    "help": "📘 *Komandas:*\n\n/start — Sākt\n/status — Statuss\n/language — Valoda\n/support — Atbalsts\n/id — Mans ID\n/help — Palīdzība",
})

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


async def override_text(setting_key: str, lang: str, default_text: str, **kwargs) -> str:
    custom = await db.get_setting(f"{setting_key}_{lang}")
    text = custom or default_text
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:
        return text


async def build_active_access_text(user_id: int, lang: str, name: str = None) -> str:
    user = await db.get_user(user_id)
    active_subs = await db.get_active_user_subscriptions(user_id)
    if not active_subs:
        return ""
    if name is None:
        name = md_escape((user or {}).get("first_name") or "Trader")

    if lang == "lv":
        header = f"ðŸ‘‹ *Sveiks, {name}!*\n\nâœ… *AktÄ«vÄs piekÄ¼uves:*"
    elif lang == "ru":
        header = f"ðŸ‘‹ *ÐŸÑ€Ð¸Ð²ÐµÑ‚, {name}!*\n\nâœ… *ÐÐºÑ‚Ð¸Ð²Ð½Ñ‹Ðµ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸:*"
    else:
        header = f"ðŸ‘‹ *Hello, {name}!*\n\nâœ… *Active subscriptions:*"

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
        product_name = sub.get("product_name") or sub.get("product_key") or "â€”"
        rows.append(f"â€¢ *{product_name}* â€” {expires_dt.strftime('%d.%m.%Y')} ({days_left}d)")

    loyalty_data = await db.get_user_loyalty(user_id)
    if not loyalty_data:
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
    current_tier = loyalty_data.get('current_tier', 'rookie')
    tier_data = config.LOYALTY_TIERS.get(current_tier, {})
    tier_emoji = tier_data.get('emoji', 'ðŸŒ±')
    tier_tag = tier_data.get('tag', 'Rookie')
    if lang == "lv":
        loyalty_line = f"\n\n{tier_emoji} Rangs: *{tier_tag}*"
    elif lang == "ru":
        loyalty_line = f"\n\n{tier_emoji} Ранг: *{tier_tag}*"
    else:
        loyalty_line = f"\n\n{tier_emoji} Rank: *{tier_tag}*"

    urgency = ""
    if nearest_days is not None and nearest_days <= 3:
        if nearest_days == 0:
            urgency = ui_text(lang, "\n\nðŸš¨ *Viena no piekÄ¼uvÄ“m beidzas Å¡odien!*", "\n\nðŸš¨ *ÐžÐ´Ð½Ð° Ð¸Ð· Ð¿Ð¾Ð´Ð¿Ð¸ÑÐ¾Ðº Ð¸ÑÑ‚ÐµÐºÐ°ÐµÑ‚ ÑÐµÐ³Ð¾Ð´Ð½Ñ!*", "\n\nðŸš¨ *One of your subscriptions expires today!*")
        else:
            urgency = ui_text(
                lang,
                f"\n\nâš ï¸ *TuvÄkÄ piekÄ¼uve beidzas pÄ“c {nearest_days} dienÄm!*",
                f"\n\nâš ï¸ *Ð‘Ð»Ð¸Ð¶Ð°Ð¹ÑˆÐ°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ÑÑ‚ÐµÐºÐ°ÐµÑ‚ Ñ‡ÐµÑ€ÐµÐ· {nearest_days} Ð´Ð½.*",
                f"\n\nâš ï¸ *Your nearest subscription expires in {nearest_days} days!*"
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
            "Automātiskās bonusu dienas pašlaik ir izslēgtas."
        ),
        (
            "👥 *Реферальная программа*\n\n"
            f"📌 Твоя ссылка:\n`{ref_link}`\n\n"
            f"📊 Приглашено: *{ref_count}*\n"
            f"✅ Друзья с начисленным бонусом: *{bonus_count}*\n"
            f"🎁 Доступно бонусных дней: *{bonus_days_balance}*\n\n"
            "Автоматические бонусные дни сейчас отключены."
        ),
        (
            "👥 *Referral Program*\n\n"
            f"📌 Your link:\n`{ref_link}`\n\n"
            f"📊 Invited: *{ref_count}*\n"
            f"✅ Friends with granted bonus: *{bonus_count}*\n"
            f"🎁 Available bonus days: *{bonus_days_balance}*\n\n"
            "Automatic bonus days are currently disabled."
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
    return ui_text(
        lang,
        f"PRO Tirgus Skaneris/AI Signāli — {SCANNER_PRICE_LABEL}",
        f"PRO Сканер рынка/AI сигналы — {SCANNER_PRICE_LABEL}",
        f"PRO Market Scanner/AI Signals — {SCANNER_PRICE_LABEL}",
    )

def vip_chat_menu_label(lang):
    return ui_text(
        lang,
        f"VIP Treideru čats — {VIP_CHAT_PRICE_LABEL}",
        f"VIP чат трейдеров — {VIP_CHAT_PRICE_LABEL}",
        f"VIP Traders Chat — {VIP_CHAT_PRICE_LABEL}",
    )

def email_binding_notice(lang):
    return ui_text(
        lang,
        "E-pasts piesaista tavu piekļuvi un pirkumus no mājaslapas, tāpēc norādi derīgu e-pastu.",
        "E-mail привязывает твой доступ и покупки с сайта, поэтому укажи действительный e-mail.",
        "E-mail links your access and website purchases - so enter a valid e-mail.",
    )

def md_escape(text):
    if not text: return ""
    for ch in ['*','_','`','[',']']: text = text.replace(ch, f'\\{ch}')
    return text


async def email_claim_is_blocked(message, email: str, lang: str) -> bool:
    existing = await db.get_other_user_by_email(message.from_user.id, email)
    if not existing:
        return False

    current_uname = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    owner_uname = f"@{existing.get('username')}" if existing.get("username") else f"ID {existing.get('user_id')}"
    await notify_admins(
        "⚠️ *Duplicate e-mail claim blocked*\n\n"
        f"📧 `{email}`\n"
        f"👤 Tried: {md_escape(current_uname)} (`{message.from_user.id}`)\n"
        f"🔒 Already linked: {md_escape(owner_uname)} (`{existing.get('user_id')}`)"
    )
    await message.answer(
        ui_text(
            lang,
            "⚠️ Šis e-pasts jau ir piesaistīts citam Telegram kontam. Ja tas ir tavs e-pasts, raksti atbalstam.",
            "⚠️ Этот e-mail уже привязан к другому Telegram аккаунту. Если это твой e-mail, напиши в поддержку.",
            "⚠️ This e-mail is already linked to another Telegram account. If it is yours, contact support.",
        )
    )
    return True


def chat_id_for_lang(lang):
    return config.chat_id_for_lang(lang) if hasattr(config, "chat_id_for_lang") else config.CHAT_ID

def chat_link_for_lang(lang):
    return config.chat_link_for_lang(lang) if hasattr(config, "chat_link_for_lang") else config.CHAT_LINK


def chat_public_link(chat) -> str:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}"
    invite_link = getattr(chat, "invite_link", None)
    return invite_link or ""


async def user_is_chat_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member_status_value(getattr(member, "status", "")) in {"administrator", "creator"}
    except Exception:
        return False


def member_status_value(status) -> str:
    return getattr(status, "value", str(status or ""))


async def track_chat_user(chat_id: int, tg_user, status: str = "member", is_member: bool = True):
    if not tg_user or getattr(tg_user, "is_bot", False):
        return
    try:
        await db.upsert_chat_member(
            chat_id=chat_id,
            user_id=tg_user.id,
            username=getattr(tg_user, "username", "") or "",
            first_name=getattr(tg_user, "first_name", "") or "",
            status=status,
            is_member=is_member,
        )
    except Exception as e:
        logger.warning(f"chat_member_track_failed chat={chat_id} user={getattr(tg_user, 'id', '-')}: {e}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.from_user, F.text, ~F.text.startswith("/"))
async def track_group_message_user(message: Message):
    await track_chat_user(message.chat.id, message.from_user, "member", True)


@dp.message(F.new_chat_members)
async def track_new_chat_members(message: Message):
    for tg_user in message.new_chat_members or []:
        await track_chat_user(message.chat.id, tg_user, "member", True)


@dp.message(F.left_chat_member)
async def track_left_chat_member(message: Message):
    tg_user = message.left_chat_member
    if tg_user and not getattr(tg_user, "is_bot", False):
        await db.mark_chat_member_left(message.chat.id, tg_user.id, "left")


@dp.chat_member()
async def track_chat_member_update(event: ChatMemberUpdated):
    tg_user = event.new_chat_member.user
    status = member_status_value(event.new_chat_member.status)
    if status in {"left", "kicked"}:
        await db.mark_chat_member_left(event.chat.id, tg_user.id, status)
        return
    is_member = getattr(event.new_chat_member, "is_member", True)
    await track_chat_user(event.chat.id, tg_user, status, bool(is_member))

async def checkout_url_for_lang(lang):
    return (await db.get_setting(f"checkout_url_{lang}")) or ""


async def checkout_url_for_course(course_key, course_lang=None):
    if course_lang:
        specific = (await db.get_setting(f"course_checkout_url_{course_key}_{course_lang}")) or ""
        if specific:
            return specific
    return (await db.get_setting(f"course_checkout_url_{course_key}")) or ""


async def checkout_url_for_subscription_product(product_key: str, user_lang: str) -> str:
    key = normalize_subscription_product_key(product_key, user_lang)
    if key == "vip_chat_lv":
        return (await db.get_setting("checkout_url_lv")) or ""
    if key == "vip_chat_en":
        return (await db.get_setting("checkout_url_en")) or ""
    if key == "vip_chat_ru":
        return (await db.get_setting("checkout_url_ru")) or ""
    if key == "scanner_chat":
        lang = user_lang if user_lang in {"lv", "en", "ru"} else DEFAULT_LANG
        return (
            (await db.get_setting(f"checkout_url_scanner_chat_{lang}"))
            or (await db.get_setting("checkout_url_scanner_chat"))
            or ""
        )
    return (await db.get_setting(f"checkout_url_{key}")) or ""


def normalize_subscription_product_key(product_key: str, user_lang: str) -> str:
    key = (product_key or "").strip().lower()
    aliases = {
        "vip_lv": "vip_chat_lv",
        "vip_chat_lv": "vip_chat_lv",
        "vip_ru": "vip_chat_ru",
        "vip_chat_ru": "vip_chat_ru",
        "vip_en": "vip_chat_en",
        "vip_chat_en": "vip_chat_en",
        "scanner": "scanner_chat",
        "scanner_chat": "scanner_chat",
        "market_scanner": "scanner_chat",
        "monthly": "vip_chat_ru" if user_lang == "ru" else ("vip_chat_en" if user_lang == "en" else "vip_chat_lv"),
    }
    return aliases.get(key, key)


def resolve_subscription_product(product_key: str, user_lang: str) -> dict:
    key = normalize_subscription_product_key(product_key, user_lang)
    catalog = {
        "vip_chat_lv": {
            "chat_id": config.CHAT_IDS.get("lv", config.CHAT_ID),
            "chat_link": config.CHAT_LINKS.get("lv", config.CHAT_LINK),
            "name": {"lv": "VIP Treideru Äats", "ru": "VIP Ñ‡Ð°Ñ‚ Ñ‚Ñ€ÐµÐ¹Ð´ÐµÑ€Ð¾Ð² (LV)", "en": "VIP Traders Chat (LV)"},
        },
        "vip_chat_ru": {
            "chat_id": config.CHAT_IDS.get("ru", config.CHAT_ID),
            "chat_link": config.CHAT_LINKS.get("ru", config.CHAT_LINK),
            "name": {"lv": "VIP Treideru Äats (RU)", "ru": "VIP Ñ‡Ð°Ñ‚ Ñ‚Ñ€ÐµÐ¹Ð´ÐµÑ€Ð¾Ð²", "en": "VIP Traders Chat (RU)"},
        },
        "vip_chat_en": {
            "chat_id": config.CHAT_IDS.get("en", config.CHAT_ID),
            "chat_link": config.CHAT_LINKS.get("en", config.CHAT_LINK),
            "name": {"lv": "VIP Treideru chats (EN)", "ru": "VIP chat traders (EN)", "en": "VIP Traders Chat"},
        },
        "scanner_chat": {
            "chat_id": getattr(config, "SCANNER_CHAT_ID", 0),
            "chat_link": getattr(config, "SCANNER_CHAT_LINK", "https://t.me/promarketscanner"),
            "name": {"lv": "Tirgus Skaneris/AI signÄli", "ru": "Ð¡ÐºÐ°Ð½ÐµÑ€ Ñ€Ñ‹Ð½ÐºÐ°/AI ÑÐ¸Ð³Ð½Ð°Ð»Ñ‹", "en": "Market Scanner/AI Signals"},
        },
    }
    meta = catalog.get(key)
    if not meta:
        return {}
    return {"product_key": key, **meta}


def _slugify_chat_key(value: str) -> str:
    value = (value or "").strip().lower()
    return "".join(ch for ch in value if ch.isalnum())


async def resolve_subscription_product_any(product_key: str, user_lang: str) -> dict:
    normalized_key = normalize_subscription_product_key(product_key, user_lang)
    try:
        managed_by_key = await db.get_managed_chat_by_webhook_key(normalized_key)
    except Exception:
        managed_by_key = None
    if managed_by_key:
        label = str(managed_by_key.get("title") or managed_by_key.get("username") or normalized_key or "Managed Chat")
        return {
            "product_key": normalized_key,
            "chat_id": int(managed_by_key.get("chat_id") or 0),
            "chat_link": str(managed_by_key.get("invite_link") or ""),
            "name": {"lv": label, "ru": label, "en": label},
        }

    meta = resolve_subscription_product(product_key, user_lang)
    if meta and (int(meta.get("chat_id") or 0) or str(meta.get("chat_link") or "").strip()):
        return meta

    wanted = _slugify_chat_key(normalized_key or product_key)
    if not wanted:
        return meta or {}

    try:
        managed_chats = await db.get_managed_chats(active_only=True)
    except Exception:
        return {}

    for chat in managed_chats:
        title = str(chat.get("title") or "")
        username = str(chat.get("username") or "")
        invite_link = str(chat.get("invite_link") or "")
        webhook_key = str(chat.get("webhook_product_key") or "")
        candidates = {
            _slugify_chat_key(title),
            _slugify_chat_key(username),
            _slugify_chat_key(invite_link),
            _slugify_chat_key(str(chat.get("chat_id") or "")),
            _slugify_chat_key(webhook_key),
        }
        if wanted in candidates:
            label = title or username or product_key or "Managed Chat"
            return {
                "product_key": webhook_key or normalized_key or product_key,
                "chat_id": int(chat.get("chat_id") or 0),
                "chat_link": invite_link,
                "name": {
                    "lv": label,
                    "ru": label,
                    "en": label,
                },
            }
    return meta or {}


def paid_invite_message(lang: str, product_name: str, expires_at: datetime, invite_text: str) -> str:
    clean_invite = (invite_text or "").strip()
    if lang == "lv":
        return (
            f"✅ *Paldies par apmaksu!*\n\n"
            f"📦 Produkts: *{product_name}*\n"
            f"📅 Aktīvs līdz: *{expires_at.strftime('%d.%m.%Y')}*\n\n"
            f"🔗 Tavs links uz *{product_name}* ir:\n{clean_invite}"
        )
    if lang == "ru":
        return (
            f"✅ *Спасибо за оплату!*\n\n"
            f"📦 Продукт: *{product_name}*\n"
            f"📅 Активно до: *{expires_at.strftime('%d.%m.%Y')}*\n\n"
            f"🔗 Твоя ссылка в *{product_name}*:\n{clean_invite}"
        )
    return (
        f"✅ *Thank you for your payment!*\n\n"
        f"📦 Product: *{product_name}*\n"
        f"📅 Active until: *{expires_at.strftime('%d.%m.%Y')}*\n\n"
        f"🔗 Your link to *{product_name}* is:\n{clean_invite}"
    )


async def invite_text_for_product(user_id: int, lang: str, product_meta: dict, expires_at: datetime, debug_source: str = "") -> str:
    if not product_meta:
        await notify_admins_error(
            f"invite_meta_missing source={debug_source or 'unknown'} user={user_id}",
            "No product metadata was resolved for invite link generation",
        )
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
        except Exception as e:
            await notify_admins_error(
                f"invite_create_failed source={debug_source or 'unknown'} user={user_id} product={product_meta.get('product_key') or ''} chat_id={chat_id}",
                f"{e}\nchat_link={chat_link or '-'}\nexpires_at={expires_at.isoformat()}",
            )
    if chat_link:
        return f"\n\nðŸ“¢ {chat_link}"
    await notify_admins_error(
        f"invite_target_missing source={debug_source or 'unknown'} user={user_id} product={product_meta.get('product_key') or ''}",
        f"chat_id={chat_id}\nchat_link=-\nexpires_at={expires_at.isoformat()}",
    )
    return ""


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
        product_meta = await resolve_subscription_product_any(sub.get("product_key") or "", lang)
        target_chat_id = sub.get("chat_id", 0) or 0
        target_chat_link = sub.get("chat_link", "") or ""
        if product_meta:
            target_chat_id = int(product_meta.get("chat_id") or target_chat_id or 0)
            target_chat_link = product_meta.get("chat_link") or target_chat_link
        await db.activate_product_subscription(
            user_id=user_id,
            username=username,
            product_key=sub.get("product_key") or "website_subscription",
            product_name=sub.get("product_name") or sub.get("product_key") or "Website Purchase",
            expires_at=expires_at,
            tx_hash=sub.get("tx_hash") or f"claimed:{sub.get('id')}",
            amount_usdt=float(sub.get("amount_usdt") or 0),
            chat_id=target_chat_id,
            chat_link=target_chat_link,
            payment_system=sub.get("payment_system", "") or "webhook",
        )
        await db.deactivate_pending_email_subscription(sub["id"])
        if not product_meta and (sub.get("chat_id") or sub.get("chat_link")):
            product_meta = {
                "product_key": sub.get("product_key") or "website_subscription",
                "chat_id": sub.get("chat_id", 0) or 0,
                "chat_link": sub.get("chat_link", "") or "",
                "name": {
                    "lv": sub.get("product_name") or sub.get("product_key") or "PiekÄ¼uve",
                    "ru": sub.get("product_name") or sub.get("product_key") or "Ð”Ð¾ÑÑ‚ÑƒÐ¿",
                    "en": sub.get("product_name") or sub.get("product_key") or "Access",
                },
            }
        try:
            invite = await invite_text_for_product(
                user_id,
                lang,
                product_meta,
                expires_at,
                debug_source=f"claim_pending email={email} product={sub.get('product_key') or ''}",
            )
            if invite:
                product_name = sub.get("product_name") or sub.get("product_key") or "Access"
                invite_text = paid_invite_message(lang, product_name, expires_at, invite)
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
    """GalvenÄ izvÄ“lne â€” vienots dizains"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("ðŸ’Ž", "VIP Treideru Äats"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ“š", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "IestatÄ«jumi"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("ðŸ’Ž", "VIP Ñ‡Ð°Ñ‚ Ñ‚Ñ€ÐµÐ¹Ð´ÐµÑ€Ð¾Ð²"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ“š", "ÐšÑƒÑ€ÑÑ‹ MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ¸"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"), callback_data="user_support")
    else:
        b.button(text=menu_button("ðŸ’Ž", "VIP Traders Chat"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ“š", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def plans_keyboard(lang):
    """VIP kanÄla valodas izvÄ“le. Pirkums notiek mÄjaslapÄ."""
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
    """Keyboard aktÄ«vajiem abonentiem â€” vienots dizains"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("ðŸ”„", "MainÄ«t / pagarinÄt plÄnu"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "Mans lojalitÄtes lÄ«menis"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "IestatÄ«jumi"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("ðŸ”„", "Ð¡Ð¼ÐµÐ½Ð¸Ñ‚ÑŒ / Ð¿Ñ€Ð¾Ð´Ð»Ð¸Ñ‚ÑŒ Ñ‚Ð°Ñ€Ð¸Ñ„"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "ÐœÐ¾Ð¹ ÑƒÑ€Ð¾Ð²ÐµÐ½ÑŒ Ð»Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚Ð¸"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "ÐšÑƒÑ€ÑÑ‹ MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ¸"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"), callback_data="user_support")
    else:
        b.button(text=menu_button("ðŸ”„", "Change / Renew Plan"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()

# â”€â”€â”€ FIRST-TIME LANGUAGE SELECTION â”€â”€â”€

class RegistrationEmailState(StatesGroup):
    waiting_email = State()

def _first_time_lang_keyboard(ref_param=None):
    """Valodas izvÄ“le jaunajiem lietotÄjiem"""
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data="first_lang_ru")
    b.button(text="🇬🇧 English", callback_data="first_lang_en")
    b.button(text="🇱🇻 Latviešu", callback_data="first_lang_lv")
    b.adjust(2, 1)
    return b.as_markup()


def _is_registered_user(user):
    return bool(user and (user.get("email") or "").strip())


@dp.callback_query(F.data.startswith("first_lang_"))
async def first_lang_selected(callback: CallbackQuery, state: FSMContext):
    """Jauns lietotÄjs izvÄ“lÄ“jÄs valodu â€” startÄ“ onboarding"""
    lang = callback.data.replace("first_lang_", "")
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    user_id = callback.from_user.id
    await db.set_user_lang(user_id, lang)
    name = md_escape(callback.from_user.first_name)
    
    # DzÄ“st valodas izvÄ“les ziÅ†u
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
    if await email_claim_is_blocked(message, email, lang):
        return
    await db.set_user_lang(message.from_user.id, lang)
    await db.set_user_email(message.from_user.id, email)
    claimed = await attach_pending_email_purchases(message.from_user.id, email, lang, message.from_user.username or "")
    uname = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    await notify_admins(
        "📧 *User linked e-mail*\n\n"
        f"👤 {uname} (`{message.from_user.id}`)\n"
        f"📧 `{email}`\n"
        f"📦 Activated pending purchases: *{len(claimed)}*"
    )
    await state.clear()
    await message.answer(("✅ E-pasts saglabāts." if lang == "lv" else ("✅ E-mail сохранён." if lang == "ru" else "✅ E-mail saved.")), parse_mode="Markdown")
    if claimed:
        await message.answer(
            ui_text(
                lang,
                f"✅ Atrasti iepriekšēji pirkumi pēc e-pasta. Aktivizētas piekļuves: {len(claimed)}.",
                f"✅ Найдены предыдущие покупки по e-mail. Активировано доступов: {len(claimed)}.",
                f"✅ Previous purchases were found for this e-mail. Activated accesses: {len(claimed)}.",
            ),
            parse_mode="Markdown",
        )
    await _send_onboarding(message, lang, name)


# â”€â”€â”€ ONBOARDING FLOW â”€â”€â”€

async def _send_onboarding(message, lang, name):
    """3 ziÅ†u karuselis jaunajiem lietotÄjiem"""
    if lang == "lv":
        msg1 = (
            "Laipni lūgts *MNtradepro VIP Treideru čatā* 🚀\n\n"
            "💎 Šeit tu iegūsi piekļuvi slēgtai treideru community ar:\n\n"
            "✅ AI signāliem\n"
            "✅ Tirgus analītiku\n"
            "✅ Idejām darījumiem\n"
            "✅ Atbalstu un pieredzes apmaiņu\n"
            "✅ Papildu materiāliem un jaunumiem\n\n"
            "Izvēlies sev piemērotāko plānu un pievienojies VIP čatam 👇\n\n"
            "Atgādinājums: signāli un analītika nav finanšu konsultācija. "
            "Lēmumus par darījumiem pieņem pats."
        )
        msg2 = (
            f"📚 *MNtradepro kursi*\n\n"
            f"No iesācēja līdz pārliecinātam treiderim — soli pa solim.\n"
            f"Audzē zināšanas un izmanto community pieredzi."
        )
        msg3 = (
            f"🏅 *Rank sistēma*\n\n"
            f"Jo aktīvāks esi community, jo augstāku ranku sasniedz:\n"
            f"🔥 Audzē savu statusu ar aktivitāti\n"
            f"🎯 Sasniedz jaunus līmeņus čatā\n"
            f"Sāc tagad! 👇"
        )
    elif lang == "ru":
        msg1 = (
            "Добро пожаловать в *MNtradepro VIP чат трейдеров* 🚀\n\n"
            "💎 Здесь ты получишь доступ к закрытой community трейдеров с:\n\n"
            "✅ AI сигналами\n"
            "✅ Аналитикой рынка\n"
            "✅ Идеями для сделок\n"
            "✅ Поддержкой и обменом опытом\n"
            "✅ Дополнительными материалами и новостями\n\n"
            "Выбери подходящий план и присоединяйся к VIP чату 👇\n\n"
            "Напоминание: сигналы и аналитика не являются финансовой консультацией. "
            "Решения по сделкам ты принимаешь сам."
        )
        msg2 = (
            f"📚 *Курсы MNtradepro Academy*\n\n"
            f"От новичка до уверенного трейдера — пошаговое обучение.\n"
            f"Прокачивай знания и используй опыт community."
        )
        msg3 = (
            f"🏅 *Система рангов*\n\n"
            f"Чем активнее ты в community, тем выше твой ранг:\n"
            f"🔥 Повышай статус через активность\n"
            f"🎯 Открывай новые уровни в чате\n"
            f"Начни прямо сейчас! 👇"
        )
    else:
        msg1 = (
            "Welcome to *MNtradepro VIP Traders Chat* 🚀\n\n"
            "💎 Here you get access to a private traders community with:\n\n"
            "✅ AI signals\n"
            "✅ Market analysis\n"
            "✅ Trade ideas\n"
            "✅ Support and knowledge sharing\n"
            "✅ Extra materials and updates\n\n"
            "Choose the plan that fits you and join the VIP chat 👇\n\n"
            "Reminder: signals and analysis are not financial advice. "
            "You make your own trading decisions."
        )
        msg2 = (
            f"📚 *MNtradepro Academy Courses*\n\n"
            f"From beginner to confident trader — step-by-step education.\n"
            f"Build your knowledge and use the community experience."
        )
        msg3 = (
            f"🏅 *Rank System*\n\n"
            f"The more active you are in the community, the higher your rank:\n"
            f"🔥 Grow your status through activity\n"
            f"🎯 Reach new levels in the chat\n"
            f"Start now! 👇"
        )
    
    await message.answer(msg1, parse_mode="Markdown")
    await asyncio.sleep(0.5)
    await message.answer(msg2, parse_mode="Markdown")
    await asyncio.sleep(0.5)
    await message.answer(msg3, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")


def _urgency_keyboard(lang):
    """Keyboard ar urgency â€” PagarinÄt tagad pogu augÅ¡Ä"""
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("ðŸš¨", "PagarinÄt tagad!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "Mans lojalitÄtes lÄ«menis"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "IestatÄ«jumi"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("ðŸš¨", "ÐŸÑ€Ð¾Ð´Ð»Ð¸Ñ‚ÑŒ ÑÐµÐ¹Ñ‡Ð°Ñ!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "ÐœÐ¾Ð¹ ÑƒÑ€Ð¾Ð²ÐµÐ½ÑŒ Ð»Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚Ð¸"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "ÐšÑƒÑ€ÑÑ‹ MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ¸"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"), callback_data="user_support")
    else:
        b.button(text=menu_button("ðŸš¨", "Renew Now!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def active_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("ðŸ”—", "SaÅ†emt piekÄ¼uves linku"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ”„", "MainÄ«t / pagarinÄt plÄnu"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "Mans lojalitÄtes lÄ«menis"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "IestatÄ«jumi"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("ðŸ”—", "ÐŸÐ¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ ÑÑÑ‹Ð»ÐºÑƒ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ”„", "Ð¡Ð¼ÐµÐ½Ð¸Ñ‚ÑŒ / Ð¿Ñ€Ð¾Ð´Ð»Ð¸Ñ‚ÑŒ Ñ‚Ð°Ñ€Ð¸Ñ„"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "ÐœÐ¾Ð¹ ÑƒÑ€Ð¾Ð²ÐµÐ½ÑŒ Ð»Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚Ð¸"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "ÐšÑƒÑ€ÑÑ‹ MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ¸"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"), callback_data="user_support")
    else:
        b.button(text=menu_button("ðŸ”—", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ”„", "Change / Renew Plan"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ’Ž", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def _urgency_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("ðŸš¨", "PagarinÄt tagad!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ”—", "SaÅ†emt piekÄ¼uves linku"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ’Ž", "Mans lojalitÄtes lÄ«menis"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "IestatÄ«jumi"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("ðŸš¨", "ÐŸÑ€Ð¾Ð´Ð»Ð¸Ñ‚ÑŒ ÑÐµÐ¹Ñ‡Ð°Ñ!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ”—", "ÐŸÐ¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ ÑÑÑ‹Ð»ÐºÑƒ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ’Ž", "ÐœÐ¾Ð¹ ÑƒÑ€Ð¾Ð²ÐµÐ½ÑŒ Ð»Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚Ð¸"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "ÐšÑƒÑ€ÑÑ‹ MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ¸"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "ÐŸÐ¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"), callback_data="user_support")
    else:
        b.button(text=menu_button("ðŸš¨", "Renew Now!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("ðŸ”—", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("ðŸ’Ž", "My Loyalty Level"), callback_data="loyalty_status")
        b.button(text=menu_button("ðŸ“š", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("ðŸ“¡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("âš™ï¸", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("ðŸ“©", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


async def _send_referral_reminder(user_id, lang):
    """NosÅ«ta referral reminder 5 min pÄ“c maksÄjuma"""
    return
    await asyncio.sleep(300)  # 5 minÅ«tes
    try:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        if lang == "ru":
            text = (
                f"ðŸ’¡ *ÐšÑÑ‚Ð°Ñ‚Ð¸!*\n\n"
                f"ÐŸÑ€Ð¸Ð³Ð»Ð°ÑÐ¸ Ð´Ñ€ÑƒÐ³Ð° â€” Ð¸ Ð¿Ð¾Ð»ÑƒÑ‡Ð°Ð¹ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸:\n\n"
                f"ðŸŽ Ð—Ð° ÐºÐ°Ð¶Ð´ÑƒÑŽ Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ Ð´Ñ€ÑƒÐ³Ð° Ñ‚ÐµÐ±Ðµ Ð½Ð°Ñ‡Ð¸ÑÐ»ÑÐµÑ‚ÑÑ *+{config.REFERRAL_BONUS_DAYS} Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ñ… Ð´Ð½ÐµÐ¹*\n"
                f"ðŸ“… Ð¢Ñ‹ ÑÐ°Ð¼ Ð²Ñ‹Ð±Ð¸Ñ€Ð°ÐµÑˆÑŒ, Ðº ÐºÐ°ÐºÐ¾Ð¼Ñƒ Ð°ÐºÑ‚Ð¸Ð²Ð½Ð¾Ð¼Ñƒ Ñ‡Ð°Ñ‚Ñƒ Ð¸Ñ… Ð¿Ñ€Ð¸Ð¼ÐµÐ½Ð¸Ñ‚ÑŒ.\n\n"
                f"ðŸ“Œ Ð¢Ð²Ð¾Ñ ÑÑÑ‹Ð»ÐºÐ°:\n`{ref_link}`"
            )
        else:
            text = (
                f"ðŸ’¡ *By the way!*\n\n"
                f"Invite a friend and collect bonus days:\n\n"
                f"ðŸŽ For every friend purchase you receive *+{config.REFERRAL_BONUS_DAYS} bonus days*\n"
                f"ðŸ“… You choose which active chat to apply them to.\n\n"
                f"ðŸ“Œ Your link:\n`{ref_link}`"
            )
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Referral reminder failed for {user_id}: {e}")

def main_menu_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("💎", vip_chat_menu_label(lang)), callback_data="vip_chat_plans")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("💎", vip_chat_menu_label(lang)), callback_data="vip_chat_plans")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("💎", vip_chat_menu_label(lang)), callback_data="vip_chat_plans")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def active_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🔗", "Saņemt piekļuves linku"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Mainīt / pagarināt plānu"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🏅", "Mans ranks"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🔗", "Получить ссылку доступа"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Сменить / продлить тариф"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🏅", "Мой ранг"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🔗", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("🔄", "Change / Renew Plan"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🏅", "My Rank"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


def _urgency_keyboard(lang):
    b = InlineKeyboardBuilder()
    if lang == "lv":
        b.button(text=menu_button("🚨", "Pagarināt tagad!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Saņemt piekļuves linku"), callback_data="get_access_links")
        b.button(text=menu_button("🏅", "Mans ranks"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro kursi"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Iestatījumi"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Atbalsts"), callback_data="user_support")
    elif lang == "ru":
        b.button(text=menu_button("🚨", "Продлить сейчас!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Получить ссылку доступа"), callback_data="get_access_links")
        b.button(text=menu_button("🏅", "Мой ранг"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "Курсы MNtradepro Academy"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Настройки"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Поддержка"), callback_data="user_support")
    else:
        b.button(text=menu_button("🚨", "Renew Now!"), callback_data="vip_chat_plans")
        b.button(text=menu_button("🔗", "Get Access Link"), callback_data="get_access_links")
        b.button(text=menu_button("🏅", "My Rank"), callback_data="loyalty_status")
        b.button(text=menu_button("📡", market_scanner_label(lang)), callback_data="market_scanner")
        b.button(text=menu_button("📚", "MNtradepro Courses"), callback_data="courses_menu")
        b.button(text=menu_button("⚙️", "Settings"), callback_data="user_settings")
        b.button(text=menu_button("📩", "Support"), callback_data="user_support")
    b.adjust(1)
    return b.as_markup()


# â”€â”€â”€ HANDLERS â”€â”€â”€

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
            "🆕 *New bot user*\n\n"
            f"👤 {uname} (`{user_id}`)\n"
            f"🌐 Language: `{auto_lang}`"
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
    
    # ReÄ£istrÄcija = DB ieraksts ar e-pastu. Ja e-pasts jau ir, neprasÄm to atkÄrtoti.
    if not has_registered_email:
        # Ja TG ID jau eksistÄ“ DB, valodu vairs neprasÄm â€” tikai trÅ«kstoÅ¡o e-pastu.
        if existing_user:
            if lang == "lv":
                text = (
                    "📧 *Ievadi savu e-pastu*\n\n"
                    f"{email_binding_notice(lang)}\n\n"
                    "_Atsūti e-pastu vienā ziņā:_"
                )
            elif lang == "ru":
                text = (
                    "ðŸ“§ *Ð£ÐºÐ°Ð¶Ð¸ ÑÐ²Ð¾Ð¹ e-mail*\n\n"
                    f"{email_binding_notice(lang)}\n\n"
                    "_ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ e-mail Ð¾Ð´Ð½Ð¸Ð¼ ÑÐ¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸ÐµÐ¼:_"
                )
            else:
                text = (
                    "ðŸ“§ *Enter your e-mail*\n\n"
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
        plan_name = user.get('plan_name', 'â€”')
        
        # Loyalty info
        loyalty_data = await db.get_user_loyalty(user_id)
        if not loyalty_data:
            await db.update_user_loyalty(user_id, 'rookie', 0)
            loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}
        
        current_tier = loyalty_data.get('current_tier', 'rookie')
        consecutive_months = loyalty_data.get('consecutive_months', 0)
        tier_data = config.LOYALTY_TIERS.get(current_tier, {})
        tier_emoji = tier_data.get('emoji', 'ðŸŒ±')
        tier_tag = tier_data.get('tag', 'Rookie')
        tier_discount = tier_data.get('chat_discount', 0)
        
        # Urgency trigger
        urgency = ""
        if days_left <= 3 and days_left > 0:
            if lang == "ru":
                urgency = f"\n\nâš ï¸ *Ð’Ð½Ð¸Ð¼Ð°Ð½Ð¸Ðµ! Ð”Ð¾ Ð¾ÐºÐ¾Ð½Ñ‡Ð°Ð½Ð¸Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸ {days_left} {'Ð´ÐµÐ½ÑŒ' if days_left == 1 else 'Ð´Ð½Ñ'}!*"
            elif lang == "lv":
                urgency = f"\n\nâš ï¸ *UzmanÄ«bu! LÄ«dz abonementa beigÄm palikuÅ¡as {days_left} {'diena' if days_left == 1 else 'dienas'}!*"
            else:
                urgency = f"\n\nâš ï¸ *Warning! Only {days_left} day{'s' if days_left != 1 else ''} left!*"
        elif days_left == 0:
            if lang == "ru":
                urgency = "\n\nðŸš¨ *ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð·Ð°ÐºÐ°Ð½Ñ‡Ð¸Ð²Ð°ÐµÑ‚ÑÑ ÑÐµÐ³Ð¾Ð´Ð½Ñ!*"
            elif lang == "lv":
                urgency = "\n\nðŸš¨ *Abonements beidzas Å¡odien!*"
            else:
                urgency = "\n\nðŸš¨ *Subscription expires today!*"
        
        # NÄkamÄ lÄ«meÅ†a info ar % gamification
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
                        f"\n\nðŸŽ¯ Ð¡Ð»ÐµÐ´ÑƒÑŽÑ‰Ð¸Ð¹: {next_emoji} *{next_tag}* â€” {progress_pct}% Ð¿Ñ€Ð¾Ð¹Ð´ÐµÐ½Ð¾\n"
                        f"ðŸŽ +{next_bonus} Ð´Ð½. Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾, ÑÐºÐ¸Ð´ÐºÐ° {next_discount}%"
                    )
                elif lang == "lv":
                    next_tier_info = (
                        f"\n\nðŸŽ¯ NÄkamais: {next_emoji} *{next_tag}* â€” {progress_pct}% pabeigts\n"
                        f"ðŸŽ +{next_bonus} bezmaksas dienas, {next_discount}% atlaide"
                    )
                else:
                    next_tier_info = (
                        f"\n\nðŸŽ¯ Next: {next_emoji} *{next_tag}* â€” {progress_pct}% complete\n"
                        f"ðŸŽ +{next_bonus} days free, {next_discount}% off"
                    )
                break
        
        if lang == "ru":
            loyalty_line = f"\n\n{tier_emoji} Ð£Ñ€Ð¾Ð²ÐµÐ½ÑŒ: *{tier_tag}*" + (f" ({tier_discount}% ÑÐºÐ¸Ð´ÐºÐ°)" if tier_discount > 0 else "")
        elif lang == "lv":
            loyalty_line = f"\n\n{tier_emoji} LÄ«menis: *{tier_tag}*" + (f" ({tier_discount}% atlaide)" if tier_discount > 0 else "")
        else:
            loyalty_line = f"\n\n{tier_emoji} Level: *{tier_tag}*" + (f" ({tier_discount}% discount)" if tier_discount > 0 else "")
        
        welcome_text = t(lang, "active_sub", name=name, expires=expires, plan=plan_name, days=days_left) + loyalty_line + next_tier_info + urgency
        
        # Ja urgency â€” pievienot speciÄlu keyboard ar "PagarinÄt tagad" pogu augÅ¡Ä
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
        expires_dt = datetime.fromisoformat(user["expires_at"]); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "â€”"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        # Custom welcome no DB (tÄpat kÄ cmd_start)
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("id"))
async def cmd_id(message: Message):
    """ParÄda lietotÄja Telegram ID"""
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        text = f"ðŸ†” *Tavs Telegram ID:*\n\n`{message.from_user.id}`\n\n_NokopÄ“ un nosÅ«ti adminam, ja nepiecieÅ¡ams._"
    elif lang == "ru":
        text = f"ðŸ†” *Ð¢Ð²Ð¾Ð¹ Telegram ID:*\n\n`{message.from_user.id}`\n\n_Ð¡ÐºÐ¾Ð¿Ð¸Ñ€ÑƒÐ¹ Ð¸ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²ÑŒ Ð°Ð´Ð¼Ð¸Ð½Ñƒ ÐµÑÐ»Ð¸ Ð½ÑƒÐ¶Ð½Ð¾._"
    else:
        text = f"ðŸ†” *Your Telegram ID:*\n\n`{message.from_user.id}`\n\n_Copy and send to admin if needed._"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command(commands=["STARTPAYMENT", "startpayment"]))
async def cmd_startpayment(message: Message):
    if message.chat.type == "private":
        await message.answer("Use this command inside the target group or channel discussion chat.")
        return
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if not await user_is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("Only a chat admin can use this command here.")
        return
    parts = (message.text or "").strip().split(maxsplit=1)
    webhook_product_key = normalize_subscription_product_key(parts[1], "lv") if len(parts) > 1 else str(message.chat.id)
    chat = await bot.get_chat(message.chat.id)
    await db.register_managed_chat(
        chat_id=message.chat.id,
        title=getattr(chat, "title", None) or getattr(message.chat, "title", None) or str(message.chat.id),
        username=getattr(chat, "username", None) or "",
        chat_type=message.chat.type,
        invite_link=chat_public_link(chat),
        added_by_user_id=message.from_user.id,
        webhook_product_key=webhook_product_key,
    )
    await message.answer(f"This chat is now registered as a managed payment chat.\nWebhook product key: `{webhook_product_key}`", parse_mode="Markdown")


@dp.message(Command(commands=["DELETEPAYMENT", "deletepayment"]))
async def cmd_deletepayment(message: Message):
    if message.chat.type == "private":
        await message.answer("Use this command inside the target group or channel discussion chat.")
        return
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if not await user_is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("Only a chat admin can use this command here.")
        return
    await db.delete_managed_chat(message.chat.id)
    await message.answer("This chat was removed from managed payment chats.")

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
    default_text = ui_text(
        lang,
        f"📡 *Tirgus Skaneris/AI signāli — {SCANNER_PRICE_LABEL}*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski iedos jaunu piekļuvi.",
        f"📡 *Сканер рынка/AI сигналы — {SCANNER_PRICE_LABEL}*\n\nПокупка происходит на сайте. После оплаты бот автоматически выдаст доступ.",
        f"📡 *Market Scanner/AI Signals — {SCANNER_PRICE_LABEL}*\n\nPurchase happens on the website. After payment the bot will grant access automatically.",
    )
    text = await override_text("scanner_text", lang, default_text)
    b = InlineKeyboardBuilder()
    if checkout_url:
        b.button(text=ui_text(lang, f"💳 Maksāt — {SCANNER_PRICE_LABEL}", f"💳 Оплатить — {SCANNER_PRICE_LABEL}", f"💳 Pay — {SCANNER_PRICE_LABEL}"), url=checkout_url)
    else:
        b.button(text=ui_text(lang, f"💳 Maksāt — {SCANNER_PRICE_LABEL}", f"💳 Оплатить — {SCANNER_PRICE_LABEL}", f"💳 Pay — {SCANNER_PRICE_LABEL}"), callback_data="scanner_checkout_missing")
    b.button(text=back_button_text(lang), callback_data="back_to_main")
    b.adjust(1)
    await callback.message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "scanner_checkout_missing")
async def scanner_checkout_missing(callback: CallbackQuery):
    await callback.answer("Scanner checkout links vel nav iestatits admin paneli.", show_alert=True)

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
            rows.append(f"â€¢ *{sub.get('product_name', sub.get('product_key', 'â€”'))}* â€” {expires.strftime('%d.%m.%Y')} ({days}d)")
        header = ui_text(lang, "ðŸŸ¢ *AktÄ«vÄs piekÄ¼uves:*", "ðŸŸ¢ *ÐÐºÑ‚Ð¸Ð²Ð½Ñ‹Ðµ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸:*", "ðŸŸ¢ *Active subscriptions:*")
        await message.answer(header + "\n\n" + "\n".join(rows), parse_mode="Markdown")
        return
    if not user or not user.get('expires_at'):
        await message.answer(t(lang, "status_none"), parse_mode="Markdown"); return
    expires = datetime.fromisoformat(user['expires_at'])
    if expires > datetime.utcnow():
        await message.answer(t(lang, "status_active", expires=expires.strftime('%d.%m.%Y'), days=max(0, (expires - datetime.utcnow()).days), plan=user.get('plan_name', 'â€”')), parse_mode="Markdown")
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
            "â„¹ï¸ Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "â„¹ï¸ Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "â„¹ï¸ The referral system is currently disabled.",
        )
    )

@dp.callback_query(F.data == "ref_main")
async def ref_main(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.message.edit_text(
        ui_text(
            lang,
            "â„¹ï¸ Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "â„¹ï¸ Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "â„¹ï¸ The referral system is currently disabled.",
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
            "â„¹ï¸ Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "â„¹ï¸ Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "â„¹ï¸ The referral system is currently disabled.",
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
            "â„¹ï¸ Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "â„¹ï¸ Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "â„¹ï¸ The referral system is currently disabled.",
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
        expires_dt = datetime.fromisoformat(user['expires_at']); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "â€”"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
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
            "Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "The referral system is currently disabled.",
        ),
        show_alert=True
    )
    await callback.message.edit_text(
        ui_text(
            lang,
            "â„¹ï¸ Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "â„¹ï¸ Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "â„¹ï¸ The referral system is currently disabled.",
        )
    )

@dp.callback_query(F.data.startswith("ref_apply_bonus_"))
async def ref_apply_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.answer(
        ui_text(
            lang,
            "Referral sistÄ“ma Å¡obrÄ«d ir izslÄ“gta.",
            "Referral ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°.",
            "The referral system is currently disabled.",
        ),
        show_alert=True
    )


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
                "Tev nav aktivu piekljuvju.",
                "U tebya net aktivnyh dostupov.",
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
        product_meta = await resolve_subscription_product_any(sub.get("product_key") or "", lang)
        if not product_meta and (sub.get("chat_id") or sub.get("chat_link")):
            product_meta = {
                "product_key": sub.get("product_key") or "website_subscription",
                "chat_id": sub.get("chat_id", 0) or 0,
                "chat_link": sub.get("chat_link", "") or "",
            }
        invite = await invite_text_for_product(
            user_id,
            lang,
            product_meta,
            expires_at,
            debug_source=f"get_access_links product={sub.get('product_key') or ''}",
        )
        if not invite:
            continue
        product_name = sub.get("product_name") or sub.get("product_key") or "Access"
        rows.append(
            ui_text(
                lang,
                f"📦 *{product_name}*\n📅 Aktivs lidz: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                f"📦 *{product_name}*\n📅 Aktivno do: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
                f"📦 *{product_name}*\n📅 Active until: *{expires_at.strftime('%d.%m.%Y')}*{invite}",
            )
        )

    if not rows:
        await callback.answer(
            ui_text(
                lang,
                "Neizdevas izveidot piekljuves linku.",
                "Ne udalos sozdat ssylku dostupa.",
                "Failed to create an access link.",
            ),
            show_alert=True,
        )
        return

    text = ui_text(
        lang,
        "🔗 *Tavi jaunie piekljuves linki*\n\n",
        "🔗 *Tvoi novye ssylki dostupa*\n\n",
        "🔗 *Your new access links*\n\n",
    ) + "\n\n".join(rows)
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer(
        ui_text(
            lang,
            "Jaunie linki nosutiti.",
            "Novye ssylki otpravleny.",
            "Fresh access links sent.",
        )
    )

# â”€â”€â”€ USER SETTINGS â”€â”€â”€

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


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
    # RÄda atjaunotu settings
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
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ " + ui_text(lang, "Atcelts", "Отменено", "Cancelled"))
        return
    email = (message.text or "").strip().lower()
    # VienkÄrÅ¡a validÄcija
    if "@" not in email or "." not in email or len(email) < 5:
        await message.answer("❌ " + ui_text(lang, "Nepareizs e-pasta formāts. Pamēģini vēlreiz:", "Неверный формат e-mail. Попробуй ещё:", "Invalid e-mail format. Try again:"))
        return
    if await email_claim_is_blocked(message, email, lang):
        return
    await state.clear()
    await db.set_user_email(message.from_user.id, email)
    claimed = await attach_pending_email_purchases(message.from_user.id, email, lang, message.from_user.username or "")
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "lv":
        await message.answer(f"✅ E-pasts saglabāts: *{email}*", parse_mode="Markdown")
    elif lang == "ru":
        await message.answer(f"✅ E-mail сохранён: *{email}*", parse_mode="Markdown")
    else:
        await message.answer(f"✅ E-mail saved: *{email}*", parse_mode="Markdown")


    if claimed:
        await message.answer(
            ui_text(
                lang,
                f"✅ Atrasti iepriekšēji pirkumi pēc e-pasta. Aktivizētas piekļuves: {len(claimed)}.",
                f"✅ Найдены предыдущие покупки по e-mail. Активировано доступов: {len(claimed)}.",
                f"✅ Previous purchases were found for this e-mail. Activated accesses: {len(claimed)}.",
            ),
            parse_mode="Markdown",
        )

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
        expires_dt = datetime.fromisoformat(user['expires_at']); await callback.message.edit_text(t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "â€”"), days=max(0, (expires_dt - datetime.utcnow()).days)), reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        welcome_text = await inactive_welcome_text(lang, name)
        await callback.message.edit_text(welcome_text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
    await callback.answer()


class GiveawayEmailState(StatesGroup):
    waiting_email = State()


async def _giveaway_settings():
    """NolasÄ«t giveaway settings no DB (admin var mainÄ«t)"""
    winners_raw = await db.get_setting("giveaway_winners_count")
    days_raw = await db.get_setting("giveaway_prize_days")
    winners_count = int(winners_raw) if winners_raw and winners_raw.isdigit() else 1
    prize_days = int(days_raw) if days_raw and days_raw.isdigit() else 14
    return winners_count, prize_days


@dp.callback_query(F.data == "giveaway_join")
async def giveaway_join(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    await callback.answer(
        ui_text(
            lang,
            "Giveaway paÅ¡laik ir izslÄ“gts.",
            "Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ ÑÐµÐ¹Ñ‡Ð°Ñ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡Ñ‘Ð½.",
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

    # PÄ€RBAUDE: aktÄ«vs abonements
    has_active = user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > now
    if not has_active:
        if lang == "ru":
            text = (
                "ðŸŽŸ *Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ Ð¼ÐµÑÑÑ†Ð°*\n\n"
                "âš ï¸ Ð”Ð»Ñ ÑƒÑ‡Ð°ÑÑ‚Ð¸Ñ Ð² Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ Ð½ÐµÐ¾Ð±Ñ…Ð¾Ð´Ð¸Ð¼Ð° *Ð°ÐºÑ‚Ð¸Ð²Ð½Ð°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ°*.\n\n"
                f"ðŸ† ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð° Ðº Ñ‡Ð°Ñ‚Ñƒ!\n\n"
                "ðŸ“‹ ÐžÑ„Ð¾Ñ€Ð¼Ð¸ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑƒ Ð¸ Ð²Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°Ð¹ÑÑ!"
            )
        elif lang == "lv":
            text = (
                "ðŸŽŸ *MÄ“neÅ¡a izloze*\n\n"
                "âš ï¸ Lai piedalÄ«tos izlozÄ“, nepiecieÅ¡ams *aktÄ«vs abonements*.\n\n"
                f"ðŸ† Balva: *+{prize_days} dienas* bezmaksas piekÄ¼uvei Äatam!\n\n"
                "ðŸ“‹ NoformÄ“ abonementu un atgriezies!"
            )
        else:
            text = (
                "ðŸŽŸ *Monthly Giveaway*\n\n"
                "âš ï¸ An *active subscription* is required to participate.\n\n"
                f"ðŸ† Prize: *+{prize_days} days* of free chat access!\n\n"
                "ðŸ“‹ Subscribe and come back!"
            )
        b = InlineKeyboardBuilder()
        b.button(text=back_button_text(lang), callback_data="settings_back")
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
        await callback.answer()
        return

    # Ja nav e-pasta â€” obligÄti jÄnorÄda
    if not email:
        if lang == "ru":
            text = (
                "ðŸŽŸ *Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ Ð¼ÐµÑÑÑ†Ð°*\n\n"
                f"ÐšÐ°Ð¶Ð´Ñ‹Ð¹ Ð¼ÐµÑÑÑ† ÑÑ€ÐµÐ´Ð¸ Ð¿Ð¾Ð´Ð¿Ð¸ÑÑ‡Ð¸ÐºÐ¾Ð² Ñ€Ð°Ð·Ñ‹Ð³Ñ€Ñ‹Ð²Ð°ÐµÑ‚ÑÑ *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°!\n\n"
                "âš ï¸ Ð”Ð»Ñ ÑƒÑ‡Ð°ÑÑ‚Ð¸Ñ Ð½ÑƒÐ¶Ð½Ð¾ ÑƒÐºÐ°Ð·Ð°Ñ‚ÑŒ *e-mail*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "ðŸ“§ _ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ ÑÐ²Ð¾Ð¹ e-mail ÑÐ¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸ÐµÐ¼:_\n"
                "/cancel Ð´Ð»Ñ Ð¾Ñ‚Ð¼ÐµÐ½Ñ‹"
            )
        elif lang == "lv":
            text = (
                "ðŸŽŸ *MÄ“neÅ¡a izloze*\n\n"
                f"Katru mÄ“nesi abonenti var laimÄ“t *+{prize_days} dienas* bezmaksas piekÄ¼uvi!\n\n"
                "âš ï¸ Lai piedalÄ«tos, jÄnorÄda *e-pasts*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "ðŸ“§ _AtsÅ«ti savu e-pastu ziÅ†Ä:_\n"
                "/cancel lai atceltu"
            )
        else:
            text = (
                "ðŸŽŸ *Monthly Giveaway*\n\n"
                f"Every month subscribers can win *+{prize_days} days* of free access!\n\n"
                "âš ï¸ To participate you need to provide your *e-mail*.\n\n"
                f"{email_binding_notice(lang)}\n\n"
                "ðŸ“§ _Send your e-mail as a message:_\n"
                "/cancel to cancel"
            )
        await state.set_state(GiveawayEmailState.waiting_email)
        await state.update_data(giveaway_month=current_month)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return

    # PÄrbaudÄm vai jau pieteicies Å¡omÄ“nes
    already = await db.is_giveaway_entered(user_id, current_month)
    if already:
        count = await db.get_giveaway_count(current_month)
        if lang == "ru":
            text = (
                "ðŸŽŸ *Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ Ð¼ÐµÑÑÑ†Ð°*\n\n"
                "âœ… Ð¢Ñ‹ ÑƒÐ¶Ðµ ÑƒÑ‡Ð°ÑÑ‚Ð²ÑƒÐµÑˆÑŒ Ð² Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ ÑÑ‚Ð¾Ð³Ð¾ Ð¼ÐµÑÑÑ†Ð°!\n\n"
                f"ðŸ‘¥ Ð£Ñ‡Ð°ÑÑ‚Ð½Ð¸ÐºÐ¾Ð²: *{count}*\n"
                "ðŸ“… Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ: *1 Ñ‡Ð¸ÑÐ»Ð° ÑÐ»ÐµÐ´ÑƒÑŽÑ‰ÐµÐ³Ð¾ Ð¼ÐµÑÑÑ†Ð°*\n"
                f"ðŸ† ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°\n\n"
                "ðŸ€ Ð£Ð´Ð°Ñ‡Ð¸!"
            )
        elif lang == "lv":
            text = (
                "ðŸŽŸ *MÄ“neÅ¡a izloze*\n\n"
                "âœ… Tu jau piedalies Å¡Ä« mÄ“neÅ¡a izlozÄ“!\n\n"
                f"ðŸ‘¥ DalÄ«bnieki: *{count}*\n"
                "ðŸ“… Izloze: *nÄkamÄ mÄ“neÅ¡a 1. datumÄ*\n"
                f"ðŸ† Balva: *+{prize_days} dienas* bezmaksas piekÄ¼uvei\n\n"
                "ðŸ€ Lai veicas!"
            )
        else:
            text = (
                "ðŸŽŸ *Monthly Giveaway*\n\n"
                "âœ… You're already entered for this month!\n\n"
                f"ðŸ‘¥ Participants: *{count}*\n"
                "ðŸ“… Drawing: *1st of next month*\n"
                f"ðŸ† Prize: *+{prize_days} days* free access\n\n"
                "ðŸ€ Good luck!"
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
            "ðŸŽŸ *Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ Ð¼ÐµÑÑÑ†Ð°*\n\n"
            "ðŸŽ‰ *Ð¢Ñ‹ ÑƒÑÐ¿ÐµÑˆÐ½Ð¾ Ð·Ð°Ñ€ÐµÐ³Ð¸ÑÑ‚Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½!*\n\n"
            f"ðŸ‘¥ Ð£Ñ‡Ð°ÑÑ‚Ð½Ð¸ÐºÐ¾Ð²: *{count}*\n"
            "ðŸ“… Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ: *1 Ñ‡Ð¸ÑÐ»Ð° ÑÐ»ÐµÐ´ÑƒÑŽÑ‰ÐµÐ³Ð¾ Ð¼ÐµÑÑÑ†Ð°*\n"
            f"ðŸ† ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°\n\n"
            "ðŸ€ Ð£Ð´Ð°Ñ‡Ð¸!"
        )
    elif lang == "lv":
        text = (
            "ðŸŽŸ *MÄ“neÅ¡a izloze*\n\n"
            "ðŸŽ‰ *Tu esi veiksmÄ«gi reÄ£istrÄ“ts!*\n\n"
            f"ðŸ‘¥ DalÄ«bnieki: *{count}*\n"
            "ðŸ“… Izloze: *nÄkamÄ mÄ“neÅ¡a 1. datumÄ*\n"
            f"ðŸ† Balva: *+{prize_days} dienas* bezmaksas piekÄ¼uvei\n\n"
            "ðŸ€ Lai veicas!"
        )
    else:
        text = (
            "ðŸŽŸ *Monthly Giveaway*\n\n"
            "ðŸŽ‰ *You're registered!*\n\n"
            f"ðŸ‘¥ Participants: *{count}*\n"
            "ðŸ“… Drawing: *1st of next month*\n"
            f"ðŸ† Prize: *+{prize_days} days* free access\n\n"
            "ðŸ€ Good luck!"
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
        await message.answer("âŒ " + ui_text(lang, "Atcelts", "ÐžÑ‚Ð¼ÐµÐ½ÐµÐ½Ð¾", "Cancelled"))
        return
    email = (message.text or "").strip().lower()
    if "@" not in email or "." not in email or len(email) < 5:
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("âŒ " + ui_text(lang, "Nepareizs e-pasta formÄts. PamÄ“Ä£ini vÄ“lreiz:", "ÐÐµÐ²ÐµÑ€Ð½Ñ‹Ð¹ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚ e-mail. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹ ÐµÑ‰Ñ‘:", "Invalid e-mail format. Try again:"))
        return
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if await email_claim_is_blocked(message, email, lang):
        return

    data = await state.get_data()
    month = data.get("giveaway_month", datetime.utcnow().strftime("%Y-%m"))
    await state.clear()

    user_id = message.from_user.id
    await db.set_user_email(user_id, email)
    await attach_pending_email_purchases(user_id, email, lang, message.from_user.username or "")
    await db.enter_giveaway(user_id, month)
    count = await db.get_giveaway_count(month)
    _, prize_days = await _giveaway_settings()

    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    if lang == "ru":
        text = (
            f"âœ… E-mail ÑÐ¾Ñ…Ñ€Ð°Ð½Ñ‘Ð½: *{email}*\n\n"
            "ðŸŽŸ *Ð¢Ñ‹ Ð·Ð°Ñ€ÐµÐ³Ð¸ÑÑ‚Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½ Ð² Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ!*\n\n"
            f"ðŸ‘¥ Ð£Ñ‡Ð°ÑÑ‚Ð½Ð¸ÐºÐ¾Ð²: *{count}*\n"
            "ðŸ“… Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ: *1 Ñ‡Ð¸ÑÐ»Ð° ÑÐ»ÐµÐ´ÑƒÑŽÑ‰ÐµÐ³Ð¾ Ð¼ÐµÑÑÑ†Ð°*\n"
            f"ðŸ† ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°\n\n"
            "ðŸ€ Ð£Ð´Ð°Ñ‡Ð¸!"
        )
    elif lang == "lv":
        text = (
            f"âœ… E-pasts saglabÄts: *{email}*\n\n"
            "ðŸŽŸ *Tu esi reÄ£istrÄ“ts izlozei!*\n\n"
            f"ðŸ‘¥ DalÄ«bnieki: *{count}*\n"
            "ðŸ“… Izloze: *nÄkamÄ mÄ“neÅ¡a 1. datumÄ*\n"
            f"ðŸ† Balva: *+{prize_days} dienas* bezmaksas piekÄ¼uvei\n\n"
            "ðŸ€ Lai veicas!"
        )
    else:
        text = (
            f"âœ… E-mail saved: *{email}*\n\n"
            "ðŸŽŸ *You're registered for the giveaway!*\n\n"
            f"ðŸ‘¥ Participants: *{count}*\n"
            "ðŸ“… Drawing: *1st of next month*\n"
            f"ðŸ† Prize: *+{prize_days} days* free access\n\n"
            "ðŸ€ Good luck!"
        )
    await message.answer(text, parse_mode="Markdown")


# â”€â”€â”€ PROMO CODE (USER) â”€â”€â”€


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
        text = "ðŸŽŸ *Ð’Ð²ÐµÐ´Ð¸ Ð¿Ñ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´:*\n\n/cancel Ð´Ð»Ñ Ð¾Ñ‚Ð¼ÐµÐ½Ñ‹"
    elif lang == "lv":
        text = "ðŸŽŸ *Ievadi promokodu:*\n\n/cancel lai atceltu"
    else:
        text = "ðŸŽŸ *Enter promo code:*\n\n/cancel to cancel"
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@dp.message(PromoCodeState.waiting_code)
async def promo_apply(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("âŒ " + ui_text(lang, "Atcelts", "ÐžÑ‚Ð¼ÐµÐ½ÐµÐ½Ð¾", "Cancelled"))
        return

    code = message.text.strip().upper()
    data = await state.get_data()
    target = data.get("promo_target", "")
    await state.clear()

    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    user_id = message.from_user.id

    # PÄrbaudÄ«t kodu DB
    promo = await db.get_promo_code(code)
    if not promo:
        await message.answer("âŒ " + ui_text(lang, "Promokods nav atrasts.", "ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½.", "Promo code not found."))
        return

    # PÄrbaudÄ«t derÄ«gumu
    if promo.get("max_uses") and promo.get("max_uses") > 0 and promo.get("used_count", 0) >= promo["max_uses"]:
        await message.answer("âŒ " + ui_text(lang, "Promokods ir izlietots.", "ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ð¸ÑÑ‡ÐµÑ€Ð¿Ð°Ð½.", "Promo code exhausted."))
        return

    if promo.get("expires_at"):
        try:
            exp = datetime.fromisoformat(promo["expires_at"])
            if exp < datetime.utcnow():
                await message.answer("âŒ " + ui_text(lang, "Promokodam beidzies termiÅ†Å¡.", "ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ð¸ÑÑ‚Ñ‘Ðº.", "Promo code expired."))
                return
        except: pass

    # PÄrbaudÄ«t vai promo attiecas uz Å¡o plÄnu/kursu
    promo_plan = promo.get("plan_key")
    is_course = target.startswith("course_")

    if promo_plan:
        # None = visiem, "all_courses" = visiem kursiem
        if promo_plan == "all_courses":
            if not is_course:
                await message.answer("âŒ " + ui_text(lang, "Promokods der tikai kursiem.", "ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð´Ð»Ñ ÐºÑƒÑ€ÑÐ¾Ð².", "Promo code is for courses only."))
                return
        elif promo_plan != target:
            await message.answer("âŒ " + ui_text(lang, "Promokods neder Å¡im produktam.", "ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ð½Ðµ Ð¿Ð¾Ð´Ñ…Ð¾Ð´Ð¸Ñ‚ Ð´Ð»Ñ ÑÑ‚Ð¾Ð³Ð¾ Ð¿Ñ€Ð¾Ð´ÑƒÐºÑ‚Ð°.", "Promo code not valid for this product."))
            return

    discount = promo.get("discount_percent", 0)

    # Noteikt cenu
    if is_course:
        ckey = target.replace("course_", "")
        item = config.COURSES.get(ckey)
        if not item: await message.answer("âŒ"); return
        saved = await db.get_setting(f"course_price_{ckey}")
        base_price = float(saved) if saved else item['price_usdt']
    else:
        pkey = target.replace("plan_", "") if target.startswith("plan_") else target
        item = config.PLANS.get(pkey)
        if not item: await message.answer("âŒ"); return
        saved = await db.get_setting(f"price_{pkey}")
        base_price = float(saved) if saved else item['price_usdt']

    # PiemÄ“rot atlaidi
    discounted = round(base_price * (1 - discount / 100), 2)
    unique_amount = await _get_unique_amount(target, user_id, discounted)

    if is_course:
        await db.set_pending_payment(user_id, target, unique_amount)
    else:
        pkey = target.replace("plan_", "") if target.startswith("plan_") else target
        await db.set_pending_payment(user_id, pkey, unique_amount)

    # AtzÄ«mÄ“ kÄ aktÄ«vu lietotÄja promokodu; izlietojam tikai pÄ“c veiksmÄ«ga pirkuma
    await db.apply_promo_to_user(user_id, code)

    name = item['name'][lang] if isinstance(item['name'], dict) else item['name']
    if lang == "ru":
        text = (
            f"ðŸŽŸ *ÐŸÑ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ `{code}` Ð¿Ñ€Ð¸Ð¼ÐµÐ½Ñ‘Ð½!*\n\n"
            f"{'ðŸ“š ÐšÑƒÑ€Ñ' if is_course else 'ðŸ“‹ Ð¢Ð°Ñ€Ð¸Ñ„'}: *{name}*\n"
            f"ðŸ’° Ð¦ÐµÐ½Ð°: ~{base_price}~ â†’ *{unique_amount} USDT* (-{discount}%)\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ *{unique_amount} USDT (BEP-20)* Ð½Ð°:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"âš ï¸ Ð¢Ð¾Ð»ÑŒÐºÐ¾ *USDT BEP-20* (BSC)"
        )
    else:
        text = (
            f"ðŸŽŸ *Promo code `{code}` applied!*\n\n"
            f"{'ðŸ“š Course' if is_course else 'ðŸ“‹ Plan'}: *{name}*\n"
            f"ðŸ’° Price: ~{base_price}~ â†’ *{unique_amount} USDT* (-{discount}%)\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"âš ï¸ Only *USDT BEP-20* (BSC)"
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


# â”€â”€â”€ COURSES â”€â”€â”€

class CourseEmailState(StatesGroup):
    waiting_email = State()


def _format_eur_price(value):
    value = float(value)
    return f"{value:.0f} EUR" if value == int(value) else f"{value} EUR"


def _course_ui_lang(lang):
    if lang == "ru":
        return "ru"
    if lang == "en":
        return "en"
    return "lv"


@dp.callback_query(F.data == "courses_menu")
async def courses_menu(callback: CallbackQuery):
    """Kursu izvÄ“lne - uzreiz rÄda kursus"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    
    if ui_lang == "lv":
        default_text = (
            "📚 *MNtradepro kursi*\n\n"
            "Izvēlies kursu, lai apskatītu detaļas un apmaksas iespējas:"
        )
    elif ui_lang == "ru":
        default_text = (
            "📚 *Курсы MNtradepro*\n\n"
            "Выбери курс, чтобы посмотреть детали и способы оплаты:"
        )
    else:
        default_text = (
            "📚 *MNtradepro Courses*\n\n"
            "Choose a course to see details and payment options:"
        )
    text = await override_text("courses_text", ui_lang, default_text)
    
    b = InlineKeyboardBuilder()
    # RÄdÄm visus kursus
    for key, course in config.COURSES.items():
        price_str = course['price_usd']
        name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
        b.button(text=f"{course['emoji']} {name} — {price_str}", callback_data=f"course_info_{key}")
    
    b.button(text=back_button_text(ui_lang), callback_data="settings_back")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("course_info_"))
async def course_info_menu(callback: CallbackQuery):
    """Show course info and let the user choose the course language."""
    course_key = callback.data.replace("course_info_", "")
    course = config.COURSES.get(course_key)
    if not course:
        await callback.answer("âŒ")
        return
    
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    
    price = course['price_usdt']
    price_str = _format_eur_price(price)
    
    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    
    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Cena: *{price_str}*\n\n"
            "📖 Detalizēts kursa apraksts un programma ir pieejama MNtradepro mājaslapā.\n\n"
            "Izvēlies kursa valodu:"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Цена: *{price_str}*\n\n"
            "📖 Подробное описание курса и программу можно посмотреть на сайте MNtradepro.\n\n"
            "Выбери язык курса:"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Price: *{price_str}*\n\n"
            "📖 Detailed course description and curriculum "
            "available on MNtradepro website.\n\n"
            "Choose the course language:"
        )
    
    b = InlineKeyboardBuilder()
    b.button(text="🇱🇻 Latviešu", callback_data=f"course_lang_{course_key}_lv")
    b.button(text="🇬🇧 English", callback_data=f"course_lang_{course_key}_en")
    b.button(text="🇷🇺 Русский", callback_data=f"course_lang_{course_key}_ru")
    b.button(text=back_button_text(ui_lang), callback_data="courses_menu")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("course_lang_"))
async def course_language_selected(callback: CallbackQuery):
    payload = callback.data.replace("course_lang_", "")
    try:
        course_key, course_lang = payload.rsplit("_", 1)
    except ValueError:
        await callback.answer("❌", show_alert=True)
        return
    course = config.COURSES.get(course_key)
    if not course or course_lang not in ("lv", "en", "ru"):
        await callback.answer("❌", show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    price = course['price_usdt']
    price_str = _format_eur_price(price)
    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    selected_lang_label = {"lv": "🇱🇻 Latviešu", "en": "🇬🇧 English", "ru": "🇷🇺 Русский"}[course_lang]

    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Cena: *{price_str}*\n"
            f"🌐 Kursa valoda: *{selected_lang_label}*\n\n"
            "Izmanto checkout pogu zemāk:"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Цена: *{price_str}*\n"
            f"🌐 Язык курса: *{selected_lang_label}*\n\n"
            "Используй checkout-кнопку ниже:"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"💰 Price: *{price_str}*\n"
            f"🌐 Course language: *{selected_lang_label}*\n\n"
            "Use the checkout button below:"
        )

    checkout_url = await checkout_url_for_course(course_key, course_lang)
    b = InlineKeyboardBuilder()
    checkout_btn = ui_text(
        ui_lang,
        "💳 Maksāt ar karti / banku / crypto",
        "💳 Оплатить картой / банком / crypto",
        "💳 Pay with card / bank / crypto",
    )
    if checkout_url:
        b.button(text=checkout_btn, url=checkout_url)
    else:
        b.button(text=checkout_btn, callback_data=f"course_checkout_missing_{course_key}_{course_lang}")
    b.button(text=back_button_text(ui_lang), callback_data=f"course_info_{course_key}")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("course_checkout_missing_"))
async def course_checkout_missing(callback: CallbackQuery):
    payload = callback.data.replace("course_checkout_missing_", "")
    try:
        course_key, course_lang = payload.rsplit("_", 1)
    except ValueError:
        course_key, course_lang = payload, ""
    lang_name = {"lv": "Latvian", "en": "English", "ru": "Russian"}.get(course_lang, "selected")
    await callback.answer(f"Checkout URL for this course language is not set in admin panel yet ({course_key} / {lang_name}).", show_alert=True)


@dp.callback_query(F.data.startswith("course_crypto_"))
async def course_crypto_selected(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    await callback.answer(
        ui_text(
            lang,
            "Kursu crypto apmaksa botÄ vairs netiek izmantota. Izmanto kursa checkout pogu.",
            "Crypto-Ð¾Ð¿Ð»Ð°Ñ‚Ð° ÐºÑƒÑ€ÑÐ¾Ð² Ð² Ð±Ð¾Ñ‚Ðµ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½Ðµ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ÑÑ. Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ checkout-ÐºÐ½Ð¾Ð¿ÐºÑƒ ÐºÑƒÑ€ÑÐ°.",
            "Course crypto payment inside the bot is no longer used. Please use the course checkout button.",
        ),
        show_alert=True,
    )
    return
    """User izvÄ“lÄ“jÄs crypto payment konkrÄ“tam kursam"""
    course_key = callback.data.replace("course_crypto_", "")
    course = config.COURSES.get(course_key)
    if not course:
        await callback.answer("âŒ")
        return
    
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""
    
    # PÄrbauda email
    if not email:
        if ui_lang == "lv":
            text = (
                "ðŸ“š *Kursa iegÄde*\n\n"
                "âš ï¸ Kursa iegÄdei nepiecieÅ¡ams *e-pasts* â€” tas tiks izmantots kÄ tavs piekÄ¼uves e-pasts.\n\n"
                "ðŸ“§ _AtsÅ«ti savu e-pastu:_\n/cancel lai atceltu"
            )
        elif ui_lang == "ru":
            text = (
                "ðŸ“š *ÐŸÐ¾ÐºÑƒÐ¿ÐºÐ° ÐºÑƒÑ€ÑÐ°*\n\n"
                "âš ï¸ Ð”Ð»Ñ Ð¿Ð¾ÐºÑƒÐ¿ÐºÐ¸ ÐºÑƒÑ€ÑÐ° Ð½ÐµÐ¾Ð±Ñ…Ð¾Ð´Ð¸Ð¼Ð¾ ÑƒÐºÐ°Ð·Ð°Ñ‚ÑŒ *e-mail* â€” "
                "Ð¾Ð½ Ð±ÑƒÐ´ÐµÑ‚ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½ ÐºÐ°Ðº Ð»Ð¾Ð³Ð¸Ð½ Ð² Ð¾Ð±ÑƒÑ‡Ð°ÑŽÑ‰ÐµÐ¹ Ð¿Ð»Ð°Ñ‚Ñ„Ð¾Ñ€Ð¼Ðµ.\n\n"
                "ðŸ“§ _ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ ÑÐ²Ð¾Ð¹ e-mail:_\n/cancel Ð´Ð»Ñ Ð¾Ñ‚Ð¼ÐµÐ½Ñ‹"
            )
        else:
            text = (
                "ðŸ“š *Course Purchase*\n\n"
                "âš ï¸ An *e-mail* is required to purchase a course â€” "
                "it will be used as your login for the learning platform.\n\n"
                "ðŸ“§ _Send your e-mail:_\n/cancel to cancel"
            )
        await state.set_state(CourseEmailState.waiting_email)
        await state.update_data(selected_course=course_key)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return
    
    # Ir email - rÄdÄm payment
    await _show_course_payment(callback, course_key, email, lang)


async def _show_course_payment(callback, course_key, email, lang):
    """RÄda crypto payment info konkrÄ“tam kursam"""
    course = config.COURSES.get(course_key)
    if not course:
        return
    ui_lang = _course_ui_lang(lang)
    
    user_id = callback.from_user.id
    
    # Cena
    saved_price = await db.get_setting(f"course_price_{course_key}")
    base_price = float(saved_price) if saved_price else course['price_usdt']
    
    # FIX: Ja jau ir pending ar Å¡o kursu â€” reuse
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
            f"ðŸ’° Cena: *{unique_amount} USDT*\n"
            f"ðŸ“§ E-pasts: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ NosÅ«ti *{unique_amount} USDT (BEP-20)* uz:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Tikai *USDT BEP-20* (BSC tÄ«kls)\n"
            f"PÄ“c apmaksas nospied pogu zemÄk"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"ðŸ’° Ð¦ÐµÐ½Ð°: *{unique_amount} USDT*\n"
            f"ðŸ“§ Ð›Ð¾Ð³Ð¸Ð½: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ *{unique_amount} USDT (BEP-20)* Ð½Ð°:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Ð¢Ð¾Ð»ÑŒÐºÐ¾ *USDT BEP-20* (ÑÐµÑ‚ÑŒ BSC)\n"
            f"ÐŸÐ¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ Ð½Ð°Ð¶Ð¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑƒ Ð½Ð¸Ð¶Ðµ"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"ðŸ’° Price: *{unique_amount} USDT*\n"
            f"ðŸ“§ Login: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Only *USDT BEP-20* (BSC network)\n"
            f"After payment press the button below"
        )
    
    b = InlineKeyboardBuilder()
    b.button(text="âœ… " + ("Esmu apmaksÄjis" if ui_lang == "lv" else "Ð¯ Ð¾Ð¿Ð»Ð°Ñ‚Ð¸Ð»"), callback_data=f"check_course_{course_key}")
    b.button(text="ðŸ”™ " + ("AtpakaÄ¼" if ui_lang == "lv" else "ÐÐ°Ð·Ð°Ð´"), callback_data=f"course_info_{course_key}")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "courses_crypto")
async def courses_crypto(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""

    # E-pasts obligÄts kursiem
    if not email:
        if ui_lang == "lv":
            text = (
                "ðŸ“š *Kursa iegÄde*\n\n"
                "âš ï¸ Kursa iegÄdei nepiecieÅ¡ams *e-pasts* â€” tas tiks izmantots kÄ tavs piekÄ¼uves e-pasts.\n\n"
                "ðŸ“§ _AtsÅ«ti savu e-pastu:_\n/cancel lai atceltu"
            )
        elif ui_lang == "ru":
            text = (
                "ðŸ“š *ÐŸÐ¾ÐºÑƒÐ¿ÐºÐ° ÐºÑƒÑ€ÑÐ°*\n\n"
                "âš ï¸ Ð”Ð»Ñ Ð¿Ð¾ÐºÑƒÐ¿ÐºÐ¸ ÐºÑƒÑ€ÑÐ° Ð½ÐµÐ¾Ð±Ñ…Ð¾Ð´Ð¸Ð¼Ð¾ ÑƒÐºÐ°Ð·Ð°Ñ‚ÑŒ *e-mail* â€” "
                "Ð¾Ð½ Ð±ÑƒÐ´ÐµÑ‚ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½ ÐºÐ°Ðº Ð»Ð¾Ð³Ð¸Ð½ Ð² Ð¾Ð±ÑƒÑ‡Ð°ÑŽÑ‰ÐµÐ¹ Ð¿Ð»Ð°Ñ‚Ñ„Ð¾Ñ€Ð¼Ðµ.\n\n"
                "ðŸ“§ _ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ ÑÐ²Ð¾Ð¹ e-mail:_\n/cancel Ð´Ð»Ñ Ð¾Ñ‚Ð¼ÐµÐ½Ñ‹"
            )
        else:
            text = (
                "ðŸ“š *Course Purchase*\n\n"
                "âš ï¸ An *e-mail* is required to purchase a course â€” "
                "it will be used as your login for the learning platform.\n\n"
                "ðŸ“§ _Send your e-mail:_\n/cancel to cancel"
            )
        await state.set_state(CourseEmailState.waiting_email)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return

    # Ir e-pasts â€” rÄdÄm kursu izvÄ“lni
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
        text = "ðŸ“š *IzvÄ“lies kursu:*"
    elif ui_lang == "ru":
        text = "ðŸ“š *Ð’Ñ‹Ð±ÐµÑ€Ð¸ ÐºÑƒÑ€Ñ:*"
    else:
        text = "ðŸ“š *Choose a course:*"
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
        b.button(text=f"{course['emoji']} {name} â€” {price_str}", callback_data=f"course_{key}")
    b.button(text="ðŸ”™ " + ("AtpakaÄ¼" if ui_lang == "lv" else "ÐÐ°Ð·Ð°Ð´"), callback_data="courses_menu")
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
            "Kursu pirkumi tagad notiek tikai caur mÄjaslapas checkout. E-pastu vari mainÄ«t iestatÄ«jumos.",
            "ÐŸÐ¾ÐºÑƒÐ¿ÐºÐ¸ ÐºÑƒÑ€ÑÐ¾Ð² Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÑŽÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ‡ÐµÑ€ÐµÐ· checkout Ð½Ð° ÑÐ°Ð¹Ñ‚Ðµ. E-mail Ð¼Ð¾Ð¶Ð½Ð¾ Ð¼ÐµÐ½ÑÑ‚ÑŒ Ð² Ð½Ð°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ°Ñ….",
            "Course purchases now work only through website checkout. You can still change your e-mail in settings.",
        )
    )
    return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("âŒ")
        return
    
    email = (message.text or "").strip().lower()
    if "@" not in email or "." not in email or len(email) < 5:
        user = await db.get_user(message.from_user.id)
        lang = user.get("lang", "ru") if user else "ru"
        await message.answer("âŒ " + ("Nepareizs e-pasts. PamÄ“Ä£ini vÄ“lreiz:" if lang == "lv" else ("ÐÐµÐ²ÐµÑ€Ð½Ñ‹Ð¹ e-mail. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹:" if lang == "ru" else "Invalid e-mail. Try:")))
        return
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if await email_claim_is_blocked(message, email, lang):
        return
    
    data = await state.get_data()
    selected_course = data.get("selected_course")
    await state.clear()
    
    await db.set_user_email(message.from_user.id, email)
    await attach_pending_email_purchases(message.from_user.id, email, lang, message.from_user.username or "")
    user = await db.get_user(message.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    
    if lang == "lv":
        confirm_text = f"âœ… E-pasts saglabÄts: *{email}*"
    elif lang == "ru":
        confirm_text = f"âœ… E-mail ÑÐ¾Ñ…Ñ€Ð°Ð½Ñ‘Ð½: *{email}*"
    else:
        confirm_text = f"âœ… E-mail saved: *{email}*"
    
    await message.answer(confirm_text, parse_mode="Markdown")
    
    # Ja ir izvÄ“lÄ“ts kurss, rÄdÄm payment
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
            "Å Ä« vecÄ kursa apmaksas poga vairs netiek izmantota. Atver kursu no jaunÄs izvÄ“lnes un izmanto checkout.",
            "Ð­Ñ‚Ð° ÑÑ‚Ð°Ñ€Ð°Ñ ÐºÐ½Ð¾Ð¿ÐºÐ° Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ ÐºÑƒÑ€ÑÐ° Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½Ðµ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ÑÑ. ÐžÑ‚ÐºÑ€Ð¾Ð¹ ÐºÑƒÑ€Ñ Ð¸Ð· Ð½Ð¾Ð²Ð¾Ð³Ð¾ Ð¼ÐµÐ½ÑŽ Ð¸ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ checkout.",
            "This old course payment button is no longer used. Open the course from the new menu and use checkout.",
        ),
        show_alert=True,
    )
    return
    course_key = callback.data.replace("course_", "")
    course = config.COURSES.get(course_key)
    if not course: await callback.answer("âŒ"); return

    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else ""

    if not email:
        await callback.answer("âš ï¸ NepiecieÅ¡ams e-pasts!" if ui_lang == "lv" else "âš ï¸ ÐÑƒÐ¶ÐµÐ½ e-mail!", show_alert=True)
        return

    # Cena no DB
    saved_price = await db.get_setting(f"course_price_{course_key}")
    base_price = float(saved_price) if saved_price else course['price_usdt']

    # UnikÄla summa (slot sistÄ“ma)
    unique_amount = await _get_unique_amount(f"course_{course_key}", user_id, base_price)
    await db.set_pending_payment(user_id, f"course_{course_key}", unique_amount)

    name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
    if ui_lang == "lv":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"ðŸ’° Cena: *{unique_amount} USDT*\n"
            f"ðŸ“§ E-pasts: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ NosÅ«ti *{unique_amount} USDT (BEP-20)* uz:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Tikai *USDT BEP-20* (BSC tÄ«kls)\n"
            f"PÄ“c apmaksas nospied pogu zemÄk"
        )
    elif ui_lang == "ru":
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"ðŸ’° Ð¦ÐµÐ½Ð°: *{unique_amount} USDT*\n"
            f"ðŸ“§ Ð›Ð¾Ð³Ð¸Ð½: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ ÐžÑ‚Ð¿Ñ€Ð°Ð²ÑŒ *{unique_amount} USDT (BEP-20)* Ð½Ð°:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Ð¢Ð¾Ð»ÑŒÐºÐ¾ *USDT BEP-20* (ÑÐµÑ‚ÑŒ BSC)\n"
            f"ÐŸÐ¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ Ð½Ð°Ð¶Ð¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑƒ Ð½Ð¸Ð¶Ðµ"
        )
    else:
        text = (
            f"{course['emoji']} *{name}*\n\n"
            f"ðŸ’° Price: *{unique_amount} USDT*\n"
            f"ðŸ“§ Login: *{email}*\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ“¤ Send *{unique_amount} USDT (BEP-20)* to:\n\n"
            f"`{config.CRYPTO_WALLET}`\n\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"âš ï¸ Only *USDT BEP-20* (BSC network)\n"
            f"After payment press the button below"
        )
    b = InlineKeyboardBuilder()
    b.button(text="âœ… " + ("Esmu apmaksÄjis" if ui_lang == "lv" else "Ð¯ Ð¾Ð¿Ð»Ð°Ñ‚Ð¸Ð»"), callback_data=f"check_course_{course_key}")
    b.button(text="ðŸ”™ " + ("AtpakaÄ¼" if ui_lang == "lv" else "ÐÐ°Ð·Ð°Ð´"), callback_data="courses_crypto")
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
            "VecÄ kursa maksÄjuma pÄrbaude ir izÅ†emta. Kursu pirkumi tagad nÄk tikai no mÄjaslapas webhook.",
            "Ð¡Ñ‚Ð°Ñ€Ð°Ñ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ° Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ ÐºÑƒÑ€ÑÐ° ÑƒÐ´Ð°Ð»ÐµÐ½Ð°. ÐŸÐ¾ÐºÑƒÐ¿ÐºÐ¸ ÐºÑƒÑ€ÑÐ¾Ð² Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¿Ñ€Ð¸Ñ…Ð¾Ð´ÑÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ‡ÐµÑ€ÐµÐ· webhook ÑÐ°Ð¹Ñ‚Ð°.",
            "The old course payment check has been removed. Course purchases now arrive only through the website webhook.",
        ),
        show_alert=True,
    )
    return
    course_key = callback.data.replace("check_course_", "")
    course = config.COURSES.get(course_key)
    if not course: await callback.answer("âŒ"); return

    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    ui_lang = _course_ui_lang(lang)
    email = user.get("email", "") if user else "?"
    username = callback.from_user.username or ""

    pending = await db.get_pending_payment(user_id)
    if not pending or not pending.get("amount_usdt"):
        await callback.answer(ui_text(lang, "âš ï¸ Nav gaidoÅ¡a maksÄjuma", "âš ï¸ ÐÐµÑ‚ Ð¾Ð¶Ð¸Ð´Ð°ÑŽÑ‰ÐµÐ³Ð¾ Ð¿Ð»Ð°Ñ‚ÐµÐ¶Ð°", "âš ï¸ No pending payment"), show_alert=True); return
    expected = float(pending["amount_usdt"])

    await callback.answer("â³...")
    msg = await callback.message.edit_text("â³ *" + ui_text(lang, "PÄrbaudu...", "ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÑŽ...", "Checking...") + "*", parse_mode="Markdown")

    tx = await check_payment(config.CRYPTO_WALLET, expected, user_id)
    if tx:
        name = course['name'][ui_lang] if isinstance(course['name'], dict) else course['name']
        name_ru = course['name']['ru'] if isinstance(course['name'], dict) else course['name']
        await db.delete_pending_payment(user_id)

        # SaglabÄt pirkumu UN iegÅ«t purchase_id
        purchase_id = await db.add_course_purchase(user_id, username, course_key, name_ru, expected, tx, email)
        active_promo_code = await db.get_user_active_promo(user_id)
        if active_promo_code:
            await db.use_promo_code(active_promo_code)
            await db.clear_user_promo(user_id)

        ref = await db.get_referral_by_referred(user_id)
        if ref and False:
            pass
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

        if lang == "ru":
            text = (
                f"âœ… *ÐžÐ¿Ð»Ð°Ñ‚Ð° Ð¿Ð¾Ð´Ñ‚Ð²ÐµÑ€Ð¶Ð´ÐµÐ½Ð°!*\n\n"
                f"ðŸ“š ÐšÑƒÑ€Ñ: *{name}*\n"
                f"ðŸ”– TX: `{tx}`\n\n"
                f"ðŸ™ Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¿Ð¾ÐºÑƒÐ¿ÐºÑƒ!\n"
                f"Ð’Ð°ÑˆÐ¸ Ð´Ð°Ð½Ð½Ñ‹Ðµ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð° Ðº Ð¾Ð±ÑƒÑ‡Ð°ÑŽÑ‰ÐµÐ¹ Ð¿Ð»Ð°Ñ‚Ñ„Ð¾Ñ€Ð¼Ðµ Ð±ÑƒÐ´ÑƒÑ‚ "
                f"Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð»ÐµÐ½Ñ‹ Ð¿Ð¾ÑÐ»Ðµ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ¸ Ð¸ Ð¿Ð¾Ð´Ñ‚Ð²ÐµÑ€Ð¶Ð´ÐµÐ½Ð¸Ñ Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹."
            )
        elif lang == "lv":
            text = (
                f"âœ… *MaksÄjums apstiprinÄts!*\n\n"
                f"ðŸ“š Kurss: *{name}*\n"
                f"ðŸ”– TX: `{tx}`\n\n"
                f"ðŸ™ Paldies par pirkumu!\n"
                f"PiekÄ¼uves dati mÄcÄ«bu platformai tiks nosÅ«tÄ«ti "
                f"pÄ“c maksÄjuma pÄrbaudes un apstiprinÄÅ¡anas."
            )
        else:
            text = (
                f"âœ… *Payment confirmed!*\n\n"
                f"ðŸ“š Course: *{name}*\n"
                f"ðŸ”– TX: `{tx}`\n\n"
                f"ðŸ™ Thank you for your purchase!\n"
                f"Your access credentials for the learning platform "
                f"will be sent after payment verification and confirmation."
            )
        await msg.edit_text(text, parse_mode="Markdown")

        # Admin paziÅ†ojums
        admin_text = (
            f"ðŸ“š *Jauns kursa pirkums!*\n\n"
            f"ðŸ‘¤ @{username} (`{user_id}`)\n"
            f"ðŸ“§ E-mail: `{email}`\n"
            f"ðŸ“š Kurss: *{name_ru}*\n"
            f"ðŸ’° Summa: *{expected} USDT*\n"
            f"ðŸ”– TX: `{tx}`"
        )
        for aid in config.ADMIN_IDS:
            try: await bot.send_message(aid, admin_text, parse_mode="Markdown")
            except: pass

        await db.mark_referral_bonus_given(user_id)
    else:
        if lang == "ru":
            text = f"âŒ *ÐŸÐ»Ð°Ñ‚Ñ‘Ð¶ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½*\n\nÐ£Ð±ÐµÐ´Ð¸ÑÑŒ Ñ‡Ñ‚Ð¾ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð¸Ð» *{expected} USDT (BEP-20)*"
        else:
            text = f"âŒ *Payment not found*\n\nMake sure you sent *{expected} USDT (BEP-20)*"
        b = InlineKeyboardBuilder()
        b.button(text="ðŸ”„ " + ui_text(lang, "PÄrbaudÄ«t vÄ“lreiz", "ÐŸÑ€Ð¾Ð²ÐµÑ€Ð¸Ñ‚ÑŒ ÑÐ½Ð¾Ð²Ð°", "Check again"), callback_data=f"check_course_{course_key}")
        b.button(text=back_button_text(lang), callback_data="courses_crypto")
        b.adjust(1)
        await msg.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# â”€â”€â”€ DEBUG / ERROR NOTIFICATIONS â”€â”€â”€
async def notify_admins(text: str, parse_mode: str = "Markdown"):
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, text, parse_mode=parse_mode)
        except Exception:
            pass


async def notify_admins_error(context: str, error: str):
    """SÅ«ta admin paziÅ†ojumu par kÄ¼Å«du"""
    text = f"⚠️ *Bot error*\n\n📍 `{context}`\n❌ `{str(error)[:500]}`"
    await notify_admins(text, parse_mode="Markdown")


# â”€â”€â”€ FIX #3: SLOT NO DB â”€â”€â”€
async def _get_unique_amount(plan_key, user_id, base_price):
    mem_slots = [amt for uid, amt in _active_payment_sessions.items() if isinstance(amt, float) and uid != user_id]
    db_slots = await db.get_active_pending_amounts(plan_key)
    taken = set(mem_slots + db_slots)
    slot = 0
    while True:
        c = round(base_price + slot * 0.01, 2)
        if c not in taken: return c
        slot += 1

# â”€â”€â”€ PLAN/PAYMENT â”€â”€â”€
@dp.callback_query(F.data.startswith("plan_"))
async def plan_selected(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    text = ui_text(
        lang,
        "Å Ä« apmaksas metode vairs netiek izmantota. Izmanto mÄjaslapas checkout pogas.",
        "Ð­Ñ‚Ð¾Ñ‚ ÑÐ¿Ð¾ÑÐ¾Ð± Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½Ðµ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ÑÑ. Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ checkout-ÐºÐ½Ð¾Ð¿ÐºÐ¸ ÑÐ°Ð¹Ñ‚Ð°.",
        "This payment method is no longer used. Please use the website checkout buttons.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("âŒ", show_alert=True); return
    plan = config.PLANS[plan_key]
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("lang", "ru") if user else "ru"
    if not (user and user.get("email")):
        await callback.message.edit_text(
            "ðŸ“§ " + ("Vispirms iestati e-pastu. Tas ir vajadzÄ«gs, lai piesaistÄ«tu piekÄ¼uvi." if lang == "lv" else ("Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° ÑƒÐºÐ°Ð¶Ð¸ e-mail Ð² Ð½Ð°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ°Ñ…. ÐžÐ½ Ð½ÑƒÐ¶ÐµÐ½ Ð´Ð»Ñ Ð¿Ñ€Ð¸Ð²ÑÐ·ÐºÐ¸ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°." if lang == "ru" else "Please set your e-mail in Settings first. It is needed to link your access.")),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    saved = await db.get_setting(f"price_{plan_key}")
    base = float(saved) if saved else plan['price_usdt']
    
    # FIX: Ja lietotÄjam jau ir pending ar Å¡o paÅ¡u plÄnu â€” NEÄ¢ENERÄ’T jaunu summu
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
          usdt=unique_amount, days=plan['days'] if plan['days'] < 36500 else "âˆž", wallet=config.CRYPTO_WALLET),
        reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
    
    # Admin paziÅ†ojums par jaunu pending payment
    uname = f"@{callback.from_user.username}" if callback.from_user.username else f"ID {user_id}"
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"ðŸ”” *Jauns maksÄjums gaida!*\n\n"
                f"ðŸ‘¤ {uname} (`{user_id}`)\n"
                f"ðŸ“¦ {plan['emoji']} {plan_name}\n"
                f"ðŸ’° *{unique_amount} USDT*\n"
                f"â± Taimeris: 15 min",
                parse_mode="Markdown")
        except: pass
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment_cb(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "lv") if user else "lv"
    text = ui_text(
        lang,
        "AutomÄtiskÄ crypto pÄrbaude ir izÅ†emta. Pirkums tagad notiek tikai caur mÄjaslapu un webhook.",
        "ÐÐ²Ñ‚Ð¾Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ° crypto ÑƒÐ´Ð°Ð»ÐµÐ½Ð°. Ð¢ÐµÐ¿ÐµÑ€ÑŒ Ð¿Ð¾ÐºÑƒÐ¿ÐºÐ° Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ‡ÐµÑ€ÐµÐ· ÑÐ°Ð¹Ñ‚ Ð¸ webhook.",
        "Automatic crypto checking has been removed. Purchases now work only via website checkout and webhook.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("âŒ", show_alert=True); return
    user_id = callback.from_user.id
    if user_id in _active_payment_sessions:
        await callback.answer("â³ PÄrbaude jau notiek!", show_alert=True); return
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
        f"â³ *{ui_text(lang, 'PÄrbaudu maksÄjumu', 'ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÑŽ Ð¿Ð»Ð°Ñ‚Ñ‘Ð¶', 'Checking payment')}...*\n\n"
        f"â± {ui_text(lang, 'Atlicis', 'ÐžÑÑ‚Ð°Ð»Ð¾ÑÑŒ', 'Time left')}: *15:00*\n\n"
        f"{ui_text(lang, 'Bots automÄtiski pÄrbauda ik pÄ“c 10 sekundÄ“m', 'Ð‘Ð¾Ñ‚ Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÑÐµÑ‚ ÐºÐ°Ð¶Ð´Ñ‹Ðµ 10 ÑÐµÐºÑƒÐ½Ð´', 'Auto-checking every 10 sec')}"
    )
    try:
        await callback.message.edit_text(start_text, parse_mode="Markdown"); msg = callback.message
    except Exception:
        msg = await callback.message.answer(start_text, parse_mode="Markdown")
    _active_payment_sessions[user_id] = expected
    asyncio.create_task(_confirm_payment(user_id, plan_key, plan, lang, msg, callback.from_user.username or ""))

# â”€â”€â”€ UNIVERSÄ€LA AKTIVIZÄ€CIJA â”€â”€â”€
async def _do_activate(user_id, plan_key, plan, lang, username, tx_hash, amount, explicit_expires_at=None):
    now = datetime.utcnow()
    product_meta = resolve_subscription_product(plan_key, lang)
    canonical_key = product_meta.get("product_key", plan_key) if product_meta else plan_key
    plan_name_save = plan['name']['ru'] if isinstance(plan['name'], dict) else plan['name']
    if product_meta and isinstance(product_meta.get("name"), dict):
        plan_name_save = product_meta["name"].get("ru", plan_name_save)
        plan_name_loc = product_meta["name"].get(lang, plan_name_save)
    else:
        plan_name_loc = plan['name'].get(lang, plan_name_save) if isinstance(plan['name'], dict) else plan['name']
    if explicit_expires_at is not None:
        if explicit_expires_at.tzinfo is not None:
            explicit_expires_at = explicit_expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        new_exp = explicit_expires_at
    else:
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
    ref = await db.get_referral_by_referred(user_id)
    if ref and not ref.get("bonus_given"):
        await db.mark_referral_bonus_given(user_id)

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
                ref_text = f"ðŸŽ *Ð‘Ð¾Ð½ÑƒÑ Ð·Ð° Ð´Ñ€ÑƒÐ³Ð°!*\n\nÐ¢Ð²Ð¾Ð¹ Ñ€ÐµÑ„ÐµÑ€Ð°Ð» Ð¾Ñ„Ð¾Ñ€Ð¼Ð¸Ð» Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑƒ.\nÐ¢ÐµÐ±Ðµ Ð´Ð¾Ð±Ð°Ð²Ð»ÐµÐ½Ð¾ *+{REFERRAL_BONUS_DAYS} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°."
            elif ref_lang == "lv":
                ref_text = f"ðŸŽ *Bonuss par draugu!*\n\nTavs referral noformÄ“ja abonementu.\nTev pievienotas *+{REFERRAL_BONUS_DAYS} bezmaksas dienas*."
            else:
                ref_text = f"ðŸŽ *Referral bonus!*\n\nYour referral purchased a subscription.\nYou received *+{REFERRAL_BONUS_DAYS} free days*."
            try:
                await bot.send_message(ref["referrer_id"], ref_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {ref['referrer_id']}: {e}")
            uname = f"@{username}" if username else f"ID {user_id}"
            for aid in config.ADMIN_IDS:
                try: await bot.send_message(aid, f"💰 *New payment!*\n\n👤 {uname} (`{user_id}`)\n📦 *{plan_name_loc}*\n💵 *{amount} USDT*\n📅 Until: *{new_exp.strftime('%d.%m.%Y')}*\n🔖 TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
                except: pass
            return new_exp, plan_name_loc, product_meta
    # Admin notify
    uname = f"@{username}" if username else f"ID {user_id}"
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, f"💰 *New payment!*\n\n👤 {uname} (`{user_id}`)\n📦 *{plan_name_loc}*\n💵 *{amount} USDT*\n📅 Until: *{new_exp.strftime('%d.%m.%Y')}*\n🔖 TX: `{tx_hash[:24]}...`", parse_mode="Markdown")
        except: pass
    return new_exp, plan_name_loc, product_meta

# PÄ“c veiksmÄ«ga payment â€” nosÅ«tÄ«t referral reminder pÄ“c 5 min
async def _post_payment_actions(user_id, lang):
    """DarbÄ«bas pÄ“c veiksmÄ«ga maksÄjuma â€” referral reminder"""
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
                inv = await invite_text_for_product(
                    user_id,
                    lang,
                    product_meta,
                    new_exp,
                    debug_source=f"renewal_notice user={user_id} product={pk}",
                )
                txt = t(lang, "paid_ok", name=plan_name_loc, expires=new_exp.strftime('%d.%m.%Y'), tx=paid[:20]) + inv
                try: await msg.edit_text(txt, parse_mode="Markdown")
                except: await bot.send_message(user_id, txt, parse_mode="Markdown")
                await _post_payment_actions(user_id, lang)
                return
            if elapsed % 30 == 0 and remaining > 0:
                m, s = remaining // 60, remaining % 60
                try: await msg.edit_text(f"â³ *{ui_text(lang, 'PÄrbaudu maksÄjumu', 'ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÑŽ Ð¿Ð»Ð°Ñ‚Ñ‘Ð¶', 'Checking')}...*\n\nâ± {ui_text(lang, 'Atlicis', 'ÐžÑÑ‚Ð°Ð»Ð¾ÑÑŒ', 'Left')}: *{m}:{s:02d}*\n\n{ui_text(lang, 'AutomÄtiska pÄrbaude ik pÄ“c 10 sekundÄ“m', 'ÐÐ²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ°Ñ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ° ÐºÐ°Ð¶Ð´Ñ‹Ðµ 10 ÑÐµÐºÑƒÐ½Ð´', 'Auto-check every 10 sec')}", parse_mode="Markdown")
                except: pass
        timeout_txt = ui_text(
            lang,
            "âŒ *Laiks beidzÄs (15 min)*\n\nJa nosÅ«tÄ«ji maksÄjumu, pagaidi - bots to pÄrbauda fonÄ ik pÄ“c 3 min.",
            "âŒ *Ð’Ñ€ÐµÐ¼Ñ Ð²Ñ‹ÑˆÐ»Ð¾ (15 Ð¼Ð¸Ð½)*\n\nÐ•ÑÐ»Ð¸ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð¸Ð» â€” Ð¿Ð¾Ð´Ð¾Ð¶Ð´Ð¸, Ð±Ð¾Ñ‚ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÑÐµÑ‚ Ñ„Ð¾Ð½Ð¾Ð¼ ÐºÐ°Ð¶Ð´Ñ‹Ðµ 3 Ð¼Ð¸Ð½.",
            "âŒ *Timeout (15 min)*\n\nIf sent â€” wait, bot checks background every 3 min."
        )
        try: await msg.edit_text(timeout_txt, reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
        except: await bot.send_message(user_id, timeout_txt, reply_markup=payment_keyboard(plan_key, lang), parse_mode="Markdown")
    except asyncio.CancelledError: pass
    except Exception as e: logger.error(f"Payment poll error user={user_id}: {e}", exc_info=True)
    finally: _active_payment_sessions.pop(user_id, None)

@dp.callback_query(F.data == "vip_chat_plans")
async def show_vip_chat_plans(callback: CallbackQuery):
    """ParÄda pieejamos VIP Äatus. Pirkums notiek mÄjaslapÄ."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    if not (user and user.get("email")):
        text = (
            "📧 Vispirms iestati e-pastu. Pēc pirkuma mājaslapa sūtīs webhook, un bots piekļuvi atradīs tieši pēc šī e-pasta."
            if lang == "lv" else
            ("📧 Сначала укажи e-mail. После покупки сайт отправит webhook, и бот найдет доступ именно по этому e-mail."
             if lang == "ru" else
             "📧 Please set your e-mail first. After purchase the website will send a webhook, and the bot will match access by this e-mail.")
        )
        await callback.message.edit_text(text, reply_markup=main_menu_keyboard(lang), parse_mode="Markdown")
        await callback.answer()
        return
    default_text = (
        f"💎 *Izvēlies VIP čatu — {VIP_CHAT_PRICE_LABEL}:*\n\nPirkums notiek mājaslapā. Pēc apmaksas bots automātiski piesaistīs piekļuvi pēc tava e-pasta."
        if lang == "lv" else
        (f"💎 *Выбери VIP чат — {VIP_CHAT_PRICE_LABEL}:*\n\nПокупка происходит на сайте. После оплаты бот автоматически привяжет доступ по твоему e-mail."
         if lang == "ru" else
         f"💎 *Choose VIP chat — {VIP_CHAT_PRICE_LABEL}:*\n\nPurchase happens on the website. After payment the bot will link access by your e-mail.")
    )
    text = await override_text("vip_intro", lang, default_text)
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
    """AtpakaÄ¼ uz galveno izvÄ“lni"""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    name = md_escape(callback.from_user.first_name)
    
    # PÄrbauda vai ir aktÄ«va subscription
    active_subs = await db.get_active_user_subscriptions(callback.from_user.id)
    if active_subs:
        text, kb = await build_active_home_view(callback.from_user.id, lang, name)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif user and user.get('expires_at') and datetime.fromisoformat(user['expires_at']) > datetime.utcnow():
        expires_dt = datetime.fromisoformat(user['expires_at'])
        text = t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "â€”"), days=max(0, (expires_dt - datetime.utcnow()).days))
        await callback.message.edit_text(text, reply_markup=active_keyboard(lang), parse_mode="Markdown")
    else:
        # NeaktÄ«viem - main_menu
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
        "QR crypto apmaksa vairs nav aktÄ«va. Izmanto checkout pogas botÄ.",
        "QR crypto Ð¾Ð¿Ð»Ð°Ñ‚Ð° Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½Ðµ Ð°ÐºÑ‚Ð¸Ð²Ð½Ð°. Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ checkout-ÐºÐ½Ð¾Ð¿ÐºÐ¸ Ð² Ð±Ð¾Ñ‚Ðµ.",
        "QR crypto payment is no longer active. Use the checkout buttons in the bot.",
    )
    await callback.answer(text, show_alert=True)
    return
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in config.PLANS: await callback.answer("âŒ", show_alert=True); return
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
        await callback.answer(f"ðŸ“‹ {config.CRYPTO_WALLET}", show_alert=True)

# â”€â”€â”€ FIX #2: AUTO-CHECK FONS â”€â”€â”€
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
                        msg = f"âœ… *ÐžÐ¿Ð»Ð°Ñ‚Ð° ÐºÑƒÑ€ÑÐ° Ð¿Ð¾Ð´Ñ‚Ð²ÐµÑ€Ð¶Ð´ÐµÐ½Ð°!*\n\nðŸ“š {cname}\nðŸ”– TX: `{tx[:20]}`\n\nðŸ™ Ð”Ð°Ð½Ð½Ñ‹Ðµ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð° Ð±ÑƒÐ´ÑƒÑ‚ Ð¾Ñ‚Ð¿Ñ€Ð°Ð²Ð»ÐµÐ½Ñ‹ Ð¿Ð¾ÑÐ»Ðµ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ¸."
                    else:
                        msg = f"âœ… *Course payment confirmed!*\n\nðŸ“š {cname}\nðŸ”– TX: `{tx[:20]}`\n\nðŸ™ Access credentials will be sent after verification."
                    try: await bot.send_message(uid, msg, parse_mode="Markdown")
                    except: pass
                    # Admin
                    for aid in config.ADMIN_IDS:
                        try: await bot.send_message(aid, f"ðŸ“š *Kursa pirkums (auto):*\nðŸ‘¤ @{username} (`{uid}`)\nðŸ“§ `{email}`\nðŸ“š {cname}\nðŸ’° {amount} USDT\nðŸ”– `{tx[:20]}`", parse_mode="Markdown")
                        except: pass
                else:
                    # ÄŒata abonements
                    plan = config.PLANS[pk]
                    new_exp, pname, product_meta = await _do_activate(uid, pk, plan, lang, username, tx, amount)
                    inv = await invite_text_for_product(
                        uid,
                        lang,
                        product_meta,
                        new_exp,
                        debug_source=f"auto_check user={uid} product={pk}",
                    )
                    await bot.send_message(uid, t(lang, "auto_found", name=pname, expires=new_exp.strftime('%d.%m.%Y'), tx=tx[:20]) + inv, parse_mode="Markdown")

                logger.info(f"[AUTO-CHECK] user={uid} TX={tx[:20]} plan={pk}")
        except Exception as e:
            logger.error(f"[AUTO-CHECK] {uid}: {e}")
            await notify_admins_error(f"auto_check user={uid}", e)

# â”€â”€â”€ SCHEDULER JOBS â”€â”€â”€
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
                    text = f"â° *Subscription expires TODAY!*\n\nðŸ“… {exp_str}\n\nRenew now:" if lang == "en" else f"â° *ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ÑÑ‚ÐµÐºÐ°ÐµÑ‚ Ð¡Ð•Ð“ÐžÐ”ÐÐ¯!*\n\nðŸ“… Ð”Ð°Ñ‚Ð°: {exp_str}\n\nÐŸÑ€Ð¾Ð´Ð»Ð¸ ÑÐµÐ¹Ñ‡Ð°Ñ:"
                await bot.send_message(user['user_id'], text, reply_markup=plans_keyboard(lang), parse_mode="Markdown")
                await db.mark_reminder_sent(user['user_id'], db_)
                await db.log_bot_event("reminder_sent", user['user_id'], meta=f"days_before={db_}")
                if db_ == 0:
                    username = f"@{user['username']}" if user.get("username") else f"ID {user['user_id']}"
                    admin_text = (
                        "â° *Abonements beidzas Å¡odien*\n\n"
                        f"ðŸ‘¤ {username} (`{user['user_id']}`)\n"
                        f"ðŸ“¦ {user.get('plan_name', 'â€”')}\n"
                        f"ðŸ“… {exp_str}"
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
            b.button(text=f"ðŸ”¥ {yn}", callback_data="plan_yearly"); b.adjust(1)
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
    now = datetime.utcnow()
    for user in await db.get_expired_chat_subscriptions():
        if user.get("is_friend"): continue
        # ADMIN AIZSARDZÄªBA â€” nekad nebanoj adminus
        if user['user_id'] in config.ADMIN_IDS:
            logger.info(f"Skip admin {user['user_id']} â€” cannot kick admin")
            continue
        try:
            expires_dt = datetime.fromisoformat(user["expires_at"])
            grace_until = expires_dt + timedelta(days=SUBSCRIPTION_GRACE_DAYS)
            if now < grace_until:
                reminder_sent_at = user.get("grace_reminder_sent_at")
                should_remind = True
                if reminder_sent_at:
                    try:
                        reminded_dt = datetime.fromisoformat(reminder_sent_at)
                        should_remind = reminded_dt.date() < now.date()
                    except Exception:
                        should_remind = True
                if should_remind:
                    days_left = max(0, (grace_until - now).days)
                    rlang = user.get("lang", "lv")
                    default_reminder_text = ui_text(
                        rlang,
                        f"⚠️ Maksājums par abonementa pagarināšanu vēl nav saņemts.\n\nTava piekļuve beidzās: *{expires_dt.strftime('%d.%m.%Y')}*\nGrace periods: *{SUBSCRIPTION_GRACE_DAYS} dienas*\nAtlikušas aptuveni: *{days_left}* dienas.\n\nJa apmaksa neatnāks, bots pēc grace perioda beigām izņems tevi no čata.",
                        f"⚠️ Оплата за продление подписки еще не получена.\n\nТвой доступ закончился: *{expires_dt.strftime('%d.%m.%Y')}*\nGrace period: *{SUBSCRIPTION_GRACE_DAYS} дней*\nОсталось примерно: *{days_left}* дней.\n\nЕсли оплата не поступит, бот удалит тебя из чата после окончания grace period.",
                        f"⚠️ Payment for subscription renewal has not been received yet.\n\nYour access expired on: *{expires_dt.strftime('%d.%m.%Y')}*\nGrace period: *{SUBSCRIPTION_GRACE_DAYS} days*\nRoughly remaining: *{days_left}* days.\n\nIf no payment arrives, the bot will remove you from the chat after the grace period ends.",
                    )
                    reminder_text = await override_text(
                        "grace_reminder",
                        rlang,
                        default_reminder_text,
                        expires=expires_dt.strftime('%d.%m.%Y'),
                        grace_days=SUBSCRIPTION_GRACE_DAYS,
                        days_left=days_left,
                    )
                    try:
                        await bot.send_message(user["user_id"], reminder_text, parse_mode="Markdown")
                    except Exception as e:
                        logger.warning(f"Grace reminder failed user={user['user_id']}: {e}")
                    await db.mark_grace_reminder_sent(user["id"])
                    await db.log_bot_event("grace_reminder", user["user_id"], meta=f"sub_id={user['id']}")
                continue
            chat_id = int(user.get("chat_id") or 0)
            if chat_id:
                try:
                    await bot.ban_chat_member(chat_id, user['user_id'])
                    await bot.unban_chat_member(chat_id, user['user_id'])
                except Exception as e:
                    logger.warning(f"Kick failed chat={chat_id} user={user['user_id']}: {e}")
            await db.mark_subscription_inactive(user['id'])
            try:
                kicked_text = await override_text(
                    "kick_message",
                    user.get("lang", "ru"),
                    t(user.get("lang", "ru"), "kicked"),
                )
                await bot.send_message(user['user_id'], kicked_text, reply_markup=plans_keyboard(user.get("lang","ru")), parse_mode="Markdown")
            except: pass
            username = f"@{user['username']}" if user.get("username") else f"ID {user['user_id']}"
            expires_at = user.get("expires_at", "")
            admin_text = (
                "ðŸš« *LietotÄjs izmests no Äata*\n\n"
                f"ðŸ‘¤ {username} (`{user['user_id']}`)\n"
                f"ðŸ“¦ {user.get('product_name', user.get('plan_name', 'â€”'))}\n"
                f"ðŸ“… Abonements beidzÄs: `{expires_at}`\n\n"
                "â„¹ï¸ Marketing ziÅ†as Å¡im lietotÄjam joprojÄm var tikt sÅ«tÄ«tas no DB segmentiem."
            )
            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, admin_text, parse_mode="Markdown")
                except Exception:
                    pass
            await db.log_bot_event("expired_kick", user['user_id'], meta=f"expires={expires_at}")
        except Exception as e: logger.error(f"Kick {user['user_id']}: {e}")

async def run_monthly_giveaway():
    """AutomÄtiska izloze â€” 1. datumÄ, iepriekÅ¡Ä“jÄ mÄ“neÅ¡a dalÄ«bnieki"""
    import random
    now = datetime.utcnow()
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    participants = await db.get_giveaway_participants(prev_month)
    if not participants:
        logger.info(f"[GIVEAWAY] Nav dalÄ«bnieku par {prev_month}")
        return

    winners_count, prize_days = await _giveaway_settings()
    winners_count = min(winners_count, len(participants))

    winners = random.sample(participants, winners_count)

    month_names_ru = ["Ð¯Ð½Ð²Ð°Ñ€ÑŒ","Ð¤ÐµÐ²Ñ€Ð°Ð»ÑŒ","ÐœÐ°Ñ€Ñ‚","ÐÐ¿Ñ€ÐµÐ»ÑŒ","ÐœÐ°Ð¹","Ð˜ÑŽÐ½ÑŒ","Ð˜ÑŽÐ»ÑŒ","ÐÐ²Ð³ÑƒÑÑ‚","Ð¡ÐµÐ½Ñ‚ÑÐ±Ñ€ÑŒ","ÐžÐºÑ‚ÑÐ±Ñ€ÑŒ","ÐÐ¾ÑÐ±Ñ€ÑŒ","Ð”ÐµÐºÐ°Ð±Ñ€ÑŒ"]
    month_idx = int(prev_month.split("-")[1]) - 1

    winner_names = []
    for w in winners:
        wid = w['user_id']
        wuser = await db.get_user(wid)
        wname = f"@{wuser['username']}" if wuser and wuser.get('username') else f"ID {wid}"
        wlang = wuser.get("lang", "ru") if wuser else "ru"
        winner_names.append(wname)

        # PieÅ¡Ä·irt dienas â€” pat ja abonements beidzies
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
                invite_text = f"\n\nðŸ”— [{ui_text(wlang, 'Pievienoties Äatam', 'Ð’ÑÑ‚ÑƒÐ¿Ð¸Ñ‚ÑŒ Ð² Ñ‡Ð°Ñ‚', 'Join chat')}]({link.invite_link})"
            except Exception:
                invite_text = f"\n\nðŸ“¢ {chat_link_for_lang(wlang)}"

        # PrivÄtÄ ziÅ†a uzvarÄ“tÄjam â€” custom vai default
        custom_winner_text = await db.get_setting(f"giveaway_winner_text_{wlang}")
        if custom_winner_text:
            private_text = custom_winner_text.replace("{days}", str(prize_days)).replace("{expires}", new_exp.strftime('%d.%m.%Y'))
        elif wlang == "ru":
            private_text = (
                "ðŸŽ‰ðŸŽ‰ðŸŽ‰ *ÐŸÐžÐ—Ð”Ð ÐÐ’Ð›Ð¯Ð•Ðœ!*\n\n"
                "ðŸ† Ð¢Ñ‹ Ð²Ñ‹Ð¸Ð³Ñ€Ð°Ð» Ð² ÐµÐ¶ÐµÐ¼ÐµÑÑÑ‡Ð½Ð¾Ð¼ Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ!\n"
                f"ðŸŽ ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð° Ðº Ñ‡Ð°Ñ‚Ñƒ!\n\n"
                f"ðŸ“… ÐŸÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð°ÐºÑ‚Ð¸Ð²Ð½Ð° Ð´Ð¾: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "ðŸŽŸ Ð£Ñ‡Ð°ÑÑ‚Ð²ÑƒÐ¹ Ð² Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ ÑÐ»ÐµÐ´ÑƒÑŽÑ‰ÐµÐ³Ð¾ Ð¼ÐµÑÑÑ†Ð°!"
            )
        elif wlang == "lv":
            private_text = (
                "ðŸŽ‰ðŸŽ‰ðŸŽ‰ *APSVEICAM!*\n\n"
                "ðŸ† Tu uzvarÄ“ji ikmÄ“neÅ¡a izlozÄ“!\n"
                f"ðŸŽ Balva: *+{prize_days} dienas* bezmaksas piekÄ¼uvei Äatam!\n\n"
                f"ðŸ“… Abonements aktÄ«vs lÄ«dz: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "ðŸŽŸ Piedalies arÄ« nÄkamÄ mÄ“neÅ¡a izlozÄ“!"
            )
        else:
            private_text = (
                "ðŸŽ‰ðŸŽ‰ðŸŽ‰ *CONGRATULATIONS!*\n\n"
                "ðŸ† You won the monthly giveaway!\n"
                f"ðŸŽ Prize: *+{prize_days} days* of free chat access!\n\n"
                f"ðŸ“… Subscription active until: *{new_exp.strftime('%d.%m.%Y')}*\n\n"
                "ðŸŽŸ Join next month's giveaway!"
            )
        try:
            await bot.send_message(wid, private_text + invite_text, parse_mode="Markdown")
        except Exception:
            pass

    await db.set_setting(f"giveaway_winner_{prev_month}", ",".join(str(w['user_id']) for w in winners))

    # KanÄla paziÅ†ojums â€” valoda no settings
    winners_str = ", ".join(winner_names)
    chat_lang = await db.get_setting("giveaway_chat_lang") or "ru"

    month_names_en = ["January","February","March","April","May","June","July","August","September","October","November","December"]

    if chat_lang == "en":
        channel_text = (
            f"ðŸŽŸ *{month_names_en[month_idx]} Giveaway Results!*\n\n"
            f"ðŸ‘¥ Participants: *{len(participants)}*\n"
            f"ðŸ† {'Winners' if winners_count > 1 else 'Winner'}: *{winners_str}*\n"
            f"ðŸŽ Prize: *+{prize_days} days* of free access!\n\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
            "ðŸŽŸ *Want to join next month's giveaway?*\n"
            "Press Â«Monthly GiveawayÂ» button in the bot!\n\n"
            "ðŸ€ Good luck everyone!"
        )
    else:
        channel_text = (
            f"ðŸŽŸ *Ð ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ñ‹ Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐ° {month_names_ru[month_idx]}!*\n\n"
            f"ðŸ‘¥ Ð£Ñ‡Ð°ÑÑ‚Ð½Ð¸ÐºÐ¾Ð²: *{len(participants)}*\n"
            f"ðŸ† {'ÐŸÐ¾Ð±ÐµÐ´Ð¸Ñ‚ÐµÐ»Ð¸' if winners_count > 1 else 'ÐŸÐ¾Ð±ÐµÐ´Ð¸Ñ‚ÐµÐ»ÑŒ'}: *{winners_str}*\n"
            f"ðŸŽ ÐŸÑ€Ð¸Ð·: *+{prize_days} Ð´Ð½ÐµÐ¹* Ð±ÐµÑÐ¿Ð»Ð°Ñ‚Ð½Ð¾Ð³Ð¾ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð°!\n\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
            "ðŸŽŸ *Ð¥Ð¾Ñ‡ÐµÑˆÑŒ ÑƒÑ‡Ð°ÑÑ‚Ð²Ð¾Ð²Ð°Ñ‚ÑŒ Ð² ÑÐ»ÐµÐ´ÑƒÑŽÑ‰ÐµÐ¼ Ñ€Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹ÑˆÐµ?*\n"
            "ÐÐ°Ð¶Ð¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑƒ Â«Ð Ð¾Ð·Ñ‹Ð³Ñ€Ñ‹Ñˆ Ð¼ÐµÑÑÑ†Ð°Â» Ð² Ð±Ð¾Ñ‚Ðµ!\n\n"
            "ðŸ€ Ð£Ð´Ð°Ñ‡Ð¸ Ð²ÑÐµÐ¼!"
        )
    try:
        await bot.send_message(config.CHAT_ID, channel_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[GIVEAWAY] Channel msg: {e}")

    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"ðŸŽŸ *Giveaway {prev_month}:*\n\n"
                f"ðŸ‘¥ DalÄ«bnieki: *{len(participants)}*\n"
                f"ðŸ† UzvarÄ“tÄji: *{winners_str}*\n"
                f"ðŸŽ +{prize_days} dienas",
                parse_mode="Markdown")
        except Exception:
            pass

    logger.info(f"[GIVEAWAY] {prev_month}: {len(winners)} winners from {len(participants)}")


# Legacy naudas referral sadaÄ¼as aizvietotas ar bonusu dienu maku
@dp.callback_query(F.data == "ref_earnings_page")
async def show_earnings_page(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get("lang", "ru") if user else "ru"
    text = await build_referral_overview_text(callback.from_user.id, lang)
    text += ui_text(
        lang,
        "\n\nâ„¹ï¸ Å obrÄ«d referral programma izmanto tikai bonusu dienas. Naudas izmaksas vairs nav pieejamas.",
        "\n\nâ„¹ï¸ Ð¡ÐµÐ¹Ñ‡Ð°Ñ referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸. Ð”ÐµÐ½ÐµÐ¶Ð½Ñ‹Ðµ Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹.",
        "\n\nâ„¹ï¸ The referral program now uses bonus days only. Cash payouts are no longer available.",
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
            "Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸.",
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
            "Naudas izmaksas vairs nav pieejamas. Referral programma tagad dod tikai bonusu dienas Äatiem.",
            "Ð”ÐµÐ½ÐµÐ¶Ð½Ñ‹Ðµ Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹. Referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð´Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
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
            "Referral izmaksas ir izslÄ“gtas. Tagad pieejamas tikai bonusu dienas Äatiem.",
            "Referral Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ñ‹. Ð¢ÐµÐ¿ÐµÑ€ÑŒ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
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
            "Referral izmaksas ir izslÄ“gtas. Tagad pieejamas tikai bonusu dienas Äatiem.",
            "Referral Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ñ‹. Ð¢ÐµÐ¿ÐµÑ€ÑŒ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
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
            "â„¹ï¸ Referral izmaksas vairs nav pieejamas. Tagad tiek izmantotas tikai bonusu dienas Äatiem.",
            "â„¹ï¸ Referral Ð²Ñ‹Ð¿Ð»Ð°Ñ‚Ñ‹ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ñ‹. Ð¢ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÑŽÑ‚ÑÑ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸ Ð´Ð»Ñ Ñ‡Ð°Ñ‚Ð¾Ð².",
            "â„¹ï¸ Referral payouts are no longer available. Only bonus days for chats are used now.",
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
            "Atcelts. Referral sadaÄ¼Ä tagad tiek izmantotas tikai bonusu dienas.",
            "ÐžÑ‚Ð¼ÐµÐ½ÐµÐ½Ð¾. Ð’ referral Ñ€Ð°Ð·Ð´ÐµÐ»Ðµ Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÑŽÑ‚ÑÑ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ðµ Ð´Ð½Ð¸.",
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
            "Izmaksu vÄ“sture vairs netiek izmantota, jo referral programma tagad strÄdÄ ar bonusu dienÄm.",
            "Ð˜ÑÑ‚Ð¾Ñ€Ð¸Ñ Ð²Ñ‹Ð¿Ð»Ð°Ñ‚ Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½Ðµ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ÑÑ, Ð¿Ð¾Ñ‚Ð¾Ð¼Ñƒ Ñ‡Ñ‚Ð¾ referral Ð¿Ñ€Ð¾Ð³Ñ€Ð°Ð¼Ð¼Ð° Ñ‚ÐµÐ¿ÐµÑ€ÑŒ Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ñ Ð±Ð¾Ð½ÑƒÑÐ½Ñ‹Ð¼Ð¸ Ð´Ð½ÑÐ¼Ð¸.",
            "Withdrawal history is no longer used because the referral program now works with bonus days.",
        ),
        show_alert=True,
    )




# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# LOYALTY HANDLERS (embedded from bot_loyalty_addon.py)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@dp.message(Command("loyalty"))
async def show_loyalty_status(message: Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await message.answer("User not found.")
        return

    lang = user.get('lang', 'ru')
    loyalty_data = await db.get_user_loyalty(user_id)
    if not loyalty_data:
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}

    current_tier = loyalty_data.get('current_tier', 'rookie')
    consecutive_months = loyalty_data.get('consecutive_months', 0)
    tier_data = config.LOYALTY_TIERS.get(current_tier, {})
    emoji = tier_data.get('emoji', '🌱')
    tag = tier_data.get('tag', 'Rookie')

    next_tier = None
    target_months = consecutive_months
    for tier_name in ['active', 'pro', 'elite', 'master', 'legend']:
        tier_info = config.LOYALTY_TIERS[tier_name]
        if consecutive_months < tier_info['min_months']:
            next_tier = tier_name
            target_months = tier_info['min_months']
            break

    progress = 1 if not next_tier else (consecutive_months / target_months if target_months > 0 else 0)
    bar_length = 12
    filled = min(bar_length, int(progress * bar_length))
    bar = "▓" * filled + "░" * (bar_length - filled)

    if lang == "lv":
        text = f"🏅 *Tavs ranks*\n\n{emoji} *{tag.upper()}*\n{bar} *{int(progress * 100)}%*\n\nAktīvie mēneši: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            left = target_months - consecutive_months
            text += f"\nNākamais ranks: *{next_tag}*\nAtlicis: *{left}* mēn."
        else:
            text += "\nTu jau esi sasniedzis augstāko ranku."
        text += "\n\nŠobrīd ranki ir bez bonusiem un bez atlaidēm."
    elif lang == "ru":
        text = f"🏅 *Твой ранг*\n\n{emoji} *{tag.upper()}*\n{bar} *{int(progress * 100)}%*\n\nАктивные месяцы: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            left = target_months - consecutive_months
            text += f"\nСледующий ранг: *{next_tag}*\nОсталось: *{left}* мес."
        else:
            text += "\nТы уже достиг максимального ранга."
        text += "\n\nСейчас ранги без бонусов и без скидок."
    else:
        text = f"🏅 *Your Rank*\n\n{emoji} *{tag.upper()}*\n{bar} *{int(progress * 100)}%*\n\nActive months: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            left = target_months - consecutive_months
            text += f"\nNext rank: *{next_tag}*\nRemaining: *{left}* mo."
        else:
            text += "\nYou already reached the highest rank."
        text += "\n\nRanks are currently visual only with no bonuses or discounts."

    b = InlineKeyboardBuilder()
    b.button(text="📋 " + ui_text(lang, "Visi ranki", "Все ранги", "All ranks"), callback_data="loyalty_tiers_info")
    b.button(text="💎 " + ui_text(lang, "Pagarināt", "Продлить", "Renew"), callback_data="vip_chat_plans")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "loyalty_status")
async def loyalty_status_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("User not found")
        return

    lang = user.get('lang', 'ru')
    loyalty_data = await db.get_user_loyalty(user_id)
    if not loyalty_data:
        await db.update_user_loyalty(user_id, 'rookie', 0)
        loyalty_data = {'current_tier': 'rookie', 'consecutive_months': 0}

    current_tier = loyalty_data.get('current_tier', 'rookie')
    consecutive_months = loyalty_data.get('consecutive_months', 0)
    tier_data = config.LOYALTY_TIERS[current_tier]
    emoji = tier_data.get('emoji', '🌱')
    tag = tier_data.get('tag', 'Rookie')

    next_tier = None
    target_months = 0
    for tier_name in ['active', 'pro', 'elite', 'master', 'legend']:
        tier_info = config.LOYALTY_TIERS[tier_name]
        if consecutive_months < tier_info['min_months']:
            next_tier = tier_name
            target_months = tier_info['min_months']
            break
    
    if next_tier:
        progress = consecutive_months / target_months if target_months > 0 else 0
        progress_pct = int(progress * 100)
        bar_length = 15
        filled = min(bar_length, int(progress * bar_length))
        bar = "▓" * filled + "░" * (bar_length - filled)
    else:
        bar = "▓" * 15
        progress_pct = 100
    if lang == 'ru':
        text = f"🏅 *Твой ранг*\n\n{emoji} *{tag.upper()}*\n{bar} *{progress_pct}%*\n\nАктивные месяцы: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            text += f"\nСледующий ранг: *{next_tag}*\nОсталось: *{target_months - consecutive_months}* мес."
        else:
            text += "\nТы уже достиг максимального ранга."
        text += "\n\nСейчас ранги без бонусов и без скидок."
    elif lang == 'lv':
        text = f"🏅 *Tavs ranks*\n\n{emoji} *{tag.upper()}*\n{bar} *{progress_pct}%*\n\nAktīvie mēneši: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            text += f"\nNākamais ranks: *{next_tag}*\nAtlicis: *{target_months - consecutive_months}* mēn."
        else:
            text += "\nTu jau esi sasniedzis augstāko ranku."
        text += "\n\nŠobrīd ranki ir bez bonusiem un bez atlaidēm."
    else:
        text = f"🏅 *Your Rank*\n\n{emoji} *{tag.upper()}*\n{bar} *{progress_pct}%*\n\nActive months: *{consecutive_months}*"
        if next_tier:
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            text += f"\nNext rank: *{next_tag}*\nRemaining: *{target_months - consecutive_months}* mo."
        else:
            text += "\nYou already reached the highest rank."
        text += "\n\nRanks are currently visual only with no bonuses or discounts."

    b = InlineKeyboardBuilder()
    b.button(text="📋 " + ui_text(lang, "Visi ranki", "Все ранги", "All ranks"), callback_data="loyalty_tiers_info")
    b.button(text=back_button_text(lang), callback_data="settings_back")
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()



def _months_ru(n):
    """MÄ“neÅ¡u locÄ«jums krievu valodÄ"""
    if n % 10 == 1 and n % 100 != 11:
        return "Ð¼ÐµÑÑÑ†"
    elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "Ð¼ÐµÑÑÑ†Ð°"
    return "Ð¼ÐµÑÑÑ†ÐµÐ²"


@dp.callback_query(F.data == "loyalty_tiers_info")
async def loyalty_tiers_info(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = user.get('lang', 'ru') if user else 'ru'
    
    loyalty_data = await db.get_user_loyalty(callback.from_user.id)
    current_tier = loyalty_data.get('current_tier', 'rookie') if loyalty_data else 'rookie'
    
    tier_order = ['rookie', 'active', 'pro', 'elite', 'master', 'legend']
    
    if lang == 'ru':
        text = "📋 *Все ранги*\n\nСейчас ранги только визуальные, без бонусов и скидок.\n"
    elif lang == 'lv':
        text = "📋 *Visi ranki*\n\nŠobrīd ranki ir tikai vizuāli, bez bonusiem un atlaidēm.\n"
    else:
        text = "📋 *All ranks*\n\nRanks are currently visual only, with no bonuses or discounts.\n"
    
    for tier_name in tier_order:
        td = config.LOYALTY_TIERS[tier_name]
        em = td['emoji']
        tg = td['tag']
        min_m = td['min_months']
        
        is_current = (tier_name == current_tier)
        marker = ui_text(lang, " <- tu esi šeit", " <- ты здесь", " <- you are here") if is_current else ""
        
        text += f"\n────────────────\n"
        text += f"{em} *{tg.upper()}*{marker}\n"
        
        if lang == 'ru':
            if min_m == 0:
                text += "📅 Стартовый ранг\n"
            else:
                text += f"📅 После {min_m} {_months_ru(min_m)} активной подписки\n"
        elif lang == 'lv':
            if min_m == 0:
                text += "📅 Sākuma ranks\n"
            else:
                text += f"📅 Pēc {min_m} aktīviem mēnešiem\n"
        else:
            if min_m == 0:
                text += "📅 Starting rank\n"
            else:
                text += f"📅 After {min_m} active months\n"
    
    text += "\n────────────────\n"
    if lang == 'ru':
        text += "\n💡 *Ранг растет, пока подписка активна.*"
    elif lang == 'lv':
        text += "\n💡 *Tavs ranks aug, kamēr abonements ir aktīvs.*"
    else:
        text += "\n💡 *Your rank grows while the subscription stays active.*"
    
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
        text = "âŒ " + ui_text(lang, "Tev nav aktÄ«vu promokodu", "Ð£ Ñ‚ÐµÐ±Ñ Ð½ÐµÑ‚ Ð°ÐºÑ‚Ð¸Ð²Ð½Ñ‹Ñ… Ð¿Ñ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´Ð¾Ð²", "You have no active promo codes")
        b = InlineKeyboardBuilder()
        b.button(text=back_button_text(lang), callback_data="loyalty_main")
        b.adjust(1)
        await callback.message.edit_text(text, reply_markup=b.as_markup())
        await callback.answer()
        return
    
    if lang == 'ru':
        text = "ðŸ’³ *Ð¢Ð’ÐžÐ˜ ÐŸÐ ÐžÐœÐžÐšÐžÐ”Ð«*\n\n"
    elif lang == 'lv':
        text = "ðŸ’³ *TAVI PROMOKODI*\n\n"
    else:
        text = "ðŸ’³ *YOUR PROMO CODES*\n\n"
    
    keyboard = InlineKeyboardBuilder()
    
    for coupon in coupons:
        code = coupon['code']
        discount = coupon['discount_percent']
        coupon_type = coupon['coupon_type']
        applies_to = coupon['applies_to']
        expires_at = coupon.get('expires_at')
        max_uses = coupon.get('max_uses')
        times_used = coupon.get('times_used', 0)
        
        text += "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        
        # Type-specific header
        if coupon_type == 'loyalty_tier':
            text += f"ðŸŽ¯ *{ui_text(lang, 'LojalitÄtes atlaide', 'Ð¡ÐºÐ¸Ð´ÐºÐ° Ð»Ð¾ÑÐ»ÑŒÐ½Ð¾ÑÑ‚Ð¸', 'Loyalty Discount')}*\n\n"
        
        elif coupon_type == 'reminder_bonus':
            text += f"ðŸŽ *{ui_text(lang, 'AtgÄdinÄjuma bonuss', 'Ð‘Ð¾Ð½ÑƒÑ-Ð½Ð°Ð¿Ð¾Ð¼Ð¸Ð½Ð°Ð½Ð¸Ðµ', 'Reminder Bonus')}*\n\n"
        
        elif coupon_type == 'winback':
            text += f"ðŸ”™ *{ui_text(lang, 'Laipni atpakaÄ¼', 'Ð¡ Ð²Ð¾Ð·Ð²Ñ€Ð°Ñ‰ÐµÐ½Ð¸ÐµÐ¼', 'Welcome Back')}*\n\n"
        
        elif coupon_type == 'survey':
            text += f"ðŸ“Š *{ui_text(lang, 'Aptaujas balva', 'ÐÐ°Ð³Ñ€Ð°Ð´Ð° Ð·Ð° Ð¾Ð¿Ñ€Ð¾Ñ', 'Survey Reward')}*\n\n"
        
        # Code
        if lang == 'ru':
            text += f"ÐšÐ¾Ð´: `{code}`\n"
            text += f"Ð¡ÐºÐ¸Ð´ÐºÐ°: *{discount}%*\n"
        elif lang == 'lv':
            text += f"Kods: `{code}`\n"
            text += f"Atlaide: *{discount}%*\n"
        else:
            text += f"Code: `{code}`\n"
            text += f"Discount: *{discount}%*\n"
        
        # Applies to
        if applies_to == 'all':
            text += ui_text(lang, "Der: visiem plÄniem + kursiem\n", "ÐŸÑ€Ð¸Ð¼ÐµÐ½ÑÐµÑ‚ÑÑ: Ð’ÑÐµ Ð¿Ð»Ð°Ð½Ñ‹ + ÐºÑƒÑ€ÑÑ‹\n", "Applies to: All plans + courses\n")
        elif applies_to == 'chat':
            text += ui_text(lang, "Der: tikai plÄniem\n", "ÐŸÑ€Ð¸Ð¼ÐµÐ½ÑÐµÑ‚ÑÑ: Ð¢Ð¾Ð»ÑŒÐºÐ¾ Ð¿Ð»Ð°Ð½Ñ‹\n", "Applies to: Plans only\n")
        elif applies_to == 'courses':
            text += ui_text(lang, "Der: tikai kursiem\n", "ÐŸÑ€Ð¸Ð¼ÐµÐ½ÑÐµÑ‚ÑÑ: Ð¢Ð¾Ð»ÑŒÐºÐ¾ ÐºÑƒÑ€ÑÑ‹\n", "Applies to: Courses only\n")
        
        # Expiry
        if expires_at:
            expiry_dt = datetime.fromisoformat(expires_at)
            time_left = expiry_dt - datetime.utcnow()
            
            if time_left.total_seconds() > 0:
                hours_left = int(time_left.total_seconds() / 3600)
                if lang == 'ru':
                    text += f"Ð˜ÑÑ‚ÐµÐºÐ°ÐµÑ‚: â° Ñ‡ÐµÑ€ÐµÐ· {hours_left} Ñ‡Ð°ÑÐ¾Ð²\n"
                elif lang == 'lv':
                    text += f"Beidzas: â° pÄ“c {hours_left} stundÄm\n"
                else:
                    text += f"Expires: â° in {hours_left} hours\n"
        else:
            # Tier-based
            if lang == 'ru':
                text += f"Ð”ÐµÐ¹ÑÑ‚Ð²ÑƒÐµÑ‚: ÐŸÐ¾ÐºÐ° ÑÑ‚Ð°Ñ‚ÑƒÑ Ð°ÐºÑ‚Ð¸Ð²ÐµÐ½\n"
            elif lang == 'lv':
                text += f"DerÄ«gs: kamÄ“r statuss ir aktÄ«vs\n"
            else:
                text += f"Valid: While status active\n"
        
        # Uses
        if max_uses:
            remaining = max_uses - times_used
            if lang == 'ru':
                text += f"ÐžÑÑ‚Ð°Ð»Ð¾ÑÑŒ: {remaining} Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ\n"
            elif lang == 'lv':
                text += f"Atlicis: {remaining} lietojums\n"
            else:
                text += f"Remaining: {remaining} use(s)\n"
        else:
            if lang == 'ru':
                text += f"Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ð¹: Ð‘ÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ‚ â™¾\n"
            elif lang == 'lv':
                text += f"Lietojumi: bez limita â™¾\n"
            else:
                text += f"Uses: Unlimited â™¾\n"
        
        text += "\n"
        
        # Copy button
        keyboard.button(
            text=f"ðŸ“‹ {code[:20]}{'...' if len(code) > 20 else ''}",
            callback_data=f"copy_{code}"
        )
    
    text += "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
    
    if lang == 'ru':
        text += "â„¹ï¸ Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ Ð¿Ñ€Ð¾Ð¼Ð¾ÐºÐ¾Ð´ Ð¿Ñ€Ð¸ Ð¾Ð¿Ð»Ð°Ñ‚Ðµ\n   Ð´Ð»Ñ Ð¿Ð¾Ð»ÑƒÑ‡ÐµÐ½Ð¸Ñ ÑÐºÐ¸Ð´ÐºÐ¸"
    elif lang == 'lv':
        text += "â„¹ï¸ Izmanto promokodu apmaksas laikÄ,\n   lai saÅ†emtu atlaidi"
    else:
        text += "â„¹ï¸ Use promo code at checkout\n   to get your discount"
    
    keyboard.button(text=back_button_text(lang), callback_data="loyalty_main")
    keyboard.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
    await callback.answer()



@dp.callback_query(F.data == "loyalty_main")
async def loyalty_main_back(callback: CallbackQuery):
    """ÐÐ°Ð·Ð°Ð´ no promo kodiem uz loyalty status â€” reuse loyalty_status_callback"""
    await loyalty_status_callback(callback)


@dp.callback_query(F.data == "start_back")
async def start_back_callback(callback: CallbackQuery):
    """ÐÐ°Ð·Ð°Ð´ uz galveno menu"""
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
        tier_emoji = tier_data.get('emoji', 'ðŸŒ±')
        tier_tag = tier_data.get('tag', 'Rookie')
        if lang == "ru":
            loyalty_line = f"\n\n{tier_emoji} Ранг: *{tier_tag}*"
        elif lang == "lv":
            loyalty_line = f"\n\n{tier_emoji} Rangs: *{tier_tag}*"
        else:
            loyalty_line = f"\n\n{tier_emoji} Rank: *{tier_tag}*"
        welcome_text = t(lang, "active_sub", name=name, expires=expires_dt.strftime("%d.%m.%Y"), plan=user.get("plan_name", "â€”"), days=days_left) + loyalty_line
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
    await callback.answer(f"âœ… {code}", show_alert=True, cache_time=1)


@dp.callback_query(F.data == "winback_survey")
async def show_winback_survey(callback: CallbackQuery):
    """Show win-back survey"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'lv') if user else 'lv'
    await callback.answer(
        ui_text(
            lang,
            "Šī aptaujas plūsma pašlaik ir izslēgta.",
            "Эта ветка опроса сейчас отключена.",
            "This survey flow is currently disabled.",
        ),
        show_alert=True,
    )
    return
    
    if lang == 'ru':
        text = """ðŸ“Š ÐŸÐ¾Ñ‡ÐµÐ¼Ñƒ ÑƒÑˆÑ‘Ð»? ÐŸÐ¾Ð¼Ð¾Ð³Ð¸ Ð½Ð°Ð¼ ÑÑ‚Ð°Ñ‚ÑŒ Ð»ÑƒÑ‡ÑˆÐµ!

Ð’Ñ‹Ð±ÐµÑ€Ð¸ Ð¿Ñ€Ð¸Ñ‡Ð¸Ð½Ñƒ (Ð¸Ð»Ð¸ Ð½Ð°Ð¿Ð¸ÑˆÐ¸ ÑÐ²Ð¾ÑŽ):"""
    elif lang == 'lv':
        text = """ðŸ“Š KÄpÄ“c aizgÄji? PalÄ«dzi mums kÄ¼Å«t labÄkiem!

IzvÄ“lies iemeslu vai uzraksti savu:"""
    else:
        text = """ðŸ“Š Why did you leave? Help us improve!

Choose a reason (or write your own):"""
    
    b = InlineKeyboardBuilder()
    
    if lang == 'ru':
        b.button(text="ðŸ’¸ Ð¡Ð»Ð¸ÑˆÐºÐ¾Ð¼ Ð´Ð¾Ñ€Ð¾Ð³Ð¾", callback_data="survey_expensive")
        b.button(text="ðŸ“‰ ÐœÐ°Ð»Ð¾ ÐºÐ¾Ð½Ñ‚ÐµÐ½Ñ‚Ð°", callback_data="survey_content")
        b.button(text="â° ÐÐµÑ‚ Ð²Ñ€ÐµÐ¼ÐµÐ½Ð¸", callback_data="survey_time")
        b.button(text="â“ ÐÐµ Ð¿Ð¾Ð½ÑÐ» ÐºÐ°Ðº Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÑŒÑÑ", callback_data="survey_confused")
        b.button(text="ðŸ“ Ð”Ñ€ÑƒÐ³Ð¾Ðµ (Ð½Ð°Ð¿Ð¸ÑˆÐ¸)", callback_data="survey_custom")
    elif lang == 'lv':
        b.button(text="ðŸ’¸ PÄrÄk dÄrgi", callback_data="survey_expensive")
        b.button(text="ðŸ“‰ Par maz vÄ“rtÄ«bas", callback_data="survey_content")
        b.button(text="â° Nav laika", callback_data="survey_time")
        b.button(text="â“ Nesapratu, kÄ lietot", callback_data="survey_confused")
        b.button(text="ðŸ“ Cits iemesls", callback_data="survey_custom")
    else:
        b.button(text="ðŸ’¸ Too expensive", callback_data="survey_expensive")
        b.button(text="ðŸ“‰ Not enough value", callback_data="survey_content")
        b.button(text="â° No time", callback_data="survey_time")
        b.button(text="â“ Didn't understand", callback_data="survey_confused")
        b.button(text="ðŸ“ Other (write)", callback_data="survey_custom")
    
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
    lang = user.get('lang', 'lv') if user else 'lv'
    await state.clear()
    await callback.answer(
        ui_text(
            lang,
            "Šī aptaujas plūsma pašlaik ir izslēgta.",
            "Эта ветка опроса сейчас отключена.",
            "This survey flow is currently disabled.",
        ),
        show_alert=True,
    )
    return
    
    response_type = callback.data[7:]  # Remove "survey_"
    
    if response_type == 'custom':
        if lang == 'ru':
            text = "ðŸ“ *ÐÐ°Ð¿Ð¸ÑˆÐ¸ ÑÐ²Ð¾ÑŽ Ð¿Ñ€Ð¸Ñ‡Ð¸Ð½Ñƒ:*\n\n/cancel Ð´Ð»Ñ Ð¾Ñ‚Ð¼ÐµÐ½Ñ‹"
        elif lang == 'lv':
            text = "ðŸ“ *Uzraksti savu iemeslu:*\n\n/cancel lai atceltu"
        else:
            text = "ðŸ“ *Write your reason:*\n\n/cancel to cancel"
        await state.set_state(SurveyCustomState.waiting_text)
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()
        return
    
    # Generate reward coupon
    coupon_code = "DISABLED"
    
    # Save response
    await db.save_survey_response(user_id, response_type, coupon_code)
    
    if lang == 'ru':
        text = f"""ðŸŽ *Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¾Ñ‚Ð²ÐµÑ‚!*

Ð¢Ð²Ð¾Ñ Ð½Ð°Ð³Ñ€Ð°Ð´Ð°:
ðŸ’³ ÐšÐ¾Ð´: `{coupon_code}`
ðŸ’° Ð¡ÐºÐ¸Ð´ÐºÐ°: *20%* Ð½Ð° Ð²ÑÑ‘
â° Ð”ÐµÐ¹ÑÑ‚Ð²ÑƒÐµÑ‚: 24 Ñ‡Ð°ÑÐ°

Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹ Ð¿Ñ€Ð¸ Ð¾Ð¿Ð»Ð°Ñ‚Ðµ!

[ðŸ’Ž ÐŸÐµÑ€ÐµÐ¹Ñ‚Ð¸ Ðº Ñ‚Ð°Ñ€Ð¸Ñ„Ð°Ð¼]"""
    elif lang == 'lv':
        text = f"""ðŸŽ *Paldies par atbildi!*

Tava balva:
ðŸ’³ Kods: `{coupon_code}`
ðŸ’° Atlaide: *20%* visam
â° DerÄ«gs: 24 stundas

Izmanto apmaksas laikÄ!

[ðŸ’Ž PÄriet uz tarifiem]"""
    else:
        text = f"""ðŸŽ *Thanks for your feedback!*

Your reward:
ðŸ’³ Code: `{coupon_code}`
ðŸ’° Discount: *20%* on everything
â° Valid: 24 hours

Use at checkout!

[ðŸ’Ž Go to plans]"""
    
    b = InlineKeyboardBuilder()
    b.button(text=ui_text(lang, "ðŸ’Ž Tarifi", "ðŸ’Ž Ð¢Ð°Ñ€Ð¸Ñ„Ñ‹", "ðŸ’Ž Plans"),
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer("âœ…")


@dp.message(SurveyCustomState.waiting_text)
async def survey_custom_text(message: Message, state: FSMContext):
    """SaÅ†em custom survey atbildi"""
    user = await db.get_user(message.from_user.id)
    lang = user.get('lang', 'lv') if user else 'lv'
    await state.clear()
    await message.answer(
        ui_text(
            lang,
            "Šī aptaujas plūsma pašlaik ir izslēgta.",
            "Эта ветка опроса сейчас отключена.",
            "This survey flow is currently disabled.",
        )
    )
    return

    user_id = message.from_user.id
    custom_text = message.text[:500]  # LimitÄ“t garumu
    await state.clear()
    
    coupon_code = "DISABLED"
    await db.save_survey_response(user_id, custom_text, coupon_code)
    
    if lang == 'ru':
        text = (
            f"ðŸŽ *Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¾Ñ‚Ð²ÐµÑ‚!*\n\n"
            f"Ð¢Ð²Ð¾Ñ Ð½Ð°Ð³Ñ€Ð°Ð´Ð°:\n"
            f"ðŸ’³ ÐšÐ¾Ð´: `{coupon_code}`\n"
            f"ðŸ’° Ð¡ÐºÐ¸Ð´ÐºÐ°: *20%* Ð½Ð° Ð²ÑÑ‘\n"
            f"â° Ð”ÐµÐ¹ÑÑ‚Ð²ÑƒÐµÑ‚: 24 Ñ‡Ð°ÑÐ°"
        )
    elif lang == 'lv':
        text = (
            f"ðŸŽ *Paldies par atbildi!*\n\n"
            f"Tava balva:\n"
            f"ðŸ’³ Kods: `{coupon_code}`\n"
            f"ðŸ’° Atlaide: *20%* visam\n"
            f"â° DerÄ«gs: 24 stundas"
        )
    else:
        text = (
            f"ðŸŽ *Thank you for your feedback!*\n\n"
            f"Your reward:\n"
            f"ðŸ’³ Code: `{coupon_code}`\n"
            f"ðŸ’° Discount: *20%* on everything\n"
            f"â° Valid: 24 hours"
        )
    
    b = InlineKeyboardBuilder()
    b.button(text=ui_text(lang, "ðŸ’Ž Tarifi", "ðŸ’Ž Ð¢Ð°Ñ€Ð¸Ñ„Ñ‹", "ðŸ’Ž Plans"), callback_data="vip_chat_plans")
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
        product_meta = resolve_subscription_product(product_key, "lv")
        if product_meta:
            localized_name = product_meta.get("name", {})
            plan = {
                "name": {
                    "lv": localized_name.get("lv", product_key or "Website subscription"),
                    "ru": localized_name.get("ru", product_key or "Website subscription"),
                    "en": localized_name.get("en", product_key or "Website subscription"),
                },
                "days": int(days_raw or 0),
                "price_usdt": float(payload.get("amount") or payload.get("amount_usd") or payload.get("amount_usdt") or 0),
                "emoji": "🌐",
            }
        elif not days_raw and not (
            payload.get("expires_at")
            or payload.get("expires_date")
            or payload.get("subscription_expires_at")
            or payload.get("subscription_expires")
            or payload.get("valid_until")
            or payload.get("expiry_date")
        ):
            return None, None, "unknown_product"
        else:
            plan = {
                "name": {
                    "lv": product_key or "Website subscription",
                    "ru": product_key or "Website subscription",
                    "en": product_key or "Website subscription",
                },
                "days": int(days_raw or 0),
                "price_usdt": float(payload.get("amount") or 0),
                "emoji": "🌐",
            }
    if days_raw:
        plan["days"] = int(days_raw)
    return product_key or "website_subscription", plan, None


def _webhook_expiry_from_payload(payload: dict):
    raw = (
        payload.get("expires_at")
        or payload.get("expires_date")
        or payload.get("subscription_expires_at")
        or payload.get("subscription_expires")
        or payload.get("valid_until")
        or payload.get("expiry_date")
    )
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        if len(normalized) == 10:
            return datetime.fromisoformat(normalized + "T23:59:59")
        return datetime.fromisoformat(normalized)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt in ("%d.%m.%Y", "%Y/%m/%d"):
                return parsed.replace(hour=23, minute=59, second=59)
            return parsed
        except Exception:
            continue
    return None


_BULK_WEBHOOK_KEYS = ("subscribers", "users", "items", "purchases")


def _bulk_webhook_items(payload):
    if isinstance(payload, list):
        return {}, payload
    if not isinstance(payload, dict):
        return None, None
    for key in _BULK_WEBHOOK_KEYS:
        items = payload.get(key)
        if isinstance(items, list):
            defaults = {k: v for k, v in payload.items() if k not in _BULK_WEBHOOK_KEYS}
            return defaults, items
    return None, None


async def _process_website_purchase_payload(payload: dict, raw_body: bytes):
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": "invalid_payload",
            "error": "invalid_payload",
            "message": "Webhook payload must be a JSON object.",
        }, 400

    email = str(payload.get("email") or payload.get("user_email") or "").strip().lower()
    payment_system = str(payload.get("payment_system") or payload.get("payment_method") or "").strip()
    event_id = str(payload.get("event_id") or payload.get("order_id") or payload.get("payment_id") or "").strip()
    try:
        amount = float(payload.get("amount") or payload.get("amount_usd") or payload.get("amount_usdt") or 0)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "status": "invalid_amount",
            "error": "invalid_amount",
            "message": "Webhook amount must be numeric when provided.",
            "email": email,
        }, 400
    try:
        product_key, plan, plan_error = _webhook_plan_from_payload(payload)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "status": "invalid_product",
            "error": "invalid_product",
            "message": "Webhook product/subscription_days could not be parsed.",
            "email": email,
        }, 400
    explicit_expires_at = _webhook_expiry_from_payload(payload)
    raw_expires_value = (
        payload.get("expires_at")
        or payload.get("expires_date")
        or payload.get("subscription_expires_at")
        or payload.get("subscription_expires")
        or payload.get("valid_until")
        or payload.get("expiry_date")
    )

    if not email or "@" not in email:
        return {
            "ok": False,
            "status": "email_required",
            "error": "email_required",
            "message": "A valid e-mail is required in webhook payload.",
        }, 400
    if plan_error:
        return {
            "ok": False,
            "status": "invalid_product",
            "error": plan_error,
            "message": f"Webhook payload could not be mapped to a valid product: {plan_error}.",
            "email": email,
        }, 400
    if raw_expires_value and explicit_expires_at is None:
        return {
            "ok": False,
            "status": "invalid_expires_at",
            "error": "invalid_expires_at",
            "message": "Webhook expires_at/expires_date format could not be parsed.",
            "received_value": str(raw_expires_value),
            "email": email,
            "product_key": product_key,
        }, 400
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
        return response, 200

    user = await db.get_user_by_email(email)
    if not user:
        product_meta = await resolve_subscription_product_any(product_key, "lv")
        pending_existing = await db.get_pending_email_subscription(email, product_key)
        now = datetime.utcnow()
        if explicit_expires_at is not None:
            if explicit_expires_at.tzinfo is not None:
                explicit_expires_at = explicit_expires_at.astimezone(timezone.utc).replace(tzinfo=None)
            pending_expires = explicit_expires_at
        elif pending_existing and pending_existing.get("expires_at"):
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
                amount_usdt=amount,
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
        return {
            "ok": True,
            "status": "pending_email_claim",
            "message": "Purchase was received and saved by e-mail. It will be attached when the user registers in the bot with this e-mail.",
            "telegram_linked": False,
            "email": email,
            "product_key": product_key,
            "event_id": event_id,
            "amount": amount,
            "expires_at": pending_expires.isoformat(),
        }, 200

    lang = user.get("lang", "ru")
    username = user.get("username") or ""
    try:
        new_exp, plan_name, product_meta = await _do_activate(
            user["user_id"],
            product_key,
            plan,
            lang,
            username,
            tx_hash,
            amount,
            explicit_expires_at=explicit_expires_at,
        )
    except Exception:
        await notify_admins_error(f"webhook_activate user={user['user_id']} product={product_key}", "Failed to activate purchase from webhook")
        await db.delete_webhook_event(event_key)
        raise

    try:
        invite = await invite_text_for_product(
            user["user_id"],
            lang,
            product_meta,
            new_exp,
            debug_source=f"webhook_paid email={email} product={product_key}",
        )
        if invite:
            paid_text = paid_invite_message(lang, plan_name, new_exp, invite)
        else:
            paid_text = await override_text(
                "payment_success",
                lang,
                t(lang, "paid_ok", name=plan_name, expires=new_exp.strftime("%d.%m.%Y"), tx=event_id[:20]),
                name=plan_name,
                expires=new_exp.strftime("%d.%m.%Y"),
                tx=event_id[:20],
            )
        await bot.send_message(user["user_id"], paid_text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Failed to notify webhook buyer {user['user_id']}: {e}")
        await notify_admins_error(f"webhook_notify_user user={user['user_id']} product={product_key}", e)

    return {
        "ok": True,
        "status": "processed",
        "message": "Webhook received and purchase processed successfully.",
        "telegram_linked": True,
        "telegram_user_id": user["user_id"],
        "telegram_username": user.get("username") or "",
        "email": email,
        "product_key": product_key,
        "event_id": event_id,
        "amount": amount,
        "expires_at": new_exp.isoformat(),
    }, 200


async def _process_bulk_website_purchase_payload(defaults: dict, items: list, raw_body: bytes):
    batch_id = str(
        defaults.get("batch_id")
        or defaults.get("event_id")
        or defaults.get("order_id")
        or hashlib.sha256(raw_body).hexdigest()[:16]
    )
    results = []
    success_count = 0
    failed_count = 0
    duplicate_count = 0

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            failed_count += 1
            results.append({
                "index": index,
                "ok": False,
                "status": "invalid_item",
                "message": "Each bulk item must be a JSON object.",
            })
            continue

        item_has_event_id = bool(item.get("event_id") or item.get("order_id") or item.get("payment_id"))
        merged = dict(defaults)
        merged.update(item)
        if not item_has_event_id:
            merged.pop("event_id", None)
            merged.pop("order_id", None)
            merged.pop("payment_id", None)
            item_fingerprint = hashlib.sha256(
                json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:12]
            merged["event_id"] = f"{batch_id}:{index}:{item_fingerprint}"

        item_body = json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            result, status_code = await _process_website_purchase_payload(merged, item_body)
        except Exception as e:
            failed_count += 1
            email = str(merged.get("email") or merged.get("user_email") or "").strip().lower()
            await notify_admins_error(f"bulk_webhook_item index={index} email={email or '-'}", e)
            results.append({
                "index": index,
                "ok": False,
                "status": "internal_error",
                "message": str(e)[:300],
                "email": email,
            })
            continue

        compact = {
            "index": index,
            "ok": bool(result.get("ok")),
            "status": result.get("status"),
            "email": result.get("email"),
            "product_key": result.get("product_key"),
            "telegram_linked": result.get("telegram_linked", False),
            "event_id": result.get("event_id"),
        }
        if result.get("telegram_user_id"):
            compact["telegram_user_id"] = result.get("telegram_user_id")
        if result.get("expires_at"):
            compact["expires_at"] = result.get("expires_at")
        results.append(compact)

        if result.get("status") == "duplicate":
            duplicate_count += 1
        elif status_code >= 400 or not result.get("ok"):
            failed_count += 1
        else:
            success_count += 1

    return web.json_response({
        "ok": failed_count == 0,
        "status": "bulk_processed",
        "batch_id": batch_id,
        "total": len(items),
        "processed": success_count,
        "duplicates": duplicate_count,
        "failed": failed_count,
        "results": results[:200],
        "results_truncated": len(results) > 200,
    }, status=200 if failed_count < len(items) else 400)


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

    defaults, bulk_items = _bulk_webhook_items(payload)
    if bulk_items is not None:
        return await _process_bulk_website_purchase_payload(defaults, bulk_items, raw_body)

    response, status_code = await _process_website_purchase_payload(payload, raw_body)
    return web.json_response(response, status=status_code)


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

    # Admins are always in the friend list.
    for admin_id in config.ADMIN_IDS:
        await db.register_user_as_friend(admin_id)
    old_monthly_price = await db.get_setting("price_monthly")
    if old_monthly_price:
        try:
            if float(old_monthly_price) == 10.0:
                await db.set_setting("price_monthly", "9.9")
        except Exception:
            pass
    for pk, plan in config.PLANS.items():
        sp = await db.get_setting(f"price_{pk}")
        if sp:
            try:
                p = float(sp)
                plan['price_usdt'] = p
                plan['price_usd'] = f"{p:.0f} EUR" if p == int(p) else f"{p} EUR"
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
    scheduler.start()
    logger.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        await webhook_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
