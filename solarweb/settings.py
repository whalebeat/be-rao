"""Site settings (key/value) and the solar calculator configuration.

The calculator defaults, labels and provinces are ported from
SolarWeb's solarweb-calculator.php so calculator.js gets identical input.
"""
from .models import Setting, db
from .utils import digits_only

SITE_DEFAULTS = {
    'site_name': 'SolarWeb',
    'hotline': '0900000000',
    'zalo': '0900000000',
    'admin_email': '',
    'address': '',
    'turnstile_site_key': '',
    'turnstile_secret': '',
}


_MISSING = object()


def get_setting(key, default=_MISSING):
    """Stored value, else `default`, else the built-in SITE_DEFAULTS value."""
    row = db.session.get(Setting, key)
    if row is not None and row.value not in (None, ''):
        return row.value
    return SITE_DEFAULTS.get(key) if default is _MISSING else default


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = value


# --------------------------------------------------------------------------
# Solar calculator
# --------------------------------------------------------------------------

CALC_DEFAULTS = {
    # Bậc giá điện sinh hoạt EVN (đ/kWh), bậc 1→6: 0–50, 51–100, 101–200, 201–300, 301–400, >400 kWh.
    'evn_tiers': '1984,2050,2380,2998,3350,3460',
    'bill_vat': 0.08,
    'rate_commercial': 3500,
    'rate_industrial': 2500,
    'panel_watt': 650,
    'performance_ratio': 0.8,
    'roof_m2_metal': 6,
    'roof_m2_flat': 6.5,
    'roof_m2_tile': 8,
    'roof_extra_flat': 2000000,
    'roof_extra_tile': 2200000,
    'grid_price_5': 7500000,
    'grid_price_10': 7200000,
    'grid_price_max': 7000000,
    'hybrid_price_5': 13500000,
    'hybrid_price_10': 13000000,
    'hybrid_price_20': 12500000,
    'hybrid_price_30': 12000000,
    'hybrid_price_max': 11500000,
    'three_phase_factor_10': 1.08,
    'three_phase_factor_20': 1.05,
    'battery_price_kwh': 2820000,
    'package_max_kwp': 3.5,
    'package_price': 30000000,
    'max_auto_kwp': 50,
    'night_ratio_hybrid': 30,
    'hybrid_min_kwp': 5,
    'price_growth': 0.05,
    'co2_kg_per_kwh': 0.6,
    'zalo': '',  # blank = use the site-wide Zalo number
}

CALC_LABELS = {
    'Giá điện': {
        'evn_tiers': 'Bậc giá EVN sinh hoạt (đ/kWh, 6 bậc, cách nhau dấu phẩy)',
        'bill_vat': 'VAT trên hóa đơn (0.08 = 8%)',
        'rate_commercial': 'Giá điện kinh doanh trung bình (đ/kWh)',
        'rate_industrial': 'Giá điện sản xuất trung bình (đ/kWh)',
        'price_growth': 'Giá điện tăng mỗi năm (0.05 = 5%)',
    },
    'Đơn giá hệ thống': {
        'grid_price_5': 'Hòa lưới ≤ 5 kWp (đ/kWp)',
        'grid_price_10': 'Hòa lưới ≤ 10 kWp (đ/kWp)',
        'grid_price_max': 'Hòa lưới > 10 kWp (đ/kWp)',
        'hybrid_price_5': 'Hybrid ≤ 5 kWp (đ/kWp)',
        'hybrid_price_10': 'Hybrid ≤ 10 kWp (đ/kWp)',
        'hybrid_price_20': 'Hybrid ≤ 20 kWp (đ/kWp)',
        'hybrid_price_30': 'Hybrid ≤ 30 kWp (đ/kWp)',
        'hybrid_price_max': 'Hybrid > 30 kWp (đ/kWp)',
        'three_phase_factor_10': 'Hệ số 3 pha ≤ 10 kWp',
        'three_phase_factor_20': 'Hệ số 3 pha ≤ 20 kWp',
        'battery_price_kwh': 'Pin lưu trữ bổ sung (đ/kWh)',
        'roof_extra_flat': 'Phụ phí khung mái bằng (đ/kWp)',
        'roof_extra_tile': 'Phụ phí khung mái ngói (đ/kWp)',
        'package_max_kwp': 'Gói trọn gói áp dụng đến (kWp)',
        'package_price': 'Giá gói trọn gói (đ)',
        'max_auto_kwp': 'Trên mức này cần khảo sát báo giá (kWp)',
    },
    'Kỹ thuật': {
        'panel_watt': 'Công suất tấm pin (Wp)',
        'performance_ratio': 'Hiệu suất hệ thống (0–1)',
        'roof_m2_metal': 'Diện tích mái tôn cho 1 kWp (m²)',
        'roof_m2_flat': 'Diện tích mái bằng cho 1 kWp (m²)',
        'roof_m2_tile': 'Diện tích mái ngói cho 1 kWp (m²)',
        'night_ratio_hybrid': 'Gợi ý hybrid khi điện ban đêm ≥ (%)',
        'hybrid_min_kwp': 'Hybrid tối thiểu (kWp)',
        'co2_kg_per_kwh': 'Hệ số phát thải CO₂ (kg/kWh)',
        'zalo': 'Số Zalo nhận tư vấn (trống = dùng số chung)',
    },
}

# 34 tỉnh/thành sau sáp nhập 2025, average peak sun hours/day
CALC_REGIONS = [
    {'name': 'Miền Bắc', 'provinces': {
        'Hà Nội': 3.608, 'Hải Phòng': 3.688, 'Phú Thọ': 3.653, 'Bắc Ninh': 3.67, 'Hưng Yên': 3.71,
        'Ninh Bình': 3.729, 'Quảng Ninh': 3.759, 'Thái Nguyên': 3.53, 'Tuyên Quang': 3.477, 'Lào Cai': 3.56,
        'Lạng Sơn': 3.584, 'Cao Bằng': 3.532, 'Sơn La': 4.153, 'Điện Biên': 4.208, 'Lai Châu': 3.97,
    }},
    {'name': 'Miền Trung', 'provinces': {
        'Thanh Hóa': 3.91, 'Nghệ An': 3.896, 'Hà Tĩnh': 3.89, 'Quảng Trị': 4.296, 'Huế': 4.384,
        'Đà Nẵng': 4.815, 'Quảng Ngãi': 5.029, 'Gia Lai': 5.036, 'Đắk Lắk': 5.111, 'Khánh Hòa': 5.458,
        'Lâm Đồng': 5.225,
    }},
    {'name': 'Miền Nam', 'provinces': {
        'TP. Hồ Chí Minh': 5.049, 'Đồng Nai': 5.014, 'Tây Ninh': 5.062, 'Cần Thơ': 4.775, 'Vĩnh Long': 4.912,
        'Đồng Tháp': 4.944, 'An Giang': 4.882, 'Cà Mau': 4.793,
    }},
]

# Consent wording shown on lead forms; stored with each lead (Nghị định 13/2023/NĐ-CP)
CONSENT_TEMPLATE = 'Tôi đồng ý cho {site} lưu và sử dụng họ tên, số điện thoại và thông tin trên để liên hệ tư vấn, báo giá.'


def consent_text():
    return CONSENT_TEMPLATE.format(site=get_setting('site_name'))


def calc_settings():
    saved = get_setting('calculator', {})
    return {**CALC_DEFAULTS, **(saved if isinstance(saved, dict) else {})}


def _number(value):
    try:
        return float(str(value).strip().replace(',', '.'))
    except ValueError:
        return 0.0


def sanitize_calc(form):
    """Same rules as the PHP sanitize_callback: invalid values fall back to the default."""
    clean = {}
    for key, default in CALC_DEFAULTS.items():
        value = str(form.get(key, '')).strip()
        if key == 'evn_tiers':
            tiers = [t for t in (_number(p) for p in value.split(',')) if t > 0]
            clean[key] = ','.join(f'{t:g}' for t in tiers) if len(tiers) == 6 else default
        elif key == 'zalo':
            clean[key] = digits_only(value)
        else:
            number = _number(value)
            clean[key] = (int(number) if number.is_integer() else number) if number > 0 else default
    return clean


def calc_client_config():
    """`config` for window.SOLARWEB_CALC: zalo removed, evn_tiers as a list of floats."""
    config = calc_settings()
    config.pop('zalo', None)
    config['evn_tiers'] = [float(t) for t in str(config['evn_tiers']).split(',') if t.strip()]
    return config


def calc_zalo_url():
    number = digits_only(calc_settings().get('zalo') or get_setting('zalo'))
    return f'https://zalo.me/{number}' if number else ''
