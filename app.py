import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from functools import wraps
from models import UsoMesa, db, Cliente, Mesa
from datetime import datetime
import pytz
import statistics
from flask_migrate import Migrate
from flask import render_template, request, redirect, url_for, session, flash
from models import Trabajador

def get_chile_time():
    santiago_tz = pytz.timezone('America/Santiago')
    return datetime.now(santiago_tz)

def convert_to_chile_time(dt):
    if dt is None:
        return None
    santiago_tz = pytz.timezone('America/Santiago')
    # Si el datetime no tiene zona horaria, asumimos que está en hora de Chile
    if dt.tzinfo is None:
        return santiago_tz.localize(dt)
    return dt.astimezone(santiago_tz)

def datetime_to_js_timestamp(dt):
    """Convierte un datetime a timestamp compatible con JavaScript"""
    if dt is None:
        return None
    # Asegurar que esté en hora de Chile
    chile_time = convert_to_chile_time(dt)
    # Retornar timestamp en milisegundos para JavaScript
    return int(chile_time.timestamp() * 1000)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'clave_super_secreta_123'
db.init_app(app)
migrate = Migrate(app, db)

# Registrar función para usar en templates
app.jinja_env.globals['datetime_to_js_timestamp'] = datetime_to_js_timestamp

socketio = SocketIO(app)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'trabajador_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
    # Verificar si ya existe un cliente_id en la sesión
    if 'cliente_id' in session:
        # Obtener el cliente existente
        cliente_existente = Cliente.query.get(session['cliente_id'])
        if cliente_existente:
            return render_template('client.html', numero=cliente_existente.id, nombre=cliente_existente.nombre)
    
    # Si no hay sesión o el cliente no existe, crear uno nuevo
    nombre = request.args.get('nombre')
    cantidad_comensales = request.args.get('cantidad_comensales')
    
    # Solo crear nuevo cliente si venimos del formulario
    if nombre and cantidad_comensales:
        nuevo = Cliente(
            joined_at=get_chile_time(),
            nombre=nombre,
            cantidad_comensales=cantidad_comensales
        )
        db.session.add(nuevo)
        db.session.commit()
        # Guardar el ID del cliente en la sesión
        session['cliente_id'] = nuevo.id
        
        socketio.emit('actualizar_cola')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        return render_template('client.html', numero=nuevo.id, nombre=nombre)
    
    # Si no hay datos del formulario y no hay sesión, redirigir al landing
    return redirect(url_for('qr_landing'))

@app.route('/trabajador',methods=['GET',"POST"])
@login_required
def trabajador():
    current_time = get_chile_time()
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
        if mesa.start_time:
            start_time_chile = convert_to_chile_time(mesa.start_time)
            current_time_chile = get_chile_time()
            tiempo_usado = (current_time_chile - start_time_chile).total_seconds()
        else:
            tiempo_usado = 0
        uso = UsoMesa(mesa_id=mesa.id, duracion=tiempo_usado)
        db.session.add(uso)
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.cliente_id = None
        mesa.llego_comensal = False
        db.session.commit()

        siguiente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
        
        if siguiente and not mesa.reservada:
            # Verificar si la mesa tiene capacidad suficiente
            if mesa.capacidad >= siguiente.cantidad_comensales:
                # Asignación automática: la mesa tiene capacidad suficiente
                siguiente.assigned_table = mesa.id
                mesa.is_occupied = True
                mesa.start_time = get_chile_time()
                mesa.cliente_id = siguiente.id
                mesa.llego_comensal = False
                db.session.commit()
                # Limpiar la sesión si este era el cliente en sesión
                if 'cliente_id' in session and session['cliente_id'] == siguiente.id:
                    session.pop('cliente_id', None)
                if siguiente.sid:
                    socketio.emit("es_tu_turno", {
                        "mesa": mesa.id
                    }, to=siguiente.sid)
            else:
                # La mesa no tiene capacidad suficiente, reservarla y buscar más mesas
                mesa.reservada = True
                db.session.commit()
                
                # Verificar si tenemos suficientes mesas disponibles para el grupo
                mesas_disponibles = Mesa.query.filter_by(is_occupied=False, reservada=False).all()
                capacidad_total = sum(m.capacidad for m in mesas_disponibles) + mesa.capacidad
                
                if capacidad_total >= siguiente.cantidad_comensales:
                    # Reservar mesas adicionales si es necesario
                    capacidad_acumulada = mesa.capacidad
                    mesas_a_reservar = [mesa]
                    
                    for mesa_adicional in mesas_disponibles:
                        if capacidad_acumulada >= siguiente.cantidad_comensales:
                            break
                        mesa_adicional.reservada = True
                        mesas_a_reservar.append(mesa_adicional)
                        capacidad_acumulada += mesa_adicional.capacidad
                    
                    db.session.commit()
                    
                    # Emitir evento especial para notificar al trabajador
                    socketio.emit('cliente_necesita_multiples_mesas', {
                        'cliente_id': siguiente.id,
                        'cliente_nombre': siguiente.nombre,
                        'cantidad_comensales': siguiente.cantidad_comensales,
                        'mesas_reservadas': [m.id for m in mesas_a_reservar]
                    })
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        return jsonify({"success": True})
    socketio.emit('actualizar_mesas')
    socketio.emit('actualizar_lista_clientes')
    enviar_estado_cola()
    return jsonify({"success": False})

@app.route('/asignar_cliente_a_mesas', methods=['POST'])
@login_required
def asignar_cliente_a_mesas():
    """Asigna un cliente específico a mesas seleccionadas manualmente"""
    try:
        data = request.get_json()
        cliente_id = data.get('cliente_id')
        mesas_ids = data.get('mesas_ids', [])
        
        if not cliente_id or not mesas_ids:
            return jsonify({"success": False, "error": "Datos incompletos"})
        
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente or cliente.assigned_table is not None:
            return jsonify({"success": False, "error": "Cliente no encontrado o ya asignado"})
        
        # Verificar que todas las mesas estén disponibles
        mesas = Mesa.query.filter(Mesa.id.in_(mesas_ids)).all()
        if len(mesas) != len(mesas_ids):
            return jsonify({"success": False, "error": "Algunas mesas no fueron encontradas"})
        
        for mesa in mesas:
            if mesa.is_occupied:
                return jsonify({"success": False, "error": f"Mesa {mesa.id} ya está ocupada"})
        
        # Verificar capacidad total
        capacidad_total = sum(m.capacidad for m in mesas)
        if capacidad_total < cliente.cantidad_comensales:
            return jsonify({
                "success": False, 
                "error": f"Capacidad insuficiente. Necesitas {cliente.cantidad_comensales} personas, tienes {capacidad_total}"
            })
        
        # Asignar el cliente a las mesas
        mesa_principal = mesas[0]
        mesa_principal.is_occupied = True
        mesa_principal.reservada = False
        mesa_principal.start_time = get_chile_time()
        mesa_principal.cliente_id = cliente.id
        mesa_principal.llego_comensal = False
        
        # Quitar al cliente de la cola
        cliente.assigned_table = mesa_principal.id
        
        # Marcar las mesas adicionales como ocupadas (parte del mismo grupo)
        for mesa in mesas[1:]:
            mesa.is_occupied = True
            mesa.reservada = False
            mesa.start_time = get_chile_time()
            mesa.cliente_id = cliente.id  # Mismo cliente en todas las mesas del grupo
            mesa.llego_comensal = False
        
        db.session.commit()
        
        # Limpiar la sesión si este era el cliente en sesión
        if 'cliente_id' in session and session['cliente_id'] == cliente.id:
            session.pop('cliente_id', None)
        
        # Notificar al cliente
        if cliente.sid:
            mesas_asignadas = [m.id for m in mesas]
            socketio.emit("es_tu_turno", {
                "mesa": mesa_principal.id,
                "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else []
            }, to=cliente.sid)
        
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        
        return jsonify({
            "success": True, 
            "mesa_principal": mesa_principal.id,
            "mesas_totales": [m.id for m in mesas],
            "cliente_nombre": cliente.nombre
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})

@app.route('/cambiar_capacidad/<int:mesa_id>', methods=['POST'])
@login_required
def cambiar_capacidad(mesa_id):
    """Cambia la capacidad de una mesa"""
    try:
        data = request.get_json()
        nueva_capacidad = int(data.get('capacidad', 4))
        
        if nueva_capacidad < 1 or nueva_capacidad > 20:
            return jsonify({"success": False, "error": "La capacidad debe estar entre 1 y 20 personas"})
        
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa:
            return jsonify({"success": False, "error": "Mesa no encontrada"})
        
        if mesa.is_occupied:
            return jsonify({"success": False, "error": "No se puede cambiar la capacidad de una mesa ocupada"})
        
        mesa.capacidad = nueva_capacidad
        db.session.commit()
        
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True, "nueva_capacidad": nueva_capacidad})
        
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Capacidad inválida"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/asignar_cliente_multiple/<int:cliente_id>', methods=['POST'])
@login_required
def asignar_cliente_multiple(cliente_id):
    """Asigna un cliente a múltiples mesas reservadas"""
    cliente = db.session.get(Cliente, cliente_id)
    if not cliente or cliente.assigned_table is not None:
        return jsonify({"success": False, "error": "Cliente no encontrado o ya asignado"})
    
    # Buscar mesas reservadas para este cliente (basado en capacidad necesaria)
    mesas_reservadas = Mesa.query.filter_by(reservada=True, is_occupied=False).all()
    
    if not mesas_reservadas:
        return jsonify({"success": False, "error": "No hay mesas reservadas disponibles"})
    
    # Verificar si las mesas reservadas tienen capacidad suficiente
    capacidad_total = sum(m.capacidad for m in mesas_reservadas)
    
    if capacidad_total < cliente.cantidad_comensales:
        return jsonify({"success": False, "error": "Las mesas reservadas no tienen capacidad suficiente"})
    
    # Asignar el cliente a la primera mesa y marcar las demás como ocupadas también
    mesa_principal = mesas_reservadas[0]
    mesa_principal.is_occupied = True
    mesa_principal.reservada = False
    mesa_principal.start_time = get_chile_time()
    mesa_principal.cliente_id = cliente.id
    mesa_principal.llego_comensal = False
    
    # Quitar al cliente de la cola
    cliente.assigned_table = mesa_principal.id
    
    # Marcar las mesas adicionales como ocupadas (parte del mismo grupo)
    for mesa in mesas_reservadas[1:]:
        mesa.is_occupied = True
        mesa.reservada = False
        mesa.start_time = get_chile_time()
        mesa.cliente_id = cliente.id  # Mismo cliente en todas las mesas del grupo
        mesa.llego_comensal = False
    
    db.session.commit()
    
    # Limpiar la sesión si este era el cliente en sesión
    if 'cliente_id' in session and session['cliente_id'] == cliente.id:
        session.pop('cliente_id', None)
    
    # Notificar al cliente
    if cliente.sid:
        mesas_asignadas = [m.id for m in mesas_reservadas]
        socketio.emit("es_tu_turno", {
            "mesa": mesa_principal.id,
            "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else []
        }, to=cliente.sid)
    
    socketio.emit('actualizar_mesas')
    socketio.emit('actualizar_lista_clientes')
    enviar_estado_cola()
    
    return jsonify({
        "success": True, 
        "mesa_principal": mesa_principal.id,
        "mesas_totales": [m.id for m in mesas_reservadas]
    })

@app.route('/ocupar_mesa/<int:mesa_id>', methods=['POST'])
def ocupar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and not mesa.is_occupied:
        mesa.is_occupied = True
        mesa.start_time = get_chile_time()
        mesa.cliente_id = None
        mesa.llego_comensal = False
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/reservar_mesa/<int:mesa_id>', methods=['POST'])
def reservar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and not mesa.reservada:
        mesa.reservada = True
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/cancelar_reserva/<int:mesa_id>', methods=['POST'])
def cancelar_reserva(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    siguiente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
    if mesa and mesa.reservada:
        mesa.reservada = False
        db.session.commit()
        if siguiente:
            siguiente.assigned_table = mesa.id
            mesa.is_occupied = True
            mesa.start_time = get_chile_time()
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
        try:
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
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar usuario: {str(e)}')
            return redirect(url_for('registro'))

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
    # Limpiar la sesión del cliente anterior si existe
    if 'cliente_id' in session:
        session.pop('cliente_id', None)
    
    if request.method == 'POST':
        # Manejar datos JSON enviados desde la nueva interfaz
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        nombre = data.get('nombre', '').strip()
        cantidad_comensales = data.get('cantidad_comensales')
        
        # Validaciones
        if not nombre:
            return jsonify({'error': 'El nombre es requerido'}), 400
        
        if not cantidad_comensales or int(cantidad_comensales) < 1:
            return jsonify({'error': 'La cantidad de comensales debe ser válida'}), 400
        
        # Convertir a entero para consistencia
        try:
            cantidad_comensales = int(cantidad_comensales)
        except (ValueError, TypeError):
            return jsonify({'error': 'La cantidad de comensales debe ser un número'}), 400
        
        # Retornar la URL de redirección en lugar de hacer redirect directo
        redirect_url = url_for('cliente', nombre=nombre, cantidad_comensales=cantidad_comensales)
        return jsonify({'redirect_url': redirect_url})
    
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
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
