import os
import requests
import datetime
from services.db_service import db_service

class BillingService:
    def __init__(self):
        self.api_key = os.getenv("INSTAMOJO_API_KEY")
        self.auth_token = os.getenv("INSTAMOJO_AUTH_TOKEN")
        env = os.getenv("INSTAMOJO_ENV", "test").lower()
        if env == "production":
            self.base_url = "https://www.instamojo.com/api/1.1"
        else:
            self.base_url = "https://test.instamojo.com/api/1.1"

    def create_checkout_session(self, user_id, email, phone, success_url, cancel_url):
        """Creates a payment request with Instamojo API and returns the checkout URL."""
        if not self.api_key or not self.auth_token:
            return None
            
        try:
            headers = {
                "X-Api-Key": self.api_key,
                "X-Auth-Token": self.auth_token
            }
            
            payload = {
                "purpose": "NoteEd Premium (Monthly)",
                "amount": "49", # ₹49
                "buyer_name": user_id,
                "email": email,
                "phone": phone,
                "redirect_url": success_url,
                "send_email": True,
                "allow_repeated_payments": False
            }
            
            response = requests.post(f"{self.base_url}/payment-requests/", data=payload, headers=headers)
            response_data = response.json()
            
            if response_data.get("success"):
                # Return the longurl for the user to visit and pay
                return response_data["payment_request"]["longurl"]
            else:
                print(f"Instamojo Error: {response_data}")
                return None
        except Exception as e:
            print(f"Error creating Instamojo payment request: {e}")
            return None

    def verify_payment(self, payment_request_id, payment_id):
        """Verifies the payment with Instamojo API and upgrades the user if successful."""
        try:
            headers = {
                "X-Api-Key": self.api_key,
                "X-Auth-Token": self.auth_token
            }
            # Verify the payment details
            response = requests.get(f"{self.base_url}/payment-requests/{payment_request_id}/{payment_id}/", headers=headers)
            data = response.json()
            
            if data.get("success") and data.get("payment_request", {}).get("payment", {}).get("status") == "Credit":
                return True
            return False
        except Exception as e:
            print(f"Error verifying Instamojo payment: {e}")
            return False

    def upgrade_user_to_premium(self, user_id, days=30):
        try:
            # Update the user's tier to premium in the database
            db_service.execute("UPDATE user_usage SET subscription_tier = 'premium' WHERE user_id = ?", (user_id,))
            
            # Set expiration to specified days from now (e.g., 30 days for monthly, 365 for yearly)
            expires_at = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()
            
            # CRITICAL FIX: Ensure the profile is also marked as premium and set the expiry date
            db_service.execute(
                "UPDATE profiles SET is_premium = 1, premium_expires_at = ? WHERE id = ?", 
                (expires_at, user_id)
            )
            print(f"Successfully upgraded user {user_id} to Premium! Expires: {expires_at}")
            return True
        except Exception as e:
            print(f"Error upgrading user to premium: {e}")
            return False

billing_service = BillingService()

