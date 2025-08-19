# Corrección: Lógica de Capacidad Respetando Orden de Llegada

## Problema Identificado

Cuando se cancelaba una reserva de mesa, el sistema asignaba automáticamente al primer cliente en la fila **sin verificar la capacidad**. Esto causaba situaciones como:

- Mesa de 2 personas se cancela
- Cliente con 4 comensales (primero en fila) era asignado automáticamente
- ❌ **INCORRECTO**: 4 personas en mesa de 2

## Principio Fundamental

⚠️ **PRIORIDAD #1: ORDEN DE LLEGADA**
- Nunca saltarse al primer cliente por temas de capacidad
- Si el primer cliente no cabe, mesa queda libre para asignación manual
- Respeto absoluto al orden de llegada

## Solución Implementada

### 1. Nuevas Funciones Helper:

```python
def buscar_siguiente_cliente_en_orden():
    """Busca al PRIMER cliente en la fila (sin saltar a nadie)"""
    return Cliente.query.filter_by(assigned_table=None).order_by(Cliente.joined_at).first()

def puede_asignar_cliente_a_mesa(cliente, mesa):
    """Verifica si un cliente específico puede ser asignado a una mesa específica"""
    return cliente.cantidad_comensales <= mesa.capacidad
```

### 2. Lógica Corregida:

#### `cancelar_reserva()` y `liberar_mesa()`:
1. ✅ Buscar al **PRIMER** cliente en la fila
2. ✅ Verificar si ese cliente específico cabe en la mesa
3. ✅ **SI CABE**: Asignar automáticamente (mesa azul - ocupada)
4. ✅ **NO CABE**: Mesa queda reservada (mesa amarilla - reservada) para asignación manual
5. ✅ **SIN CLIENTES**: Mesa queda libre (mesa verde - disponible)

## Comportamiento Correcto

### Escenario 1: Primer Cliente Cabe
- Mesa capacidad 4 se cancela/libera
- Primer cliente en fila: 3 comensales
- ✅ **CORRECTO**: Se asigna automáticamente (mesa azul)

### Escenario 2: Primer Cliente NO Cabe
- Mesa capacidad 2 se cancela/libera  
- Primer cliente en fila: 4 comensales
- ✅ **CORRECTO**: Mesa queda RESERVADA (amarilla) para asignación manual
- ✅ **CORRECTO**: Meseros pueden asignar manualmente cuando consideren apropiado
- ✅ **CORRECTO**: NO se salta al segundo/tercero/etc. por capacidad

### Escenario 3: No Hay Clientes en Espera
- Mesa se cancela/libera
- Fila de espera: vacía
- ✅ **CORRECTO**: Mesa queda libre (verde - disponible)

## Estados de Mesa Resultantes

1. **Mesa Azul (Ocupada)**: Primer cliente cabe y fue asignado automáticamente
2. **Mesa Amarilla (Reservada)**: Primer cliente NO cabe, queda reservada para asignación manual
3. **Mesa Verde (Libre)**: No hay clientes en espera, mesa disponible

## Beneficios

1. **Orden de llegada respetado**: Nunca se salta a nadie
2. **Lógica clara**: Simple de entender y predecir
3. **Flexibilidad**: Trabajador puede asignar manualmente casos especiales
4. **Justicia**: Primer llegado, primer servido (si cabe)
5. **Control**: Trabajador tiene control total sobre asignaciones "difíciles"

## Casos de Uso

- ✅ **Mesa pequeña libre + cliente grande**: Mesa queda RESERVADA (amarilla) para asignación manual
- ✅ **Mesa grande libre + cliente pequeño**: Mesa se asigna automáticamente (azul)
- ✅ **No hay clientes**: Mesa queda libre (verde)
- ✅ **Asignación manual disponible**: Para mesas reservadas cuando el primer cliente no cabe
- ✅ **Orden siempre respetado**: Nunca se salta por capacidad

La mejora asegura que el sistema **NUNCA** comprometa el orden de llegada por temas de capacidad, manteniendo la justicia del sistema mientras permite flexibilidad manual cuando sea necesario.
