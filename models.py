from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    joined_at = db.Column(db.DateTime, default=datetime.now())
    assigned_table = db.Column(db.Integer, nullable=True)
    sid = db.Column(db.String, nullable=True)  # Socket session ID

class Mesa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_occupied = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    cliente = db.relationship('Cliente', backref='mesa')
