import os
import json
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from functools import wraps
from models import UsoMesa, db, Cliente, Mesa, PushSubscription
from datetime import datetime, timedelta
import pytz
import statistics
from flask_migrate import Migrate
from flask import render_template, request, redirect, url_for, session, flash
from models import Trabajador
import secrets
# from flask_wtf.csrf import CSRFProtect

# 🔔 Imports para notificaciones push
from pywebpush import webpush, WebPushException
import base64

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
    """Calcula el TIEMPO MÍNIMO de espera entre los últimos 6 clientes atendidos.
    Mantiene el mismo contrato del endpoint (segundos), pero ahora retorna el mínimo.
    Si hay menos de 3 clientes con datos, retorna 15 minutos por defecto.
    Aplica límites de 2 a 60 minutos para evitar valores extremos.
    """
    try:
        clientes_recientes = (
            Cliente.query
            .filter(Cliente.atendido_at.isnot(None))
            .order_by(Cliente.atendido_at.desc())
            .limit(6)
            .all()
        )

        if len(clientes_recientes) < 3:
            return 15 * 60

        tiempos_espera = []
        for cliente in clientes_recientes:
            if cliente.joined_at and cliente.atendido_at:
                try:
                    inicio = convert_to_chile_time(cliente.joined_at)
                    fin = convert_to_chile_time(cliente.atendido_at)
                    diff = (fin - inicio).total_seconds()
                    if diff >= 0:
                        tiempos_espera.append(diff)
                except Exception:
                    continue

        if not tiempos_espera:
            return 15 * 60

        minimo = min(tiempos_espera)
        return max(120, min(3600, minimo))

    except Exception as e:
        print(f"Error calculando tiempo de espera (mínimo): {e}")
        return 15 * 60

def datetime_to_js_timestamp(dt):
    """Convierte un datetime a timestamp compatible con JavaScript"""
    if dt is None:
        return None
    # Asegurar que esté en hora de Chile
    chile_time = convert_to_chile_time(dt)
    # Retornar timestamp en milisegundos para JavaScript
    return int(chile_time.timestamp() * 1000)

def formatear_orden_previa(orden_json_str):
    """Convierte una orden_previa (JSON en texto) a un texto legible para Mesa.orden.
    Soporta lista de personas o dict con clave 'personas'.
    """
    if not orden_json_str:
        return None
    try:
        data = json.loads(orden_json_str)
        personas = []
        if isinstance(data, dict) and isinstance(data.get('personas'), list):
            personas = data['personas']
        elif isinstance(data, list):
            personas = data
        else:
            return orden_json_str
        lineas = []
        for idx, p in enumerate(personas, start=1):
            if not isinstance(p, dict):
                continue
            comida = p.get('comida') or p.get('plato') or ''
            bebida = p.get('bebida') or p.get('trago') or ''
            notas = p.get('notas') or p.get('comentarios') or ''
            partes = []
            if comida:
                partes.append(f"Comida: {comida}")
            if bebida:
                partes.append(f"Bebida: {bebida}")
            if notas:
                partes.append(f"Notas: {notas}")
            contenido = ' | '.join(partes) if partes else '(sin detalles)'
            lineas.append(f"Persona {idx}: {contenido}")
        if not lineas:
            return orden_json_str
        return "Orden previa ingresada por el cliente:\n" + "\n".join(lineas)
    except Exception:
        return orden_json_str

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

# 🔔 CONFIGURACIÓN NOTIFICACIONES PUSH
# Claves VAPID para Web Push Protocol
VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgm8TC3OWohRPCqBJr
75mmluQkPHNSO24p9bYURuriQcKhRANCAASrtA4Ntd1HqfgA5Aqn9poeWZeIyVUL
2CkkJInpZYKWUSVJmmNYX0nhKUfpkccfvNQy+Nf/jAQ3O4py7Vu7Ie0l
-----END PRIVATE KEY-----"""

VAPID_PUBLIC_KEY = "BKu0Dg213Uep-ADkCqf2mh5Zl4jJVQvYKSQkiellgpZRJUmaY1hfSeEpR-mRxx-81DL41_-MBDc7inLtW7sh7SU"
VAPID_EMAIL = "mailto:admin@restaurante-alleria.com"

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
            print("🔄 Verificando estado de la base de datos en producción...")
            
            with app.app_context():
                try:
                    # Verificar si las tablas principales existen
                    from models import Cliente, Mesa, PushSubscription
                    
                    # Intentar consultar cada tabla para verificar que existe
                    Cliente.query.limit(1).all()
                    Mesa.query.limit(1).all() 
                    PushSubscription.query.limit(1).all()
                    
                    print("✅ Todas las tablas necesarias ya existen en la base de datos")
                    print("✅ Tabla PushSubscription encontrada - notificaciones push habilitadas")
                    
                except Exception as table_error:
                    print(f"⚠️ Algunas tablas no existen o tienen problemas: {table_error}")
                    
                    # Intentar crear solo las tablas faltantes
                    try:
                        print("📦 Intentando crear tablas faltantes...")
                        db.create_all()  # Esto solo crea tablas que no existen
                        print("✅ Tablas faltantes creadas exitosamente")
                    except Exception as create_error:
                        print(f"⚠️ Error creando tablas: {create_error}")
                        
                        # Como último recurso, intentar migraciones tradicionales
                        try:
                            from flask_migrate import upgrade
                            upgrade()
                            print("✅ Migraciones aplicadas como fallback")
                        except Exception as migration_error:
                            if "already exists" in str(migration_error):
                                print("✅ Las tablas ya existen (ignorando error de duplicado)")
                            else:
                                print(f"❌ Error final en migraciones: {migration_error}")
                        
    except Exception as e:
        print(f"⚠️ Error general en verificación de base de datos: {e}")
        print("🔄 Continuando con inicialización de la aplicación...")

# Registrar función para usar en templates
app.jinja_env.globals['datetime_to_js_timestamp'] = datetime_to_js_timestamp

# 🔥 CONFIGURACIÓN ROBUSTA DE SOCKET.IO PARA PRODUCCIÓN
socketio = SocketIO(
    app,
    # 🔄 Configuración de reconexiones
    ping_timeout=60,      # Tiempo límite para responder ping (60s)
    ping_interval=25,     # Intervalo entre pings (25s)
    
    # 🌐 Configuración de transporte mejorada
    transports=['websocket', 'polling'],  # Permitir WebSocket y polling
    
    # ⚙️ Configuraciones de estabilidad
    async_mode='threading',    # Modo de async
    logger=False,             # Reducir logs para producción
    engineio_logger=False,    # Reducir logs de Engine.IO
    
    # 📊 Configuraciones de escalabilidad
    max_http_buffer_size=1000000,  # Buffer HTTP máximo
    
    # 🔒 Seguridad
    cors_allowed_origins="*",  # Ajustar según necesidades
    
    # 🛡️ Configuraciones adicionales para manejar conexiones problemáticas
    client_timeout=60,        # Timeout del cliente
    reconnection_attempts=5,  # Límite de intentos de reconexión
    reconnection_delay=2,     # Delay entre reconexiones
)

# 📈 DICCIONARIOS PARA TRACKING DE CLIENTES EN MEMORIA
clientes_conectados = {}  # {client_id: socket_id}
sockets_activos = {}      # {socket_id: client_info}

# 🛡️ FUNCIÓN SEGURA PARA EMITIR EVENTOS
def safe_emit(event, data, room=None, to=None):
    """Emite eventos de Socket.IO con manejo de errores"""
    try:
        if room:
            socketio.emit(event, data, room=room)
        elif to:
            socketio.emit(event, data, to=to)
        else:
            socketio.emit(event, data)
        return True
    except Exception as e:
        print(f"❌ Error emitiendo evento '{event}': {e}")
        return False

# 🎯 FUNCIONES OPTIMIZADAS PARA EMISIÓN SELECTIVA
def emit_to_workers_only(event, data):
    """Emite eventos solo a trabajadores (meseros)"""
    return safe_emit(event, data, room='workers')

def emit_to_clients_only(event, data):
    """Emite eventos solo a clientes"""
    return safe_emit(event, data, room='clients')

def emit_to_specific_client(event, data, client_id):
    """Emite evento a un cliente específico"""
    return safe_emit(event, data, room=f'cliente_{client_id}')
ultimo_heartbeat = {}     # {client_id: timestamp}

# 🧹 FUNCIÓN DE LIMPIEZA DE MEMORIA
def limpiar_cliente_desconectado(sid):
    """Limpia todas las referencias de un cliente desconectado"""
    try:
        if sid in sockets_activos:
            client_info = sockets_activos.pop(sid, {})
            client_id = client_info.get('client_id')
            
            if client_id:
                # Limpiar de clientes_conectados
                if client_id in clientes_conectados and clientes_conectados[client_id] == sid:
                    clientes_conectados.pop(client_id, None)
                
                # Limpiar heartbeat tracking
                ultimo_heartbeat.pop(client_id, None)
                
                # Limpiar SID en base de datos
                try:
                    cliente = db.session.get(Cliente, client_id)
                    if cliente and cliente.sid == sid:
                        cliente.sid = None
                        db.session.commit()
                        print(f"✨ Cliente {client_id} limpiado de BD (SID: {sid})")
                except Exception as e:
                    print(f"⚠️ Error limpiando BD para cliente {client_id}: {e}")
                    db.session.rollback()
                
                print(f"🧺 Cliente {client_id} completamente desconectado y limpiado")
            else:
                print(f"🔍 Socket {sid} desconectado (sin client_id asociado)")
        else:
            print(f"ℹ️ Socket {sid} no estaba en tracking activo")
            
    except Exception as e:
        print(f"❌ Error en limpieza de cliente: {e}")

# 🔗 EVENTOS DE CONEXIÓN Y DESCONEXIÓN
@socketio.on('connect')
def handle_connect():
    """Manejo de nuevas conexiones Socket.IO con manejo de errores mejorado"""
    try:
        sid = request.sid
        client_ip = request.environ.get('REMOTE_ADDR', 'unknown')
        user_agent = request.environ.get('HTTP_USER_AGENT', 'unknown')[:100]
        transport = request.transport if hasattr(request, 'transport') else 'unknown'
        
        print(f"🔌 Nuevo socket conectado:")
        print(f"  🆔 SID: {sid}")
        print(f"  🌐 IP: {client_ip}")
        print(f"  🚀 Transport: {transport}")
        print(f"  📱 User-Agent: {user_agent}")
        print(f"  📊 Total sockets activos: {len(sockets_activos) + 1}")
        
        # Registrar socket con manejo de errores
        sockets_activos[sid] = {
            'connected_at': datetime.now(),
            'client_ip': client_ip,
            'user_agent': user_agent,
            'transport': transport,
            'client_id': None  # Se llenará cuando se registre el cliente
        }
    except Exception as e:
        print(f"❌ Error en handle_connect: {e}")
        # No re-lanzar el error para evitar crashear la conexión

@socketio.on('disconnect')
def handle_disconnect():
    """Manejo de desconexiones Socket.IO con manejo de errores mejorado"""
    try:
        sid = request.sid
        disconnect_reason = request.event.get('reason', 'unknown') if hasattr(request, 'event') else 'unknown'
        
        socket_info = sockets_activos.get(sid, {})
        client_id = socket_info.get('client_id')
        connected_duration = None
        
        if 'connected_at' in socket_info:
            connected_duration = datetime.now() - socket_info['connected_at']
        
        print(f"❌ Socket desconectado:")
        print(f"  🆔 SID: {sid}")
        print(f"  👤 Cliente ID: {client_id or 'No registrado'}")
        print(f"  🔴 Razón: {disconnect_reason}")
        print(f"  ⏱️ Duración conexión: {connected_duration or 'unknown'}")
        print(f"  📊 Total sockets restantes: {len(sockets_activos) - 1}")
        
        # Limpiar todas las referencias con manejo de errores
        limpiar_cliente_desconectado(sid)
    except Exception as e:
        print(f"❌ Error en handle_disconnect: {e}")
        # Intentar limpiar de todas formas
        try:
            limpiar_cliente_desconectado(request.sid)
        except:
            pass

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
        # Verificar que las tablas principales funcionen
        try:
            from models import Mesa, PushSubscription
            
            # Verificar Mesa
            mesas_existentes = db.session.query(db.func.count(Mesa.id)).scalar() or 0
            print(f"✅ Tabla Mesa: {mesas_existentes} registros encontrados")
            
            # Verificar PushSubscription
            try:
                push_count = db.session.query(db.func.count(PushSubscription.id)).scalar() or 0
                print(f"✅ Tabla PushSubscription: {push_count} suscripciones encontradas")
            except Exception as push_error:
                print(f"⚠️ Tabla PushSubscription: {push_error}")
                # Si la tabla no existe, intentar crearla
                try:
                    PushSubscription.__table__.create(db.engine, checkfirst=True)
                    print("✅ Tabla PushSubscription creada exitosamente")
                except Exception as create_error:
                    print(f"❌ No se pudo crear tabla PushSubscription: {create_error}")
            
        except Exception as check_error:
            print(f"⚠️ Error verificando tablas existentes: {check_error}")
            # Como fallback, intentar crear todas las tablas
            db.create_all()
            print("✅ Tablas inicializadas con create_all()")
        
        # Inicializar mesas si es necesario
        try:
            mesas_existentes = db.session.query(db.func.count(Mesa.id)).scalar() or 0
            mesas_deseadas = 26
            
            if mesas_existentes < mesas_deseadas:
                for i in range(mesas_existentes, mesas_deseadas):
                    nueva_mesa = Mesa(capacidad=4)
                    db.session.add(nueva_mesa)
                db.session.commit()
                print(f"Inicializadas {mesas_deseadas - mesas_existentes} mesas nuevas")
            else:
                print(f"Ya existen {mesas_existentes} mesas en la base de datos")
        except Exception as mesa_error:
            print(f"⚠️ Error inicializando mesas: {mesa_error}")
            db.session.rollback()
            
    except Exception as e:
        print(f"Error general inicializando tablas: {e}")
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
            # Si ya tiene mesa asignada y pasaron > 5 minutos desde la asignación, cerrar sesión automáticamente
            try:
                if cliente_existente.mesa_asignada_at:
                    ahora = get_chile_time()
                    asignada = convert_to_chile_time(cliente_existente.mesa_asignada_at)
                    if (ahora - asignada) > timedelta(minutes=5):
                        session.pop('cliente_id', None)
                        return redirect(url_for('qr_landing'))
            except Exception:
                # Si falla cálculo de tiempo, continuar flujo normal
                pass
            llegada_cola_iso = cliente_existente.joined_at.isoformat() if cliente_existente.joined_at else None
            try:
                llegada_cola_fmt = convert_to_chile_time(cliente_existente.joined_at).strftime('%d/%m %H:%M') if cliente_existente.joined_at else None
            except Exception:
                llegada_cola_fmt = cliente_existente.joined_at.strftime('%d/%m %H:%M') if cliente_existente.joined_at else None
            return render_template(
                'client.html',
                numero=cliente_existente.id,
                nombre=cliente_existente.nombre,
                mesa_asignada_at=cliente_existente.mesa_asignada_at.isoformat() if cliente_existente.mesa_asignada_at else None,
                mesa_asignada=cliente_existente.assigned_table,
                llegada_cola=llegada_cola_iso,
                llegada_cola_str=llegada_cola_fmt,
                cantidad_comensales=cliente_existente.cantidad_comensales,
                orden_previa_json=cliente_existente.orden_previa or None,
                en_camino=bool(getattr(cliente_existente, 'en_camino', False))
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
        
        emit_to_workers_only('actualizar_cola', {})
        emit_to_workers_only('actualizar_lista_clientes', {})
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


# 🔔 FUNCIONES PARA NOTIFICACIONES PUSH REALES

def enviar_notificacion_push(cliente_id, mensaje_data):
    """
    Envía una notificación push real al cliente especificado
    
    Args:
        cliente_id (int): ID del cliente
        mensaje_data (dict): Datos del mensaje con keys: type, title, body, mesa, etc.
    """
    try:
        print(f"🔔 === ENVIANDO NOTIFICACIÓN PUSH ===")
        print(f"📱 Cliente ID: {cliente_id}")
        print(f"📦 Datos: {mensaje_data}")
        
        # Buscar suscripciones activas del cliente
        suscripciones = PushSubscription.query.filter_by(
            cliente_id=cliente_id, 
            is_active=True
        ).all()
        
        if not suscripciones:
            print(f"⚠️ No hay suscripciones push activas para cliente {cliente_id}")
            return False
        
        # Configurar headers VAPID
        vapid_headers = {
            "Crypto-Key": f"p256ecdsa={VAPID_PUBLIC_KEY}",
            "Authorization": f"WebPush {VAPID_EMAIL}"
        }
        
        enviadas_exitosamente = 0
        
        # Enviar a todas las suscripciones del cliente
        for suscripcion in suscripciones:
            try:
                # Preparar payload
                payload = json.dumps(mensaje_data)
                
                print(f"📡 Enviando push a endpoint: {suscripcion.endpoint[:50]}...")
                
                # Enviar notificación push
                response = webpush(
                    subscription_info={
                        "endpoint": suscripcion.endpoint,
                        "keys": {
                            "p256dh": suscripcion.p256dh_key,
                            "auth": suscripcion.auth_key
                        }
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_EMAIL}
                )
                
                print(f"✅ Push enviado exitosamente - Status: {response.status_code}")
                enviadas_exitosamente += 1
                
            except WebPushException as e:
                print(f"❌ Error WebPush para suscripción {suscripcion.id}: {e}")
                
                # Si el endpoint ya no es válido, desactivar la suscripción
                if e.response and e.response.status_code in [410, 404]:
                    print(f"🗑️ Desactivando suscripción inválida: {suscripcion.id}")
                    suscripcion.is_active = False
                    db.session.commit()
                    
            except Exception as e:
                print(f"❌ Error general enviando push a suscripción {suscripcion.id}: {e}")
        
        print(f"📊 Resumen: {enviadas_exitosamente}/{len(suscripciones)} notificaciones enviadas")
        return enviadas_exitosamente > 0
        
    except Exception as e:
        print(f"❌ Error en enviar_notificacion_push: {e}")
        return False


def notificar_turno_listo(cliente_id, mesa):
    """
    Envía notificación push cuando el turno del cliente está listo
    
    Args:
        cliente_id (int): ID del cliente
        mesa (int): Número de mesa asignada
    """
    mensaje_data = {
        "type": "turno_listo",
        "title": "🎉 ¡ES TU TURNO!",
        "body": f"Tu mesa {mesa} está lista. Tienes 10 minutos para llegar.",
        "mesa": mesa,
        "timestamp": datetime.now().isoformat(),
        "priority": "high"
    }
    
    print(f"🚨 NOTIFICACIÓN TURNO LISTO - Cliente {cliente_id}, Mesa {mesa}")
    return enviar_notificacion_push(cliente_id, mensaje_data)


def notificar_preaviso_turno(cliente_id, minutos_restantes):
    """
    Envía notificación push de preaviso de turno
    
    Args:
        cliente_id (int): ID del cliente
        minutos_restantes (int): Minutos restantes aproximados
    """
    mensaje_data = {
        "type": "preaviso",
        "title": "⏳ Tu turno se acerca",
        "body": f"Faltan aproximadamente {minutos_restantes} minutos para tu turno.",
        "minutos": minutos_restantes,
        "timestamp": datetime.now().isoformat(),
        "priority": "medium"
    }
    
    print(f"⚠️ NOTIFICACIÓN PREAVISO - Cliente {cliente_id}, {minutos_restantes} min")
    return enviar_notificacion_push(cliente_id, mensaje_data)


def notificar_llamada_mesa(cliente_id, mesa):
    """
    Envía notificación push cuando el mesero llama a una mesa
    
    Args:
        cliente_id (int): ID del cliente
        mesa (int): Número de mesa
    """
    mensaje_data = {
        "type": "llamada_mesa",
        "title": "📞 Te están llamando",
        "body": f"El mesero está llamando a tu mesa {mesa}. ¡Acércate!",
        "mesa": mesa,
        "timestamp": datetime.now().isoformat(),
        "priority": "high"
    }
    
    print(f"📞 NOTIFICACIÓN LLAMADA - Cliente {cliente_id}, Mesa {mesa}")
    return enviar_notificacion_push(cliente_id, mensaje_data)


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
                    # Propagar orden previa si existe
                    if siguiente.orden_previa:
                        try:
                            mesa_liberada.orden = formatear_orden_previa(siguiente.orden_previa)
                        except Exception:
                            mesa_liberada.orden = siguiente.orden_previa
                    
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
                emit_to_specific_client("es_tu_turno", {
                    "mesa": mesa_id_asignada,
                    "asignada_at": cliente_asignado.mesa_asignada_at.isoformat() if cliente_asignado.mesa_asignada_at else None
                }, cliente_asignado.id)
            
            # 🔔 ENVIAR NOTIFICACIÓN PUSH REAL
            notificar_turno_listo(cliente_asignado.id, mesa_id_asignada)
        
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
        
        # Si hay orden previa, colocarla en la mesa principal
        if cliente.orden_previa:
            try:
                mesa_principal.orden = formatear_orden_previa(cliente.orden_previa)
            except Exception:
                mesa_principal.orden = cliente.orden_previa

        db.session.commit()
        
    # Mantener la sesión del cliente; no limpiar para soportar recargas sin duplicados
        
        # Notificar al cliente con función optimizada
        mesas_asignadas = [m.id for m in mesas]
        emit_to_specific_client("es_tu_turno", {
            "mesa": mesa_principal.id,
            "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else [],
            "asignada_at": cliente.mesa_asignada_at.isoformat() if cliente.mesa_asignada_at else None
        }, cliente.id)
        
        # 🔔 ENVIAR NOTIFICACIÓN PUSH REAL
        notificar_turno_listo(cliente.id, mesa_principal.id)
        
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
        
        # Si hay orden previa, colocarla en la mesa principal
        if cliente.orden_previa:
            try:
                mesa_principal.orden = formatear_orden_previa(cliente.orden_previa)
            except Exception:
                mesa_principal.orden = cliente.orden_previa

        db.session.commit()
        
    # Mantener la sesión del cliente; no limpiar para soportar recargas sin duplicados
        
        # Notificar al cliente después del commit exitoso
        if cliente.sid:
            mesas_asignadas = [m.id for m in mesas_reservadas]
            emit_to_specific_client("es_tu_turno", {
                "mesa": mesa_principal.id,
                "mesas_adicionales": mesas_asignadas[1:] if len(mesas_asignadas) > 1 else [],
                "asignada_at": cliente.mesa_asignada_at.isoformat() if cliente.mesa_asignada_at else None
            }, cliente.id)
        
        # 🔔 ENVIAR NOTIFICACIÓN PUSH REAL
        notificar_turno_listo(cliente.id, mesa_principal.id)
        
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
            # Si el cliente tiene orden previa, propagar a la mesa
            if siguiente.orden_previa:
                try:
                    mesa.orden = formatear_orden_previa(siguiente.orden_previa)
                except Exception:
                    mesa.orden = siguiente.orden_previa
            
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
        
        # 🔔 ENVIAR NOTIFICACIÓN PUSH REAL
        if siguiente:
            notificar_turno_listo(siguiente.id, mesa.id)
        
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
            # Propagar orden previa si existe
            if siguiente.orden_previa:
                try:
                    mesa.orden = formatear_orden_previa(siguiente.orden_previa)
                except Exception:
                    mesa.orden = siguiente.orden_previa
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

        # 🔔 ENVIAR NOTIFICACIÓN PUSH REAL
        if cliente_notificado:
            notificar_turno_listo(cliente_notificado.id, mesa.id)

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
    """Registro robusto de clientes con tracking completo"""
    sid = request.sid
    
    try:
        cliente_id = data.get("id")
        
        print(f"📝 Intento de registro:")
        print(f"  🆔 SID: {sid}")
        print(f"  👤 Cliente ID: {cliente_id}")
        print(f"  🔐 Sesión cliente_id: {session.get('cliente_id', 'None')}")
        
        # ✔️ Validar que el cliente_id esté en la sesión
        if 'cliente_id' not in session or session['cliente_id'] != cliente_id:
            print(f"❌ Registro NO AUTORIZADO para cliente {cliente_id} desde SID {sid}")
            emit('error', {'message': 'No autorizado'})
            return False
        
        # ✔️ Verificar cliente en BD
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            print(f"❌ Cliente {cliente_id} NO ENCONTRADO en BD")
            emit('error', {'message': 'Cliente no encontrado'})
            return False
        
        # 🧺 Limpiar registros anteriores del mismo cliente
        if cliente_id in clientes_conectados:
            old_sid = clientes_conectados[cliente_id]
            print(f"♾️ Limpiando registro anterior del cliente {cliente_id} (old SID: {old_sid})")
            limpiar_cliente_desconectado(old_sid)
        
        # ✅ Registrar nuevo cliente
        cliente.sid = sid
        clientes_conectados[cliente_id] = sid
        ultimo_heartbeat[cliente_id] = datetime.now()
        
        # Actualizar info del socket
        if sid in sockets_activos:
            sockets_activos[sid]['client_id'] = cliente_id
            sockets_activos[sid]['registered_at'] = datetime.now()
        
        db.session.commit()
        
        # 🏠 Unirse a salas (personal y general de clientes)
        join_room(f"cliente_{cliente_id}")
        join_room("clients")  # Sala para todos los clientes
        
        print(f"✨ Cliente {cliente_id} registrado exitosamente:")
        print(f"  🆔 SID: {sid}")
        print(f"  📊 Clientes conectados: {len(clientes_conectados)}")
        print(f"  🏠 En salas: cliente_{cliente_id}, clients")
        
        # 📢 Notificar estado actualizado (solo a trabajadores)
        emit_to_workers_only('nuevo_cliente', {
            'cliente_id': cliente.id,
            'joined_at': cliente.joined_at.strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # 📊 Enviar estado de cola
        enviar_estado_cola()
        
        # ✅ Confirmar registro exitoso
        emit('registro_confirmado', {
            'cliente_id': cliente_id,
            'timestamp': datetime.now().isoformat()
        })
        
        return True
        
    except Exception as e:
        print(f"❌ Error crítico en registrar_cliente: {e}")
        print(f"  🆔 SID: {sid}")
        print(f"  📄 Data: {data}")
        db.session.rollback()
        emit('error', {'message': 'Error interno del servidor'})
        return False

@socketio.on("registrar_trabajador")
def registrar_trabajador(data):
    """Registra un trabajador en la sala correspondiente"""
    try:
        sid = request.sid
        trabajador_id = data.get('trabajador_id')
        
        if not trabajador_id or 'trabajador_id' not in session:
            emit('error', {'message': 'No autorizado'})
            return False
            
        # Unirse a sala de trabajadores
        join_room("workers")
        
        # Actualizar información del socket
        if sid in sockets_activos:
            sockets_activos[sid]['worker_id'] = trabajador_id
            sockets_activos[sid]['type'] = 'worker'
        
        print(f"👨‍💼 Trabajador {trabajador_id} registrado en sala workers")
        emit('registro_trabajador_confirmado', {'worker_id': trabajador_id})
        return True
        
    except Exception as e:
        print(f"❌ Error registrando trabajador: {e}")
        emit('error', {'message': 'Error interno'})
        return False

@socketio.on("heartbeat")
def manejar_heartbeat(data):
    """Sistema robusto de heartbeat con detección de conexiones zombie"""
    sid = request.sid
    
    try:
        cliente_id = data.get('cliente_id')
        timestamp = data.get('timestamp', datetime.now().timestamp())
        page_visible = data.get('page_visible', True)
        
        # 📊 Stats del heartbeat
        ahora = datetime.now()
        
        if cliente_id:
            # ✅ Heartbeat con cliente_id
            if cliente_id in clientes_conectados and clientes_conectados[cliente_id] == sid:
                ultimo_heartbeat[cliente_id] = ahora
                print(f"💚 Heartbeat OK - Cliente {cliente_id} (visible: {page_visible})")
                
                # Verificar que el cliente existe en BD
                cliente = db.session.get(Cliente, cliente_id)
                if not cliente:
                    print(f"⚠️ Cliente {cliente_id} no existe en BD - desconectando")
                    limpiar_cliente_desconectado(sid)
                    emit('error', {'message': 'Cliente no válido'})
                    return False
                
                # Actualizar info del socket
                if sid in sockets_activos:
                    sockets_activos[sid]['last_heartbeat'] = ahora
                    sockets_activos[sid]['page_visible'] = page_visible
                
            else:
                print(f"⚠️ Heartbeat de cliente {cliente_id} con SID incorrecto {sid}")
                print(f"  Esperado: {clientes_conectados.get(cliente_id, 'None')}")
                print(f"  Recibido: {sid}")
                limpiar_cliente_desconectado(sid)
                emit('error', {'message': 'SID no válido'})
                return False
        else:
            # 📄 Heartbeat sin cliente_id (socket no registrado)
            print(f"� Heartbeat de socket no registrado: {sid}")
            if sid in sockets_activos:
                sockets_activos[sid]['last_heartbeat'] = ahora
        
        # ✅ Respuesta exitosa del heartbeat
        emit('heartbeat_ack', {
            'timestamp': ahora.timestamp(),
            'server_time': ahora.isoformat(),
            'clientes_conectados': len(clientes_conectados)
        })
        
        return True
        
    except Exception as e:
        print(f"❌ Error en heartbeat: {e}")
        print(f"  🆔 SID: {sid}")
        print(f"  📄 Data: {data}")
        return False

# 🧺 LIMPIEZA PERIÓDICA DE CONEXIONES ZOMBIE
def limpiar_conexiones_zombie():
    """Limpia conexiones que no han enviado heartbeat en mucho tiempo"""
    ahora = datetime.now()
    timeout_segundos = 120  # 2 minutos sin heartbeat = zombie
    
    clientes_zombie = []
    
    for cliente_id, ultimo_hb in ultimo_heartbeat.items():
        if (ahora - ultimo_hb).total_seconds() > timeout_segundos:
            clientes_zombie.append(cliente_id)
    
    if clientes_zombie:
        print(f"🧺 Limpiando {len(clientes_zombie)} conexiones zombie:")
        
        for cliente_id in clientes_zombie:
            if cliente_id in clientes_conectados:
                sid = clientes_conectados[cliente_id]
                print(f"  ❌ Cliente zombie: {cliente_id} (SID: {sid})")
                limpiar_cliente_desconectado(sid)
                
                # Notificar al cliente que debe reconectarse
                try:
                    socketio.emit('connection_expired', {
                        'message': 'Conexión expirada, reconectando...'
                    }, room=f"cliente_{cliente_id}")
                except:
                    pass
        
        print(f"✨ Limpieza zombie completada")
    
    return len(clientes_zombie)

# 🔄 Programar limpieza periódica cada 60 segundos
import threading
import time

def limpieza_periodica():
    """Hilo para limpieza periódica"""
    while True:
        try:
            time.sleep(60)  # Cada minuto
            with app.app_context():
                zombie_count = limpiar_conexiones_zombie()
                if zombie_count > 0:
                    print(f"🧺 Limpieza periódica: {zombie_count} zombies eliminados")
        except Exception as e:
            print(f"❌ Error en limpieza periódica: {e}")

# Iniciar hilo de limpieza
limpieza_thread = threading.Thread(target=limpieza_periodica, daemon=True)
limpieza_thread.start()
print("🧺 Hilo de limpieza periódica iniciado")

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
            'joined_at': c.joined_at.strftime('%Y-%m-%d %H:%M:%S'),
            'tiene_orden_previa': bool(c.orden_previa),
            'en_camino': bool(getattr(c, 'en_camino', False))
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

        # Si hay cliente asociado, pedir al cliente que cierre su sesión (para permitir reuso del teléfono)
        cliente_id = mesa.cliente_id
        if cliente_id:
            cliente = db.session.get(Cliente, cliente_id)
            if cliente and cliente.sid:
                socketio.emit('cerrar_sesion_cliente', {"motivo": "llego"}, to=cliente.sid)
        
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

@app.route('/obtener_info_mesa/<int:mesa_id>')
@worker_required
def obtener_info_mesa(mesa_id):
    """Obtener información completa de la mesa incluyendo datos del cliente"""
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa:
            return jsonify({"success": False, "error": "Mesa no encontrada"})
        
        # Información básica de la mesa
        info_mesa = {
            "success": True,
            "mesa_id": mesa.id,
            "is_occupied": mesa.is_occupied,
            "capacidad": mesa.capacidad,
            "reservada": mesa.reservada,
            "start_time": mesa.start_time.isoformat() if mesa.start_time else None,
            "orden": mesa.orden
        }
        
        # Información del cliente si existe
        if mesa.cliente:
            info_mesa["cliente"] = {
                "id": mesa.cliente.id,
                "nombre": mesa.cliente.nombre,
                "telefono": mesa.cliente.telefono,
                "cantidad_comensales": mesa.cliente.cantidad_comensales,
                "joined_at": mesa.cliente.joined_at.isoformat() if mesa.cliente.joined_at else None,
                "mesa_asignada_at": mesa.cliente.mesa_asignada_at.isoformat() if mesa.cliente.mesa_asignada_at else None,
                "en_camino": getattr(mesa.cliente, 'en_camino', False)
            }
        else:
            info_mesa["cliente"] = None
        
        return jsonify(info_mesa)
        
    except Exception as e:
        print(f"Error en obtener_info_mesa: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)}"})


@app.route('/llamar_mesa/<int:mesa_id>', methods=['POST'])
@worker_required
def llamar_mesa(mesa_id):
    """
    Envía una notificación push para llamar al cliente de una mesa específica
    """
    try:
        mesa = db.session.get(Mesa, mesa_id)
        if not mesa:
            return jsonify({"success": False, "error": "Mesa no encontrada"}), 404
        
        if not mesa.is_occupied or not mesa.cliente_id:
            return jsonify({"success": False, "error": "La mesa no tiene cliente asignado"}), 400
        
        # Obtener el cliente
        cliente = db.session.get(Cliente, mesa.cliente_id)
        if not cliente:
            return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
        
        print(f"📞 === LLAMANDO A MESA {mesa_id} ===")
        print(f"👤 Cliente: {cliente.nombre} (ID: {cliente.id})")
        
        # Enviar notificación push
        push_enviado = notificar_llamada_mesa(cliente.id, mesa_id)
        
        # También enviar por Socket.IO si está conectado
        socket_enviado = False
        if cliente.sid:
            try:
                socketio.emit('llamada_mesa', {
                    'mesa': mesa_id,
                    'mensaje': f'El mesero está llamando a tu mesa {mesa_id}. ¡Acércate!'
                }, to=cliente.sid)
                socket_enviado = True
                print(f"✅ Notificación Socket.IO enviada al cliente {cliente.id}")
            except Exception as e:
                print(f"❌ Error enviando Socket.IO: {e}")
        
        return jsonify({
            "success": True,
            "mensaje": f"Llamada enviada a mesa {mesa_id}",
            "cliente": cliente.nombre,
            "notificaciones": {
                "push": push_enviado,
                "socket": socket_enviado
            }
        })
        
    except Exception as e:
        print(f"❌ Error en llamar_mesa: {e}")
        return jsonify({"success": False, "error": "Error interno del servidor"}), 500

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

@app.route('/marcar_en_camino', methods=['POST'])
def marcar_en_camino():
    """Permite que el cliente en sesión marque que viene en camino."""
    try:
        if 'cliente_id' not in session:
            return jsonify({"success": False, "error": "No autorizado"}), 401

        cliente = db.session.get(Cliente, session['cliente_id'])
        if not cliente:
            return jsonify({"success": False, "error": "Cliente no encontrado"}), 404

        # Solo tiene sentido si aún no tiene mesa asignada
        if cliente.assigned_table is None:
            cliente.en_camino = True
            db.session.commit()
            # Notificar a UIs (solo trabajadores)
            emit_to_workers_only('actualizar_lista_clientes', {})
            emit_to_workers_only('actualizar_cola', {})
            return jsonify({"success": True})
        else:
            # Si ya tiene mesa, también marcamos (visible en mesa recién asignada)
            cliente.en_camino = True
            db.session.commit()
            socketio.emit('actualizar_mesas')
            return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/obtener_orden_previa/<int:cliente_id>')
@worker_required
def obtener_orden_previa(cliente_id):
    try:
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
        return jsonify({
            "success": True,
            "orden_previa": cliente.orden_previa or None,
            "orden_previa_texto": formatear_orden_previa(cliente.orden_previa) if cliente.orden_previa else None
        })
    except Exception as e:
        print(f"Error en obtener_orden_previa: {e}")
        return jsonify({"success": False, "error": "Error interno"}), 500

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
            'tiene_mesa': cliente.assigned_table is not None,
            'en_camino': bool(getattr(cliente, 'en_camino', False))
        }
        
        return jsonify(response)
        
    except Exception as e:
        print(f"Error verificando estado del cliente {cliente_id}: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


# 🔔 RUTAS API PARA NOTIFICACIONES PUSH

@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    """
    Endpoint para que los clientes se suscriban a notificaciones push
    """
    try:
        data = request.json
        print(f"🔔 === NUEVA SUSCRIPCIÓN PUSH ===")
        print(f"📦 Data recibida: {data}")
        
        if not data or 'subscription' not in data:
            return jsonify({'success': False, 'error': 'Datos de suscripción faltantes'}), 400
        
        subscription = data['subscription']
        user_agent = data.get('user_agent', '')
        
        # Validar campos obligatorios
        required_fields = ['endpoint', 'keys']
        for field in required_fields:
            if field not in subscription:
                return jsonify({'success': False, 'error': f'Campo requerido faltante: {field}'}), 400
        
        keys = subscription['keys']
        if 'p256dh' not in keys or 'auth' not in keys:
            return jsonify({'success': False, 'error': 'Claves de suscripción faltantes'}), 400
        
        # Obtener cliente desde la sesión
        cliente_id = session.get('cliente_id')
        if not cliente_id:
            return jsonify({'success': False, 'error': 'Sesión de cliente no encontrada'}), 401
        
        # Verificar si ya existe una suscripción para este endpoint
        suscripcion_existente = PushSubscription.query.filter_by(
            endpoint=subscription['endpoint']
        ).first()
        
        if suscripcion_existente:
            # Actualizar la suscripción existente
            suscripcion_existente.cliente_id = cliente_id
            suscripcion_existente.p256dh_key = keys['p256dh']
            suscripcion_existente.auth_key = keys['auth']
            suscripcion_existente.user_agent = user_agent[:500] if user_agent else None
            suscripcion_existente.is_active = True
            suscripcion_existente.created_at = get_chile_time()
            
            print(f"🔄 Suscripción actualizada para cliente {cliente_id}")
        else:
            # Crear nueva suscripción
            nueva_suscripcion = PushSubscription(
                cliente_id=cliente_id,
                endpoint=subscription['endpoint'],
                p256dh_key=keys['p256dh'],
                auth_key=keys['auth'],
                user_agent=user_agent[:500] if user_agent else None,
                created_at=get_chile_time(),
                is_active=True
            )
            db.session.add(nueva_suscripcion)
            print(f"✅ Nueva suscripción creada para cliente {cliente_id}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Suscripción a notificaciones push registrada exitosamente'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en push_subscribe: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@app.route('/api/push/unsubscribe', methods=['POST'])
def push_unsubscribe():
    """
    Endpoint para desuscribirse de notificaciones push
    """
    try:
        cliente_id = session.get('cliente_id')
        if not cliente_id:
            return jsonify({'success': False, 'error': 'Sesión de cliente no encontrada'}), 401
        
        # Desactivar todas las suscripciones del cliente
        suscripciones = PushSubscription.query.filter_by(cliente_id=cliente_id).all()
        for suscripcion in suscripciones:
            suscripcion.is_active = False
        
        db.session.commit()
        
        print(f"🔕 Cliente {cliente_id} se desuscribió de notificaciones push")
        
        return jsonify({
            'success': True,
            'message': 'Desuscripción exitosa'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en push_unsubscribe: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@app.route('/api/push/test', methods=['POST'])
def test_push_notification():
    """
    Endpoint para probar notificaciones push (solo para desarrollo)
    """
    try:
        cliente_id = session.get('cliente_id')
        if not cliente_id:
            return jsonify({'success': False, 'error': 'Sesión de cliente no encontrada'}), 401
        
        # Enviar notificación de prueba
        mensaje_data = {
            "type": "test",
            "title": "🧪 Notificación de Prueba",
            "body": "Esta es una notificación de prueba para verificar que todo funciona correctamente.",
            "timestamp": datetime.now().isoformat()
        }
        
        enviado = enviar_notificacion_push(cliente_id, mensaje_data)
        
        return jsonify({
            'success': enviado,
            'message': 'Notificación de prueba enviada' if enviado else 'No se pudo enviar la notificación'
        })
        
    except Exception as e:
        print(f"❌ Error en test_push_notification: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@app.route('/test_push')
def test_push_page():
    """Página de prueba para notificaciones push (solo desarrollo)"""
    return render_template('test_push.html')

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
        emit_to_workers_only('actualizar_lista_clientes', {})
        emit_to_workers_only('actualizar_cola', {})
        enviar_estado_cola()
        
        return jsonify({
            "success": True, 
            "mensaje": "Tu lugar en la fila ha sido cancelado exitosamente"
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error cancelando turno: {e}")
        return jsonify({"success": False, "error": "Error interno"}), 500

@app.route('/logout_cliente', methods=['POST'])
def logout_cliente():
    """Cerrar solo la sesión del cliente (no afecta sesión de trabajador)."""
    try:
        session.pop('cliente_id', None)
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error en logout_cliente: {e}")
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
        # Configuración para Render (producción) - permitir Werkzeug temporalmente
        port = int(os.environ.get('PORT', 5000))
        socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
    else:
        # Configuración para desarrollo local
        socketio.run(app, debug=True)
