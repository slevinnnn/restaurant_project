#!/usr/bin/env python3
"""
Script para reiniciar completamente la base de datos de clientes y trabajadores
"""

import os
import sys
from app import app, db, Cliente, Mesa, Trabajador, UsoMesa

def reiniciar_base_datos():
    """Reiniciar completamente la base de datos eliminando clientes y trabajadores"""
    with app.app_context():
        try:
            # Detectar si estamos en producción o desarrollo
            es_produccion = bool(os.environ.get('DATABASE_URL'))
            tipo_bd = "PostgreSQL (Render)" if es_produccion else "SQLite (Local)"
            
            print(f"🌍 Conectado a: {tipo_bd}")
            print(f"🔗 Base de datos: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
            print()
            
            # Contar registros antes de eliminar
            clientes_count = Cliente.query.count()
            trabajadores_count = Trabajador.query.count()
            uso_mesas_count = UsoMesa.query.count()
            
            print(f"📊 Estado actual de la base de datos:")
            print(f"   - Clientes: {clientes_count}")
            print(f"   - Trabajadores: {trabajadores_count}")
            print(f"   - Registros de uso de mesas: {uso_mesas_count}")
            print()
            
            # 1. Eliminar todos los clientes
            Cliente.query.delete()
            print("🗑️ Eliminados todos los clientes")
            
            # 2. Eliminar todos los trabajadores
            Trabajador.query.delete()
            print("🗑️ Eliminados todos los trabajadores")
            
            # 3. Eliminar historial de uso de mesas
            UsoMesa.query.delete()
            print("🗑️ Eliminado historial de uso de mesas")
            
            # 4. Resetear estado de todas las mesas
            mesas = Mesa.query.all()
            for mesa in mesas:
                mesa.is_occupied = False
                mesa.start_time = None
                mesa.cliente_id = None
                mesa.llego_comensal = False
                mesa.reservada = False
                mesa.orden = None
            
            print(f"🔄 Reseteadas {len(mesas)} mesas (mantienen su capacidad)")
            
            # 5. Confirmar cambios
            db.session.commit()
            
            print()
            print("✅ Base de datos reiniciada completamente:")
            print(f"   - Eliminados {clientes_count} clientes")
            print(f"   - Eliminados {trabajadores_count} trabajadores")
            print(f"   - Eliminados {uso_mesas_count} registros de uso")
            print(f"   - Reseteadas {len(mesas)} mesas")
            print(f"   - Las {len(mesas)} mesas se mantienen disponibles")
            print()
            print("⚠️  IMPORTANTE: Necesitarás registrar un nuevo trabajador para acceder al sistema")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error al reiniciar la base de datos: {e}")
            return False

if __name__ == '__main__':
    print("🔄 SCRIPT DE REINICIO DE BASE DE DATOS")
    print("⚠️  PELIGRO: Esto eliminará TODOS los clientes y trabajadores")
    print("⚠️  PELIGRO: Esto reseteará TODAS las mesas")
    print("⚠️  Esta acción NO se puede deshacer")
    print()
    respuesta = input("¿Estás COMPLETAMENTE seguro de que quieres continuar? (escribe 'SÍ ESTOY SEGURO' para confirmar): ")
    
    if respuesta.strip().upper() == "SÍ ESTOY SEGURO":
        print("Procediendo con el reinicio...")
        reiniciar_base_datos()
    else:
        print("❌ Reinicio cancelado por el usuario. Ningún dato fue modificado.")
        print("Para ejecutar el reinicio, debes escribir exactamente: SÍ ESTOY SEGURO")
