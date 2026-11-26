// Barre de chargement fine en haut de l'écran (style NProgress, sans
// dépendance) : suit les requêtes HTMX et les navigations entre pages.
// - Apparaît seulement après 150 ms : une réponse rapide ne fait pas de flash.
// - Avance par à-coups décroissants (jamais jusqu'à 100 % tant que ça charge).
// - Marque la cible HTMX en aria-busy="true" (voir loading-bar.css) pour
//   l'estomper et y faire courir un reflet pendant l'attente.
// - Ignore le polling (hx-trigger="every …") pour ne pas clignoter en boucle.
(function () {
  var SHOW_DELAY = 150;
  var SAFETY_TIMEOUT = 15000;
  var bar = null;
  var pending = 0;
  var showTimer = null;
  var trickleTimer = null;
  var safetyTimer = null;
  var progress = 0;

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.id = "loading-bar";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-hidden", "true");
    bar.innerHTML = "<div class=\"loading-bar__fill\"></div>";
    document.body.appendChild(bar);
    return bar;
  }

  function setProgress(value) {
    progress = value;
    ensureBar().firstChild.style.transform = "scaleX(" + value + ")";
  }

  function trickle() {
    // Chaque pas couvre une fraction du chemin restant, plafonné à 92 %.
    setProgress(Math.min(0.92, progress + (1 - progress) * 0.12));
  }

  function start() {
    pending += 1;
    if (pending > 1) return;
    clearTimeout(safetyTimer);
    safetyTimer = setTimeout(function () { pending = 1; done(); }, SAFETY_TIMEOUT);
    showTimer = setTimeout(function () {
      var el = ensureBar();
      el.classList.remove("is-done");
      el.classList.add("is-active");
      setProgress(0.15);
      trickleTimer = setInterval(trickle, 400);
    }, SHOW_DELAY);
  }

  function done() {
    pending = Math.max(0, pending - 1);
    if (pending > 0) return;
    clearTimeout(showTimer);
    clearTimeout(safetyTimer);
    clearInterval(trickleTimer);
    if (!bar || !bar.classList.contains("is-active")) return;
    setProgress(1);
    bar.classList.add("is-done");
    setTimeout(function () {
      if (pending === 0 && bar) {
        bar.classList.remove("is-active", "is-done");
        setProgress(0);
      }
    }, 300);
  }

  function isPolling(elt) {
    var trigger = elt && elt.getAttribute && elt.getAttribute("hx-trigger");
    return !!trigger && /\bevery\b/.test(trigger);
  }

  document.addEventListener("htmx:beforeRequest", function (event) {
    var detail = event.detail || {};
    if (isPolling(detail.elt)) return;
    detail.elt && (detail.elt.__lbTracked = true);
    if (detail.target && detail.target.setAttribute) detail.target.setAttribute("aria-busy", "true");
    start();
  });

  function finish(event) {
    var detail = event.detail || {};
    if (!detail.elt || !detail.elt.__lbTracked) return;
    detail.elt.__lbTracked = false;
    if (detail.target && detail.target.removeAttribute) detail.target.removeAttribute("aria-busy");
    done();
  }
  document.addEventListener("htmx:afterRequest", finish);

  // Navigation classique : clic sur un lien interne (hors nouvel onglet,
  // téléchargement, ancre ou touche modificatrice). Le minuteur de sécurité
  // referme la barre si le « lien » n'a en fait déclenché qu'un téléchargement.
  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
    if (link.hasAttribute("hx-get") || link.hasAttribute("hx-post")) return;
    if (link.origin !== location.origin) return;
    if (link.pathname === location.pathname && link.search === location.search) return;
    start();
  });

  // Retour arrière (bfcache) : repart d'une barre propre.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) { pending = 1; done(); }
  });
})();
