import os
import requests

class EmailService:
    def __init__(self):
        self.api_key = os.environ.get("RESEND_API_KEY")
        self.sender_email = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev") # Default Resend sandbox email

    def send_password_reset_otp(self, to_email, otp_code):
        if not self.api_key:
            print("WARNING: RESEND_API_KEY is not set. Cannot send email.")
            return False

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">Helix AI</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 20px;">Password Reset Request</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.5;">
                We received a request to reset the password for your Helix AI account. 
                Use the following 6-digit code to securely reset your password:
            </p>
            <div style="background-color: #f4f4f5; padding: 16px; border-radius: 8px; text-align: center; margin: 24px 0;">
                <span style="font-family: monospace; font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #0071e3;">{otp_code}</span>
            </div>
            <p style="color: #555; font-size: 14px;">
                This code will expire in <strong>15 minutes</strong>. If you did not request this reset, you can safely ignore this email.
            </p>
            <hr style="border: none; border-top: 1px solid #eaeaea; margin: 30px 0;" />
            <p style="color: #888; font-size: 12px; text-align: center;">
                &copy; 2026 Helix AI. All rights reserved.
            </p>
        </div>
        """

        payload = {
            "from": f"Helix AI <{self.sender_email}>",
            "to": [to_email],
            "subject": f"{otp_code} is your password reset code",
            "html": html_content
        }

        try:
            response = requests.post("https://api.resend.com/emails", headers=headers, json=payload)
            response.raise_for_status()
            print(f"Password reset OTP sent to {to_email}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending email via Resend: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Resend API Response: {e.response.text}")
            print(f"DEV MODE: OTP for {to_email} is {otp_code}")
            return True


    def send_signup_verification_otp(self, to_email, otp_code):
        if not self.api_key:
            print("WARNING: RESEND_API_KEY is not set. Cannot send email.")
            return False

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">Helix AI</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 20px;">Verify your Email</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.5;">
                Welcome to Helix AI! Please use the following 6-digit code to verify your email address and complete your registration:
            </p>
            <div style="background-color: #f4f4f5; padding: 16px; border-radius: 8px; text-align: center; margin: 24px 0;">
                <span style="font-family: monospace; font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #0071e3;">{otp_code}</span>
            </div>
            <p style="color: #555; font-size: 14px;">
                This code will expire in <strong>15 minutes</strong>. If you did not create this account, you can safely ignore this email.
            </p>
            <hr style="border: none; border-top: 1px solid #eaeaea; margin: 30px 0;" />
            <p style="color: #888; font-size: 12px; text-align: center;">
                &copy; 2026 Helix AI. All rights reserved.
            </p>
        </div>
        """

        payload = {
            "from": f"Helix AI <{self.sender_email}>",
            "to": [to_email],
            "subject": f"{otp_code} is your Helix AI verification code",
            "html": html_content
        }

        try:
            response = requests.post("https://api.resend.com/emails", headers=headers, json=payload)
            response.raise_for_status()
            print(f"Signup verification OTP sent to {to_email}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending email via Resend: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Resend API Response: {e.response.text}")
            print(f"DEV MODE: OTP for {to_email} is {otp_code}")
            return True

    def send_support_reply(self, to_email, user_name, reply_message):
        if not self.api_key:
            print("WARNING: RESEND_API_KEY is not set. Cannot send email.")
            return False

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">Helix AI Support</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 18px;">Hi {user_name},</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Our team has reviewed your support request and here is the response:
            </p>
            <div style="background-color: #f4f4f5; padding: 16px; border-radius: 8px; margin: 24px 0; font-size: 15px; color: #333; line-height: 1.6; white-space: pre-wrap;">{reply_message}</div>
            <p style="color: #555; font-size: 14px;">
                If you have any further questions, feel free to reply to this email or open a new request on the platform.
            </p>
            <hr style="border: none; border-top: 1px solid #eaeaea; margin: 30px 0;" />
            <p style="color: #888; font-size: 12px; text-align: center;">
                &copy; 2026 Helix AI. All rights reserved.
            </p>
        </div>
        """

        payload = {
            "from": f"Helix AI Support <{self.sender_email}>",
            "to": [to_email],
            "subject": "Response to your Support Request",
            "html": html_content
        }

        try:
            response = requests.post("https://api.resend.com/emails", headers=headers, json=payload)
            response.raise_for_status()
            print(f"Support reply sent to {to_email}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending support reply via Resend: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Resend API Response: {e.response.text}")
            return False

    def send_premium_reminder(self, to_email, user_name):
        if not self.api_key:
            print("WARNING: RESEND_API_KEY is not set. Cannot send email.")
            return False

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">Helix AI Premium</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 18px;">Hi {user_name},</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Your KiraakStudy Premium subscription expires in exactly <strong>3 days</strong>.
            </p>
            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Renew now to keep your advanced AI limits, priority access, and faster generation speeds! 
                If your account expires, you will automatically be downgraded to the free Basic tier.
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://kiraakstudy.com/upgrade" style="background-color: #1d1d1f; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px;">Renew Premium Now</a>
            </div>
            <p style="color: #888; font-size: 14px; text-align: center;">
                If you have any questions, feel free to contact our support team.
            </p>
        </div>
        """

        payload = {
            "from": f"Helix AI Support <{self.sender_email}>",
            "to": [to_email],
            "subject": "Action Required: Your Premium Expires in 3 Days!",
            "html": html_content
        }

        try:
            response = requests.post("https://api.resend.com/emails", headers=headers, json=payload)
            response.raise_for_status()
            print(f"Premium reminder sent to {to_email}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending premium reminder via Resend: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Resend API Response: {e.response.text}")
            return False

email_service = EmailService()
