import os
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    CHAT_ID: int = int(os.getenv("CHAT_ID", "-1001234567890"))
    CHAT_LINK: str = os.getenv("CHAT_LINK", "https://t.me/+xxxx")
    CRYPTO_WALLET: str = os.getenv("CRYPTO_WALLET", "0xYourBEP20WalletHere")

    # Support kontakts — @username vai grupa
    SUPPORT_CONTACT: str = os.getenv("SUPPORT_CONTACT", "@YourSupportBot")

    # MegaNode (BSCTrace) — BEZMAKSAS: https://dashboard.nodereal.io
    MEGANODE_API_KEY: str = os.getenv("MEGANODE_API_KEY", "")

    # Etherscan V2 — BSC prasa MAKSAS plānu
    BSCSCAN_API_KEY: str = os.getenv("BSCSCAN_API_KEY", "")

    # USDT BEP-20 contract (BSC mainnet)
    USDT_CONTRACT: str = "0x55d398326f99059fF775485246999027B3197955"

    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()
    ])

    PLANS: Dict[str, Any] = field(default_factory=lambda: {
        "monthly": {
            "name": {"ru": "1 Месяц", "en": "1 Month"},
            "price_usd": "10$",
            "price_usdt": 10.0,
            "days": 30,
            "emoji": "📅",
        },
        "halfyear": {
            "name": {"ru": "Полгода", "en": "6 Months"},
            "price_usd": "55$",
            "price_usdt": 55.0,
            "days": 180,
            "emoji": "⭐",
        },
        "yearly": {
            "name": {"ru": "1 Год", "en": "1 Year"},
            "price_usd": "100$",
            "price_usdt": 100.0,
            "days": 365,
            "emoji": "🔥",
        },
        "lifetime": {
            "name": {"ru": "Навсегда", "en": "Lifetime"},
            "price_usd": "500$",
            "price_usdt": 500.0,
            "days": 36500,
            "emoji": "💎",
        },
    })

    COURSES: Dict[str, Any] = field(default_factory=lambda: {
        "mini": {
            "name": {"ru": "Мини курс", "en": "Mini Course"},
            "price_usd": "25$",
            "price_usdt": 25.0,
            "emoji": "📘",
        },
        "basic": {
            "name": {"ru": "Базовый курс", "en": "Basic Course"},
            "price_usd": "75$",
            "price_usdt": 75.0,
            "emoji": "📗",
        },
        "full": {
            "name": {"ru": "Полный курс", "en": "Full Course"},
            "price_usd": "150$",
            "price_usdt": 150.0,
            "emoji": "📕",
        },
        "autotrading": {
            "name": {"ru": "Автотрейдинг курс", "en": "Autotrading Course"},
            "price_usd": "200$",
            "price_usdt": 200.0,
            "emoji": "🤖",
        },
        "vip": {
            "name": {"ru": "VIP курс", "en": "VIP Course"},
            "price_usd": "5000$",
            "price_usdt": 5000.0,
            "emoji": "👑",
        },
    })

    # Referral komisijas procenti
    REFERRAL_COMMISSION_COURSES: int = 15  # 15% par kursiem
    REFERRAL_COMMISSION_CHAT: int = 20     # 20% par chat subscription
    
    # Minimālā withdrawal summa USD
    MIN_WITHDRAWAL_AMOUNT: float = 50.0
    
    # Referral bonus dienas (chat subscription)
    REFERRAL_BONUS_DAYS: int = 10  # 10 dienas par chat subscription

    
    # ═══════════════════════════════════════════════════════════════
    # LOYALTY SYSTEM CONFIGURATION
    # ═══════════════════════════════════════════════════════════════
    
    LOYALTY_TIERS: Dict[str, Any] = field(default_factory=lambda: {
        "rookie": {
            "min_months": 0,
            "max_months": 3,
            "chat_discount": 0,
            "course_discount": 0,
            "bonus_days": 0,
            "tag": "Rookie",
            "emoji": "🌱",
        },
        "active": {
            "min_months": 3,
            "max_months": 6,
            "chat_discount": 5,
            "course_discount": 5,
            "bonus_days": 5,
            "tag": "Active Trader",
            "emoji": "🔥",
        },
        "pro": {
            "min_months": 6,
            "max_months": 12,
            "chat_discount": 7,
            "course_discount": 7,
            "bonus_days": 10,
            "tag": "Pro Trader",
            "emoji": "⭐",
        },
        "elite": {
            "min_months": 12,
            "max_months": 13,
            "chat_discount": 10,
            "course_discount": 10,
            "bonus_days": 15,
            "free_course": "powerup",
            "tag": "Elite Trader",
            "emoji": "👑",
        },
        "master": {
            "min_months": 13,
            "max_months": 18,
            "chat_discount": 15,
            "course_discount": 15,
            "bonus_days": 20,
            "tag": "Master Trader",
            "emoji": "💎",
        },
        "legend": {
            "min_months": 18,
            "max_months": 999,
            "chat_discount": 20,
            "course_discount": 20,
            "bonus_days": 30,
            "tag": "Legend Trader",
            "emoji": "🔱",
        },
    })
    
    # Consecutive months calculation
    CONSECUTIVE_GAP_THRESHOLD: int = 7  # days
    
    # Loyalty reset
    LOYALTY_RESET_DAYS: int = 30
    LOYALTY_RESET_GRACE_HOURS: int = 6
    
    # Reminders
    REMINDER_BONUS_DAYS: int = 5
    REMINDER_COUPON_DISCOUNT: int = 5
    REMINDER_COUPON_HOURS: int = 24
    YEARLY_REMINDER_DAYS: List[int] = field(default_factory=lambda: [30, 7, 3, 1])
    MONTHLY_REMINDER_DAYS: List[int] = field(default_factory=lambda: [7, 3, 1])
    
    # Win-back
    WINBACK_TRIGGER_DAYS: int = 5
    WINBACK_MAX_PER_YEAR: int = 2
    WINBACK_YEARLY_DISCOUNT: int = 10
    SURVEY_REWARD_DISCOUNT: int = 20
    SURVEY_REWARD_HOURS: int = 24

    def __post_init__(self):
        if self.CRYPTO_WALLET.startswith("0xYour"):
            logger.error("❌ CRYPTO_WALLET nav iestatīts!")
        if self.MEGANODE_API_KEY:
            logger.info(f"✅ MegaNode key: {self.MEGANODE_API_KEY[:8]}...")
        logger.info(f"CONFIG: wallet={self.CRYPTO_WALLET[:16]}... support={self.SUPPORT_CONTACT}")


config = Config()
