import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        # [C5] Credentials moved from hardcoded values to environment variables
        self.sender_email = os.getenv("SMTP_EMAIL", "")
        self.sender_password = os.getenv("SMTP_PASSWORD", "")

        if not self.sender_email or not self.sender_password:
            print("⚠️  WARNING: SMTP_EMAIL or SMTP_PASSWORD not set. Email sending will fail.")

    def _send_email(self, to_email, subject, html_content):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"NoteEd <{self.sender_email}>"
        msg["To"] = to_email

        part = MIMEText(html_content, "html")
        msg.attach(part)

        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, to_email, msg.as_string())
            server.quit()
            return True
        except Exception as e:
            print(f"Error sending email via SMTP: {e}")
            return False

    def send_password_reset_otp(self, to_email, otp_code):
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">NoteEd</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 20px;">Password Reset Request</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.5;">
                We received a request to reset the password for your NoteEd account. 
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
                &copy; 2026 NoteEd. All rights reserved.
            </p>
        </div>
        """

        subject = f"{otp_code} is your password reset code"
        success = self._send_email(to_email, subject, html_content)
        if success:
            print(f"Password reset OTP sent to {to_email}")
        else:
            print(f"DEV MODE: OTP for {to_email} is {otp_code}")
        return success


    def send_signup_verification_otp(self, to_email, otp_code):
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">NoteEd</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 20px;">Verify your Email</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.5;">
                Welcome to NoteEd! Please use the following 6-digit code to verify your email address and complete your registration:
            </p>
            <div style="background-color: #f4f4f5; padding: 16px; border-radius: 8px; text-align: center; margin: 24px 0;">
                <span style="font-family: monospace; font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #0071e3;">{otp_code}</span>
            </div>
            <p style="color: #555; font-size: 14px;">
                This code will expire in <strong>15 minutes</strong>. If you did not create this account, you can safely ignore this email.
            </p>
            <hr style="border: none; border-top: 1px solid #eaeaea; margin: 30px 0;" />
            <p style="color: #888; font-size: 12px; text-align: center;">
                &copy; 2026 NoteEd. All rights reserved.
            </p>
        </div>
        """

        subject = f"{otp_code} is your NoteEd verification code"
        success = self._send_email(to_email, subject, html_content)
        if success:
            print(f"Signup verification OTP sent to {to_email}")
        else:
            print(f"DEV MODE: OTP for {to_email} is {otp_code}")
        return success

    def send_support_reply(self, to_email, user_name, reply_message):
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">NoteEd Support</h1>
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
                &copy; 2026 NoteEd. All rights reserved.
            </p>
        </div>
        """

        subject = "Response to your Support Request"
        success = self._send_email(to_email, subject, html_content)
        if success:
            print(f"Support reply sent to {to_email}")
        return success

    def send_premium_reminder(self, to_email, user_name):
        # HTML Template for the email
        html_content = f"""
        <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h1 style="color: #1d1d1f; margin: 0;">NoteEd Premium</h1>
            </div>
            <h2 style="color: #1d1d1f; font-size: 18px;">Hi {user_name},</h2>
            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Your NoteEd Premium subscription expires in exactly <strong>3 days</strong>.
            </p>
            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Renew now to keep your advanced AI limits, priority access, and faster generation speeds! 
                If your account expires, you will automatically be downgraded to the free Basic tier.
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://noted.vercel.app/upgrade" style="background-color: #1d1d1f; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px;">Renew Premium Now</a>
            </div>
            <p style="color: #888; font-size: 14px; text-align: center;">
                If you have any questions, feel free to contact our support team.
            </p>
        </div>
        """

        subject = "Action Required: Your Premium Expires in 3 Days!"
        success = self._send_email(to_email, subject, html_content)
        if success:
            print(f"Premium reminder sent to {to_email}")
        return success

email_service = EmailService()

