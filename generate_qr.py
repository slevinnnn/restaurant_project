#!/usr/bin/env python3
"""
Generador de código QR para el restaurante
Genera un código QR que redirije a la página de registro de clientes
"""

import qrcode
from PIL import Image
import os

def generate_restaurant_qr():
    # URL de tu sitio web
    url = "https://colasrestaurant.onrender.com/qr_landing"
    
    # Crear instancia QR con configuración optimizada
    qr = qrcode.QRCode(
        version=1,  # Controla el tamaño (1 es el más pequeño)
        error_correction=qrcode.constants.ERROR_CORRECT_M,  # ~15% corrección de errores
        box_size=10,  # Tamaño de cada "caja" en píxeles
        border=4,     # Grosor del borde (mínimo recomendado: 4)
    )
    
    # Agregar datos al código QR
    qr.add_data(url)
    qr.make(fit=True)
    
    # Crear imagen del QR
    # Usar colores personalizados: negro sobre blanco
    qr_img = qr.make_image(
        fill_color="black",
        back_color="white"
    )
    
    # Guardar en la carpeta del proyecto
    output_path = "qr_code_restaurant.png"
    qr_img.save(output_path)
    
    print(f"✅ Código QR generado exitosamente!")
    print(f"📁 Archivo guardado como: {output_path}")
    print(f"🌐 URL codificada: {url}")
    print(f"📱 Escaneando este QR los clientes serán redirigidos a tu página de registro")
    
    return output_path

def generate_high_quality_qr():
    """Genera una versión de alta calidad para impresión"""
    url = "https://colasrestaurant.onrender.com/qr_landing"
    
    # Configuración para alta calidad
    qr = qrcode.QRCode(
        version=3,  # Más grande para mejor legibilidad
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # Máxima corrección de errores
        box_size=20,  # Cajas más grandes
        border=6,     # Borde más ancho
    )
    
    qr.add_data(url)
    qr.make(fit=True)
    
    # Crear imagen de alta resolución
    qr_img = qr.make_image(
        fill_color="black",
        back_color="white"
    ).convert('RGB')
    
    # Redimensionar para calidad de impresión (300 DPI aproximadamente)
    width, height = qr_img.size
    qr_img = qr_img.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    
    output_path = "qr_code_restaurant_hq.png"
    qr_img.save(output_path, "PNG", quality=100, optimize=True)
    
    print(f"✅ Código QR de alta calidad generado!")
    print(f"📁 Archivo guardado como: {output_path}")
    print(f"🖨️  Optimizado para impresión")
    
    return output_path

if __name__ == "__main__":
    print("🍽️  Generador de Código QR - Restaurante")
    print("=" * 40)
    
    try:
        # Generar ambas versiones
        standard_qr = generate_restaurant_qr()
        print()
        hq_qr = generate_high_quality_qr()
        
        print("\n" + "=" * 40)
        print("📋 INSTRUCCIONES DE USO:")
        print("1. Imprime el archivo de alta calidad para las mesas")
        print("2. Asegúrate de que el QR tenga al menos 2.5cm x 2.5cm")
        print("3. Prueba escaneando con diferentes dispositivos")
        print("4. Coloca los códigos QR en lugares visibles en cada mesa")
        
    except ImportError as e:
        print("❌ Error: Faltan dependencias")
        print("Instala las librerías necesarias con:")
        print("pip install qrcode[pil] pillow")
        
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
