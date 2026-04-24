# ═══════════════════════════════════════════════════════════════
# CRON JOBS - AUTOMATED LOYALTY & RETENTION TASKS
# Run daily via APScheduler
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timedelta, timezone
from typing import List
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)


def _cron_renew_keyboard(lang='ru'):
    b = InlineKeyboardBuilder()
    if lang == 'ru':
        b.button(text="🔥  Продлить сейчас", callback_data="vip_chat_plans")
    elif lang == 'lv':
        b.button(text="🔥  Pagarināt tagad", callback_data="vip_chat_plans")
    else:
        b.button(text="🔥  Renew Now", callback_data="vip_chat_plans")
    b.adjust(1)
    return b.as_markup()


class LoyaltyCronJobs:
    """Automated loyalty system tasks"""
    
    def __init__(self, bot, db, config, loyalty_system):
        self.bot = bot
        self.db = db
        self.config = config
        self.loyalty = loyalty_system

    async def _get_text_setting(self, key: str, fallback: str) -> str:
        return (await self.db.get_setting(key)) or fallback

    async def _get_int_setting(self, key: str, fallback: int) -> int:
        raw = await self.db.get_setting(key)
        try:
            return int(raw) if raw is not None else fallback
        except (TypeError, ValueError):
            return fallback

    def _coupon_block(self, lang: str, coupon_code) -> str:
        if not coupon_code:
            return ""
        if lang == 'ru':
            return (
                f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% скидка на другие планы"
                f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% купон на курсы ({self.config.REMINDER_COUPON_HOURS}ч) ⏰"
                f"\n\nКод: `{coupon_code}`"
            )
        if lang == 'lv':
            return (
                f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% atlaide citiem plāniem"
                f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% kupons kursiem ({self.config.REMINDER_COUPON_HOURS}h) ⏰"
                f"\n\nKods: `{coupon_code}`"
            )
        return (
            f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% discount other plans"
            f"\n✅ {self.config.REMINDER_COUPON_DISCOUNT}% course coupon ({self.config.REMINDER_COUPON_HOURS}h) ⏰"
            f"\n\nCode: `{coupon_code}`"
        )

    def _tier_block(self, lang: str, days: int, tier_emoji: str, tier_name: str, tier_discount: int) -> str:
        if tier_discount <= 0:
            return ""
        if lang == 'ru':
            if days in (7, 30):
                return f"\n\n🎯 ВАЖНО: Сохрани статус {tier_emoji} {tier_name} ({tier_discount}%)!"
            if days == 3:
                return f"\n✅ Сохранить {tier_emoji} {tier_name} ({tier_discount}%)"
            return f"\n❌ Статус {tier_emoji} {tier_name} (-{tier_discount}%)"
        if lang == 'lv':
            if days in (7, 30):
                return f"\n\n🎯 SVARĪGI: Saglabā statusu {tier_emoji} {tier_name} ({tier_discount}%)!"
            if days == 3:
                return f"\n✅ Saglabā {tier_emoji} {tier_name} ({tier_discount}%)"
            return f"\n❌ Statuss {tier_emoji} {tier_name} (-{tier_discount}%)"
        if days in (7, 30):
            return f"\n\n🎯 IMPORTANT: Keep {tier_emoji} {tier_name} status ({tier_discount}%)!"
        if days == 3:
            return f"\n✅ Keep {tier_emoji} {tier_name} ({tier_discount}%)"
        return f"\n❌ {tier_emoji} {tier_name} status (-{tier_discount}%)"
    
    async def daily_loyalty_check(self):
        """
        Daily task: Check and update user loyalty tiers
        Run: 8:00 UTC daily
        """
        logger.info("🔄 Running daily loyalty check...")
        
        try:
            # Get all users with active or recent subscriptions
            all_users = await self.db.fetch_all("""
                SELECT user_id FROM users 
                WHERE expires_at IS NOT NULL
            """)
            
            tier_upgrades = 0
            
            for user_row in all_users:
                user_id = user_row['user_id']
                
                # Check tier
                old_tier, new_tier, changed = await self.loyalty.check_and_update_tier(user_id)
                
                if changed:
                    tier_upgrades += 1
                    logger.info(f"Tier change: user={user_id} {old_tier} → {new_tier}")
                    
                    # Award bonus
                    bonus = await self.loyalty.award_tier_bonus(user_id, new_tier)
                    
                    if bonus:
                        # Send notifications
                        await self.notify_tier_achievement(user_id, old_tier, new_tier, bonus)
                    
                    # Update loyalty record
                    consecutive = await self.loyalty.calculate_consecutive_months(user_id)
                    await self.db.update_user_loyalty(user_id, new_tier, consecutive)
            
            logger.info(f"✅ Daily loyalty check complete: {tier_upgrades} upgrades")
            
        except Exception as e:
            logger.error(f"❌ Daily loyalty check failed: {e}", exc_info=True)
    
    async def daily_loyalty_resets(self):
        """
        Daily task: Check for loyalty resets (30 days + 6h grace)
        Run: 8:00 UTC daily
        """
        logger.info("🔄 Checking loyalty resets...")
        
        try:
            threshold = (datetime.utcnow() - timedelta(
                days=self.config.LOYALTY_RESET_DAYS,
                hours=self.config.LOYALTY_RESET_GRACE_HOURS
            )).isoformat()
            
            users_to_reset = await self.db.get_users_needing_reset(threshold)
            
            for user_row in users_to_reset:
                user_id = user_row['user_id']
                old_tier = user_row['current_tier']
                
                # Reset
                await self.loyalty.reset_loyalty_tier(user_id)
                
                # Notify user
                await self.notify_loyalty_reset(user_id, old_tier)
                
                logger.warning(f"Reset loyalty: user={user_id} {old_tier} → rookie")
            
            logger.info(f"✅ Loyalty resets: {len(users_to_reset)} users reset")
            
        except Exception as e:
            logger.error(f"❌ Loyalty reset check failed: {e}", exc_info=True)
    
    async def send_expiry_reminders(self):
        """
        Daily task: Send reminders before subscription expiry
        Run: 10:00 UTC daily
        """
        logger.info("🔄 Sending expiry reminders...")
        
        try:
            # 7-day reminders
            await self.send_reminders_for_days(7)
            
            # 3-day reminders
            await self.send_reminders_for_days(3)
            
            # 1-day reminders
            await self.send_reminders_for_days(1)
            
            # 30-day reminders (for yearly plans)
            await self.send_reminders_for_days(30)
            
            logger.info("✅ Expiry reminders sent")
            
        except Exception as e:
            logger.error(f"❌ Reminder sending failed: {e}", exc_info=True)
    
    async def send_reminders_for_days(self, days: int):
        """Send reminders for users expiring in N days"""
        users = await self.db.get_users_for_reminders(days)
        
        for user_row in users:
            user_id = user_row['user_id']
            plan_key = user_row.get('plan_key', 'monthly')
            
            # Check if should send reminder based on plan length
            plan_days = self.config.PLANS.get(plan_key, {}).get('days', 30)
            
            # Skip if long subscription and not in final 30 days
            if plan_days >= 180 and days > 30:
                continue
            
            # Get user tier
            loyalty_data = await self.db.get_user_loyalty(user_id)
            tier = loyalty_data.get('current_tier', 'rookie') if loyalty_data else 'rookie'
            
            # Send reminder
            await self.send_reminder_message(user_id, days, tier)
    
    async def send_reminder_message(self, user_id: int, days: int, tier: str):
        """Send reminder message to user"""
        try:
            user = await self.db.get_user(user_id)
            lang = user.get('lang', 'ru')
            
            # Generate coupon if applicable (7-day reminder only)
            coupon_code = None
            if days == 7:
                coupon_code = await self.loyalty.generate_reminder_coupon(user_id, tier)
            
            # Get tier info
            tier_data = self.config.LOYALTY_TIERS[tier]
            tier_discount = tier_data.get('chat_discount', 0)
            tier_emoji = tier_data.get('emoji', '')
            tier_name = tier_data.get('tag', tier)

            bonus_days = await self._get_int_setting("remarketing_reminder_bonus_days", self.config.REMINDER_BONUS_DAYS)
            template = await self._get_text_setting(
                f"remarketing_reminder_{days}_{lang}",
                ""
            )
            if not template:
                logger.warning(f"Missing remarketing reminder template: days={days} lang={lang}")
                return

            text = template.format(
                bonus_days=bonus_days,
                coupon_block=self._coupon_block(lang, coupon_code),
                tier_block=self._tier_block(lang, days, tier_emoji, tier_name, tier_discount),
                tier_emoji=tier_emoji,
                tier_name=tier_name,
                tier_discount=tier_discount,
                coupon_code=coupon_code or "",
                coupon_discount=self.config.REMINDER_COUPON_DISCOUNT,
                coupon_hours=self.config.REMINDER_COUPON_HOURS,
            )
            
            await self.bot.send_message(user_id, text, reply_markup=_cron_renew_keyboard(lang), parse_mode="Markdown")
            logger.info(f"Sent {days}d reminder: user={user_id}")
            
        except Exception as e:
            logger.error(f"Failed to send reminder: user={user_id} error={e}")
    
    async def trigger_winback_campaigns(self):
        """
        Daily task: Trigger win-back campaigns for expired users
        Run: 12:00 UTC daily
        """
        logger.info("🔄 Triggering win-back campaigns...")
        
        try:
            # Get users who expired exactly 5 days ago
            trigger_days = await self._get_int_setting("remarketing_winback_trigger_days", self.config.WINBACK_TRIGGER_DAYS)
            users = await self.db.get_expired_users_for_winback(trigger_days)
            
            for user_row in users:
                user_id = user_row['user_id']
                
                # Check if can use win-back
                can_use = await self.loyalty.can_use_winback(user_id)
                
                if not can_use:
                    logger.info(f"Win-back limit reached: user={user_id}")
                    continue
                
                # Send win-back offer
                await self.send_winback_offer(user_id)
            
            logger.info(f"✅ Win-back campaigns: {len(users)} users contacted")
            
        except Exception as e:
            logger.error(f"❌ Win-back campaign failed: {e}", exc_info=True)
    
    async def send_winback_offer(self, user_id: int):
        """Send win-back offer to user"""
        try:
            user = await self.db.get_user(user_id)
            lang = user.get('lang', 'ru')
            bonus_days = await self._get_int_setting("remarketing_winback_bonus_days", 7)
            offer_hours = await self._get_int_setting("remarketing_offer_hours", 72)

            text = (await self._get_text_setting(f"remarketing_winback_{lang}", "")).format(
                bonus_days=bonus_days,
                yearly_discount=self.config.WINBACK_YEARLY_DISCOUNT,
                course_discount=self.config.REMINDER_COUPON_DISCOUNT,
                offer_hours=offer_hours,
            )

            await self.db.create_winback_offer(user_id, bonus_days, offer_hours)
            
            await self.bot.send_message(user_id, text, reply_markup=_cron_renew_keyboard(lang), parse_mode="Markdown")
            
            # Also send survey
            await self.send_survey(user_id, lang)
            
            logger.info(f"Sent win-back offer: user={user_id}")
            
        except Exception as e:
            logger.error(f"Failed to send win-back: user={user_id} error={e}")
    
    async def send_survey(self, user_id: int, lang: str):
        """Send survey to user"""
        # This will be handled in bot.py with callback buttons
        # Just log for now
        logger.info(f"Survey trigger: user={user_id}")
    
    async def cleanup_expired_coupons(self):
        """
        Daily task: Clean up expired coupons
        Run: 2:00 UTC daily
        """
        logger.info("🔄 Cleaning up expired coupons...")
        
        try:
            await self.db.cleanup_expired_coupons()
            logger.info("✅ Expired coupons cleaned")
            
        except Exception as e:
            logger.error(f"❌ Coupon cleanup failed: {e}", exc_info=True)
    
    async def remind_pending_tags(self):
        """
        Daily task: Remind admin about pending tag updates
        Run: 9:00 UTC daily
        """
        logger.info("🔄 Checking pending tags...")
        
        try:
            pending = await self.db.get_pending_tags_today()
            
            if not pending:
                return
            
            # Group by tier
            by_tier = {}
            for user_row in pending:
                tier = user_row['tier']
                if tier not in by_tier:
                    by_tier[tier] = []
                by_tier[tier].append(user_row)
            
            # Build message
            text = f"🏷 **PENDING TAG UPDATES: {len(pending)}**\n\n"
            
            for tier, users in by_tier.items():
                tier_data = self.config.LOYALTY_TIERS.get(tier, {})
                emoji = tier_data.get('emoji', '')
                tag = tier_data.get('tag', tier)
                
                text += f"{emoji} {tier.upper()}: {len(users)} users\n"
                
                for user in users[:5]:  # Top 5
                    username = user.get('username', 'Unknown')
                    text += f"  • @{username}\n"
                
                if len(users) > 5:
                    text += f"  ... and {len(users)-5} more\n"
                
                text += "\n"
            
            text += "\n⚙️ Set member tags manually in Telegram"
            
            # Send to all admins
            for admin_id in self.config.ADMIN_IDS:
                try:
                    await self.bot.send_message(admin_id, text, parse_mode="Markdown")
                except:
                    pass
            
            logger.info(f"✅ Pending tags reminder: {len(pending)} users")
            
        except Exception as e:
            logger.error(f"❌ Pending tags reminder failed: {e}", exc_info=True)
    
    async def notify_tier_achievement(self, user_id: int, old_tier: str, new_tier: str, bonus: dict):
        """Send public and private tier achievement notifications"""
        try:
            user = await self.db.get_user(user_id)
            username = user.get('username', f'user_{user_id}')
            lang = user.get('lang', 'ru')
            
            # Get public announcement language setting
            pub_lang = await self.db.get_setting('public_announcement_lang') or 'ru'
            
            tier_data = self.config.LOYALTY_TIERS[new_tier]
            emoji = tier_data.get('emoji', '')
            tag = tier_data.get('tag', new_tier)
            
            # PUBLIC announcement (chat)
            if pub_lang == 'ru':
                if new_tier == 'legend':
                    pub_text = f"""🔱⚡️ ЛЕГЕНДАРНЫЙ СТАТУС! ⚡️🔱

@{username} стал 🔱 LEGEND TRADER!

🎁 Максимальные бонусы:
• +30 дней (МЕСЯЦ!) бесплатно
• 20% ПОЖИЗНЕННАЯ скидка
• Высший статус
• Эксклюзивные сигналы
• Premium поддержка

👑 Спасибо за лояльность, Legend! 🏆"""
                else:
                    pub_text = f"""🎉 ПОЗДРАВЛЯЕМ!

@{username} достиг статуса {emoji} {tag}!

🎁 Бонусы:
• +{bonus.get('bonus_days', 0)} дней бесплатного абонемента
• {tier_data.get('chat_discount', 0)}% пожизненная скидка"""
                    
                    if bonus.get('free_course'):
                        pub_text += "\n• 🎓 Курс Power Up (100$ стоимость)"
                    
                    pub_text += f"\n\nПродолжай! 🚀"
            
            else:  # EN
                if new_tier == 'legend':
                    pub_text = f"""🔱⚡️ LEGENDARY STATUS! ⚡️🔱

@{username} became 🔱 LEGEND TRADER!

🎁 Ultimate bonuses:
• +30 days (MONTH!) free
• 20% LIFETIME discount
• Highest status
• Exclusive signals
• Premium support

👑 Thank you for loyalty, Legend! 🏆"""
                else:
                    pub_text = f"""🎉 CONGRATULATIONS!

@{username} reached {emoji} {tag} status!

🎁 Bonuses:
• +{bonus.get('bonus_days', 0)} days free subscription
• {tier_data.get('chat_discount', 0)}% lifetime discount"""
                    
                    if bonus.get('free_course'):
                        pub_text += "\n• 🎓 Power Up Course (100$ value)"
                    
                    pub_text += f"\n\nKeep going! 🚀"
            
            # Send to chat
            await self.bot.send_message(self.config.CHAT_ID, pub_text)
            
            # PRIVATE DM (user's language)
            # This will be more detailed - implement in bot.py
            
            # Create tag update notification for admin
            await self.db.create_tag_update(user_id, new_tier)
            
            logger.info(f"Notified tier achievement: user={user_id} tier={new_tier}")
            
        except Exception as e:
            logger.error(f"Failed to notify achievement: user={user_id} error={e}")
    
    async def notify_loyalty_reset(self, user_id: int, old_tier: str):
        """Notify user about loyalty reset"""
        try:
            user = await self.db.get_user(user_id)
            lang = user.get('lang', 'ru')
            
            tier_data = self.config.LOYALTY_TIERS.get(old_tier, {})
            emoji = tier_data.get('emoji', '')
            tag = tier_data.get('tag', old_tier)
            discount = tier_data.get('chat_discount', 0)
            
            if lang == 'ru':
                text = f"""😔 Твой loyalty статус был сброшен

Потеряно:
• {emoji} {tag} → Member
• {discount}% скидка → 0%

💡 Продли абонемент и начни путь заново!
Достигни {tag} за {tier_data.get('min_months', 0)} месяцев.

"""
            
            else:
                text = f"""😔 Your loyalty status was reset

Lost:
• {emoji} {tag} → Member
• {discount}% discount → 0%

💡 Renew subscription and start the journey again!
Reach {tag} in {tier_data.get('min_months', 0)} months.

"""
            
            await self.bot.send_message(user_id, text, reply_markup=_cron_renew_keyboard(lang), parse_mode="Markdown")
            
            logger.info(f"Notified loyalty reset: user={user_id} tier={old_tier}")
            
        except Exception as e:
            logger.error(f"Failed to notify reset: user={user_id} error={e}")


# Scheduler setup helper
def setup_loyalty_cron(scheduler, bot, db, config, loyalty_system):
    """
    Setup APScheduler jobs for loyalty system
    
    Usage in bot.py:
        from cron_jobs import setup_loyalty_cron
        setup_loyalty_cron(scheduler, bot, db, config, loyalty_system)
    """
    jobs = LoyaltyCronJobs(bot, db, config, loyalty_system)
    
    # Daily 8:00 UTC - Loyalty checks and resets
    scheduler.add_job(
        jobs.daily_loyalty_check,
        trigger='cron',
        hour=8,
        minute=0,
        id='daily_loyalty_check'
    )
    
    scheduler.add_job(
        jobs.daily_loyalty_resets,
        trigger='cron',
        hour=8,
        minute=30,
        id='daily_loyalty_resets'
    )
    
    # Daily 10:00 UTC - Expiry reminders
    scheduler.add_job(
        jobs.send_expiry_reminders,
        trigger='cron',
        hour=10,
        minute=0,
        id='send_expiry_reminders'
    )
    
    # Daily 12:00 UTC - Win-back campaigns
    scheduler.add_job(
        jobs.trigger_winback_campaigns,
        trigger='cron',
        hour=12,
        minute=0,
        id='trigger_winback_campaigns'
    )
    
    # Daily 2:00 UTC - Cleanup
    scheduler.add_job(
        jobs.cleanup_expired_coupons,
        trigger='cron',
        hour=2,
        minute=0,
        id='cleanup_expired_coupons'
    )
    
    # Daily 9:00 UTC - Admin reminders
    scheduler.add_job(
        jobs.remind_pending_tags,
        trigger='cron',
        hour=9,
        minute=0,
        id='remind_pending_tags'
    )
    
    logger.info("✅ Loyalty cron jobs scheduled")
