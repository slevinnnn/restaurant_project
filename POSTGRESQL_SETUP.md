# Configuración de PostgreSQL en Render

## Problema Resuelto
Este archivo documenta la solución al problema donde los datos se perdían en Render debido al uso de SQLite con almacenamiento efímero.

## Solución Implementada
La aplicación ahora usa:
- **PostgreSQL** en producción (Render) - Base de datos persistente
- **SQLite** en desarrollo local - Para facilidad de desarrollo

## Pasos para configurar en Render:

### 1. Crear una base de datos PostgreSQL
1. Ve a tu dashboard de Render
2. Clic en "New +" → "PostgreSQL"
3. Configuración:
   - **Name**: `restaurant-db` (o el nombre que prefieras)
   - **Database**: `restaurant_project`
   - **User**: `restaurant_user` (o el que prefieras)
   - **Region**: Usa la misma región que tu aplicación web
   - **PostgreSQL Version**: 15 (recomendado)
   - **Plan**: Free (para comenzar)

### 2. Configurar variables de entorno en tu Web Service
1. Ve a tu Web Service en Render
2. Ve a "Environment"
3. Agregar las siguientes variables:

```
DATABASE_URL=postgresql://restaurant_user:password@hostname:5432/restaurant_project
FLASK_ENV=production
```

**Importante**: Render te proporcionará automáticamente la URL completa de la base de datos. Cópiala exactamente como aparece en tu PostgreSQL service.

### 3. Conectar la base de datos al Web Service
1. En tu PostgreSQL service, copia la "Internal Database URL"
2. En tu Web Service, en "Environment", actualiza `DATABASE_URL` con esa URL

### 4. Ejecutar migraciones (primera vez)
Cuando despliegues por primera vez con PostgreSQL, la aplicación automáticamente:
- Creará las tablas necesarias
- Inicializará las 8 mesas por defecto
- Estará lista para usar

## Beneficios de esta solución:

✅ **Persistencia de datos**: Los datos nunca se pierden
✅ **Escalabilidad**: PostgreSQL maneja mejor múltiples usuarios
✅ **Backup automático**: Render hace backups automáticos
✅ **Desarrollo local**: Sigue usando SQLite para desarrollo rápido
✅ **Configuración automática**: La app detecta automáticamente el entorno

## Verificación
Después del deployment:
1. Verifica que la variable `DATABASE_URL` esté configurada
2. Comprueba que la aplicación inicie sin errores
3. Crea algunos datos de prueba
4. Reinicia la aplicación en Render
5. Verifica que los datos persistan

## Troubleshooting

### Si ves errores de conexión:
- Verifica que `DATABASE_URL` esté correctamente configurada
- Asegúrate de que la PostgreSQL database esté en "Available" status
- Revisa los logs del Web Service para errores específicos

### Si los datos no persisten:
- Confirma que estás usando la Internal Database URL
- Verifica que no hay múltiples variables DATABASE_URL configuradas
- Revisa que psycopg2-binary esté en requirements.txt

## Comandos útiles para desarrollo local:

```bash
# Ver la configuración de base de datos que se está usando
python -c "import os; print('DB:', os.environ.get('DATABASE_URL', 'SQLite local'))"

# Para migrar cambios del modelo (si haces cambios a models.py)
python -m flask db init
python -m flask db migrate -m "Descripción del cambio"
python -m flask db upgrade
```
