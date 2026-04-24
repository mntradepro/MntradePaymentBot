import aiosqlite
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


def _default_db_path() -> str:
    # Railway persistent volumes are commonly mounted at /data. Prefer it when present.
    if Path("/data").exists():
        return "/data/subscriptions.db"
    return "/app/data/subscriptions.db"


DB_PATH = os.getenv("DB_PATH") or os.getenv("DATABASE_PATH") or _default_db_path()


class Database:
    def __init__(self):
        self.db_path = DB_PATH

    def _ensure_db_dir(self):
        db_dir = Path(self.db_path).expanduser().parent
        if str(db_dir) and str(db_dir) != ".":
            db_dir.mkdir(parents=True, exist_ok=True)
        target = Path(self.db_path)
        old_runtime_db = Path("/app/data/subscriptions.db")
        if target == Path("/data/subscriptions.db") and old_runtime_db.exists() and not target.exists():
            import shutil
            shutil.copy2(old_runtime_db, target)
            logger.info("Copied existing database from /app/data to /data volume")

    async def init(self):
        self._ensure_db_dir()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id      INTEGER PRIMARY KEY,
                    username     TEXT,
                    first_name   TEXT,
                    lang         TEXT DEFAULT 'ru',
                    plan_key     TEXT,
                    plan_name    TEXT,
                    activated_at TEXT,
                    expires_at   TEXT,
                    is_active    INTEGER DEFAULT 0,
                    tx_hash      TEXT,
                    email        TEXT,
                    email_registered_at TEXT,
                    last_seen_at TEXT,
                    created_at   TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_payments (
                    user_id     INTEGER PRIMARY KEY,
                    plan_key    TEXT,
                    amount_usdt REAL,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER,
                    plan_key    TEXT,
                    plan_name   TEXT,
                    amount_usdt REAL,
                    tx_hash     TEXT,
                    paid_at     TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS used_transactions (
                    tx_hash TEXT PRIMARY KEY,
                    user_id INTEGER,
                    used_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status_expires ON users(is_active, expires_at)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id    TEXT PRIMARY KEY,
                    email       TEXT NOT NULL,
                    product_key TEXT NOT NULL,
                    payment_system TEXT,
                    payload     TEXT,
                    processed_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    product_key   TEXT NOT NULL,
                    product_name  TEXT,
                    chat_id       INTEGER,
                    chat_link     TEXT,
                    activated_at  TEXT NOT NULL,
                    expires_at    TEXT NOT NULL,
                    is_active     INTEGER DEFAULT 1,
                    tx_hash       TEXT,
                    payment_system TEXT,
                    UNIQUE(user_id, product_key)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_active ON user_subscriptions(user_id, is_active, expires_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_subscriptions_chat_active ON user_subscriptions(chat_id, is_active, expires_at)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_reminders (
                    user_id     INTEGER,
                    days_before INTEGER,
                    sent_date   TEXT,
                    PRIMARY KEY (user_id, days_before, sent_date)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_event_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type  TEXT NOT NULL,
                    user_id     INTEGER,
                    event_date  TEXT NOT NULL,
                    meta        TEXT,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS marketing_sends (
                    user_id   INTEGER,
                    campaign  TEXT,
                    sent_at   TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, campaign)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS winback_offers (
                    user_id     INTEGER PRIMARY KEY,
                    sent_at     TEXT NOT NULL,
                    expires_at  TEXT NOT NULL,
                    bonus_days  INTEGER NOT NULL DEFAULT 0,
                    redeemed_at TEXT,
                    redeemed_tx TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id   INTEGER NOT NULL,
                    referred_id   INTEGER NOT NULL UNIQUE,
                    bonus_given   INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # Migrācijas — kolonnas
            for col_sql in [
                "ALTER TABLE users ADD COLUMN first_name TEXT",
                "ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'",
                "ALTER TABLE users ADD COLUMN is_friend INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN email TEXT",
                "ALTER TABLE users ADD COLUMN email_registered_at TEXT",
                "ALTER TABLE users ADD COLUMN last_seen_at TEXT",
            ]:
                try:
                    await conn.execute(col_sql)
                except Exception:
                    pass

            # Migrācija — aizpildīt vecos payment_history kur amount_usdt ir NULL
            try:
                await conn.execute(
                    "UPDATE payment_history SET amount_usdt = 0.1 WHERE amount_usdt IS NULL"
                )
                await conn.commit()
                logger.info("Migration: filled NULL amount_usdt in payment_history")
            except Exception as e:
                logger.warning(f"Migration amount_usdt: {e}")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    user_id    INTEGER NOT NULL,
                    month      TEXT NOT NULL,
                    entered_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, month)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS course_purchases (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    username    TEXT,
                    course_key  TEXT NOT NULL,
                    course_name TEXT,
                    amount_usdt REAL DEFAULT 0,
                    tx_hash     TEXT,
                    email       TEXT,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code             TEXT PRIMARY KEY,
                    discount_percent INTEGER NOT NULL,
                    plan_key         TEXT,
                    max_uses         INTEGER DEFAULT 0,
                    used_count       INTEGER DEFAULT 0,
                    expires_at       TEXT,
                    created_at       TEXT DEFAULT (datetime('now'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_promos (
                    user_id    INTEGER PRIMARY KEY,
                    promo_code TEXT,
                    applied_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # ═══════════════════════════════════════════════════════════════
            # JAUNĀS TABULAS - REFERRAL EARNINGS & WITHDRAWAL SYSTEM
            # ═══════════════════════════════════════════════════════════════
            
            # Referral earnings - katrs pirkums kas nesa komisju
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_earnings (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id     INTEGER NOT NULL,
                    referred_id     INTEGER NOT NULL,
                    purchase_id     INTEGER NOT NULL,
                    course_key      TEXT,
                    amount_usd      REAL NOT NULL,
                    commission_usd  REAL NOT NULL,
                    earned_at       TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (purchase_id) REFERENCES course_purchases(id)
                )
            """)
            
            # Withdrawal requests - izmaksu pieprasījumi
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS withdrawal_requests (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL,
                    amount_usd      REAL NOT NULL,
                    wallet_address  TEXT NOT NULL,
                    email           TEXT NOT NULL,
                    status          TEXT DEFAULT 'pending',
                    requested_at    TEXT DEFAULT (datetime('now')),
                    processed_at    TEXT,
                    admin_id        INTEGER,
                    admin_notes     TEXT,
                    rejection_reason TEXT
                )
            """)
            
            # Withdrawal history - vēsture (completed/rejected)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS withdrawal_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL,
                    amount_usd      REAL NOT NULL,
                    wallet_address  TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    requested_at    TEXT,
                    processed_at    TEXT,
                    admin_id        INTEGER,
                    admin_notes     TEXT
                )
            """)
            
            # Fraud alerts - drošības log
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS fraud_alerts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    alert_type  TEXT NOT NULL,
                    description TEXT,
                    detected_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # User bans - bloķētie lietotāji
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_bans (
                    user_id     INTEGER PRIMARY KEY,
                    reason      TEXT,
                    banned_by   INTEGER,
                    banned_at   TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # ═══════════════════════════════════════════════════════════════
            
            # Defaults
            defaults = {
                "reminder_3d_ru": "⚠️ *Подписка истекает через 3 дня!*\n\n📅 Дата: {expires}\n\nПродли подписку:",
                "reminder_3d_en": "⚠️ *Subscription expires in 3 days!*\n\n📅 Date: {expires}\n\nRenew now:",
                "reminder_1d_ru": "🚨 *Подписка истекает ЗАВТРА!*\n\n📅 Дата: {expires}\n\nПродли сейчас:",
                "reminder_1d_en": "🚨 *Subscription expires TOMORROW!*\n\n📅 Date: {expires}\n\nRenew now:",
                "remarket_ru": "👋 Привет! Ты смотрел наш канал, но так и не подписался.\n\n🔥 Присоединяйся — не пожалеешь!",
                "remarket_en": "👋 Hey! You checked our channel but never subscribed.\n\n🔥 Join now — you won't regret it!",
                "remarket_after_expire_ru": "😔 Твоя подписка истекла.\n\n💎 Возвращайся — специально для тебя тарифы ниже:",
                "remarket_after_expire_en": "😔 Your subscription has expired.\n\n💎 Come back — choose your plan:",
                "remarket_after_expire_days": "3",
                "remarketing_reminder_7_ru": "📅 Абонемент закончится через 7 дней!\n\n💰 ПРОДЛИ СЕЙЧАС — получи:\n✅ +{bonus_days} дней бесплатно{coupon_block}{tier_block}",
                "remarketing_reminder_7_en": "📅 Subscription expires in 7 days!\n\n💰 RENEW NOW — get:\n✅ +{bonus_days} days free{coupon_block}{tier_block}",
                "remarketing_reminder_7_lv": "📅 Abonements beigsies pēc 7 dienām!\n\n💰 Pagarini tagad un saņem:\n✅ +{bonus_days} dienas bez maksas{coupon_block}{tier_block}",
                "remarketing_reminder_3_ru": "⚠️ 3 ДНЯ до окончания абонемента!\n\n💰 Самое время продлить и получить:\n✅ +{bonus_days} дней бесплатно{tier_block}",
                "remarketing_reminder_3_en": "⚠️ 3 DAYS until subscription ends!\n\n💰 Time to renew and get:\n✅ +{bonus_days} days free{tier_block}",
                "remarketing_reminder_3_lv": "⚠️ Līdz abonementa beigām palikušas 3 dienas!\n\n💰 Tagad ir īstais brīdis pagarināt un saņemt:\n✅ +{bonus_days} dienas bez maksas{tier_block}",
                "remarketing_reminder_1_ru": "🚨 ПОСЛЕДНИЙ ДЕНЬ!\n\nЗавтра потеряешь:\n❌ Доступ к VIP чату{tier_block}\n\n💡 Продли СЕЙЧАС - не упусти момент!",
                "remarketing_reminder_1_en": "🚨 LAST DAY!\n\nTomorrow you'll lose:\n❌ VIP chat access{tier_block}\n\n💡 RENEW NOW - don't miss out!",
                "remarketing_reminder_1_lv": "🚨 PĒDĒJĀ DIENA!\n\nRīt tu zaudēsi:\n❌ Piekļuvi VIP čatam{tier_block}\n\n💡 Pagarini TAGAD, lai nezaudētu piekļuvi!",
                "remarketing_reminder_30_ru": "📅 Годовой абонемент заканчивается через месяц\n\nℹ️ Напоминание:\nДо окончания подписки осталось 30 дней{tier_block}\n\nЧтобы сохранить статус и привилегии,\nпродли подписку до истечения срока.",
                "remarketing_reminder_30_en": "📅 Yearly subscription expires in a month\n\nℹ️ Reminder:\n30 days until subscription ends{tier_block}\n\nTo keep your status and privileges,\nrenew before expiration.",
                "remarketing_reminder_30_lv": "📅 Gada abonements beigsies pēc mēneša\n\nℹ️ Atgādinājums:\nLīdz abonementa beigām palikušas 30 dienas{tier_block}\n\nLai saglabātu savu statusu un privilēģijas,\npagarini abonementu pirms termiņa beigām.",
                "remarketing_winback_ru": "💔 Мы тебя потеряли...\n\nВернись в MNtradepro VIP с бонусами:\n\n🎁 WELCOME BACK бонусы:\n• {bonus_days} дней БЕСПЛАТНО\n• {yearly_discount}% скидка на год\n• {course_discount}% скидка на курсы\n\n⏰ Предложение {offer_hours} часа",
                "remarketing_winback_en": "💔 We lost you...\n\nReturn to MNtradepro VIP with bonuses:\n\n🎁 WELCOME BACK bonuses:\n• {bonus_days} days FREE\n• {yearly_discount}% discount yearly\n• {course_discount}% discount courses\n\n⏰ Offer valid {offer_hours}h",
                "remarketing_winback_lv": "💔 Mums tevis pietrūkst...\n\nAtgriezies MNtradepro VIP ar bonusiem:\n\n🎁 ATGRIEŠANĀS bonusi:\n• {bonus_days} dienas BEZ MAKSAS\n• {yearly_discount}% atlaide gadam\n• {course_discount}% atlaide kursiem\n\n⏰ Piedāvājums spēkā {offer_hours}h",
                "remarketing_winback_trigger_days": "5",
                "remarketing_winback_bonus_days": "7",
                "remarketing_offer_hours": "72",
            }
            defaults["reminder_0d_ru"] = "⏰ *Подписка истекает СЕГОДНЯ!*\n\n📅 Дата: {expires}\n\nПродли сейчас, чтобы не потерять доступ:"
            defaults["reminder_0d_en"] = "⏰ *Subscription expires TODAY!*\n\n📅 Date: {expires}\n\nRenew now to avoid losing access:"
            for k, v in defaults.items():
                await conn.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)", (k, v))
            await conn.commit()
        
        # Initialize loyalty tables
        await self.init_loyalty_tables()
        logger.info("Database initialized with referral earnings & withdrawal system")

    # ─── USERS ───

    async def get_user(self, user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_user_by_email(self, email: str) -> Optional[Dict]:
        normalized = email.strip().lower()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (normalized,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def register_user(self, user_id: int, username: Optional[str], first_name: Optional[str], lang: str = "ru"):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, lang, is_active, last_seen_at)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, username),
                    first_name = COALESCE(excluded.first_name, first_name),
                    last_seen_at = excluded.last_seen_at
            """, (user_id, username, first_name, lang, now))
            await conn.commit()

    async def set_user_lang(self, user_id: int, lang: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO users (user_id, lang, is_active) VALUES (?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
            """, (user_id, lang))
            await conn.commit()

    async def set_user_email(self, user_id: int, email: str):
        email = email.strip().lower()
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO users (user_id, email, email_registered_at, is_active, last_seen_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email = excluded.email,
                    email_registered_at = COALESCE(email_registered_at, excluded.email_registered_at),
                    last_seen_at = excluded.last_seen_at
            """, (user_id, email, now, now))
            await conn.commit()

    async def webhook_event_exists(self, event_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM webhook_events WHERE event_id = ?", (event_id,)) as cur:
                return await cur.fetchone() is not None

    async def claim_webhook_event(self, event_id: str, email: str, product_key: str, payment_system: str, payload: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute("""
                INSERT OR IGNORE INTO webhook_events (event_id, email, product_key, payment_system, payload)
                VALUES (?, ?, ?, ?, ?)
            """, (event_id, email.strip().lower(), product_key, payment_system, payload))
            await conn.commit()
            return (cur.rowcount or 0) > 0

    async def save_webhook_event(self, event_id: str, email: str, product_key: str, payment_system: str, payload: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR IGNORE INTO webhook_events (event_id, email, product_key, payment_system, payload)
                VALUES (?, ?, ?, ?, ?)
            """, (event_id, email.strip().lower(), product_key, payment_system, payload))
            await conn.commit()

    async def delete_webhook_event(self, event_id: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM webhook_events WHERE event_id = ?", (event_id,))
            await conn.commit()

    # ─── GIVEAWAY ───
    async def enter_giveaway(self, user_id: int, month: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO giveaway_entries (user_id, month) VALUES (?, ?)",
                (user_id, month)
            )
            await conn.commit()

    async def is_giveaway_entered(self, user_id: int, month: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT 1 FROM giveaway_entries WHERE user_id = ? AND month = ?",
                (user_id, month)
            ) as cur:
                return await cur.fetchone() is not None

    async def get_giveaway_count(self, month: str) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM giveaway_entries WHERE month = ?", (month,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_giveaway_participants(self, month: str) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT user_id FROM giveaway_entries WHERE month = ?", (month,)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def activate_subscription(self, user_id, username, plan_key, plan_name, expires_at, tx_hash, amount_usdt=0.0):
        return await self.activate_product_subscription(
            user_id=user_id,
            username=username,
            product_key=plan_key,
            product_name=plan_name,
            expires_at=expires_at,
            tx_hash=tx_hash,
            amount_usdt=amount_usdt,
            chat_id=0,
            chat_link="",
            payment_system=""
        )

    async def _refresh_user_access_summary(self, conn, user_id: int):
        conn.row_factory = aiosqlite.Row
        now = datetime.utcnow().isoformat()
        async with conn.execute("""
            SELECT product_key, product_name, activated_at, expires_at, tx_hash
            FROM user_subscriptions
            WHERE user_id = ? AND is_active = 1 AND expires_at > ?
            ORDER BY expires_at DESC
            LIMIT 1
        """, (user_id, now)) as cur:
            row = await cur.fetchone()
        if row:
            await conn.execute("""
                UPDATE users
                SET plan_key = ?, plan_name = ?, activated_at = ?, expires_at = ?, is_active = 1, tx_hash = ?
                WHERE user_id = ?
            """, (row["product_key"], row["product_name"], row["activated_at"], row["expires_at"], row["tx_hash"], user_id))
        else:
            await conn.execute("""
                UPDATE users
                SET is_active = 0, plan_key = NULL, plan_name = NULL, activated_at = NULL, tx_hash = NULL
                WHERE user_id = ?
            """, (user_id,))

    async def activate_product_subscription(self, user_id, username, product_key, product_name, expires_at, tx_hash, amount_usdt=0.0, chat_id=0, chat_link="", payment_system=""):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, plan_key, plan_name, activated_at, expires_at, is_active, tx_hash)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username, plan_key=excluded.plan_key,
                    plan_name=excluded.plan_name, activated_at=excluded.activated_at,
                    expires_at=excluded.expires_at, is_active=1, tx_hash=excluded.tx_hash
            """, (user_id, username, product_key, product_name, now, expires_at.isoformat(), tx_hash))
            await conn.execute("""
                INSERT INTO user_subscriptions
                    (user_id, product_key, product_name, chat_id, chat_link, activated_at, expires_at, is_active, tx_hash, payment_system)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, product_key) DO UPDATE SET
                    product_name = excluded.product_name,
                    chat_id = excluded.chat_id,
                    chat_link = excluded.chat_link,
                    activated_at = excluded.activated_at,
                    expires_at = excluded.expires_at,
                    is_active = 1,
                    tx_hash = excluded.tx_hash,
                    payment_system = excluded.payment_system
            """, (user_id, product_key, product_name, chat_id or 0, chat_link or "", now, expires_at.isoformat(), tx_hash, payment_system or ""))
            await conn.execute("""
                INSERT INTO payment_history (user_id, plan_key, plan_name, amount_usdt, tx_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, product_key, product_name, amount_usdt, tx_hash))
            await conn.execute("INSERT OR IGNORE INTO used_transactions (tx_hash, user_id) VALUES (?, ?)", (tx_hash, user_id))
            await conn.execute("DELETE FROM pending_payments WHERE user_id = ?", (user_id,))
            await self._refresh_user_access_summary(conn, user_id)
            await conn.commit()

    async def set_friend(self, user_id: int, is_friend: bool):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("UPDATE users SET is_friend = ? WHERE user_id = ?", (1 if is_friend else 0, user_id))
            await conn.commit()

    async def register_user_as_friend(self, user_id: int, username: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, lang, is_active, is_friend)
                VALUES (?, ?, 'ru', 0, 1)
                ON CONFLICT(user_id) DO UPDATE SET is_friend = 1, username = COALESCE(excluded.username, username)
            """, (user_id, username))
            await conn.commit()

    async def is_user_friend(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT is_friend FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return bool(row and row[0])

    async def get_all_friends(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE is_friend = 1") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.lstrip("@"),)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def deactivate_subscription(self, user_id: int):
        """Deaktivizē abonementu — uzliek is_active=0 UN expires_at=now lai bots uzreiz rāda neaktīvu"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "UPDATE users SET is_active = 0, expires_at = ? WHERE user_id = ?",
                (now, user_id)
            )
            await conn.execute(
                "UPDATE user_subscriptions SET is_active = 0 WHERE user_id = ?",
                (user_id,)
            )
            await conn.commit()

    async def get_active_user_subscriptions(self, user_id: int) -> List[Dict]:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM user_subscriptions
                WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                ORDER BY expires_at ASC
            """, (user_id, now)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_expired_chat_subscriptions(self) -> List[Dict]:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT us.*, u.username, u.lang, u.is_friend
                FROM user_subscriptions us
                JOIN users u ON u.user_id = us.user_id
                WHERE us.is_active = 1 AND us.expires_at < ? AND COALESCE(us.chat_id, 0) != 0
            """, (now,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def mark_subscription_inactive(self, subscription_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT user_id FROM user_subscriptions WHERE id = ?", (subscription_id,)) as cur:
                row = await cur.fetchone()
                user_id = row[0] if row else None
            await conn.execute("UPDATE user_subscriptions SET is_active = 0 WHERE id = ?", (subscription_id,))
            if user_id:
                await self._refresh_user_access_summary(conn, user_id)
            await conn.commit()

    # ─── PENDING PAYMENTS ───

    async def set_pending_payment(self, user_id: int, plan_key: str, amount: float):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO pending_payments (user_id, plan_key, amount_usdt)
                VALUES (?, ?, ?)
            """, (user_id, plan_key, amount))
            await conn.commit()

    async def get_pending_payment(self, user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM pending_payments WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_all_pending_payments(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM pending_payments") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_active_pending_amounts(self, plan_key: str) -> List[float]:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT amount_usdt FROM pending_payments WHERE plan_key = ?", (plan_key,)
            ) as cur:
                return [row[0] for row in await cur.fetchall()]

    async def cleanup_old_pending(self):
        cutoff = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            result = await conn.execute("DELETE FROM pending_payments WHERE created_at < ?", (cutoff,))
            await conn.commit()
            if result.rowcount > 0:
                logger.info(f"Cleaned {result.rowcount} old pending payments")
                
    async def delete_pending_payment(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM pending_payments WHERE user_id = ?", (user_id,))
            await conn.commit()

    async def is_tx_used(self, tx_hash: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM used_transactions WHERE tx_hash = ?", (tx_hash,)) as cur:
                return await cur.fetchone() is not None

    async def mark_tx_used(self, tx_hash: str, user_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO used_transactions (tx_hash, user_id) VALUES (?, ?)", (tx_hash, user_id))
            await conn.commit()

    async def add_course_purchase(self, user_id, username, course_key, course_name, amount, tx_hash, email):
        """Pievieno kursa pirkumu un atgriež purchase_id"""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("""
                INSERT INTO course_purchases (user_id, username, course_key, course_name, amount_usdt, tx_hash, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, course_key, course_name, amount, tx_hash, email))
            await conn.commit()
            return cursor.lastrowid

    async def get_referral_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT COUNT(*) as c FROM referrals") as cur:
                total_refs = (await cur.fetchone())['c']
            async with conn.execute("""
                SELECT COUNT(DISTINCT r.referred_id) as c
                FROM referrals r
                JOIN payment_history ph ON ph.user_id = r.referred_id
            """) as cur:
                paid_refs = (await cur.fetchone())['c']
            return {"total_referrals": total_refs, "paid_referrals": paid_refs}

    # ─── STATS ───

    async def get_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            now = datetime.utcnow().isoformat()

            async with conn.execute("SELECT COUNT(*) as c FROM users") as cur:
                total_users = (await cur.fetchone())["c"]

            async with conn.execute("SELECT COUNT(*) as c FROM users WHERE is_active = 1 AND expires_at > ?", (now,)) as cur:
                active = (await cur.fetchone())["c"]

            async with conn.execute("SELECT COUNT(*) as c FROM users WHERE (plan_key IS NULL OR plan_key = '') AND is_active = 0") as cur:
                never_bought = (await cur.fetchone())["c"]

            async with conn.execute("SELECT COUNT(*) as c FROM users WHERE is_active = 0 AND plan_key IS NOT NULL AND plan_key != '' AND plan_key != 'manual'") as cur:
                expired = (await cur.fetchone())["c"]

            async with conn.execute("""
                SELECT plan_name, COUNT(*) as c FROM users
                WHERE is_active = 1 AND expires_at > ? GROUP BY plan_name
            """, (now,)) as cur:
                by_plan = {row["plan_name"]: row["c"] for row in await cur.fetchall()}

            async with conn.execute("SELECT COALESCE(SUM(amount_usdt), 0) as s FROM payment_history") as cur:
                total_revenue = (await cur.fetchone())["s"] or 0

            return {
                "total_users": total_users, "active": active, "never_bought": never_bought,
                "expired": expired, "by_plan": by_plan, "total_revenue": total_revenue,
            }

    async def get_detailed_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            now = datetime.utcnow()
            today = now.strftime("%Y-%m-%d")
            month_start = now.strftime("%Y-%m-01")
            year_start = now.strftime("%Y-01-01")

            async with conn.execute("SELECT COUNT(DISTINCT user_id) as c FROM payment_history WHERE plan_key != 'manual' AND plan_key != 'referral_bonus'") as cur:
                unique_buyers = (await cur.fetchone())["c"]

            async with conn.execute("""
                SELECT COUNT(*) as c FROM (
                    SELECT user_id FROM payment_history
                    WHERE plan_key != 'manual' AND plan_key != 'referral_bonus'
                    GROUP BY user_id HAVING COUNT(*) >= 2
                )
            """) as cur:
                repeat_buyers = (await cur.fetchone())["c"]

            one_time = unique_buyers - repeat_buyers

            async with conn.execute(
                "SELECT COALESCE(SUM(amount_usdt), 0) as s FROM payment_history WHERE date(paid_at) = ?", (today,)
            ) as cur:
                today_revenue = (await cur.fetchone())["s"] or 0

            async with conn.execute(
                "SELECT COUNT(*) as c FROM payment_history WHERE date(paid_at) = ?", (today,)
            ) as cur:
                today_purchases = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COALESCE(SUM(amount_usdt), 0) as s FROM payment_history WHERE paid_at >= ?", (month_start,)
            ) as cur:
                month_revenue = (await cur.fetchone())["s"] or 0

            async with conn.execute(
                "SELECT COUNT(*) as c FROM payment_history WHERE paid_at >= ?", (month_start,)
            ) as cur:
                month_purchases = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COALESCE(SUM(amount_usdt), 0) as s FROM payment_history WHERE paid_at >= ?", (year_start,)
            ) as cur:
                year_revenue = (await cur.fetchone())["s"] or 0

            async with conn.execute("SELECT COALESCE(SUM(amount_usdt), 0) as s FROM payment_history") as cur:
                total_revenue = (await cur.fetchone())["s"] or 0

            async with conn.execute("SELECT COUNT(*) as c FROM payment_history WHERE plan_key != 'manual' AND plan_key != 'referral_bonus'") as cur:
                total_purchases = (await cur.fetchone())["c"]

            arpu = total_revenue / unique_buyers if unique_buyers > 0 else 0

            async with conn.execute("SELECT COUNT(*) as c FROM users") as cur:
                total_users = (await cur.fetchone())["c"]
            conversion = (unique_buyers / total_users * 100) if total_users > 0 else 0

            week_data = []
            for i in range(6, -1, -1):
                day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                async with conn.execute(
                    "SELECT COALESCE(SUM(amount_usdt), 0) as s, COUNT(*) as c FROM payment_history WHERE date(paid_at) = ?", (day,)
                ) as cur:
                    row = await cur.fetchone()
                    week_data.append({
                        "date": (now - timedelta(days=i)).strftime("%d.%m"),
                        "revenue": row["s"] or 0,
                        "count": row["c"]
                    })

            async with conn.execute("""
                SELECT plan_name, COUNT(*) as cnt, COALESCE(SUM(amount_usdt), 0) as rev
                FROM payment_history WHERE plan_key != 'manual' AND plan_key != 'referral_bonus'
                GROUP BY plan_name ORDER BY rev DESC
            """) as cur:
                top_plans = [dict(row) for row in await cur.fetchall()]

            async with conn.execute("""
                SELECT COUNT(*) as c FROM users
                WHERE is_active = 0 AND plan_key IS NOT NULL AND plan_key != '' AND plan_key != 'manual'
            """) as cur:
                churned = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COUNT(*) as c FROM users WHERE date(created_at) = ?", (today,)
            ) as cur:
                new_today = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COUNT(*) as c FROM bot_event_log WHERE event_type = 'reminder_sent' AND event_date = ?",
                (today,)
            ) as cur:
                reminders_today = (await cur.fetchone())["c"]

            week_start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            async with conn.execute(
                "SELECT COUNT(*) as c FROM bot_event_log WHERE event_type = 'reminder_sent' AND event_date >= ?",
                (week_start,)
            ) as cur:
                reminders_7d = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COUNT(*) as c FROM bot_event_log WHERE event_type = 'expired_kick' AND event_date = ?",
                (today,)
            ) as cur:
                kicked_today = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COUNT(*) as c FROM bot_event_log WHERE event_type = 'expiry_today_notice' AND event_date = ?",
                (today,)
            ) as cur:
                expiry_today_notices = (await cur.fetchone())["c"]

            async with conn.execute(
                "SELECT COUNT(*) as c FROM bot_event_log WHERE event_type = 'expired_kick' AND event_date >= ?",
                (week_start,)
            ) as cur:
                kicked_7d = (await cur.fetchone())["c"]

            return {
                "unique_buyers": unique_buyers,
                "repeat_buyers": repeat_buyers,
                "one_time_buyers": one_time,
                "today_revenue": today_revenue,
                "today_purchases": today_purchases,
                "month_revenue": month_revenue,
                "month_purchases": month_purchases,
                "year_revenue": year_revenue,
                "total_revenue": total_revenue,
                "total_purchases": total_purchases,
                "arpu": arpu,
                "conversion": conversion,
                "total_users": total_users,
                "week_data": week_data,
                "top_plans": top_plans,
                "churned": churned,
                "new_today": new_today,
                "reminders_today": reminders_today,
                "reminders_7d": reminders_7d,
                "expiry_today_notices": expiry_today_notices,
                "kicked_today": kicked_today,
                "kicked_7d": kicked_7d,
            }

    # ─── MARKETING ───

    async def get_high_value_users(self, min_spent: float = 50.0) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT u.*, COALESCE(SUM(ph.amount_usdt), 0) as total_spent
                FROM users u
                LEFT JOIN payment_history ph ON ph.user_id = u.user_id
                GROUP BY u.user_id
                HAVING total_spent >= ?
                ORDER BY total_spent DESC
            """, (min_spent,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_users_expiring_soon(self, days: int = 7) -> List[Dict]:
        now = datetime.utcnow().isoformat()
        future = (datetime.utcnow() + timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users WHERE is_active = 1 AND expires_at BETWEEN ? AND ?
            """, (now, future)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_one_time_buyers(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT u.* FROM users u
                WHERE u.user_id IN (
                    SELECT user_id FROM payment_history
                    WHERE plan_key != 'manual' AND plan_key != 'referral_bonus'
                    GROUP BY user_id HAVING COUNT(*) = 1
                ) AND u.is_active = 0
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_referral_active_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT u.* FROM users u
                JOIN referrals r ON r.referred_id = u.user_id
                WHERE r.bonus_given = 0 AND (u.plan_key IS NULL OR u.plan_key = '')
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_all_active_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE is_active = 1") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_registered_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users
                WHERE email IS NOT NULL AND email != ''
                ORDER BY created_at DESC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_expired_users(self) -> List[Dict]:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE is_active = 1 AND expires_at < ?", (now,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_all_users_stats(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_never_bought_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE (plan_key IS NULL OR plan_key = '') AND is_active = 0") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_expired_within_days(self, from_days: int, to_days: int) -> List[Dict]:
        now = datetime.utcnow()
        date_from = (now - timedelta(days=to_days)).isoformat()
        date_to = (now - timedelta(days=from_days)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users WHERE is_active = 0 AND expires_at BETWEEN ? AND ?
                AND plan_key IS NOT NULL AND plan_key != ''
            """, (date_from, date_to)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_expired_older_than_days(self, days: int) -> List[Dict]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users WHERE is_active = 0 AND expires_at < ?
                AND plan_key IS NOT NULL AND plan_key != ''
            """, (cutoff,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_recently_expired_users(self, days_after: int) -> List[Dict]:
        now = datetime.utcnow()
        target = (now - timedelta(days=days_after)).isoformat()
        target_end = (now - timedelta(days=days_after - 1)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users WHERE is_active = 0 AND expires_at BETWEEN ? AND ?
                AND plan_key IS NOT NULL AND plan_key != ''
            """, (target, target_end)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_expiring_users(self, target_date: datetime) -> List[Dict]:
        date_str = target_date.strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE is_active = 1 AND date(expires_at) = ?", (date_str,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def reminder_already_sent(self, user_id: int, days_before: int) -> bool:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM sent_reminders WHERE user_id=? AND days_before=? AND sent_date=?", (user_id, days_before, today)) as cur:
                return await cur.fetchone() is not None

    async def mark_reminder_sent(self, user_id: int, days_before: int):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO sent_reminders (user_id, days_before, sent_date) VALUES (?, ?, ?)", (user_id, days_before, today))
            await conn.commit()

    async def log_bot_event(self, event_type: str, user_id: Optional[int] = None, event_date: Optional[str] = None, meta: str = ""):
        day = event_date or datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT INTO bot_event_log (event_type, user_id, event_date, meta) VALUES (?, ?, ?, ?)",
                (event_type, user_id, day, meta),
            )
            await conn.commit()

    async def count_bot_events(self, event_type: str, days: int = 1) -> int:
        start_date = (datetime.utcnow() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM bot_event_log WHERE event_type = ? AND event_date >= ?",
                (event_type, start_date),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_bot_event_stats(self) -> Dict:
        return {
            "reminders_today": await self.count_bot_events("reminder_sent", 1),
            "reminders_7d": await self.count_bot_events("reminder_sent", 7),
            "expiry_today_notices": await self.count_bot_events("expiry_today_notice", 1),
            "kicked_today": await self.count_bot_events("expired_kick", 1),
            "kicked_7d": await self.count_bot_events("expired_kick", 7),
        }

    async def get_recent_bot_events(self, limit: int = 30) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT bel.*, u.username, u.plan_name
                FROM bot_event_log bel
                LEFT JOIN users u ON u.user_id = bel.user_id
                ORDER BY bel.created_at DESC, bel.id DESC
                LIMIT ?
            """, (limit,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ─── SETTINGS ───

    async def get_setting(self, key: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
            await conn.commit()

    async def create_winback_offer(self, user_id: int, bonus_days: int, offer_hours: int):
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=offer_hours)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO winback_offers (user_id, sent_at, expires_at, bonus_days, redeemed_at, redeemed_tx)
                VALUES (?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(user_id) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    expires_at = excluded.expires_at,
                    bonus_days = excluded.bonus_days,
                    redeemed_at = NULL,
                    redeemed_tx = NULL
            """, (user_id, now.isoformat(), expires_at.isoformat(), bonus_days))
            await conn.commit()

    async def get_active_winback_offer(self, user_id: int) -> Optional[Dict]:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM winback_offers
                WHERE user_id = ? AND redeemed_at IS NULL AND expires_at > ?
            """, (user_id, now)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def redeem_winback_offer(self, user_id: int, tx_hash: str = ""):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                UPDATE winback_offers
                SET redeemed_at = ?, redeemed_tx = ?
                WHERE user_id = ? AND redeemed_at IS NULL
            """, (now, tx_hash, user_id))
            await conn.commit()

    async def extend_product_subscription(self, user_id: int, product_key: str, extra_days: int):
        if extra_days <= 0:
            return None
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT expires_at FROM user_subscriptions
                WHERE user_id = ? AND product_key = ? AND is_active = 1
                ORDER BY expires_at DESC
                LIMIT 1
            """, (user_id, product_key)) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            now = datetime.utcnow()
            current_exp = datetime.fromisoformat(row["expires_at"])
            new_exp = (current_exp if current_exp > now else now) + timedelta(days=extra_days)
            await conn.execute("""
                UPDATE user_subscriptions
                SET expires_at = ?
                WHERE user_id = ? AND product_key = ? AND is_active = 1
            """, (new_exp.isoformat(), user_id, product_key))
            await self._refresh_user_access_summary(conn, user_id)
            await conn.commit()
            return new_exp

    # ─── MARKETING ───

    async def get_all_users_for_export(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT u.*,
                    (SELECT COUNT(*) FROM payment_history ph WHERE ph.user_id = u.user_id) as total_purchases,
                    (SELECT COALESCE(SUM(ph.amount_usdt), 0) FROM payment_history ph WHERE ph.user_id = u.user_id) as total_spent
                FROM users u ORDER BY u.created_at DESC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_never_messaged_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users
                WHERE (plan_key IS NULL OR plan_key = '') AND is_active = 0
                AND user_id NOT IN (SELECT DISTINCT user_id FROM marketing_sends)
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def marketing_already_sent(self, user_id: int, campaign: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM marketing_sends WHERE user_id=? AND campaign=?", (user_id, campaign)) as cur:
                return await cur.fetchone() is not None

    async def mark_marketing_sent(self, user_id: int, campaign: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO marketing_sends (user_id, campaign) VALUES (?, ?)", (user_id, campaign))
            await conn.commit()

    # ─── REFERRALS ───

    async def register_referral(self, referrer_id: int, referred_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
            await conn.commit()

    async def get_referral_by_referred(self, referred_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM referrals WHERE referred_id = ?", (referred_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def mark_referral_bonus_given(self, referred_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("UPDATE referrals SET bonus_given = 1 WHERE referred_id = ? AND bonus_given = 0", (referred_id,))
            await conn.commit()

    async def get_referral_count(self, referrer_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_referral_bonus_count(self, referrer_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND bonus_given = 1", (referrer_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_my_referrals(self, referrer_id: int) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT r.referred_id, r.bonus_given, r.created_at, u.username, u.first_name
                FROM referrals r LEFT JOIN users u ON u.user_id = r.referred_id
                WHERE r.referrer_id = ? ORDER BY r.created_at DESC
            """, (referrer_id,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_referrals_for_export(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT r.*, u1.username as referrer_username, u2.username as referred_username, u2.is_active as referred_is_active
                FROM referrals r
                LEFT JOIN users u1 ON u1.user_id = r.referrer_id
                LEFT JOIN users u2 ON u2.user_id = r.referred_id
                ORDER BY r.created_at DESC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ═══════════════════════════════════════════════════════════════
    # REFERRAL EARNINGS SYSTEM
    # ═══════════════════════════════════════════════════════════════

    async def add_referral_earning(self, referrer_id: int, referred_id: int, purchase_id: int, 
                                   course_key: str, amount_usd: float, commission_usd: float, earning_type: str = "course"):
        """Pievieno referral komisijas ierakstu
        
        earning_type: 'course' vai 'chat'
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO referral_earnings 
                (referrer_id, referred_id, purchase_id, course_key, amount_usd, commission_usd)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (referrer_id, referred_id, purchase_id, course_key or earning_type, amount_usd, commission_usd))
            await conn.commit()
            logger.info(f"Referral earning [{earning_type}]: {referrer_id} earned {commission_usd}$ from {referred_id}")

    async def get_referral_balance(self, user_id: int) -> float:
        """Aprēķina user pieejamo balance (naudas summu izmaksai)"""
        async with aiosqlite.connect(self.db_path) as conn:
            # Kopējie ienākumi
            async with conn.execute(
                "SELECT COALESCE(SUM(commission_usd), 0) FROM referral_earnings WHERE referrer_id = ?",
                (user_id,)
            ) as cur:
                total_earned = (await cur.fetchone())[0] or 0
            
            # Izmaksātā summa (approved)
            async with conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM withdrawal_requests WHERE user_id = ? AND status = 'approved'",
                (user_id,)
            ) as cur:
                withdrawn = (await cur.fetchone())[0] or 0
            
            # Pending izmaksas (nedrīkst izmaksāt vēlreiz)
            async with conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM withdrawal_requests WHERE user_id = ? AND status = 'pending'",
                (user_id,)
            ) as cur:
                pending = (await cur.fetchone())[0] or 0
            
            available = total_earned - withdrawn - pending
            return max(0, available)

    async def get_referral_earnings_list(self, user_id: int) -> List[Dict]:
        """Iegūst visus referral ienākumus konkrētam lietotājam"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT re.*, u.username as referred_username, u.first_name as referred_first_name
                FROM referral_earnings re
                LEFT JOIN users u ON u.user_id = re.referred_id
                WHERE re.referrer_id = ?
                ORDER BY re.earned_at DESC
            """, (user_id,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_total_referral_earnings(self, user_id: int) -> float:
        """Kopējie komisijas ienākumi"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT COALESCE(SUM(commission_usd), 0) FROM referral_earnings WHERE referrer_id = ?",
                (user_id,)
            ) as cur:
                return (await cur.fetchone())[0] or 0

    # ═══════════════════════════════════════════════════════════════
    # WITHDRAWAL SYSTEM
    # ═══════════════════════════════════════════════════════════════

    async def create_withdrawal_request(self, user_id: int, amount_usd: float, wallet_address: str, email: str) -> int:
        """Izveido jaunu withdrawal pieprasījumu"""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("""
                INSERT INTO withdrawal_requests (user_id, amount_usd, wallet_address, email, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (user_id, amount_usd, wallet_address, email))
            await conn.commit()
            request_id = cursor.lastrowid
            logger.info(f"Withdrawal request created: #{request_id} for user {user_id}, amount {amount_usd}$")
            return request_id

    async def get_pending_withdrawals(self) -> List[Dict]:
        """Visi pending withdrawal pieprasījumi (admin)"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT wr.*, u.username, u.first_name
                FROM withdrawal_requests wr
                LEFT JOIN users u ON u.user_id = wr.user_id
                WHERE wr.status = 'pending'
                ORDER BY wr.requested_at ASC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_withdrawal_request(self, request_id: int) -> Optional[Dict]:
        """Iegūst konkrētu withdrawal pieprasījumu"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM withdrawal_requests WHERE id = ?
            """, (request_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def approve_withdrawal(self, request_id: int, admin_id: int, notes: str = ""):
        """Admin apstiprina izmaksu"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            # Update request
            await conn.execute("""
                UPDATE withdrawal_requests
                SET status = 'approved', processed_at = ?, admin_id = ?, admin_notes = ?
                WHERE id = ? AND status = 'pending'
            """, (now, admin_id, notes, request_id))
            
            # Copy to history
            await conn.execute("""
                INSERT INTO withdrawal_history (user_id, amount_usd, wallet_address, status, requested_at, processed_at, admin_id, admin_notes)
                SELECT user_id, amount_usd, wallet_address, 'approved', requested_at, ?, ?, ?
                FROM withdrawal_requests WHERE id = ?
            """, (now, admin_id, notes, request_id))
            
            await conn.commit()
            logger.info(f"Withdrawal #{request_id} approved by admin {admin_id}")

    async def reject_withdrawal(self, request_id: int, admin_id: int, reason: str):
        """Admin noraida izmaksu"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                UPDATE withdrawal_requests
                SET status = 'rejected', processed_at = ?, admin_id = ?, rejection_reason = ?
                WHERE id = ? AND status = 'pending'
            """, (now, admin_id, reason, request_id))
            
            await conn.execute("""
                INSERT INTO withdrawal_history (user_id, amount_usd, wallet_address, status, requested_at, processed_at, admin_id, admin_notes)
                SELECT user_id, amount_usd, wallet_address, 'rejected', requested_at, ?, ?, ?
                FROM withdrawal_requests WHERE id = ?
            """, (now, admin_id, reason, request_id))
            
            await conn.commit()
            logger.info(f"Withdrawal #{request_id} rejected by admin {admin_id}: {reason}")

    async def get_user_withdrawal_history(self, user_id: int) -> List[Dict]:
        """User izmaksu vēsture"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM withdrawal_requests
                WHERE user_id = ?
                ORDER BY requested_at DESC
            """, (user_id,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_all_withdrawal_history(self) -> List[Dict]:
        """Visa izmaksu vēsture (admin)"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT wh.*, u.username, u.first_name
                FROM withdrawal_history wh
                LEFT JOIN users u ON u.user_id = wh.user_id
                ORDER BY wh.processed_at DESC
                LIMIT 100
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def has_pending_withdrawal(self, user_id: int) -> bool:
        """Pārbauda vai user jau ir pending withdrawal"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT 1 FROM withdrawal_requests WHERE user_id = ? AND status = 'pending'",
                (user_id,)
            ) as cur:
                return await cur.fetchone() is not None

    async def count_recent_withdrawal_requests(self, user_id: int, hours: int = 24) -> int:
        """Skaita cik reižu user ir pieprasījis izmaksu pēdējo X stundu laikā (rate limit)"""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM withdrawal_requests WHERE user_id = ? AND requested_at > ?",
                (user_id, cutoff)
            ) as cur:
                return (await cur.fetchone())[0] or 0

    # ═══════════════════════════════════════════════════════════════
    # FRAUD DETECTION & BANS
    # ═══════════════════════════════════════════════════════════════

    async def add_fraud_alert(self, user_id: int, alert_type: str, description: str):
        """Pievieno fraud alert"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO fraud_alerts (user_id, alert_type, description)
                VALUES (?, ?, ?)
            """, (user_id, alert_type, description))
            await conn.commit()
            logger.warning(f"FRAUD ALERT: {alert_type} for user {user_id} - {description}")

    async def get_fraud_alerts(self, user_id: Optional[int] = None) -> List[Dict]:
        """Iegūst fraud alerts (visus vai konkrētam user)"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            if user_id:
                async with conn.execute("""
                    SELECT * FROM fraud_alerts WHERE user_id = ? ORDER BY detected_at DESC
                """, (user_id,)) as cur:
                    return [dict(row) for row in await cur.fetchall()]
            else:
                async with conn.execute("""
                    SELECT fa.*, u.username, u.first_name
                    FROM fraud_alerts fa
                    LEFT JOIN users u ON u.user_id = fa.user_id
                    ORDER BY fa.detected_at DESC LIMIT 50
                """) as cur:
                    return [dict(row) for row in await cur.fetchall()]

    async def ban_user(self, user_id: int, reason: str, admin_id: int):
        """Bloķē lietotāju"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO user_bans (user_id, reason, banned_by)
                VALUES (?, ?, ?)
            """, (user_id, reason, admin_id))
            await conn.commit()
            logger.warning(f"User {user_id} BANNED by admin {admin_id}: {reason}")

    async def unban_user(self, user_id: int):
        """Atbloķē lietotāju"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM user_bans WHERE user_id = ?", (user_id,))
            await conn.commit()
            logger.info(f"User {user_id} unbanned")

    async def is_user_banned(self, user_id: int) -> bool:
        """Pārbauda vai user ir bloķēts"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM user_bans WHERE user_id = ?", (user_id,)) as cur:
                return await cur.fetchone() is not None

    async def get_banned_users(self) -> List[Dict]:
        """Visi bloķētie lietotāji"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT ub.*, u.username, u.first_name
                FROM user_bans ub
                LEFT JOIN users u ON u.user_id = ub.user_id
                ORDER BY ub.banned_at DESC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ═══════════════════════════════════════════════════════════════
    # ADMIN HELPERS - Withdrawal earnings breakdown
    # ═══════════════════════════════════════════════════════════════

    async def get_earnings_breakdown_for_withdrawal(self, user_id: int, request_id: int) -> List[Dict]:
        """Admin redz kādi konkrēti pirkumi veido šo withdrawal summu"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            # Iegūst visus earnings līdz šim withdrawal request datumam
            async with conn.execute("""
                SELECT re.*, u.username as referred_username, cp.course_name, cp.tx_hash
                FROM referral_earnings re
                LEFT JOIN users u ON u.user_id = re.referred_id
                LEFT JOIN course_purchases cp ON cp.id = re.purchase_id
                WHERE re.referrer_id = ?
                ORDER BY re.earned_at DESC
            """, (user_id,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ─── PROMO CODES ───

    async def create_promo_code(self, code: str, discount_percent: int, plan_key: str = None, max_uses: int = 0, expires_at: str = None):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO promo_codes (code, discount_percent, plan_key, max_uses, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (code.upper(), discount_percent, plan_key, max_uses, expires_at))
            await conn.commit()

    async def get_promo_code(self, code: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code.upper(),)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                promo = dict(row)
                if promo.get('expires_at') and promo['expires_at'] < datetime.utcnow().isoformat():
                    return None
                if promo.get('max_uses') and promo['max_uses'] > 0 and promo['used_count'] >= promo['max_uses']:
                    return None
                return promo

    async def use_promo_code(self, code: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?", (code.upper(),))
            await conn.commit()

    async def get_all_promo_codes(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM promo_codes ORDER BY created_at DESC") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def delete_promo_code(self, code: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM promo_codes WHERE code = ?", (code.upper(),))
            await conn.commit()

    async def apply_promo_to_user(self, user_id: int, code: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO user_promos (user_id, promo_code) VALUES (?, ?)", (user_id, code.upper()))
            await conn.commit()

    async def get_user_active_promo(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT promo_code FROM user_promos WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def clear_user_promo(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM user_promos WHERE user_id = ?", (user_id,))
            await conn.commit()

    # ─── DB BACKUP ───

    async def backup_db(self, backup_path: str = "/app/data/backup"):
        import shutil
        import os
        os.makedirs(backup_path, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        dest = f"{backup_path}/subscriptions_{ts}.db"
        shutil.copy2(self.db_path, dest)
        backups = sorted([f for f in os.listdir(backup_path) if f.endswith('.db')])
        for old in backups[:-10]:
            os.remove(f"{backup_path}/{old}")
        logger.info(f"DB backup: {dest}")
        return dest



# ═══════════════════════════════════════════════════════════════
# LOYALTY SYSTEM INTEGRATION
# ═══════════════════════════════════════════════════════════════
from database_loyalty_addon import apply_loyalty_mixin

# Apply loyalty mixin to add all loyalty methods
Database = apply_loyalty_mixin(Database)

db = Database()
