from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from models import UsoMesa, db, Cliente, Mesa
from datetime import datetime
import statistics
from flask_migrate import Migrate

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
migrate = Migrate(app, db)

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
    socketio.emit('actualizar_cola')
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
        tiempo_usado = (datetime.now() - mesa.start_time).total_seconds() if mesa.start_time else 0
        uso = UsoMesa(mesa_id=mesa.id, duracion=tiempo_usado)#guarda el tiempo de uso de la mesa para calcular promedio
        db.session.add(uso)
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.cliente_id = None
        db.session.commit()

        siguiente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
        if siguiente:
            siguiente.assigned_table = mesa.id
            mesa.is_occupied = True
            mesa.start_time = datetime.now()
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
        mesa.start_time = datetime.now()
        mesa.cliente_id = None
        db.session.commit()
        return jsonify({"mensaje": "Mesa marcada como ocupada manualmente."})
    return jsonify({"mensaje": "Mesa ya ocupada o no encontrada."})

@app.route('/estadisticas')
def estadisticas():
    usos = UsoMesa.query.all()  # Trae todos los registros históricos

    if not usos:
        promedio = 0
    else:
        total_segundos = sum(uso.duracion for uso in usos)
        promedio = total_segundos / len(usos)
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
        socketio.emit('nuevo_cliente', {
            'cliente_id': cliente.id,
            'joined_at': cliente.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        })

@app.route('/clientes')
def obtener_clientes():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    return jsonify([
        {
            'id': c.id,
            'joined_at': c.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        } for c in clientes
    ])


if __name__ == "__main__":
    socketio.run(app)
