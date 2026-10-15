"""Session cart and order-request checkout (COD only, no online payment)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..mailer import send_admin_mail
from ..models import Order, OrderItem, Product, db
from ..security import client_ip, limiter, turnstile_verify
from ..utils import PHONE_RE, clean_phone, parse_int, truncate, vnd

bp = Blueprint('cart', __name__)

MAX_QTY = 9999
MAX_LINES = 50
ORDER_LIMIT = 5
ORDER_WINDOW = 60 * 60
CHECKOUT_FIELDS = ('name', 'phone', 'address', 'city', 'email', 'note')


def _cart():
    raw = session.get('cart')
    return raw if isinstance(raw, dict) else {}


def _save(cart):
    session['cart'] = cart
    session.permanent = True


def cart_count():
    return sum(q for q in _cart().values() if isinstance(q, int))


def cart_lines():
    """[(product, qty, subtotal_or_None)], dropping products that no longer exist or are hidden."""
    cart = _cart()
    ids = [parse_int(pid) for pid in cart]
    products = {p.id: p for p in Product.query.filter(Product.id.in_([i for i in ids if i]), Product.published.is_(True)).all()} if ids else {}
    lines = []
    for pid, qty in cart.items():
        product = products.get(parse_int(pid))
        if product and isinstance(qty, int) and qty > 0:
            lines.append((product, qty, None if product.price is None else product.price * qty))
    return lines


def cart_totals(lines):
    known = sum(sub for _, _, sub in lines if sub is not None)
    has_contact = any(sub is None for _, _, sub in lines)
    return known, has_contact


def _safe_next(default):
    """`next` is a path within this app (no mount prefix); `default` is a url_for result."""
    target = request.form.get('next') or ''
    return request.script_root + target if target.startswith('/') and not target.startswith('//') else default


@bp.route('/gio-hang/')
def view():
    lines = cart_lines()
    known, has_contact = cart_totals(lines)
    return render_template('cart.html', lines=lines, total_known=known, has_contact=has_contact)


@bp.route('/gio-hang/them', methods=['POST'])
def add():
    product = Product.query.filter_by(id=parse_int(request.form.get('product_id')), published=True).first()
    if not product:
        abort(404)
    qty = max(1, min(MAX_QTY, parse_int(request.form.get('qty'), 1)))
    cart = _cart()
    if str(product.id) not in cart and len(cart) >= MAX_LINES:
        flash('Giỏ hàng đã đầy.', 'warning')
        return redirect(url_for('cart.view'))
    cart[str(product.id)] = min(MAX_QTY, cart.get(str(product.id), 0) + qty)
    _save(cart)
    flash(f'Đã thêm "{product.name}" vào giỏ hàng.', 'success')
    return redirect(_safe_next(url_for('cart.view')))


@bp.route('/gio-hang/cap-nhat', methods=['POST'])
def update():
    cart = {}
    for pid, qty in _cart().items():
        new_qty = parse_int(request.form.get(f'qty_{pid}'), qty)
        if new_qty and new_qty > 0:
            cart[pid] = min(MAX_QTY, new_qty)
    _save(cart)
    flash('Đã cập nhật giỏ hàng.', 'success')
    return redirect(url_for('cart.view'))


@bp.route('/gio-hang/xoa', methods=['POST'])
def remove():
    cart = _cart()
    cart.pop(str(parse_int(request.form.get('product_id'))), None)
    _save(cart)
    return redirect(url_for('cart.view'))


@bp.route('/dat-hang/', methods=['GET', 'POST'])
def checkout():
    lines = cart_lines()
    if not lines:
        flash('Giỏ hàng đang trống.', 'warning')
        return redirect(url_for('cart.view'))
    known, has_contact = cart_totals(lines)
    form = {k: request.form.get(k, '') for k in CHECKOUT_FIELDS}
    if request.method == 'POST':
        data = {
            'name': truncate(form['name'], 100),
            'phone': clean_phone(form['phone']),
            'address': truncate(form['address'], 300),
            'city': truncate(form['city'], 100),
            'email': truncate(form['email'], 200),
            'note': truncate(form['note'], 2000),
        }
        error = None
        if not data['name'] or not data['address'] or not data['city']:
            error = 'Vui lòng nhập đủ họ tên, địa chỉ và tỉnh/thành phố.'
        elif not PHONE_RE.match(data['phone']):
            error = 'Số điện thoại không hợp lệ.'
        elif data['email'] and '@' not in data['email']:
            error = 'Email không hợp lệ.'
        elif not limiter.hit(f'order|{client_ip()}', ORDER_LIMIT, ORDER_WINDOW):
            error = 'Bạn đã gửi quá nhiều đơn, vui lòng gọi hotline hoặc thử lại sau.'
        elif not turnstile_verify(request.form.get('cf-turnstile-response')):
            error = 'Vui lòng xác nhận bạn không phải robot rồi gửi lại.'
        if error:
            flash(error, 'danger')
            return render_template('checkout.html', lines=lines, total_known=known, has_contact=has_contact, form=form), 400

        order = Order(total_known=known, has_contact_price=has_contact, **data)
        order.items = [OrderItem(product_id=p.id, sku=p.sku, name=p.name, unit_price=p.price, qty=q) for p, q, _ in lines]
        db.session.add(order)
        db.session.flush()
        order.code = f'SW{order.id:06d}'
        db.session.commit()

        body = [f'Mã đơn: {order.code}', f'Khách hàng: {order.name}', f'SĐT: {order.phone}',
                f'Địa chỉ: {order.address}, {order.city}', f'Email: {order.email or "—"}', f'Ghi chú: {order.note or "—"}', '']
        for item in order.items:
            price = 'Liên hệ' if item.unit_price is None else vnd(item.subtotal)
            body.append(f'- {item.name} ({item.sku}) x{item.qty}: {price}')
        body += ['', f'Tạm tính: {vnd(known)}' + (' + các sản phẩm giá liên hệ' if has_contact else ''),
                 url_for('admin.order_detail', order_id=order.id, _external=True)]
        send_admin_mail(f'Yêu cầu đặt hàng {order.code}: {order.name}', '\n'.join(body))

        session['cart'] = {}
        session['last_order'] = order.code
        return redirect(url_for('cart.done', code=order.code))
    return render_template('checkout.html', lines=lines, total_known=known, has_contact=has_contact, form=form)


@bp.route('/dat-hang/thanh-cong/<code>')
def done(code):
    # Only the visitor who placed the order can see it
    if session.get('last_order') != code:
        abort(404)
    order = Order.query.filter_by(code=code).first_or_404()
    return render_template('order_done.html', order=order)
