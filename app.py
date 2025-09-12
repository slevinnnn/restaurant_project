import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from functools import wraps
from models import UsoMesa, db, Cliente, Mesa
from datetime import datetime, timedelta
import pytz
import statistics
from flask_migrate import Migrate
from flask import render_template, request, redirect, url_for, session, flash
from models import Trabajador
import secrets
# from flask_wtf.csrf import CSRFProtect

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

def buscar_siguiente_cliente_en_orden():
    """Busca al PRIMER cliente en la fila (sin saltar a nadie por capacidad)"""
    try:
        # Siempre tomar el primer cliente en orden de llegada
        primer_cliente = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()
        return primer_cliente
        
    except Exception as e:
        print(f"Error buscando primer cliente: {e}")
        return None

def puede_asignar_cliente_a_mesa(cliente, mesa):
    """Verifica si un cliente específico puede ser asignado a una mesa específica"""
    if not cliente or not mesa or not cliente.cantidad_comensales:
        return False
    return cliente.cantidad_comensales <= mesa.capacidad

def worker_required(f):
    """Decorador para proteger endpoints que requieren sesión de trabajador"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'trabajador_id' not in session:
            return jsonify({"success": False, "error": "No autorizado - se requiere sesión de trabajador"}), 401
        
        # Renovar sesión en cada request autenticado
        session.permanent = True
        
        return f(*args, **kwargs)
    return decorated_function

# Rate limiting básico para login (diccionario simple para desarrollo)
login_attempts = {}

def check_rate_limit(ip_address, max_attempts=5, window_minutes=15):
    """Rate limiting básico para prevenir ataques de fuerza bruta"""
    now = get_chile_time()
    window_start = now - timedelta(minutes=window_minutes)
    
    # Limpiar intentos antiguos
    if ip_address in login_attempts:
        login_attempts[ip_address] = [
            attempt for attempt in login_attempts[ip_address] 
            if attempt > window_start
        ]
    else:
        login_attempts[ip_address] = []
    
    # Verificar si se excedió el límite
    if len(login_attempts[ip_address]) >= max_attempts:
        return False
    
    return True

def record_login_attempt(ip_address):
    """Registrar un intento de login"""
    if ip_address not in login_attempts:
        login_attempts[ip_address] = []
    login_attempts[ip_address].append(get_chile_time())

def calcular_tiempo_espera_promedio():
    """Calcula el tiempo de espera promedio basado en los últimos 6 clientes atendidos"""
    try:
        # Obtener los últimos 6 clientes que fueron atendidos (tienen atendido_at)
        clientes_recientes = Cliente.query.filter(
            Cliente.atendido_at.isnot(None)
        ).order_by(Cliente.atendido_at.desc()).limit(6).all()
        
        if len(clientes_recientes) < 3:  # Necesitamos al menos 3 clientes para un promedio confiable
            return 15 * 60  # Retornar 15 minutos por defecto en segundos
        
        tiempos_espera = []
        for cliente in clientes_recientes:
            if cliente.joined_at and cliente.atendido_at:
                tiempo_espera = (cliente.atendido_at - cliente.joined_at).total_seconds()
                tiempos_espera.append(tiempo_espera)
        
        if tiempos_espera:
            promedio = sum(tiempos_espera) / len(tiempos_espera)
            # Limitar el tiempo máximo a 60 minutos y mínimo a 2 minutos
            return max(120, min(3600, promedio))  # Entre 2 y 60 minutos
        else:
            return 15 * 60  # 15 minutos por defecto
            
    except Exception as e:
        print(f"Error calculando tiempo de espera promedio: {e}")
        return 15 * 60  # 15 minutos por defecto

def datetime_to_js_timestamp(dt):
    """Convierte un datetime a timestamp compatible con JavaScript"""
    if dt is None:
        return None
    # Asegurar que esté en hora de Chile
    chile_time = convert_to_chile_time(dt)
    # Retornar timestamp en milisegundos para JavaScript
    return int(chile_time.timestamp() * 1000)

app = Flask(__name__)

# Configuración de base de datos
if os.environ.get('DATABASE_URL'):
    # Usar PostgreSQL en producción (Render)
    database_url = os.environ.get('DATABASE_URL')
    # Render proporciona postgres:// pero SQLAlchemy requiere postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    # Configurar zona horaria para PostgreSQL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'options': '-c timezone=America/Santiago'
        }
    }
else:
    # Usar SQLite en desarrollo local
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración de seguridad mejorada
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
else:
    app.config['SECRET_KEY'] = secrets.token_hex(32)  # Generar clave aleatoria para desarrollo

# Configuración de cookies seguras
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)  # Expiración de 8 horas

# Inicializar protección CSRF (deshabilitado temporalmente para desarrollo)
# csrf = CSRFProtect(app)

# Excluir endpoints de API de CSRF (para compatibilidad con JSON)
# csrf.exempt('/tiempo_espera_promedio')
# csrf.exempt('/clientes')
# Excluir endpoints públicos de autenticación
# csrf.exempt('/login')
# csrf.exempt('/registro')

db.init_app(app)
migrate = Migrate(app, db)

def run_migrations():
    """Ejecutar migraciones automáticamente en producción"""
    try:
        if os.environ.get('DATABASE_URL'):  # Solo en producción (Render)
            from flask_migrate import upgrade
            with app.app_context():
                upgrade()
                print("✅ Migraciones aplicadas exitosamente")
    except Exception as e:
        print(f"⚠️ Error aplicando migraciones: {e}")

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
    """Inicializar tablas y datos básicos de la aplicación"""
    try:
        # Solo crear tablas si no existen (para compatibility con migraciones)
        db.create_all()
        
        mesas_existentes = db.session.query(db.func.count(Mesa.id)).scalar() or 0
        mesas_deseadas = 26
        
        if mesas_existentes < mesas_deseadas:
            for i in range(mesas_existentes, mesas_deseadas):
                nueva_mesa = Mesa(capacidad=4)  # Capacidad por defecto
                db.session.add(nueva_mesa)
            db.session.commit()
            print(f"Inicializadas {mesas_deseadas - mesas_existentes} mesas nuevas")
        else:
            print(f"Ya existen {mesas_existentes} mesas en la base de datos")
            
    except Exception as e:
        print(f"Error inicializando tablas: {e}")
        db.session.rollback()

# Solo inicializar si se ejecuta directamente, no en producción
def init_app_data():
    """Inicializar datos de la aplicación si es necesario"""
    with app.app_context():  # Agregar contexto de aplicación
        # Siempre inicializar tablas básicas, tanto en desarrollo como producción
        initialize_tables()

# En producción, inicializar solo si es necesario
try:
    with app.app_context():
        # Verificar si las tablas existen
        Mesa.query.first()
except Exception:
    # Las tablas no existen, inicializar
    with app.app_context():
        initialize_tables()

@app.route('/cliente')
def cliente(nombre=None, cantidad_comensales=None, telefono=None):
    # Verificar si ya existe un cliente_id en la sesión
    if 'cliente_id' in session:
        # Obtener el cliente existente
        cliente_existente = Cliente.query.get(session['cliente_id'])
        if cliente_existente:
            return render_template(
                'client.html',
                numero=cliente_existente.id,
                nombre=cliente_existente.nombre,
                mesa_asignada_at=cliente_existente.mesa_asignada_at.isoformat() if cliente_existente.mesa_asignada_at else None,
                mesa_asignada=cliente_existente.assigned_table
            )
    
    # Si no hay sesión o el cliente no existe, crear uno nuevo
    nombre = request.args.get('nombre')
    cantidad_comensales = request.args.get('cantidad_comensales')
    telefono = request.args.get('telefono')
    
    # Solo crear nuevo cliente si venimos del formulario
    if nombre and cantidad_comensales and telefono:
        # 1) Intentar reutilizar un cliente ya ASIGNADO recientemente para este nombre
        try:
            candidato = Cliente.query.filter_by(nombre=nombre).order_by(Cliente.id.desc()).first()
            if candidato and candidato.mesa_asignada_at:
                # Si fue asignado en los últimos 15 minutos, reutilizarlo
                try:
                    ahora_cl = get_chile_time()
                    asignado_cl = convert_to_chile_time(candidato.mesa_asignada_at)
                    if (ahora_cl - asignado_cl) <= timedelta(minutes=15):
                        session['cliente_id'] = candidato.id
                        # Importante: limpiar la URL para evitar recreaciones al refrescar
                        return redirect(url_for('cliente'))
                except Exception:
                    # Si hay cualquier problema de timezone/None, ignorar y seguir flujo normal
                    pass
        except Exception as e:
            print(f"Advertencia al intentar reutilizar cliente existente: {e}")

        # 2) Crear un nuevo cliente (y luego redirigir a URL limpia sin querystring)
        nuevo = Cliente(
            joined_at=get_chile_time(),
            nombre=nombre,
            telefono=telefono,
            cantidad_comensales=int(cantidad_comensales) if str(cantidad_comensales).isdigit() else cantidad_comensales
        )
        db.session.add(nuevo)
        db.session.commit()
        # Guardar el ID del cliente en la sesión
        session['cliente_id'] = nuevo.id
        
        socketio.emit('actualizar_cola')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        # Redirigir a URL limpia para evitar re-creación al refrescar
        return redirect(url_for('cliente'))
    
    # Si no hay datos del formulario y no hay sesión, redirigir al landing
    return redirect(url_for('qr_landing'))

@app.route('/trabajador',methods=['GET',"POST"])
@login_required
def trabajador():
    current_time = get_chile_time()
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    mesas = Mesa.query.order_by(Mesa.id).all()  # Ordenar por ID para mantener orden consistente
    
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
@worker_required
def liberar_mesa(mesa_id):
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa or not mesa.is_occupied:
            return jsonify({"success": False, "error": "Mesa no encontrada o no está ocupada"})
        
        # Obtener el cliente_id antes de limpiar la mesa
        cliente_id = mesa.cliente_id

        # IMPORTANTE: Si la mesa fue ocupada manualmente, cliente_id será None.
        # En ese caso, NO debemos liberar todas las mesas con cliente_id NULL, solo esta mesa.
        if cliente_id is None:
            mesas_del_cliente = [mesa]
            print(f"Liberando SOLO la mesa {mesa_id} (ocupación manual, cliente_id=None)")
        else:
            # Buscar TODAS las mesas asignadas al mismo cliente (grupo)
            mesas_del_cliente = Mesa.query.filter_by(cliente_id=cliente_id, is_occupied=True).all()
            print(f"Liberando mesa {mesa_id} del cliente {cliente_id}. Total mesas del cliente: {len(mesas_del_cliente)}")
        
        # Liberar TODAS las mesas del cliente
        for mesa_cliente in mesas_del_cliente:
            # Calcular tiempo usado para cada mesa
            if mesa_cliente.start_time:
                start_time_chile = convert_to_chile_time(mesa_cliente.start_time)
                current_time_chile = get_chile_time()
                tiempo_usado = (current_time_chile - start_time_chile).total_seconds()
            else:
                tiempo_usado = 0
            
            # Crear registro de uso para cada mesa
            uso = UsoMesa(mesa_id=mesa_cliente.id, duracion=tiempo_usado)
            db.session.add(uso)
            
            # Limpiar cada mesa
            mesa_cliente.is_occupied = False
            mesa_cliente.start_time = None
            mesa_cliente.cliente_id = None
            mesa_cliente.llego_comensal = False
            mesa_cliente.orden = None
            
            print(f"Mesa {mesa_cliente.id} liberada automáticamente")
        
        # Ahora procesar asignaciones automáticas para cada mesa liberada
        mesas_asignadas = []
        for mesa_liberada in mesas_del_cliente:
            # Solo procesar si la mesa no está reservada
            if not mesa_liberada.reservada:
                siguiente = buscar_siguiente_cliente_en_orden()
                
                # Verificar si el primer cliente PUEDE ser asignado a esta mesa
                if siguiente and puede_asignar_cliente_a_mesa(siguiente, mesa_liberada):
                    # El primer cliente SÍ cabe en la mesa - asignar automáticamente
                    siguiente.assigned_table = mesa_liberada.id
                    siguiente.atendido_at = get_chile_time()
                    siguiente.mesa_asignada_at = get_chile_time()  # Timestamp para cronómetro
                    mesa_liberada.is_occupied = True
                    mesa_liberada.start_time = get_chile_time()
                    mesa_liberada.cliente_id = siguiente.id
                    mesa_liberada.llego_comensal = False
                    
                # Mantener la sesión del cliente; no limpiar para soportar recargas sin duplicados
                    
                    mesas_asignadas.append((mesa_liberada.id, siguiente))
                    print(f"Mesa {mesa_liberada.id} (capacidad {mesa_liberada.capacidad}) reasignada automáticamente a primer cliente {siguiente.id} ({siguiente.cantidad_comensales} comensales)")
                elif siguiente:
                    # El primer cliente NO cabe - reservar mesa para asignación manual
                    mesa_liberada.reservada = True
                    print(f"Mesa {mesa_liberada.id} (capacidad {mesa_liberada.capacidad}) - primer cliente {siguiente.id} ({siguiente.cantidad_comensales} comensales) no cabe. Mesa queda RESERVADA para asignación manual")
                else:
                    # No hay clientes en espera
                    print(f"Mesa {mesa_liberada.id} (capacidad {mesa_liberada.capacidad}) - no hay clientes en espera. Mesa queda disponible")
        
        # Hacer commit una sola vez al final
        db.session.commit()
        
        # Notificar clientes asignados después del commit exitoso
        for mesa_id_asignada, cliente_asignado in mesas_asignadas:
            if cliente_asignado.sid:
                socketio.emit("es_tu_turno", {
                    "mesa": mesa_id_asignada,
                    "asignada_at": cliente_asignado.mesa_asignada_at.isoformat() if cliente_asignado.mesa_asignada_at else None
                }, to=cliente_asignado.sid)
        
        # Emitir actualizaciones
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        
        return jsonify({
            "success": True, 
            "mesas_liberadas": [m.id for m in mesas_del_cliente],
            "mensaje": f"Se liberaron {len(mesas_del_cliente)} mesa(s) del cliente {cliente_id}"
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error en liberar_mesa: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})

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
        
        # Quitar al cliente de la cola y registrar cuándo fue atendido
        cliente.assigned_table = mesa_principal.id
        cliente.atendido_at = get_chile_time()
        cliente.mesa_asignada_at = get_chile_time()  # Timestamp para cronómetro
        
        # Marcar las mesas adicionales como ocupadas (parte del mismo grupo)
        for mesa in mesas[1:]:
            mesa.is_occupied = True
            mesa.reservada = False
            mesa.start_time = get_chile_time()
            mesa.cliente_id = cliente.id  # Mismo cliente en todas las mesas del grupo
            mesa.llego_comensal = False
        
        db.session.commit()
        
    # Mantener la sesión del cliente; no limpiar para soportar recargas sin duplicados
        
        # Notificar al cliente
        if cliente.sid:
            mesas_asignadas = [m.id for m in mesas]
            socketio.emit("es_tu_turno", {
                "mesa": mesa_principal.id,
                "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else [],
                "asignada_at": cliente.mesa_asignada_at.isoformat() if cliente.mesa_asignada_at else None
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
    try:
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
        
        # Quitar al cliente de la cola y registrar cuándo fue atendido
        cliente.assigned_table = mesa_principal.id
        cliente.atendido_at = get_chile_time()
        cliente.mesa_asignada_at = get_chile_time()  # Timestamp para cronómetro
        
        # Marcar las mesas adicionales como ocupadas (parte del mismo grupo)
        for mesa in mesas_reservadas[1:]:
            mesa.is_occupied = True
            mesa.reservada = False
            mesa.start_time = get_chile_time()
            mesa.cliente_id = cliente.id  # Mismo cliente en todas las mesas del grupo
            mesa.llego_comensal = False
        
        db.session.commit()
        
    # Mantener la sesión del cliente; no limpiar para soportar recargas sin duplicados
        
        # Notificar al cliente después del commit exitoso
        if cliente.sid:
            mesas_asignadas = [m.id for m in mesas_reservadas]
            socketio.emit("es_tu_turno", {
                "mesa": mesa_principal.id,
                "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else [],
                "asignada_at": cliente.mesa_asignada_at.isoformat() if cliente.mesa_asignada_at else None
            }, to=cliente.sid)
        
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        
        return jsonify({
            "success": True, 
            "mesa_principal": mesa_principal.id,
            "mesas_totales": [m.id for m in mesas_reservadas]
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error en asignar_cliente_multiple: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})

@app.route('/ocupar_mesa/<int:mesa_id>', methods=['POST'])
@worker_required
def ocupar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and not mesa.is_occupied:
        mesa.is_occupied = True
        mesa.start_time = get_chile_time()
        mesa.cliente_id = None
        # Mesa libre ocupada manualmente: el comensal ya está presente
        mesa.llego_comensal = True
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/ocupar_multiples_mesas', methods=['POST'])
@worker_required
def ocupar_multiples_mesas():
    """Ocupa varias mesas libres como un grupo manual (sin cliente en cola).
    Espera JSON: { "mesa_principal": int, "mesas_adicionales": [int, ...] }
    Crea un cliente 'manual' efímero para linkear las mesas bajo un mismo cliente_id,
    de modo que liberar y confirmar llegada propaguen entre las mesas del grupo.
    """
    try:
        data = request.get_json() or {}
        mesa_principal_id = data.get('mesa_principal')
        adicionales = data.get('mesas_adicionales', []) or []

        if not mesa_principal_id or not isinstance(adicionales, list):
            return jsonify({"success": False, "error": "Datos inválidos"}), 400

        # Obtener mesas y validar que estén libres
        todas_ids = [mesa_principal_id] + [mid for mid in adicionales if mid != mesa_principal_id]
        mesas = Mesa.query.filter(Mesa.id.in_(todas_ids)).with_for_update().all()
        mesa_por_id = {m.id: m for m in mesas}
        faltantes = [mid for mid in todas_ids if mid not in mesa_por_id]
        if faltantes:
            return jsonify({"success": False, "error": f"Mesas inexistentes: {faltantes}"}), 404

        # Validar estado libre
        no_libres = [m.id for m in mesas if m.is_occupied or m.reservada]
        if no_libres:
            return jsonify({"success": False, "error": f"Mesas no disponibles: {no_libres}"}), 409

        # Crear un 'cliente' manual para agrupar
        cliente_manual = Cliente(
            nombre='Manual',
            telefono='manual',
            cantidad_comensales=sum(m.capacidad for m in mesas),
            joined_at=get_chile_time(),
            assigned_table=mesa_principal_id,  # marcar como ya asignado para que no aparezca en la cola
            atendido_at=get_chile_time(),
            mesa_asignada_at=get_chile_time(),
            sid=None
        )
        db.session.add(cliente_manual)
        db.session.flush()  # para obtener cliente_manual.id

        # Ocupar todas bajo el mismo cliente_id
        ahora = get_chile_time()
        for m in mesas:
            m.is_occupied = True
            m.start_time = ahora
            m.cliente_id = cliente_manual.id
            # Ocupación manual desde estado libre: ya están presentes
            m.llego_comensal = True
            m.reservada = False

        db.session.commit()

        socketio.emit('actualizar_mesas')
        return jsonify({
            "success": True,
            "mesa_principal": mesa_principal_id,
            "mesas_totales": todas_ids,
            "cliente_manual_id": cliente_manual.id
        })
    except Exception as e:
        db.session.rollback()
        print(f"Error en ocupar_multiples_mesas: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"}), 500

@app.route('/reservar_mesa/<int:mesa_id>', methods=['POST'])
@worker_required
def reservar_mesa(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa and not mesa.reservada:
        mesa.reservada = True
        db.session.commit()
        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/desocupar_y_reservar/<int:mesa_id>', methods=['POST'])
@worker_required
def desocupar_y_reservar(mesa_id):
    """Desocupa una mesa ocupada y la deja marcada como reservada para evitar auto-asignación."""
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa or not mesa.is_occupied:
            return jsonify({"success": False, "error": "Mesa no encontrada o no está ocupada"}), 400

        # Registrar uso si corresponde
        if mesa.start_time:
            start_time_chile = convert_to_chile_time(mesa.start_time)
            current_time_chile = get_chile_time()
            tiempo_usado = (current_time_chile - start_time_chile).total_seconds()
        else:
            tiempo_usado = 0
        uso = UsoMesa(mesa_id=mesa.id, duracion=tiempo_usado)
        db.session.add(uso)

        # Desocupar y reservar
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.llego_comensal = False
        mesa.orden = None
        mesa.cliente_id = None
        mesa.reservada = True

        db.session.commit()

        socketio.emit('actualizar_mesas')
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        print(f"Error en desocupar_y_reservar: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"}), 500

@app.route('/cancelar_reserva/<int:mesa_id>', methods=['POST'])
@worker_required
def cancelar_reserva(mesa_id):
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa or not mesa.reservada:
            return jsonify({"success": False, "error": "Mesa no encontrada o no está reservada"})
        
        # Cancelar la reserva
        mesa.reservada = False
        
        # Buscar el PRIMER cliente en la fila (respetando orden de llegada)
        siguiente = buscar_siguiente_cliente_en_orden()
        
        # Verificar si el primer cliente PUEDE ser asignado a esta mesa
        if siguiente and puede_asignar_cliente_a_mesa(siguiente, mesa):
            # El primer cliente SÍ cabe en esta mesa - asignar automáticamente
            siguiente.assigned_table = mesa.id
            siguiente.atendido_at = get_chile_time()
            siguiente.mesa_asignada_at = get_chile_time()  # Timestamp para cronómetro
            mesa.is_occupied = True
            mesa.start_time = get_chile_time()
            mesa.cliente_id = siguiente.id
            mesa.llego_comensal = False
            
            # Limpiar sesión si corresponde
            if 'cliente_id' in session and session['cliente_id'] == siguiente.id:
                session.pop('cliente_id', None)
            
            print(f"Mesa {mesa_id} (capacidad {mesa.capacidad}) reserva cancelada y asignada automáticamente a primer cliente {siguiente.id} ({siguiente.cantidad_comensales} comensales)")
        elif siguiente:
            # El primer cliente NO cabe - volver a reservar mesa para asignación manual
            mesa.reservada = True
            print(f"Mesa {mesa_id} (capacidad {mesa.capacidad}) reserva cancelada - primer cliente {siguiente.id} ({siguiente.cantidad_comensales} comensales) no cabe. Mesa queda RESERVADA para asignación manual")
            siguiente = None  # No notificar automáticamente
        else:
            # No hay clientes en espera - mesa queda libre
            print(f"Mesa {mesa_id} (capacidad {mesa.capacidad}) reserva cancelada - no hay clientes en espera. Mesa queda disponible")
        
        # Hacer commit una sola vez
        db.session.commit()
        
        # Notificar al cliente después del commit exitoso
        if siguiente and siguiente.sid:
            socketio.emit("es_tu_turno", {
                "mesa": mesa.id,
                "asignada_at": siguiente.mesa_asignada_at.isoformat() if siguiente.mesa_asignada_at else None
            }, to=siguiente.sid)
        
        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()
        
        return jsonify({"success": True})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error en cancelar_reserva: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})

@app.route('/desocupar_y_cancelar/<int:mesa_id>', methods=['POST'])
@worker_required
def desocupar_y_cancelar(mesa_id):
    """Desocupa una mesa que está ocupada (y posiblemente reservada) y cancela su reserva.
    Luego la deja disponible; si el primer cliente en la fila cabe, se asigna automáticamente.
    """
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa or not mesa.is_occupied:
            return jsonify({"success": False, "error": "Mesa no encontrada o no está ocupada"}), 400

        # Registrar uso si corresponde
        if mesa.start_time:
            start_time_chile = convert_to_chile_time(mesa.start_time)
            current_time_chile = get_chile_time()
            tiempo_usado = (current_time_chile - start_time_chile).total_seconds()
        else:
            tiempo_usado = 0
        db.session.add(UsoMesa(mesa_id=mesa.id, duracion=tiempo_usado))

        # Desocupar y cancelar reserva
        mesa.is_occupied = False
        mesa.start_time = None
        mesa.llego_comensal = False
        mesa.orden = None
        mesa.cliente_id = None
        mesa.reservada = False

        # Intentar asignar al primer cliente si cabe; si no cabe, se deja libre sin reservar
        siguiente = buscar_siguiente_cliente_en_orden()
        cliente_notificado = None
        if siguiente and puede_asignar_cliente_a_mesa(siguiente, mesa):
            siguiente.assigned_table = mesa.id
            siguiente.atendido_at = get_chile_time()
            siguiente.mesa_asignada_at = get_chile_time()
            mesa.is_occupied = True
            mesa.start_time = get_chile_time()
            mesa.cliente_id = siguiente.id
            mesa.llego_comensal = False
            # Limpiar sesión si corresponde
            if 'cliente_id' in session and session['cliente_id'] == siguiente.id:
                session.pop('cliente_id', None)
            cliente_notificado = siguiente

        db.session.commit()

        # Notificar al cliente asignado, si corresponde
        if cliente_notificado and cliente_notificado.sid:
            socketio.emit("es_tu_turno", {
                "mesa": mesa.id,
                "asignada_at": cliente_notificado.mesa_asignada_at.isoformat() if cliente_notificado.mesa_asignada_at else None
            }, to=cliente_notificado.sid)

        socketio.emit('actualizar_mesas')
        socketio.emit('actualizar_lista_clientes')
        enviar_estado_cola()

        return jsonify({"success": True, "mesa": mesa.id, "asignada": bool(cliente_notificado)})
    except Exception as e:
        db.session.rollback()
        print(f"Error en desocupar_y_cancelar: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"}), 500



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
    try:
        cliente_id = data.get("id")
        sid = request.sid
        
        # Validar que el cliente_id esté en la sesión para prevenir suplantación
        if 'cliente_id' not in session or session['cliente_id'] != cliente_id:
            print(f"Intento de registro no autorizado para cliente {cliente_id} desde SID {sid}")
            return False
        
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            print(f"Cliente {cliente_id} no encontrado en la base de datos")
            return False
            
        # Actualizar SID del cliente
        cliente.sid = sid
        db.session.commit()
        
        join_room(sid)
        socketio.emit('nuevo_cliente', {
            'cliente_id': cliente.id,
            'joined_at': cliente.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        })
        enviar_estado_cola()
        
    except Exception as e:
        print(f"Error en registrar_cliente: {e}")
        return False

@socketio.on("heartbeat")
def manejar_heartbeat(data):
    """Manejar heartbeat del cliente para mantener conexión activa"""
    try:
        cliente_id = data.get('cliente_id')
        
        if cliente_id:
            print(f"💓 Heartbeat de cliente {cliente_id}")
                
        return True
        
    except Exception as e:
        print(f"Error en heartbeat: {e}")
        return False

@app.route('/clientes')
@worker_required
def obtener_clientes():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    return jsonify([
        {
            'id': c.id,
            'nombre': c.nombre,
            'telefono': c.telefono,
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

@app.route('/')
def index():
    """Ruta principal - redirige al login"""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        
        # Verificar rate limiting
        if not check_rate_limit(client_ip):
            flash('Demasiados intentos de login. Intenta de nuevo en 15 minutos.')
            return redirect(url_for('login'))
        
        email = request.form['email']
        password = request.form['password']
        
        # Registrar el intento
        record_login_attempt(client_ip)
        
        trabajador = Trabajador.query.filter_by(email=email).first()

        if trabajador and trabajador.check_password(password):
            # Login exitoso - limpiar intentos de este IP
            if client_ip in login_attempts:
                del login_attempts[client_ip]
            
            session['trabajador_id'] = trabajador.id
            session.permanent = True  # Hacer la sesión permanente para usar PERMANENT_SESSION_LIFETIME
            flash('Bienvenido, ' + trabajador.username)
            return redirect(url_for('trabajador'))
        else:
            flash('Credenciales incorrectas')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    # Limpiar toda la sesión para prevenir fijación/contaminación
    session.clear()
    flash('Sesión cerrada correctamente')
    return redirect(url_for('login'))


@app.route('/clientes_espera')
def clientes_espera():
    clientes = Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).all()
    return render_template('clientes_espera.html', clientes=clientes)

@app.route('/qr_landing', methods=['GET', 'POST'])
def qr_landing():
    # No limpiar la sesión aquí para permitir recargas sin duplicar clientes
    
    if request.method == 'POST':
        # Manejar datos JSON enviados desde la nueva interfaz
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        nombre = data.get('nombre', '').strip()
        telefono = data.get('telefono', '').strip()
        cantidad_comensales = data.get('cantidad_comensales')
        
        # Validaciones
        if not nombre:
            return jsonify({'error': 'El nombre es requerido'}), 400
        
        if not telefono:
            return jsonify({'error': 'El teléfono es requerido'}), 400
        
        # Validar formato del teléfono chileno
        if not telefono.startswith('+569') or len(telefono) != 12:
            return jsonify({'error': 'El teléfono debe tener formato +569xxxxxxxx'}), 400
        
        if not cantidad_comensales or int(cantidad_comensales) < 1:
            return jsonify({'error': 'La cantidad de comensales debe ser válida'}), 400
        
        # Convertir a entero para consistencia
        try:
            cantidad_comensales = int(cantidad_comensales)
        except (ValueError, TypeError):
            return jsonify({'error': 'La cantidad de comensales debe ser un número'}), 400
        
        # Si ya hay un cliente en sesión, enviar directo a /cliente limpio
        if 'cliente_id' in session:
            redirect_url = url_for('cliente')
        else:
            # Retornar la URL de redirección con parámetros solo una vez; luego /cliente redirige a limpio
            redirect_url = url_for('cliente', nombre=nombre, telefono=telefono, cantidad_comensales=cantidad_comensales)
        return jsonify({'redirect_url': redirect_url})
    
    return render_template('qr_landing.html')

@app.route('/confirmar_llegada/<int:mesa_id>', methods=['POST'])
@worker_required
def confirmar_llegada(mesa_id):
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa:
            return jsonify({"success": False, "error": "Mesa no encontrada"})
        
        if not mesa.is_occupied:
            return jsonify({"success": False, "error": "Mesa no está ocupada"})
        
        # Confirmar llegada del comensal en TODAS las mesas de este cliente
        mesas_actualizadas = []
        if mesa.cliente_id:
            mesas_cliente = Mesa.query.filter_by(cliente_id=mesa.cliente_id, is_occupied=True).all()
            for m in mesas_cliente:
                if not m.llego_comensal:
                    m.llego_comensal = True
                    mesas_actualizadas.append(m.id)
        else:
            # Mesa ocupada manualmente sin cliente asignado: marcar solo esta mesa
            if not mesa.llego_comensal:
                mesa.llego_comensal = True
                mesas_actualizadas.append(mesa.id)
        
        # Hacer commit
        db.session.commit()
        
        # Emitir actualizaciones después del commit exitoso
        socketio.emit('actualizar_mesas')
        
        return jsonify({"success": True, "mesas_actualizadas": mesas_actualizadas})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error en confirmar_llegada: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})

@app.route('/obtener_orden/<int:mesa_id>')
@worker_required
def obtener_orden(mesa_id):
    mesa = db.session.get(Mesa, mesa_id)
    if mesa:
        return jsonify({"orden": mesa.orden or ""})
    return jsonify({"orden": ""})

@app.route('/guardar_orden/<int:mesa_id>', methods=['POST'])
@worker_required
def guardar_orden(mesa_id):
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa:
            return jsonify({"success": False, "error": "Mesa no encontrada"})
        
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Datos no válidos"})
        
        # Guardar la orden
        mesa.orden = data.get('orden', '')
        
        # Hacer commit
        db.session.commit()
        
        # Emitir actualizaciones después del commit exitoso
        socketio.emit('actualizar_mesas')
        
        return jsonify({"success": True})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error en guardar_orden: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})

@app.route('/tiempo_espera_promedio')
def tiempo_espera_promedio():
    """Endpoint para obtener el tiempo de espera promedio"""
    promedio_segundos = calcular_tiempo_espera_promedio()
    
    # Convertir a minutos para mostrar
    promedio_minutos = round(promedio_segundos / 60)
    
    return jsonify({
        "promedio_segundos": promedio_segundos,
        "promedio_minutos": promedio_minutos
    })

@app.route('/verificar_estado_cliente/<int:cliente_id>')
def verificar_estado_cliente(cliente_id):
    """Verificar si un cliente ya tiene mesa asignada"""
    try:
        cliente = db.session.get(Cliente, cliente_id)
        
        if not cliente:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        response = {
            'cliente_id': cliente_id,
            'nombre': cliente.nombre,
            'mesa_asignada': cliente.assigned_table,
            'joined_at': cliente.joined_at.isoformat() if cliente.joined_at else None,
            'mesa_asignada_at': cliente.mesa_asignada_at.isoformat() if cliente.mesa_asignada_at else None,
            'tiene_mesa': cliente.assigned_table is not None
        }
        
        return jsonify(response)
        
    except Exception as e:
        print(f"Error verificando estado del cliente {cliente_id}: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/cancelar_turno/<int:cliente_id>', methods=['POST'])
def cancelar_turno(cliente_id):
    """Permitir que un cliente cancele su lugar en la fila"""
    try:
        # Verificar que el cliente_id coincida con la sesión para prevenir cancelaciones maliciosas
        if 'cliente_id' not in session or session['cliente_id'] != cliente_id:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
        
        # Solo permitir cancelación si el cliente NO tiene mesa asignada
        if cliente.assigned_table:
            return jsonify({"success": False, "error": "No puedes cancelar cuando ya tienes mesa asignada"}), 400
        
        # Eliminar al cliente de la base de datos
        db.session.delete(cliente)
        db.session.commit()
        
        # Limpiar la sesión
        session.clear()
        
        # Notificar a todos los trabajadores que la lista de clientes cambió
        socketio.emit('actualizar_lista_clientes')
        socketio.emit('actualizar_cola')
        enviar_estado_cola()
        
        return jsonify({
            "success": True, 
            "mensaje": "Tu lugar en la fila ha sido cancelado exitosamente"
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error cancelando turno: {e}")
        return jsonify({"success": False, "error": "Error interno"}), 500

# FUNCIÓN DESHABILITADA POR SEGURIDAD - CAUSABA RESETEO ACCIDENTAL DE MESAS EN PRODUCCIÓN
# @app.route('/admin/reiniciar_bd', methods=['GET', 'POST'])
# @login_required
# def reiniciar_base_datos_admin():
    """Endpoint administrativo para reiniciar la base de datos"""
    if request.method == 'GET':
        # Mostrar página de confirmación
        es_produccion = bool(os.environ.get('DATABASE_URL'))
        tipo_bd = "PostgreSQL (Render)" if es_produccion else "SQLite (Local)"
        
        # Contar registros actuales
        clientes_count = Cliente.query.count()
        trabajadores_count = Trabajador.query.count()
        uso_mesas_count = UsoMesa.query.count()
        mesas_count = Mesa.query.count()
        
        stats = {
            'tipo_bd': tipo_bd,
            'es_produccion': es_produccion,
            'clientes': clientes_count,
            'trabajadores': trabajadores_count,
            'uso_mesas': uso_mesas_count,
            'mesas': mesas_count
        }
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Reiniciar Base de Datos</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .danger {{ background: #f8d7da; border: 1px solid #f5c6cb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                button {{ padding: 10px 20px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; }}
                .btn-danger {{ background: #dc3545; color: white; }}
                .btn-secondary {{ background: #6c757d; color: white; }}
            </style>
        </head>
        <body>
            <h1>🔄 Reiniciar Base de Datos</h1>
            
            <div class="info">
                <h3>📊 Estado Actual:</h3>
                <p><strong>Tipo de BD:</strong> {stats['tipo_bd']}</p>
                <p><strong>Clientes:</strong> {stats['clientes']}</p>
                <p><strong>Trabajadores:</strong> {stats['trabajadores']}</p>
                <p><strong>Mesas:</strong> {stats['mesas']}</p>
                <p><strong>Registros de uso:</strong> {stats['uso_mesas']}</p>
            </div>
            
            <div class="danger">
                <h3>⚠️ ADVERTENCIA</h3>
                <p>Esta acción eliminará <strong>TODOS</strong> los siguientes datos:</p>
                <ul>
                    <li>Todos los clientes en cola</li>
                    <li>Todos los trabajadores registrados</li>
                    <li>Todo el historial de uso de mesas</li>
                    <li>Reseteo del estado de todas las mesas</li>
                </ul>
                <p><strong>Las mesas se mantendrán pero quedarán libres.</strong></p>
            </div>
            
            <div class="warning">
                <h3>📝 Después del reinicio necesitarás:</h3>
                <ul>
                    <li>Registrar un nuevo trabajador en <a href="/registro">/registro</a></li>
                    <li>Configurar las capacidades de las mesas si es necesario</li>
                </ul>
            </div>
            
            <form method="POST" onsubmit="return confirm('¿Estás COMPLETAMENTE seguro de que quieres reiniciar la base de datos? Esta acción NO se puede deshacer.');">
                <button type="submit" class="btn-danger">🗑️ SÍ, REINICIAR BASE DE DATOS</button>
                <a href="/trabajador"><button type="button" class="btn-secondary">❌ Cancelar</button></a>
            </form>
        </body>
        </html>
        """
    
    elif request.method == 'POST':
        try:
            # Ejecutar el reinicio
            es_produccion = bool(os.environ.get('DATABASE_URL'))
            
            # Contar antes de eliminar
            clientes_count = Cliente.query.count()
            trabajadores_count = Trabajador.query.count()
            uso_mesas_count = UsoMesa.query.count()
            
            # 1. Eliminar todos los clientes
            Cliente.query.delete()
            
            # 2. Eliminar todos los trabajadores
            Trabajador.query.delete()
            
            # 3. Eliminar historial de uso de mesas
            UsoMesa.query.delete()
            
            # 4. Resetear estado de todas las mesas
            mesas = Mesa.query.all()
            for mesa in mesas:
                mesa.is_occupied = False
                mesa.start_time = None
                mesa.cliente_id = None
                mesa.llego_comensal = False
                mesa.reservada = False
                mesa.orden = None
            
            # 5. Confirmar cambios
            db.session.commit()
            
            # Limpiar sesión actual (el trabajador que ejecutó el reinicio ya no existe)
            session.clear()
            
            # Emitir actualizaciones
            socketio.emit('actualizar_mesas')
            socketio.emit('actualizar_lista_clientes')
            
            tipo_bd = "PostgreSQL (Render)" if es_produccion else "SQLite (Local)"
            
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Reinicio Completado</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .success {{ background: #d4edda; border: 1px solid #c3e6cb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                    .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                    button {{ padding: 10px 20px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; background: #007bff; color: white; }}
                </style>
            </head>
            <body>
                <h1>✅ Base de Datos Reiniciada</h1>
                
                <div class="success">
                    <h3>🎉 Reinicio completado exitosamente</h3>
                    <p><strong>Base de datos:</strong> {tipo_bd}</p>
                    <p><strong>Eliminados:</strong></p>
                    <ul>
                        <li>{clientes_count} clientes</li>
                        <li>{trabajadores_count} trabajadores</li>
                        <li>{uso_mesas_count} registros de uso</li>
                    </ul>
                    <p><strong>Reseteadas:</strong> {len(mesas)} mesas</p>
                </div>
                
                <div class="info">
                    <h3>📝 Próximos pasos:</h3>
                    <ol>
                        <li>Registrar un nuevo trabajador</li>
                        <li>Configurar capacidades de mesas si es necesario</li>
                        <li>¡Listo para usar!</li>
                    </ol>
                </div>
                
                <a href="/registro"><button>👥 Registrar Trabajador</button></a>
                <a href="/"><button>🏠 Ir al Inicio</button></a>
            </body>
            </html>
            """
            
        except Exception as e:
            db.session.rollback()
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Error en Reinicio</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .danger {{ background: #f8d7da; border: 1px solid #f5c6cb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <h1>❌ Error en el Reinicio</h1>
                <div class="danger">
                    <p><strong>Error:</strong> {str(e)}</p>
                    <p>Intenta nuevamente o contacta al administrador.</p>
                </div>
                <a href="/admin/reiniciar_bd"><button>🔄 Intentar de nuevo</button></a>
            </body>
            </html>
            """

if __name__ == "__main__":
    # Ejecutar migraciones automáticamente en producción
    run_migrations()
    
    # Inicializar datos de la aplicación
    init_app_data()
    # Configuración para desarrollo vs producción
    if os.environ.get('FLASK_ENV') == 'production':
        # Configuración para Render (producción)
        port = int(os.environ.get('PORT', 5000))
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        # Configuración para desarrollo local
        socketio.run(app, debug=True)
