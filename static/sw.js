// Service Worker para manejar notificaciones push
self.addEventListener('install', (event) => {
  console.log('🔧 Service Worker instalado');
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('✅ Service Worker activado');
  event.waitUntil(self.clients.claim());
});

// Manejar notificaciones push
self.addEventListener('push', (event) => {
  console.log('🔔 Notificación push recibida:', event);
  
  let notificationData = {
    title: '🍽️ Restaurante Alleria',
    body: 'Es tu turno en el restaurante!',
    mesa: 'N/A'
  };
  
  if (event.data) {
    try {
      const data = event.data.json();
      notificationData = {
        title: data.title || notificationData.title,
        body: data.body || notificationData.body,
        mesa: data.mesa || notificationData.mesa
      };
    } catch (e) {
      notificationData.body = event.data.text();
    }
  }
  
  const options = {
    body: notificationData.body,
    icon: '/static/images/logo-alleria.png',
    badge: '/static/images/logo-alleria.png',
    vibrate: [500, 200, 500, 200, 500], // Vibración más intensa
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1,
      mesa: notificationData.mesa,
      url: '/cliente'
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
    ],
    requireInteraction: true, // Mantener hasta que el usuario interactúe
    silent: false, // Asegurarse de que no sea silenciosa
    tag: 'restaurant-turn' // Tag único para reemplazar notificaciones anteriores
  };

  event.waitUntil(
    self.registration.showNotification(notificationData.title, options)
  );
});

// Manejar clics en las notificaciones
self.addEventListener('notificationclick', (event) => {
  console.log('🔔 Notificación clickeada:', event);
  
  event.notification.close();
  
  if (event.action === 'view' || !event.action) {
    // Abrir o enfocar la ventana de la aplicación
    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
        // Buscar una ventana ya abierta con la aplicación
        for (const client of clientList) {
          if (client.url.includes('/cliente') && 'focus' in client) {
            console.log('📱 Enfocando ventana existente');
            return client.focus();
          }
        }
        
        // Si no hay ventana abierta, abrir una nueva
        if (clients.openWindow) {
          console.log('📱 Abriendo nueva ventana');
          return clients.openWindow('/cliente');
        }
      })
    );
  }
});

// Manejar mensajes del cliente
self.addEventListener('message', (event) => {
  console.log('📨 Mensaje recibido en SW:', event.data);
  
  if (event.data && event.data.type === 'SHOW_NOTIFICATION') {
    const { title, body, mesa } = event.data;
    
    const options = {
      body: body,
      icon: '/static/images/logo-alleria.png',
      badge: '/static/images/logo-alleria.png',
      vibrate: [500, 200, 500, 200, 500],
      data: { mesa, url: '/cliente' },
      requireInteraction: true,
      tag: 'restaurant-turn'
    };
    
    self.registration.showNotification(title, options);
  }
});
