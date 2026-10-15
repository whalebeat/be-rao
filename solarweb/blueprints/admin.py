"""Staff admin at /admin (replaces wp-admin). Roles: 'staff' and 'admin'."""
from datetime import datetime

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import func, or_

from ..content import sanitize_html
from ..csv_io import export_products, import_products
from ..models import (LEAD_FIELDS, LEAD_STATUSES, ORDER_STATUSES, POST_KINDS, Brand, Category,
                    ContactMessage, Lead, Order, Post, Product, ProductAttribute, ProductImage, User, db)
from ..security import (LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS, admin_required, get_current_user, limiter,
                      login_key, staff_required)
from ..settings import CALC_LABELS, calc_settings, get_setting, sanitize_calc, set_setting
from ..storage import UploadError, media_url, save_image, save_pdf
from ..utils import digits_only, parse_int, parse_price, truncate, unique_slug

bp = Blueprint('admin', __name__, url_prefix='/admin')

PER_PAGE = 30
MIN_PASSWORD_LENGTH = 8
ROLES = {'staff': 'Nhân viên', 'admin': 'Quản trị viên'}


@bp.context_processor
def inject_admin():
    return {'user': get_current_user(), 'ORDER_STATUSES': ORDER_STATUSES, 'LEAD_STATUSES': LEAD_STATUSES,
            'POST_KINDS': POST_KINDS, 'ROLES': ROLES,
            'new_orders': Order.query.filter_by(status='moi').count() if session.get('user_id') else 0,
            'new_leads': Lead.query.filter_by(status='moi').count() if session.get('user_id') else 0}


@bp.before_request
def enforce_password_change():
    # Accounts with a generated/reset password must change it before doing anything else
    if request.endpoint in ('admin.login', 'admin.logout', 'admin.change_password'):
        return
    user = get_current_user()
    if user and user.must_change_password:
        flash('Vui lòng đổi mật khẩu trước khi tiếp tục.', 'warning')
        return redirect(url_for('admin.change_password'))


def password_problem(password):
    if len(password or '') < MIN_PASSWORD_LENGTH:
        return f'Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự!'
    return None


# ---------------------------------------------------------------- auth

@bp.route('/dang-nhap', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        key = login_key(username)
        if limiter.recent(key, LOGIN_WINDOW_SECONDS) >= LOGIN_MAX_ATTEMPTS:
            flash('Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút.', 'danger')
            return render_template('admin/login.html'), 429
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(request.form.get('password')):
            limiter.reset(key)
            cart = session.get('cart')
            session.clear()
            if cart:
                session['cart'] = cart
            session.permanent = True
            session['user_id'] = user.id
            # `next` is relative to this app (see roles_required); add the mount prefix back
            target = request.args.get('next') or ''
            if target.startswith('/admin/') and not target.startswith('//'):
                return redirect(request.script_root + target)
            return redirect(url_for('admin.dashboard'))
        limiter.add(key)
        flash('Tên đăng nhập hoặc mật khẩu không đúng!', 'danger')
    return render_template('admin/login.html')


@bp.route('/dang-xuat', methods=['POST'])
def logout():
    session.pop('user_id', None)
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('admin.login'))


@bp.route('/doi-mat-khau', methods=['GET', 'POST'])
@staff_required
def change_password():
    user = get_current_user()
    if request.method == 'POST':
        current, new, confirm = (request.form.get(k) or '' for k in ('current_password', 'new_password', 'confirm_password'))
        problem = password_problem(new)
        if not user.check_password(current):
            flash('Mật khẩu hiện tại không đúng!', 'danger')
        elif new != confirm:
            flash('Mật khẩu mới không khớp!', 'danger')
        elif problem:
            flash(problem, 'danger')
        else:
            user.set_password(new)
            user.must_change_password = False
            db.session.commit()
            flash('Đã đổi mật khẩu.', 'success')
            return redirect(url_for('admin.dashboard'))
    return render_template('admin/change_password.html')


# ---------------------------------------------------------------- dashboard

@bp.route('/')
@staff_required
def dashboard():
    return render_template('admin/dashboard.html',
                           counts={'products': Product.query.count(),
                                   'orders': Order.query.count(),
                                   'leads': Lead.query.count(),
                                   'messages': ContactMessage.query.filter_by(status='moi').count()},
                           orders=Order.query.order_by(Order.created_at.desc()).limit(8).all(),
                           leads=Lead.query.order_by(Lead.created_at.desc()).limit(8).all())


# ---------------------------------------------------------------- products

@bp.route('/san-pham/')
@staff_required
def products():
    q = Product.query
    search = (request.args.get('q') or '').strip()
    if search:
        q = q.filter(or_(Product.name.ilike(f'%{search}%'), Product.sku.ilike(f'%{search}%')))
    category_id = parse_int(request.args.get('danh_muc'))
    if category_id:
        cat = db.get_or_404(Category, category_id)
        q = q.filter(Product.categories.any(Category.id.in_(cat.descendant_ids())))
    brand_id = parse_int(request.args.get('thuong_hieu'))
    if brand_id:
        q = q.filter(Product.brands.any(Brand.id == brand_id))
    status = request.args.get('trang_thai')
    if status in ('hien', 'an'):
        q = q.filter(Product.published.is_(status == 'hien'))
    page = q.order_by(Product.updated_at.desc()).paginate(page=parse_int(request.args.get('trang'), 1), per_page=PER_PAGE, error_out=False)
    return render_template('admin/products.html', page=page, search=search, category_id=category_id,
                           brand_id=brand_id, status=status, categories=category_options(),
                           brands=Brand.query.order_by(Brand.name).all())


def category_options(exclude=None):
    """[(category, depth)] in tree order, for selects."""
    excluded = set(exclude.descendant_ids()) if exclude else set()
    by_parent = {}
    for c in Category.query.order_by(Category.position, Category.name).all():
        by_parent.setdefault(c.parent_id, []).append(c)
    out = []

    def walk(parent_id, depth):
        for c in by_parent.get(parent_id, []):
            if c.id not in excluded:
                out.append((c, depth))
                walk(c.id, depth + 1)
    walk(None, 0)
    return out


def apply_product_form(product):
    """Copy the form onto `product` (call with autoflush off). Returns an error message or None."""
    f = request.form
    errors = []
    name, sku = truncate(f.get('name'), 255), truncate(f.get('sku'), 100)
    if not name or not sku:
        errors.append('Tên và mã SKU là bắt buộc.')
    clash = Product.query.filter(func.lower(Product.sku) == sku.lower(), Product.id != product.id).first() if product.id else \
        Product.query.filter(func.lower(Product.sku) == sku.lower()).first()
    if sku and clash:
        errors.append(f'Mã SKU "{sku}" đã được dùng cho "{clash.name}".')
    product.name, product.sku = name, sku
    product.slug = unique_slug(Product, f.get('slug') or name, exclude_id=product.id)
    product.short_description = truncate(f.get('short_description'), 1000)
    product.description = sanitize_html(f.get('description'))
    product.regular_price = parse_price(f.get('regular_price'))
    product.sale_price = parse_price(f.get('sale_price'))
    product.in_stock = bool(f.get('in_stock'))
    product.published = bool(f.get('published'))
    product.featured = bool(f.get('featured'))
    product.seo_title = truncate(f.get('seo_title'), 255)
    product.seo_description = truncate(f.get('seo_description'), 500)
    ids = [parse_int(i) for i in f.getlist('categories')]
    product.categories = Category.query.filter(Category.id.in_([i for i in ids if i])).all() if ids else []
    ids = [parse_int(i) for i in f.getlist('brands')]
    product.brands = Brand.query.filter(Brand.id.in_([i for i in ids if i])).all() if ids else []

    attrs = []
    for pos, (a_name, a_value, a_visible) in enumerate(zip(f.getlist('attr_name[]'), f.getlist('attr_value[]'), f.getlist('attr_visible[]'))):
        if a_name.strip():
            attrs.append(ProductAttribute(name=truncate(a_name, 200), value=truncate(a_value, 500), visible=a_visible == '1', position=pos))
    product.attributes = attrs

    # Images: delete ticked ones, reorder, then append uploads
    remove = {parse_int(i) for i in f.getlist('image_delete')}
    product.images = [img for img in product.images if img.id not in remove]
    for img in product.images:
        img.position = parse_int(f.get(f'image_pos_{img.id}'), img.position)
    product.images.sort(key=lambda i: i.position)
    if not errors:  # don't store uploads for a form that will be rejected anyway
        try:
            for upload in request.files.getlist('images'):
                if upload and upload.filename:
                    product.images.append(ProductImage(media=save_image(upload), position=len(product.images) + 1000))
            datasheet = request.files.get('datasheet_file')
            if datasheet and datasheet.filename:
                product.datasheet_media = save_pdf(datasheet)
        except UploadError as exc:
            errors.append(str(exc))
    for pos, img in enumerate(product.images):
        img.position = pos
    if f.get('datasheet_remove'):
        product.datasheet_media = None
    url = truncate(f.get('datasheet_url'), 500)
    if url and not url.startswith(('http://', 'https://')):
        errors.append('Đường dẫn datasheet phải bắt đầu bằng http:// hoặc https://')
    product.datasheet_url = url
    return errors[0] if errors else None


def product_form(product):
    is_new = product.id is None
    if request.method == 'POST':
        with db.session.no_autoflush:
            error = apply_product_form(product)
            if error:
                # Re-render with what was typed, then discard the unsaved changes
                flash(error, 'danger')
                html = render_product_form(product, is_new)
        if error:
            db.session.rollback()
            return html, 400
        if is_new:
            db.session.add(product)
        db.session.commit()
        flash(f'Đã lưu sản phẩm "{product.name}".', 'success')
        return redirect(url_for('admin.product_edit', product_id=product.id))
    return render_product_form(product, is_new)


def render_product_form(product, is_new):
    return render_template('admin/product_form.html', product=product, is_new=is_new,
                           categories=category_options(), brands=Brand.query.order_by(Brand.name).all())


@bp.route('/san-pham/moi', methods=['GET', 'POST'])
@staff_required
def product_new():
    return product_form(Product(published=True, in_stock=True))


@bp.route('/san-pham/<int:product_id>/', methods=['GET', 'POST'])
@staff_required
def product_edit(product_id):
    return product_form(db.get_or_404(Product, product_id))


@bp.route('/san-pham/<int:product_id>/xoa', methods=['POST'])
@staff_required
def product_delete(product_id):
    product = db.get_or_404(Product, product_id)
    db.session.delete(product)
    db.session.commit()
    flash(f'Đã xóa sản phẩm "{product.name}".', 'success')
    return redirect(url_for('admin.products'))


@bp.route('/san-pham/nhap', methods=['GET', 'POST'])
@staff_required
def product_import():
    report = None
    if request.method == 'POST':
        upload = request.files.get('file')
        if not upload or not upload.filename:
            flash('Chưa chọn tệp CSV.', 'danger')
        else:
            raw = upload.read()
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = None
                flash('Tệp phải lưu dạng CSV UTF-8 (Excel: Lưu thành → "CSV UTF-8").', 'danger')
            if text is not None:
                report = import_products(text, update_existing=bool(request.form.get('update_existing')))
    return render_template('admin/product_import.html', report=report)


@bp.route('/san-pham/xuat')
@staff_required
def product_export():
    products = Product.query.order_by(Product.sku).all()
    filename = f'san-pham-{datetime.now():%Y%m%d-%H%M}.csv'
    return Response(export_products(products), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@bp.route('/media/anh', methods=['POST'])
@staff_required
def media_upload():
    """Image upload for the rich-text editor (JSON, CSRF via X-CSRFToken)."""
    try:
        media = save_image(request.files.get('file'))
    except UploadError as exc:
        return jsonify({'error': str(exc)}), 400
    db.session.commit()
    return jsonify({'url': media_url(media)})


# ---------------------------------------------------------------- categories & brands

@bp.route('/danh-muc/', methods=['GET', 'POST'])
@staff_required
def categories():
    if request.method == 'POST':
        name = truncate(request.form.get('name'), 200)
        parent = db.session.get(Category, parse_int(request.form.get('parent_id'), 0))
        if name:
            db.session.add(Category(name=name, slug=unique_slug(Category, name), parent=parent,
                                    position=parse_int(request.form.get('position'), 0)))
            db.session.commit()
            flash(f'Đã thêm danh mục "{name}".', 'success')
        return redirect(url_for('admin.categories'))
    counts = dict(db.session.query(Category.id, func.count(Product.id)).outerjoin(Category.products).group_by(Category.id).all())
    return render_template('admin/categories.html', categories=category_options(), counts=counts)


@bp.route('/danh-muc/<int:category_id>/', methods=['GET', 'POST'])
@staff_required
def category_edit(category_id):
    cat = db.get_or_404(Category, category_id)
    if request.method == 'POST':
        name = truncate(request.form.get('name'), 200)
        parent_id = parse_int(request.form.get('parent_id'), 0) or None
        if parent_id in cat.descendant_ids():
            flash('Không thể chọn danh mục con làm danh mục cha.', 'danger')
        elif name:
            cat.name = name
            cat.slug = unique_slug(Category, request.form.get('slug') or name, exclude_id=cat.id)
            cat.parent_id = parent_id
            cat.position = parse_int(request.form.get('position'), 0)
            db.session.commit()
            flash('Đã lưu danh mục.', 'success')
            return redirect(url_for('admin.categories'))
    return render_template('admin/category_form.html', category=cat, parents=category_options(exclude=cat))


@bp.route('/danh-muc/<int:category_id>/xoa', methods=['POST'])
@staff_required
def category_delete(category_id):
    cat = db.get_or_404(Category, category_id)
    for child in list(cat.children):
        child.parent_id = cat.parent_id
    cat.products = []
    db.session.delete(cat)
    db.session.commit()
    flash(f'Đã xóa danh mục "{cat.name}" (sản phẩm vẫn được giữ).', 'success')
    return redirect(url_for('admin.categories'))


@bp.route('/thuong-hieu/', methods=['GET', 'POST'])
@staff_required
def brands():
    if request.method == 'POST':
        name = truncate(request.form.get('name'), 200)
        if name and Brand.query.filter(func.lower(Brand.name) == name.lower()).first():
            flash(f'Thương hiệu "{name}" đã tồn tại.', 'danger')
        elif name:
            db.session.add(Brand(name=name, slug=unique_slug(Brand, name)))
            db.session.commit()
            flash(f'Đã thêm thương hiệu "{name}".', 'success')
        return redirect(url_for('admin.brands'))
    counts = dict(db.session.query(Brand.id, func.count(Product.id)).outerjoin(Brand.products).group_by(Brand.id).all())
    return render_template('admin/brands.html', brands=Brand.query.order_by(Brand.name).all(), counts=counts)


@bp.route('/thuong-hieu/<int:brand_id>/', methods=['POST'])
@staff_required
def brand_edit(brand_id):
    brand = db.get_or_404(Brand, brand_id)
    name = truncate(request.form.get('name'), 200)
    if name and Brand.query.filter(func.lower(Brand.name) == name.lower(), Brand.id != brand.id).first():
        flash(f'Thương hiệu "{name}" đã tồn tại.', 'danger')
    elif name:
        brand.name = name
        brand.slug = unique_slug(Brand, name, exclude_id=brand.id)
        db.session.commit()
        flash('Đã lưu thương hiệu.', 'success')
    return redirect(url_for('admin.brands'))


@bp.route('/thuong-hieu/<int:brand_id>/xoa', methods=['POST'])
@staff_required
def brand_delete(brand_id):
    brand = db.get_or_404(Brand, brand_id)
    brand.products = []
    db.session.delete(brand)
    db.session.commit()
    flash(f'Đã xóa thương hiệu "{brand.name}".', 'success')
    return redirect(url_for('admin.brands'))


# ---------------------------------------------------------------- orders, leads, messages

def status_filtered(model, statuses):
    q = model.query
    status = request.args.get('trang_thai')
    if status in statuses:
        q = q.filter_by(status=status)
    search = (request.args.get('q') or '').strip()
    if search:
        cols = [model.name.ilike(f'%{search}%'), model.phone.ilike(f'%{search}%')]
        if model is Order:
            cols.append(Order.code.ilike(f'%{search}%'))
        q = q.filter(or_(*cols))
    page = q.order_by(model.created_at.desc()).paginate(page=parse_int(request.args.get('trang'), 1), per_page=PER_PAGE, error_out=False)
    return page, status, search


def update_status(obj, statuses):
    status = request.form.get('status')
    if status in statuses:
        obj.status = status
        db.session.commit()
        flash('Đã cập nhật trạng thái.', 'success')


@bp.route('/don-hang/')
@staff_required
def orders():
    page, status, search = status_filtered(Order, ORDER_STATUSES)
    return render_template('admin/orders.html', page=page, status=status, search=search)


@bp.route('/don-hang/<int:order_id>/', methods=['GET', 'POST'])
@staff_required
def order_detail(order_id):
    order = db.get_or_404(Order, order_id)
    if request.method == 'POST':
        update_status(order, ORDER_STATUSES)
        return redirect(url_for('admin.order_detail', order_id=order.id))
    return render_template('admin/order_detail.html', order=order)


@bp.route('/tu-van/')
@staff_required
def leads():
    page, status, search = status_filtered(Lead, LEAD_STATUSES)
    return render_template('admin/leads.html', page=page, status=status, search=search)


@bp.route('/tu-van/<int:lead_id>/', methods=['GET', 'POST'])
@staff_required
def lead_detail(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    if request.method == 'POST':
        update_status(lead, LEAD_STATUSES)
        return redirect(url_for('admin.lead_detail', lead_id=lead.id))
    return render_template('admin/lead_detail.html', lead=lead, fields=LEAD_FIELDS)


@bp.route('/tu-van/<int:lead_id>/xoa', methods=['POST'])
@admin_required
def lead_delete(lead_id):
    db.session.delete(db.get_or_404(Lead, lead_id))
    db.session.commit()
    flash('Đã xóa yêu cầu tư vấn.', 'success')
    return redirect(url_for('admin.leads'))


@bp.route('/lien-he/')
@staff_required
def messages():
    page, status, search = status_filtered(ContactMessage, LEAD_STATUSES)
    return render_template('admin/messages.html', page=page, status=status, search=search)


@bp.route('/lien-he/<int:message_id>/', methods=['GET', 'POST'])
@staff_required
def message_detail(message_id):
    msg = db.get_or_404(ContactMessage, message_id)
    if request.method == 'POST':
        update_status(msg, LEAD_STATUSES)
        return redirect(url_for('admin.message_detail', message_id=msg.id))
    return render_template('admin/message_detail.html', msg=msg)


@bp.route('/lien-he/<int:message_id>/xoa', methods=['POST'])
@admin_required
def message_delete(message_id):
    db.session.delete(db.get_or_404(ContactMessage, message_id))
    db.session.commit()
    flash('Đã xóa tin nhắn.', 'success')
    return redirect(url_for('admin.messages'))


# ---------------------------------------------------------------- posts (projects, news, pages)

def check_kind(kind):
    if kind not in POST_KINDS:
        abort(404)


@bp.route('/noi-dung/<kind>/')
@staff_required
def posts(kind):
    check_kind(kind)
    page = Post.query.filter_by(kind=kind).order_by(Post.created_at.desc()).paginate(
        page=parse_int(request.args.get('trang'), 1), per_page=PER_PAGE, error_out=False)
    return render_template('admin/posts.html', page=page, kind=kind)


def apply_post_form(post):
    """Copy the form onto `post` (call with autoflush off). Returns an error message or None."""
    f = request.form
    errors = []
    post.title = truncate(f.get('title'), 255)
    if not post.title:
        errors.append('Tiêu đề là bắt buộc.')
    post.slug = unique_slug(Post, f.get('slug') or post.title, exclude_id=post.id, extra_filter=Post.kind == post.kind)
    post.excerpt = truncate(f.get('excerpt'), 1000)
    post.content = sanitize_html(f.get('content'))
    post.published = bool(f.get('published'))
    post.seo_title = truncate(f.get('seo_title'), 255)
    post.seo_description = truncate(f.get('seo_description'), 500)
    created = (f.get('created_at') or '').strip()
    if created:
        try:
            post.created_at = datetime.strptime(created, '%Y-%m-%d')
        except ValueError:
            errors.append('Ngày đăng không hợp lệ.')
    if f.get('thumbnail_remove'):
        post.thumbnail = None
    thumb = request.files.get('thumbnail')
    if not errors and thumb and thumb.filename:
        try:
            post.thumbnail = save_image(thumb)
        except UploadError as exc:
            errors.append(str(exc))
    return errors[0] if errors else None


def post_form(post):
    is_new = post.id is None
    if request.method == 'POST':
        with db.session.no_autoflush:
            error = apply_post_form(post)
            if error:
                flash(error, 'danger')
                html = render_template('admin/post_form.html', post=post, is_new=is_new)
        if error:
            db.session.rollback()
            return html, 400
        if is_new:
            db.session.add(post)
        db.session.commit()
        flash(f'Đã lưu "{post.title}".', 'success')
        return redirect(url_for('admin.post_edit', kind=post.kind, post_id=post.id))
    return render_template('admin/post_form.html', post=post, is_new=is_new)


@bp.route('/noi-dung/<kind>/moi', methods=['GET', 'POST'])
@staff_required
def post_new(kind):
    check_kind(kind)
    return post_form(Post(kind=kind, published=True))


@bp.route('/noi-dung/<kind>/<int:post_id>/', methods=['GET', 'POST'])
@staff_required
def post_edit(kind, post_id):
    post = db.get_or_404(Post, post_id)
    if post.kind != kind:
        abort(404)
    return post_form(post)


@bp.route('/noi-dung/<kind>/<int:post_id>/xoa', methods=['POST'])
@staff_required
def post_delete(kind, post_id):
    post = db.get_or_404(Post, post_id)
    db.session.delete(post)
    db.session.commit()
    flash(f'Đã xóa "{post.title}".', 'success')
    return redirect(url_for('admin.posts', kind=post.kind))


# ---------------------------------------------------------------- settings (admin only)

SITE_FIELDS = {
    'site_name': 'Tên website',
    'hotline': 'Hotline',
    'zalo': 'Số Zalo',
    'address': 'Địa chỉ (hiện ở chân trang)',
    'admin_email': 'Email nhận thông báo (đơn hàng, tư vấn)',
    'turnstile_site_key': 'Cloudflare Turnstile – Site key',
    'turnstile_secret': 'Cloudflare Turnstile – Secret key',
}


@bp.route('/cai-dat/', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        for key in SITE_FIELDS:
            value = truncate(request.form.get(key), 300)
            if key in ('hotline', 'zalo'):
                value = digits_only(value)
            if key == 'turnstile_secret' and not value:
                continue  # blank = keep the stored secret
            set_setting(key, value)
        if request.form.get('turnstile_clear'):
            set_setting('turnstile_site_key', '')
            set_setting('turnstile_secret', '')
        db.session.commit()
        flash('Đã lưu cài đặt.', 'success')
        return redirect(url_for('admin.settings'))
    values = {k: get_setting(k) or '' for k in SITE_FIELDS}
    has_secret = bool(values.pop('turnstile_secret'))
    return render_template('admin/settings.html', fields=SITE_FIELDS, values=values, has_secret=has_secret)


@bp.route('/cai-dat/tinh-dien', methods=['GET', 'POST'])
@admin_required
def calc_settings_view():
    if request.method == 'POST':
        set_setting('calculator', sanitize_calc(request.form))
        db.session.commit()
        flash('Đã lưu cài đặt công cụ tính.', 'success')
        return redirect(url_for('admin.calc_settings_view'))
    return render_template('admin/calc_settings.html', labels=CALC_LABELS, values=calc_settings())


# ---------------------------------------------------------------- users (admin only)

@bp.route('/nguoi-dung/', methods=['GET', 'POST'])
@admin_required
def users():
    if request.method == 'POST':
        username = truncate(request.form.get('username'), 100)
        password = request.form.get('password') or ''
        role = request.form.get('role')
        problem = password_problem(password)
        if not username or role not in ROLES:
            flash('Vui lòng nhập tên đăng nhập và chọn vai trò.', 'danger')
        elif problem:
            flash(problem, 'danger')
        elif User.query.filter(func.lower(User.username) == username.lower()).first():
            flash('Tên đăng nhập đã tồn tại!', 'danger')
        else:
            new_user = User(username=username, role=role, must_change_password=True)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Đã tạo người dùng {username}. Họ sẽ phải đổi mật khẩu khi đăng nhập lần đầu.', 'success')
        return redirect(url_for('admin.users'))
    return render_template('admin/users.html', users=User.query.order_by(User.username).all())


@bp.route('/nguoi-dung/<int:user_id>/', methods=['POST'])
@admin_required
def user_update(user_id):
    target = db.get_or_404(User, user_id)
    me = get_current_user()
    action = request.form.get('action')
    if action == 'role':
        role = request.form.get('role')
        if target.id == me.id:
            flash('Bạn không thể đổi vai trò của chính mình!', 'danger')
        elif role in ROLES:
            target.role = role
            db.session.commit()
            flash(f'Đã đổi vai trò của {target.username}.', 'success')
    elif action == 'password':
        password = request.form.get('password') or ''
        problem = password_problem(password)
        if problem:
            flash(problem, 'danger')
        else:
            target.set_password(password)
            target.must_change_password = target.id != me.id
            db.session.commit()
            flash(f'Đã đặt lại mật khẩu cho {target.username}.', 'success')
    elif action == 'delete':
        if target.id == me.id:
            flash('Bạn không thể xóa tài khoản của chính mình!', 'danger')
        else:
            db.session.delete(target)
            db.session.commit()
            flash(f'Đã xóa người dùng {target.username}.', 'success')
    return redirect(url_for('admin.users'))
