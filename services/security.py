"""
NoteEd Security Utilities
Centralized security helpers for authentication, input validation,
file upload safety, and rate limiting.
"""

import os
import time
import hashlib
import secrets
import functools
from collections import defaultdict
from threading import Lock
from flask import session, redirect, url_for, request, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash


# ─── Admin Authentication ────────────────────────────────────────────────────

def require_admin(f):
    """Decorator: redirect to admin login if not authenticated as superadmin."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_superadmin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated_function


def verify_admin_credentials(username, password):
    """Verify admin credentials against environment variables with hashed comparison."""
    expected_user = os.getenv("ADMIN_USERNAME", "")
    expected_hash = os.getenv("ADMIN_PASSWORD_HASH", "")

    if not expected_user or not expected_hash:
        # Fallback: if env vars not set, deny access entirely in production
        print("⚠️  ADMIN_USERNAME or ADMIN_PASSWORD_HASH not set in environment!")
        return False

    if not secrets.compare_digest(username, expected_user):
        return False

    return check_password_hash(expected_hash, password)


def generate_admin_password_hash(password):
    """Utility to generate a hash for ADMIN_PASSWORD_HASH env var."""
    return generate_password_hash(password)


# ─── Rate Limiting (In-Memory) ───────────────────────────────────────────────

class RateLimiter:
    """Simple in-memory rate limiter keyed by IP address.
    
    Thread-safe. Suitable for single-server deployments.
    For multi-server, use Redis-backed Flask-Limiter instead.
    """

    def __init__(self):
        self._attempts = defaultdict(list)  # key -> [timestamps]
        self._lock = Lock()

    def is_rate_limited(self, key, max_attempts, window_seconds):
        """Check if the key has exceeded max_attempts within window_seconds.
        
        Returns True if rate-limited, False if allowed.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Prune old entries
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]

            if len(self._attempts[key]) >= max_attempts:
                return True

            self._attempts[key].append(now)
            return False

    def get_remaining(self, key, max_attempts, window_seconds):
        """Get remaining attempts for a key."""
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
            return max(0, max_attempts - len(self._attempts[key]))

    def reset(self, key):
        """Reset rate limit counter for a key."""
        with self._lock:
            self._attempts.pop(key, None)


# Global rate limiters for different endpoints
auth_limiter = RateLimiter()
otp_limiter = RateLimiter()
api_limiter = RateLimiter()


def check_auth_rate_limit(identifier=None):
    """Check rate limit for authentication endpoints.
    
    Returns (is_limited, remaining_attempts) tuple.
    Max 10 attempts per 15 minutes per IP.
    """
    key = identifier or request.remote_addr or "unknown"
    max_attempts = 10
    window = 900  # 15 minutes

    is_limited = auth_limiter.is_rate_limited(key, max_attempts, window)
    remaining = auth_limiter.get_remaining(key, max_attempts, window)
    return is_limited, remaining


def check_otp_rate_limit(email):
    """Check rate limit for OTP verification.
    
    Max 5 attempts per 15 minutes per email.
    """
    key = f"otp:{email}"
    max_attempts = 5
    window = 900  # 15 minutes

    is_limited = otp_limiter.is_rate_limited(key, max_attempts, window)
    remaining = otp_limiter.get_remaining(key, max_attempts, window)
    return is_limited, remaining


def check_password_reset_rate_limit(email_or_ip=None):
    """Check rate limit for password reset requests.
    
    Max 3 requests per hour per email/IP.
    """
    key = f"reset:{email_or_ip or request.remote_addr}"
    max_attempts = 3
    window = 3600  # 1 hour

    is_limited = auth_limiter.is_rate_limited(key, max_attempts, window)
    remaining = auth_limiter.get_remaining(key, max_attempts, window)
    return is_limited, remaining


# ─── File Upload Validation ──────────────────────────────────────────────────

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "pptx", "txt"}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}

# Magic bytes for common image formats
IMAGE_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpg',      # JPEG
    b'\x89PNG': 'png',            # PNG
    b'GIF87a': 'gif',             # GIF87a
    b'GIF89a': 'gif',             # GIF89a
    b'RIFF': 'webp',             # WebP (starts with RIFF)
}

PDF_MAGIC = b'%PDF'


def get_file_extension(filename):
    """Safely extract file extension from filename."""
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def validate_upload_file(file_storage, allowed_extensions=None, max_size_bytes=None):
    """Validate an uploaded file for safety.
    
    Args:
        file_storage: Flask FileStorage object
        allowed_extensions: Set of allowed extensions (default: ALLOWED_UPLOAD_EXTENSIONS)
        max_size_bytes: Maximum file size in bytes (default: 16MB)
    
    Returns:
        (is_valid, error_message) tuple
    """
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_UPLOAD_EXTENSIONS
    if max_size_bytes is None:
        max_size_bytes = 16 * 1024 * 1024  # 16MB

    if not file_storage or not file_storage.filename:
        return False, "No file selected."

    ext = get_file_extension(file_storage.filename)
    if ext not in allowed_extensions:
        return False, f"File type '.{ext}' is not allowed. Allowed: {', '.join(sorted(allowed_extensions))}"

    # Check file size by reading content length
    file_storage.seek(0, 2)  # Seek to end
    size = file_storage.tell()
    file_storage.seek(0)  # Reset to beginning

    if size > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        return False, f"File too large. Maximum size is {max_mb:.0f}MB."

    if size == 0:
        return False, "File is empty."

    # Validate magic bytes for image files
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        header = file_storage.read(8)
        file_storage.seek(0)

        is_valid_image = False
        for magic, _ in IMAGE_MAGIC_BYTES.items():
            if header.startswith(magic):
                is_valid_image = True
                break

        if not is_valid_image:
            return False, "File content doesn't match its extension. Possible file type spoofing."

    # Validate magic bytes for PDF files
    if ext == 'pdf':
        header = file_storage.read(4)
        file_storage.seek(0)
        if not header.startswith(PDF_MAGIC):
            return False, "File content doesn't match PDF format."

    return True, None


def validate_path_within_directory(file_path, allowed_directory):
    """Ensure a file path resolves within an allowed directory.
    
    Prevents path traversal attacks (e.g., ../../etc/passwd).
    """
    abs_path = os.path.realpath(os.path.abspath(file_path))
    abs_allowed = os.path.realpath(os.path.abspath(allowed_directory))

    return abs_path.startswith(abs_allowed + os.sep) or abs_path == abs_allowed


# ─── Input Sanitization ─────────────────────────────────────────────────────

def sanitize_string(value, max_length=500, strip=True):
    """Sanitize a string input: trim whitespace and enforce max length.
    
    Returns sanitized string or None if empty.
    """
    if not value:
        return None

    if strip:
        value = value.strip()

    if len(value) > max_length:
        value = value[:max_length]

    if not value:
        return None

    return value


def validate_email(email):
    """Basic email format validation."""
    if not email or '@' not in email:
        return False
    parts = email.split('@')
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain or '.' not in domain:
        return False
    if len(email) > 254:
        return False
    return True


def validate_password_strength(password):
    """Check password meets minimum requirements.
    
    Returns (is_valid, error_message) tuple.
    """
    if not password:
        return False, "Password is required."
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > 128:
        return False, "Password is too long."

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not (has_upper and has_lower and has_digit):
        return False, "Password must contain at least one uppercase letter, one lowercase letter, and one digit."

    return True, None


# ─── Security Headers ───────────────────────────────────────────────────────

def add_security_headers(response):
    """Add security headers to every response.
    
    Attach this to Flask's after_request hook.
    """
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'

    # XSS Protection (legacy but still useful for older browsers)
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # Control referrer information
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Permissions Policy (restrict browser features)
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'

    # Content Security Policy (permitting required CDNs, fonts, and sourcemaps)
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://accounts.google.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com",
        "font-src 'self' data: https://fonts.gstatic.com https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com",
        "img-src 'self' data: blob: https: http:",
        "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://accounts.google.com https://generativelanguage.googleapis.com",
        "frame-src 'self' https://accounts.google.com",
        "base-uri 'self'",
        "form-action 'self' https://accounts.google.com",
    ]
    response.headers['Content-Security-Policy'] = '; '.join(csp_directives)

    # HSTS (only in production with HTTPS)
    if request.is_secure or os.environ.get("VERCEL"):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    return response


# ─── Cron Endpoint Authentication ────────────────────────────────────────────

def verify_cron_secret():
    """Verify the CRON_SECRET header for protected cron endpoints.
    
    Returns True if authorized, False otherwise.
    On Vercel, cron jobs are called with the Authorization header.
    """
    cron_secret = os.getenv("CRON_SECRET")

    # If no secret configured, allow in development but block in production
    if not cron_secret:
        if os.environ.get("VERCEL"):
            return False  # Block in production without secret
        return True  # Allow in local dev

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {cron_secret}":
        return True

    return False


# ─── OAuth State Parameter ───────────────────────────────────────────────────

def generate_oauth_state():
    """Generate a random state parameter for OAuth CSRF protection."""
    state = secrets.token_urlsafe(32)
    session['_oauth_state'] = state
    return state


def verify_oauth_state(received_state):
    """Verify the OAuth state parameter matches what was stored in session."""
    expected = session.pop('_oauth_state', None)
    if not expected or not received_state:
        return False
    return secrets.compare_digest(expected, received_state)
