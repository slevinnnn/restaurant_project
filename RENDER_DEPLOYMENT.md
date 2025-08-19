# Instrucciones para configurar variables de entorno en Render

## Variables de entorno requeridas en Render:

### 1. FLASK_ENV
- Nombre: `FLASK_ENV`
- Valor: `production`
- Descripción: Indica que la aplicación está en producción

### 2. SECRET_KEY (CRÍTICO)
- Nombre: `SECRET_KEY`
- Valor: [generar una clave segura única]
- Descripción: Clave secreta para sesiones y seguridad

Para generar una SECRET_KEY segura, ejecuta en tu terminal local:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. PORT (Opcional)
- Nombre: `PORT`
- Valor: Se configura automáticamente por Render
- Descripción: Puerto donde corre la aplicación

## Pasos para configurar en Render:

1. Ve a tu servicio en Render Dashboard
2. Ir a "Environment" 
3. Agregar las variables:
   - `FLASK_ENV` = `production`
   - `SECRET_KEY` = [tu_clave_generada]

## Verificación:

Una vez desplegado, la aplicación:
- ✅ Usará configuración de producción (host='0.0.0.0', debug=False)
- ✅ Tomará el puerto de la variable PORT de Render
- ✅ Usará cookies seguras con HTTPS
- ✅ Inicializará las 8 mesas automáticamente
- ✅ Mantendrá todas las mejoras de seguridad

## Nota importante:
Sin la variable FLASK_ENV=production, la app funcionará pero con configuración de desarrollo.
