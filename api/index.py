import os
import time
from flask import Flask
from dotenv import load_dotenv

# Set default timezone to IST (Hyderabad/Kolkata)
os.environ['TZ'] = 'Asia/Kolkata'
try:
    if hasattr(time, 'tzset'):
        time.tzset()
except Exception:
    pass

# Load environment variables
load_dotenv()

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "supersecretkey")
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    
    # Configure Uploads
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "../uploads")
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    except OSError:
        app.config["UPLOAD_FOLDER"] = "/tmp/uploads"
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    
    # Register blueprints
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.files import files_bp
    from routes.planner import planner_bp
    from routes.study import study_bp
    from routes.billing import billing_bp
    from routes.chat import chat_bp
    from routes.legal import legal_bp
    from routes.admin import admin_bp
    from routes.tests import tests_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(legal_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(study_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(tests_bp)
    
    @app.route("/sw.js")
    def serve_sw():
        from flask import send_from_directory
        return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")

    @app.route("/manifest.json")
    def serve_manifest():
        from flask import send_from_directory
        return send_from_directory(app.static_folder, "manifest.json", mimetype="application/manifest+json")

    @app.route("/debug_session")
    def debug_session():
        from flask import session, request
        import os
        from services.db_service import db_service
        profile = None
        if session.get("user_id"):
            profile = db_service.query("SELECT * FROM profiles WHERE id = ?", (session["user_id"],), one=True)
            
        return {
            "session_data": dict(session),
            "profile_in_db": dict(profile) if profile else None,
            "env_keys": list(os.environ.keys()),
            "use_postgres_flag": getattr(db_service, "use_postgres", False),
            "db_url_starts_with": str(getattr(db_service, "database_url", ""))[:15],
            "cookies": getattr(request, "cookies", {})
        }
    
    # Streak updater moved to specific actions in routes/study.py
    
    # Simple global context processor for user sessions
    @app.context_processor
    def inject_user():
        from flask import session
        from services.ai_service import ai_service
        is_invalid = session.get("api_key_invalid", False)
        if "user_id" in session:
            from services.usage_service import usage_service
            try:
                tier = usage_service.get_tier(session["user_id"])
            except Exception:
                tier = "free"
            user_data = {
                "id": session["user_id"],
                "email": session.get("email"),
                "full_name": session.get("full_name"),
                "subscription_tier": tier
            }
        else:
            user_data = None
            
        return {
            "current_user": user_data,
            "has_api_key": bool(ai_service.api_key) and not is_invalid,
            "api_key_invalid": is_invalid
        }

    return app

app = create_app()

# Temporarily disabled to save API keys for users
# if not os.environ.get("VERCEL_URL") and os.environ.get("WERKZEUG_RUN_MAIN") == "true":
#     import threading
#     from services.question_bank_service import question_bank_service
#     def run_replenishment():
#         import time
#         while True:
#             question_bank_service.replenish_bank()
#             time.sleep(60 * 60 * 6) # Every 6 hours
#             
#     thread = threading.Thread(target=run_replenishment, daemon=True)
#     thread.start()
