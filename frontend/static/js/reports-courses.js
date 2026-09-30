(function () {
  "use strict";

  // Graphique de l'onglet "Courses" du rapport : barres empilées, un rayon
  // par série, sur la fenêtre glissante de 12 mois. Fichier statique dédié
  // (données lues en data-* sur le <canvas>) plutôt qu'un <script> inline
  // de plus dans reports/_content.html.
  //
  // Le contenu du rapport est rechargé par htmx au changement de période :
  // on réinstancie donc le graphique à chaque htmx:afterSwap, en détruisant
  // l'instance précédente (sinon Chart.js garde le canvas occupé et refuse
  // d'en créer un nouveau dessus).
  var chart = null;

  // Palette lisible en clair comme en sombre, volontairement fixe : ces
  // couleurs distinguent des séries entre elles, elles ne portent pas de
  // sens sémantique (pas de vert = bien / rouge = mal ici).
  var SERIES_COLORS = [
    "#d4a96a",
    "#5b8fa8",
    "#a8785b",
    "#7fa87f",
    "#b07f9e",
    "#8a86b8",
    "#9a9a9a",
  ];

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

    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: months,
        datasets: series.map(function (entry, index) {
          return {
            label: entry.label,
            data: entry.data,
            backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length],
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
                return value.toLocaleString("fr-FR") + " €";
              },
            },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: function (context) {
                var amount = context.parsed.y || 0;
                return (
                  context.dataset.label +
                  " : " +
                  amount.toLocaleString("fr-FR", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  }) +
                  " €"
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
