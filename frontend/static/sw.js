const CACHE_NAME = "finance-dashboard-static-v3";

// Uniquement les assets statiques (JS, CSS, icônes, manifest) : les données
// dynamiques (transactions, soldes, dashboard...) ne sont jamais mises en
// cache ici et continuent de passer par le réseau / l'API.
const PRECACHE_ASSETS = [
  "/static/vendor/htmx.min.js",
  "/static/vendor/tailwind.min.css",
  "/static/vendor/chart.min.js",
  "/static/css/design-system.css",
  "/static/js/tour.js",
  "/static/js/inbox-shortcuts.js",
  "/static/js/transactions-selection.js",
  "/static/js/htmx-confirm.js",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Ne touche qu'aux requêtes GET vers les assets statiques ; toute autre
  // requête (pages, API) passe directement au réseau, sans passer par le
  // cache, pour ne jamais servir de données périmées hors-ligne.
  if (request.method !== "GET" || !url.pathname.startsWith("/static/")) {
    return;
  }

  // Réseau d'abord, cache en secours (et non l'inverse) : un asset statique
  // mis en cache une fois pour l'usage hors-ligne ne doit jamais empêcher de
  // voir une mise à jour du CSS/JS tant que le réseau est disponible. Avec
  // "cache d'abord", un fichier mis en cache au tout premier chargement de
  // l'app restait servi indéfiniment, même après un redéploiement du
  // serveur — c'était le bug réel derrière "le mode sombre ne fait rien".
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
