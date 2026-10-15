import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # solarweb/
sys.path.insert(0, os.path.dirname(ROOT))  # repo root, so `solarweb` imports as a package

# SolarWeb reads SOLARWEB_<NAME> first; set only namespaced variables so be-rao's tests are unaffected
os.environ['SOLARWEB_ADMIN_USERNAME'] = 'admin'
os.environ['SOLARWEB_ADMIN_PASSWORD'] = 'admin-pass-123'
for var in ('TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET', 'SMTP_HOST', 'SITE_URL', 'NOINDEX'):
    os.environ.pop(var, None)
    os.environ.pop(f'SOLARWEB_{var}', None)

from solarweb import create_app  # noqa: E402
from solarweb.models import User, db, init_db  # noqa: E402
from solarweb.security import limiter  # noqa: E402

_db_dir = tempfile.mkdtemp(prefix='solarweb-test-')
flask_app = create_app({
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(_db_dir, 'test.db').replace('\\', '/'),
    'SECRET_KEY': 'test-secret',
    'TESTING': True,
})

SEED_CSV = os.path.join(ROOT, 'seed', 'products.csv')


@pytest.fixture
def app(monkeypatch):
    # init_db() below re-reads these; pin them so other test modules' environment can't leak in
    monkeypatch.setenv('SOLARWEB_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('SOLARWEB_ADMIN_PASSWORD', 'admin-pass-123')
    with flask_app.app_context():
        db.drop_all()
        init_db()
        limiter.clear()
        yield flask_app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded(app):
    from solarweb.csv_io import import_products
    with open(SEED_CSV, encoding='utf-8-sig') as f:
        return import_products(f.read(), update_existing=True)


def csrf(client):
    """CSRF token for this client's session (loads a page first if needed)."""
    with client.session_transaction() as s:
        token = s.get('_csrf_token')
    if not token:
        client.get('/admin/dang-nhap')
        with client.session_transaction() as s:
            token = s['_csrf_token']
    return token


def login(client, username='admin', password='admin-pass-123'):
    r = client.post('/admin/dang-nhap', data={'username': username, 'password': password, 'csrf_token': csrf(client)})
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    return r


def make_user(username, role, password='staff-pass-123'):
    u = User(username=username, role=role)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u
