import os
import time
import secrets
from datetime import timedelta
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

# Warn if running on Vercel without a persistent database
if os.environ.get("VERCEL") and not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")):
    print("⚠️  WARNING: Running on Vercel without DATABASE_URL or POSTGRES_URL set!")
    print("⚠️  The app will use ephemeral /tmp/kiraak_study.db — all data WILL BE LOST on cold start.")
    print("⚠️  Please connect a Supabase or Neon PostgreSQL database in your Vercel project settings.")

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # ── Security: Enforce strong SECRET_KEY ──────────────────────────────
    configured_key = os.getenv("SECRET_KEY", "")
    if not configured_key or configured_key in ("supersecretkey", "supersecretkeyreplaceinproduction", "changeme"):
        if os.environ.get("VERCEL"):
            raise RuntimeError(
                "FATAL: SECRET_KEY is not set or is using a default value in production! "
                "Set a strong SECRET_KEY in your Vercel environment variables."
            )
        # Auto-generate a key for local development (warn loudly)
        configured_key = secrets.token_hex(32)
        print("⚠️  WARNING: Using auto-generated SECRET_KEY for local development.")
        print("⚠️  Set a strong SECRET_KEY in your .env file for production!")
    app.config["SECRET_KEY"] = configured_key

    # ── Session Security ─────────────────────────────────────────────────
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("VERCEL") is not None
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_NAME"] = "noted_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True          # [M4] Prevent JS access to session cookie
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)  # [M3] Session expires after 24h

    # ── Upload Security ──────────────────────────────────────────────────
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # [H5] 16MB max upload size
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

    @app.route("/favicon.ico")
    def serve_favicon():
        from flask import send_from_directory
        return send_from_directory(os.path.join(app.static_folder, "images"), "noteedhalf.png", mimetype="image/png")

    # [C4] REMOVED: /debug_session endpoint — leaked session data, user profile,
    # environment variable names, DB connection info, and cookies to anyone without auth.
    
    # ── [M1] Security Headers ────────────────────────────────────────────
    from services.security import add_security_headers

    @app.after_request
    def apply_security_headers(response):
        return add_security_headers(response)

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

