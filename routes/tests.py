import uuid
import json
import time
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from services.db_service import db_service
from routes.dashboard import get_current_user

tests_bp = Blueprint("tests", __name__)

@tests_bp.route("/test/<test_id>", methods=["GET"])
def view_test(test_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    test = db_service.query("SELECT * FROM weekly_tests WHERE id = ? AND user_id = ?", (test_id, user["id"]), one=True)
    if not test:
        flash("Test not found.", "error")
        return redirect(url_for("dashboard.index"))
        
    questions = json.loads(test["test_data"])
    
    # Check if already completed
    if test["status"] == "completed":
        leaderboard_entry = db_service.query("SELECT * FROM leaderboard WHERE user_id = ? AND test_id = ?", (user["id"], test_id), one=True)
        # Fetch user's answers to show what they got right/wrong
        user_answers = db_service.query("SELECT * FROM weekly_test_answers WHERE test_id = ? ORDER BY question_index ASC", (test_id,))
        
        # Create a dict mapping question index to user answer object
        ans_dict = {ans["question_index"]: ans for ans in user_answers}
        
        return render_template(
            "dashboard/take_test.html", 
            test=test, 
            questions=questions, 
            leaderboard=leaderboard_entry, 
            is_completed=True,
            user_answers=ans_dict
        )
        
    # Start timer (store in session or just use form submission time, let's use created_at roughly, or pass start_time to template)
    start_time = int(time.time())
    
    return render_template("dashboard/take_test.html", test=test, questions=questions, is_completed=False, start_time=start_time)


@tests_bp.route("/test/<test_id>/submit_all", methods=["POST"])
def submit_all_answers(test_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    test = db_service.query("SELECT * FROM weekly_tests WHERE id = ? AND user_id = ?", (test_id, user["id"]), one=True)
    if not test or test["status"] == "completed":
        flash("Test not found or already completed.", "error")
        return redirect(url_for("dashboard.index"))
        
    questions = json.loads(test["test_data"])
    
    start_time = int(request.form.get("start_time", int(time.time())))
    time_taken_seconds = int(time.time()) - start_time
    
    correct_count = 0
    wrong_count = 0
    
    # Store user answers in weekly_test_answers for review
    for i, q in enumerate(questions):
        user_choice = request.form.get(f"q_{i}", "")
        correct_answer = q.get("correct_answer", "")
        
        is_correct = False
        if user_choice.strip() and user_choice.strip().lower() == correct_answer.strip().lower():
            is_correct = True
            correct_count += 1
        else:
            wrong_count += 1
            
        score_for_q = 5 if is_correct else 0
        
        ans_id = str(uuid.uuid4())
        db_service.execute(
            """INSERT INTO weekly_test_answers (id, test_id, question_index, user_answer, score, feedback)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ans_id, test_id, i, user_choice, score_for_q, q.get("explanation", ""))
        )
        
    total_score = correct_count * 5  # 5 marks per question
    percentage = (correct_count / len(questions)) * 100 if len(questions) > 0 else 0
    
    # Mark test as completed
    db_service.execute("UPDATE weekly_tests SET status = 'completed', score = ? WHERE id = ?", (total_score, test_id))
    
    # Calculate week number roughly
    week_number = datetime.now().isocalendar()[1]
    
    # Save to leaderboard
    lid = str(uuid.uuid4())
    # Ensure test_id exists in schema
    try:
        db_service.execute("ALTER TABLE leaderboard ADD COLUMN test_id TEXT")
    except:
        pass # Already exists
        
    db_service.execute(
        """INSERT INTO leaderboard (id, user_id, test_id, score, percentage, correct_answers, wrong_answers, time_taken_seconds, week_number)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (lid, user["id"], test_id, total_score, percentage, correct_count, wrong_count, time_taken_seconds, week_number)
    )
    
    flash(f"Test completed! You scored {total_score}/100.", "success")
    return redirect(url_for("tests.view_test", test_id=test_id))

