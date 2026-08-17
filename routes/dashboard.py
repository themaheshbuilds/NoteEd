import uuid
import os
from datetime import datetime
# pyrefly: ignore [missing-import]
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from services.db_service import db_service
from services.ai_service import ai_service

dashboard_bp = Blueprint("dashboard", __name__)

def get_current_user():
    if "user_id" not in session:
        return None
    # Fetch subscription tier using usage_service which syncs from profiles
    from services.usage_service import usage_service
    tier = usage_service.check_and_sync_premium_status(session["user_id"])
    
    return {
        "id": session["user_id"],
        "email": session["email"],
        "full_name": session["full_name"],
        "subscription_tier": tier
    }

@dashboard_bp.route("/")
def index():
    user = get_current_user()
    if not user:
        # Pass empty/default values for unauthenticated users
        return render_template(
            "dashboard/index.html",
            profile=None,
            semesters=[],
            sessions=[],
            exams=[],
            recent_files=[],
            pending_tests=[],
            is_sunday=False,
            weekly_test_status=None
        )
        
    # Get user profile info
    profile = db_service.query("SELECT * FROM profiles WHERE id = ?", (user["id"],), one=True)
    if not profile:
        session.clear()
        flash("Your session is invalid or database was reset. Please log in again.", "error")
        return redirect(url_for("auth.login"))
        
    from routes.study import increment_daily_streak
    increment_daily_streak(user["id"])
    
    # Refresh profile to get updated streak
    profile = db_service.query("SELECT * FROM profiles WHERE id = ?", (user["id"],), one=True)
    
    # Get semesters
    semesters = db_service.query("SELECT * FROM semesters WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
    
    # Get study sessions (for progress/study streak)
    sessions = db_service.query("SELECT * FROM study_sessions WHERE user_id = ? ORDER BY completed_at DESC LIMIT 5", (user["id"],))
    
    # Get upcoming exam planners
    exams = db_service.query(
        "SELECT * FROM planner_events WHERE user_id = ? AND event_type = 'exam' AND is_completed = 0 ORDER BY start_time ASC LIMIT 3",
        (user["id"],)
    )
    
    # Get recent files
    recent_files = db_service.query(
        """SELECT f.*, t.name as topic_name, s.name as subject_name 
           FROM files f 
           JOIN topics t ON f.topic_id = t.id
           JOIN units u ON t.unit_id = u.id
           JOIN subjects s ON u.subject_id = s.id
           WHERE s.semester_id IN (SELECT id FROM semesters WHERE user_id = ?)
           ORDER BY f.created_at DESC LIMIT 5""",
        (user["id"],)
    )
    
    # If no semesters, redirect to setup wizard
    if not semesters:
        return redirect(url_for("dashboard.setup"))

    # Check and generate weekly tests (runs async in background)
    from services.weekly_test_service import weekly_test_service
    weekly_test_service.check_and_generate(user["id"])
    
    # Get available weekly tests
    pending_tests = db_service.query("SELECT * FROM weekly_tests WHERE user_id = ? AND status = 'approved' ORDER BY created_at DESC", (user["id"],))

    # Check global admin approval status for the week
    today = datetime.now()
    is_sunday = (today.weekday() == 6)
    weekly_test_status = None
    if is_sunday:
        current_year, current_week, _ = today.isocalendar()
        week_key = f"WEEKLY_TEST_RELEASE_{current_year}_W{current_week}"
        release_status_row = db_service.query("SELECT key_value FROM system_settings WHERE key_name = ?", (week_key,), one=True)
        if release_status_row:
            weekly_test_status = release_status_row["key_value"] # "approved" or "dismissed"

    # Determine premium status from authoritative subscription_tier
    is_premium = (user.get('subscription_tier') == 'premium') or bool(profile['is_premium'])

    # Dynamic IST 12-Hour Hourly Greetings and Daily Rotating AI Coach Tips
    from services.study_coach_service import get_ist_time_info, get_daily_study_tips, get_all_study_tips
    ist_info = get_ist_time_info()
    daily_study_tips = get_daily_study_tips(count=2)
    all_study_tips = get_all_study_tips()

    return render_template(
        "dashboard/index.html",
        profile=profile,
        current_user=user,
        is_premium=is_premium,
        semesters=semesters,
        sessions=sessions,
        exams=exams,
        recent_files=recent_files,
        pending_tests=pending_tests,
        is_sunday=is_sunday,
        weekly_test_status=weekly_test_status,
        ist_info=ist_info,
        daily_study_tips=daily_study_tips,
        all_study_tips=all_study_tips
    )

@dashboard_bp.route("/setup", methods=["GET", "POST"])
def setup():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    from services.syllabus_service import syllabus_service
    
    if request.method == "POST":
        education = request.form.get("education")

        # Custom Degree / MBA / Other Course Creation
        if education == "custom" or request.form.get("custom_course_name"):
            course_name = request.form.get("custom_course_name", "Degree Course").strip()
            univ_name = request.form.get("custom_board_name", "University / Autonomous").strip()
            year_sem = request.form.get("custom_year_name", "Semester 1").strip()
            branch = request.form.get("custom_group_name", "General").strip()
            raw_subjects = request.form.get("custom_subjects", "").strip()

            if not course_name:
                course_name = "Custom Degree / Course"

            sem_name = f"{course_name} ({branch}) - {year_sem}"
            if univ_name:
                sem_name += f" [{univ_name}]"

            sem_id = str(uuid.uuid4())
            db_service.execute(
                "INSERT INTO semesters (id, user_id, name) VALUES (?, ?, ?)",
                (sem_id, user["id"], sem_name)
            )

            import re
            sub_list = []
            if raw_subjects:
                lines = [line.strip() for line in re.split(r'[\r\n,]+', raw_subjects) if line.strip()]
                sub_list = lines

            if not sub_list:
                sub_list = [f"{course_name} Core Paper 1", f"{course_name} Core Paper 2", f"{course_name} Core Paper 3"]

            for sub_name in sub_list:
                sub_id = str(uuid.uuid4())
                db_service.execute(
                    "INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)",
                    (sub_id, sem_id, sub_name, "")
                )
                default_units = [
                    ("Unit 1: Introduction & Foundational Concepts", [f"Overview of {sub_name}", f"Key Principles & Definitions in {sub_name}", f"Theoretical Framework of {sub_name}"]),
                    ("Unit 2: Core Models & Methodologies", [f"Core Methodologies in {sub_name}", f"Process & Implementation Techniques", f"Standard Models & Workflows"]),
                    ("Unit 3: Advanced Analysis & Problem Solving", [f"Advanced Concepts in {sub_name}", f"Analytical Frameworks & Tools", f"Problem Solving Strategies"]),
                    ("Unit 4: Real-World Applications & Case Studies", [f"Practical Case Studies in {sub_name}", f"Industry Standards & Best Practices", f"Contemporary Issues in {sub_name}"]),
                    ("Unit 5: Exam Review, Revision & Viva Q&A", [f"High-Yield Exam Topics in {sub_name}", f"Key Formulas & Summaries", f"Viva Voce Preparation for {sub_name}"])
                ]
                for u_idx, (u_title, default_topics) in enumerate(default_units, 1):
                    unit_id = str(uuid.uuid4())
                    db_service.execute(
                        "INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)",
                        (unit_id, sub_id, u_title, u_idx)
                    )
                    for t_name in default_topics:
                        topic_id = str(uuid.uuid4())
                        db_service.execute(
                            "INSERT INTO topics (id, unit_id, name) VALUES (?, ?, ?)",
                            (topic_id, unit_id, t_name)
                        )

            flash(f"Custom course '{course_name}' imported successfully with all subjects and starter units!", "success")
            return redirect(url_for("dashboard.index"))

        board = request.form.get("board")
        group = request.form.get("group")
        year = request.form.get("year")
        
        if not all([education, board, group, year]):
            flash("Please fill all fields", "error")
            return redirect(url_for("dashboard.setup"))
            
        # Format semester name
        sem_name = f"{year} - {group} ({board.upper()})"
        import re
        match_c24 = re.match(r"(c\d+)_(\d+)(?:st|nd|rd|th)_sem", year, re.IGNORECASE)
        match_btech = re.match(r"(\d+)(?:st|nd|rd|th)_year_(\d+)(?:st|nd|rd|th)_sem", year, re.IGNORECASE)
        if match_c24:
            curriculum = match_c24.group(1).upper()
            sem_num = match_c24.group(2)
            board_upper = board.upper()
            formatted_board = "TG SBTET" if board_upper == "SBTET_TG" else ("AP SBTET" if board_upper == "SBTET_AP" else board_upper)
            sem_name = f"{curriculum} SEM {sem_num} - {formatted_board} {group.upper()}"
        elif match_btech:
            y_num = match_btech.group(1)
            s_num = match_btech.group(2)
            board_label = "JNTUH" if "jntu" in board.lower() else board.upper()
            sem_name = f"B.Tech Year {y_num}-{s_num} ({board_label}) - {group.upper()}"
        elif year in ["first_year", "second_year"]:
            yr_str = "1st Year" if year == "first_year" else "2nd Year"
            board_upper = board.upper()
            formatted_board = "TG Board" if board_upper == "TG" else ("AP Board" if board_upper == "AP" else board_upper)
            sem_name = f"{yr_str} - {formatted_board} {group.upper()}"
            
        sem_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO semesters (id, user_id, name) VALUES (?, ?, ?)",
            (sem_id, user["id"], sem_name)
        )
        
        subjects = syllabus_service.get_subjects_for_group(education, board, year, group)
        for sub in subjects:
            sub_id = str(uuid.uuid4())
            db_service.execute(
                "INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)",
                (sub_id, sem_id, sub["subject"], sub.get("code", ""))
            )
            
            for i, chapter in enumerate(sub.get("chapters", []), start=1):
                unit_id = str(uuid.uuid4())
                db_service.execute(
                    "INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)",
                    (unit_id, sub_id, chapter["name"], i)
                )
                
                for topic in chapter.get("topics", []):
                    topic_id = str(uuid.uuid4())
                    db_service.execute(
                        "INSERT INTO topics (id, unit_id, name) VALUES (?, ?, ?)",
                        (topic_id, unit_id, topic)
                    )
                    
        flash("Your syllabus has been successfully imported!", "success")
        return redirect(url_for("dashboard.index"))

    educations = syllabus_service.get_available_education_levels()
    return render_template("dashboard/setup.html", educations=educations)

@dashboard_bp.route("/api/syllabus/boards/<education>")
def api_get_boards(education):
    from services.syllabus_service import syllabus_service
    return jsonify(syllabus_service.get_available_boards(education))

@dashboard_bp.route("/api/syllabus/years/<education>/<board>")
def api_get_years(education, board):
    from services.syllabus_service import syllabus_service
    return jsonify(syllabus_service.get_available_years(education, board))

@dashboard_bp.route("/api/syllabus/groups/<education>/<board>/<year>")
def api_get_groups(education, board, year):
    from services.syllabus_service import syllabus_service
    return jsonify(syllabus_service.get_available_groups(education, board, year))

@dashboard_bp.route("/semester/add", methods=["POST"])
def add_semester():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    name = request.form.get("name")
    if name:
        sem_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO semesters (id, user_id, name) VALUES (?, ?, ?)",
            (sem_id, user["id"], name)
        )
        flash("Semester added.", "success")
    return redirect(url_for("dashboard.index"))

@dashboard_bp.route("/semester/<sem_id>")
def view_semester(sem_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    semester = db_service.query("SELECT * FROM semesters WHERE id = ? AND user_id = ?", (sem_id, user["id"]), one=True)
    if not semester:
        flash("Semester not found.", "error")
        return redirect(url_for("dashboard.index"))
        
    subjects = db_service.query("SELECT * FROM subjects WHERE semester_id = ? ORDER BY created_at DESC", (sem_id,))
    return render_template("dashboard/semester.html", semester=semester, subjects=subjects)

@dashboard_bp.route("/semester/<sem_id>/subject/add", methods=["POST"])
def add_subject(sem_id):
    name = request.form.get("name")
    code = request.form.get("code", "")
    if name:
        sub_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)",
            (sub_id, sem_id, name, code)
        )
        flash("Subject added.", "success")
    return redirect(url_for("dashboard.view_semester", sem_id=sem_id))

@dashboard_bp.route("/subject/<sub_id>")
def view_subject(sub_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    subject = db_service.query(
        """SELECT s.*, sem.user_id FROM subjects s 
           JOIN semesters sem ON s.semester_id = sem.id 
           WHERE s.id = ?""", (sub_id,), one=True
    )
    if not subject or subject["user_id"] != user["id"]:
        flash("Subject not found.", "error")
        return redirect(url_for("dashboard.index"))
        
    units = db_service.query("SELECT * FROM units WHERE subject_id = ? ORDER BY number ASC", (sub_id,))
    
    # Fetch topics for each unit
    units_with_topics = []
    for unit in units:
        topics = db_service.query("SELECT * FROM topics WHERE unit_id = ? ORDER BY order_index ASC", (unit["id"],))
        units_with_topics.append({
            "unit": unit,
            "topics": topics
        })
        
    return render_template("dashboard/subject.html", subject=subject, units_with_topics=units_with_topics)

@dashboard_bp.route("/subject/<sub_id>/unit/add", methods=["POST"])
def add_unit(sub_id):
    name = request.form.get("name")
    number = request.form.get("number")
    if name and number:
        unit_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)",
            (unit_id, sub_id, name, int(number))
        )
        flash("Unit added.", "success")
    return redirect(url_for("dashboard.view_subject", sub_id=sub_id))

@dashboard_bp.route("/unit/<unit_id>/topic/add", methods=["POST"])
def add_topic(unit_id):
    name = request.form.get("name")
    if name:
        topic_id = str(uuid.uuid4())
        # Find current highest order index
        highest = db_service.query("SELECT MAX(order_index) as max_idx FROM topics WHERE unit_id = ?", (unit_id,), one=True)
        next_idx = (highest["max_idx"] or 0) + 1
        
        db_service.execute(
            "INSERT INTO topics (id, unit_id, name, order_index, is_completed) VALUES (?, ?, ?, ?, 0)",
            (topic_id, unit_id, name, next_idx)
        )
        flash("Topic added.", "success")
        
    # Redirect back to subject page
    unit = db_service.query("SELECT subject_id FROM units WHERE id = ?", (unit_id,), one=True)
    return redirect(url_for("dashboard.view_subject", sub_id=unit["subject_id"]))

@dashboard_bp.route("/topic/<topic_id>")
def view_topic(topic_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    topic = db_service.query(
        """SELECT t.*, u.name as unit_name, s.name as subject_name, s.id as subject_id
           FROM topics t
           JOIN units u ON t.unit_id = u.id
           JOIN subjects s ON u.subject_id = s.id
           WHERE t.id = ?""", (topic_id,), one=True)
    
    files = db_service.query("SELECT * FROM files WHERE topic_id = ? AND is_archived = 0", (topic_id,))
    
    # Active materials (is_archived = 0)
    notes = db_service.query("SELECT * FROM notes WHERE topic_id = ? AND is_archived = 0 ORDER BY created_at DESC", (topic_id,))
    flashcards = db_service.query("SELECT * FROM flashcards WHERE topic_id = ? AND is_archived = 0", (topic_id,))
    quizzes = db_service.query("SELECT * FROM quizzes WHERE topic_id = ? AND is_archived = 0", (topic_id,))
    
    # Archived materials
    archived_notes = db_service.query("SELECT * FROM notes WHERE topic_id = ? AND is_archived = 1 ORDER BY created_at DESC", (topic_id,))
    archived_flashcards = db_service.query("SELECT * FROM flashcards WHERE topic_id = ? AND is_archived = 1", (topic_id,))
    archived_quizzes = db_service.query("SELECT * FROM quizzes WHERE topic_id = ? AND is_archived = 1 ORDER BY created_at DESC", (topic_id,))
    
    # Fetch chat sessions (exclude archived ones)
    chat_sessions = db_service.query("SELECT * FROM chat_sessions WHERE topic_id = ? AND is_archived = 0 ORDER BY created_at DESC", (topic_id,))
    
    # Determine which session to load
    session_id = request.args.get("session_id")
    is_new = request.args.get("new")
    
    if is_new == '1':
        session_id = None
    elif not session_id and chat_sessions:
        session_id = chat_sessions[0]["id"]
        
    # Fetch chat history for the active session
    if session_id:
        chat_messages = db_service.query("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    else:
        chat_messages = []
    
    # Check bookmark status
    is_bookmarked = False
    bookmark = db_service.query("SELECT id FROM bookmarks WHERE user_id = ? AND topic_id = ?", (user["id"], topic_id), one=True)
    if bookmark:
        is_bookmarked = True
    
    # Fetch user's profile for experience level and study purpose
    profile = db_service.query("SELECT experience_level, study_purpose FROM profiles WHERE id = ?", (user["id"],), one=True)
    experience_level = profile["experience_level"] if profile and profile["experience_level"] else "intermediate"
    study_purpose = profile["study_purpose"] if profile and profile["study_purpose"] else "learning"
    
    # Check Admin status and Print Permissions
    admin_email = os.getenv("ADMIN_EMAIL", "vilasagarammahesh90@gmail.com").strip().lower()
    user_email = (user.get("email") or "").strip().lower()
    is_admin = bool(
        session.get("is_superadmin")
        or (user_email and user_email == admin_email)
        or (user.get("role") == "admin")
    )

    print_setting = db_service.query("SELECT key_value FROM system_settings WHERE key_name = 'ADMIN_PRINT_MODE'", one=True)
    print_mode = (print_setting["key_value"] if print_setting else "disabled").strip().lower()
    
    if print_mode in ["all_users", "enabled", "true", "on"]:
        allow_print = True
    elif print_mode == "admin_only":
        allow_print = is_admin
    else:  # "disabled", "off", "false", "0"
        allow_print = False

    copy_setting = db_service.query("SELECT key_value FROM system_settings WHERE key_name = 'ADMIN_COPY_MODE'", one=True)
    copy_mode = copy_setting["key_value"] if copy_setting else "admin_only"
    
    if copy_mode == "all_users":
        allow_copy = True
    elif copy_mode == "disabled":
        allow_copy = False
    else:  # "admin_only"
        allow_copy = is_admin

    return render_template(
        "dashboard/topic.html",
        topic=topic,
        files=files,
        notes=notes,
        flashcards=flashcards,
        quizzes=quizzes,
        chat_messages=chat_messages,
        is_bookmarked=is_bookmarked,
        archived_notes=archived_notes,
        archived_flashcards=archived_flashcards,
        archived_quizzes=archived_quizzes,
        chat_sessions=chat_sessions,
        active_session_id=session_id,
        experience_level=experience_level,
        study_purpose=study_purpose,
        is_admin=is_admin,
        allow_print=allow_print,
        allow_copy=allow_copy,
        print_mode=print_mode,
        copy_mode=copy_mode
    )

# ── Bookmarks ────────────────────────────────────────────────────────────
@dashboard_bp.route("/bookmarks")
def bookmarks():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))

    bookmarked_topics = db_service.query(
        """SELECT b.id as bookmark_id, b.created_at as bookmarked_at,
                  t.id as topic_id, t.name as topic_name, t.is_completed,
                  u.name as unit_name,
                  s.name as subject_name, s.id as subject_id
           FROM bookmarks b
           JOIN topics t ON b.topic_id = t.id
           JOIN units u ON t.unit_id = u.id
           JOIN subjects s ON u.subject_id = s.id
           WHERE b.user_id = ?
           ORDER BY b.created_at DESC""",
        (user["id"],)
    )

    return render_template("dashboard/bookmarks.html", bookmarks=bookmarked_topics)

# ── Settings ────────────────────────────────────────────────────────────
@dashboard_bp.route("/settings")
def settings():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    profile = db_service.query("SELECT * FROM profiles WHERE id = ?", (user["id"],), one=True)
    return render_template("dashboard/settings.html", profile=profile)

@dashboard_bp.route("/settings/profile", methods=["POST"])
def update_profile():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    full_name_input = (request.form.get("full_name") or "").strip()
    
    full_name = f"{first_name} {last_name}".strip() or full_name_input
    if full_name:
        db_service.execute("UPDATE profiles SET full_name = ? WHERE id = ?", (full_name, user["id"]))
        session["full_name"] = full_name
        flash("Profile updated successfully.", "success")
    return redirect(url_for("dashboard.settings"))

@dashboard_bp.route("/settings/api_keys", methods=["POST"])
def update_api_keys():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    api_keys = request.form.get("api_keys")
    ai_platform = request.form.get("ai_platform", "custom")
    custom_instructions = request.form.get("custom_instructions", "")
    
    if api_keys is not None:
        db_service.execute(
            "UPDATE profiles SET api_keys = ?, ai_platform = ?, custom_instructions = ? WHERE id = ?", 
            (api_keys, ai_platform, custom_instructions, user["id"])
        )
    else:
        db_service.execute(
            "UPDATE profiles SET ai_platform = ?, custom_instructions = ? WHERE id = ?", 
            (ai_platform, custom_instructions, user["id"])
        )
    
    # Clear invalid flag if present
    from flask import session
    session.pop("api_key_invalid", None)
    
    flash("API Settings updated successfully.", "success")
    return redirect(url_for("dashboard.settings"))

@dashboard_bp.route("/settings/reset", methods=["POST"])
def reset_account():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    user_id = user["id"]
    
    # Get all semester IDs for this user
    sems = db_service.query("SELECT id FROM semesters WHERE user_id = ?", (user_id,))
    sem_ids = [s["id"] for s in sems]
    
    if sem_ids:
        # Get all subjects for these semesters
        placeholders = ','.join('?' for _ in sem_ids)
        subs = db_service.query(f"SELECT id FROM subjects WHERE semester_id IN ({placeholders})", sem_ids)
        sub_ids = [s["id"] for s in subs]
        
        if sub_ids:
            # Get all units for these subjects
            placeholders_sub = ','.join('?' for _ in sub_ids)
            units = db_service.query(f"SELECT id FROM units WHERE subject_id IN ({placeholders_sub})", sub_ids)
            unit_ids = [u["id"] for u in units]
            
            if unit_ids:
                # Get all topics for these units
                placeholders_unit = ','.join('?' for _ in unit_ids)
                topics = db_service.query(f"SELECT id FROM topics WHERE unit_id IN ({placeholders_unit})", unit_ids)
                topic_ids = [t["id"] for t in topics]
                
                if topic_ids:
                    placeholders_topic = ','.join('?' for _ in topic_ids)
                    
                    # Delete files
                    db_service.execute(f"DELETE FROM files WHERE topic_id IN ({placeholders_topic})", topic_ids)
                    # Delete notes
                    db_service.execute(f"DELETE FROM notes WHERE topic_id IN ({placeholders_topic})", topic_ids)
                    # Delete flashcards
                    db_service.execute(f"DELETE FROM flashcards WHERE topic_id IN ({placeholders_topic})", topic_ids)
                    

                    # Delete quizzes
                    db_service.execute(f"DELETE FROM quizzes WHERE topic_id IN ({placeholders_topic})", topic_ids)
                    
                    # Delete topics
                    db_service.execute(f"DELETE FROM topics WHERE unit_id IN ({placeholders_unit})", unit_ids)
                
                # Delete units
                db_service.execute(f"DELETE FROM units WHERE subject_id IN ({placeholders_sub})", sub_ids)
            
            # Delete subjects
            db_service.execute(f"DELETE FROM subjects WHERE semester_id IN ({placeholders})", sem_ids)

    # Delete semesters
    db_service.execute("DELETE FROM semesters WHERE user_id = ?", (user_id,))
    
    # Delete user-scoped tables
    db_service.execute("DELETE FROM quiz_results WHERE user_id = ?", (user_id,))
    db_service.execute("DELETE FROM study_sessions WHERE user_id = ?", (user_id,))
    db_service.execute("DELETE FROM background_tasks WHERE user_id = ?", (user_id,))
    db_service.execute("DELETE FROM bookmarks WHERE user_id = ?", (user_id,))
    
    # Clear active semester
    db_service.execute("UPDATE profiles SET current_semester_id = NULL WHERE id = ?", (user_id,))
    
    flash("Account data and active background tasks reset successfully.", "success")
    return redirect(url_for("dashboard.settings"))

@dashboard_bp.route("/support", methods=["GET", "POST"])
def support():
    user = get_current_user()
    if not user:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for("auth.login"))
        
    if request.method == "POST":
        message = request.form.get("message")
        if not message:
            return jsonify({"error": "Message cannot be empty."}), 400
            
        # Call AI Triage
        triage_result = ai_service.triage_support_request(message)
        
        is_genuine = triage_result.get("needs_admin", False)
        ai_response = triage_result.get("answer", "Thank you for reaching out. An admin will review your request.")
        
        # Save to DB
        import uuid
        req_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO support_requests (id, user_id, message, ai_response, is_genuine, status) VALUES (?, ?, ?, ?, ?, 'open')",
            (req_id, user["id"], message, ai_response, 1 if is_genuine else 0)
        )
        
        return jsonify({
            "response": ai_response,
            "is_genuine": is_genuine
        })
        
    # GET request - fetch history
    history = db_service.query(
        "SELECT * FROM support_requests WHERE user_id = ? ORDER BY created_at ASC",
        (user["id"],)
    )
    return render_template("dashboard/support.html", history=history)

@dashboard_bp.route("/leaderboard")
def leaderboard():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    # Fetch top 100 students on the global leaderboard
    top_entries = db_service.query("""
        SELECT l.*, p.full_name, p.avatar_url 
        FROM leaderboard l
        JOIN profiles p ON l.user_id = p.id
        ORDER BY l.score DESC, l.time_taken_seconds ASC, l.created_at ASC
        LIMIT 100
    """)
    
    return render_template("dashboard/leaderboard.html", entries=top_entries)

@dashboard_bp.route('/api/dashboard/ai-coach')
def api_ai_coach():
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 401

    from services.usage_service import usage_service
    tier = usage_service.get_tier(user['id'])
    
    # Admin bypass or premium check
    # [M7] Admin email from environment variable
    admin_email = os.getenv("ADMIN_EMAIL", "")
    profile_check = db_service.query('SELECT email FROM profiles WHERE id = ?', (user['id'],), one=True)
    is_admin = admin_email and profile_check and profile_check['email'] == admin_email
    
    if not is_admin and tier != 'premium':
        return jsonify({'suggestions': []})

    subjects = db_service.query('SELECT s.name FROM subjects s JOIN semesters sem ON s.semester_id = sem.id WHERE sem.user_id = ? LIMIT 5', (user['id'],))
    subject_names = [s['name'] for s in subjects]

    prompt = f'The user is studying: {", ".join(subject_names) if subject_names else "general subjects"}. Provide exactly 3 short, personalized, actionable study tips (1 sentence each). Output JSON with a "tips" array.'

    try:
        result = ai_service._generate_partial(prompt, max_tokens=200)
        tips = result.get("tips", [])
        if not tips: raise ValueError('No tips')
    except Exception:
        tips = ['Take a 25-minute Pomodoro session today.', 'Review your most recent notes to reinforce memory.', 'Test yourself with a quick flashcard session.']

    return jsonify({'suggestions': tips})


@dashboard_bp.route('/api/topic/<topic_id>/save-experience-level', methods=['POST'])
def save_experience_level(topic_id):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    experience_level = data.get('experience_level')
    if experience_level not in ['beginner', 'intermediate', 'topper']:
        return jsonify({'error': 'Invalid experience level'}), 400
    db_service.execute("UPDATE profiles SET experience_level = ? WHERE id = ?", (experience_level, user['id']))
    return jsonify({'status': 'success'})


@dashboard_bp.route('/api/topic/<topic_id>/save-study-purpose', methods=['POST'])
def save_study_purpose(topic_id):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    study_purpose = data.get('study_purpose')
    if study_purpose not in ['learning', 'exam_prep']:
        return jsonify({'error': 'Invalid study purpose'}), 400
    db_service.execute("UPDATE profiles SET study_purpose = ? WHERE id = ?", (study_purpose, user['id']))
    return jsonify({'status': 'success'})


@dashboard_bp.route('/api/global-search', methods=['GET'])
def global_search():
    user = get_current_user()
    if not user:
        return jsonify({'results': [], 'topics': [], 'subjects': []}), 401
        
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'topics': [], 'subjects': []})
        
    like_param = f"%{query}%"
    
    # 1. Search Topics
    topics = db_service.query("""
        SELECT t.id, t.name, u.name as unit_name, s.name as subject_name
        FROM topics t
        JOIN units u ON t.unit_id = u.id
        JOIN subjects s ON u.subject_id = s.id
        JOIN semesters sem ON s.semester_id = sem.id
        WHERE sem.user_id = ? AND (t.name LIKE ? OR u.name LIKE ? OR s.name LIKE ?)
        ORDER BY t.name ASC
        LIMIT 8
    """, (user['id'], like_param, like_param, like_param))
    
    # 2. Search Subjects
    subjects = db_service.query("""
        SELECT s.id, s.name, sem.name as semester_name
        FROM subjects s
        JOIN semesters sem ON s.semester_id = sem.id
        WHERE sem.user_id = ? AND s.name LIKE ?
        ORDER BY s.name ASC
        LIMIT 4
    """, (user['id'], like_param))
    
    return jsonify({
        'topics': [dict(t) for t in (topics or [])],
        'subjects': [dict(s) for s in (subjects or [])]
    })


