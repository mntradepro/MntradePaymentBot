# ═══════════════════════════════════════════════════════════════
# LOYALTY & RETENTION SYSTEM - CORE LOGIC
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple
import secrets

logger = logging.getLogger(__name__)


class LoyaltySystem:
    """Core loyalty tier calculation and management"""
    
    def __init__(self, config, db):
        self.config = config
        self.db = db
    
    async def calculate_tier_from_months(self, consecutive_months: int) -> str:
        """
        Calculate loyalty tier based on consecutive active months
        
        Args:
            consecutive_months: Number of consecutive paid months
            
        Returns:
            Tier name: 'rookie', 'active', 'pro', 'elite', 'master', 'legend'
        """
        for tier_name in ['legend', 'master', 'elite', 'pro', 'active', 'rookie']:
            tier_data = self.config.LOYALTY_TIERS[tier_name]
            if consecutive_months >= tier_data['min_months']:
                if consecutive_months < tier_data['max_months']:
                    return tier_name
        
        return 'rookie'
    
    async def calculate_consecutive_months(self, user_id: int) -> int:
        """
        Calculate consecutive paid months for a user
        
        Uses payment history to determine consecutive subscription months.
        Gap threshold: 7 days between payments is allowed.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Number of consecutive months
        """
        payments = await self.db.get_user_payment_history(user_id)
        
        if not payments:
            return 0
        
        # Sort by date
        payments.sort(key=lambda x: datetime.fromisoformat(x['created_at']))
        
        consecutive = 0
        last_expiry = None
        
        for payment in payments:
            payment_date = datetime.fromisoformat(payment['created_at'])
            
            if last_expiry is None:
                # First payment
                consecutive += 1
                # Calculate expiry
                days = payment.get('days', 30)
                last_expiry = payment_date + timedelta(days=days)
            else:
                # Check gap
                gap = (payment_date - last_expiry).days
                
                if gap <= self.config.CONSECUTIVE_GAP_THRESHOLD:
                    # Still consecutive
                    consecutive += 1
                    days = payment.get('days', 30)
                    last_expiry = payment_date + timedelta(days=days)
                else:
                    # Gap too large - reset
                    consecutive = 1
                    days = payment.get('days', 30)
                    last_expiry = payment_date + timedelta(days=days)
        
        return consecutive
    
    async def check_and_update_tier(self, user_id: int) -> Tuple[str, str, bool]:
        """
        Check if user's tier should be updated
        
        Returns:
            (old_tier, new_tier, changed)
        """
        # Calculate current tier based on payments
        consecutive_months = await self.calculate_consecutive_months(user_id)
        new_tier = await self.calculate_tier_from_months(consecutive_months)
        
        # Get stored tier
        loyalty_data = await self.db.get_user_loyalty(user_id)
        old_tier = loyalty_data.get('current_tier', 'rookie') if loyalty_data else 'rookie'
        
        changed = (new_tier != old_tier)
        
        return old_tier, new_tier, changed
    
    async def award_tier_bonus(self, user_id: int, tier: str) -> Optional[Dict]:
        """
        Award bonus for reaching a tier
        
        Bonuses include:
        - Free subscription days
        - Power Up course (Elite tier)
        
        Returns:
            Dict with bonus details or None if already awarded
        """
        # Check if already awarded
        already_awarded = await self.db.check_tier_bonus_awarded(user_id, tier)
        
        if already_awarded:
            logger.info(f"Tier bonus already awarded: user={user_id} tier={tier}")
            return None
        
        tier_data = self.config.LOYALTY_TIERS[tier]
        bonus_days = tier_data.get('bonus_days', 0)
        free_course = tier_data.get('free_course')
        
        result = {
            'tier': tier,
            'bonus_days': bonus_days,
            'free_course': free_course
        }
        
        # Add bonus days to subscription
        if bonus_days > 0:
            await self.db.add_bonus_days(user_id, bonus_days, f"Tier {tier} achievement")
        
        # Grant Power Up course (Elite tier)
        if free_course:
            course_granted = await self.grant_course_once(user_id, free_course, tier)
            result['course_granted'] = course_granted
        
        # Mark as awarded
        await self.db.mark_tier_bonus_awarded(user_id, tier)
        
        # Log achievement
        await self.db.log_loyalty_achievement(
            user_id=user_id,
            from_tier='rookie',  # Could track this better
            to_tier=tier,
            bonus_days=bonus_days,
            free_course=free_course
        )
        
        logger.info(f"Awarded tier bonus: user={user_id} tier={tier} bonus={bonus_days}d")
        
        return result
    
    async def grant_course_once(self, user_id: int, course_key: str, granted_by_tier: str) -> bool:
        """
        Grant a course to user (once only)
        
        Args:
            user_id: Telegram user ID
            course_key: Course identifier (e.g. 'power_up')
            granted_by_tier: Which tier granted it
            
        Returns:
            True if granted, False if already has it
        """
        # Check if already granted
        already_has = await self.db.check_course_granted(user_id, course_key)
        
        if already_has:
            logger.info(f"Course already granted: user={user_id} course={course_key}")
            return False
        
        # Grant course
        await self.db.grant_course(user_id, course_key, granted_by_tier)
        
        logger.info(f"Granted course: user={user_id} course={course_key} by={granted_by_tier}")
        
        return True
    
    async def generate_loyalty_coupon(self, user_id: int, tier: str) -> Optional[str]:
        """
        Generate personal loyalty discount code for tier
        
        Format: LOYAL_{TIER}_{USER_ID}
        
        Args:
            user_id: Telegram user ID  
            tier: Tier name
            
        Returns:
            Coupon code or None
        """
        tier_data = self.config.LOYALTY_TIERS[tier]
        discount = tier_data.get('chat_discount', 0)
        
        if discount == 0:
            return None  # Rookie has no discount
        
        code = f"LOYAL_{tier.upper()}_{user_id}"
        
        # Create/update coupon
        await self.db.upsert_personal_coupon(
            code=code,
            user_id=user_id,
            coupon_type='loyalty_tier',
            discount_percent=discount,
            applies_to='all',
            expires_at=None,  # Tier-based (no fixed expiry)
            tied_to_tier=tier,
            max_uses=None,  # Unlimited
            reason=f'Loyalty tier: {tier}'
        )
        
        logger.info(f"Generated loyalty coupon: {code} discount={discount}%")
        
        return code
    
    async def deactivate_old_loyalty_coupon(self, user_id: int, old_tier: str):
        """Deactivate previous tier's loyalty coupon"""
        if old_tier in ['active', 'pro', 'elite', 'master', 'legend']:
            old_code = f"LOYAL_{old_tier.upper()}_{user_id}"
            await self.db.deactivate_coupon(old_code)
            logger.info(f"Deactivated old loyalty coupon: {old_code}")
    
    async def generate_reminder_coupon(self, user_id: int, tier: str) -> Optional[str]:
        """
        Generate reminder bonus coupon (smart based on tier)
        
        Only generates coupon if tier discount <5%
        (Rookie, Active get coupon; Pro+ get only bonus days)
        
        Returns:
            Coupon code or None
        """
        tier_data = self.config.LOYALTY_TIERS[tier]
        tier_discount = tier_data.get('chat_discount', 0)
        
        # Smart logic: only if tier discount <5%
        if tier_discount >= 5:
            logger.info(f"No reminder coupon for {tier} (already has {tier_discount}%)")
            return None
        
        # Generate code
        random_suffix = secrets.token_hex(4).upper()
        code = f"REMIND7D_{user_id}_{random_suffix}"
        
        expires_at = datetime.utcnow() + timedelta(hours=self.config.REMINDER_COUPON_HOURS)
        
        await self.db.upsert_personal_coupon(
            code=code,
            user_id=user_id,
            coupon_type='reminder_bonus',
            discount_percent=self.config.REMINDER_COUPON_DISCOUNT,
            applies_to='courses',
            expires_at=expires_at.isoformat(),
            tied_to_tier=None,
            max_uses=1,
            reason='7-day reminder bonus'
        )
        
        logger.info(f"Generated reminder coupon: {code} (5% courses, 24h)")
        
        return code
    
    async def should_reset_loyalty(self, user_id: int) -> bool:
        """
        Check if user's loyalty should be reset
        
        Reset conditions:
        - No active subscription
        - Last payment >30 days + 6h grace ago
        
        Returns:
            True if should reset
        """
        user = await self.db.get_user(user_id)
        
        if not user:
            return False
        
        # Check if has active subscription
        expires_at = user.get('expires_at')
        if expires_at:
            expiry = datetime.fromisoformat(expires_at)
            if expiry > datetime.utcnow():
                # Still active
                return False
        
        # Check last payment date
        loyalty_data = await self.db.get_user_loyalty(user_id)
        if not loyalty_data:
            return False
        
        last_payment_date = loyalty_data.get('last_payment_date')
        if not last_payment_date:
            return False
        
        last_payment = datetime.fromisoformat(last_payment_date)
        
        threshold = datetime.utcnow() - timedelta(
            days=self.config.LOYALTY_RESET_DAYS,
            hours=self.config.LOYALTY_RESET_GRACE_HOURS
        )
        
        should_reset = last_payment < threshold
        
        if should_reset:
            logger.warning(f"Loyalty reset triggered: user={user_id} last_payment={last_payment_date}")
        
        return should_reset
    
    async def reset_loyalty_tier(self, user_id: int):
        """
        Reset user's loyalty tier to Rookie
        
        - Sets tier to 'rookie'
        - Resets consecutive months
        - Deactivates loyalty coupon
        - Logs event
        """
        # Get current tier for logging
        loyalty_data = await self.db.get_user_loyalty(user_id)
        old_tier = loyalty_data.get('current_tier', 'rookie') if loyalty_data else 'rookie'
        
        # Deactivate loyalty coupon
        await self.deactivate_old_loyalty_coupon(user_id, old_tier)
        
        # Reset in database
        await self.db.reset_user_loyalty(user_id)
        
        logger.warning(f"Reset loyalty: user={user_id} {old_tier} → rookie")
        
        return old_tier
    
    async def can_use_winback(self, user_id: int) -> bool:
        """
        Check if user can use win-back offer
        
        Limit: 2x per rolling 365 days
        
        Returns:
            True if allowed
        """
        threshold = datetime.utcnow() - timedelta(days=365)
        
        usage_count = await self.db.count_winback_usage(user_id, since=threshold.isoformat())
        
        allowed = usage_count < self.config.WINBACK_MAX_PER_YEAR
        
        if not allowed:
            logger.info(f"Win-back limit reached: user={user_id} count={usage_count}")
        
        return allowed
    
    async def generate_winback_coupon(self, user_id: int, survey_response: bool = False) -> str:
        """
        Generate win-back coupon
        
        Args:
            user_id: Telegram user ID
            survey_response: True if from survey (20%), False if basic (10%)
            
        Returns:
            Coupon code
        """
        random_suffix = secrets.token_hex(4).upper()
        
        if survey_response:
            code = f"SURVEY_{user_id}_{random_suffix}"
            discount = self.config.SURVEY_REWARD_DISCOUNT
            hours = self.config.SURVEY_REWARD_HOURS
            reason = 'Survey response reward'
        else:
            code = f"WB_{user_id}_{random_suffix}"
            discount = self.config.WINBACK_YEARLY_DISCOUNT
            hours = 72
            reason = 'Win-back offer'
        
        expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        await self.db.upsert_personal_coupon(
            code=code,
            user_id=user_id,
            coupon_type='winback' if not survey_response else 'survey',
            discount_percent=discount,
            applies_to='all',
            expires_at=expires_at.isoformat(),
            tied_to_tier=None,
            max_uses=1,
            reason=reason
        )
        
        logger.info(f"Generated win-back coupon: {code} ({discount}%, {hours}h)")
        
        return code


# Helper function for calculating final price with discount
def calculate_final_price(base_price: float, tier_discount: int, coupon_discount: int = 0) -> Dict:
    """
    Calculate final price with tier and/or coupon discount
    
    Rule: MAX(tier_discount, coupon_discount) - NO STACKING
    
    Args:
        base_price: Original price
        tier_discount: Tier discount percentage
        coupon_discount: Coupon discount percentage
        
    Returns:
        Dict with price, discount, and warning if applicable
    """
    # Apply maximum discount (no stacking)
    final_discount = max(tier_discount, coupon_discount)
    
    final_price = base_price * (1 - final_discount / 100)
    
    result = {
        'original_price': base_price,
        'final_price': round(final_price, 2),
        'discount_percent': final_discount,
        'discount_amount': round(base_price - final_price, 2)
    }
    
    # Warning if coupon is worse than tier
    if coupon_discount > 0 and coupon_discount <= tier_discount:
        result['warning'] = f"Your tier discount ({tier_discount}%) is better than coupon ({coupon_discount}%)"
    
    return result
