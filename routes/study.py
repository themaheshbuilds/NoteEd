import uuid
import os
import json
from datetime import datetime
# pyrefly: ignore [missing-import]
from flask import Blueprint, request, session, render_template, redirect, url_for, flash, jsonify
from services.db_service import db_service
from services.ai_service import ai_service
from services.task_service import task_service
from services.usage_service import usage_service

study_bp = Blueprint("study", __name__)

def get_current_user_id():
    return session.get("user_id")

@study_bp.route("/topic/<topic_id>/chat", methods=["POST"])
def chat_with_topic(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_message = request.form.get("message")
    image_base64 = request.form.get("image")
    
    if not user_message and not image_base64:
        return jsonify({"error": "Empty message"}), 400
        
    if not user_message and image_base64:
        user_message = "Please describe this image."

        
    if not usage_service.can_chat(user_id):
        return jsonify({"error": "You have reached your free daily chat limit. Please upgrade to Premium!"}), 403
        
    usage_service.increment_chat(user_id)
        
    # Build context from OCR texts and notes associated with topic
    files = db_service.query("SELECT ocr_text FROM files WHERE topic_id = ? AND ocr_text IS NOT NULL", (topic_id,))
    notes = db_service.query("SELECT content FROM notes WHERE topic_id = ?", (topic_id,))
    # Fetch topic details for subject context
    topic_data = db_service.query("""
        SELECT t.name as topic_name, u.name as unit_name, s.name as subject_name 
        FROM topics t 
        JOIN units u ON t.unit_id = u.id 
        JOIN subjects s ON u.subject_id = s.id 
        WHERE t.id = ?
    """, (topic_id,), one=True)
    
    # Fetch user's experience level
    profile = db_service.query("SELECT experience_level FROM profiles WHERE id = ?", (user_id,), one=True)
    experience_level = profile["experience_level"] if profile and profile["experience_level"] else "intermediate"
    
    context = ""
    if topic_data:
        context += f"Context:\n"
        context += f"Subject: {topic_data['subject_name']}\n"
        context += f"Unit: {topic_data['unit_name']}\n"
        context += f"Topic: {topic_data['topic_name']}\n"
        context += f"User's Experience Level: {experience_level}\n\n"

    for f in files:
        context += f"\nFile Excerpt:\n{f['ocr_text']}"
    for n in notes:
        context += f"\nNote Excerpt:\n{n['content']}"
        
    session_id = request.form.get("session_id")
    if not session_id:
        # Create a new session
        session_id = str(uuid.uuid4())
        # Truncate user message for a title (first 30 chars)
        title = user_message[:30] + ("..." if len(user_message) > 30 else "")
        db_service.execute(
            "INSERT INTO chat_sessions (id, topic_id, user_id, title) VALUES (?, ?, ?, ?)",
            (session_id, topic_id, user_id, title)
        )
        
    # Fetch existing chat history for context
    history_rows = db_service.query("SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    chat_history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
    
    # Save user message to DB
    user_msg_id = str(uuid.uuid4())
    db_service.execute(
        "INSERT INTO chat_messages (id, topic_id, session_id, user_id, role, content) VALUES (?, ?, ?, ?, ?, ?)",
        (user_msg_id, topic_id, session_id, user_id, "user", user_message)
    )
        
    ai_response = ai_service.generate_chat_response(
        user_message, 
        context, 
        chat_history=chat_history, 
        image_base64=image_base64,
        topic_id=topic_id
    )
    
    # Save AI response to DB
    ai_msg_id = str(uuid.uuid4())
    db_service.execute(
        "INSERT INTO chat_messages (id, topic_id, session_id, user_id, role, content) VALUES (?, ?, ?, ?, ?, ?)",
        (ai_msg_id, topic_id, session_id, user_id, "assistant", ai_response)
    )
    
    return jsonify({"response": ai_response, "session_id": session_id})

@study_bp.route("/topic/<topic_id>/chat-sessions", methods=["GET"])
def get_chat_sessions(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    sessions = db_service.query(
        "SELECT id, title, created_at, updated_at FROM chat_sessions WHERE user_id = ? AND topic_id = ? ORDER BY updated_at DESC",
        (user_id, topic_id)
    )
    return jsonify({"sessions": sessions})

@study_bp.route("/chat-session/<session_id>/messages", methods=["GET"])
def get_chat_messages(session_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    messages = db_service.query(
        "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)
    )
    return jsonify({"messages": messages})

@study_bp.route("/chat-session/<session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Verify ownership
    session = db_service.query("SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id), one=True)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    db_service.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    db_service.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return jsonify({"success": True})

@study_bp.route("/chat-session/<session_id>", methods=["PUT"])
def rename_chat_session(session_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Verify ownership
    session = db_service.query("SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id), one=True)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    data = request.json
    title = data.get("title")
    if not title:
        return jsonify({"error": "Title required"}), 400
    
    db_service.execute(
        "UPDATE chat_sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (title, session_id)
    )
    return jsonify({"success": True})

@study_bp.route("/topic/<topic_id>/explain", methods=["GET"])
def explain_topic_ai(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    level = request.args.get("level", "beginner")
    language = request.args.get("language", "English")
    
    topic = db_service.query("SELECT * FROM topics WHERE id = ?", (topic_id,), one=True)
    if not topic:
        flash("Topic not found", "error")
        return redirect(url_for("dashboard.index"))
        
    # Render immediately. The explanation will be loaded via AJAX.
    return render_template("study/explanation.html", topic=topic, level=level, language=language)

@study_bp.route("/api/topic/<topic_id>/explain", methods=["POST"])
def api_explain_topic(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    level = data.get("level", "beginner")
    language = data.get("language", "English")
    
    topic = db_service.query("SELECT * FROM topics WHERE id = ?", (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404
        
    explanation = ai_service.explain_topic(topic["name"], level, language)
    return jsonify({"explanation": explanation})

@study_bp.route("/topic/<topic_id>/math-level", methods=["GET", "POST"])
def math_level_prompt(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    topic = db_service.query("""
        SELECT t.*, s.name as subject_name 
        FROM topics t 
        JOIN units u ON t.unit_id = u.id 
        JOIN subjects s ON u.subject_id = s.id 
        WHERE t.id = ?
    """, (topic_id,), one=True)
    if not topic:
        flash("Topic not found", "error")
        return redirect(url_for("dashboard.index"))
        
    if request.method == "POST":
        level = request.form.get("math_level")
        if level in ["beginner", "intermediate", "advanced"]:
            db_service.execute("UPDATE profiles SET math_learning_level = ? WHERE id = ?", (level, user_id))
            # Auto-trigger generation by posting back to the generate route
            # Since we are returning a response, we can just redirect to a view that auto-submits, 
            # or call the generate_resources logic directly. Let's redirect to a temporary auto-submit page, 
            # or simply generate here to avoid complexity.
            # Easiest way in Flask is a 307 redirect so the POST method is preserved!
            return redirect(url_for("study.generate_resources", topic_id=topic_id), code=307)
        else:
            flash("Invalid learning level selected.", "error")
            
    return render_template("study/math_level.html", topic=topic)

@study_bp.route("/topic/<topic_id>/generate-resources", methods=["POST"])
def generate_resources(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    topic = db_service.query("""
        SELECT t.*, s.name as subject_name, u.name as unit_name, sem.name as semester_name
        FROM topics t 
        JOIN units u ON t.unit_id = u.id 
        JOIN subjects s ON u.subject_id = s.id 
        JOIN semesters sem ON s.semester_id = sem.id
        WHERE t.id = ?
    """, (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404
    
    # Get user's experience level and study purpose
    data = (request.get_json() or {}) if request.is_json else (request.form or {})
    study_purpose = data.get("study_purpose", "learning")
    db_service.execute("UPDATE profiles SET study_purpose = ? WHERE id = ?", (study_purpose, user_id))
    
    profile = db_service.query("SELECT experience_level FROM profiles WHERE id = ?", (user_id,), one=True)
    experience_level = profile["experience_level"] if profile and profile["experience_level"] else "intermediate"
    
    # Check for global caching across users
    cached_topic = db_service.query("""
        SELECT t.id 
        FROM topics t
        JOIN units u ON t.unit_id = u.id
        JOIN subjects s ON u.subject_id = s.id
        JOIN semesters sem ON s.semester_id = sem.id
        WHERE t.name = ? 
          AND u.name = ? 
          AND s.name = ? 
          AND sem.name = ?
          AND t.id != ?
          AND t.is_completed = 1
        LIMIT 1
    """, (topic['name'], topic['unit_name'], topic['subject_name'], topic['semester_name'], topic_id), one=True)
    
    if cached_topic:
        import uuid
        other_id = cached_topic['id']
        
        # Archive existing materials for current user's topic
        db_service.execute("UPDATE notes SET is_archived = 1 WHERE topic_id = ?", (topic_id,))
        db_service.execute("UPDATE flashcards SET is_archived = 1 WHERE topic_id = ?", (topic_id,))
        db_service.execute("UPDATE quizzes SET is_archived = 1 WHERE topic_id = ?", (topic_id,))

        # Copy notes
        notes = db_service.query("SELECT * FROM notes WHERE topic_id = ? AND is_archived = 0", (other_id,))
        for note in notes:
            db_service.execute("INSERT INTO notes (id, topic_id, title, content, is_ai_generated, is_archived) VALUES (?, ?, ?, ?, ?, ?)",
                               (str(uuid.uuid4()), topic_id, note['title'], note['content'], note['is_ai_generated'], 0))
                               
        # Copy flashcards
        cards = db_service.query("SELECT * FROM flashcards WHERE topic_id = ? AND is_archived = 0", (other_id,))
        for c in cards:
            db_service.execute("INSERT INTO flashcards (id, topic_id, question, answer, difficulty, box_number, is_archived) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (str(uuid.uuid4()), topic_id, c['question'], c['answer'], c['difficulty'], c['box_number'], 0))
                               
        # Copy quizzes
        quizzes = db_service.query("SELECT * FROM quizzes WHERE topic_id = ? AND is_archived = 0", (other_id,))
        for q in quizzes:
            db_service.execute("INSERT INTO quizzes (id, topic_id, title, quiz_data, is_archived) VALUES (?, ?, ?, ?, ?)",
                               (str(uuid.uuid4()), topic_id, q['title'], q['quiz_data'], 0))
                               
        # Mark current topic as completed
        db_service.execute("UPDATE topics SET is_completed = 1 WHERE id = ?", (topic_id,))
        
        return jsonify({"status": "completed"})
    
    if not usage_service.can_generate_deck(user_id):
        return jsonify({"error": "You have reached your free AI Study Deck generation limit. Please upgrade to Premium to generate more!"}), 403
    
    usage_service.increment_deck(user_id)
        
    # Cancel existing tasks
    db_service.execute("""
        UPDATE background_tasks 
        SET status = 'cancelled', message = 'Cancelled by user'
        WHERE user_id = ? AND task_type = 'generate_study_materials' AND status IN ('pending', 'processing')
    """, (user_id,))
    
    gen_options = {
        "style": data.get("style", "detailed_study"),
        "difficulty": data.get("difficulty", "beginner"),
        "length": data.get("length", "medium"),
        "toggles": data.get("toggles", {}),
        "source_text": data.get("source_text", ""),
        "language": data.get("language")
    }

    # Start async task with delayed archiving/deletion parameters
    task_id = task_service.start_generate_materials_task(
        user_id, 
        [(topic_id, topic["name"], topic["subject_name"], experience_level)], 
        run_sync=False,
        archive_old=True,
        delete_chats=True,
        gen_options=gen_options
    )
    
    return jsonify({"task_id": task_id, "status": "started"})


@study_bp.route("/topic/<topic_id>/regenerate-resources", methods=["POST"])
def regenerate_resources(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    topic = db_service.query("""
        SELECT t.*, s.name as subject_name, u.name as unit_name 
        FROM topics t 
        JOIN units u ON t.unit_id = u.id 
        JOIN subjects s ON u.subject_id = s.id 
        WHERE t.id = ?
    """, (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404
    
    # Get user's experience level and study purpose
    data = (request.get_json() or {}) if request.is_json else (request.form or {})
    study_purpose = data.get("study_purpose", "learning")
    db_service.execute("UPDATE profiles SET study_purpose = ? WHERE id = ?", (study_purpose, user_id))
    
    profile = db_service.query("SELECT experience_level FROM profiles WHERE id = ?", (user_id,), one=True)
    experience_level = profile["experience_level"] if profile and profile["experience_level"] else "intermediate"
    
    if not usage_service.can_generate_deck(user_id):
        return jsonify({"error": "You have reached your free AI Study Deck generation limit. Please upgrade to Premium to generate more!"}), 403
    
    usage_service.increment_deck(user_id)
        
    delete_chats = True
    
    # Cancel existing tasks
    db_service.execute("""
        UPDATE background_tasks 
        SET status = 'cancelled', message = 'Cancelled by user'
        WHERE user_id = ? AND task_type = 'generate_study_materials' AND status IN ('pending', 'processing')
    """, (user_id,))
    
    gen_options = {
        "style": data.get("style", "detailed_study"),
        "difficulty": data.get("difficulty", "beginner"),
        "length": data.get("length", "medium"),
        "toggles": data.get("toggles", {}),
        "source_text": data.get("source_text", ""),
        "language": data.get("language")
    }

    # Start async task with archiving/deletion parameters passed to background task
    task_id = task_service.start_generate_materials_task(
        user_id, 
        [(topic_id, topic["name"], topic["subject_name"], experience_level)], 
        run_sync=False,
        archive_old=True,
        delete_chats=delete_chats,
        gen_options=gen_options
    )
    
    return jsonify({"task_id": task_id, "status": "started"})


@study_bp.route("/api/topic/<topic_id>/regenerate-section", methods=["POST"])
def api_regenerate_section(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    topic = db_service.query("""
        SELECT t.*, s.name as subject_name, u.name as unit_name 
        FROM topics t 
        JOIN units u ON t.unit_id = u.id 
        JOIN subjects s ON u.subject_id = s.id 
        WHERE t.id = ?
    """, (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404

    data = (request.get_json() or {}) if request.is_json else (request.form or {})
    section_title = data.get("section_title", "Section")
    section_content = data.get("section_content", "")
    action = data.get("action", "more_detail")
    language = data.get("language")

    from services.ai_service import ai_service
    new_section_md = ai_service.regenerate_section_ai(
        section_title=section_title,
        section_content=section_content,
        topic_name=topic["name"],
        action=action,
        subject_name=topic["subject_name"],
        language=language
    )

    if not new_section_md:
        return jsonify({"error": "Failed to regenerate section. Please try again."}), 500

    return jsonify({"status": "success", "section_markdown": new_section_md})


@study_bp.route("/api/topic/<topic_id>/save-notes", methods=["POST"])
def api_save_notes(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    topic = db_service.query("SELECT * FROM topics WHERE id = ?", (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404

    data = (request.get_json() or {}) if request.is_json else (request.form or {})
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "Note content cannot be empty"}), 400

    import uuid
    # Find existing primary note
    existing_note = db_service.query(
        "SELECT id FROM notes WHERE topic_id = ? AND is_archived = 0 AND title LIKE '%AI Notes%' ORDER BY created_at ASC LIMIT 1",
        (topic_id,), one=True
    )

    if existing_note:
        db_service.execute(
            "UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (content, existing_note["id"])
        )
    else:
        note_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO notes (id, topic_id, title, content, is_ai_generated, is_archived) VALUES (?, ?, ?, ?, 1, 0)",
            (note_id, topic_id, f"AI Notes: {topic['name']}", content)
        )

    return jsonify({"status": "success", "message": "Notes saved successfully!"})


@study_bp.route("/api/topic/<topic_id>/generation-status/<task_id>", methods=["GET"])
def get_generation_status(topic_id, task_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    task = db_service.query("SELECT status, message, total_items, completed_items FROM background_tasks WHERE id = ? AND user_id = ?", (task_id, user_id), one=True)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    return jsonify({
        "status": task["status"],
        "message": task["message"],
        "total_items": task["total_items"],
        "completed_items": task["completed_items"]
    })

from datetime import datetime, timezone, timedelta

def increment_daily_streak(user_id):
    from services.db_service import db_service
    profile = db_service.query("SELECT last_active, study_streak FROM profiles WHERE id = ?", (user_id,), one=True)
    if not profile:
        return
        
    # IST is UTC+5:30 permanently (no DST)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    today_ist = now_ist.date()
    
    current_streak = profile["study_streak"] if profile["study_streak"] is not None else 0
    last_active_str = profile["last_active"]
    
    needs_update = False
    
    if last_active_str:
        try:
            if isinstance(last_active_str, datetime):
                last_dt = last_active_str
            else:
                clean_iso = last_active_str[:19]
                last_dt = datetime.fromisoformat(clean_iso)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            last_dt_ist = last_dt.astimezone(ist).date()
            
            delta = (today_ist - last_dt_ist).days
            
            if delta == 1:
                current_streak += 1
                needs_update = True
            elif delta > 1:
                current_streak = 1
                needs_update = True
            elif delta == 0:
                needs_update = True
        except Exception:
            current_streak = 1
            needs_update = True
    else:
        current_streak = 1
        needs_update = True
        
    if needs_update:
        db_service.execute(
            "UPDATE profiles SET study_streak = ?, last_active = ? WHERE id = ?",
            (current_streak, now_ist.isoformat(), user_id)
        )


@study_bp.route("/topic/<topic_id>/mini-quiz", methods=["POST"])
def mini_quiz(topic_id):
    from services.db_service import db_service
    from services.ai_service import ai_service
    from flask import session, jsonify, request
    
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
        
    topic = db_service.query("SELECT * FROM topics WHERE id = ?", (topic_id,), one=True)
    if not topic:
        return jsonify({"error": "Topic not found"}), 404
        
    try:
        data = request.get_json(silent=True) or {}
        context_text = data.get("context", "")
        
        profile = db_service.query("SELECT api_keys, ai_platform, is_premium, email FROM profiles WHERE id = ?", (user_id,), one=True)
        if profile:
            profile = dict(profile)
        key = profile["api_keys"] if profile else None
        base_url = None
        chat_model = None
        
        is_premium = bool(dict(profile).get("is_premium")) if profile else False
        # [M7] Admin email from environment variable
        admin_email = os.getenv("ADMIN_EMAIL", "")
        is_admin_email = admin_email and profile and profile["email"] == admin_email
        
        if key:
            # User has their own key, infer platform and model
            if key.startswith("sk-or-"):
                base_url = "https://openrouter.ai/api/v1"
                chat_model = "google/gemini-2.0-flash-exp:free"
            elif key.startswith("nvapi-"):
                base_url = "https://integrate.api.nvidia.com/v1"
                chat_model = "meta/llama-3.1-8b-instruct"
            elif key.startswith("AIza") or key.startswith("AQ."):
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                chat_model = "gemini-2.5-flash"
            elif key.startswith("gsk_"):
                base_url = "https://api.groq.com/openai/v1"
                chat_model = "llama-3.3-70b-versatile"
            elif key.startswith("sk-"):
                base_url = "https://api.openai.com/v1"
                chat_model = "gpt-4o-mini"
            else:
                base_url = "https://integrate.api.nvidia.com/v1"
                chat_model = "meta/llama-3.1-8b-instruct"
        else:
            if is_premium or is_admin_email:
                key, base_url, chat_model, _ = ai_service._get_config()
            else:
                return jsonify({"error": "Upgrade to Premium to generate mini quizzes."}), 403
                
        import json
        
        if context_text:
            prompt_topic = f"the specific sub-topics '{context_text}' from the overall topic '{topic['name']}'"
        else:
            prompt_topic = f"the topic '{topic['name']}'"
            
        prompt = f'''Generate exactly ONE multiple choice question based on {prompt_topic}.
Return ONLY valid JSON in this exact format, with no markdown code blocks or other text.
Do NOT include any newlines or unescaped quotes inside the JSON string values. Keep all text values on a single line.
{{
  "question": "The question text here",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correct_index": 0,
  "explanation": "Why this is correct."
}}
'''
        
        # Leverage ai_service's built-in key rotation, retry logic, and JSON parsing
        response_data = ai_service._generate_partial(
            prompt=prompt,
            max_tokens=500,
            key=key,
            base_url=base_url,
            chat_model=chat_model
        )
        
        if response_data and isinstance(response_data, dict) and "question" in response_data:
            return jsonify(response_data)
            
        # Fallback if AI fails
        fallback = {
            "question": f"What is a key concept in {context_text or topic['name']}?",
            "options": ["Read the text above carefully", "Skip the section", "Guess randomly", "None of the above"],
            "correct_index": 0,
            "explanation": "Reviewing the material is always the best approach!"
        }
        return jsonify(fallback)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Helper to Get Current User ID ───────────────────────────────────────────────
@study_bp.route("/topic/<topic_id>/archive/<item_type>/<item_id>/delete", methods=["POST"])
def delete_archived_item(topic_id, item_type, item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # [H4] Use explicit branches instead of f-string table name to prevent SQL injection risk
    if item_type == "note":
        db_service.execute("DELETE FROM notes WHERE id = ? AND topic_id = ? AND is_archived = 1", (item_id, topic_id))
    elif item_type == "flashcard":
        db_service.execute("DELETE FROM flashcards WHERE id = ? AND topic_id = ? AND is_archived = 1", (item_id, topic_id))
    elif item_type == "quiz":
        db_service.execute("DELETE FROM quizzes WHERE id = ? AND topic_id = ? AND is_archived = 1", (item_id, topic_id))
    else:
        return jsonify({"error": "Invalid type"}), 400
    return jsonify({"success": True})

@study_bp.route("/syllabus/paste", methods=["GET", "POST"])
@study_bp.route("/paste-syllabus", methods=["GET", "POST"])
@study_bp.route("/syllabus", methods=["GET", "POST"])
def paste_syllabus():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    semesters = db_service.query("SELECT * FROM semesters WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    
    if request.method == "POST":
        semester_id = request.form.get("semester_id")
        syllabus_text = request.form.get("syllabus_text")
        
        if not semester_id or not syllabus_text:
            flash("Semester and syllabus text are required.", "error")
            return redirect(url_for("study.paste_syllabus"))
            
        parsed = ai_service.parse_syllabus(syllabus_text)
        
        # Populate DB automatically
        for sub in parsed.get("subjects", []):
            sub_id = str(uuid.uuid4())
            db_service.execute(
                "INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)",
                (sub_id, semester_id, sub["name"], sub.get("code", ""))
            )
            
            for unit in sub.get("units", []):
                unit_id = str(uuid.uuid4())
                db_service.execute(
                    "INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)",
                    (unit_id, sub_id, unit["name"], unit.get("number", 1))
                )
                
                for idx, topic_name in enumerate(unit.get("topics", [])):
                    topic_id = str(uuid.uuid4())
                    db_service.execute(
                        "INSERT INTO topics (id, unit_id, name, order_index, is_completed) VALUES (?, ?, ?, ?, 0)",
                        (topic_id, unit_id, topic_name, idx + 1)
                    )
                    
        flash("Syllabus processed. Created subjects, units, and topics successfully.", "success")
        return redirect(url_for("dashboard.index"))
        
    return render_template("study/syllabus.html", semesters=semesters)

@study_bp.route("/quiz/<quiz_id>", methods=["GET", "POST"])
def play_quiz(quiz_id):
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    quiz = db_service.query("SELECT * FROM quizzes WHERE id = ?", (quiz_id,), one=True)
    if not quiz:
        flash("Quiz not found", "error")
        return redirect(url_for("dashboard.index"))
        
    quiz_data = json.loads(quiz["quiz_data"])
    
    if request.method == "POST":
        # Calculate scores
        user_answers = request.form.to_dict()
        score = 0
        total = len(quiz_data)
        
        for idx, question in enumerate(quiz_data):
            submitted = user_answers.get(f"q_{idx}")
            correct_idx = question.get("correct_index")
            if correct_idx is None:
                correct_idx = question.get("correctIndex", question.get("answer", 0))
            try:
                correct_idx = int(correct_idx)
            except (ValueError, TypeError):
                correct_idx = 0

            if submitted is not None and int(submitted) == correct_idx:
                score += 1
                
        accuracy = (score / total) * 100 if total > 0 else 0
        result_id = str(uuid.uuid4())
        
        db_service.execute(
            """INSERT INTO quiz_results (id, quiz_id, user_id, score, total_questions, accuracy) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (result_id, quiz_id, user_id, score, total, accuracy)
        )
        
        increment_daily_streak(user_id)
        
        return render_template("study/quiz_result.html", quiz=quiz, quiz_data=quiz_data, score=score, total=total, accuracy=accuracy)
        
    return render_template("study/quiz.html", quiz=quiz, quiz_data=quiz_data)

@study_bp.route("/flashcards/review/<topic_id>")
def review_flashcards(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    topic = db_service.query("SELECT * FROM topics WHERE id = ?", (topic_id,), one=True)
    flashcards_rows = db_service.query("SELECT * FROM flashcards WHERE topic_id = ?", (topic_id,))
    flashcards = [dict(row) for row in flashcards_rows]
    
    increment_daily_streak(user_id)
    
    return render_template("study/flashcards.html", topic=topic, flashcards=flashcards)

@study_bp.route("/session/track", methods=["POST"])
def track_study_session():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    topic_id = request.form.get("topic_id")
    duration = request.form.get("duration") # in minutes
    
    if topic_id and duration:
        session_id = str(uuid.uuid4())
        db_service.execute(
            """INSERT INTO study_sessions (id, user_id, topic_id, start_time, duration_minutes) 
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, user_id, topic_id, datetime.now().isoformat(), int(duration))
        )
        
        # Increment study streak using the IST daily logic
        increment_daily_streak(user_id)
        return jsonify({"success": True})
    return jsonify({"error": "Invalid payload"}), 400

# ── AI Natural Language Command ──────────────────────────────────────────
@study_bp.route("/ai/command", methods=["POST"])
def ai_command():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "No command provided"}), 400

    # Parse the natural language command via AI service
    plan = ai_service.process_natural_language_command(command)
    action = plan.get("action")

    if action == "create_study_structure":
        if not usage_service.can_use_planner(user_id):
            return jsonify({"success": False, "message": "You have reached your free AI Planner limit. Please upgrade to Premium!"})
        usage_service.increment_planner(user_id)

        # ── Create or find semester ──────────────────────────────────
        sem_name = plan.get("semester", {}).get("name", "Semester 1")
        semester = db_service.query(
            "SELECT * FROM semesters WHERE user_id = ? AND name = ?",
            (user_id, sem_name), one=True
        )
        if semester:
            sem_id = semester["id"]
        else:
            sem_id = str(uuid.uuid4())
            db_service.execute(
                "INSERT INTO semesters (id, user_id, name) VALUES (?, ?, ?)",
                (sem_id, user_id, sem_name)
            )

        focus_topics = [ft.lower() for ft in plan.get("focus_topics", [])]
        generate_materials = plan.get("generate_materials", False)
        created_topic_ids = []

        for sub in plan.get("subjects", []):
            existing_sub = db_service.query(
                "SELECT * FROM subjects WHERE semester_id = ? AND LOWER(name) = ?",
                (sem_id, sub["name"].lower()), one=True
            )
            if existing_sub:
                sub_id = existing_sub["id"]
            else:
                sub_id = str(uuid.uuid4())
                db_service.execute(
                    "INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)",
                    (sub_id, sem_id, sub["name"], sub.get("code", ""))
                )

            for unit in sub.get("units", []):
                existing_unit = db_service.query(
                    "SELECT * FROM units WHERE subject_id = ? AND LOWER(name) = ?",
                    (sub_id, unit["name"].lower()), one=True
                )
                if existing_unit:
                    unit_id = existing_unit["id"]
                else:
                    unit_id = str(uuid.uuid4())
                    db_service.execute(
                        "INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)",
                        (unit_id, sub_id, unit["name"], unit.get("number", 1))
                    )

                for idx, topic_name in enumerate(unit.get("topics", [])):
                    topic_id = str(uuid.uuid4())
                    db_service.execute(
                        "INSERT INTO topics (id, unit_id, name, order_index, is_completed) VALUES (?, ?, ?, ?, 0)",
                        (topic_id, unit_id, topic_name, idx + 1)
                    )
                    created_topic_ids.append((topic_id, topic_name, sub["name"]))

        # ── Generate study materials ─────────────────────────────────
        if generate_materials:
            topics_to_generate = []
            if focus_topics:
                # Only generate for focus topics
                for tid, tname, sname in created_topic_ids:
                    if any(ft in tname.lower() for ft in focus_topics):
                        topics_to_generate.append((tid, tname, sname))
            else:
                # Generate for ALL topics
                topics_to_generate = created_topic_ids

            if topics_to_generate:
                task_id = task_service.start_generate_materials_task(user_id, topics_to_generate)
                return jsonify({
                    "success": True, 
                    "message": f"Created {len(plan.get('subjects', []))} subjects. Generating materials for {len(topics_to_generate)} topics in the background.", 
                    "redirect": f"/semester/{sem_id}",
                    "task_id": task_id
                })

        return jsonify({
            "success": True,
            "message": f"Created study structure for {sem_name} with {len(created_topic_ids)} topics.",
            "redirect": f"/semester/{sem_id}"
        })

    return jsonify({"error": "Unknown action", "plan": plan}), 400


# ── Search ───────────────────────────────────────────────────────────────
@study_bp.route("/search")
def search():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))

    q = request.args.get("q", "").strip()
    results = {"subjects": [], "topics": [], "notes": [], "files": []}

    if q:
        like_q = f"%{q}%"

        results["subjects"] = db_service.query(
            """SELECT s.*, sem.name as semester_name FROM subjects s
               JOIN semesters sem ON s.semester_id = sem.id
               WHERE sem.user_id = ? AND s.name LIKE ?""",
            (user_id, like_q)
        )

        results["topics"] = db_service.query(
            """SELECT t.*, u.name as unit_name, s.name as subject_name
               FROM topics t
               JOIN units u ON t.unit_id = u.id
               JOIN subjects s ON u.subject_id = s.id
               JOIN semesters sem ON s.semester_id = sem.id
               WHERE sem.user_id = ? AND t.name LIKE ?""",
            (user_id, like_q)
        )

        results["notes"] = db_service.query(
            """SELECT n.*, t.name as topic_name
               FROM notes n
               JOIN topics t ON n.topic_id = t.id
               JOIN units u ON t.unit_id = u.id
               JOIN subjects s ON u.subject_id = s.id
               JOIN semesters sem ON s.semester_id = sem.id
               WHERE sem.user_id = ? AND (n.title LIKE ? OR n.content LIKE ?)""",
            (user_id, like_q, like_q)
        )

        results["files"] = db_service.query(
            """SELECT f.*, t.name as topic_name
               FROM files f
               JOIN topics t ON f.topic_id = t.id
               JOIN units u ON t.unit_id = u.id
               JOIN subjects s ON u.subject_id = s.id
               JOIN semesters sem ON s.semester_id = sem.id
               WHERE sem.user_id = ? AND (f.name LIKE ? OR f.ocr_text LIKE ?)""",
            (user_id, like_q, like_q)
        )

    return render_template("study/search.html", query=q, results=results)


# ── Analytics ────────────────────────────────────────────────────────────
@study_bp.route("/analytics")
def analytics():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))

    # Total study sessions & hours
    session_stats = db_service.query(
        """SELECT COUNT(*) as total_sessions,
                  COALESCE(SUM(duration_minutes), 0) as total_minutes
           FROM study_sessions WHERE user_id = ?""",
        (user_id,), one=True
    )
    total_sessions = session_stats["total_sessions"] if session_stats else 0
    total_hours = round((session_stats["total_minutes"] if session_stats else 0) / 60, 1)

    # Topics completed vs total
    topic_stats = db_service.query(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN t.is_completed = 1 THEN 1 ELSE 0 END) as completed
           FROM topics t
           JOIN units u ON t.unit_id = u.id
           JOIN subjects s ON u.subject_id = s.id
           JOIN semesters sem ON s.semester_id = sem.id
           WHERE sem.user_id = ?""",
        (user_id,), one=True
    )
    topics_total = topic_stats["total"] if topic_stats else 0
    topics_completed = topic_stats["completed"] if topic_stats else 0

    # Quiz average accuracy
    quiz_stats = db_service.query(
        "SELECT COALESCE(AVG(accuracy), 0) as avg_accuracy FROM quiz_results WHERE user_id = ?",
        (user_id,), one=True
    )
    avg_accuracy = round(quiz_stats["avg_accuracy"], 1) if quiz_stats else 0

    # Study streak from profile
    profile = db_service.query(
        "SELECT study_streak FROM profiles WHERE id = ?",
        (user_id,), one=True
    )
    study_streak = profile["study_streak"] if profile else 0

    # Recent quiz results
    recent_quizzes = db_service.query(
        """SELECT qr.*, q.title as quiz_title
           FROM quiz_results qr
           JOIN quizzes q ON qr.quiz_id = q.id
           WHERE qr.user_id = ?
           ORDER BY qr.completed_at DESC LIMIT 10""",
        (user_id,)
    )

    return render_template(
        "study/analytics.html",
        total_sessions=total_sessions,
        total_hours=total_hours,
        total_topics=topics_total,
        completed_topics=topics_completed,
        avg_accuracy=avg_accuracy,
        study_streak=study_streak,
        recent_results=recent_quizzes
    )


# ── Bookmark Toggle ──────────────────────────────────────────────────────
@study_bp.route("/topic/<topic_id>/bookmark", methods=["POST"])
def toggle_bookmark(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    existing = db_service.query(
        "SELECT id FROM bookmarks WHERE user_id = ? AND topic_id = ?",
        (user_id, topic_id), one=True
    )

    if existing:
        db_service.execute("DELETE FROM bookmarks WHERE id = ?", (existing["id"],))
        return jsonify({"success": True, "bookmarked": False, "message": "Bookmark removed"})
    else:
        bookmark_id = str(uuid.uuid4())
        db_service.execute(
            "INSERT INTO bookmarks (id, user_id, topic_id) VALUES (?, ?, ?)",
            (bookmark_id, user_id, topic_id)
        )
        return jsonify({"success": True, "bookmarked": True, "message": "Bookmark added"})

@study_bp.route("/topic/<topic_id>/complete", methods=["POST"])
def toggle_complete(topic_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    topic = db_service.query("SELECT is_completed FROM topics WHERE id = ?", (topic_id,), one=True)
    if not topic:
        return jsonify({"success": False, "error": "Topic not found"}), 404

    is_completed = bool(topic["is_completed"])
    new_status = 0 if is_completed else 1

    db_service.execute(
        "UPDATE topics SET is_completed = ? WHERE id = ?",
        (new_status, topic_id)
    )
    
    return jsonify({
        "success": True, 
        "is_completed": bool(new_status), 
        "message": "Topic marked as completed" if new_status else "Topic marked as incomplete"
    })


# ── API Background Tasks ──────────────────────────────────────────────────
@study_bp.route("/api/tasks/active", methods=["GET"])
def get_active_tasks():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify([])

    try:
        # Fetch active tasks (pending or processing)
        # Also fetch completed/failed tasks from the last 10 seconds to show brief completion toast
        if db_service.use_postgres:
            tasks = db_service.query("""
                SELECT * FROM background_tasks 
                WHERE user_id = ? 
                AND (status IN ('pending', 'processing') 
                     OR (status IN ('completed', 'failed') AND updated_at >= NOW() - INTERVAL '10 seconds'))
                ORDER BY created_at DESC
            """, (user_id,))
        else:
            tasks = db_service.query("""
                SELECT * FROM background_tasks 
                WHERE user_id = ? 
                AND (status IN ('pending', 'processing') 
                     OR (status IN ('completed', 'failed') AND strftime('%s', 'now') - strftime('%s', updated_at) < 10))
                ORDER BY created_at DESC
            """, (user_id,))
        
        return jsonify([dict(t) for t in tasks])
    except Exception as e:
        print(f"Error fetching active tasks: {e}")
        return jsonify([])


@study_bp.route("/api/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Mark task as completed so UI immediately stops waiting and saves generated items
        db_service.execute("""
            UPDATE background_tasks 
            SET status = 'completed', message = 'Generation stopped by user. Notes and generated items saved!', updated_at = CURRENT_TIMESTAMP 
            WHERE id = ? AND user_id = ?
        """, (task_id, user_id))
        return jsonify({"success": True, "message": "Task stopped successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


