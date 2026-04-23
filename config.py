import os
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Deploy trigger: no behavior change.

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    CHAT_ID: int = int(os.getenv("CHAT_ID", "-1001234567890"))
    CHAT_LINK: str = os.getenv("CHAT_LINK", "https://t.me/+xxxx")
    CHAT_IDS: Dict[str, int] = field(default_factory=lambda: {
        lang: int(os.getenv(f"CHAT_ID_{lang.upper()}", os.getenv("CHAT_ID", "-1001234567890")))
        for lang in ("lv", "en", "ru")
    })
    CHAT_LINKS: Dict[str, str] = field(default_factory=lambda: {
        lang: os.getenv(f"CHAT_LINK_{lang.upper()}", os.getenv("CHAT_LINK", "https://t.me/+xxxx"))
        for lang in ("lv", "en", "ru")
    })
    SCANNER_CHAT_ID: int = int(os.getenv("SCANNER_CHAT_ID", "0"))
    SCANNER_CHAT_LINK: str = os.getenv("SCANNER_CHAT_LINK", "https://t.me/promarketscanner")
    CRYPTO_WALLET: str = os.getenv("CRYPTO_WALLET", "0xYourBEP20WalletHere")

    # Website purchase webhook
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook/purchase")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # Support kontakts — @username vai grupa
    SUPPORT_CONTACT: str = os.getenv("SUPPORT_CONTACT", "https://t.me/mntrade_support")

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
            "name": {"ru": "1 Месяц", "en": "1 Month", "lv": "1 mēnesis"},
            "price_usd": "10€",
            "price_usdt": 10.0,
            "days": 30,
            "emoji": "📅",
        },
    })

    COURSES: Dict[str, Any] = field(default_factory=lambda: {
        "mini": {
            "name": {"ru": "Мини курс", "en": "Mini Course", "lv": "Mini kurss"},
            "price_usd": "99 EUR",
            "price_usdt": 99.0,
            "emoji": "📘",
        },
        "basic": {
            "name": {"ru": "Базовый курс", "en": "Basic Course", "lv": "Pamata kurss"},
            "price_usd": "499 EUR",
            "price_usdt": 499.0,
            "emoji": "📗",
        },
        "full": {
            "name": {"ru": "Полный курс", "en": "Full Course", "lv": "Pilnais kurss"},
            "price_usd": "990 EUR",
            "price_usdt": 990.0,
            "emoji": "📕",
        },
        "autotrading": {
            "name": {"ru": "Автотрейдинг курс", "en": "Autotrading Course", "lv": "Autotrading kurss"},
            "price_usd": "499 EUR",
            "price_usdt": 499.0,
            "emoji": "🤖",
        },
        "vip": {
            "name": {"ru": "VIP курс - приватный менторинг", "en": "VIP Course - private mentoring", "lv": "VIP Kurss - privāts mentorings"},
            "price_usd": "4990 EUR",
            "price_usdt": 4990.0,
            "emoji": "👑",
        },
    })

    # Referral bonus days. Referrals no longer earn money or discounts.
    REFERRAL_COMMISSION_COURSES: int = 0
    REFERRAL_COMMISSION_CHAT: int = 0
    
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
            "chat_discount": 0,
            "course_discount": 0,
            "bonus_days": 5,
            "tag": "Active Trader",
            "emoji": "🔥",
        },
        "pro": {
            "min_months": 6,
            "max_months": 12,
            "chat_discount": 0,
            "course_discount": 0,
            "bonus_days": 10,
            "tag": "Pro Trader",
            "emoji": "⭐",
        },
        "elite": {
            "min_months": 12,
            "max_months": 13,
            "chat_discount": 0,
            "course_discount": 0,
            "bonus_days": 15,
            "free_course": "powerup",
            "tag": "Elite Trader",
            "emoji": "👑",
        },
        "master": {
            "min_months": 13,
            "max_months": 18,
            "chat_discount": 0,
            "course_discount": 0,
            "bonus_days": 20,
            "tag": "Master Trader",
            "emoji": "💎",
        },
        "legend": {
            "min_months": 18,
            "max_months": 999,
            "chat_discount": 0,
            "course_discount": 0,
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

    def chat_id_for_lang(self, lang: str) -> int:
        return self.CHAT_IDS.get(lang, self.CHAT_ID)

    def chat_link_for_lang(self, lang: str) -> str:
        return self.CHAT_LINKS.get(lang, self.CHAT_LINK)

    def all_chat_ids(self) -> List[int]:
        return list(dict.fromkeys([self.CHAT_ID, *self.CHAT_IDS.values()]))


config = Config()
