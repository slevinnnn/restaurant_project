#!/usr/bin/env python3
"""
Script de verificación para el deployment de la aplicación
Verifica que todas las dependencias y configuraciones estén correctas
"""

def check_push_notifications():
    """Verificar que las dependencias de push notifications estén disponibles"""
    try:
        import pywebpush
        from py_vapid import Vapid
        print("✅ Dependencias de push notifications: OK")
        return True
    except ImportError as e:
        print(f"❌ Error importando dependencias push: {e}")
        return False

def check_database():
    """Verificar configuración de base de datos"""
    try:
        from models import db, Cliente, Mesa, PushSubscription
        print("✅ Modelos de base de datos: OK")
        return True
    except ImportError as e:
        print(f"❌ Error importando modelos: {e}")
        return False

def check_socketio():
    """Verificar configuración de Socket.IO"""
    try:
        from flask_socketio import SocketIO
        print("✅ Socket.IO: OK")
        return True
    except ImportError as e:
        print(f"❌ Error importando Socket.IO: {e}")
        return False

def check_vapid_keys():
    """Verificar que las claves VAPID estén configuradas"""
    try:
        from app import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_EMAIL
        
        if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY and VAPID_EMAIL:
            print("✅ Claves VAPID configuradas: OK")
            return True
        else:
            print("❌ Claves VAPID no configuradas correctamente")
            return False
    except ImportError as e:
        print(f"❌ Error importando claves VAPID: {e}")
        return False

def main():
    """Ejecutar todas las verificaciones"""
    print("🔍 === VERIFICACIÓN DE DEPLOYMENT ===\n")
    
    checks = [
        ("Push Notifications", check_push_notifications),
        ("Base de Datos", check_database), 
        ("Socket.IO", check_socketio),
        ("Claves VAPID", check_vapid_keys)
    ]
    
    results = []
    for name, check_func in checks:
        print(f"🧪 Verificando {name}...")
        result = check_func()
        results.append(result)
        print()
    
    print("📊 === RESUMEN ===")
    if all(results):
        print("🎉 ¡Todas las verificaciones pasaron! La aplicación está lista para deployment.")
        return True
    else:
        failed_count = len([r for r in results if not r])
        print(f"❌ {failed_count} verificaciones fallaron. Revisa los errores arriba.")
        return False

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)