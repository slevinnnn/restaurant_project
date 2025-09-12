#!/usr/bin/env python3
"""
Script para agregar 6 mesas adicionales (de 20 a 26) 
Compatible con desarrollo local y producción en Render
"""

import os
import sys
from datetime import datetime

# Agregar el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def agregar_mesas_nuevas():
    """Agrega las mesas nuevas de la 21 a la 26"""
    try:
        from app import app, db, Mesa
        
        with app.app_context():
            print("🔧 Verificando mesas existentes...")
            
            # Contar mesas actuales
            total_mesas = Mesa.query.count()
            print(f"📊 Mesas actuales: {total_mesas}")
            
            if total_mesas >= 26:
                print("✅ Ya tienes 26 o más mesas. No se necesita agregar más.")
                return
            
            # Agregar las mesas faltantes
            mesas_a_agregar = 26 - total_mesas
            print(f"➕ Agregando {mesas_a_agregar} mesas nuevas...")
            
            for i in range(mesas_a_agregar):
                nueva_mesa = Mesa(capacidad=4)  # Capacidad por defecto de 4 personas
                db.session.add(nueva_mesa)
            
            db.session.commit()
            
            # Verificar resultado
            total_final = Mesa.query.count()
            print(f"✅ ¡Completado! Ahora tienes {total_final} mesas en total")
            
            # Mostrar las últimas mesas agregadas
            ultimas_mesas = Mesa.query.order_by(Mesa.id.desc()).limit(mesas_a_agregar).all()
            print(f"🆕 Mesas agregadas:")
            for mesa in reversed(ultimas_mesas):
                print(f"   • Mesa {mesa.id} - Capacidad: {mesa.capacidad} personas")
    
    except Exception as e:
        print(f"❌ Error agregando mesas: {e}")
        return False
    
    return True

def main():
    """Función principal"""
    print("🍽️  AGREGANDO MESAS ADICIONALES (20 → 26)")
    print("=" * 50)
    
    # Detectar si estamos en desarrollo o producción
    if os.environ.get('DATABASE_URL'):
        print("🌐 Ejecutando en PRODUCCIÓN (Render)")
    else:
        print("💻 Ejecutando en DESARROLLO (Local)")
    
    # Agregar las mesas
    if agregar_mesas_nuevas():
        print("\n🎉 ¡Proceso completado exitosamente!")
        print("💡 Las nuevas mesas aparecerán en la interfaz de trabajador")
        print("💡 Puedes cambiar su capacidad individualmente desde la interfaz web")
    else:
        print("\n❌ Hubo un error en el proceso")
        
if __name__ == "__main__":
    main()