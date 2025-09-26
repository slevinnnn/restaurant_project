// 🔔 SERVICE WORKER PARA NOTIFICACIONES PUSH REALES
// Versión del cache para forzar actualizaciones
const CACHE_VERSION = 'v1.2.0';
const CACHE_NAME = `restaurant-sw-${CACHE_VERSION}`;

// 📦 INSTALACIÓN DEL SERVICE WORKER
self.addEventListener('install', (event) => {
  console.log('🔧 Service Worker: Instalando versión', CACHE_VERSION);
  self.skipWaiting(); // Forzar activación inmediata
});

// ⚡ ACTIVACIÓN DEL SERVICE WORKER
self.addEventListener('activate', (event) => {
  console.log('🚀 Service Worker: Activado versión', CACHE_VERSION);
  event.waitUntil(
    self.clients.claim() // Tomar control inmediatamente
  );
});

// 🔔 RECIBIR NOTIFICACIONES PUSH DEL SERVIDOR
self.addEventListener('push', (event) => {
  console.log('🔔 === PUSH NOTIFICATION RECIBIDA ===');
  console.log('📦 Event data:', event.data);
  
  try {
    // Parsear datos del push
    let data = {};
    if (event.data) {
      data = event.data.json();
      console.log('✅ Datos parseados:', data);
    }
    
    // Configuración por defecto
    const defaultOptions = {
      title: '🍽️ Restaurante Alleria',
      body: 'Tienes una nueva notificación',
      icon: '/static/images/logo-alleria.png',
      badge: '/static/images/logo-alleria.png',
      tag: 'restaurant-notification',
      renotify: true,
      requireInteraction: false, // Cambiado a false por defecto
      silent: false,
      vibrate: [500, 200, 500, 200, 500], // Patrón de vibración estándar
      actions: [
        {
          action: 'view',
          title: '👀 Ver Mesa',
          icon: '/static/images/icono-de-la-mesa-redonda.webp'
        },
        {
          action: 'dismiss',
          title: '✖️ Cerrar'
        }
      ],
      data: {
        ...data,
        timestamp: Date.now(),
        url: '/cliente'
      }
    };
    
    // Personalizar según el tipo de notificación
    let options = { ...defaultOptions };
    
    if (data.type === 'turno_listo') {
      // 🎉 TURNO LISTO - MÁXIMA PRIORIDAD
      options.title = '🎉 ¡ES TU TURNO!';
      options.body = `Tu mesa ${data.mesa} está lista. Tienes 5 minutos para llegar.`;
      options.tag = 'turno-mesa';
      options.vibrate = [800, 200, 800, 200, 800, 200, 1000]; // Vibración MUY intensa
      options.requireInteraction = true; // Requiere interacción del usuario
      options.silent = false;
      options.data.priority = 'high';
      options.data.mesa = data.mesa;
      
      console.log('🚨 NOTIFICACIÓN DE TURNO LISTO - VIBRACIÓN INTENSA');
      
    } else if (data.type === 'preaviso') {
      // ⏳ PREAVISO - PRIORIDAD MEDIA
      options.title = '⏳ Tu turno se acerca';
      options.body = `Faltan aproximadamente ${data.minutos || 5} minutos para tu turno.`;
      options.tag = 'preaviso-turno';
      options.vibrate = [300, 150, 300, 150, 300]; // Vibración suave
      options.requireInteraction = false;
      
      console.log('⚠️ NOTIFICACIÓN DE PREAVISO - VIBRACIÓN SUAVE');
      
    } else if (data.type === 'llamada_mesa') {
      // 📞 LLAMADA A MESA - ALTA PRIORIDAD
      options.title = '📞 Te están llamando';
      options.body = `El mesero está llamando a tu mesa ${data.mesa}. ¡Acércate!`;
      options.tag = 'llamada-mesa';
      options.vibrate = [600, 300, 600, 300, 600, 300, 600]; // Vibración persistente
      options.requireInteraction = true;
      options.data.mesa = data.mesa;
      
      console.log('📞 NOTIFICACIÓN DE LLAMADA - VIBRACIÓN PERSISTENTE');
      
    } else {
      // ℹ️ NOTIFICACIÓN GENERAL
      options.title = data.title || options.title;
      options.body = data.body || options.body;
      options.vibrate = [200, 100, 200]; // Vibración ligera
      
      console.log('ℹ️ NOTIFICACIÓN GENERAL - VIBRACIÓN LIGERA');
    }
    
    // Mostrar notificación con configuración optimizada
    event.waitUntil(
      self.registration.showNotification(options.title, options)
        .then(() => {
          console.log('✅ Notificación mostrada exitosamente con vibración');
          
          // Enviar confirmación a todas las pestañas abiertas
          return self.clients.matchAll();
        })
        .then(clients => {
          clients.forEach(client => {
            client.postMessage({
              type: 'PUSH_RECEIVED',
              data: data,
              timestamp: Date.now(),
              success: true
            });
          });
        })
    );
    
  } catch (error) {
    console.error('❌ Error procesando push notification:', error);
    
    // Notificación de fallback con vibración básica
    event.waitUntil(
      self.registration.showNotification('🔔 Nueva Notificación', {
        body: 'Tienes una nueva notificación del restaurante',
        icon: '/static/images/logo-alleria.png',
        vibrate: [500, 200, 500],
        tag: 'fallback-notification'
      })
    );
  }
});

// 👆 MANEJO DE CLICS EN NOTIFICACIONES
self.addEventListener('notificationclick', (event) => {
  console.log('� Click en notificación:', event.notification.tag, event.action);
  
  const notification = event.notification;
  const data = notification.data || {};
  
  // Cerrar la notificación
  notification.close();
  
  // Manejar acciones específicas
  if (event.action === 'dismiss' || event.action === 'close') {
    console.log('✖️ Usuario cerró la notificación');
    return;
  }
  
  // Determinar URL a abrir
  const urlToOpen = data.url || '/cliente';
  
  // Abrir o enfocar ventana de la app
  event.waitUntil(
    self.clients.matchAll({ 
      type: 'window',
      includeUncontrolled: true 
    }).then(clients => {
      console.log('🔍 Buscando ventanas abiertas...', clients.length);
      
      // Buscar si ya hay una ventana abierta con la app
      for (let client of clients) {
        if (client.url.includes('/cliente') && 'focus' in client) {
          console.log('🎯 Enfocando ventana existente:', client.url);
          return client.focus();
        }
      }
      
      // Si no hay ventana abierta, abrir una nueva
      if ('openWindow' in self.clients) {
        console.log('🆕 Abriendo nueva ventana:', urlToOpen);
        return self.clients.openWindow(urlToOpen);
      }
    }).catch(error => {
      console.error('❌ Error manejando click de notificación:', error);
    })
  );
});

// 💬 MANEJAR MENSAJES DESDE LA APLICACIÓN PRINCIPAL
self.addEventListener('message', (event) => {
  console.log('� Mensaje recibido en SW:', event.data);
  
  const { type, data } = event.data || {};
  
  if (type === 'SHOW_NOTIFICATION') {
    // 🔔 Mostrar notificación solicitada por la app principal
    const options = {
      body: data.body || 'Notificación del restaurante',
      icon: '/static/images/logo-alleria.png',
      badge: '/static/images/logo-alleria.png',
      vibrate: data.vibrate || [300, 200, 300],
      tag: data.tag || 'app-notification',
      requireInteraction: data.requireInteraction || false,
      data: data
    };
    
    self.registration.showNotification(data.title || '🍽️ Restaurante', options)
      .then(() => {
        console.log('✅ Notificación desde mensaje mostrada');
        // Responder al cliente que la notificación se mostró
        event.ports[0]?.postMessage({ success: true });
      })
      .catch(error => {
        console.error('❌ Error mostrando notificación desde mensaje:', error);
        event.ports[0]?.postMessage({ success: false, error: error.message });
      });
      
  } else if (type === 'GET_SUBSCRIPTION') {
    // 📱 Enviar información de suscripción actual
    self.registration.pushManager.getSubscription()
      .then(subscription => {
        event.ports[0]?.postMessage({
          type: 'SUBSCRIPTION_INFO',
          subscription: subscription
        });
      })
      .catch(error => {
        console.error('❌ Error obteniendo suscripción:', error);
        event.ports[0]?.postMessage({
          type: 'SUBSCRIPTION_ERROR',
          error: error.message
        });
      });
  }
});

console.log('🚀 Service Worker completo cargado - Notificaciones Push habilitadas');
