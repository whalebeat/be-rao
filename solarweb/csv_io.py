"""Product CSV import/export in WooCommerce's column format (see seed/products.csv)."""
import csv
import io
import re

from .content import text_to_html
from .models import Brand, Category, Product, ProductAttribute, ProductImage, db
from .utils import get_or_create, parse_price, unique_slug

BASE_COLUMNS = ['Type', 'SKU', 'Name', 'Published', 'Is featured?', 'Visibility in catalog',
                'Short description', 'Description', 'In stock?', 'Sale price', 'Regular price',
                'Categories', 'Brands', 'Images']
DATASHEET_COLUMN = 'Meta: _solarweb_datasheet'
BRAND_COLUMNS = ('Brands', 'Thương hiệu')
TRUE_VALUES = {'1', 'yes', 'true', 'có', 'x'}


def _truthy(value, default=False):
    value = (value or '').strip().lower()
    if not value:
        return default
    return value in TRUE_VALUES


def _split_list(value):
    return [v.strip() for v in (value or '').split(',') if v.strip()]


def category_from_path(path):
    """'Inverter > Inverter 1 pha' -> leaf Category, creating parents as needed."""
    parent = None
    for name in [p.strip() for p in path.split('>') if p.strip()]:
        q = Category.query.filter(db.func.lower(Category.name) == name.lower())
        q = q.filter(Category.parent_id.is_(None)) if parent is None else q.filter(Category.parent_id == parent.id)
        node = q.first()
        if not node:
            node = Category(name=name, slug=unique_slug(Category, name), parent=parent)
            db.session.add(node)
            db.session.flush()
        parent = node
    return parent


def _attribute_numbers(headers):
    numbers = sorted({int(m.group(1)) for h in headers if (m := re.match(r'Attribute (\d+) name$', h))})
    return numbers


def import_products(text, update_existing=False):
    """Returns {'created': n, 'updated': n, 'skipped': n, 'errors': [(line, message)]}."""
    reader = csv.DictReader(io.StringIO(text.lstrip('﻿')))
    headers = reader.fieldnames or []
    report = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}
    if 'SKU' not in headers or 'Name' not in headers:
        report['errors'].append((1, 'Thiếu cột SKU hoặc Name. Hãy dùng mẫu seed/products.csv.'))
        return report
    attr_numbers = _attribute_numbers(headers)
    brand_column = next((c for c in BRAND_COLUMNS if c in headers), None)

    for line, row in enumerate(reader, start=2):
        sku = (row.get('SKU') or '').strip()
        name = (row.get('Name') or '').strip()
        if (row.get('Type') or 'simple').strip().lower() not in ('simple', ''):
            report['skipped'] += 1
            report['errors'].append((line, f'{sku}: chỉ hỗ trợ sản phẩm loại "simple".'))
            continue
        if not sku or not name:
            report['skipped'] += 1
            report['errors'].append((line, 'Thiếu SKU hoặc tên sản phẩm.'))
            continue
        product = Product.query.filter_by(sku=sku).first()
        if product and not update_existing:
            report['skipped'] += 1
            report['errors'].append((line, f'{sku}: đã tồn tại (tick "Cập nhật sản phẩm có sẵn" để cập nhật).'))
            continue
        try:
            with db.session.begin_nested():
                created = product is None
                if created:
                    product = Product(sku=sku, name=name, slug=unique_slug(Product, name))
                    db.session.add(product)
                product.name = name
                if 'Published' in row:
                    product.published = (row.get('Published') or '').strip() == '1' and \
                        (row.get('Visibility in catalog') or 'visible').strip() != 'hidden'
                if 'Is featured?' in row:
                    product.featured = _truthy(row.get('Is featured?'))
                if 'In stock?' in row:
                    product.in_stock = _truthy(row.get('In stock?'), default=True)
                if 'Short description' in row:
                    product.short_description = (row.get('Short description') or '').strip()
                if 'Description' in row:
                    product.description = text_to_html(row.get('Description'))
                if 'Regular price' in row:
                    product.regular_price = parse_price(row.get('Regular price'))
                if 'Sale price' in row:
                    product.sale_price = parse_price(row.get('Sale price'))
                if 'Categories' in row:
                    product.categories = [c for c in (category_from_path(p) for p in _split_list(row.get('Categories'))) if c]
                if brand_column:
                    product.brands = [get_or_create(Brand, b) for b in _split_list(row.get(brand_column))]
                if DATASHEET_COLUMN in row:
                    product.datasheet_url = (row.get(DATASHEET_COLUMN) or '').strip()
                if (row.get('Images') or '').strip():
                    # Replace external images; uploaded ones are kept
                    product.images = [i for i in product.images if i.media_id]
                    start = len(product.images)
                    for pos, url in enumerate(_split_list(row.get('Images'))):
                        if url.startswith(('http://', 'https://')):
                            product.images.append(ProductImage(url=url, position=start + pos))
                attrs = []
                for n in attr_numbers:
                    attr_name = (row.get(f'Attribute {n} name') or '').strip()
                    if attr_name:
                        attrs.append(ProductAttribute(
                            name=attr_name, value=(row.get(f'Attribute {n} value(s)') or '').strip(),
                            visible=_truthy(row.get(f'Attribute {n} visible'), default=True), position=n))
                if attrs:
                    product.attributes = attrs
                db.session.flush()
            report['created' if created else 'updated'] += 1
        except Exception as exc:
            report['skipped'] += 1
            report['errors'].append((line, f'{sku}: {exc}'))
    db.session.commit()
    return report


def export_products(products):
    max_attrs = max((len(p.attributes) for p in products), default=0)
    headers = list(BASE_COLUMNS)
    for n in range(1, max_attrs + 1):
        headers += [f'Attribute {n} name', f'Attribute {n} value(s)', f'Attribute {n} visible', f'Attribute {n} global']
    headers.append(DATASHEET_COLUMN)

    out = io.StringIO()
    out.write('﻿')  # so Excel opens it as UTF-8
    writer = csv.writer(out)
    writer.writerow(headers)
    for p in products:
        row = ['simple', p.sku, p.name, '1' if p.published else '0', '1' if p.featured else '0', 'visible',
               p.short_description or '', p.description or '', '1' if p.in_stock else '0',
               '' if p.sale_price is None else p.sale_price, '' if p.regular_price is None else p.regular_price,
               ', '.join(c.path() for c in p.categories), ', '.join(b.name for b in p.brands),
               ', '.join(i.url for i in p.images if i.url)]
        for n in range(max_attrs):
            if n < len(p.attributes):
                a = p.attributes[n]
                row += [a.name, a.value, '1' if a.visible else '0', '0']
            else:
                row += ['', '', '', '']
        row.append(p.datasheet_url or '')
        writer.writerow(row)
    return out.getvalue()
