# ═══════════════════════════════════════════════════════════════
# ADMIN LOYALTY PANEL ADDON
# Add these handlers to admin.py
# ═══════════════════════════════════════════════════════════════

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
import logging

logger = logging.getLogger(__name__)

# Create router for admin loyalty handlers
admin_loyalty_router = Router()


# ═══════════════════════════════════════════════════════════════
# LOYALTY DASHBOARD
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.callback_query(F.data == "adm_loyalty_stats")
async def show_loyalty_stats(callback: CallbackQuery, db, config):
    """Show loyalty statistics dashboard"""
    
    # Get stats
    users_by_tier = await db.get_users_by_tier()
    total_bonuses = await db.get_total_bonuses_given()
    
    # Count courses granted
    all_courses = await db.fetch_all("SELECT COUNT(*) as count FROM course_grants")
    courses_count = all_courses[0]['count'] if all_courses else 0
    
    # Build tier distribution
    tier_counts = {tier: 0 for tier in config.LOYALTY_TIERS.keys()}
    for row in users_by_tier:
        tier_counts[row['current_tier']] = row['count']
    
    total_users = sum(tier_counts.values())
    
    text = """📊 **LOYALTY STATISTICS**

━━━━━━━━━━━━━━━━

👥 **User Distribution:**
"""
    
    for tier_name in ['legend', 'master', 'elite', 'pro', 'active', 'rookie']:
        tier_data = config.LOYALTY_TIERS[tier_name]
        emoji = tier_data.get('emoji', '')
        count = tier_counts.get(tier_name, 0)
        percentage = (count / total_users * 100) if total_users > 0 else 0
        
        bar_length = 20
        filled = int(percentage / 100 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        text += f"\n{emoji} **{tier_name.upper()}**: {count} ({percentage:.1f}%)\n{bar}\n"
    
    text += f"""
━━━━━━━━━━━━━━━━

💰 **Total Bonus Days Given:** {total_bonuses}
🎓 **Courses Granted:** {courses_count}
👥 **Total Active Users:** {total_users}

━━━━━━━━━━━━━━━━
"""
    
    b = InlineKeyboardBuilder()
    b.button(text="🏷 Pending Tags", callback_data="adm_pending_tags")
    b.button(text="🎟 Coupons", callback_data="adm_coupons_stats")
    b.button(text="📋 Survey Responses", callback_data="adm_survey_responses")
    b.button(text="🔙 Back", callback_data="adm_main")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# PENDING TAGS MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.callback_query(F.data == "adm_pending_tags")
async def show_pending_tags(callback: CallbackQuery, db, config):
    """Show pending tag updates"""
    
    pending = await db.get_pending_tag_updates()
    
    if not pending:
        await callback.answer("✅ No pending tag updates!", show_alert=True)
        return
    
    text = f"🏷 **PENDING TAG UPDATES**\n\n"
    text += f"Total: {len(pending)} users\n\n"
    text += "━━━━━━━━━━━━━━━━\n\n"
    
    b = InlineKeyboardBuilder()
    
    for user_row in pending[:10]:  # Show first 10
        user_id = user_row['user_id']
        username = user_row.get('username', f'user_{user_id}')
        tier = user_row['tier']
        tag_name = user_row['tag_name']
        
        tier_data = config.LOYALTY_TIERS.get(tier, {})
        emoji = tier_data.get('emoji', '')
        
        text += f"{emoji} **@{username}**\n"
        text += f"   Tag: `{tag_name}`\n"
        text += f"   User ID: `{user_id}`\n\n"
        
        b.button(text=f"✅ {username}", callback_data=f"tag_done_{user_id}")
    
    if len(pending) > 10:
        text += f"\n... and {len(pending) - 10} more\n\n"
    
    text += """━━━━━━━━━━━━━━━━

⚙️ **How to set tags:**
1. Open Telegram → VIP Chat
2. Find user → View Profile
3. Edit → Member tag
4. Set tag as shown above
5. Click ✅ button here

"""
    
    b.button(text="✅ Mark All Done", callback_data="tag_done_all")
    b.button(text="🔙 Back", callback_data="adm_loyalty_stats")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@admin_loyalty_router.callback_query(F.data.startswith("tag_done_"))
async def mark_tag_done(callback: CallbackQuery, db):
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
    await show_pending_tags(callback, db, config)


# ═══════════════════════════════════════════════════════════════
# COUPON STATISTICS
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.callback_query(F.data == "adm_coupons_stats")
async def show_coupons_stats(callback: CallbackQuery, db):
    """Show coupon statistics"""
    
    # Get stats
    all_coupons = await db.fetch_all("""
        SELECT coupon_type, COUNT(*) as count, SUM(times_used) as total_uses
        FROM personal_coupons
        WHERE is_active = 1
        GROUP BY coupon_type
    """)
    
    total_active = 0
    stats_by_type = {}
    
    for row in all_coupons:
        coupon_type = row['coupon_type']
        count = row['count']
        total_uses = row.get('total_uses', 0) or 0
        
        total_active += count
        stats_by_type[coupon_type] = {
            'count': count,
            'uses': total_uses
        }
    
    text = """🎟 **PROMO CODES DASHBOARD**

━━━━━━━━━━━━━━━━

📊 **Active Codes:** """ + str(total_active) + "\n\n"
    
    for coupon_type in ['loyalty_tier', 'reminder_bonus', 'winback', 'survey']:
        stats = stats_by_type.get(coupon_type, {'count': 0, 'uses': 0})
        
        if coupon_type == 'loyalty_tier':
            icon = "🎯"
            name = "Loyalty Tier Codes"
        elif coupon_type == 'reminder_bonus':
            icon = "🎁"
            name = "Reminder Bonuses"
        elif coupon_type == 'winback':
            icon = "🔙"
            name = "Win-Back Offers"
        else:
            icon = "📊"
            name = "Survey Rewards"
        
        text += f"{icon} **{name}**\n"
        text += f"   Active: {stats['count']} | Used: {stats['uses']}x\n\n"
    
    text += "━━━━━━━━━━━━━━━━\n"
    
    b = InlineKeyboardBuilder()
    b.button(text="🔍 View All", callback_data="adm_view_coupons")
    b.button(text="➕ Create", callback_data="adm_create_coupon")
    b.button(text="🗑 Cleanup", callback_data="adm_cleanup_coupons")
    b.button(text="🔙 Back", callback_data="adm_loyalty_stats")
    b.adjust(2, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@admin_loyalty_router.callback_query(F.data == "adm_cleanup_coupons")
async def cleanup_coupons(callback: CallbackQuery, db):
    """Manually trigger coupon cleanup"""
    
    await db.cleanup_expired_coupons()
    await callback.answer("✅ Expired coupons cleaned up!")
    await show_coupons_stats(callback, db)


# ═══════════════════════════════════════════════════════════════
# SURVEY RESPONSES
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.callback_query(F.data == "adm_survey_responses")
async def show_survey_responses(callback: CallbackQuery, db):
    """Show recent survey responses"""
    
    responses = await db.get_survey_responses(limit=20)
    
    if not responses:
        await callback.answer("📋 No survey responses yet", show_alert=True)
        return
    
    text = "📋 **SURVEY RESPONSES**\n\n"
    text += f"Last {len(responses)} responses:\n\n"
    text += "━━━━━━━━━━━━━━━━\n\n"
    
    for resp in responses[:10]:
        username = resp.get('username', 'Unknown')
        response_type = resp['response_type']
        custom_text = resp.get('custom_text')
        created_at = resp['created_at']
        
        # Format date
        dt = datetime.fromisoformat(created_at)
        date_str = dt.strftime("%d.%m %H:%M")
        
        # Response icon
        if response_type == 'expensive':
            icon = "💸"
            reason = "Too expensive"
        elif response_type == 'content':
            icon = "📉"
            reason = "Not enough value"
        elif response_type == 'time':
            icon = "⏰"
            reason = "No time"
        elif response_type == 'confused':
            icon = "❓"
            reason = "Didn't understand"
        else:
            icon = "📝"
            reason = "Custom"
        
        text += f"{icon} **@{username}** - {date_str}\n"
        text += f"   {reason}\n"
        
        if custom_text:
            text += f"   💬 _{custom_text[:50]}{'...' if len(custom_text) > 50 else ''}_\n"
        
        text += "\n"
    
    if len(responses) > 10:
        text += f"... and {len(responses) - 10} more\n\n"
    
    text += "━━━━━━━━━━━━━━━━\n"
    
    b = InlineKeyboardBuilder()
    b.button(text="📊 Export CSV", callback_data="adm_export_survey")
    b.button(text="🔙 Back", callback_data="adm_loyalty_stats")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# SETTINGS - PUBLIC ANNOUNCEMENT LANGUAGE
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.callback_query(F.data == "adm_settings")
async def show_admin_settings(callback: CallbackQuery, db):
    """Show admin settings"""
    
    # Get current public lang
    pub_lang = await db.get_setting('public_announcement_lang') or 'ru'
    
    flag_map = {'ru': '🇷🇺', 'en': '🇬🇧', 'lv': '🇱🇻'}
    
    text = f"""⚙️ **BOT SETTINGS**

━━━━━━━━━━━━━━━━

📢 **Public Announcements Language**

Current: {flag_map.get(pub_lang, '🇷🇺')} **{pub_lang.upper()}**

Used for tier achievements in VIP chat.
Private messages stay in user's language.

━━━━━━━━━━━━━━━━
"""
    
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский (RU)", callback_data="set_pub_lang_ru")
    b.button(text="🇬🇧 English (EN)", callback_data="set_pub_lang_en")
    b.button(text="🇱🇻 Latviešu (LV)", callback_data="set_pub_lang_lv")
    b.button(text="🔙 Back", callback_data="adm_main")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@admin_loyalty_router.callback_query(F.data.startswith("set_pub_lang_"))
async def set_public_language(callback: CallbackQuery, db):
    """Set public announcement language"""
    
    lang = callback.data[13:]  # Remove "set_pub_lang_"
    
    await db.set_setting('public_announcement_lang', lang)
    
    await callback.answer(f"✅ Public language set to {lang.upper()}")
    await show_admin_settings(callback, db)


# ═══════════════════════════════════════════════════════════════
# MANUAL LOYALTY MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@admin_loyalty_router.message(Command("admin_set_tier"))
async def admin_set_tier_command(message: Message, db, config):
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


@admin_loyalty_router.message(Command("admin_add_days"))
async def admin_add_days_command(message: Message, db):
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


# ═══════════════════════════════════════════════════════════════
# INTEGRATION INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════

"""
TO INTEGRATE INTO admin.py:

1. Import at top:
   from admin_loyalty_addon import admin_loyalty_router

2. Include router:
   dp.include_router(admin_loyalty_router)

3. Add "📊 Loyalty Stats" button to main admin menu in admin.py:
   
   In adm_main handler, add button:
   b.button(text="📊 Loyalty Stats", callback_data="adm_loyalty_stats")

4. Add "⚙️ Settings" button to main admin menu:
   b.button(text="⚙️ Settings", callback_data="adm_settings")

5. Pass dependencies:
   admin_loyalty_router.callback_query.middleware(lambda h, d: d.update({
       'db': db,
       'config': config
   }))
"""
