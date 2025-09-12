#!/usr/bin/env python3
"""
Script para limpiar los datos de la base de datos manteniendo las 26 mesas
"""

import os
import sys
from app import app, db, Cliente, Mesa

def limpiar_datos():
    """Limpiar todos los datos de clientes y resetear mesas"""
    with app.app_context():
        try:
            # Contar clientes antes de eliminar
            clientes_eliminados = Cliente.query.count()
            
            # Eliminar todos los clientes
            Cliente.query.delete()
            
            # Resetear estado de todas las mesas
            mesas = Mesa.query.all()
            for mesa in mesas:
                mesa.is_occupied = False
                mesa.start_time = None
                mesa.cliente_id = None
                mesa.llego_comensal = False
                mesa.reservada = False
                mesa.orden = None
            
            # Confirmar cambios
            db.session.commit()
            
            print(f'✅ Base de datos limpiada exitosamente:')
            print(f'   - Eliminados {clientes_eliminados} clientes')
            print(f'   - Reseteadas {len(mesas)} mesas (mantienen su capacidad)')
            print(f'   - Todas las mesas están ahora disponibles')
            print(f'   - Las {len(mesas)} mesas se mantienen en la base de datos')
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f'❌ Error al limpiar la base de datos: {e}')
            return False

if __name__ == '__main__':
    print("🧹 SCRIPT DE LIMPIEZA DE DATOS")
    print("⚠️  PELIGRO: Esto eliminará TODOS los clientes")
    print("⚠️  PELIGRO: Esto reseteará TODAS las mesas")  
    print("⚠️  Esta acción NO se puede deshacer")
    print()
    respuesta = input("¿Estás COMPLETAMENTE seguro de que quieres continuar? (escribe 'SÍ ESTOY SEGURO' para confirmar): ")
    
    if respuesta.strip().upper() == "SÍ ESTOY SEGURO":
        print("Procediendo con la limpieza...")
        limpiar_datos()
    else:
        print("❌ Limpieza cancelada por el usuario. Ningún dato fue modificado.")
        print("Para ejecutar la limpieza, debes escribir exactamente: SÍ ESTOY SEGURO")
