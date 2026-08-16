import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from services.db_service import db_service

planner_bp = Blueprint("planner", __name__)

def get_current_user_id():
    return session.get("user_id")

@planner_bp.route("/planner")
def view_planner():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
        
    events = db_service.query("SELECT * FROM planner_events WHERE user_id = ? ORDER BY start_time ASC", (user_id,))
    return render_template("planner/index.html", events=events)

@planner_bp.route("/planner/event/add", methods=["POST"])
def add_event():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    title = request.form.get("title")
    description = request.form.get("description", "")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    event_type = request.form.get("event_type", "daily") # daily, weekly, exam, revision
    
    if title and start_time:
        event_id = str(uuid.uuid4())
        db_service.execute(
            """INSERT INTO planner_events (id, user_id, title, description, start_time, end_time, event_type, is_completed) 
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (event_id, user_id, title, description, start_time, end_time, event_type)
        )
        flash("Event scheduled.", "success")
        
    return redirect(url_for("planner.view_planner"))

@planner_bp.route("/planner/event/<event_id>/toggle", methods=["POST"])
def toggle_event(event_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    event = db_service.query("SELECT * FROM planner_events WHERE id = ? AND user_id = ?", (event_id, user_id), one=True)
    if event:
        new_status = 0 if event["is_completed"] else 1
        db_service.execute("UPDATE planner_events SET is_completed = ? WHERE id = ?", (new_status, event_id))
        return jsonify({"success": True, "is_completed": bool(new_status)})
    return jsonify({"error": "Event not found"}), 404

