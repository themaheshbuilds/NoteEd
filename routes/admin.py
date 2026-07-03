from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from services.db_service import db_service
import os
import json
import fitz  # PyMuPDF
from services.syllabus_service import syllabus_service
from services.ai_service import ai_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if username == "Mahesh" and password == "Mahesh@1111":
            session["is_superadmin"] = True
            flash("Admin logged in successfully", "success")
            return redirect(url_for("admin.dashboard"))
        else:
            flash("Invalid credentials", "error")
            return redirect(url_for("admin.login"))
            
    return render_template("admin/login.html")

@admin_bp.route("/logout")
def logout():
    session.pop("is_superadmin", None)
    flash("Admin logged out", "success")
    return redirect(url_for("dashboard.index"))

@admin_bp.route("/", methods=["GET", "POST"])
def dashboard():
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    if request.method == "POST":
        keys_to_save = {
            "BACKGROUND_KEY_PERCENTAGE": request.form.get("background_key_percentage", "50").strip(),
            "GEMINI_API_KEYS": request.form.get("gemini_keys", "").strip(),
            "NVIDIA_NIM_API_KEYS": request.form.get("nvidia_keys", "").strip(),
            "GROQ_API_KEYS": request.form.get("groq_keys", "").strip(),
            "CEREBRAS_API_KEYS": request.form.get("cerebras_keys", "").strip(),
            "OPENROUTER_API_KEYS": request.form.get("openrouter_keys", "").strip()
        }
        
        for k, v in keys_to_save.items():
            # Upsert
            existing = db_service.query("SELECT * FROM system_settings WHERE key_name = ?", (k,), one=True)
            if existing:
                db_service.execute("UPDATE system_settings SET key_value = ?, updated_at = CURRENT_TIMESTAMP WHERE key_name = ?", (v, k))
            else:
                db_service.execute("INSERT INTO system_settings (key_name, key_value) VALUES (?, ?)", (k, v))
                
        flash("Global API Keys updated successfully!", "success")
        return redirect(url_for("admin.dashboard"))
        
    # Fetch existing API keys
    rows = db_service.query("SELECT key_name, key_value FROM system_settings")
    settings = {row["key_name"]: row["key_value"] for row in rows} if rows else {}
    
    # Fetch Users
    users = db_service.query("SELECT p.*, COALESCE(u.subscription_tier, 'free') as subscription_tier FROM profiles p LEFT JOIN user_usage u ON p.id = u.user_id ORDER BY p.created_at DESC")
    
    # Fetch Payment Proofs (Pending first)
    proofs = db_service.query("SELECT pp.*, p.email, p.full_name FROM payment_proofs pp JOIN profiles p ON pp.user_id = p.id ORDER BY CASE WHEN pp.status = 'pending' THEN 0 ELSE 1 END, pp.created_at DESC")
    
    # Fetch Genuine Support Requests
    requests_list = db_service.query("SELECT sr.*, p.email, p.full_name FROM support_requests sr JOIN profiles p ON sr.user_id = p.id WHERE sr.is_genuine = 1 ORDER BY CASE WHEN sr.status = 'open' THEN 0 ELSE 1 END, sr.created_at DESC")
    
    # Fetch Global Weekly Test Approval Status
    from datetime import datetime
    today = datetime.now()
    current_year, current_week, _ = today.isocalendar()
    week_key = f"WEEKLY_TEST_RELEASE_{current_year}_W{current_week}"
    
    release_status_row = db_service.query("SELECT key_value FROM system_settings WHERE key_name = ?", (week_key,), one=True)
    weekly_test_status = release_status_row["key_value"] if release_status_row else "pending"
    
    return render_template("admin/dashboard.html", settings=settings, users=users, proofs=proofs, requests=requests_list, weekly_test_status=weekly_test_status, current_week=f"Week {current_week}, {current_year}")

@admin_bp.route("/proof/<proof_id>/view", methods=["GET"])
def view_proof(proof_id):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    proof = db_service.query("SELECT * FROM payment_proofs WHERE id = ?", (proof_id,), one=True)
    if not proof or not proof.get("file_path"):
        flash("Proof file not found", "error")
        return redirect(url_for("admin.dashboard"))
        
    import os
    from flask import send_file
    file_path = proof["file_path"]
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        flash("File no longer exists on server", "error")
        return redirect(url_for("admin.dashboard"))

@admin_bp.route("/proof/<proof_id>/<action>", methods=["POST"])
def handle_proof(proof_id, action):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    proof = db_service.query("SELECT * FROM payment_proofs WHERE id = ?", (proof_id,), one=True)
    if not proof:
        flash("Proof not found", "error")
        return redirect(url_for("admin.dashboard"))
        
    if action == "approve":
        db_service.execute("UPDATE payment_proofs SET status = 'approved' WHERE id = ?", (proof_id,))
        # IMPORTANT: Set is_premium in profiles, and subscription_tier in user_usage
        from services.billing_service import billing_service
        billing_service.upgrade_user_to_premium(proof["user_id"])
        flash("Proof approved and user upgraded to premium.", "success")
    elif action == "reject":
        db_service.execute("UPDATE payment_proofs SET status = 'rejected' WHERE id = ?", (proof_id,))
        flash("Proof rejected.", "success")
        
    # Delete screenshot from disk to save space (but keep DB record)
    if proof.get("file_path"):
        import os
        try:
            if os.path.exists(proof["file_path"]):
                os.remove(proof["file_path"])
        except Exception as e:
            print(f"Failed to delete payment proof screenshot: {e}")
            
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/weekly-tests/global/<action>", methods=["POST"])
def handle_global_weekly_test(action):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    from datetime import datetime
    today = datetime.now()
    current_year, current_week, _ = today.isocalendar()
    week_key = f"WEEKLY_TEST_RELEASE_{current_year}_W{current_week}"
    
    if action == "approve":
        existing = db_service.query("SELECT * FROM system_settings WHERE key_name = ?", (week_key,), one=True)
        if existing:
            db_service.execute("UPDATE system_settings SET key_value = 'approved', updated_at = CURRENT_TIMESTAMP WHERE key_name = ?", (week_key,))
        else:
            db_service.execute("INSERT INTO system_settings (key_name, key_value) VALUES (?, 'approved')", (week_key,))
        flash(f"Weekly tests for Week {current_week} have been released globally.", "success")
        
    elif action == "reject":
        existing = db_service.query("SELECT * FROM system_settings WHERE key_name = ?", (week_key,), one=True)
        if existing:
            db_service.execute("UPDATE system_settings SET key_value = 'dismissed', updated_at = CURRENT_TIMESTAMP WHERE key_name = ?", (week_key,))
        else:
            db_service.execute("INSERT INTO system_settings (key_name, key_value) VALUES (?, 'dismissed')", (week_key,))
        flash(f"Weekly tests for Week {current_week} have been dismissed.", "success")
        
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/request/<request_id>/close", methods=["POST"])
def close_request(request_id):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    db_service.execute("UPDATE support_requests SET status = 'closed' WHERE id = ?", (request_id,))
    flash("Request marked as closed.", "success")
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/request/<request_id>/reply", methods=["POST"])
def reply_request(request_id):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    reply_message = request.form.get("reply_message")
    if not reply_message:
        flash("Reply message cannot be empty.", "error")
        return redirect(url_for("admin.dashboard"))
        
    # Get request and user info
    req = db_service.query(
        "SELECT sr.*, p.email, p.full_name FROM support_requests sr JOIN profiles p ON sr.user_id = p.id WHERE sr.id = ?",
        (request_id,), one=True
    )
    
    if req and req["email"]:
        from services.email_service import email_service
        success = email_service.send_support_reply(req["email"], req["full_name"] or "User", reply_message)
        
        if success:
            db_service.execute("UPDATE support_requests SET status = 'closed' WHERE id = ?", (request_id,))
            flash(f"Reply sent to {req['email']} and request closed.", "success")
        else:
            flash("Failed to send email. Check Resend configuration.", "error")
    else:
        flash("Request or user email not found.", "error")
        
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/user/<user_id>/reset_password", methods=["POST"])
def reset_password(user_id):
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))
        
    user = db_service.query("SELECT * FROM profiles WHERE id = ?", (user_id,), one=True)
    if user and user["email"]:
        from services.email_service import email_service
        from routes.auth import _generate_otp
        
        otp, otp_hash = _generate_otp()
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
        
        import uuid
        db_service.execute("INSERT INTO password_reset_otps (id, email, otp_hash, expires_at) VALUES (?, ?, ?, ?)",
                           (str(uuid.uuid4()), user["email"], otp_hash, expires_at))
        
        email_service.send_password_reset(user["email"], otp)
        flash(f"Password reset email sent to {user['email']}.", "success")
    else:
        flash("User or email not found.", "error")
        
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/upload-syllabus", methods=["POST"])
def upload_syllabus():
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))

    education = request.form.get("education", "").strip().lower().replace(" ", "_")
    board = request.form.get("board", "").strip().lower().replace(" ", "_")
    year = request.form.get("year", "").strip().lower().replace(" ", "_")
    group = request.form.get("group", "").strip().upper()
    
    pdf_file = request.files.get("pdf_file")

    if not all([education, board, year, group, pdf_file]):
        flash("Please provide all fields and a PDF file.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        # Extract text from PDF
        pdf_bytes = pdf_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
            
        if not text.strip():
            flash("Could not extract text from the PDF. It might be an image-only PDF.", "error")
            return redirect(url_for("admin.dashboard"))

        # Send to AI for parsing
        extracted_subjects = ai_service.parse_syllabus(text)
        
        if not extracted_subjects or "subjects" not in extracted_subjects:
            flash("AI failed to extract syllabus accurately. Please try a cleaner PDF.", "error")
            return redirect(url_for("admin.dashboard"))

        # Define file path
        target_dir = os.path.join(syllabus_service.data_dir, education, board)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, f"{year}.json")

        # Load existing or create new JSON structure
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {
                "year": request.form.get("year"), # original case
                "groups": {}
            }

        if "groups" not in data:
            data["groups"] = {}

        # Save to the specific group
        data["groups"][group] = extracted_subjects["subjects"]

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        flash(f"Successfully added syllabus for {group} in {education}/{board}/{year}!", "success")
        return redirect(url_for("admin.dashboard"))

    except Exception as e:
        print(f"Error processing PDF: {e}")
        flash(f"An error occurred: {str(e)}", "error")
        return redirect(url_for("admin.dashboard"))

@admin_bp.route("/import-questions", methods=["POST"])
def import_questions():
    if not session.get("is_admin"):
        return redirect(url_for("admin.login"))
        
    try:
        json_file = request.files.get("json_file")
        if not json_file or not json_file.filename.endswith(".json"):
            flash("Please upload a valid JSON file.", "error")
            return redirect(url_for("admin.dashboard"))
            
        data = json.loads(json_file.read().decode("utf-8"))
        if not isinstance(data, list):
            flash("JSON must contain a list of questions.", "error")
            return redirect(url_for("admin.dashboard"))
            
        conn, cursor = db_service._get_conn()
        try:
            for q in data:
                cursor.execute(db_service._prepare_query('''
                    INSERT INTO question_bank 
                    (id, subject_id, unit_id, topic_id, difficulty, question, options, correct_answer, explanation, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                '''), (
                    q.get("id"), q.get("subject_id"), q.get("unit_id"), q.get("topic_id"), 
                    q.get("difficulty"), q.get("question"), q.get("options"), 
                    q.get("correct_answer"), q.get("explanation"), q.get("created_at")
                ))
            conn.commit()
            flash(f"Successfully imported {len(data)} questions into the Question Bank!", "success")
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        flash(f"Import failed: {str(e)}", "error")
        
    return redirect(url_for("admin.dashboard"))
