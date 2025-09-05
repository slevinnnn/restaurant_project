#!/usr/bin/env python3
"""
Script para limpiar los datos de la base de datos manteniendo las 20 mesas
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
    limpiar_datos()
