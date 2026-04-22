# ═══════════════════════════════════════════════════════════════
# BOT LOYALTY HANDLERS ADDON
# Add these handlers to bot.py
# ═══════════════════════════════════════════════════════════════

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Create router for loyalty handlers
loyalty_router = Router()


# ═══════════════════════════════════════════════════════════════
# LOYALTY PROGRESS & STATUS
# ═══════════════════════════════════════════════════════════════

@loyalty_router.message(Command("loyalty"))
async def show_loyalty_status(message: Message, db, config, loyalty_system):
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

{emoji} **{tag.upper()}** ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} месяцев
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Следующий: {next_emoji} **{next_tag.upper()}**
📅 До цели: {months_left} {'месяц' if months_left == 1 else 'месяца' if months_left < 5 else 'месяцев'}! 🔥

🎁 Получишь:
   • +{next_bonus} дней бесплатно
   • {next_discount}% скидка (против {discount}%)
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up курс (100$ стоимость)"
        
        else:
            text += f"""
🔱 **ТЫ ДОСТИГ МАКСИМУМА!**
👑 Legend статус - высшее достижение!

Спасибо за {consecutive_months} месяцев лояльности! 🏆"""
        
        text += "\n\n💡 *Продолжай продлять - сохраняй статус!*"
    
    else:  # EN
        text = f"""📊 Your Loyalty Progress

{emoji} **{tag.upper()}** ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} months
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Next: {next_emoji} **{next_tag.upper()}**
📅 Time left: {months_left} {'month' if months_left == 1 else 'months'}! 🔥

🎁 You'll get:
   • +{next_bonus} days free
   • {next_discount}% discount (vs {discount}%)
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up course (100$ value)"
        
        else:
            text += f"""
🔱 **YOU REACHED THE TOP!**
👑 Legend status - ultimate achievement!

Thank you for {consecutive_months} months of loyalty! 🏆"""
        
        text += "\n\n💡 *Keep renewing - maintain your status!*"
    
    b = InlineKeyboardBuilder()
    b.button(text="💳 " + ("Мои промокоды" if lang == 'ru' else "My Promo Codes"), 
             callback_data="my_promo_codes")
    b.button(text="💎 " + ("Продлить" if lang == 'ru' else "Renew"), 
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
# PROMO CODES DISPLAY
# ═══════════════════════════════════════════════════════════════


@loyalty_router.callback_query(F.data == "loyalty_status")
async def loyalty_status_callback(callback: CallbackQuery, db, config, loyalty_system):
    """Handle loyalty status button from main menu"""
    # Reuse the same logic but for callback
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
    emoji = tier_data.get('emoji', '')
    tag = tier_data.get('tag', current_tier)
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
    
    # Build progress bar
    if next_tier:
        progress = consecutive_months / target_months
        bar_length = 20
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        months_left = target_months - consecutive_months
    else:
        bar = "█" * 20
        months_left = 0
    
    if lang == 'ru':
        text = f"""📊 Твой Прогресс Лояльности

{emoji} **{tag.upper()}** ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} месяцев
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Следующий: {next_emoji} **{next_tag.upper()}**
📅 До цели: {months_left} {'месяц' if months_left == 1 else 'месяца' if months_left < 5 else 'месяцев'}

🎁 Получишь:
   • +{next_bonus} дней бесплатно
   • {next_discount}% скидка
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up курс (100$)"
        else:
            text += f"""
🔱 **ТЫ ДОСТИГ МАКСИМУМА!**
👑 Legend статус!

Спасибо за {consecutive_months} месяцев! 🏆"""
        
        text += "\n\n💡 *Продолжай продлять - сохраняй статус!*"
    
    else:  # EN
        text = f"""📊 Your Loyalty Progress

{emoji} **{tag.upper()}** ({discount}%)
{bar} {consecutive_months}/{target_months if next_tier else consecutive_months} months
"""
        
        if next_tier:
            next_emoji = config.LOYALTY_TIERS[next_tier]['emoji']
            next_tag = config.LOYALTY_TIERS[next_tier]['tag']
            next_discount = config.LOYALTY_TIERS[next_tier]['chat_discount']
            next_bonus = config.LOYALTY_TIERS[next_tier]['bonus_days']
            
            text += f"""
➡️ Next: {next_emoji} **{next_tag.upper()}**
📅 Months left: {months_left}

🎁 You'll get:
   • +{next_bonus} days free
   • {next_discount}% discount
   • {next_emoji} {next_tag} badge"""
            
            if next_tier == 'elite':
                text += "\n   • 🎓 Power Up course (100$)"
        else:
            text += f"""
🔱 **YOU REACHED THE TOP!**
👑 Legend status!

Thank you for {consecutive_months} months! 🏆"""
        
        text += "\n\n💡 *Keep renewing!*"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="💳 " + ("Мои промокоды" if lang == 'ru' else "My Promo Codes"), 
             callback_data="my_promo_codes")
    b.button(text="💎 " + ("Продлить" if lang == 'ru' else "Renew"), 
             callback_data="vip_chat_plans")
    b.button(text="🔙 " + ("Назад" if lang == 'ru' else "Back"),
             callback_data="start")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer()


@loyalty_router.callback_query(F.data == "my_promo_codes")
async def show_promo_codes(callback: CallbackQuery, db, config):
    """Show user's active promo codes"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru')
    
    # Get active coupons
    coupons = await db.get_active_coupons(user_id)
    
    if not coupons:
        text = "❌ " + ("У тебя нет активных промокодов" if lang == 'ru' else "You have no active promo codes")
        await callback.message.edit_text(text)
        await callback.answer()
        return
    
    if lang == 'ru':
        text = "💳 **ТВОИ ПРОМОКОДЫ**\n\n"
    else:
        text = "💳 **YOUR PROMO CODES**\n\n"
    
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
                text += f"🎯 **Loyalty Discount**\n\n"
            else:
                text += f"🎯 **Loyalty Discount**\n\n"
        
        elif coupon_type == 'reminder_bonus':
            if lang == 'ru':
                text += f"🎁 **Reminder Bonus**\n\n"
            else:
                text += f"🎁 **Reminder Bonus**\n\n"
        
        elif coupon_type == 'winback':
            if lang == 'ru':
                text += f"🔙 **Welcome Back**\n\n"
            else:
                text += f"🔙 **Welcome Back**\n\n"
        
        elif coupon_type == 'survey':
            if lang == 'ru':
                text += f"📊 **Survey Reward**\n\n"
            else:
                text += f"📊 **Survey Reward**\n\n"
        
        # Code
        if lang == 'ru':
            text += f"Код: `{code}`\n"
            text += f"Скидка: **{discount}%**\n"
        else:
            text += f"Code: `{code}`\n"
            text += f"Discount: **{discount}%**\n"
        
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


@loyalty_router.callback_query(F.data.startswith("copy_"))
async def copy_coupon_code(callback: CallbackQuery):
    """Handle coupon code copy"""
    code = callback.data[5:]  # Remove "copy_"
    
    # Just show in answer popup
    await callback.answer(f"✅ {code}", show_alert=True, cache_time=1)


# ═══════════════════════════════════════════════════════════════
# WIN-BACK SURVEY
# ═══════════════════════════════════════════════════════════════

@loyalty_router.callback_query(F.data == "winback_survey")
async def show_winback_survey(callback: CallbackQuery, db):
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


@loyalty_router.callback_query(F.data.startswith("survey_"))
async def handle_survey_response(callback: CallbackQuery, db, config, loyalty_system):
    """Handle survey response"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get('lang', 'ru')
    
    response_type = callback.data[7:]  # Remove "survey_"
    
    if response_type == 'custom':
        # Ask for custom text (handle in message handler)
        if lang == 'ru':
            text = "📝 Напиши свою причину:"
        else:
            text = "📝 Write your reason:"
        
        await callback.message.edit_text(text)
        await callback.answer()
        # Set state for next message
        # (Implement FSM state if needed)
        return
    
    # Generate reward coupon
    coupon_code = await loyalty_system.generate_winback_coupon(user_id, survey_response=True)
    
    # Save response
    await db.save_survey_response(user_id, response_type, None, coupon_code)
    
    # Log win-back usage
    await db.log_winback_usage(user_id, 'survey_coupon', coupon_code)
    
    if lang == 'ru':
        text = f"""🎁 **Спасибо за ответ!**

Твоя награда:
💳 Код: `{coupon_code}`
💰 Скидка: **20%** на всё
⏰ Действует: 24 часа

Используй при оплате!

[💎 Перейти к тарифам]"""
    else:
        text = f"""🎁 **Thanks for your feedback!**

Your reward:
💳 Code: `{coupon_code}`
💰 Discount: **20%** on everything
⏰ Valid: 24 hours

Use at checkout!

[💎 Go to plans]"""
    
    b = InlineKeyboardBuilder()
    b.button(text=("💎 Тарифы" if lang == 'ru' else "💎 Plans"), 
             callback_data="vip_chat_plans")
    b.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="Markdown")
    await callback.answer("✅")


# ═══════════════════════════════════════════════════════════════
# HELPER: Get translated text
# ═══════════════════════════════════════════════════════════════

def t(lang: str, key: str, **kwargs):
    """Get translated text"""
    # Implement translations dict or use existing system
    # For now, simple placeholder
    return key


# ═══════════════════════════════════════════════════════════════
# INTEGRATION INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════

"""
TO INTEGRATE INTO bot.py:

1. Import at top of bot.py:
   from bot_loyalty_addon import loyalty_router

2. Include router in dispatcher:
   dp.include_router(loyalty_router)

3. Pass dependencies in main():
   # After creating loyalty_system
   loyalty_router.message.middleware(lambda h, d: d.update({
       'db': db,
       'config': config,
       'loyalty_system': loyalty_system
   }))

4. Initialize loyalty system in main():
   from loyalty_system import LoyaltySystem
   loyalty_system = LoyaltySystem(config, db)

5. Setup cron jobs:
   from cron_jobs import setup_loyalty_cron
   setup_loyalty_cron(scheduler, bot, db, config, loyalty_system)
"""
