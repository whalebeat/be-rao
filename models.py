from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

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

class ReturnRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marathon_id = db.Column(db.Integer, db.ForeignKey('marathon.id'), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    person_name = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)


def init_db():
    db.create_all()
