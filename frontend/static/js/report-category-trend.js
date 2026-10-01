(function () {
  "use strict";

  // Graphique de la boîte de dialogue "Évolution" d'une catégorie (Rapports
  // → onglets Dépenses/Recettes). Fichier statique dédié (données lues en
  // data-* sur le <canvas>) plutôt qu'un <script> inline de plus — voir
  // CLAUDE.md §6, même approche que reports-courses.js.
  //
  // Le contenu de la boîte de dialogue est rechargé par htmx à chaque
  // catégorie ouverte : on réinstancie donc le graphique à chaque
  // htmx:afterSwap, en détruisant l'instance précédente (sinon Chart.js
  // garde le canvas occupé et refuse d'en créer un nouveau dessus).
  var chart = null;

  function parseData(canvas, attribute) {
    try {
      return JSON.parse(canvas.getAttribute(attribute) || "[]");
    } catch (error) {
      return [];
    }
  }

  function render() {
    var canvas = document.getElementById("category-trend-chart");
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (!canvas || typeof Chart === "undefined") return;

    var labels = parseData(canvas, "data-labels");
    var amounts = parseData(canvas, "data-amounts");
    if (!labels.length || !amounts.length) return;

    // Dernier mois (celui affiché dans le rapport) mis en évidence dans la
    // couleur d'accent de l'app, les précédents dans une teinte neutre —
    // c'est celui qu'on compare, pas juste un mois parmi d'autres.
    var lastIndex = amounts.length - 1;
    var barColors = amounts.map(function (_, index) {
      return index === lastIndex ? "#d4a96a" : "#9ca3af";
    });

    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            data: amounts,
            backgroundColor: barColors,
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { grid: { display: false } },
          y: {
            ticks: {
              callback: function (value) {
                return new Intl.NumberFormat((document.documentElement.dataset.numberLocale || 'fr-FR'), { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
              },
            },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (context) {
                var amount = context.parsed.y || 0;
                return (
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
