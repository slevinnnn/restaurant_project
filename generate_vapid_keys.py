#!/usr/bin/env python3
"""
Generador de claves VAPID para notificaciones push
"""
import base64
import secrets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

def generate_vapid_keys():
    """Genera un par de claves VAPID (pública y privada)"""
    
    # Generar clave privada
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    
    # Obtener clave pública
    public_key = private_key.public_key()
    
    # Serializar clave privada en formato PEM
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # Serializar clave pública en formato UncompressedPoint
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    
    # Convertir clave pública a base64 URL-safe (sin padding)
    public_b64 = base64.urlsafe_b64encode(public_raw).decode('utf-8').rstrip('=')
    
    # Para la clave privada, usar el formato PEM completo
    private_str = private_pem.decode('utf-8')
    
    return private_str, public_b64

if __name__ == '__main__':
    print("🔑 Generando claves VAPID...")
    private_key, public_key = generate_vapid_keys()
    
    print(f"\n🔒 CLAVE PRIVADA (para el servidor):")
    print(private_key)
    
    print(f"\n🔓 CLAVE PÚBLICA (para el cliente):")
    print(public_key)
    
    print(f"\n📝 Configura estas variables:")
    print(f"VAPID_PUBLIC_KEY = '{public_key}'")