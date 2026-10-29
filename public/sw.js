// TRAIN LIVE service worker：讓沒有網路時也能打開網頁
// - 網頁本身（HTML、CSS、JS）：先抓最新的，抓不到才用存起來的（三個檔案要同一版，不能混用新舊）
// - 字型、圖示：用存起來的，背景再更新
// - /api/：不經過這裡（時刻表資料由網頁自己存在瀏覽器裡）
const CACHE = 'train-live-v2';
const SHELL = ['/style.css', '/stations.js', '/app.js'];
const PRECACHE = ['/', ...SHELL, '/manifest.json', '/icon.png', '/fonts/barlow-sc-500.woff', '/fonts/barlow-sc-600.woff'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put('/', copy)); return res; })
        .catch(() => caches.match('/'))
    );
    return;
  }

  if (SHELL.includes(url.pathname)) {
    event.respondWith(
      fetch(req)
        .then((res) => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copy)); } return res; })
        .catch(() => caches.match(url.pathname))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
