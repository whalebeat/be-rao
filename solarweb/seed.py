"""Demo content (port of SolarWeb's seed/seed.php). Safe to run more than once:
products are updated by SKU, and pages/projects are only created if missing.

    python -m solarweb.seed
"""
import os

from . import create_app
from .csv_io import import_products
from .models import Post, db

HERE = os.path.dirname(os.path.abspath(__file__))

PAGES = {
    'gioi-thieu': ('Giới thiệu', '<p>Giới thiệu công ty…</p>'),
    'dich-vu': ('Dịch vụ', '<p>Khảo sát, thiết kế, thi công và bảo trì hệ thống điện mặt trời.</p>'),
    'bao-hanh': ('Bảo hành', '<p>Chính sách bảo hành…</p>'),
    'lien-he': ('Liên hệ', '<p>Để lại thông tin, kỹ thuật viên sẽ gọi lại tư vấn miễn phí.</p>'),
    'tinh-dien-mat-troi': ('Tính điện mặt trời', '<p>Nhập tiền điện hàng tháng để ước tính công suất, chi phí và thời gian hoàn vốn.</p>'),
    'chinh-sach-bao-mat': ('Chính sách bảo mật', (
        '<p><strong>Cần viết lại trước khi ra mắt.</strong> Nêu rõ dữ liệu thu thập (họ tên, số điện thoại, địa chỉ, email), '
        'mục đích (liên hệ tư vấn, báo giá, giao hàng), thời gian lưu trữ và cách khách yêu cầu xóa dữ liệu '
        '(Nghị định 13/2023/NĐ-CP).</p>')),
}

PROJECTS = {
    'he-thong-50kwp-nha-xuong-binh-duong': ('Hệ thống 50kWp nhà xưởng Bình Dương',
                                             '<p>Inverter Huawei 50kW, 86 tấm pin JA Solar 580W.</p>'),
}


def ensure_post(kind, slug, title, content):
    if Post.query.filter_by(kind=kind, slug=slug).first():
        return False
    db.session.add(Post(kind=kind, slug=slug, title=title, content=content, published=True))
    return True


def run():
    with open(os.path.join(HERE, 'seed', 'products.csv'), encoding='utf-8-sig') as f:
        report = import_products(f.read(), update_existing=True)
    created_pages = sum(ensure_post('page', slug, *data) for slug, data in PAGES.items())
    created_projects = sum(ensure_post('project', slug, *data) for slug, data in PROJECTS.items())
    db.session.commit()
    print(f"Products: {report['created']} created, {report['updated']} updated, {report['skipped']} skipped")
    for line, message in report['errors']:
        print(f'  line {line}: {message}')
    print(f'Pages created: {created_pages}, projects created: {created_projects}')


if __name__ == '__main__':
    with create_app().app_context():
        run()
