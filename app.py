import os
import hmac
import secrets
import time
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import func
from models import db, init_db, Station, Equipment, Person, Marathon, IssueRecord, ReturnRecord, User, StoreIssueRecord, StoreReturnRecord, DEFAULT_ADMIN_PASSWORD
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from functools import wraps
load_dotenv()
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
database_url = os.getenv("DATABASE_URL", "sqlite:///database.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://","postgresql://",1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    # Random per-process key: sessions don't survive restarts, but cookies can't be forged.
    print("WARNING: SECRET_KEY is not set; using a random key. Set SECRET_KEY in production.")
    secret_key = secrets.token_hex(32)
app.config['SECRET_KEY'] = secret_key
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv("SESSION_COOKIE_SECURE", "true" if os.getenv("RENDER") else "false").lower() == "true"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
db.init_app(app)
with app.app_context():
    init_db()

MIN_PASSWORD_LENGTH = 6
VN_TZ = timezone(timedelta(hours=7))  # Vietnam has no DST

def utcnow():
    """Naive UTC timestamp (matches existing stored values)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

@app.template_filter('vntime')
def vntime(value, fmt='%Y-%m-%d %H:%M', default='—'):
    if not value:
        return default
    return value.replace(tzinfo=timezone.utc).astimezone(VN_TZ).strftime(fmt)

# CSRF protection
def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def csrf_protect():
    if request.method == 'POST':
        expected = session.get('_csrf_token')
        sent = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, description='CSRF token missing or invalid')

@app.before_request
def enforce_password_change():
    # Accounts still using the default password must change it before doing anything else
    if session.get('must_change_password') and request.endpoint not in ('change_password', 'logout', 'static'):
        flash('Vui lòng đổi mật khẩu mặc định trước khi tiếp tục.', 'warning')
        return redirect(url_for('change_password'))

# Login throttling (in-memory, per worker)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_failed_logins = defaultdict(list)

def _login_key(username):
    return f"{request.remote_addr}|{(username or '').lower()}"

def _recent_failures(key):
    cutoff = time.time() - LOGIN_WINDOW_SECONDS
    _failed_logins[key] = [t for t in _failed_logins[key] if t > cutoff]
    return _failed_logins[key]

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
            return redirect(url_for('login'))
        if not get_current_user():
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
                return redirect(url_for('login'))
            user = get_current_user()
            if not user or user.role not in roles:
                flash('Bạn không có quyền truy cập trang này.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

admin_required = roles_required('admin')
admin_or_storekeeper_required = roles_required('admin', 'storekeeper')

def get_current_user():
    if session.get('user_id'):
        return db.session.get(User, session['user_id'])
    return None

def get_user_marathons(user):
    """Get marathons accessible to the user based on their role"""
    if not user:
        return []
    if user.role in ['admin', 'storekeeper']:
        # Admins and storekeepers can see all marathons
        return Marathon.query.order_by(Marathon.name).all()
    else:
        # Regular users can only see assigned marathons
        return sorted(user.assigned_marathons, key=lambda m: m.name)

def can_access_marathon(user, marathon_id):
    """No marathon (None) is always allowed; otherwise it must be one the user can see."""
    if not marathon_id:
        return True
    try:
        marathon_id = int(marathon_id)
    except (TypeError, ValueError):
        return False
    return any(m.id == marathon_id for m in get_user_marathons(user))

def parse_quantity(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def get_or_create(model, name):
    """Find a row by name (case-insensitive) or create it. Returns None for blank names."""
    name = (name or '').strip()
    if not name:
        return None
    obj = model.query.filter(func.lower(model.name) == name.lower()).first()
    if not obj:
        obj = model(name=name)
        db.session.add(obj)
        db.session.flush()
    return obj

def sum_by(model, marathon_id, *group_cols):
    """Return {group key: total quantity} for a record model within a marathon."""
    cols = [getattr(model, c) for c in group_cols]
    rows = db.session.query(*cols, func.sum(model.quantity)).filter(model.marathon_id == marathon_id).group_by(*cols).all()
    if len(cols) == 1:
        return {r[0]: int(r[1] or 0) for r in rows}
    return {tuple(r[:-1]): int(r[-1] or 0) for r in rows}

def name_maps():
    return ({e.id: e.name for e in Equipment.query.all()},
            {s.id: s.name for s in Station.query.all()},
            {m.id: m.name for m in Marathon.query.all()})

def build_transactions(records, rec_type, eq_names, st_names=None, mar_names=None):
    rows = []
    for rec in records:
        row = {
            'type': rec_type,
            'timestamp': rec.timestamp,
            'equipment': eq_names.get(rec.equipment_id),
            'quantity': rec.quantity,
            'person': rec.person_name,
            'created_by': rec.created_by,
        }
        if st_names is not None:
            row['station'] = st_names.get(rec.station_id)
        if mar_names is not None:
            row['marathon'] = mar_names.get(rec.marathon_id, '-----')
        rows.append(row)
    return rows

def sort_newest_first(transactions):
    transactions.sort(key=lambda x: x['timestamp'] or datetime.min, reverse=True)
    return transactions

def password_too_short(password):
    if len(password or '') < MIN_PASSWORD_LENGTH:
        flash(f'Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự!', 'danger')
        return True
    return False

@app.route('/')
@login_required
def index():
    user = get_current_user()
    return render_template('index.html', title="Bê Rào Checklist", user=user)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        key = _login_key(username)
        if len(_recent_failures(key)) >= LOGIN_MAX_ATTEMPTS:
            flash('Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút.', 'danger')
            return render_template('login.html', user=None), 429
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            _failed_logins.pop(key, None)
            session.clear()
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            if password == DEFAULT_ADMIN_PASSWORD:
                session['must_change_password'] = True
                return redirect(url_for('change_password'))
            flash(f'Chào mừng {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            _failed_logins[key].append(time.time())
            flash('Tên đăng nhập hoặc mật khẩu không đúng!', 'danger')
    return render_template('login.html', user=None)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Bạn đã đăng xuất thành công!', 'success')
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = get_current_user()
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_password or not new_password or not confirm_password:
            flash('Vui lòng điền đầy đủ thông tin!', 'danger')
            return render_template('change_password.html', user=user)

        if not user.check_password(current_password):
            flash('Mật khẩu hiện tại không đúng!', 'danger')
            return render_template('change_password.html', user=user)

        if new_password != confirm_password:
            flash('Mật khẩu mới không khớp!', 'danger')
            return render_template('change_password.html', user=user)

        if password_too_short(new_password):
            return render_template('change_password.html', user=user)

        if new_password == DEFAULT_ADMIN_PASSWORD:
            flash('Không được dùng mật khẩu mặc định!', 'danger')
            return render_template('change_password.html', user=user)

        user.set_password(new_password)
        db.session.commit()
        session.pop('must_change_password', None)
        flash('Mật khẩu đã được thay đổi thành công!', 'success')
        return redirect(url_for('index'))

    return render_template('change_password.html', user=user)

def resolve_person_name(user):
    # Only admin can select/enter a different person, others use their username
    if user.role == 'admin':
        return request.form.get('person') or request.form.get('new_person') or user.username
    return user.username

@app.route('/issue', methods=['GET','POST'])
@login_required
def issue():
    user = get_current_user()
    marathons = get_user_marathons(user)
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        if not can_access_marathon(user, marathon_id):
            flash('Bạn không có quyền với giải chạy này.', 'danger')
            return redirect(url_for('issue'))
        station_id = request.form.get('station') or None
        new_station = get_or_create(Station, request.form.get('new_station'))
        if new_station:
            station_id = new_station.id

        person = get_or_create(Person, resolve_person_name(user))
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        new_equipments = request.form.getlist('new_equipment[]')

        saved = 0
        for idx, qty in enumerate(quantities):
            q = parse_quantity(qty)
            if q <= 0:
                continue
            # Use new_equipment[] if it has a value, otherwise the selected equipment[]
            new_eq = get_or_create(Equipment, new_equipments[idx] if idx < len(new_equipments) else None)
            eq_id = new_eq.id if new_eq else (equipment_ids[idx] if idx < len(equipment_ids) else None)
            if not eq_id:
                continue
            db.session.add(IssueRecord(marathon_id=marathon_id, station_id=station_id, equipment_id=eq_id,
                          person_name=person.name, quantity=q, timestamp=utcnow(),
                          created_by=user.username))
            saved += 1
        db.session.commit()
        flash(f'Đã lưu {saved} dòng giao đồ.' if saved else 'Không có dòng nào được lưu.', 'success' if saved else 'warning')
        return redirect(url_for('issue'))
    return render_template('issue.html', marathons=marathons, stations=stations, equipments=equipments, persons=persons, user=user)

def unreturned_items(marathon_id, station_id=None):
    """Per (station, equipment): issued minus returned, for rows still outstanding."""
    issued = sum_by(IssueRecord, marathon_id, 'station_id', 'equipment_id')
    returned = sum_by(ReturnRecord, marathon_id, 'station_id', 'equipment_id')
    eq_names, st_names, _ = name_maps()
    items = []
    for (st_id, eq_id), qty in issued.items():
        if station_id and str(st_id) != str(station_id):
            continue
        missing = qty - returned.get((st_id, eq_id), 0)
        if missing > 0:
            items.append({'station_id': st_id, 'station': st_names.get(st_id, '—'), 'equipment_id': eq_id,
                          'equipment': eq_names.get(eq_id, '—'), 'missing': missing})
    items.sort(key=lambda i: (i['station'], i['equipment']))
    return items

@app.route('/return', methods=['GET','POST'])
@login_required
def return_equipment():
    user = get_current_user()
    marathons = get_user_marathons(user)
    stations = Station.query.order_by(Station.name).all()
    persons = Person.query.order_by(Person.name).all()
    marathon_id = request.args.get('marathon') or None
    selected_station_id = request.args.get('station') or None
    if not can_access_marathon(user, marathon_id):
        flash('Bạn không có quyền với giải chạy này.', 'danger')
        return redirect(url_for('return_equipment'))
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        if not marathon_id or not can_access_marathon(user, marathon_id):
            flash('Bạn không có quyền với giải chạy này.', 'danger')
            return redirect(url_for('return_equipment'))
        person = get_or_create(Person, resolve_person_name(user))
        outstanding = {(i['station_id'], i['equipment_id']): i['missing'] for i in unreturned_items(marathon_id)}
        station_ids = request.form.getlist('station_id[]')
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        saved = 0
        for st_id, eq_id, qty in zip(station_ids, equipment_ids, quantities):
            q = parse_quantity(qty)
            if q <= 0:
                continue
            st_key = int(st_id) if st_id.isdigit() else None
            eq_key = parse_quantity(eq_id)
            missing = outstanding.get((st_key, eq_key), 0)
            if q > missing:
                flash(f'Số lượng trả vượt quá số còn thiếu ({missing}); đã bỏ qua dòng này.', 'warning')
                continue
            db.session.add(ReturnRecord(marathon_id=marathon_id, station_id=st_key, equipment_id=eq_key,
                           person_name=person.name, quantity=q, timestamp=utcnow(),
                           created_by=user.username))
            saved += 1
        db.session.commit()
        if saved:
            flash(f'Đã lưu {saved} dòng trả đồ.', 'success')
        return redirect(url_for('return_equipment', marathon=marathon_id))
    unreturned = unreturned_items(marathon_id, selected_station_id) if marathon_id else []
    return render_template('return.html', marathons=marathons, stations=stations,
                         persons=persons, unreturned=unreturned, selected_marathon=marathon_id,
                         selected_station=selected_station_id, user=user)

@app.route('/report', methods=['GET'])
@login_required
def report():
    user = get_current_user()
    marathon_id = request.args.get('marathon') or None
    marathons = get_user_marathons(user)
    if not can_access_marathon(user, marathon_id):
        flash('Bạn không có quyền với giải chạy này.', 'danger')
        return redirect(url_for('report'))
    equipment_summary = []; station_details = []; transactions = []
    if marathon_id:
        eq_names, st_names, _ = name_maps()
        issued_by_eq = sum_by(IssueRecord, marathon_id, 'equipment_id')
        returned_by_eq = sum_by(ReturnRecord, marathon_id, 'equipment_id')
        for eq_id in sorted(set(issued_by_eq) | set(returned_by_eq), key=lambda i: eq_names.get(i, '')):
            issued = issued_by_eq.get(eq_id, 0)
            returned = returned_by_eq.get(eq_id, 0)
            equipment_summary.append({
                'equipment': eq_names.get(eq_id, '—'),
                'issued': issued,
                'returned': returned,
                'remaining': issued - returned
            })
        by_station = {}
        for item in unreturned_items(marathon_id):
            by_station.setdefault(item['station'], []).append({'equipment': item['equipment'], 'missing': item['missing']})
        station_details = [{'station': st, 'items': items} for st, items in sorted(by_station.items())]

        transactions = build_transactions(IssueRecord.query.filter_by(marathon_id=marathon_id).all(), 'issue', eq_names, st_names) + \
                       build_transactions(ReturnRecord.query.filter_by(marathon_id=marathon_id).all(), 'return', eq_names, st_names)
        sort_newest_first(transactions)
    return render_template('report.html', marathons=marathons, equipment_summary=equipment_summary, station_details=station_details, selected_marathon=marathon_id, transactions=transactions, user=user)

@app.route('/reconciliation_report', methods=['GET'])
@admin_or_storekeeper_required
def reconciliation_report():
    user = get_current_user()
    marathon_id = request.args.get('marathon') or None
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipment_summary = []
    eq_names, _, mar_names = name_maps()

    if marathon_id:
        # Show statistics and records for selected marathon
        store_issued = sum_by(StoreIssueRecord, marathon_id, 'equipment_id')
        issued = sum_by(IssueRecord, marathon_id, 'equipment_id')
        returned = sum_by(ReturnRecord, marathon_id, 'equipment_id')
        store_returned = sum_by(StoreReturnRecord, marathon_id, 'equipment_id')
        for eq in Equipment.query.order_by(Equipment.name).all():
            si, i, r, sr = (d.get(eq.id, 0) for d in (store_issued, issued, returned, store_returned))
            equipment_summary.append({
                'equipment': eq.name,
                'store_issued': si,
                'issued': i,
                'store_vs_issued_diff': si - i,  # Should be 0 if balanced
                'returned': r,
                'store_returned': sr,
                'returned_vs_store_diff': r - sr  # Should be 0 if balanced
            })
        store_issue_q = StoreIssueRecord.query.filter_by(marathon_id=marathon_id)
        store_return_q = StoreReturnRecord.query.filter_by(marathon_id=marathon_id)
    else:
        # Show 100 most recent store issue/return records when no marathon is selected
        store_issue_q = StoreIssueRecord.query.order_by(StoreIssueRecord.timestamp.desc()).limit(100)
        store_return_q = StoreReturnRecord.query.order_by(StoreReturnRecord.timestamp.desc()).limit(100)

    store_transactions = build_transactions(store_issue_q.all(), 'store_issue', eq_names, mar_names=mar_names) + \
                         build_transactions(store_return_q.all(), 'store_return', eq_names, mar_names=mar_names)
    sort_newest_first(store_transactions)

    return render_template('reconciliation_report.html', marathons=marathons, equipment_summary=equipment_summary,
                         selected_marathon=marathon_id, store_transactions=store_transactions, user=user)

def store_person_name():
    person = get_or_create(Person, request.form.get('person') or request.form.get('new_person'))
    if not person:
        flash('Vui lòng chọn hoặc nhập tên người!', 'danger')
        return None
    return person.name

@app.route('/store_issue', methods=['GET','POST'])
@admin_or_storekeeper_required
def store_issue():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        new_marathon = get_or_create(Marathon, request.form.get('new_marathon'))
        if new_marathon:
            marathon_id = new_marathon.id
        person_name = store_person_name()
        if not person_name:
            return redirect(url_for('store_issue'))

        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')

        for eq_id, qty in zip(equipment_ids, quantities):
            q = parse_quantity(qty)
            if q<=0 or not eq_id: continue
            db.session.add(StoreIssueRecord(marathon_id=marathon_id, equipment_id=eq_id,
                          person_name=person_name, quantity=q, timestamp=utcnow(),
                          created_by=user.username))
        db.session.commit()
        flash('Xuất kho thành công!', 'success')
        return redirect(url_for('store_issue'))
    return render_template('store_issue.html', marathons=marathons, equipments=equipments, persons=persons, user=user)

def store_available(marathon_id):
    """Per equipment: store_issued - store_returned (independent of user issue/return)."""
    store_issued = sum_by(StoreIssueRecord, marathon_id, 'equipment_id')
    store_returned = sum_by(StoreReturnRecord, marathon_id, 'equipment_id')
    return {eq_id: qty - store_returned.get(eq_id, 0) for eq_id, qty in store_issued.items() if qty - store_returned.get(eq_id, 0) > 0}

@app.route('/store_return', methods=['GET','POST'])
@admin_or_storekeeper_required
def store_return():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    marathon_id = request.args.get('marathon') or None

    if request.method=='POST':
        # marathon from form data; empty means a non-race return
        marathon_id = request.form.get('marathon') or None
        redirect_url = url_for('store_return', marathon=marathon_id) if marathon_id else url_for('store_return')
        person_name = store_person_name()
        if not person_name:
            return redirect(redirect_url)
        available = store_available(marathon_id) if marathon_id else None

        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')

        for eq_id, qty in zip(equipment_ids, quantities):
            q = parse_quantity(qty)
            if q<=0 or not eq_id: continue
            if available is not None and q > available.get(parse_quantity(eq_id), 0):
                flash(f'Số lượng nhập kho vượt quá số có thể nhập ({available.get(parse_quantity(eq_id), 0)}); đã bỏ qua dòng này.', 'warning')
                continue
            db.session.add(StoreReturnRecord(marathon_id=marathon_id, equipment_id=eq_id,
                           person_name=person_name, quantity=q, timestamp=utcnow(),
                           created_by=user.username))
        db.session.commit()
        flash('Nhập kho thành công!', 'success')
        return redirect(redirect_url)

    unreturned = []
    if marathon_id:
        eq_names, _, _ = name_maps()
        unreturned = sorted(({'equipment_id': eq_id, 'equipment': eq_names.get(eq_id, '—'), 'available': qty}
                             for eq_id, qty in store_available(marathon_id).items()), key=lambda i: i['equipment'])
    return render_template('store_return.html', marathons=marathons, equipments=equipments, persons=persons,
                         unreturned=unreturned, selected_marathon=marathon_id, user=user)

def api_get_or_create(model):
    name = ((request.get_json(silent=True) or {}).get('name') or '').strip()
    if not name: return jsonify({'error':'missing name'}),400
    obj = get_or_create(model, name)
    db.session.commit()
    return jsonify({'id':obj.id,'name':obj.name})

@app.route('/api/add_station', methods=['POST'])
@login_required
def api_add_station():
    return api_get_or_create(Station)

@app.route('/api/add_equipment', methods=['POST'])
@login_required
def api_add_equipment():
    return api_get_or_create(Equipment)

@app.route('/api/add_marathon', methods=['POST'])
@admin_or_storekeeper_required
def api_add_marathon():
    return api_get_or_create(Marathon)

@app.route('/api/persons')
@login_required
def api_persons():
    persons = Person.query.order_by(Person.name).all(); return jsonify([p.name for p in persons])

# Admin routes
@app.route('/admin/users')
@admin_required
def admin_users():
    user = get_current_user()
    users = User.query.order_by(User.username).all()
    return render_template('admin_users.html', users=users, user=user)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def admin_add_user():
    user = get_current_user()
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password')
        role = request.form.get('role', 'user')

        if not username or not password:
            flash('Tên đăng nhập và mật khẩu là bắt buộc!', 'danger')
            return render_template('admin_add_user.html', user=user)

        if role not in ['admin', 'user', 'storekeeper']:
            flash('Vai trò không hợp lệ!', 'danger')
            return render_template('admin_add_user.html', user=user)

        if password_too_short(password):
            return render_template('admin_add_user.html', user=user)

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Tên đăng nhập đã tồn tại!', 'danger')
            return render_template('admin_add_user.html', user=user)

        new_user = User(username=username, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'Người dùng {username} đã được tạo thành công!', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin_add_user.html', user=user)

@app.route('/admin/users/<int:user_id>/reset_password', methods=['GET', 'POST'])
@admin_required
def admin_reset_password(user_id):
    current_user = get_current_user()
    target_user = db.get_or_404(User, user_id)

    if request.method == 'POST':
        new_password = request.form.get('password')
        if not new_password:
            flash('Mật khẩu không được để trống!', 'danger')
            return render_template('admin_reset_password.html', target_user=target_user, user=current_user)

        if password_too_short(new_password):
            return render_template('admin_reset_password.html', target_user=target_user, user=current_user)

        target_user.set_password(new_password)
        db.session.commit()
        flash(f'Mật khẩu của {target_user.username} đã được đặt lại thành công!', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin_reset_password.html', target_user=target_user, user=current_user)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    current_user = get_current_user()
    target_user = db.get_or_404(User, user_id)

    if target_user.id == current_user.id:
        flash('Bạn không thể xóa tài khoản của chính mình!', 'danger')
        return redirect(url_for('admin_users'))

    username = target_user.username
    db.session.delete(target_user)
    db.session.commit()
    flash(f'Người dùng {username} đã được xóa!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.id).all()
    stations = Station.query.order_by(Station.id).all()
    equipments = Equipment.query.order_by(Equipment.id).all()
    issue_records = IssueRecord.query.order_by(IssueRecord.timestamp.desc()).limit(100).all()
    return_records = ReturnRecord.query.order_by(ReturnRecord.timestamp.desc()).limit(100).all()
    return render_template('admin_dashboard.html', marathons=marathons, stations=stations, equipments=equipments, issue_records=issue_records, return_records=return_records, user=user)

@app.route('/admin/delete/issue/<int:record_id>', methods=['POST'])
@admin_required
def delete_issue_record(record_id):
    record = db.get_or_404(IssueRecord, record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Bản ghi xuất đã được xóa thành công!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/return/<int:record_id>', methods=['POST'])
@admin_required
def delete_return_record(record_id):
    record = db.get_or_404(ReturnRecord, record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Bản ghi nhập đã được xóa thành công!', 'success')
    return redirect(url_for('admin_dashboard'))

def edit_record(model, record_id, template, success_message):
    user = get_current_user()
    record = db.get_or_404(model, record_id)
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    if request.method == 'POST':
        quantity = parse_quantity(request.form.get('quantity'))
        equipment_id = request.form.get('equipment')
        if quantity <= 0 or not equipment_id:
            flash('Số lượng phải là số nguyên dương và phải chọn thiết bị!', 'danger')
        else:
            record.marathon_id = request.form.get('marathon') or None
            record.station_id = request.form.get('station') or None
            record.equipment_id = equipment_id
            record.quantity = quantity
            record.person_name = request.form.get('person')
            db.session.commit()
            flash(success_message, 'success')
            return redirect(url_for('admin_dashboard'))
    return render_template(template, record=record, marathons=marathons, stations=stations, equipments=equipments, user=user)

@app.route('/admin/edit/issue/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_issue_record(record_id):
    return edit_record(IssueRecord, record_id, 'admin_edit_issue.html', 'Bản ghi xuất đã được cập nhật thành công!')

@app.route('/admin/edit/return/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_return_record(record_id):
    return edit_record(ReturnRecord, record_id, 'admin_edit_return.html', 'Bản ghi nhập đã được cập nhật thành công!')

def is_referenced(column_name, value, models):
    return any(m.query.filter(getattr(m, column_name) == value).first() for m in models)

def rename(obj, anchor, success_message):
    name = (request.form.get('name') or '').strip()
    if name:
        clash = type(obj).query.filter(func.lower(type(obj).name) == name.lower(), type(obj).id != obj.id).first()
        if clash:
            flash(f'Tên "{name}" đã tồn tại!', 'danger')
        else:
            obj.name = name
            db.session.commit()
            flash(success_message, 'success')
    return redirect(url_for('admin_dashboard') + anchor)

def add_named(model, anchor, success_message):
    name = (request.form.get('name') or '').strip()
    if name:
        if model.query.filter(func.lower(model.name) == name.lower()).first():
            flash(f'Tên "{name}" đã tồn tại!', 'danger')
        else:
            db.session.add(model(name=name))
            db.session.commit()
            flash(success_message.format(name=name), 'success')
    return redirect(url_for('admin_dashboard') + anchor)

def delete_named(obj, column_name, models, anchor, success_message):
    name = obj.name
    if is_referenced(column_name, obj.id, models):
        flash(f'Không thể xóa "{name}" vì đã có bản ghi liên quan. Hãy xóa các bản ghi đó trước.', 'danger')
    else:
        db.session.delete(obj)
        db.session.commit()
        flash(success_message.format(name=name), 'success')
    return redirect(url_for('admin_dashboard') + anchor)

ALL_RECORD_MODELS = (IssueRecord, ReturnRecord, StoreIssueRecord, StoreReturnRecord)

# Marathon management routes
@app.route('/admin/marathon/add', methods=['POST'])
@admin_required
def admin_add_marathon():
    return add_named(Marathon, '#marathons', 'Giải chạy "{name}" đã được thêm!')

@app.route('/admin/marathon/<int:marathon_id>/edit', methods=['POST'])
@admin_required
def admin_edit_marathon(marathon_id):
    return rename(db.get_or_404(Marathon, marathon_id), '#marathons', 'Giải chạy đã được cập nhật!')

@app.route('/admin/marathon/<int:marathon_id>/delete', methods=['POST'])
@admin_required
def admin_delete_marathon(marathon_id):
    return delete_named(db.get_or_404(Marathon, marathon_id), 'marathon_id', ALL_RECORD_MODELS,
                        '#marathons', 'Giải chạy "{name}" đã được xóa!')

# Station management routes
@app.route('/admin/station/add', methods=['POST'])
@admin_required
def admin_add_station_form():
    return add_named(Station, '#stations', 'Trạm "{name}" đã được thêm!')

@app.route('/admin/station/<int:station_id>/edit', methods=['POST'])
@admin_required
def admin_edit_station(station_id):
    return rename(db.get_or_404(Station, station_id), '#stations', 'Trạm đã được cập nhật!')

@app.route('/admin/station/<int:station_id>/delete', methods=['POST'])
@admin_required
def admin_delete_station(station_id):
    return delete_named(db.get_or_404(Station, station_id), 'station_id', (IssueRecord, ReturnRecord),
                        '#stations', 'Trạm "{name}" đã được xóa!')

# Equipment management routes
@app.route('/admin/equipment/add', methods=['POST'])
@admin_required
def admin_add_equipment_form():
    return add_named(Equipment, '#equipments-manage', 'Thiết bị "{name}" đã được thêm!')

@app.route('/admin/equipment/<int:equipment_id>/edit', methods=['POST'])
@admin_required
def admin_edit_equipment(equipment_id):
    return rename(db.get_or_404(Equipment, equipment_id), '#equipments-manage', 'Thiết bị đã được cập nhật!')

@app.route('/admin/equipment/<int:equipment_id>/delete', methods=['POST'])
@admin_required
def admin_delete_equipment(equipment_id):
    return delete_named(db.get_or_404(Equipment, equipment_id), 'equipment_id', ALL_RECORD_MODELS,
                        '#equipments-manage', 'Thiết bị "{name}" đã được xóa!')

@app.route('/admin/equipment/<int:equipment_id>/set_available', methods=['POST'])
@admin_required
def admin_set_available_quantity(equipment_id):
    equipment = db.get_or_404(Equipment, equipment_id)
    available_quantity = request.form.get('available_quantity')
    if available_quantity is not None:
        try:
            value = int(available_quantity)
            if value < 0:
                raise ValueError
            equipment.available_quantity = value
            db.session.commit()
            flash(f'Đã cập nhật tồn kho cho "{equipment.name}"!', 'success')
        except ValueError:
            flash('Số lượng không hợp lệ!', 'danger')
    return redirect(url_for('admin_dashboard') + '#equipments-manage')

# Bulk inventory management route (for admin and storekeeper)
@app.route('/manage_inventory', methods=['GET', 'POST'])
@admin_or_storekeeper_required
def manage_inventory():
    user = get_current_user()
    equipments = Equipment.query.order_by(Equipment.name).all()

    if request.method == 'POST':
        # Get all equipment IDs and quantities from form
        for equipment in equipments:
            qty_key = f'quantity_{equipment.id}'
            qty_value = request.form.get(qty_key)
            if qty_value is not None:
                try:
                    value = int(qty_value)
                except ValueError:
                    continue  # Skip invalid values
                if value >= 0:
                    equipment.available_quantity = value

        db.session.commit()
        flash('Đã cập nhật tồn kho thành công!', 'success')
        return redirect(url_for('manage_inventory'))

    return render_template('manage_inventory.html', equipments=equipments, user=user)

# User-Marathon assignment routes
@app.route('/admin/users/<int:user_id>/marathons', methods=['GET', 'POST'])
@admin_required
def admin_user_marathons(user_id):
    current_user = get_current_user()
    target_user = db.get_or_404(User, user_id)
    all_marathons = Marathon.query.order_by(Marathon.name).all()

    if request.method == 'POST':
        # Get selected marathon IDs from form
        selected_marathon_ids = [parse_quantity(mid) for mid in request.form.getlist('marathons') if mid]
        target_user.assigned_marathons = Marathon.query.filter(Marathon.id.in_(selected_marathon_ids)).all() if selected_marathon_ids else []
        db.session.commit()
        flash(f'Đã cập nhật phân công giải chạy cho {target_user.username}!', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin_user_marathons.html', target_user=target_user, all_marathons=all_marathons, user=current_user)

@app.route('/admin/users/<int:user_id>/change_role', methods=['GET', 'POST'])
@admin_required
def admin_change_user_role(user_id):
    current_user = get_current_user()
    target_user = db.get_or_404(User, user_id)

    if target_user.id == current_user.id:
        flash('Bạn không thể thay đổi vai trò của chính mình!', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        new_role = request.form.get('role')
        if new_role in ['admin', 'user', 'storekeeper']:
            target_user.role = new_role
            db.session.commit()
            flash(f'Đã thay đổi vai trò của {target_user.username} thành {new_role}!', 'success')
            return redirect(url_for('admin_users'))
        else:
            flash('Vai trò không hợp lệ!', 'danger')

    return render_template('admin_change_role.html', target_user=target_user, user=current_user)

@app.route('/admin/marathon_users', methods=['GET', 'POST'])
@admin_required
def admin_marathon_users():
    current_user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    all_users = User.query.filter(User.role == 'user').order_by(User.username).all()

    selected_marathon_id = request.args.get('marathon') or (marathons[0].id if marathons else None)
    selected_marathon = db.session.get(Marathon, parse_quantity(selected_marathon_id)) if selected_marathon_id else None

    if request.method == 'POST':
        marathon_id = request.form.get('marathon_id')
        selected_marathon = db.get_or_404(Marathon, parse_quantity(marathon_id))

        # Get selected user IDs from form
        selected_user_ids = {parse_quantity(uid) for uid in request.form.getlist('users') if uid}

        # Keep non-'user' roles (admins etc.) as they are; replace regular user assignments
        kept = [u for u in selected_marathon.assigned_users if u.role != 'user']
        chosen = User.query.filter(User.id.in_(selected_user_ids), User.role == 'user').all() if selected_user_ids else []
        selected_marathon.assigned_users = kept + chosen

        db.session.commit()
        flash(f'Đã cập nhật phân công người dùng cho giải chạy "{selected_marathon.name}"!', 'success')
        return redirect(url_for('admin_marathon_users', marathon=marathon_id))

    return render_template('admin_marathon_users.html', marathons=marathons, all_users=all_users,
                         selected_marathon=selected_marathon, user=current_user)

if __name__=='__main__': app.run(debug=os.getenv("FLASK_DEBUG") == "1")
