import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from models import db, init_db, Station, Equipment, Person, Marathon, IssueRecord, ReturnRecord
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

# Admin login decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function
@app.route('/')
def index():
    return render_template('index.html', title="Bê Rào Checklist")
@app.route('/issue', methods=['GET','POST'])
def issue():
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
        person_name = request.form.get('person') or request.form.get('new_person') or 'Unknown'
        person = Person.query.filter_by(name=person_name).first()
        if not person:
            person = Person(name=person_name); db.session.add(person); db.session.commit()
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        new_equipments = request.form.getlist('new_equipment[]')
        for idx, ne in enumerate(new_equipments):
            if ne and not ne.isspace():
                eq = Equipment(name=ne.strip()); db.session.add(eq); db.session.commit()
                if idx < len(equipment_ids) and (not equipment_ids[idx] or equipment_ids[idx]==''):
                    equipment_ids[idx] = str(eq.id)
                else:
                    equipment_ids.append(str(eq.id))
        for eq_id, qty in zip(equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = IssueRecord(marathon_id=marathon_id, station_id=station_id, equipment_id=eq_id, person_name=person.name, quantity=q, timestamp=datetime.utcnow())
            db.session.add(r)
        db.session.commit()
        return redirect(url_for('issue'))
    return render_template('issue.html', marathons=marathons, stations=stations, equipments=equipments, persons=persons)
@app.route('/return', methods=['GET','POST'])
def return_equipment():
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
        person_name = request.form.get('person') or request.form.get('new_person') or 'Unknown'
        person = Person.query.filter_by(name=person_name).first()
        if not person:
            person = Person(name=person_name); db.session.add(person); db.session.commit()
        equipment_ids = request.form.getlist('equipment[]')
        quantities = request.form.getlist('quantity[]')
        for eq_id, qty in zip(equipment_ids, quantities):
            try: q=int(qty)
            except: q=0
            if q<=0 or not eq_id: continue
            r = ReturnRecord(marathon_id=marathon_id, station_id=station_id, equipment_id=eq_id, person_name=person.name, quantity=q, timestamp=datetime.utcnow())
            db.session.add(r)
        db.session.commit()
        return redirect(url_for('return_equipment', marathon=marathon_id))
    return render_template('return.html', marathons=marathons, stations=stations, equipments=equipments, persons=persons, unreturned=unreturned, selected_marathon=marathon_id)
@app.route('/report', methods=['GET'])
def report():
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
                'person': rec.person_name
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
                'person': rec.person_name
            })
        # Sort transactions by timestamp descending (newest first)
        transactions.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    return render_template('report.html', marathons=marathons, equipment_summary=equipment_summary, station_details=station_details, selected_marathon=marathon_id, transactions=transactions)
@app.route('/api/add_station', methods=['POST'])
def api_add_station():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    s = Station(name=name); db.session.add(s); db.session.commit()
    return jsonify({'id':s.id,'name':s.name})
@app.route('/api/add_equipment', methods=['POST'])
def api_add_equipment():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    e = Equipment(name=name); db.session.add(e); db.session.commit()
    return jsonify({'id':e.id,'name':e.name})
@app.route('/api/add_marathon', methods=['POST'])
def api_add_marathon():
    name = request.json.get('name')
    if not name: return jsonify({'error':'missing name'}),400
    m = Marathon(name=name); db.session.add(m); db.session.commit()
    return jsonify({'id':m.id,'name':m.name})
@app.route('/api/persons')
def api_persons():
    persons = Person.query.order_by(Person.name).all(); return jsonify([p.name for p in persons])

# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin_user = os.getenv('ADMIN_USERNAME', 'admin')
        admin_pass = os.getenv('ADMIN_PASSWORD', 'admin123')
        if username == admin_user and password == admin_pass:
            session['admin_logged_in'] = True
            flash('Successfully logged in!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials!', 'danger')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Successfully logged out!', 'success')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    marathons = Marathon.query.order_by(Marathon.name).all()
    stations = Station.query.order_by(Station.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    issue_records = IssueRecord.query.order_by(IssueRecord.timestamp.desc()).limit(100).all()
    return_records = ReturnRecord.query.order_by(ReturnRecord.timestamp.desc()).limit(100).all()
    return render_template('admin_dashboard.html', marathons=marathons, stations=stations, equipments=equipments, issue_records=issue_records, return_records=return_records)

@app.route('/admin/delete/issue/<int:record_id>', methods=['POST'])
@admin_required
def delete_issue_record(record_id):
    record = IssueRecord.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Issue record deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/return/<int:record_id>', methods=['POST'])
@admin_required
def delete_return_record(record_id):
    record = ReturnRecord.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Return record deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/issue/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_issue_record(record_id):
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
        flash('Issue record updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_edit_issue.html', record=record, marathons=marathons, stations=stations, equipments=equipments)

@app.route('/admin/edit/return/<int:record_id>', methods=['GET', 'POST'])
@admin_required
def edit_return_record(record_id):
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
        flash('Return record updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_edit_return.html', record=record, marathons=marathons, stations=stations, equipments=equipments)

if __name__=='__main__': app.run(debug=True)
