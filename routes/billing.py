
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, current_app, flash
import datetime
from services.billing_service import billing_service
from services.email_service import email_service
from services.db_service import db_service
from routes.dashboard import get_current_user

billing_bp = Blueprint("billing", __name__)

@billing_bp.route("/upgrade", methods=["GET"])
def upgrade_page():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    return render_template("dashboard/upgrade.html", user=user)

@billing_bp.route("/checkout", methods=["POST"])
def checkout():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    phone = request.form.get("phone", "").strip()
    plan_type = request.form.get("plan_type", "monthly")
    days = 365 if plan_type == "yearly" else 30
    plan_title = "Annual Premium (1 Year)" if plan_type == "yearly" else "Monthly Premium (30 Days)"

    # Test Mode Simulation or direct test upgrade
    if not billing_service.api_key or billing_service.api_key == "test_placeholder_api_key":
        # Simulate payment success instantly
        billing_service.upgrade_user_to_premium(user["id"], days=days)
        flash(f"Payment Simulator: Successfully upgraded to {plan_title}!", "success")
        return redirect(url_for("billing.success"))
        
    if not phone or len(phone) < 10:
        flash("Please enter a valid 10-digit mobile number.", "error")
        return redirect(url_for("billing.upgrade_page"))
        
    success_url = request.host_url.rstrip("/") + url_for("billing.success")
    cancel_url = request.host_url.rstrip("/") + url_for("billing.upgrade_page")
    
    checkout_url = billing_service.create_checkout_session(user["id"], user["email"], phone, success_url, cancel_url)
    
    if checkout_url:
        return redirect(checkout_url)
    else:
        flash("Unable to connect to Payment Gateway right now. Please try again or upload proof.", "error")
        return redirect(url_for("billing.upgrade_page"))

@billing_bp.route("/upgrade/success", methods=["GET"])
def success():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    # Instamojo redirects here with query params: payment_id, payment_status, payment_request_id
    payment_id = request.args.get("payment_id")
    payment_status = request.args.get("payment_status")
    payment_request_id = request.args.get("payment_request_id")
    
    # If returned from live Instamojo payment, verify it server-side before upgrading
    if payment_id and payment_request_id and payment_status == "Credit":
        is_valid = billing_service.verify_payment(payment_request_id, payment_id)
        if is_valid:
            billing_service.upgrade_user_to_premium(user["id"])
        else:
            flash("Payment verification failed. If money was deducted, please contact support.", "error")
            return redirect(url_for("billing.upgrade_page"))
            
    return render_template("dashboard/upgrade.html", user=user, success=True)

@billing_bp.route("/proof", methods=["POST"])
def upload_proof():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    if "proof_image" not in request.files:
        flash("No image uploaded.", "error")
        return redirect(url_for("billing.upgrade_page"))
        
    file = request.files["proof_image"]
    if file.filename == "":
        flash("No selected file.", "error")
        return redirect(url_for("billing.upgrade_page"))
        
    if file:
        import uuid
        import os
        from werkzeug.utils import secure_filename
        from services.security import validate_upload_file, ALLOWED_IMAGE_EXTENSIONS
        
        # [H6] Validate file type and size for payment proofs (images only)
        is_valid, error_msg = validate_upload_file(
            file,
            allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
            max_size_bytes=10 * 1024 * 1024  # 10MB for proof images
        )
        if not is_valid:
            flash(error_msg, "error")
            return redirect(url_for("billing.upgrade_page"))
        
        # Save file to upload directory (which is /tmp on Vercel)
        upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "proofs")
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
        new_filename = f"{uuid.uuid4()}.{ext}"
        filepath = os.path.join(upload_dir, new_filename)
        
        file.save(filepath)
        
        # Insert into DB
        from services.db_service import db_service
        proof_id = str(uuid.uuid4())
        
        # For Vercel/ephemeral we ideally use a storage bucket, but we'll store the filepath for now
        db_path = filepath
        
        db_service.execute(
            "INSERT INTO payment_proofs (id, user_id, file_path, status) VALUES (?, ?, ?, 'pending')",
            (proof_id, user["id"], db_path)
        )
        
        flash("Payment proof uploaded successfully! Our team will verify it shortly.", "success")
        return redirect(url_for("billing.upgrade_page"))

@billing_bp.route("/api/cron/check-subscriptions", methods=["GET", "POST"])
def check_subscriptions():
    # [H1] Verify CRON_SECRET for protected cron endpoints
    from services.security import verify_cron_secret
    if not verify_cron_secret():
        return jsonify({"error": "Unauthorized"}), 401
    
    now = datetime.datetime.utcnow()
    three_days_from_now = now + datetime.timedelta(days=3)
    
    # 1. Check for expired subscriptions and downgrade them
    expired_users = db_service.query(
        "SELECT id, email, full_name FROM profiles WHERE is_premium = 1 AND premium_expires_at <= ?",
        (now.isoformat(),)
    )
    
    for u in expired_users:
        db_service.execute("UPDATE profiles SET is_premium = 0, premium_expires_at = NULL, premium_reminder_sent = FALSE WHERE id = ?", (u["id"],))
        db_service.execute("UPDATE user_usage SET subscription_tier = 'free' WHERE user_id = ?", (u["id"],))
        print(f"Downgraded expired premium user {u['email']}")

    # 2. Check for subscriptions expiring in exactly 3 days that haven't received a reminder
    remind_users = db_service.query(
        "SELECT id, email, full_name FROM profiles WHERE is_premium = 1 AND premium_expires_at <= ? AND premium_expires_at > ? AND premium_reminder_sent = FALSE",
        (three_days_from_now.isoformat(), now.isoformat())
    )
    
    for u in remind_users:
        success = email_service.send_premium_reminder(u["email"], u["full_name"] or "User")
        if success:
            db_service.execute("UPDATE profiles SET premium_reminder_sent = TRUE WHERE id = ?", (u["id"],))
            print(f"Sent premium expiration reminder to {u['email']}")

    return jsonify({
        "status": "success",
        "expired_processed": len(expired_users),
        "reminders_sent": len(remind_users)
    }), 200



