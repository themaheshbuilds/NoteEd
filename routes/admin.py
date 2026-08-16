from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from services.db_service import db_service
import os
import json
import fitz  # PyMuPDF
from services.syllabus_service import syllabus_service
from services.ai_service import ai_service
from services.security import require_admin, verify_admin_credentials, validate_path_within_directory

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        # [C1] Verify credentials from environment variables (hashed)
        if verify_admin_credentials(username, password):
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
        form_type = request.form.get("form_type", "ai_keys")

        if form_type in ("ai_keys", "omniroute"):
            keys_to_save = {
                "GEMINI_API_KEY":        request.form.get("gemini_api_key", "").strip(),
                "OPENROUTER_API_KEY":    request.form.get("openrouter_api_key", "").strip(),
                "GROQ_API_KEY":          request.form.get("groq_api_key", "").strip(),
                "OPENAI_API_KEY":        request.form.get("openai_api_key", "").strip(),
                "NVIDIA_API_KEY":        request.form.get("nvidia_api_key", "").strip(),
                "OMNIROUTE_BASE_URL":    request.form.get("omniroute_base_url", "").strip(),
                "OMNIROUTE_API_KEY":     request.form.get("omniroute_api_key", "").strip(),
                "OMNIROUTE_MODEL":       request.form.get("omniroute_model", "").strip(),
                "OMNIROUTE_VISION_MODEL": request.form.get("omniroute_vision_model", "").strip(),
            }
            for k, v in keys_to_save.items():
                if v is not None:
                    existing = db_service.query("SELECT * FROM system_settings WHERE key_name = ?", (k,), one=True)
                    if existing:
                        db_service.execute("UPDATE system_settings SET key_value = ?, updated_at = CURRENT_TIMESTAMP WHERE key_name = ?", (v, k))
                    elif v:
                        db_service.execute("INSERT INTO system_settings (key_name, key_value) VALUES (?, ?)", (k, v))
            flash("AI API configuration saved successfully!", "success")

        return redirect(url_for("admin.dashboard"))

    # Fetch settings
    rows = db_service.query("SELECT key_name, key_value FROM system_settings")
    settings = {row["key_name"]: row["key_value"] for row in rows} if rows else {}

    # AI Provider health check
    ai_status = "unconfigured"
    ai_status_detail = ""
    active_provider = "None"
    try:
        _key, _url, _model, _ = ai_service._get_omni_config()
        if _key and "your-" not in _key.lower() and "placeholder" not in _key.lower():
            if "generativelanguage.googleapis.com" in _url:
                active_provider = "Google Gemini"
            elif "openrouter.ai" in _url:
                active_provider = "OpenRouter"
            elif "api.groq.com" in _url:
                active_provider = "Groq"
            elif "api.openai.com" in _url:
                active_provider = "OpenAI"
            elif "nvidia.com" in _url:
                active_provider = "NVIDIA NIM"
            else:
                active_provider = "OmniRoute / Gateway"

            ai_status = "connected"
            ai_status_detail = f"Active: {active_provider} ({_model})"
        else:
            ai_status = "unconfigured"
            ai_status_detail = "No API key configured"
    except Exception as _e:
        ai_status = "offline"
        ai_status_detail = str(_e)[:120]

    omniroute_status = ai_status
    omniroute_status_detail = ai_status_detail

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

    # Build syllabus file browser list
    syllabus_files = _get_syllabus_files()
    provider_pools = ai_service.get_all_provider_pools()

    # IST Time & System Clock
    from services.study_coach_service import get_ist_time_info
    ist_info = get_ist_time_info()

    return render_template(
        "admin/dashboard.html",
        settings=settings,
        users=users,
        proofs=proofs,
        requests=requests_list,
        weekly_test_status=weekly_test_status,
        current_week=f"Week {current_week}, {current_year}",
        syllabus_files=syllabus_files,
        omniroute_status=omniroute_status,
        omniroute_status_detail=omniroute_status_detail,
        provider_pools=provider_pools,
        ist_info=ist_info,
    )


def _get_syllabus_files():
    """Walk the syllabus data directory and return a list of file info dicts."""
    files = []
    data_dir = syllabus_service.data_dir
    if not os.path.exists(data_dir):
        return files
    for root, dirs, filenames in os.walk(data_dir):
        for fname in filenames:
            if fname.endswith('.json'):
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, data_dir).replace('\\', '/')
                size_kb = round(os.path.getsize(full_path) / 1024, 1)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    groups = list(data.get('groups', {}).keys())
                except Exception:
                    groups = ['(invalid JSON)']
                files.append({'path': rel_path, 'size_kb': size_kb, 'groups': groups})
    return sorted(files, key=lambda x: x['path'])



@admin_bp.route("/proof/<proof_id>/view", methods=["GET"])
@require_admin
def view_proof(proof_id):
    proof = db_service.query("SELECT * FROM payment_proofs WHERE id = ?", (proof_id,), one=True)
    if not proof or not proof["file_path"]:
        flash("Proof file not found", "error")
        return redirect(url_for("admin.dashboard"))
        
    from flask import send_file
    file_path = os.path.abspath(proof["file_path"])

    # [H7] Path traversal protection: ensure file is within uploads directory
    uploads_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "../uploads"))
    if not validate_path_within_directory(file_path, uploads_dir):
        flash("Access denied: file path is outside the uploads directory.", "error")
        return redirect(url_for("admin.dashboard"))

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
    if proof and proof["file_path"]:
        import os
        try:
            target_path = os.path.abspath(proof["file_path"])
            if os.path.exists(target_path):
                os.remove(target_path)
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

@admin_bp.route("/add-syllabus-manual", methods=["POST"])
def add_syllabus_manual():
    if not session.get("is_superadmin"):
        return redirect(url_for("admin.login"))

    education = request.form.get("education", "").strip().lower().replace(" ", "_")
    board = request.form.get("board", "").strip().lower().replace(" ", "_")
    year = request.form.get("year", "").strip().lower().replace(" ", "_")
    group = request.form.get("group", "").strip()
    subjects_json_str = request.form.get("subjects_json", "").strip()

    if not all([education, board, year, group, subjects_json_str]):
        flash("Please fill in all required fields and add at least one subject.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        subjects = json.loads(subjects_json_str)
        if not isinstance(subjects, list) or len(subjects) == 0:
            flash("Please add at least one subject with a name.", "error")
            return redirect(url_for("admin.dashboard"))

        # Validate basic structure
        for subj in subjects:
            if not subj.get("subject"):
                flash("One or more subjects is missing a name.", "error")
                return redirect(url_for("admin.dashboard"))

        # Build the file path
        target_dir = os.path.join(syllabus_service.data_dir, education, board)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, f"{year}.json")

        # Load existing or create new
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        else:
            data = {"year": year, "groups": {}}

        if "groups" not in data:
            data["groups"] = {}

        # Save/overwrite this group's subjects
        data["groups"][group] = subjects

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        flash(f"✅ Syllabus saved! {len(subjects)} subject(s) added for '{group}' in {education}/{board}/{year}.", "success")

    except json.JSONDecodeError as e:
        flash(f"Invalid subject data format: {str(e)}", "error")
    except Exception as e:
        print(f"Error saving manual syllabus: {e}")
        flash(f"An error occurred: {str(e)}", "error")

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
            with open(file_path, "r", encoding="utf-8-sig") as f:
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
    if not session.get("is_superadmin"):
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

