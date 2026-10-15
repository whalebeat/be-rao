"""Uploads stored in the database as MediaFile rows.

Images are re-encoded (which also strips EXIF/GPS and any embedded payload)
and scaled down so the free-tier database stays small.
"""
import hashlib
import io
import os
import warnings

from flask import url_for
from PIL import Image, UnidentifiedImageError

from .models import MediaFile, db
from .utils import slugify

IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
IMAGE_MAX_SIDE = 1600
IMAGE_QUALITY = 82
PDF_MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs


class UploadError(ValueError):
    pass


def _store(data, filename, content_type):
    digest = hashlib.sha256(data).hexdigest()
    existing = MediaFile.query.filter_by(sha256=digest, content_type=content_type).first()
    if existing:
        return existing
    media = MediaFile(filename=filename, content_type=content_type, size=len(data), sha256=digest, data=data)
    db.session.add(media)
    db.session.flush()
    return media


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        raise UploadError('Chưa chọn ảnh.')
    raw = file_storage.read()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            if Image.MIME.get(img.format) not in IMAGE_TYPES:
                raise UploadError('Chỉ nhận ảnh JPEG, PNG hoặc WebP.')
            img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError):
        raise UploadError('Tệp ảnh không hợp lệ hoặc quá lớn.')
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert('RGB')
    img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=IMAGE_QUALITY, optimize=True, progressive=True)
    name = slugify(os.path.splitext(file_storage.filename)[0])[:80] + '.jpg'
    return _store(out.getvalue(), name, 'image/jpeg')


def save_pdf(file_storage):
    if not file_storage or not file_storage.filename:
        raise UploadError('Chưa chọn tệp PDF.')
    data = file_storage.read(PDF_MAX_BYTES + 1)
    if len(data) > PDF_MAX_BYTES:
        raise UploadError('Tệp PDF tối đa 10 MB.')
    if not data.startswith(b'%PDF-'):
        raise UploadError('Tệp không phải PDF.')
    name = slugify(os.path.splitext(file_storage.filename)[0])[:80] + '.pdf'
    return _store(data, name, 'application/pdf')


def media_url(media, external=False):
    if media is None:
        return ''
    return url_for('public.media', media_id=media.id, filename=media.filename, _external=external)


def image_src(image, external=False):
    """URL for a ProductImage (uploaded or external)."""
    if image is None:
        return ''
    return media_url(image.media, external) if image.media_id else image.url
