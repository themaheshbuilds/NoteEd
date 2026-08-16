from flask import Blueprint, render_template, session, redirect, url_for, request
from services.db_service import db_service

chat_bp = Blueprint("chat", __name__)

def get_current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "email": session.get("email", ""),
        "full_name": session.get("full_name", "")
    }

@chat_bp.route("/chat")
def global_chat():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
        
    user_id = user["id"]
    
    # Group chat sessions by topic name
    # Fetch all sessions for this user, joining with topics to get topic name
    query = """
        SELECT cs.*, t.name as topic_name
        FROM chat_sessions cs
        JOIN topics t ON cs.topic_id = t.id
        WHERE cs.user_id = ?
        ORDER BY cs.created_at DESC
    """
    sessions_raw = db_service.query(query, (user_id,))
    
    # Group them by topic
    grouped_sessions = {}
    for s in sessions_raw:
        t_name = s["topic_name"]
        if t_name not in grouped_sessions:
            grouped_sessions[t_name] = []
        grouped_sessions[t_name].append(s)
        
    # Get active session
    active_session_id = request.args.get("session_id")
    chat_messages = []
    active_session = None
    
    if active_session_id:
        chat_messages = db_service.query("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (active_session_id,))
        active_session = db_service.query("SELECT * FROM chat_sessions WHERE id = ?", (active_session_id,), one=True)
    elif sessions_raw:
        # Load the most recent session
        active_session_id = sessions_raw[0]["id"]
        chat_messages = db_service.query("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (active_session_id,))
        active_session = sessions_raw[0]
        
    return render_template(
        "dashboard/chat.html",
        user=user,
        grouped_sessions=grouped_sessions,
        active_session_id=active_session_id,
        chat_messages=chat_messages,
        active_session=active_session
    )

