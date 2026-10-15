import json
import re

from solarweb.models import Lead
from solarweb.settings import CALC_DEFAULTS, sanitize_calc

VALID = {'name': 'Lê C', 'phone': '0901234567', 'consent': True, 'website': '', 'turnstile': '',
         'province': 'Đà Nẵng', 'bill': '2.000.000đ', 'customer': 'Hộ gia đình', 'system': '5 kWp',
         'price': '35–40 triệu', 'savings': '1.500.000đ (75%)', 'payback': '5,2 năm', 'note': ''}


def post_lead(client, **overrides):
    return client.post('/api/lead', json={**VALID, **overrides})


def test_calculator_page_config(client):
    html = client.get('/tinh-dien-mat-troi/').get_data(as_text=True)
    assert 'data-solarweb-calculator' in html and 'calculator.js' in html
    data = json.loads(re.search(r'window\.SOLARWEB_CALC = (.*?);</script>', html).group(1))
    assert set(data) == {'config', 'regions', 'zalo', 'leadUrl', 'consent', 'privacy', 'captcha'}
    assert data['config']['evn_tiers'] == [1984.0, 2050.0, 2380.0, 2998.0, 3350.0, 3460.0]
    assert 'zalo' not in data['config']
    assert data['leadUrl'] == '/api/lead' and data['captcha'] == ''
    assert sum(len(r['provinces']) for r in data['regions']) == 34


def test_valid_lead_saved(client):
    r = post_lead(client)
    assert r.status_code == 201 and r.get_json() == {'ok': True}
    lead = Lead.query.one()
    assert lead.name == 'Lê C' and lead.province == 'Đà Nẵng' and 'đồng ý' in lead.consent


def test_lead_needs_no_csrf_but_json(client):
    # calculator.js posts JSON with credentials: 'omit', so there is no session or CSRF token
    assert client.post('/api/lead', data=VALID).status_code == 415


def test_honeypot(client):
    r = post_lead(client, website='http://spam')
    assert r.status_code == 200 and Lead.query.count() == 0


def test_validation(client):
    r = post_lead(client, consent=False)
    assert r.status_code == 400 and 'đồng ý' in r.get_json()['message']
    assert post_lead(client, consent='true').status_code == 400  # must be the JSON boolean
    assert post_lead(client, phone='123').status_code == 400
    assert post_lead(client, name='  ').status_code == 400
    assert Lead.query.count() == 0


def test_rate_limit(client):
    for _ in range(5):
        assert post_lead(client).status_code == 201
    r = post_lead(client)
    assert r.status_code == 429 and r.get_json()['message']
    assert Lead.query.count() == 5


def test_long_fields_truncated(client):
    post_lead(client, name='A' * 500, note='x' * 1000)
    lead = Lead.query.one()
    assert len(lead.name) == 100 and len(lead.note) == 300


def test_sanitize_calc_matches_php_rules():
    clean = sanitize_calc({'evn_tiers': '1,2,3', 'bill_vat': '0,1', 'panel_watt': '-5', 'zalo': '090-123 4567',
                           'rate_commercial': 'abc'})
    assert clean['evn_tiers'] == CALC_DEFAULTS['evn_tiers']  # needs exactly 6 tiers
    assert clean['bill_vat'] == 0.1  # comma decimal accepted
    assert clean['panel_watt'] == CALC_DEFAULTS['panel_watt']  # must be > 0
    assert clean['rate_commercial'] == CALC_DEFAULTS['rate_commercial']
    assert clean['zalo'] == '0901234567'
    assert sanitize_calc({'evn_tiers': '1,2,3,4,5,6'})['evn_tiers'] == '1,2,3,4,5,6'
