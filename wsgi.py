"""Production entry point: be-rao at /, SolarWeb mounted at /solar.

    gunicorn wsgi:app        (Render start command)
    python wsgi.py           (local development, http://127.0.0.1:5000)
"""
import os

from werkzeug.middleware.dispatcher import DispatcherMiddleware

from app import app as berao_app
from solarweb import create_app

SOLAR_PREFIX = '/solar'

# Own cookie path so its login never touches be-rao's session cookie (and vice versa)
solar_app = create_app({'SESSION_COOKIE_PATH': SOLAR_PREFIX})

app = DispatcherMiddleware(berao_app, {SOLAR_PREFIX: solar_app})

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    debug = os.getenv('FLASK_DEBUG') == '1'
    run_simple('127.0.0.1', int(os.getenv('PORT', '5000')), app, use_reloader=debug, use_debugger=debug)
