// Service Worker para manejar notificaciones push
self.addEventListener('install', (event) => {
  console.log('Service Worker instalado');
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('Service Worker activado');
  event.waitUntil(self.clients.claim());
});

// Manejar notificaciones push
self.addEventListener('push', (event) => {
  console.log('Notificación push recibida:', event);
  
  const options = {
    body: event.data ? event.data.text() : 'Es tu turno en el restaurante!',
    icon: '/static/images/logo-alleria.png',
    badge: '/static/images/logo-alleria.png',
    vibrate: [200, 100, 200],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'view',
        title: 'Ver Mesa',
        icon: '/static/images/icono-de-la-mesa-redonda.webp'
      },
      {
        action: 'close',
        title: 'Cerrar'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification('🍽️ Restaurante Alleria', options)
  );
});

// Manejar clics en las notificaciones
self.addEventListener('notificationclick', (event) => {
  console.log('Notificación clickeada:', event);
  
  event.notification.close();
  
  if (event.action === 'view') {
    // Abrir o enfocar la ventana de la aplicación
    event.waitUntil(
      clients.matchAll().then((clientList) => {
        for (const client of clientList) {
          if (client.url.includes('/cliente') && 'focus' in client) {
            return client.focus();
          }
        }
        if (clients.openWindow) {
          return clients.openWindow('/cliente');
        }
      })
    );
  }
});
