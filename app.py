import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from models import db, init_db, Station, Equipment, Person, Marathon, IssueRecord, ReturnRecord, User, StoreIssueRecord, StoreReturnRecord
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

# Admin or Storekeeper required decorator
def admin_or_storekeeper_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role not in ['admin', 'storekeeper']:
            flash('Bạn không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    if session.get('user_id'):
        return User.query.get(session['user_id'])
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
        return user.assigned_marathons

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
    return render_template('login.html', user=None)

@app.route('/logout')
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
        
        user.set_password(new_password)
        db.session.commit()
        flash('Mật khẩu đã được thay đổi thành công!', 'success')
        return redirect(url_for('index'))
    
    return render_template('change_password.html', user=user)

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
        new_marathon = request.form.get('new_marathon')
        if new_marathon:
            m = Marathon(name=new_marathon); db.session.add(m); db.session.commit(); marathon_id = m.id
        station_id = request.form.get('station') or None
        new_station = request.form.get('new_station')
        if new_station:
            s = Station(name=new_station); db.session.add(s); db.session.commit(); station_id = s.id
        
        # Only admin can select/enter a different person, others use their username
        if user.role == 'admin':
            person_name = request.form.get('person') or request.form.get('new_person') or user.username
        else:
            person_name = user.username
        
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
    marathons = get_user_marathons(user)
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    marathon_id = request.args.get('marathon') or None
    selected_station_id = request.args.get('station') or None
    unreturned = []
    if marathon_id:
        from sqlalchemy import func
        issued_q = db.session.query(IssueRecord.station_id, IssueRecord.equipment_id, func.sum(IssueRecord.quantity).label('issued')).filter(IssueRecord.marathon_id==marathon_id).group_by(IssueRecord.station_id, IssueRecord.equipment_id).subquery()
        returned_q = db.session.query(ReturnRecord.station_id, ReturnRecord.equipment_id, func.sum(ReturnRecord.quantity).label('returned')).filter(ReturnRecord.marathon_id==marathon_id).group_by(ReturnRecord.station_id, ReturnRecord.equipment_id).subquery()
        base_query = db.session.query(issued_q.c.station_id, issued_q.c.equipment_id, issued_q.c.issued, returned_q.c.returned).outerjoin(returned_q, (issued_q.c.station_id==returned_q.c.station_id)&(issued_q.c.equipment_id==returned_q.c.equipment_id))
        if selected_station_id:
            base_query = base_query.filter(issued_q.c.station_id == selected_station_id)
        rows = base_query.all()
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
        
        # Only admin can select/enter a different person, others use their username
        if user.role == 'admin':
            person_name = request.form.get('person') or request.form.get('new_person') or user.username
        else:
            person_name = user.username
        
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
    return render_template('return.html', marathons=marathons, stations=stations, equipments=equipments, 
                         persons=persons, unreturned=unreturned, selected_marathon=marathon_id, 
                         selected_station=selected_station_id, user=user)

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
            equipment_summary.append({
                'equipment': eq.name,
                'issued': int(issued), 
                'returned': int(returned), 
                'remaining': int(diff)
            })
        for st in stations:
            items = []
            for eq in equipments:
                issued = db.session.query(func.sum(IssueRecord.quantity)).filter(IssueRecord.equipment_id==eq.id, IssueRecord.marathon_id==marathon_id, IssueRecord.station_id==st.id).scalar() or 0
                returned = db.session.query(func.sum(ReturnRecord.quantity)).filter(ReturnRecord.equipment_id==eq.id, ReturnRecord.marathon_id==marathon_id, ReturnRecord.station_id==st.id).scalar() or 0
                diff = issued - returned
                if diff>0: items.append({'equipment': eq.name, 'missing': int(diff)})
            if items: station_details.append({'station': st.name, 'items': items})
        # Get transaction history (only issue and return records)
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

@app.route('/reconciliation_report', methods=['GET'])
@admin_or_storekeeper_required
def reconciliation_report():
    user = get_current_user()
    marathon_id = request.args.get('marathon') or None
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipment_summary = []; store_transactions = []
    from sqlalchemy import func
    equipments = Equipment.query.order_by(Equipment.name).all()
    
    if marathon_id:
        # Show statistics and records for selected marathon
        for eq in equipments:
            store_issued = db.session.query(func.sum(StoreIssueRecord.quantity)).filter(StoreIssueRecord.equipment_id==eq.id, StoreIssueRecord.marathon_id==marathon_id).scalar() or 0
            issued = db.session.query(func.sum(IssueRecord.quantity)).filter(IssueRecord.equipment_id==eq.id, IssueRecord.marathon_id==marathon_id).scalar() or 0
            returned = db.session.query(func.sum(ReturnRecord.quantity)).filter(ReturnRecord.equipment_id==eq.id, ReturnRecord.marathon_id==marathon_id).scalar() or 0
            store_returned = db.session.query(func.sum(StoreReturnRecord.quantity)).filter(StoreReturnRecord.equipment_id==eq.id, StoreReturnRecord.marathon_id==marathon_id).scalar() or 0
            
            # Calculate differences
            store_vs_issued = store_issued - issued  # Should be 0 if balanced
            returned_vs_store = returned - store_returned  # Should be 0 if balanced
            
            equipment_summary.append({
                'equipment': eq.name,
                'store_issued': int(store_issued),
                'issued': int(issued), 
                'store_vs_issued_diff': int(store_vs_issued),
                'returned': int(returned), 
                'store_returned': int(store_returned),
                'returned_vs_store_diff': int(returned_vs_store)
            })
        
        # Get store transaction history for selected marathon
        store_issue_records = StoreIssueRecord.query.filter_by(marathon_id=marathon_id).order_by(StoreIssueRecord.timestamp.desc()).all()
        store_return_records = StoreReturnRecord.query.filter_by(marathon_id=marathon_id).order_by(StoreReturnRecord.timestamp.desc()).all()
        
        for rec in store_issue_records:
            equipment = Equipment.query.get(rec.equipment_id)
            marathon = Marathon.query.get(rec.marathon_id) if rec.marathon_id else None
            store_transactions.append({
                'type': 'store_issue',
                'timestamp': rec.timestamp,
                'marathon': marathon.name if marathon else '-----',
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        
        for rec in store_return_records:
            equipment = Equipment.query.get(rec.equipment_id)
            marathon = Marathon.query.get(rec.marathon_id) if rec.marathon_id else None
            store_transactions.append({
                'type': 'store_return',
                'timestamp': rec.timestamp,
                'marathon': marathon.name if marathon else '-----',
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        
        # Sort transactions by timestamp descending (newest first)
        store_transactions.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    else:
        # Show 100 most recent store issue/return records when no marathon is selected
        store_issue_records = StoreIssueRecord.query.order_by(StoreIssueRecord.timestamp.desc()).limit(100).all()
        store_return_records = StoreReturnRecord.query.order_by(StoreReturnRecord.timestamp.desc()).limit(100).all()
        
        for rec in store_issue_records:
            equipment = Equipment.query.get(rec.equipment_id)
            marathon = Marathon.query.get(rec.marathon_id) if rec.marathon_id else None
            store_transactions.append({
                'type': 'store_issue',
                'timestamp': rec.timestamp,
                'marathon': marathon.name if marathon else '-----',
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        
        for rec in store_return_records:
            equipment = Equipment.query.get(rec.equipment_id)
            marathon = Marathon.query.get(rec.marathon_id) if rec.marathon_id else None
            store_transactions.append({
                'type': 'store_return',
                'timestamp': rec.timestamp,
                'marathon': marathon.name if marathon else '-----',
                'equipment': equipment.name if equipment else None,
                'quantity': rec.quantity,
                'person': rec.person_name,
                'created_by': rec.created_by
            })
        
        # Sort transactions by timestamp descending (newest first)
        store_transactions.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    
    return render_template('reconciliation_report.html', marathons=marathons, equipment_summary=equipment_summary, 
                         selected_marathon=marathon_id, store_transactions=store_transactions, user=user)

@app.route('/store_issue', methods=['GET','POST'])
@login_required
def store_issue():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    if request.method=='POST':
        marathon_id = request.form.get('marathon') or None
        new_marathon = request.form.get('new_marathon')
        if new_marathon:
            m = Marathon(name=new_marathon)
            db.session.add(m)
            db.session.commit()
            marathon_id = m.id
        
        person_name = request.form.get('person') or request.form.get('new_person')
        if person_name:
            person = Person.query.filter_by(name=person_name).first()
            if not person:
                person = Person(name=person_name)
                db.session.add(person)
                db.session.commit()
        
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        
        for eq_id, qty in zip(equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = StoreIssueRecord(marathon_id=marathon_id, equipment_id=eq_id, 
                          person_name=person_name, quantity=q, timestamp=datetime.utcnow(),
                          created_by=user.username)
            db.session.add(r)
        db.session.commit()
        flash('Xuất kho thành công!', 'success')
        return redirect(url_for('store_issue'))
    return render_template('store_issue.html', marathons=marathons, equipments=equipments, persons=persons, user=user)

@app.route('/store_return', methods=['GET','POST'])
@login_required
def store_return():
    user = get_current_user()
    marathons = Marathon.query.order_by(Marathon.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    persons = Person.query.order_by(Person.name).all()
    marathon_id = request.args.get('marathon') or None
    unreturned = []
    if marathon_id:
        from sqlalchemy import func
        # Calculate: store_issued - issue + return - store_returned
        store_issued_q = db.session.query(StoreIssueRecord.equipment_id, func.sum(StoreIssueRecord.quantity).label('store_issued')).filter(StoreIssueRecord.marathon_id==marathon_id).group_by(StoreIssueRecord.equipment_id).subquery()
        issued_q = db.session.query(IssueRecord.equipment_id, func.sum(IssueRecord.quantity).label('issued')).filter(IssueRecord.marathon_id==marathon_id).group_by(IssueRecord.equipment_id).subquery()
        returned_q = db.session.query(ReturnRecord.equipment_id, func.sum(ReturnRecord.quantity).label('returned')).filter(ReturnRecord.marathon_id==marathon_id).group_by(ReturnRecord.equipment_id).subquery()
        store_returned_q = db.session.query(StoreReturnRecord.equipment_id, func.sum(StoreReturnRecord.quantity).label('store_returned')).filter(StoreReturnRecord.marathon_id==marathon_id).group_by(StoreReturnRecord.equipment_id).subquery()
        
        base_query = db.session.query(
            store_issued_q.c.equipment_id,
            store_issued_q.c.store_issued,
            issued_q.c.issued,
            returned_q.c.returned,
            store_returned_q.c.store_returned
        ).outerjoin(issued_q, store_issued_q.c.equipment_id==issued_q.c.equipment_id
        ).outerjoin(returned_q, store_issued_q.c.equipment_id==returned_q.c.equipment_id
        ).outerjoin(store_returned_q, store_issued_q.c.equipment_id==store_returned_q.c.equipment_id)
        
        rows = base_query.all()
        for r in rows:
            store_issued = r.store_issued or 0
            issued = r.issued or 0
            returned = r.returned or 0
            store_returned = r.store_returned or 0
            # Available to return to store = returned from stations - already returned to store
            available = returned - store_returned
            if available > 0:
                eq = Equipment.query.get(r.equipment_id)
                unreturned.append({'equipment_id': r.equipment_id, 'equipment': eq.name if eq else '—', 'available': int(available)})
    
    if request.method=='POST':
        # Get marathon_id from form data (for non-race returns) or from query string (for race-specific returns)
        form_marathon_id = request.form.get('marathon')
        if form_marathon_id:
            marathon_id = form_marathon_id
        else:
            marathon_id = None
        
        person_name = request.form.get('person') or request.form.get('new_person')
        if person_name:
            person = Person.query.filter_by(name=person_name).first()
            if not person:
                person = Person(name=person_name)
                db.session.add(person)
                db.session.commit()
        
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        
        for eq_id, qty in zip(equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = StoreReturnRecord(marathon_id=marathon_id, equipment_id=eq_id, 
                           person_name=person_name, quantity=q, timestamp=datetime.utcnow(),
                           created_by=user.username)
            db.session.add(r)
        db.session.commit()
        flash('Nhập kho thành công!', 'success')
        # Redirect back to the same page with or without marathon parameter
        if marathon_id:
            return redirect(url_for('store_return', marathon=marathon_id))
        else:
            return redirect(url_for('store_return'))
    
    return render_template('store_return.html', marathons=marathons, equipments=equipments, persons=persons,
                         unreturned=unreturned, selected_marathon=marathon_id, user=user)

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

# Marathon management routes
@app.route('/admin/marathon/add', methods=['POST'])
@admin_required
def admin_add_marathon():
    name = request.form.get('name')
    if name:
        marathon = Marathon(name=name)
        db.session.add(marathon)
        db.session.commit()
        flash(f'Giải chạy "{name}" đã được thêm!', 'success')
    return redirect(url_for('admin_dashboard') + '#marathons')

@app.route('/admin/marathon/<int:marathon_id>/edit', methods=['POST'])
@admin_required
def admin_edit_marathon(marathon_id):
    marathon = Marathon.query.get_or_404(marathon_id)
    name = request.form.get('name')
    if name:
        marathon.name = name
        db.session.commit()
        flash(f'Giải chạy đã được cập nhật!', 'success')
    return redirect(url_for('admin_dashboard') + '#marathons')

@app.route('/admin/marathon/<int:marathon_id>/delete', methods=['POST'])
@admin_required
def admin_delete_marathon(marathon_id):
    marathon = Marathon.query.get_or_404(marathon_id)
    name = marathon.name
    db.session.delete(marathon)
    db.session.commit()
    flash(f'Giải chạy "{name}" đã được xóa!', 'success')
    return redirect(url_for('admin_dashboard') + '#marathons')

# Station management routes
@app.route('/admin/station/add', methods=['POST'])
@admin_required
def admin_add_station_form():
    name = request.form.get('name')
    if name:
        station = Station(name=name)
        db.session.add(station)
        db.session.commit()
        flash(f'Trạm "{name}" đã được thêm!', 'success')
    return redirect(url_for('admin_dashboard') + '#stations')

@app.route('/admin/station/<int:station_id>/edit', methods=['POST'])
@admin_required
def admin_edit_station(station_id):
    station = Station.query.get_or_404(station_id)
    name = request.form.get('name')
    if name:
        station.name = name
        db.session.commit()
        flash(f'Trạm đã được cập nhật!', 'success')
    return redirect(url_for('admin_dashboard') + '#stations')

@app.route('/admin/station/<int:station_id>/delete', methods=['POST'])
@admin_required
def admin_delete_station(station_id):
    station = Station.query.get_or_404(station_id)
    name = station.name
    db.session.delete(station)
    db.session.commit()
    flash(f'Trạm "{name}" đã được xóa!', 'success')
    return redirect(url_for('admin_dashboard') + '#stations')

# Equipment management routes
@app.route('/admin/equipment/add', methods=['POST'])
@admin_required
def admin_add_equipment_form():
    name = request.form.get('name')
    if name:
        equipment = Equipment(name=name)
        db.session.add(equipment)
        db.session.commit()
        flash(f'Thiết bị "{name}" đã được thêm!', 'success')
    return redirect(url_for('admin_dashboard') + '#equipments-manage')

@app.route('/admin/equipment/<int:equipment_id>/edit', methods=['POST'])
@admin_required
def admin_edit_equipment(equipment_id):
    equipment = Equipment.query.get_or_404(equipment_id)
    name = request.form.get('name')
    if name:
        equipment.name = name
        db.session.commit()
        flash(f'Thiết bị đã được cập nhật!', 'success')
    return redirect(url_for('admin_dashboard') + '#equipments-manage')

@app.route('/admin/equipment/<int:equipment_id>/delete', methods=['POST'])
@admin_required
def admin_delete_equipment(equipment_id):
    equipment = Equipment.query.get_or_404(equipment_id)
    name = equipment.name
    db.session.delete(equipment)
    db.session.commit()
    flash(f'Thiết bị "{name}" đã được xóa!', 'success')
    return redirect(url_for('admin_dashboard') + '#equipments-manage')

@app.route('/admin/equipment/<int:equipment_id>/set_available', methods=['POST'])
@admin_required
def admin_set_available_quantity(equipment_id):
    equipment = Equipment.query.get_or_404(equipment_id)
    available_quantity = request.form.get('available_quantity')
    if available_quantity is not None:
        try:
            equipment.available_quantity = int(available_quantity)
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
                    equipment.available_quantity = int(qty_value)
                except ValueError:
                    pass  # Skip invalid values
        
        db.session.commit()
        flash('Đã cập nhật tồn kho thành công!', 'success')
        return redirect(url_for('manage_inventory'))
    
    return render_template('manage_inventory.html', equipments=equipments, user=user)

# User-Marathon assignment routes
@app.route('/admin/users/<int:user_id>/marathons', methods=['GET', 'POST'])
@admin_required
def admin_user_marathons(user_id):
    current_user = get_current_user()
    target_user = User.query.get_or_404(user_id)
    all_marathons = Marathon.query.order_by(Marathon.name).all()
    
    if request.method == 'POST':
        # Get selected marathon IDs from form
        selected_marathon_ids = request.form.getlist('marathons')
        selected_marathon_ids = [int(mid) for mid in selected_marathon_ids if mid]
        
        # Clear existing assignments
        target_user.assigned_marathons = []
        
        # Add new assignments
        for marathon_id in selected_marathon_ids:
            marathon = Marathon.query.get(marathon_id)
            if marathon:
                target_user.assigned_marathons.append(marathon)
        
        db.session.commit()
        flash(f'Đã cập nhật phân công giải chạy cho {target_user.username}!', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin_user_marathons.html', target_user=target_user, all_marathons=all_marathons, user=current_user)

@app.route('/admin/users/<int:user_id>/change_role', methods=['GET', 'POST'])
@admin_required
def admin_change_user_role(user_id):
    current_user = get_current_user()
    target_user = User.query.get_or_404(user_id)
    
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
    selected_marathon = Marathon.query.get(selected_marathon_id) if selected_marathon_id else None
    
    if request.method == 'POST':
        marathon_id = request.form.get('marathon_id')
        selected_marathon = Marathon.query.get_or_404(marathon_id)
        
        # Get selected user IDs from form
        selected_user_ids = request.form.getlist('users')
        selected_user_ids = [int(uid) for uid in selected_user_ids if uid]
        
        # Clear existing assignments for this marathon
        for user in selected_marathon.assigned_users:
            if user.role != 'admin':  # Don't modify admin assignments
                selected_marathon.assigned_users.remove(user)
        
        # Add new assignments
        for user_id in selected_user_ids:
            user = User.query.get(user_id)
            if user and user.role != 'admin' and user not in selected_marathon.assigned_users:
                selected_marathon.assigned_users.append(user)
        
        db.session.commit()
        flash(f'Đã cập nhật phân công người dùng cho giải chạy "{selected_marathon.name}"!', 'success')
        return redirect(url_for('admin_marathon_users', marathon=marathon_id))
    
    return render_template('admin_marathon_users.html', marathons=marathons, all_users=all_users, 
                         selected_marathon=selected_marathon, user=current_user)

if __name__=='__main__': app.run(debug=True)
