from datetime import timedelta, timezone

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template,
                   request, url_for)
from sqlalchemy import or_

from ..mailer import send_admin_mail
from ..models import (LEAD_FIELDS, Brand, Category, ContactMessage, Lead, MediaFile, Post, Product, db,
                    utcnow)
from ..security import client_ip, limiter, turnstile_enabled, turnstile_site_key, turnstile_verify
from ..settings import CALC_REGIONS, calc_client_config, calc_zalo_url, consent_text, get_setting
from ..storage import image_src
from ..utils import PHONE_RE, clean_phone, parse_int, truncate

bp = Blueprint('public', __name__)

PER_PAGE = 12
SUBMIT_LIMIT = 5  # lead/contact/order submissions per IP per hour
SUBMIT_WINDOW = 60 * 60
VN_TZ = timezone(timedelta(hours=7))
SORTS = {
    'moi-nhat': Product.created_at.desc(),
    'gia-tang': Product.regular_price.asc(),
    'gia-giam': Product.regular_price.desc(),
    'ten': Product.name.asc(),
}


def published_products():
    return Product.query.filter(Product.published.is_(True))


def published_posts(kind):
    return Post.query.filter_by(kind=kind, published=True)


def vn_now_text():
    return utcnow().replace(tzinfo=timezone.utc).astimezone(VN_TZ).strftime('%d/%m/%Y %H:%M')


def privacy_url():
    page = published_posts('page').filter_by(slug='chinh-sach-bao-mat').first()
    return url_for('public.page', slug=page.slug) if page else ''


@bp.route('/')
def home():
    featured = published_products().filter(Product.featured.is_(True)).order_by(Product.updated_at.desc()).limit(8).all()
    latest = published_products().order_by(Product.created_at.desc()).limit(8).all()
    return render_template('home.html', featured=featured or latest, latest=latest,
                           categories=Category.query.filter(Category.parent_id.is_(None)).order_by(Category.position, Category.name).all(),
                           brands=Brand.query.order_by(Brand.name).all(),
                           projects=published_posts('project').order_by(Post.created_at.desc()).limit(3).all(),
                           news=published_posts('news').order_by(Post.created_at.desc()).limit(3).all())


def product_listing(title, category=None, brand=None, description=''):
    q = published_products()
    if category is not None:
        q = q.filter(Product.categories.any(Category.id.in_(category.descendant_ids())))
    if brand is not None:
        q = q.filter(Product.brands.any(Brand.id == brand.id))
    search = (request.args.get('q') or '').strip()[:100]
    if search:
        like = f'%{search}%'
        q = q.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.short_description.ilike(like)))
    sort = request.args.get('sap-xep', 'moi-nhat')
    q = q.order_by(SORTS.get(sort, SORTS['moi-nhat']), Product.id.desc())
    page = q.paginate(page=parse_int(request.args.get('trang'), 1), per_page=PER_PAGE, error_out=False)
    return render_template('product_list.html', page=page, title=title, category=category, brand=brand,
                           search=search, sort=sort, description=description,
                           brands=Brand.query.order_by(Brand.name).all())


@bp.route('/san-pham/')
def products():
    search = (request.args.get('q') or '').strip()
    return product_listing(f'Tìm kiếm: {search}' if search else 'Sản phẩm')


@bp.route('/danh-muc/<slug>/')
def category(slug):
    cat = Category.query.filter_by(slug=slug).first_or_404()
    return product_listing(cat.name, category=cat, description=f'{cat.name} chính hãng, giá tốt tại {get_setting("site_name")}.')


@bp.route('/thuong-hieu/<slug>/')
def brand(slug):
    b = Brand.query.filter_by(slug=slug).first_or_404()
    return product_listing(f'Thương hiệu {b.name}', brand=b, description=f'Sản phẩm {b.name} chính hãng tại {get_setting("site_name")}.')


@bp.route('/san-pham/<slug>/')
def product(slug):
    p = published_products().filter_by(slug=slug).first_or_404()
    related = []
    if p.categories:
        related = published_products().filter(Product.id != p.id, Product.categories.any(Category.id.in_([c.id for c in p.categories]))) \
            .order_by(Product.featured.desc(), Product.created_at.desc()).limit(4).all()
    return render_template('product_detail.html', product=p, related=related,
                           specs=[a for a in p.attributes if a.visible], jsonld=product_jsonld(p))


def product_jsonld(p):
    """schema.org Product for search results."""
    data = {'@context': 'https://schema.org', '@type': 'Product', 'name': p.name, 'sku': p.sku,
            'description': p.short_description or p.name,
            'image': [image_src(i, external=True) for i in p.images]}
    if p.brands:
        data['brand'] = {'@type': 'Brand', 'name': p.brands[0].name}
    if p.price is not None:
        data['offers'] = {'@type': 'Offer', 'priceCurrency': 'VND', 'price': p.price,
                          'availability': 'https://schema.org/' + ('InStock' if p.in_stock else 'OutOfStock'),
                          'url': url_for('public.product', slug=p.slug, _external=True)}
    return data


def post_list(kind, template_title):
    page = published_posts(kind).order_by(Post.created_at.desc()).paginate(
        page=parse_int(request.args.get('trang'), 1), per_page=PER_PAGE, error_out=False)
    return render_template('post_list.html', page=page, kind=kind, title=template_title)


def post_detail(kind, slug):
    post = published_posts(kind).filter_by(slug=slug).first_or_404()
    others = published_posts(kind).filter(Post.id != post.id).order_by(Post.created_at.desc()).limit(3).all()
    return render_template('post_detail.html', post=post, others=others)


@bp.route('/du-an/')
def projects():
    return post_list('project', 'Dự án')


@bp.route('/du-an/<slug>/')
def project(slug):
    return post_detail('project', slug)


@bp.route('/tin-tuc/')
def news_list():
    return post_list('news', 'Tin tức')


@bp.route('/tin-tuc/<slug>/')
def news(slug):
    return post_detail('news', slug)


@bp.route('/tinh-dien-mat-troi/')
def calculator():
    intro = published_posts('page').filter_by(slug='tinh-dien-mat-troi').first()
    calc_data = {
        'config': calc_client_config(),
        'regions': CALC_REGIONS,
        'zalo': calc_zalo_url(),
        'leadUrl': url_for('public.api_lead'),
        'consent': consent_text(),
        'privacy': privacy_url(),
        'captcha': turnstile_site_key() if turnstile_enabled() else '',
    }
    return render_template('calculator.html', intro=intro, calc_data=calc_data)


def api_error(message, status):
    return jsonify({'message': message}), status


@bp.route('/api/lead', methods=['POST'])
def api_lead():
    """Public JSON endpoint for calculator.js (CSRF-exempt: it sends no cookies)."""
    if not request.is_json:
        return api_error('Yêu cầu không hợp lệ.', 415)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error('Yêu cầu không hợp lệ.', 400)
    # Honeypot: bots fill every field, people never see this one.
    if str(data.get('website') or ''):
        return jsonify({'ok': True}), 200

    name = truncate(data.get('name'), 100)
    phone = clean_phone(data.get('phone'))
    if not name or not PHONE_RE.match(phone):
        return api_error('Vui lòng nhập họ tên và số điện thoại hợp lệ.', 400)
    if data.get('consent') is not True:
        return api_error('Vui lòng đồng ý cho chúng tôi sử dụng thông tin để liên hệ tư vấn.', 400)
    # Rate limit before the captcha check, so bots can't make us flood Cloudflare.
    if not limiter.hit(f'lead|{client_ip()}', SUBMIT_LIMIT, SUBMIT_WINDOW):
        return api_error('Bạn đã gửi quá nhiều yêu cầu, vui lòng thử lại sau.', 429)
    if not turnstile_verify(data.get('turnstile')):
        return api_error('Xác minh chống spam không thành công, vui lòng thử lại.', 400)

    fields = {key: truncate(data.get(key), 300) for key in LEAD_FIELDS if key not in ('phone', 'consent')}
    lead = Lead(name=name, phone=phone, consent=f'{vn_now_text()} – "{consent_text()}"', **fields)
    db.session.add(lead)
    db.session.commit()

    lines = [f'Khách hàng: {name}']
    for key, label in LEAD_FIELDS.items():
        value = getattr(lead, key)
        if value:
            lines.append(f'{label}: {value}')
    lines.append(url_for('admin.lead_detail', lead_id=lead.id, _external=True))
    send_admin_mail(f'Yêu cầu tư vấn điện mặt trời: {name}', '\n'.join(lines))
    return jsonify({'ok': True}), 201


@bp.route('/lien-he/', methods=['GET', 'POST'])
def contact():
    page_post = published_posts('page').filter_by(slug='lien-he').first()
    form = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        if request.form.get('website'):  # honeypot
            flash('Cảm ơn bạn! Chúng tôi sẽ liên hệ lại sớm.', 'success')
            return redirect(url_for('public.contact'))
        name = truncate(request.form.get('name'), 100)
        phone = clean_phone(request.form.get('phone'))
        message = truncate(request.form.get('message'), 3000)
        error = None
        if not name or not PHONE_RE.match(phone):
            error = 'Vui lòng nhập họ tên và số điện thoại hợp lệ.'
        elif not request.form.get('consent'):
            error = 'Vui lòng đồng ý cho chúng tôi sử dụng thông tin để liên hệ tư vấn.'
        elif not limiter.hit(f'contact|{client_ip()}', SUBMIT_LIMIT, SUBMIT_WINDOW):
            error = 'Bạn đã gửi quá nhiều yêu cầu, vui lòng thử lại sau.'
        elif not turnstile_verify(request.form.get('cf-turnstile-response')):
            error = 'Vui lòng xác nhận bạn không phải robot rồi gửi lại.'
        if error:
            flash(error, 'danger')
        else:
            msg = ContactMessage(name=name, phone=phone, email=truncate(request.form.get('email'), 200),
                                 message=message, consent=f'{vn_now_text()} – "{consent_text()}"')
            db.session.add(msg)
            db.session.commit()
            send_admin_mail(f'Liên hệ mới: {name}', '\n'.join([
                f'Khách hàng: {name}', f'SĐT: {phone}', f'Email: {msg.email or "—"}', '', message,
                url_for('admin.message_detail', message_id=msg.id, _external=True)]))
            flash('Cảm ơn bạn! Chúng tôi sẽ liên hệ lại sớm.', 'success')
            return redirect(url_for('public.contact'))
    return render_template('contact.html', post=page_post, form=form, consent=consent_text(), privacy=privacy_url())


@bp.route('/media/<int:media_id>/<filename>')
def media(media_id, filename):
    m = db.session.get(MediaFile, media_id)
    if m is None:
        abort(404)
    etag = m.sha256
    if request.if_none_match and etag in request.if_none_match:
        resp = Response(status=304)
    else:
        resp = Response(m.data, mimetype=m.content_type)
        resp.headers['Content-Disposition'] = f'inline; filename="{m.filename}"'
    resp.set_etag(etag)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


def site_root():
    """Public base URL including any mount prefix, e.g. https://teso.vn/solar."""
    return current_app.config['SITE_URL'] or request.url_root.rstrip('/')


def abs_url(endpoint, **values):
    # url_for already includes the mount prefix, and so does site_root(): drop one of them
    return site_root() + url_for(endpoint, **values)[len(request.script_root):]


@bp.route('/robots.txt')
def robots():
    # Crawlers only read /robots.txt at the domain root, so this matters once SolarWeb has its own domain
    prefix = request.script_root
    body = '\n'.join(['User-agent: *'] + [f'Disallow: {prefix}{p}' for p in ('/admin/', '/gio-hang/', '/dat-hang/', '/api/')]
                     + [f'Sitemap: {abs_url("public.sitemap")}', ''])
    return Response(body, mimetype='text/plain')


@bp.route('/sitemap.xml')
def sitemap():
    urls = [(abs_url(e), None) for e in ('public.home', 'public.products', 'public.projects', 'public.news_list',
                                         'public.calculator', 'public.contact')]
    urls += [(abs_url('public.product', slug=p.slug), p.updated_at) for p in published_products().all()]
    urls += [(abs_url('public.category', slug=c.slug), None) for c in Category.query.all()]
    urls += [(abs_url('public.brand', slug=b.slug), None) for b in Brand.query.all()]
    endpoints = {'project': 'public.project', 'news': 'public.news', 'page': 'public.page'}
    for post in Post.query.filter_by(published=True).all():
        if post.kind == 'page' and post.slug in ('lien-he', 'tinh-dien-mat-troi'):
            continue
        urls.append((abs_url(endpoints[post.kind], slug=post.slug), post.updated_at))
    xml = render_template('sitemap.xml', urls=urls)
    return Response(xml, mimetype='application/xml')


@bp.route('/<slug>/')
def page(slug):
    # /lien-he/ and /tinh-dien-mat-troi/ have their own routes, which take precedence
    post =published_posts('page').filter_by(slug=slug).first_or_404()
    return render_template('page.html', post=post)
