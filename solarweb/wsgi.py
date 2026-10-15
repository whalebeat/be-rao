"""Standalone entry point, for running SolarWeb on its own domain:

    gunicorn solarweb.wsgi:app
"""
import os

from solarweb import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
