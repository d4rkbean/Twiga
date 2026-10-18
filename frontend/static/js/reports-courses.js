(function () {
  "use strict";

  // Graphique de l'onglet "Courses" du rapport : barres empilées, un rayon
  // par série, sur la fenêtre glissante de 12 mois. Fichier statique dédié
  // (données lues en data-* sur le <canvas>) plutôt qu'un <script> inline
  // de plus dans reports/_content.html — voir le guide du projet §6.
  //
  // Le contenu du rapport est rechargé par htmx au changement de période :
  // on réinstancie donc le graphique à chaque htmx:afterSwap, en détruisant
  // l'instance précédente (sinon Chart.js garde le canvas occupé et refuse
  // d'en créer un nouveau dessus).
  var chart = null;

  // Palette de données de l'application (--color-chart-1 à 8, voir
  // design-system.css), lisible en clair comme en sombre : ces couleurs
  // distinguent des séries entre elles, elles ne portent pas de sens
  // sémantique (pas de vert = bien / rouge = mal ici) et ne comprennent jamais
  // l'ambre, réservé à l'action principale. Les replis sont les mêmes valeurs.
  var SERIES_FALLBACKS = ["#2563eb", "#0d9488", "#9333ea", "#db2777", "#65a30d", "#ea580c", "#0891b2", "#64748b"];

  function seriesColors() {
    var styles = getComputedStyle(document.documentElement);
    return SERIES_FALLBACKS.map(function (fallback, index) {
      return styles.getPropertyValue("--color-chart-" + (index + 1)).trim() || fallback;
    });
  }

  function parseData(canvas, attribute) {
    try {
      return JSON.parse(canvas.getAttribute(attribute) || "[]");
    } catch (error) {
      return [];
    }
  }

  function render() {
    var canvas = document.getElementById("report-courses-chart");
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (!canvas || typeof Chart === "undefined") return;

    var months = parseData(canvas, "data-months");
    var series = parseData(canvas, "data-series");
    if (!months.length || !series.length) return;

    var colors = seriesColors();
    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: months,
        datasets: series.map(function (entry, index) {
          return {
            label: entry.label,
            data: entry.data,
            backgroundColor: colors[index % colors.length],
            borderWidth: 0,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: {
            stacked: true,
            ticks: {
              callback: function (value) {
                return new Intl.NumberFormat((document.documentElement.dataset.numberLocale || 'fr-FR'), { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
              },
            },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 14, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: function (context) {
                var amount = context.parsed.y || 0;
                return (
                  context.dataset.label +
                  " : " +
                  new Intl.NumberFormat((document.documentElement.dataset.numberLocale || 'fr-FR'), { style: "currency", currency: "EUR" }).format(amount)
                );
              },
            },
          },
        },
      },
    });
  }

  document.addEventListener("DOMContentLoaded", render);
  document.body.addEventListener("htmx:afterSwap", render);
})();
