# ═══════════════════════════════════════════════════════════════
# DATABASE LOYALTY ADDON - PILNS AR VISĀM METODĒM
# FIX: Pievienotas visas 20 trūkstošās metodes
# FIX: Labots payment_history kolonnu nosaukums (paid_at, ne created_at)
# FIX: Noņemts status='completed' filtrs (nav tādas kolonnas)
# ═══════════════════════════════════════════════════════════════

import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class LoyaltyDatabaseMixin:
    """Mixin that adds loyalty system methods to Database"""

    # ─── GENERIC SQL HELPERS ───

    async def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Generic: izpilda SELECT un atgriež visas rindas kā dict sarakstu"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(sql, params) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """Generic: izpilda SELECT un atgriež pirmo rindu kā dict"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(sql, params) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    # ─── USER LOYALTY CRUD ───

    async def get_user_loyalty(self, user_id: int) -> Optional[Dict]:
        """Get user's loyalty data"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM user_loyalty WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def update_user_loyalty(self, user_id: int, tier: str, consecutive_months: int):
        """Update user's loyalty tier"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO user_loyalty (user_id, current_tier, consecutive_months, last_payment_date, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_tier = excluded.current_tier,
                    consecutive_months = excluded.consecutive_months,
                    last_payment_date = excluded.last_payment_date,
                    updated_at = excluded.updated_at
            """, (user_id, tier, consecutive_months, now, now))
            await conn.commit()

    async def reset_user_loyalty(self, user_id: int):
        """Reset user loyalty to rookie — izsauc loyalty_system.py"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                UPDATE user_loyalty SET
                    current_tier = 'rookie',
                    consecutive_months = 0,
                    updated_at = ?
                WHERE user_id = ?
            """, (now, user_id))
            await conn.commit()
        logger.info(f"Reset loyalty to rookie: user={user_id}")

    # ─── STATS ───

    async def get_users_by_tier(self) -> List[Dict]:
        """Get user count by tier — izsauc admin.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT current_tier, COUNT(*) as count
                FROM user_loyalty GROUP BY current_tier
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_total_bonuses_given(self) -> int:
        """Kopējais piešķirto bonus dienu skaits — izsauc admin.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT COALESCE(SUM(bonus_days), 0) FROM loyalty_achievements"
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    # ─── PAYMENT HISTORY (FIX: nav status kolonnas, kolonnas nosaukums ir paid_at) ───

    async def get_user_payment_history(self, user_id: int) -> List[Dict]:
        """Get payment history for loyalty calculation.
        FIX: Noņemts status='completed' (nav tādas kolonnas).
        FIX: Izmanto paid_at (ne created_at).
        Pievieno 'days' lauku no PLANS config."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT paid_at as created_at, plan_key, amount_usdt
                FROM payment_history
                WHERE user_id = ?
                    AND plan_key NOT IN ('manual', 'referral_bonus', 'giveaway')
                ORDER BY paid_at DESC
                LIMIT 50
            """, (user_id,)) as cur:
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    # Pievieno days lauku no config
                    from config import config as cfg
                    plan = cfg.PLANS.get(d.get('plan_key', ''), {})
                    d['days'] = plan.get('days', 30)
                    result.append(d)
                return result

    # ─── BONUS DAYS ───

    async def add_bonus_days(self, user_id: int, days: int, reason: str = ""):
        """Pievieno bonus dienas lietotāja abonementam — izsauc loyalty_system.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            # Nolasīt pašreizējo expires_at
            async with conn.execute(
                "SELECT expires_at FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                if not row or not row[0]:
                    logger.warning(f"add_bonus_days: user {user_id} nav aktīva abonementa")
                    return

            expires_at = datetime.fromisoformat(row[0])
            now = datetime.utcnow()
            base = expires_at if expires_at > now else now
            new_expires = base + timedelta(days=days)

            await conn.execute(
                "UPDATE users SET expires_at = ?, is_active = 1 WHERE user_id = ?",
                (new_expires.isoformat(), user_id)
            )
            await conn.commit()
        logger.info(f"Added {days} bonus days to user {user_id}: {reason}")

    # ─── TIER BONUSES ───

    async def check_tier_bonus_awarded(self, user_id: int, tier: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT 1 FROM tier_bonuses_awarded WHERE user_id = ? AND tier = ?",
                (user_id, tier)
            ) as cur:
                return await cur.fetchone() is not None

    async def mark_tier_bonus_awarded(self, user_id: int, tier: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO tier_bonuses_awarded (user_id, tier) VALUES (?, ?)",
                (user_id, tier)
            )
            await conn.commit()

    async def log_loyalty_achievement(self, user_id: int, from_tier: str, to_tier: str,
                                      bonus_days: int = 0, free_course: str = None):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO loyalty_achievements
                (user_id, from_tier, to_tier, bonus_days, free_course)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, from_tier, to_tier, bonus_days, free_course))
            await conn.commit()

    # ─── COURSE GRANTS ───

    async def check_course_granted(self, user_id: int, course_key: str) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT 1 FROM course_grants WHERE user_id = ? AND course_key = ?",
                (user_id, course_key)
            ) as cur:
                return await cur.fetchone() is not None

    async def grant_course(self, user_id: int, course_key: str, granted_by_tier: str):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR IGNORE INTO course_grants (user_id, course_key, granted_by_tier)
                VALUES (?, ?, ?)
            """, (user_id, course_key, granted_by_tier))
            await conn.commit()

    # ─── PERSONAL COUPONS ───

    async def upsert_personal_coupon(self, code: str, user_id: int, coupon_type: str,
                                      discount_percent: int, applies_to: str = 'all',
                                      expires_at: str = None, tied_to_tier: str = None,
                                      max_uses: int = None, reason: str = ""):
        """Izveido vai atjaunina personīgu kupona kodu — izsauc loyalty_system.py"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO loyalty_promo_codes
                    (user_id, code, discount_percent, expires_at, used, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(code) DO UPDATE SET
                    discount_percent = excluded.discount_percent,
                    expires_at = excluded.expires_at,
                    used = 0
            """, (user_id, code, discount_percent, expires_at or '2099-12-31', now))
            await conn.commit()
        logger.info(f"Upserted coupon: {code} user={user_id} {discount_percent}% type={coupon_type}")

    async def deactivate_coupon(self, code: str):
        """Deaktivizē kupona kodu — izsauc loyalty_system.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "UPDATE loyalty_promo_codes SET used = 1 WHERE code = ?", (code,)
            )
            await conn.commit()

    async def get_active_coupons(self, user_id: int) -> List[Dict]:
        """Lietotāja aktīvie kuponi — izsauc bot.py"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM loyalty_promo_codes
                WHERE user_id = ? AND used = 0 AND expires_at > ?
                ORDER BY created_at DESC
            """, (user_id, now)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def cleanup_expired_coupons(self):
        """Dzēš beigušos kuponus — izsauc cron_jobs.py un admin.py"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            result = await conn.execute(
                "DELETE FROM loyalty_promo_codes WHERE expires_at < ? AND used = 0", (now,)
            )
            await conn.commit()
            if result.rowcount > 0:
                logger.info(f"Cleaned {result.rowcount} expired loyalty coupons")

    # ─── WINBACK ───

    async def count_winback_usage(self, user_id: int, since: str = None) -> int:
        """Skaita win-back izmantošanu — izsauc loyalty_system.py"""
        if not since:
            since = (datetime.utcnow() - timedelta(days=365)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("""
                SELECT COUNT(*) FROM winback_surveys
                WHERE user_id = ? AND created_at > ?
            """, (user_id, since)) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def log_winback_usage(self, user_id: int):
        """Reģistrē win-back izmantošanu — izsauc bot.py"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT INTO winback_surveys (user_id, created_at) VALUES (?, ?)",
                (user_id, now)
            )
            await conn.commit()

    async def get_expired_users_for_winback(self, days_expired: int = 5) -> List[Dict]:
        """Lietotāji kuru abonements beidzies pirms N dienām — izsauc cron_jobs.py"""
        target_date = (datetime.utcnow() - timedelta(days=days_expired)).strftime("%Y-%m-%d")
        target_next = (datetime.utcnow() - timedelta(days=days_expired - 1)).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM users
                WHERE is_active = 0 AND date(expires_at) BETWEEN ? AND ?
                AND plan_key IS NOT NULL AND plan_key != ''
            """, (target_date, target_next)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ─── SURVEYS ───

    async def save_survey_response(self, user_id: int, response_text: str, coupon_code: str = None):
        """Saglabā aptaujas atbildi — izsauc bot.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT INTO winback_surveys (user_id, response_text, coupon_code)
                VALUES (?, ?, ?)
            """, (user_id, response_text, coupon_code))
            await conn.commit()

    async def get_survey_responses(self, limit: int = 50) -> List[Dict]:
        """Aptauju atbildes admin panelim — izsauc admin.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT ws.*, u.username, u.first_name
                FROM winback_surveys ws
                LEFT JOIN users u ON u.user_id = ws.user_id
                WHERE ws.response_text IS NOT NULL
                ORDER BY ws.created_at DESC LIMIT ?
            """, (limit,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ─── TAG UPDATES ───

    async def create_tag_update(self, user_id: int, tier: str):
        """Izveido pending tag update — izsauc cron_jobs.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO loyalty_pending_tags (user_id, tier)
                VALUES (?, ?)
            """, (user_id, tier))
            await conn.commit()

    async def get_pending_tag_updates(self) -> List[Dict]:
        """Visi pending tag updates — izsauc admin.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT pt.*, u.username, u.first_name
                FROM loyalty_pending_tags pt
                LEFT JOIN users u ON u.user_id = pt.user_id
                ORDER BY pt.created_at DESC
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_pending_tags_today(self) -> List[Dict]:
        """Šodienas pending tags — izsauc cron_jobs.py"""
        return await self.get_pending_tag_updates()

    async def mark_tag_updated(self, user_id: int):
        """Atzīmē tag kā atjaunotu — izsauc admin.py"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "DELETE FROM loyalty_pending_tags WHERE user_id = ?", (user_id,)
            )
            await conn.commit()

    # ─── REMINDERS & RESET ───

    async def get_users_for_reminders(self, days_before: int) -> List[Dict]:
        """Lietotāji kuriem abonements beidzas pēc N dienām — izsauc cron_jobs.py"""
        target_date = (datetime.utcnow() + timedelta(days=days_before)).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM users WHERE is_active = 1 AND date(expires_at) = ?",
                (target_date,)
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_users_needing_reset(self, days_since_expiry: int = 30) -> List[Dict]:
        """Lietotāji kuru loyalty jāresetē — izsauc cron_jobs.py"""
        cutoff = (datetime.utcnow() - timedelta(days=days_since_expiry)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT ul.*, u.username, u.expires_at
                FROM user_loyalty ul
                JOIN users u ON u.user_id = ul.user_id
                WHERE ul.current_tier != 'rookie'
                AND u.is_active = 0
                AND u.expires_at < ?
            """, (cutoff,)) as cur:
                return [dict(row) for row in await cur.fetchall()]

    # ─── INIT TABLES ───

    async def init_loyalty_tables(self):
        """Initialize loyalty tables"""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_loyalty (
                    user_id INTEGER PRIMARY KEY,
                    current_tier TEXT DEFAULT 'rookie',
                    consecutive_months INTEGER DEFAULT 0,
                    last_payment_date TEXT,
                    last_expiry_date TEXT,
                    tier_achieved_at TEXT,
                    total_bonus_days_earned INTEGER DEFAULT 0,
                    reset_warning_sent_day INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tier_bonuses_awarded (
                    user_id INTEGER NOT NULL,
                    tier TEXT NOT NULL,
                    awarded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, tier)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    from_tier TEXT,
                    to_tier TEXT NOT NULL,
                    bonus_days INTEGER DEFAULT 0,
                    free_course TEXT,
                    announced_public BOOLEAN DEFAULT 0,
                    announced_private BOOLEAN DEFAULT 0,
                    achieved_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS course_grants (
                    user_id INTEGER NOT NULL,
                    course_key TEXT NOT NULL,
                    granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    granted_by_tier TEXT,
                    PRIMARY KEY (user_id, course_key)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_promo_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    used_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_pending_tags (
                    user_id INTEGER PRIMARY KEY,
                    tier TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS winback_surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    response_text TEXT,
                    coupon_code TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_loyalty_tier ON user_loyalty(current_tier)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_loyalty_codes_user ON loyalty_promo_codes(user_id)")

            await conn.commit()
        logger.info("✅ Loyalty tables initialized")


def apply_loyalty_mixin(base_class):
    """Apply loyalty mixin to Database class"""
    class DatabaseWithLoyalty(base_class, LoyaltyDatabaseMixin):
        pass
    return DatabaseWithLoyalty
