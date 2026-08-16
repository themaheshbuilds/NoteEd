import uuid
import random
import os
import requests
from datetime import datetime
from flask import Blueprint, request, session, redirect, url_for, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash
from services.db_service import db_service
from services.email_service import EmailService
from services.security import (
    check_auth_rate_limit, check_otp_rate_limit,
    check_password_reset_rate_limit, sanitize_string,
    validate_email, validate_password_strength,
    generate_oauth_state, verify_oauth_state
)

auth_bp = Blueprint("auth", __name__)

# Instantiate email service once
email_service = EmailService()

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # [M2] Rate limiting on signup
        is_limited, remaining = check_auth_rate_limit()
        if is_limited:
            flash("Too many signup attempts. Please try again later.", "error")
            return redirect(url_for("auth.signup"))

        email = sanitize_string(request.form.get("email"), max_length=254)
        password = request.form.get("password")
        first_name = sanitize_string(request.form.get("first_name"), max_length=50)
        last_name = sanitize_string(request.form.get("last_name"), max_length=50)
        full_name_raw = sanitize_string(request.form.get("full_name"), max_length=100)
        
        full_name = f"{first_name or ''} {last_name or ''}".strip() or full_name_raw
        
        if not email or not password or not full_name:
            flash("All fields are required.", "error")
            return redirect(url_for("auth.signup"))

        # [L4] Validate email format
        if not validate_email(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("auth.signup"))

        # Validate password strength
        pw_valid, pw_error = validate_password_strength(password)
        if not pw_valid:
            flash(pw_error, "error")
            return redirect(url_for("auth.signup"))
            
        # Check if user exists
        existing = db_service.query("SELECT * FROM profiles WHERE email = ?", (email,), one=True)
        if existing:
            flash("Email already registered.", "error")
            return redirect(url_for("auth.signup"))
            
        # Generate OTP
        otp_code = f"{random.randint(100000, 999999)}"
        
        # [H8] Hash password before storing in session — never store plaintext
        session["temp_signup"] = {
            "email": email,
            "password_hash": generate_password_hash(password),
            "full_name": full_name,
            "otp": otp_code,
            "otp_attempts": 0,
            "expires_at": datetime.now().timestamp() + 900  # 15 minutes
        }
        
        # Send Email
        success = False
        try:
            success = email_service.send_signup_verification_otp(email, otp_code)
        except Exception as e:
            print(f"Exception sending signup OTP email: {e}")
        
        if success:
            flash("A verification code has been sent to your email.", "success")
        else:
            # [L1] Log OTP to server console only — never expose to user in production
            print(f"[DEV] Signup OTP for {email}: {otp_code}")
            if not os.environ.get("VERCEL"):
                flash("Email service unavailable. Check server console for OTP.", "warning")
            else:
                flash("Failed to send verification email. Please try again.", "error")
            
        return redirect(url_for("auth.verify_signup"))
        
    return render_template("auth/signup.html")

@auth_bp.route("/signup/verify", methods=["GET", "POST"])
def verify_signup():
    temp_user = session.get("temp_signup")
    if not temp_user:
        flash("Verification session expired. Please sign up again.", "error")
        return redirect(url_for("auth.signup"))
        
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "resend":
            # Generate new OTP
            otp_code = f"{random.randint(100000, 999999)}"
            temp_user["otp"] = otp_code
            temp_user["otp_attempts"] = 0  # Reset attempts on resend
            temp_user["expires_at"] = datetime.now().timestamp() + 900
            session["temp_signup"] = temp_user

            success = False
            try:
                success = email_service.send_signup_verification_otp(temp_user["email"], otp_code)
            except Exception as e:
                print(f"Exception resending OTP email: {e}")

            if success:
                flash("A new verification code has been sent.", "success")
            else:
                print(f"[DEV] Resend OTP for {temp_user['email']}: {otp_code}")
                if not os.environ.get("VERCEL"):
                    flash("Email service unavailable. Check server console for OTP.", "warning")
                else:
                    flash("Failed to send verification email. Please try again.", "error")
            return redirect(url_for("auth.verify_signup"))
            
        # [M5] Check OTP attempt counter — max 5 attempts
        otp_attempts = temp_user.get("otp_attempts", 0)
        if otp_attempts >= 5:
            session.pop("temp_signup", None)
            flash("Too many failed attempts. Please sign up again.", "error")
            return redirect(url_for("auth.signup"))

        # Validate OTP
        entered_otp = request.form.get("otp_code")
        
        if datetime.now().timestamp() > temp_user.get("expires_at", 0):
            flash("OTP expired. Please request a new one.", "error")
            return redirect(url_for("auth.verify_signup"))
            
        if entered_otp != temp_user.get("otp"):
            temp_user["otp_attempts"] = otp_attempts + 1
            session["temp_signup"] = temp_user
            remaining = 5 - temp_user["otp_attempts"]
            flash(f"Invalid verification code. {remaining} attempt(s) remaining.", "error")
            return redirect(url_for("auth.verify_signup"))
            
        # Success! Insert into DB
        user_id = str(uuid.uuid4())
        # [H8] Use pre-hashed password from session (never stored plaintext)
        hashed_pw = temp_user["password_hash"]
        
        db_service.execute(
            "INSERT INTO profiles (id, email, full_name, study_streak, password_hash, last_active) VALUES (?, ?, ?, 0, ?, ?)",
            (user_id, temp_user["email"], temp_user["full_name"], hashed_pw, datetime.now().isoformat())
        )
        
        # Generate custom API key
        try:
            admin_url = os.getenv("CUSTOM_AI_ADMIN_URL")
            admin_token = os.getenv("CUSTOM_AI_MASTER_TOKEN")
            if admin_url and admin_token:
                resp = requests.post(
                    admin_url,
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"user_id": user_id, "tier": "free"},
                    timeout=5
                )
                if resp.status_code == 200:
                    new_key = resp.json().get("api_key")
                    if new_key:
                        db_service.execute("UPDATE profiles SET api_keys = ? WHERE id = ?", (new_key, user_id))
        except Exception as e:
            print(f"Failed to generate custom API key: {e}")
            
        # Log them in
        session.pop("temp_signup", None)
        session["user_id"] = user_id
        session["email"] = temp_user["email"]
        session["full_name"] = temp_user["full_name"]
        
        flash("Email verified! Welcome to NoteEd!", "success")
        return redirect(url_for("dashboard.index"))
        
    return render_template("auth/verify_signup.html", email=temp_user["email"])

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # [M2] Rate limiting on login
        is_limited, remaining = check_auth_rate_limit()
        if is_limited:
            flash("Too many login attempts. Please try again in 15 minutes.", "error")
            return redirect(url_for("auth.login"))

        email = sanitize_string(request.form.get("email"), max_length=254)
        password = request.form.get("password")
        
        if not email or not password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("auth.login"))
            
        user = db_service.query("SELECT * FROM profiles WHERE email = ?", (email,), one=True)
        
        # Verify user and password
        if user and "password_hash" in dict(user).keys() and dict(user)["password_hash"] and check_password_hash(dict(user)["password_hash"], password):
            session.permanent = True
            session["user_id"] = dict(user)["id"]
            session["email"] = dict(user)["email"]
            session["full_name"] = dict(user)["full_name"]
            
            # Downgrade if premium expired
            user_dict = dict(user)
            if user_dict.get("is_premium") and user_dict.get("premium_expires_at"):
                try:
                    expires_at = datetime.fromisoformat(user_dict["premium_expires_at"])
                    if expires_at < datetime.utcnow():
                        db_service.execute("UPDATE profiles SET is_premium = 0, premium_expires_at = NULL WHERE id = ?", (user_dict["id"],))
                        db_service.execute("UPDATE user_usage SET subscription_tier = 'free' WHERE user_id = ?", (user_dict["id"],))
                except Exception:
                    pass
            
            # Update last active
            db_service.execute(
                "UPDATE profiles SET last_active = ? WHERE id = ?",
                (datetime.now().isoformat(), user_dict["id"])
            )
            
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard.index"))
        else:
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))
            
    return render_template("auth/login.html")

@auth_bp.route("/google/login")
def google_login():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        flash("Google Sign-In is not configured yet. (Missing GOOGLE_CLIENT_ID)", "error")
        return redirect(url_for("auth.login"))
        
    redirect_uri = url_for("auth.google_callback", _external=True)
    scope = "openid email profile"
    
    # [L3] Generate state parameter for OAuth CSRF protection
    state = generate_oauth_state()
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        "response_type=code&"
        f"scope={scope}&"
        f"state={state}&"
        "access_type=online"
    )
    return redirect(auth_url)

@auth_bp.route("/google/callback")
def google_callback():
    # [L3] Verify OAuth state parameter
    received_state = request.args.get("state")
    if not verify_oauth_state(received_state):
        flash("Authentication request expired or was tampered with. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("Google authentication failed or was cancelled.", "error")
        return redirect(url_for("auth.login"))
        
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = url_for("auth.google_callback", _external=True)
    
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    try:
        token_res = requests.post(token_url, data=token_data)
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        userinfo_res = requests.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        userinfo_res.raise_for_status()
        user_info = userinfo_res.json()
        
        email = user_info.get("email")
        google_id = user_info.get("id")
        full_name = user_info.get("name", "Google User")
        
        if not email:
            flash("Could not retrieve email from Google.", "error")
            return redirect(url_for("auth.login"))
            
        # Check if user exists by google_id or email
        user = db_service.query("SELECT * FROM profiles WHERE google_id = ? OR email = ?", (google_id, email), one=True)
        
        if not user:
            # Create new user
            user_id = str(uuid.uuid4())
            db_service.execute(
                "INSERT INTO profiles (id, email, full_name, google_id, study_streak, last_active) VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, email, full_name, google_id, datetime.now().isoformat())
            )
            
            # Generate custom API key
            try:
                admin_url = os.getenv("CUSTOM_AI_ADMIN_URL")
                admin_token = os.getenv("CUSTOM_AI_MASTER_TOKEN")
                if admin_url and admin_token:
                    resp = requests.post(
                        admin_url,
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"user_id": user_id, "tier": "free"},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        new_key = resp.json().get("api_key")
                        if new_key:
                            db_service.execute("UPDATE profiles SET api_keys = ? WHERE id = ?", (new_key, user_id))
            except Exception as e:
                print(f"Failed to generate custom API key via Google Auth: {e}")
                
        else:
            user_id = user["id"]
            # If they exist but don't have google_id linked yet, link it
            if not user["google_id"]:
                db_service.execute("UPDATE profiles SET google_id = ? WHERE id = ?", (google_id, user_id))
            # Update last active
            db_service.execute("UPDATE profiles SET last_active = ? WHERE id = ?", (datetime.now().isoformat(), user_id))
            
        session.permanent = True
        session["user_id"] = user_id
        session["email"] = email
        session["full_name"] = full_name
        
        # Downgrade if premium expired
        if user:
            user_dict = dict(user)
            if user_dict.get("is_premium") and user_dict.get("premium_expires_at"):
                try:
                    expires_at = datetime.fromisoformat(user_dict["premium_expires_at"])
                    if expires_at < datetime.utcnow():
                        db_service.execute("UPDATE profiles SET is_premium = 0, premium_expires_at = NULL WHERE id = ?", (user_dict["id"],))
                        db_service.execute("UPDATE user_usage SET subscription_tier = 'free' WHERE user_id = ?", (user_dict["id"],))
                except Exception:
                    pass
        
        flash("Logged in successfully with Google.", "success")
        return redirect(url_for("dashboard.index"))
        
    except requests.exceptions.RequestException as e:
        print(f"Google Auth Error: {e}")
        flash("An error occurred during Google authentication.", "error")
        return redirect(url_for("auth.login"))

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("auth.login"))

import secrets
from datetime import timedelta
from services.email_service import email_service

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        # [M2] Rate limiting on password reset
        is_limited, _ = check_password_reset_rate_limit()
        if is_limited:
            flash('Too many reset attempts. Please try again in 1 hour.', 'error')
            return redirect(url_for('auth.forgot_password'))

        email = sanitize_string(request.form.get('email'), max_length=254)
        if not email:
            flash('Email is required.', 'error')
            return redirect(url_for('auth.forgot_password'))
        user = db_service.query('SELECT id FROM profiles WHERE email = ?', (email,), one=True)
        if user:
            # [M6] Clean up old/expired OTPs for this email before creating a new one
            db_service.execute('DELETE FROM password_reset_otps WHERE email = ?', (email,))

            otp_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            otp_hash = generate_password_hash(otp_code)
            expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
            db_service.execute(
                'INSERT INTO password_reset_otps (id, email, otp_hash, expires_at) VALUES (?, ?, ?, ?)',
                (str(uuid.uuid4()), email, otp_hash, expires_at)
            )
            success = email_service.send_password_reset_otp(email, otp_code)
            if not success:
                flash('Failed to send password reset email. Please try again.', 'error')
                return redirect(url_for('auth.forgot_password'))
        session['reset_email'] = email
        flash('If an account exists with that email, a 6-digit OTP has been sent.', 'success')
        return redirect(url_for('auth.verify_otp'))
    return render_template('auth/forgot_password.html')

@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        # [M5] Rate limit OTP verification attempts
        is_limited, remaining = check_otp_rate_limit(email)
        if is_limited:
            flash('Too many OTP attempts. Please request a new code.', 'error')
            return redirect(url_for('auth.forgot_password'))

        otp_code = request.form.get('otp')
        record = db_service.query(
            'SELECT * FROM password_reset_otps WHERE email = ? ORDER BY created_at DESC LIMIT 1',
            (email,), one=True
        )
        if record and check_password_hash(record['otp_hash'], otp_code):
            expires_at = record['expires_at']
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
                
            if expires_at > datetime.now():
                session['otp_verified'] = True
                return redirect(url_for('auth.reset_password'))
            else:
                flash('OTP has expired. Please request a new one.', 'error')
        else:
            flash('Invalid OTP.', 'error')
    return render_template('auth/verify_otp.html', email=email)

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = session.get('reset_email')
    if not email or not session.get('otp_verified'):
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password')
        password_hash = generate_password_hash(password)
        db_service.execute('UPDATE profiles SET password_hash = ? WHERE email = ?', (password_hash, email))
        db_service.execute('DELETE FROM password_reset_otps WHERE email = ?', (email,))
        session.pop('reset_email', None)
        session.pop('otp_verified', None)
        flash('Password has been successfully reset. You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html')

