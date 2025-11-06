import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from models import db, init_db, Station, Equipment, Person, Marathon, IssueRecord, ReturnRecord, User
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
load_dotenv()
app = Flask(__name__)
database_url = os.getenv("DATABASE_URL", "sqlite:///database.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://","postgresql://",1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
db.init_app(app)
with app.app_context():
    init_db()

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Bạn không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    if session.get('user_id'):
        return User.query.get(session['user_id'])
    return None

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
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Chào mừng {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng!', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Bạn đã đăng xuất thành công!', 'success')
    return redirect(url_for('login'))

@app.route('/issue', methods=['GET','POST'])
@login_required
def issue():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        new_marathon = request.form.get('new_marathon')
        if new_marathon:
            m = Marathon(name=new_marathon); db.session.add(m); db.session.commit(); marathon_id = m.id
        station_id = request.form.get('station') or None
        new_station = request.form.get('new_station')
        if new_station:
            s = Station(name=new_station); db.session.add(s); db.session.commit(); station_id = s.id
        person_name = request.form.get('person') or request.form.get('new_person') or user.username
        person = Person.query.filter_by(name=person_name).first()
        if not person:
            person = Person(name=person_name); db.session.add(person); db.session.commit()
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        new_equipments = request.form.getlist('new_equipment[]')
        
        # Build final equipment IDs list - use new_equipment[] if it has value, otherwise use equipment[]
        final_equipment_ids = []
        for idx in range(len(quantities)):
            # Check if new_equipment has a value for this row
            if idx < len(new_equipments) and new_equipments[idx] and not new_equipments[idx].isspace():
                new_eq_name = new_equipments[idx].strip()
                # Check if equipment with this name already exists (case-insensitive)
                existing_eq = Equipment.query.filter(Equipment.name.ilike(new_eq_name)).first()
                if existing_eq:
                    # Use existing equipment instead of creating a new one
                    final_equipment_ids.append(str(existing_eq.id))
                else:
                    # Create new equipment and use its ID
                    eq = Equipment(name=new_eq_name)
                    db.session.add(eq)
                    db.session.commit()
                    final_equipment_ids.append(str(eq.id))
            elif idx < len(equipment_ids) and equipment_ids[idx]:
                # Use the selected equipment ID from dropdown
                final_equipment_ids.append(equipment_ids[idx])
            else:
                # No equipment selected for this row
                final_equipment_ids.append(None)
        
        # Save records
        for eq_id, qty in zip(final_equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = IssueRecord(marathon_id=marathon_id, station_id=station_id, equipment_id=eq_id, 
                          person_name=person.name, quantity=q, timestamp=datetime.utcnow(),
                          created_by=user.username)
            db.session.add(r)
        db.session.commit()
        return redirect(url_for('issue'))
    return render_template('issue.html', marathons=marathons, stations=stations, equipments=equipments, persons=persons, user=user)

@app.route('/return', methods=['GET','POST'])
@login_required
def return_equipment():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    marathon_id = request.args.get('marathon') or None
    unreturned = []
    if marathon_id:
        from sqlalchemy import func
        issued_q = db.session.query(IssueRecord.station_id, IssueRecord.equipment_id, func.sum(IssueRecord.quantity).label('issued')).filter(IssueRecord.marathon_id==marathon_id).group_by(IssueRecord.station_id, IssueRecord.equipment_id).subquery()
        returned_q = db.session.query(ReturnRecord.station_id, ReturnRecord.equipment_id, func.sum(ReturnRecord.quantity).label('returned')).filter(ReturnRecord.marathon_id==marathon_id).group_by(ReturnRecord.station_id, ReturnRecord.equipment_id).subquery()
        rows = db.session.query(issued_q.c.station_id, issued_q.c.equipment_id, issued_q.c.issued, returned_q.c.returned).outerjoin(returned_q, (issued_q.c.station_id==returned_q.c.station_id)&(issued_q.c.equipment_id==returned_q.c.equipment_id)).all()
        for r in rows:
            returned = r.returned or 0
            if r.issued - returned > 0:
                st = Station.query.get(r.station_id) if r.station_id else None
                eq = Equipment.query.get(r.equipment_id)
                unreturned.append({'station_id': r.station_id, 'station': st.name if st else '—', 'equipment_id': r.equipment_id, 'equipment': eq.name if eq else '—', 'missing': int(r.issued-returned)})
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        new_marathon = request.form.get('new_marathon')
        if new_marathon:
            m = Marathon(name=new_marathon); db.session.add(m); db.session.commit(); marathon_id = m.id
        station_id = request.form.get('station') or None
        new_station = request.form.get('new_station')
        if new_station:
            s = Station(name=new_station); db.session.add(s); db.session.commit(); station_id = s.id
        person_name = request.form.get('person') or request.form.get('new_person') or user.username
        person = Person.query.filter_by(name=person_name).first()
        if not person:
            person = Person(name=person_name); db.session.add(person); db.session.commit()
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        for eq_id, qty in zip(equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = ReturnRecord(marathon_id=marathon_id, station_id=station_id, equipment_id=eq_id, 
                           person_name=person.name, quantity=q, timestamp=datetime.utcnow(),
                           created_by=user.username)
            db.session.add(r)
        db.session.commit()
        return redirect(url_for('return_equipment', marathon=marathon_id))
    return render_template('return.html', marathons=marathons, stations=stations, equipments=equipments, persons=persons, unreturned=unreturned, selected_marathon=marathon_id, user=user)

@app.route('/report', methods=['GET'])
@login_required
def report():
    user = get_current_user()
    marathon_id = request.args.get('marathon') or None
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipment_summary = []; station_details = []; transactions = []
    from sqlalchemy import func
    equipments = Equipment.query.order_by(Equipment.name).all()
    stations = Station.query.order_by(Station.name).all()
    if marathon_id:
        for eq in equipments:
            issued = db.session.query(func.sum(IssueRecord.quantity)).filter(IssueRecord.equipment_id==eq.id, IssueRecord.marathon_id==marathon_id).scalar() or 0
            returned = db.session.query(func.sum(ReturnRecord.quantity)).filter(ReturnRecord.equipment_id==eq.id, ReturnRecord.marathon_id==marathon_id).scalar() or 0
            diff = issued - returned
            equipment_summary.append({'equipment': eq.name, 'issued': int(issued), 'returned': int(returned), 'remaining': int(diff)})
        for st in stations:
            items = []
            for eq in equipments:
                issued = db.session.query(func.sum(IssueRecord.quantity)).filter(IssueRecord.equipment_id==eq.id, IssueRecord.marathon_id==marathon_id, IssueRecord.station_id==st.id).scalar() or 0
                returned = db.session.query(func.sum(ReturnRecord.quantity)).filter(ReturnRecord.equipment_id==eq.id, ReturnRecord.marathon_id==marathon_id, ReturnRecord.station_id==st.id).scalar() or 0
                diff = issued - returned
                if diff>0: items.append({'equipment': eq.name, 'missing': int(diff)})
            if items: station_details.append({'station': st.name, 'items': items})
        # Get transaction history
        issue_records = IssueRecord.query.filter_by(marathon_id=marathon_id).all()
        return_records = ReturnRecord.query.filter_by(marathon_id=marathon_id).all()
        for rec in issue_records:
            station = Station.query.get(rec.station_id) if rec.station_id else None
            equipment = Equipment.query.get(rec.equipment_id)
            transactions.append({
                'type': 'issue',
                'timestamp': rec.timestamp,
                'station': station.name if station else None,
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        for rec in return_records:
            station = Station.query.get(rec.station_id) if rec.station_id else None
            equipment = Equipment.query.get(rec.equipment_id)
            transactions.append({
                'type': 'return',
                'timestamp': rec.timestamp,
                'station': station.name if station else None,
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        # Sort transactions by timestamp descending (newest first)
        transactions.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    return render_template('report.html', marathons=marathons, equipment_summary=equipment_summary, station_details=station_details, selected_marathon=marathon_id, transactions=transactions, user=user)

@app.route('/api/add_station', methods=['POST'])
@login_required
def api_add_station():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    s = Station(name=name); db.session.add(s); db.session.commit()
    return jsonify({'id':s.id,'name':s.name})

@app.route('/api/add_equipment', methods=['POST'])
@login_required
def api_add_equipment():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    e = Equipment(name=name); db.session.add(e); db.session.commit()
    return jsonify({'id':e.id,'name':e.name})

@app.route('/api/add_marathon', methods=['POST'])
@login_required
def api_add_marathon():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    m = Marathon(name=name); db.session.add(m); db.session.commit()
    return jsonify({'id':m.id,'name':m.name})

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
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'user')
        
        if not username or not password:
            flash('Tên đăng nhập và mật khẩu là bắt buộc!', 'danger')
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
    target_user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        if not new_password:
            flash('Mật khẩu không được để trống!', 'danger')
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
    target_user = User.query.get_or_404(user_id)
    
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
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    issue_records = IssueRecord.query.order_by(IssueRecord.timestamp.desc()).limit(100).all()
    return_records = ReturnRecord.query.order_by(ReturnRecord.timestamp.desc()).limit(100).all()
    return render_template('admin_dashboard.html', marathons=marathons, stations=stations, equipments=equipments, issue_records=issue_records, return_records=return_records, user=user)

@app.route('/admin/delete/issue/<int:record_id>', methods=['POST'])
@admin_required
def delete_issue_record(record_id):
    record = IssueRecord.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Bản ghi xuất đã được xóa thành công!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/return/<int:record_id>', methods=['POST'])
@admin_required
def delete_return_record(record_id):
    record = ReturnRecord.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Bản ghi nhập đã được xóa thành công!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/issue/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_issue_record(record_id):
    user = get_current_user()
    record = IssueRecord.query.get_or_404(record_id)
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    if request.method == 'POST':
        record.marathon_id = request.form.get('marathon') or None
        record.station_id = request.form.get('station') or None
        record.equipment_id = request.form.get('equipment')
        record.quantity = int(request.form.get('quantity'))
        record.person_name = request.form.get('person')
        db.session.commit()
        flash('Bản ghi xuất đã được cập nhật thành công!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_edit_issue.html', record=record, marathons=marathons, stations=stations, equipments=equipments, user=user)

@app.route('/admin/edit/return/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_return_record(record_id):
    user = get_current_user()
    record = ReturnRecord.query.get_or_404(record_id)
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    if request.method == 'POST':
        record.marathon_id = request.form.get('marathon') or None
        record.station_id = request.form.get('station') or None
        record.equipment_id = request.form.get('equipment')
        record.quantity = int(request.form.get('quantity'))
        record.person_name = request.form.get('person')
        db.session.commit()
        flash('Bản ghi nhập đã được cập nhật thành công!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_edit_return.html', record=record, marathons=marathons, stations=stations, equipments=equipments, user=user)

if __name__=='__main__': app.run(debug=True)
