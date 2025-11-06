from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Marathon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

class Station(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

class Person(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

class IssueRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marathon_id = db.Column(db.Integer, db.ForeignKey('marathon.id'), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    person_name = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    created_by = db.Column(db.String(100))  # Username of creator

class ReturnRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marathon_id = db.Column(db.Integer, db.ForeignKey('marathon.id'), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    person_name = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    created_by = db.Column(db.String(100))  # Username of creator


def init_db():
    db.create_all()
    # Ensure older SQLite databases get new columns added without manual migrations.
    # If the app is using SQLite and the `created_by` column was added to the model
    # after the DB file was created, add the column at startup so queries that
    # reference it won't fail with "no such column".
    try:
        engine_url = str(db.engine.url)
    except Exception:
        engine_url = ''
    if 'sqlite' in engine_url:
        from sqlalchemy import text

        def _has_column(table, colname):
            res = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
            # PRAGMA returns rows where the second column (index 1) is the column name
            return any(r[1] == colname for r in res)

        # Add `created_by` to issue_record if missing
        if not _has_column('issue_record', 'created_by'):
            db.session.execute(text("ALTER TABLE issue_record ADD COLUMN created_by TEXT"))
        # Add `created_by` to return_record if missing
        if not _has_column('return_record', 'created_by'):
            db.session.execute(text("ALTER TABLE return_record ADD COLUMN created_by TEXT"))
        db.session.commit()
    # Create default admin user if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
