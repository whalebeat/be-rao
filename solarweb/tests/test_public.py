from solarweb.models import Category, Order, Post, Product, db
from solarweb.tests.conftest import csrf

PUBLIC_PAGES = ['/', '/san-pham/', '/san-pham/?q=solis', '/san-pham/?sap-xep=gia-giam&trang=3',
                '/danh-muc/inverter/', '/thuong-hieu/solis/', '/du-an/', '/tin-tuc/',
                '/tinh-dien-mat-troi/', '/lien-he/', '/gio-hang/', '/sitemap.xml', '/robots.txt']


def test_public_pages(client, seeded):
    for path in PUBLIC_PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
    for p in Product.query.all():
        assert client.get(f'/san-pham/{p.slug}/').status_code == 200
    assert client.get('/khong-ton-tai/').status_code == 404


def test_security_headers(client):
    r = client.get('/')
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert r.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert 'Referrer-Policy' in r.headers and 'Permissions-Policy' in r.headers


def test_category_includes_children(client, seeded):
    parent = Category.query.filter_by(name='Inverter', parent_id=None).one()
    html = client.get(f'/danh-muc/{parent.slug}/').get_data(as_text=True)
    assert 'Inverter Solis 1 pha 5kW' in html and 'Inverter Hybrid Solis 6kW' in html
    assert 'Tấm pin JA Solar' not in html


def test_hidden_product_404(client, seeded):
    p = Product.query.first()
    p.published = False
    db.session.commit()
    assert client.get(f'/san-pham/{p.slug}/').status_code == 404


def test_contact_price_product(client, seeded):
    p = Product.query.filter_by(sku='HUAWEI-SUN2000-50KTL-M3').one()
    assert p.has_no_price
    html = client.get(f'/san-pham/{p.slug}/').get_data(as_text=True)
    assert 'Liên hệ' in html and 'Thông số kỹ thuật' in html
    r = client.post('/gio-hang/them', data={'product_id': p.id, 'qty': 2, 'csrf_token': csrf(client)})
    assert r.status_code == 302
    cart_html = client.get('/gio-hang/').get_data(as_text=True)
    assert p.name in cart_html and 'Liên hệ' in cart_html


def place_order(client, **overrides):
    data = {'name': 'Nguyễn Văn A', 'phone': '0912 345 678', 'address': '12 Lê Lợi', 'city': 'Đà Nẵng',
            'email': '', 'note': 'Gọi buổi sáng', 'csrf_token': csrf(client)}
    data.update(overrides)
    return client.post('/dat-hang/', data=data)


def test_checkout_creates_order(client, seeded):
    priced = Product.query.filter_by(sku='SOLIS-S6-GR1P5K').one()
    contact = Product.query.filter_by(sku='HUAWEI-SUN2000-50KTL-M3').one()
    token = csrf(client)
    client.post('/gio-hang/them', data={'product_id': priced.id, 'qty': 2, 'csrf_token': token})
    client.post('/gio-hang/them', data={'product_id': contact.id, 'qty': 1, 'csrf_token': token})

    r = place_order(client)
    assert r.status_code == 302 and '/dat-hang/thanh-cong/' in r.headers['Location']
    order = Order.query.one()
    assert order.phone == '0912345678'
    assert order.total_known == 2 * 16500000 and order.has_contact_price
    assert {(i.sku, i.qty, i.unit_price) for i in order.items} == {('SOLIS-S6-GR1P5K', 2, 16500000), ('HUAWEI-SUN2000-50KTL-M3', 1, None)}
    done = client.get(r.headers['Location'])
    assert done.status_code == 200 and order.code in done.get_data(as_text=True)
    assert client.get('/gio-hang/').get_data(as_text=True).count('Giỏ hàng đang trống') == 1
    # Another visitor can't open the confirmation page
    assert client.application.test_client().get(r.headers['Location']).status_code == 404


def test_checkout_validation(client, seeded):
    p = Product.query.first()
    client.post('/gio-hang/them', data={'product_id': p.id, 'csrf_token': csrf(client)})
    assert place_order(client, phone='12345').status_code == 400
    assert place_order(client, address='').status_code == 400
    assert Order.query.count() == 0


def test_post_without_csrf_rejected(client, seeded):
    p = Product.query.first()
    assert client.post('/gio-hang/them', data={'product_id': p.id}).status_code == 400
    assert client.post('/dat-hang/', data={'name': 'x'}).status_code == 400


def test_order_rate_limit(client, seeded):
    p = Product.query.first()
    for i in range(5):
        client.post('/gio-hang/them', data={'product_id': p.id, 'csrf_token': csrf(client)})
        assert place_order(client).status_code == 302
    client.post('/gio-hang/them', data={'product_id': p.id, 'csrf_token': csrf(client)})
    assert place_order(client).status_code == 400
    assert Order.query.count() == 5


def test_contact_form(client):
    from solarweb.models import ContactMessage
    token = csrf(client)
    r = client.post('/lien-he/', data={'name': 'Trần B', 'phone': '0987654321', 'message': 'Tư vấn mái tôn', 'consent': '1', 'csrf_token': token})
    assert r.status_code == 302
    msg = ContactMessage.query.one()
    assert msg.phone == '0987654321' and 'đồng ý' in msg.consent
    # Honeypot and missing consent save nothing
    client.post('/lien-he/', data={'name': 'Bot', 'phone': '0987654321', 'consent': '1', 'website': 'spam', 'csrf_token': token})
    client.post('/lien-he/', data={'name': 'C', 'phone': '0987654321', 'csrf_token': token})
    assert ContactMessage.query.count() == 1


def test_pages_and_sitemap(client, seeded):
    db.session.add(Post(kind='page', slug='gioi-thieu', title='Giới thiệu', content='<p>Về chúng tôi</p>'))
    db.session.add(Post(kind='news', slug='tin-moi', title='Tin mới', content='<p>Nội dung</p>', published=False))
    db.session.commit()
    assert 'Về chúng tôi' in client.get('/gioi-thieu/').get_data(as_text=True)
    assert client.get('/tin-tuc/tin-moi/').status_code == 404  # draft
    xml = client.get('/sitemap.xml').get_data(as_text=True)
    assert '/gioi-thieu/' in xml and '/tin-tuc/tin-moi/' not in xml and '/san-pham/' in xml
    assert 'Disallow: /admin/' in client.get('/robots.txt').get_data(as_text=True)
