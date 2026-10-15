import secrets
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from . import env

db = SQLAlchemy()


def utcnow():
    """Naive UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


product_category = db.Table('sw_product_category',
    db.Column('product_id', db.Integer, db.ForeignKey('sw_product.id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('sw_category.id', ondelete='CASCADE'), primary_key=True),
)

product_brand = db.Table('sw_product_brand',
    db.Column('product_id', db.Integer, db.ForeignKey('sw_product.id', ondelete='CASCADE'), primary_key=True),
    db.Column('brand_id', db.Integer, db.ForeignKey('sw_brand.id', ondelete='CASCADE'), primary_key=True),
)


class User(db.Model):
    __tablename__ = 'sw_user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='staff', nullable=False)  # 'admin' or 'staff'
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password or '')


class Category(db.Model):
    __tablename__ = 'sw_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('sw_category.id', ondelete='SET NULL'))
    position = db.Column(db.Integer, default=0, nullable=False)
    parent = db.relationship('Category', remote_side=[id], backref='children')

    def path(self):
        """'Inverter > Inverter 1 pha' (CSV format)."""
        names, node = [], self
        while node is not None and len(names) < 10:
            names.insert(0, node.name)
            node = node.parent
        return ' > '.join(names)

    def descendant_ids(self):
        ids, stack = [], [self]
        while stack:
            node = stack.pop()
            ids.append(node.id)
            stack.extend(node.children)
        return ids


class Brand(db.Model):
    __tablename__ = 'sw_brand'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)


class MediaFile(db.Model):
    """Uploaded images/PDFs, stored in the database (Render free has no persistent disk)."""
    __tablename__ = 'sw_media_file'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), index=True, nullable=False)
    data = db.deferred(db.Column(db.LargeBinary, nullable=False))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class Product(db.Model):
    __tablename__ = 'sw_product'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    short_description = db.Column(db.Text, default='')
    description = db.Column(db.Text, default='')  # sanitized HTML
    regular_price = db.Column(db.BigInteger)  # None = "Liên hệ"
    sale_price = db.Column(db.BigInteger)
    in_stock = db.Column(db.Boolean, default=True, nullable=False)
    published = db.Column(db.Boolean, default=True, nullable=False)
    featured = db.Column(db.Boolean, default=False, nullable=False)
    datasheet_url = db.Column(db.String(500), default='')
    datasheet_media_id = db.Column(db.Integer, db.ForeignKey('sw_media_file.id', ondelete='SET NULL'))
    seo_title = db.Column(db.String(255), default='')
    seo_description = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    categories = db.relationship('Category', secondary=product_category, backref='products')
    brands = db.relationship('Brand', secondary=product_brand, backref='products')
    attributes = db.relationship('ProductAttribute', order_by='ProductAttribute.position',
                                 cascade='all, delete-orphan', backref='product')
    images = db.relationship('ProductImage', order_by='ProductImage.position',
                             cascade='all, delete-orphan', backref='product')
    datasheet_media = db.relationship('MediaFile', foreign_keys=[datasheet_media_id])

    @property
    def has_no_price(self):
        return self.regular_price is None and self.sale_price is None

    @property
    def on_sale(self):
        return self.sale_price is not None and (self.regular_price is None or self.sale_price < self.regular_price)

    @property
    def price(self):
        """Price used in the cart; None means 'Liên hệ'."""
        return self.sale_price if self.on_sale else self.regular_price


class ProductAttribute(db.Model):
    __tablename__ = 'sw_product_attribute'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('sw_product.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    value = db.Column(db.String(500), default='')
    position = db.Column(db.Integer, default=0, nullable=False)
    visible = db.Column(db.Boolean, default=True, nullable=False)


class ProductImage(db.Model):
    __tablename__ = 'sw_product_image'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('sw_product.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    media_id = db.Column(db.Integer, db.ForeignKey('sw_media_file.id', ondelete='CASCADE'))
    url = db.Column(db.String(500), default='')  # external image (e.g. from CSV import)
    media = db.relationship('MediaFile')


ORDER_STATUSES = {'moi': 'Mới', 'da_lien_he': 'Đã liên hệ', 'hoan_tat': 'Hoàn tất', 'huy': 'Đã hủy'}
LEAD_STATUSES = {'moi': 'Mới', 'da_lien_he': 'Đã liên hệ', 'xong': 'Đã xử lý'}


class Order(db.Model):
    __tablename__ = 'sw_order'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), default='')
    note = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='moi', nullable=False)
    total_known = db.Column(db.BigInteger, default=0, nullable=False)
    has_contact_price = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    items = db.relationship('OrderItem', cascade='all, delete-orphan', backref='order')


class OrderItem(db.Model):
    __tablename__ = 'sw_order_item'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('sw_order.id', ondelete='CASCADE'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('sw_product.id', ondelete='SET NULL'))
    sku = db.Column(db.String(100), default='')
    name = db.Column(db.String(255), nullable=False)
    unit_price = db.Column(db.BigInteger)  # None = "Liên hệ"
    qty = db.Column(db.Integer, nullable=False)

    @property
    def subtotal(self):
        return None if self.unit_price is None else self.unit_price * self.qty


class Lead(db.Model):
    """Yêu cầu tư vấn from the solar calculator."""
    __tablename__ = 'sw_lead'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    province = db.Column(db.String(300), default='')
    bill = db.Column(db.String(300), default='')
    customer = db.Column(db.String(300), default='')
    system = db.Column(db.String(300), default='')
    price = db.Column(db.String(300), default='')
    savings = db.Column(db.String(300), default='')
    payback = db.Column(db.String(300), default='')
    note = db.Column(db.String(300), default='')
    consent = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='moi', nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# Label for each lead field, in display order (SOLARWEB_LEAD_FIELDS in the PHP plugin)
LEAD_FIELDS = {
    'phone': 'SĐT / Zalo',
    'province': 'Tỉnh/thành',
    'bill': 'Hóa đơn/tháng',
    'customer': 'Loại khách hàng',
    'system': 'Hệ thống đề xuất',
    'price': 'Giá ước tính',
    'savings': 'Tiết kiệm/tháng',
    'payback': 'Hoàn vốn',
    'note': 'Ghi chú',
    'consent': 'Đồng ý xử lý dữ liệu',
}


class ContactMessage(db.Model):
    __tablename__ = 'sw_contact_message'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(200), default='')
    message = db.Column(db.Text, default='')
    consent = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='moi', nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


POST_KINDS = {'project': 'Dự án', 'news': 'Tin tức', 'page': 'Trang'}


class Post(db.Model):
    __tablename__ = 'sw_post'
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(200), nullable=False)
    excerpt = db.Column(db.Text, default='')
    content = db.Column(db.Text, default='')  # sanitized HTML
    thumbnail_media_id = db.Column(db.Integer, db.ForeignKey('sw_media_file.id', ondelete='SET NULL'))
    published = db.Column(db.Boolean, default=True, nullable=False)
    seo_title = db.Column(db.String(255), default='')
    seo_description = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    thumbnail = db.relationship('MediaFile')
    __table_args__ = (db.UniqueConstraint('kind', 'slug'),)


class Setting(db.Model):
    __tablename__ = 'sw_setting'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.JSON)


def init_db():
    db.create_all()
    # Create the first admin user if there are no admins yet
    if not User.query.filter_by(role='admin').first():
        username = env('ADMIN_USERNAME', 'admin')
        password = env('ADMIN_PASSWORD')
        generated = not password
        if generated:
            password = secrets.token_urlsafe(12)
            print(f"Created admin user '{username}' with generated password: {password}")
        admin = User.query.filter_by(username=username).first() or User(username=username)
        admin.role = 'admin'
        admin.must_change_password = generated
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
