const CACHE = 'zingaroebike-v1';
const ASSETS = [
  '/mappa',
  '/static/gpx/lungomare.gpx',
  '/static/gpx/zingaro.gpx',
  '/static/gpx/costa-integrale.gpx',
  '/static/gpx/segesta.gpx',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700;800&display=swap',
];

// Installa e metti in cache
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(ASSETS))
  );
});

// Servi dalla cache se offline
self.addEventListener('fetch', e => {
  // Cache tiles OpenStreetMap
  if (e.request.url.includes('tile.openstreetmap.org')) {
    e.respondWith(
      caches.open(CACHE + '-tiles').then(cache =>
        cache.match(e.request).then(cached => {
          if (cached) return cached;
          return fetch(e.request).then(res => {
            cache.put(e.request, res.clone());
            return res;
          }).catch(() => cached);
        })
      )
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
