from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

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

class UsoMesa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False)
    duracion = db.Column(db.Integer)  # duración en segundos
    timestamp = db.Column(db.DateTime, default=datetime.now())
    
class Trabajador(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    

class Pedidos(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now())
    estado = db.Column(db.String(20), default='pendiente')
    
    mesa = db.relationship('Mesa', backref='pedidos')
