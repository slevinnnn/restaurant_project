from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=True)
    cantidad_comensales = db.Column(db.Integer, nullable=True)
    joined_at = db.Column(db.DateTime, default=datetime.now())
    assigned_table = db.Column(db.Integer, nullable=True)
    sid = db.Column(db.String, nullable=True)  # Socket session ID

class Mesa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_occupied = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    cliente = db.relationship('Cliente', backref='mesa')
    llego_comensal = db.Column(db.Boolean, default=False)
    reservada = db.Column(db.Boolean, default=False)
    capacidad = db.Column(db.Integer, default=4)  # Capacidad de la mesa

class UsoMesa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False)
    duracion = db.Column(db.Integer)  # duración en segundos
    timestamp = db.Column(db.DateTime, default=datetime.now())
    
class Trabajador(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('email', name='uq_trabajador_email'),
    )

    @staticmethod
    def validate_email(email):
        import re
        # Patrón de regex más completo para validar emails
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

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
