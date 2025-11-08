from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Association table for User-Marathon many-to-many relationship
user_marathon = db.Table('user_marathon',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('marathon_id', db.Integer, db.ForeignKey('marathon.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin', 'user', or 'storekeeper'
    assigned_marathons = db.relationship('Marathon', secondary=user_marathon, backref='assigned_users')
    
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
    available_quantity = db.Column(db.Integer, default=0)  # Tồn kho - available inventory

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

class StoreIssueRecord(db.Model):
    """Xuất kho - Store issues equipment to be dispatched"""
    id = db.Column(db.Integer, primary_key=True)
    marathon_id = db.Column(db.Integer, db.ForeignKey('marathon.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    person_name = db.Column(db.String(200))  # Person receiving from store
    quantity = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    created_by = db.Column(db.String(100))  # Username of storekeeper

class StoreReturnRecord(db.Model):
    """Nhập kho - Equipment returned back to store"""
    id = db.Column(db.Integer, primary_key=True)
    marathon_id = db.Column(db.Integer, db.ForeignKey('marathon.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    person_name = db.Column(db.String(200))  # Person returning to store
    quantity = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    created_by = db.Column(db.String(100))  # Username of storekeeper


def init_db():
    db.create_all()
    # Ensure older databases get new columns added without manual migrations.
    try:
        engine_url = str(db.engine.url)
    except Exception:
        engine_url = ''
    
    from sqlalchemy import text, inspect
    
    def _has_column(table, colname):
        """Check if a column exists in a table (works for both SQLite and PostgreSQL)"""
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns(table)]
        return colname in columns
    
    try:
        # Add `created_by` to issue_record if missing
        if not _has_column('issue_record', 'created_by'):
            if 'sqlite' in engine_url:
                db.session.execute(text("ALTER TABLE issue_record ADD COLUMN created_by TEXT"))
            else:
                db.session.execute(text("ALTER TABLE issue_record ADD COLUMN created_by VARCHAR(100)"))
        
        # Add `created_by` to return_record if missing
        if not _has_column('return_record', 'created_by'):
            if 'sqlite' in engine_url:
                db.session.execute(text("ALTER TABLE return_record ADD COLUMN created_by TEXT"))
            else:
                db.session.execute(text("ALTER TABLE return_record ADD COLUMN created_by VARCHAR(100)"))
        
        # Add `person_name` to store_issue_record if missing
        if not _has_column('store_issue_record', 'person_name'):
            if 'sqlite' in engine_url:
                db.session.execute(text("ALTER TABLE store_issue_record ADD COLUMN person_name TEXT"))
            else:
                db.session.execute(text("ALTER TABLE store_issue_record ADD COLUMN person_name VARCHAR(200)"))
        
        # Add `person_name` to store_return_record if missing
        if not _has_column('store_return_record', 'person_name'):
            if 'sqlite' in engine_url:
                db.session.execute(text("ALTER TABLE store_return_record ADD COLUMN person_name TEXT"))
            else:
                db.session.execute(text("ALTER TABLE store_return_record ADD COLUMN person_name VARCHAR(200)"))
        
        # Add `available_quantity` to equipment if missing
        if not _has_column('equipment', 'available_quantity'):
            if 'sqlite' in engine_url:
                db.session.execute(text("ALTER TABLE equipment ADD COLUMN available_quantity INTEGER DEFAULT 0"))
            else:
                db.session.execute(text("ALTER TABLE equipment ADD COLUMN available_quantity INTEGER DEFAULT 0"))
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration warning: {e}")
    # Create default admin user if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
