from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from models import db, Cliente, Mesa
from datetime import datetime
import statistics
from flask_migrate import Migrate

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

socketio = SocketIO(app)

with app.app_context():
    db.create_all()
    if not Mesa.query.first():
        for i in range(1, 6):  # Crea 5 mesas
            db.session.add(Mesa())
        db.session.commit()

@app.route('/cliente')
def cliente():
    nuevo = Cliente()
    db.session.add(nuevo)
    db.session.commit()
    return render_template('client.html', numero=nuevo.id)

@app.route('/trabajador')
def trabajador():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    mesas = Mesa.query.all()
    return render_template('worker.html', clientes=clientes, mesas=mesas)

@app.route('/liberar_mesa/<int:mesa_id>', methods=['POST'])
def liberar_mesa(mesa_id):
    mesa = Mesa.query.get(mesa_id)
    if mesa and mesa.is_occupied:
        tiempo_usado = (datetime.utcnow() - mesa.start_time).total_seconds() if mesa.start_time else 0
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.cliente_id = None
        db.session.commit()

        siguiente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
        if siguiente:
            siguiente.assigned_table = mesa.id
            mesa.is_occupied = True
            mesa.start_time = datetime.utcnow()
            mesa.cliente_id = siguiente.id
            db.session.commit()
            if siguiente.sid:
                socketio.emit("es_tu_turno", {
                    "mesa": mesa.id
                }, to=siguiente.sid)

        return jsonify({"mensaje": "Mesa liberada", "duracion": tiempo_usado})
    return jsonify({"mensaje": "Mesa no ocupada o no encontrada"})

@app.route('/ocupar_mesa/<int:mesa_id>', methods=['POST'])
def ocupar_mesa(mesa_id):
    mesa = Mesa.query.get(mesa_id)
    if mesa and not mesa.is_occupied:
        mesa.is_occupied = True
        mesa.start_time = datetime.utcnow()
        mesa.cliente_id = None
        db.session.commit()
        return jsonify({"mensaje": "Mesa marcada como ocupada manualmente."})
    return jsonify({"mensaje": "Mesa ya ocupada o no encontrada."})

@app.route('/estadisticas')
def estadisticas():
    mesas = Mesa.query.all()
    tiempos = []
    for mesa in mesas:
        if mesa.start_time and mesa.is_occupied:
            tiempos.append((datetime.utcnow() - mesa.start_time).total_seconds())
    promedio = statistics.mean(tiempos) if tiempos else 0
    return jsonify({"promedio_tiempo_uso": promedio})

@socketio.on("registrar_cliente")
def registrar_cliente(data):
    cliente_id = data.get("id")
    sid = request.sid
    cliente = Cliente.query.get(cliente_id)
    if cliente:
        cliente.sid = sid
        db.session.commit()
        join_room(sid)


if __name__ == "__main__":
    socketio.run(app)
