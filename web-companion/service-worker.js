const cacheName = "sudobrain-companion-v1";
const assets = ["./index.html", "./styles.css", "./app.js", "./manifest.webmanifest"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll(assets)));
});

self.addEventListener("fetch", event => {
  if (event.request.url.includes("127.0.0.1:8420")) return;
  event.respondWith(caches.match(event.request).then(response => response || fetch(event.request)));
});
