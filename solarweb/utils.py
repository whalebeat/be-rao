"""Small helpers shared across blueprints."""
import re
import unicodedata

from sqlalchemy import func

PHONE_RE = re.compile(r'^\+?\d{9,12}$')


def slugify(text):
    """ASCII slug for Vietnamese text: 'Tấm pin Đông Á' -> 'tam-pin-dong-a'."""
    text = (text or '').replace('đ', 'd').replace('Đ', 'D')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
    return text[:180] or 'muc'


def unique_slug(model, text, exclude_id=None, extra_filter=None):
    """slugify(text), suffixed with -2, -3… until no other row of `model` uses it."""
    base = slugify(text)
    slug, n = base, 2
    while True:
        q = model.query.filter(model.slug == slug)
        if extra_filter is not None:
            q = q.filter(extra_filter)
        if exclude_id is not None:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f'{base}-{n}'
        n += 1


def vnd(amount):
    """16500000 -> '16.500.000đ'."""
    if amount is None:
        return ''
    return f'{int(round(amount)):,}'.replace(',', '.') + 'đ'


def parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_price(value):
    """'16.500.000đ' / '16500000' -> 16500000; blank -> None (shown as 'Liên hệ')."""
    digits = re.sub(r'\D', '', str(value or ''))
    return int(digits) if digits else None


def clean_phone(value):
    return re.sub(r'[^\d+]', '', str(value or ''))


def digits_only(value):
    return re.sub(r'\D+', '', str(value or ''))


def truncate(value, length):
    return str(value or '').strip()[:length]


def get_or_create(model, name, **extra):
    """Find a row by name (case-insensitive) or create it. Returns None for blank names."""
    from .models import db
    name = (name or '').strip()
    if not name:
        return None
    obj = model.query.filter(func.lower(model.name) == name.lower()).filter_by(**extra).first()
    if not obj:
        obj = model(name=name, slug=unique_slug(model, name), **extra)
        db.session.add(obj)
        db.session.flush()
    return obj
