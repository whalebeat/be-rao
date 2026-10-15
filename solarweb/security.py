"""CSRF, login throttling, roles, rate limits, security headers and Turnstile.

CSRF / throttling / roles are adapted from be-rao/app.py.
"""
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for

from . import env

# Endpoints that accept cross-site-safe JSON without a session (see public.api_lead)
CSRF_EXEMPT = {'public.api_lead'}


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def csrf_protect():
    if request.method != 'POST' or request.endpoint in CSRF_EXEMPT:
        return
    expected = session.get('_csrf_token')
    sent = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, description='CSRF token missing or invalid')


def client_ip():
    """Visitor IP. CF-Connecting-IP is only trusted when opted in, since anyone can send it."""
    if env('BEHIND_CLOUDFLARE') == '1':
        cf = request.headers.get('CF-Connecting-IP', '').strip()
        if cf:
            return cf
    return request.remote_addr or ''


class RateLimiter:
    """In-memory sliding window (per worker process)."""

    def __init__(self):
        self._hits = defaultdict(list)

    def recent(self, key, window):
        cutoff = time.time() - window
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        return len(self._hits[key])

    def hit(self, key, limit, window):
        """Record one hit; return False if the key was already at the limit."""
        if self.recent(key, window) >= limit:
            return False
        self._hits[key].append(time.time())
        return True

    def add(self, key):
        self._hits[key].append(time.time())

    def reset(self, key):
        self._hits.pop(key, None)

    def clear(self):
        self._hits.clear()


limiter = RateLimiter()

# Login throttling
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60


def login_key(username):
    return f"login|{client_ip()}|{(username or '').lower()}"


def get_current_user():
    from .models import User, db
    if session.get('user_id'):
        return db.session.get(User, session['user_id'])
    return None


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                session.pop('user_id', None)
                flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
                return redirect(url_for('admin.login', next=request.full_path))
            if user.role not in roles:
                flash('Bạn không có quyền truy cập trang này.', 'danger')
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


staff_required = roles_required('admin', 'staff')
admin_required = roles_required('admin')


def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


# Cloudflare Turnstile: off until both keys exist (env vars override admin settings)
def turnstile_site_key():
    from .settings import get_setting
    return env('TURNSTILE_SITE_KEY') or get_setting('turnstile_site_key', '')


def turnstile_secret():
    from .settings import get_setting
    return env('TURNSTILE_SECRET') or get_setting('turnstile_secret', '')


def turnstile_enabled():
    return bool(turnstile_site_key() and turnstile_secret())


def turnstile_verify(token):
    """Fails closed: if Cloudflare can't be reached the submission is refused."""
    if not turnstile_enabled():
        return True
    token = token.strip() if isinstance(token, str) else ''
    if not token or len(token) > 2048:
        return False
    body = urllib.parse.urlencode({'secret': turnstile_secret(), 'response': token, 'remoteip': client_ip()}).encode()
    try:
        with urllib.request.urlopen('https://challenges.cloudflare.com/turnstile/v0/siteverify', body, timeout=10) as res:
            return bool(json.load(res).get('success'))
    except Exception:
        return False
