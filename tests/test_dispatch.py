"""be-rao at / and SolarWeb at /solar, served together by wsgi.py from one database."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# wsgi imports be-rao's app.py, which configures itself from the environment at import time
_db_dir = tempfile.mkdtemp(prefix='berao-dispatch-')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_db_dir, 'shared.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'shared-test-secret'
os.environ['ADMIN_PASSWORD'] = 'berao-pass-123'
os.environ['SOLARWEB_ADMIN_USERNAME'] = 'admin'
os.environ['SOLARWEB_ADMIN_PASSWORD'] = 'solar-pass-123'
os.environ['SOLARWEB_NOINDEX'] = '1'
for var in ('SITE_URL', 'SOLARWEB_SITE_URL', 'SOLARWEB_SECRET_KEY', 'TURNSTILE_SITE_KEY', 'SOLARWEB_TURNSTILE_SITE_KEY'):
    os.environ.pop(var, None)

import pytest  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402
from werkzeug.test import Client  # noqa: E402

import wsgi  # noqa: E402


@pytest.fixture
def client():
    return Client(wsgi.app)


def token(response):
    html = response.get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([0-9a-f]+)"', html) or re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert m, 'no CSRF token on page'
    return m.group(1)


def set_cookies(response):
    return response.headers.getlist('Set-Cookie')


def login_berao(client):
    page = client.get('/login')
    r = client.post('/login', data={'username': 'admin', 'password': 'berao-pass-123', 'csrf_token': token(page)})
    assert r.status_code == 302 and r.headers['Location'].endswith('/')
    return r


def login_solar(client, next_path=None):
    page = client.get('/solar/admin/dang-nhap')
    url = '/solar/admin/dang-nhap' + (f'?next={next_path}' if next_path else '')
    r = client.post(url, data={'username': 'admin', 'password': 'solar-pass-123', 'csrf_token': token(page)})
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    return r


def test_routing(client):
    r = client.get('/')
    assert r.status_code == 302 and r.headers['Location'].endswith('/login')  # be-rao
    home = client.get('/solar/')
    html = home.get_data(as_text=True)
    assert home.status_code == 200 and 'href="/solar/san-pham/"' in html and '/solar/static/site.css' in html
    assert 'href="/san-pham/' not in html  # every link carries the prefix
    assert client.get('/solar/static/site.css').status_code == 200
    assert client.get('/static/style.css').status_code == 200  # be-rao's own static files
    bare = client.get('/solar')
    assert bare.status_code in (301, 308) and bare.headers['Location'].endswith('/solar/')
    assert client.get('/solar/khong-co/').status_code == 404


def test_solar_admin_login_stays_under_prefix(client):
    r = client.get('/solar/admin/san-pham/')
    assert r.status_code == 302
    location = r.headers['Location']
    assert location.startswith('/solar/admin/dang-nhap?next=')
    next_path = location.split('next=', 1)[1]
    r = login_solar(client, next_path)
    assert r.headers['Location'].rstrip('?') == '/solar/admin/san-pham/'
    # A `next` pointing outside the admin falls back to the dashboard
    client2 = Client(wsgi.app)
    assert login_solar(client2, '//evil.example').headers['Location'] == '/solar/admin/'


def test_separate_sessions(client):
    r = login_berao(client)
    cookies = set_cookies(r)
    assert any(c.startswith('session=') and 'Path=/' in c for c in cookies)
    assert not any(c.startswith('sw_session=') for c in cookies)

    r = login_solar(client)
    cookies = set_cookies(r)
    assert any(c.startswith('sw_session=') and 'Path=/solar' in c for c in cookies)
    assert not any(c.startswith('session=') for c in cookies)

    # Both logins work side by side in one browser
    assert client.get('/issue').status_code == 200
    assert client.get('/solar/admin/').status_code == 200

    # Logging out of SolarWeb keeps the be-rao login, and the other way round
    admin_page = client.get('/solar/admin/')
    client.post('/solar/admin/dang-xuat', data={'csrf_token': token(admin_page)})
    assert client.get('/solar/admin/').status_code == 302
    assert client.get('/issue').status_code == 200


def test_berao_login_does_not_grant_solar_admin(client):
    login_berao(client)
    r = client.get('/solar/admin/')
    assert r.status_code == 302 and '/solar/admin/dang-nhap' in r.headers['Location']


def test_seo_urls_have_single_prefix(client):
    xml = client.get('/solar/sitemap.xml').get_data(as_text=True)
    assert '<loc>http://localhost/solar/</loc>' in xml and '/solar/solar' not in xml
    robots = client.get('/solar/robots.txt').get_data(as_text=True)
    assert 'Disallow: /solar/admin/' in robots and 'Sitemap: http://localhost/solar/sitemap.xml' in robots
    html = client.get('/solar/san-pham/').get_data(as_text=True)
    assert '<link rel="canonical" href="http://localhost/solar/san-pham/">' in html


def test_noindex_only_on_solar(client):
    solar = client.get('/solar/')
    assert solar.headers.get('X-Robots-Tag') == 'noindex, nofollow'
    assert '<meta name="robots" content="noindex, nofollow">' in solar.get_data(as_text=True)
    assert 'X-Robots-Tag' not in client.get('/login').headers


def test_tables_side_by_side():
    tables = set(inspect(create_engine(os.environ['DATABASE_URL'])).get_table_names())
    assert {'user', 'marathon', 'issue_record'} <= tables  # be-rao
    assert {'sw_user', 'sw_product', 'sw_order', 'sw_lead'} <= tables  # SolarWeb
    assert not {t for t in tables if not t.startswith('sw_')} & {'product', 'order', 'lead', 'post', 'setting'}


def test_solar_secret_differs_from_berao():
    assert wsgi.solar_app.config['SECRET_KEY'] != wsgi.berao_app.config['SECRET_KEY']
