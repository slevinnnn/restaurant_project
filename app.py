import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from models import UsoMesa, db, Cliente, Mesa
from datetime import datetime
import statistics
from flask_migrate import Migrate
from flask import render_template, request, redirect, url_for, session, flash
from models import Trabajador

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'clave_super_secreta_123'
db.init_app(app)
migrate = Migrate(app, db)

socketio = SocketIO(app)

def initialize_tables():
    with app.app_context():
        db.create_all()
        mesas_existentes = db.session.query(db.func.count(Mesa.id)).scalar() or 0
        mesas_deseadas = 8
        
        if mesas_existentes < mesas_deseadas:
            for i in range(mesas_existentes, mesas_deseadas):
                db.session.add(Mesa())
            db.session.commit()

if __name__ == "__main__":
    initialize_tables()

@app.route('/cliente')
def cliente(nombre=None, cantidad_comensales=None):
    nombre = request.args.get('nombre')
    cantidad_comensales = request.args.get('cantidad_comensales')
    nuevo = Cliente(
        joined_at=datetime.now(),
        nombre=nombre,
        cantidad_comensales=cantidad_comensales
    )
    db.session.add(nuevo)
    db.session.commit()
    socketio.emit('actualizar_cola')
    socketio.emit('actualizar_lista_clientes')
    enviar_estado_cola()
    return render_template('client.html', numero=nuevo.id, nombre=nombre)

@app.route('/trabajador',methods=['GET',"POST"])
def trabajador():
    current_time = datetime.now()
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    mesas = Mesa.query.all()
    
    # Determinar qué mesas están recién asignadas
    for mesa in mesas:
        if mesa.is_occupied and not mesa.llego_comensal:
            mesa.recien_asignada = True
        else:
            mesa.recien_asignada = False
            
    return render_template('worker.html', clientes=clientes, mesas=mesas)


def enviar_estado_cola():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    if clientes:
        primero = clientes[0].id
    else:
        primero = None
    # Para cada cliente en cola, emitimos a su SID la posición y el primero
    for idx, cliente in enumerate(clientes):
        if cliente.sid:
            socketio.emit('actualizar_posicion', {
                'primero': primero,
                'posicion': idx + 1,  # 1-based index
                'total': len(clientes)
            }, to=cliente.sid)


@app.route('/liberar_mesa/<int:mesa_id>', methods=['POST'])
def liberar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and mesa.is_occupied:
        tiempo_usado = (datetime.now() - mesa.start_time).total_seconds() if mesa.start_time else 0
        uso = UsoMesa(mesa_id=mesa.id, duracion=tiempo_usado)
        db.session.add(uso)
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.cliente_id = None
        mesa.llego_comensal = False
        db.session.commit()

        siguiente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
        if siguiente:
            siguiente.assigned_table = mesa.id
            mesa.is_occupied = True
            mesa.start_time = datetime.now()
            mesa.cliente_id = siguiente.id
            mesa.llego_comensal = False
            db.session.commit()
            if siguiente.sid:
                socketio.emit("es_tu_turno", {
                    "mesa": mesa.id
                }, to=siguiente.sid)
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        return jsonify({"success": True})
    socketio.emit('actualizar_mesas')
    socketio.emit('actualizar_lista_clientes')
    enviar_estado_cola()
    return jsonify({"success": False})

@app.route('/ocupar_mesa/<int:mesa_id>', methods=['POST'])
def ocupar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and not mesa.is_occupied:
        mesa.is_occupied = True
        mesa.start_time = datetime.now()
        mesa.cliente_id = None
        mesa.llego_comensal = False
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

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
    cliente = db.session.get(Cliente, cliente_id)
    if cliente:
        cliente.sid = sid
        db.session.commit()
        join_room(sid)
        socketio.emit('nuevo_cliente', {
            'cliente_id': cliente.id,
            'joined_at': cliente.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        })
        enviar_estado_cola()

@app.route('/clientes')
def obtener_clientes():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    return jsonify([
        {
            'id': c.id,
            'nombre': c.nombre,
            'cantidad_comensales': c.cantidad_comensales,
            'joined_at': c.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        } for c in clientes
    ])


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if not email or not username or not password or not confirm_password:
            flash('Todos los campos son requeridos')
            return redirect(url_for('registro'))

        if not Trabajador.validate_email(email):
            flash('Por favor ingresa un correo electrónico válido')
            return redirect(url_for('registro'))

        if password != confirm_password:
            flash('Las contraseñas no coinciden')
            return redirect(url_for('registro'))

        if Trabajador.query.filter_by(email=email).first():
            flash('Este correo electrónico ya está registrado')
            return redirect(url_for('registro'))
            
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres')
            return redirect(url_for('registro'))

        nuevo = Trabajador(email=email, username=username)
        nuevo.set_password(password)
        db.session.add(nuevo)
        db.session.commit()
        flash('Registro exitoso, ahora inicia sesión')
        return redirect(url_for('login'))

    return render_template('registro_mesero.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        trabajador = Trabajador.query.filter_by(email=email).first()

        if trabajador and trabajador.check_password(password):
            session['trabajador_id'] = trabajador.id
            flash('Bienvenido, ' + trabajador.username)
            return redirect(url_for('trabajador'))  # o tu dashboard
        else:
            flash('Credenciales incorrectas')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('trabajador_id', None)
    flash('Sesión cerrada')
    return redirect(url_for('login'))


@app.route('/clientes_espera')
def clientes_espera():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    return render_template('clientes_espera.html', clientes=clientes)

@app.route('/qr_landing', methods=['GET', 'POST'])
def qr_landing():
    if request.method == 'POST':
        nombre = request.form["nombre"]
        cantidad_comensales = request.form["cantidad_comensales"]
        return redirect(url_for('cliente', nombre=nombre, cantidad_comensales=cantidad_comensales))
    return render_template('qr_landing.html')

@app.route('/confirmar_llegada/<int:mesa_id>', methods=['POST'])
def confirmar_llegada(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and mesa.is_occupied:
        mesa.llego_comensal = True
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
