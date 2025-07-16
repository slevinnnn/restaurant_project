import qrcode

# URL de tu servidor, puede ser localhost o ngrok
url = "https://abc123.ngrok.io/cliente"

img = qrcode.make(url)
img.save("codigo_qr_cliente.png")
