from datetime import datetime, date
from services.db_service import db_service

class UsageService:
    def __init__(self):
        # Define limits
        self.LIMITS = {
            "free": {
                "study_decks": 5,
                "planner_commands": 3,
                "daily_chats": 5
            },
            "premium": {
                "study_decks": 20,
                "planner_commands": 20,
                "daily_chats": 50
            }
        }

    def _ensure_usage_record(self, user_id):
        record = db_service.query("SELECT * FROM user_usage WHERE user_id = ?", (user_id,), one=True)
        if not record:
            db_service.execute("INSERT INTO user_usage (user_id) VALUES (?)", (user_id,))
            record = db_service.query("SELECT * FROM user_usage WHERE user_id = ?", (user_id,), one=True)
        
        # Reset daily chats if it's a new day
        today_str = date.today().isoformat()
        if record["last_chat_date"] != today_str:
            db_service.execute(
                "UPDATE user_usage SET daily_chats = 0, last_chat_date = ? WHERE user_id = ?",
                (today_str, user_id)
            )
            # Re-fetch or manually update dict to avoid sqlite3.Row immutability issues
            record = db_service.query("SELECT * FROM user_usage WHERE user_id = ?", (user_id,), one=True)
            
        return record

    def get_tier(self, user_id):
        # Get tier from profiles table (source of truth), not just user_usage
        profile = db_service.query("SELECT is_premium, premium_expires_at FROM profiles WHERE id = ?", (user_id,), one=True)
        
        if profile and profile["is_premium"]:
            # Check if premium hasn't expired
            if profile["premium_expires_at"]:
                expires_at = datetime.fromisoformat(profile["premium_expires_at"])
                if datetime.utcnow() > expires_at:
                    # Premium has expired, downgrade
                    db_service.execute("UPDATE profiles SET is_premium = 0 WHERE id = ?", (user_id,))
                    db_service.execute("UPDATE user_usage SET subscription_tier = 'free' WHERE user_id = ?", (user_id,))
                    return "free"
            return "premium"
        return "free"

    def check_and_sync_premium_status(self, user_id):
        # Sync user_usage.subscription_tier with profiles.is_premium
        tier = self.get_tier(user_id)
        db_service.execute("UPDATE user_usage SET subscription_tier = ? WHERE user_id = ?", (tier, user_id))
        return tier

    def can_generate_deck(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return True
        record = self._ensure_usage_record(user_id)
        tier = self.get_tier(user_id)
        self.check_and_sync_premium_status(user_id)
        return record["study_decks_generated"] < self.LIMITS[tier]["study_decks"]

    def increment_deck(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return
        db_service.execute("UPDATE user_usage SET study_decks_generated = study_decks_generated + 1 WHERE user_id = ?", (user_id,))

    def can_use_planner(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return True
        record = self._ensure_usage_record(user_id)
        tier = self.get_tier(user_id)
        self.check_and_sync_premium_status(user_id)
        return record["planner_commands_used"] < self.LIMITS[tier]["planner_commands"]

    def increment_planner(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return
        db_service.execute("UPDATE user_usage SET planner_commands_used = planner_commands_used + 1 WHERE user_id = ?", (user_id,))

    def can_chat(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return True
        record = self._ensure_usage_record(user_id)
        tier = self.get_tier(user_id)
        self.check_and_sync_premium_status(user_id)
        return record["daily_chats"] < self.LIMITS[tier]["daily_chats"]

    def increment_chat(self, user_id):
        profile = db_service.query("SELECT email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile and profile["email"] == "vilasagarammahesh90@gmail.com":
            return
        self._ensure_usage_record(user_id) # ensure date is current
        db_service.execute("UPDATE user_usage SET daily_chats = daily_chats + 1 WHERE user_id = ?", (user_id,))

usage_service = UsageService()

