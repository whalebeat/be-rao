"""SolarWeb: solar-equipment catalogue (Flask rewrite of the WordPress site).

Mounted at /solar by be-rao's wsgi.py, or run on its own with solarweb/wsgi.py.
Settings are read from SOLARWEB_<NAME> first, then <NAME>, so one environment
can hold both apps' settings.
"""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta, timezone

from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

VN_TZ = timezone(timedelta(hours=7))  # Vietnam has no DST


def env(name, default=None):
    """SOLARWEB_<name> if set, else <name>, else default."""
    value = os.getenv(f'SOLARWEB_{name}')
    if value is None or value == '':
        value = os.getenv(name)
    return default if value is None or value == '' else value


def _secret_key():
    own = os.getenv('SOLARWEB_SECRET_KEY')
    if own:
        return own
    shared = os.getenv('SECRET_KEY')
    if shared:
        # Derived, so it never equals the key of an app sharing this environment
        return hmac.new(shared.encode(), b'solarweb', hashlib.sha256).hexdigest()
    # Random per-process key: sessions don't survive restarts, but cookies can't be forged.
    print('WARNING: SECRET_KEY is not set; using a random key. Set SOLARWEB_SECRET_KEY in production.')
    return secrets.token_hex(32)


def create_app(config=None):
    from . import security, settings, storage, utils
    from .models import db, init_db

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    database_url = env('DATABASE_URL', 'sqlite:///solarweb.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
        SECRET_KEY=_secret_key(),
        SESSION_COOKIE_NAME='sw_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=env('SESSION_COOKIE_SECURE', 'true' if os.getenv('RENDER') else 'false').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        SITE_URL=env('SITE_URL', '').rstrip('/'),  # full base URL incl. any mount prefix, e.g. https://teso.vn/solar
        NOINDEX=env('NOINDEX') == '1',
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    with app.app_context():
        init_db()

    from .blueprints.admin import bp as admin_bp
    from .blueprints.cart import bp as cart_bp
    from .blueprints.public import bp as public_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(public_bp)  # last: it owns the catch-all /<slug>/ page route

    app.before_request(security.csrf_protect)
    app.after_request(security.security_headers)

    @app.after_request
    def noindex(response):
        if app.config['NOINDEX']:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.template_filter('vntime')
    def vntime(value, fmt='%d/%m/%Y %H:%M', default='—'):
        if not value:
            return default
        return value.replace(tzinfo=timezone.utc).astimezone(VN_TZ).strftime(fmt)

    app.jinja_env.filters['vnd'] = utils.vnd
    app.jinja_env.globals.update(
        csrf_token=security.csrf_token,
        media_url=storage.media_url,
        image_src=storage.image_src,
        get_setting=settings.get_setting,
        digits_only=utils.digits_only,
        turnstile_site_key=lambda: security.turnstile_site_key() if security.turnstile_enabled() else '',
    )

    @app.context_processor
    def inject_site():
        from .blueprints.cart import cart_count
        from .models import Category
        return {
            'site_name': settings.get_setting('site_name'),
            'hotline': settings.get_setting('hotline'),
            'zalo': settings.get_setting('zalo'),
            'cart_count': cart_count(),
            'menu_categories': Category.query.filter(Category.parent_id.is_(None)).order_by(Category.position, Category.name).all()
                               if not request.path.startswith('/admin') else [],
        }

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template('error.html', message='Tệp tải lên quá lớn (tối đa 16 MB).'), 413

    return app
