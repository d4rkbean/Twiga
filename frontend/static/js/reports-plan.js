(function () {
  "use strict";

  // Rapports de « L'autre voie » (other_way/reports/_content.html).
  //
  // Les neuf réponses sont déjà dans la page : ce fichier ne fait que ce qu'un gabarit
  // ne sait pas faire : la courbe du patrimoine (Chart.js, par compte et en total), la
  // ligne mise en valeur quand la feuille d'une catégorie s'ouvre, la fermeture de cette
  // feuille, et la préférence « Décaler les recettes » mémorisée dans le navigateur.
  // Les données de la courbe arrivent en JSON dans data-networth du <canvas>.

  var chart = null;

  function cssColor(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function buildNetWorth() {
    if (chart) {
      try {
        chart.destroy();
      } catch (error) {}
      chart = null;
    }
    var canvas = document.getElementById("report-networth-chart");
    if (!canvas || !window.Chart) return;
    var data;
    try {
      data = JSON.parse(canvas.dataset.networth || "null");
    } catch (error) {
      return;
    }
    if (!data || !data.labels.length) return;

    var locale = document.documentElement.dataset.numberLocale || "fr-FR";
    var spanDays = (new Date(data.labels[data.labels.length - 1]) - new Date(data.labels[0])) / 86400000;
    var money = new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" });
    var compact = function (value) {
      return Math.abs(value) >= 1000 ? (value / 1000).toLocaleString(locale) + " k" : value;
    };
    var palette = ["#2563eb", "#0d9488", "#9333ea", "#db2777", "#65a30d", "#ea580c", "#0891b2", "#64748b"].map(function (fallback, index) {
      return cssColor("--color-chart-" + (index + 1), fallback);
    });
    var primary = cssColor("--color-primary", "#111827");
    var secondary = cssColor("--color-secondary", "#585e6a");
    var border = cssColor("--color-border", "#e7e2da");

    var datasets = data.accountIds.map(function (id, index) {
      return {
        label: data.accountNames[index],
        data: data.byAccount.map(function (point) {
          return point[id];
        }),
        borderColor: palette[index % palette.length],
        backgroundColor: palette[index % palette.length],
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 1.5,
      };
    });
    datasets.push({
      label: data.totalLabel,
      data: data.totals,
      borderColor: primary,
      backgroundColor: primary,
      tension: 0.2,
      pointRadius: 0,
      borderWidth: 3,
    });

    canvas.removeAttribute("style");
    canvas.removeAttribute("width");
    canvas.removeAttribute("height");
    chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: datasets },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: secondary,
              maxRotation: 0,
              maxTicksLimit: 8,
              callback: function (value) {
                // Sur un mois, les jours ; au-delà, les mois.
                return new Date(this.getLabelForValue(value)).toLocaleDateString(
                  locale,
                  spanDays <= 92 ? { day: "numeric", month: "short" } : { month: "short", year: "2-digit" }
                );
              },
            },
          },
          y: { grid: { color: border }, ticks: { color: secondary, callback: compact } },
        },
        plugins: {
          legend: { display: true, labels: { usePointStyle: true, boxWidth: 10, boxHeight: 10, padding: 16, color: secondary } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + " : " + money.format(ctx.raw);
              },
            },
          },
        },
      },
    });
  }

  // Le patrimoine n'est dessiné que quand sa question est affichée : un <canvas>
  // caché n'a pas de taille, Chart.js le mesure alors à zéro.
  function rebuildSoon() {
    window.requestAnimationFrame(buildNetWorth);
  }

  // « Décaler les recettes » : le serveur ne connaît le réglage que par
  // ?shift_income=1. Quand le navigateur se souvient d'un autre choix (retour sur la
  // page sans le paramètre), un seul rechargement les aligne, sans boucle.
  function reconcileShift() {
    var marker = document.getElementById("reports-data");
    if (!marker) return;
    var stored = false;
    try {
      stored = localStorage.getItem("twiga_reports_shift_income") === "1";
    } catch (error) {}
    var current = marker.dataset.shift === "true";
    if (stored === current) return;
    var url = new URL(window.location.href);
    if (stored) url.searchParams.set("shift_income", "1");
    else url.searchParams.delete("shift_income");
    window.location.replace(url.toString());
  }

  window.twigaRememberReportShift = function (checked) {
    try {
      localStorage.setItem("twiga_reports_shift_income", checked ? "1" : "0");
    } catch (error) {}
  };

  // La feuille d'une catégorie : la ligne ouverte est mise en valeur, une autre la
  // remplace, « Fermer » (ou le voile, sur mobile) la vide.
  document.addEventListener("click", function (event) {
    var closer = event.target.closest && event.target.closest("[data-close-sheet]");
    if (closer) {
      var sheet = document.getElementById("report-sheet");
      if (sheet) sheet.innerHTML = "";
      Array.prototype.forEach.call(document.querySelectorAll("[data-sheet-row]"), function (row) {
        row.setAttribute("aria-pressed", "false");
      });
      return;
    }
    var row = event.target.closest && event.target.closest("[data-sheet-row]");
    if (!row) return;
    Array.prototype.forEach.call(document.querySelectorAll("[data-sheet-row]"), function (other) {
      other.setAttribute("aria-pressed", other === row ? "true" : "false");
    });
  });

  function init() {
    reconcileShift();
    rebuildSoon();
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.target;
    if (target && target.id === "reports-content") init();
  });
})();
