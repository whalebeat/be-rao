import io

from PIL import Image

from solarweb.csv_io import export_products, import_products
from solarweb.models import Brand, Category, MediaFile, Product, User, db
from solarweb.tests.conftest import SEED_CSV, csrf, login, make_user


def test_anonymous_redirected_to_login(client):
    for path in ['/admin/', '/admin/san-pham/', '/admin/don-hang/', '/admin/cai-dat/']:
        r = client.get(path)
        assert r.status_code == 302 and '/admin/dang-nhap' in r.headers['Location'], path


def test_admin_pages_render(client, seeded):
    login(client)
    p = Product.query.first()
    for path in ['/admin/', '/admin/san-pham/', '/admin/san-pham/moi', f'/admin/san-pham/{p.id}/', '/admin/san-pham/nhap',
                 '/admin/danh-muc/', '/admin/thuong-hieu/', '/admin/don-hang/', '/admin/tu-van/', '/admin/lien-he/',
                 '/admin/noi-dung/project/', '/admin/noi-dung/news/moi', '/admin/noi-dung/page/', '/admin/cai-dat/',
                 '/admin/cai-dat/tinh-dien', '/admin/nguoi-dung/', '/admin/doi-mat-khau']:
        assert client.get(path).status_code == 200, path
    export = client.get('/admin/san-pham/xuat')
    assert export.status_code == 200 and export.mimetype == 'text/csv'


def test_staff_cannot_open_settings_or_users(client):
    make_user('nhanvien', 'staff')
    login(client, 'nhanvien', 'staff-pass-123')
    assert client.get('/admin/san-pham/').status_code == 200
    for path in ['/admin/cai-dat/', '/admin/cai-dat/tinh-dien', '/admin/nguoi-dung/']:
        assert client.get(path).status_code == 302, path
    r = client.post('/admin/nguoi-dung/', data={'username': 'x', 'password': 'xxxxxxxxxx', 'role': 'admin', 'csrf_token': csrf(client)})
    assert r.status_code == 302 and User.query.filter_by(username='x').first() is None


def test_login_throttle(client):
    for _ in range(5):
        client.post('/admin/dang-nhap', data={'username': 'admin', 'password': 'wrong', 'csrf_token': csrf(client)})
    r = client.post('/admin/dang-nhap', data={'username': 'admin', 'password': 'admin-pass-123', 'csrf_token': csrf(client)})
    assert r.status_code == 429


def test_generated_password_must_be_changed(client):
    u = make_user('moi', 'staff')
    u.must_change_password = True
    db.session.commit()
    login(client, 'moi', 'staff-pass-123')
    r = client.get('/admin/san-pham/')
    assert r.status_code == 302 and '/admin/doi-mat-khau' in r.headers['Location']
    client.post('/admin/doi-mat-khau', data={'current_password': 'staff-pass-123', 'new_password': 'new-pass-456',
                                            'confirm_password': 'new-pass-456', 'csrf_token': csrf(client)})
    assert client.get('/admin/san-pham/').status_code == 200


def test_csv_import_seed(app, seeded):
    assert seeded['created'] == 8 and not seeded['errors']
    p = Product.query.filter_by(sku='SOLIS-S6-GR1P5K').one()
    assert p.regular_price == 16500000 and p.featured
    assert [c.path() for c in p.categories] == ['Inverter > Inverter 1 pha']
    assert [b.name for b in p.brands] == ['Solis']
    assert [(a.name, a.value) for a in p.attributes][:2] == [('Công suất', '5 kW'), ('Số pha', '1 pha')]
    assert Product.query.filter_by(sku='HUAWEI-SUN2000-50KTL-M3').one().regular_price is None
    assert Category.query.filter_by(name='Inverter').count() == 1


def test_csv_reimport_updates_not_duplicates(app, seeded):
    with open(SEED_CSV, encoding='utf-8-sig') as f:
        text = f.read()
    report = import_products(text.replace('16500000', '17000000'), update_existing=True)
    assert report['updated'] == 8 and report['created'] == 0
    assert Product.query.count() == 8 and Brand.query.count() == 5
    assert Product.query.filter_by(sku='SOLIS-S6-GR1P5K').one().regular_price == 17000000
    report = import_products(text, update_existing=False)
    assert report['skipped'] == 8 and report['updated'] == 0


def test_csv_export_roundtrip(app, seeded):
    def snapshot():
        return sorted((p.sku, p.name, p.regular_price, p.featured, p.published, tuple(c.path() for c in p.categories),
                       tuple(b.name for b in p.brands), tuple((a.name, a.value) for a in p.attributes), p.datasheet_url)
                      for p in Product.query.all())
    before = snapshot()
    exported = export_products(Product.query.all())
    db.session.query(Product).delete()
    db.session.commit()
    report = import_products(exported, update_existing=True)
    assert report['created'] == 8 and not report['errors']
    assert snapshot() == before


def test_csv_bad_rows_reported(app):
    report = import_products('SKU,Name,Regular price\n,No sku,1\nA1,Có SKU,1000\n', update_existing=True)
    assert report['created'] == 1 and report['skipped'] == 1 and report['errors'][0][0] == 2


def png_upload(width=3000, height=2000):
    buf = io.BytesIO()
    Image.new('RGBA', (width, height), (243, 156, 18, 255)).save(buf, 'PNG')
    buf.seek(0)
    return buf


def test_product_create_with_image(client):
    login(client)
    data = {'csrf_token': csrf(client), 'name': 'Tấm pin thử', 'sku': 'TEST-1', 'regular_price': '2.500.000',
            'published': '1', 'in_stock': '1', 'attr_name[]': ['Công suất', ''], 'attr_value[]': ['600W', ''],
            'attr_visible[]': ['1', '1'], 'description': '<p>Mô tả <script>alert(1)</script><b>đậm</b></p>',
            'images': (png_upload(), 'anh-lon.png')}
    r = client.post('/admin/san-pham/moi', data=data, content_type='multipart/form-data')
    assert r.status_code == 302
    p = Product.query.filter_by(sku='TEST-1').one()
    assert p.slug == 'tam-pin-thu' and p.regular_price == 2500000
    assert [(a.name, a.value) for a in p.attributes] == [('Công suất', '600W')]
    assert '<script>' not in p.description and '<b>đậm</b>' in p.description
    media = p.images[0].media
    assert media.content_type == 'image/jpeg'
    stored = Image.open(io.BytesIO(media.data))
    assert max(stored.size) == 1600
    served = client.get(f'/media/{media.id}/{media.filename}')
    assert served.status_code == 200 and 'immutable' in served.headers['Cache-Control'] and served.headers['ETag']
    again = client.get(f'/media/{media.id}/{media.filename}', headers={'If-None-Match': served.headers['ETag']})
    assert again.status_code == 304


def test_product_duplicate_sku_keeps_input(client, seeded):
    login(client)
    r = client.post('/admin/san-pham/moi', data={'csrf_token': csrf(client), 'name': 'Tên đã gõ', 'sku': 'SOLIS-S6-GR1P5K'})
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert 'đã được dùng' in html and 'Tên đã gõ' in html
    assert Product.query.count() == 8


def test_bad_upload_rejected(client):
    login(client)
    r = client.post('/admin/san-pham/moi', data={'csrf_token': csrf(client), 'name': 'X', 'sku': 'X1',
                                                 'images': (io.BytesIO(b'not an image'), 'evil.png')},
                    content_type='multipart/form-data')
    assert r.status_code == 400 and Product.query.count() == 0 and MediaFile.query.count() == 0


def test_calc_settings_saved(client):
    login(client)
    client.post('/admin/cai-dat/tinh-dien', data={'csrf_token': csrf(client), 'panel_watt': '700', 'evn_tiers': 'bad'})
    from solarweb.settings import calc_settings
    s = calc_settings()
    assert s['panel_watt'] == 700 and s['evn_tiers'] == '1984,2050,2380,2998,3350,3460'
