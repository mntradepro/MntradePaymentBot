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
            
            # Build message based on days and tier
            if lang == 'ru':
                if days == 7:
                    text = f"""📅 Абонемент закончится через 7 дней!

💰 ПРОДЛИ СЕЙЧАС — получи:
✅ +{self.config.REMINDER_BONUS_DAYS} дней бесплатно"""
                    
                    if coupon_code:
                        text += f"""
✅ 5% скидка на другие планы
✅ 5% купон на курсы (24ч) ⏰

Код: `{coupon_code}`"""
                    
                    if tier_discount > 0:
                        text += f"""

🎯 ВАЖНО: Сохрани статус {tier_emoji} {tier_name} ({tier_discount}%)!"""
                    
                    text += "\n\n"
                
                elif days == 3:
                    text = f"""⚠️ 3 ДНЯ до окончания абонемента!

💰 Самое время продлить и получить:
✅ +{self.config.REMINDER_BONUS_DAYS} дней бесплатно"""
                    
                    if tier_discount > 0:
                        text += f"""
✅ Сохранить {tier_emoji} {tier_name} ({tier_discount}%)"""
                    
                    text += "\n\n"
                
                elif days == 1:
                    text = f"""🚨 ПОСЛЕДНИЙ ДЕНЬ!

Завтра потеряешь:
❌ Доступ к VIP чату"""
                    
                    if tier_discount > 0:
                        text += f"""
❌ Статус {tier_emoji} {tier_name} (-{tier_discount}%)"""
                    
                    text += """

💡 Продли СЕЙЧАС - не упусти момент!

"""
                
                elif days == 30:
                    text = f"""📅 Годовой абонемент заканчивается через месяц

ℹ️ Напоминание:
До окончания подписки осталось 30 дней"""
                    
                    if tier_discount > 0:
                        text += f"""

💎 Твой статус: {tier_emoji} {tier_name} ({tier_discount}%)"""
                    
                    text += """

Чтобы сохранить статус и привилегии,
продли подписку до истечения срока.

"""
            
            else:  # EN
                if days == 7:
                    text = f"""📅 Subscription expires in 7 days!

💰 RENEW NOW — get:
✅ +{self.config.REMINDER_BONUS_DAYS} days free"""
                    
                    if coupon_code:
                        text += f"""
✅ 5% discount other plans
✅ 5% course coupon (24h) ⏰

Code: `{coupon_code}`"""
                    
                    if tier_discount > 0:
                        text += f"""

🎯 IMPORTANT: Keep {tier_emoji} {tier_name} status ({tier_discount}%)!"""
                    
                    text += "\n\n"
                
                elif days == 3:
                    text = f"""⚠️ 3 DAYS until subscription ends!

💰 Time to renew and get:
✅ +{self.config.REMINDER_BONUS_DAYS} days free"""
                    
                    if tier_discount > 0:
                        text += f"""
✅ Keep {tier_emoji} {tier_name} ({tier_discount}%)"""
                    
                    text += "\n\n"
                
                elif days == 1:
                    text = f"""🚨 LAST DAY!

Tomorrow you'll lose:
❌ VIP chat access"""
                    
                    if tier_discount > 0:
                        text += f"""
❌ {tier_emoji} {tier_name} status (-{tier_discount}%)"""
                    
                    text += """

💡 RENEW NOW - don't miss out!

"""
                
                elif days == 30:
                    text = f"""📅 Yearly subscription expires in a month

ℹ️ Reminder:
30 days until subscription ends"""
                    
                    if tier_discount > 0:
                        text += f"""

💎 Your status: {tier_emoji} {tier_name} ({tier_discount}%)"""
                    
                    text += """

To keep your status and privileges,
renew before expiration.

"""
            
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
            users = await self.db.get_expired_users_for_winback(
                self.config.WINBACK_TRIGGER_DAYS
            )
            
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
            
            if lang == 'ru':
                text = """💔 Мы тебя потеряли...

Вернись в MNtradepro VIP с бонусами:

🎁 WELCOME BACK бонусы:
• 7 дней БЕСПЛАТНО
• 10% скидка на год
• 5% скидка на курсы

⏰ Предложение 72 часа

"""
            
            else:
                text = """💔 We lost you...

Return to MNtradepro VIP with bonuses:

🎁 WELCOME BACK bonuses:
• 7 days FREE
• 10% discount yearly
• 5% discount courses

⏰ Offer valid 72h

"""
            
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
