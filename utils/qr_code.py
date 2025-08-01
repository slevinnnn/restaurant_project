import qrcode

# URL de tu servidor, puede ser localhost o ngrok
url = "https://colasrestaurant.onrender.com/qr_landing"

img = qrcode.make(url)
img.save("codigo_qr_cliente.png")
