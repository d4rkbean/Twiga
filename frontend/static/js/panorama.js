(function () {
  "use strict";

  // Le Panorama de « L'autre voie » (other_way/dashboard/_content.html).
  //
  // Les anneaux et les listes sont dessinés par le serveur ; ce fichier ne fait que
  // ce qu'un gabarit ne sait pas faire : la courbe d'évolution sur 12 mois (Chart.js),
  // le diagramme de flux (Sankey), le mois lu sur la courbe, la ligne d'un anneau
  // mise en valeur au clic, et la préférence « Décaler recettes » mémorisée.
  //
  // Les données arrivent en JSON dans data-* de #panorama-data, jamais en script en
  // ligne. Tout est reconstruit à chaque échange HTMX de #dashboard-content, APRÈS
  // le « settle » : HTMX retire alors les attributs width/height que Chart.js vient
  // de poser sur les <canvas> qui portent un id (voir l'ancien dashboard/_content.html).

  var charts = [];
  var observers = [];

  function cssColor(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function palette() {
    return ["#2563eb", "#0d9488", "#9333ea", "#db2777", "#65a30d", "#ea580c", "#0891b2", "#64748b"].map(function (fallback, index) {
      return cssColor("--color-chart-" + (index + 1), fallback);
    });
  }

  function destroyCharts() {
    charts.forEach(function (chart) {
      try {
        chart.destroy();
      } catch (error) {}
    });
    charts = [];
    observers.forEach(function (observer) {
      observer.disconnect();
    });
    observers = [];
  }

  function createChart(canvas, config) {
    var existing = window.Chart.getChart(canvas);
    if (existing) existing.destroy();
    canvas.removeAttribute("style");
    canvas.removeAttribute("width");
    canvas.removeAttribute("height");
    var chart = new window.Chart(canvas, config);
    charts.push(chart);
    // Le conteneur change de taille sans que la fenêtre bouge (panneau qui s'ouvre) :
    // on le surveille nous-mêmes.
    var box = canvas.parentElement;
    if (window.ResizeObserver && box) {
      var observer = new window.ResizeObserver(function () {
        if (window.Chart.getChart(canvas) === chart) chart.resize();
      });
      observer.observe(box);
      observers.push(observer);
    }
    return chart;
  }

  function readJson(root, name) {
    try {
      return JSON.parse(root.dataset[name] || "null");
    } catch (error) {
      return null;
    }
  }

  function numberLocale() {
    return document.documentElement.dataset.numberLocale || "fr-FR";
  }

  function money(value, plus) {
    var text = new Intl.NumberFormat(numberLocale(), { style: "currency", currency: "EUR" }).format(Math.abs(value));
    if (value < 0) return "−" + text;
    return (plus ? "+" : "") + text;
  }

  // --- Évolution sur 12 mois ---------------------------------------------------

  function buildTrend(root) {
    var data = readJson(root, "trend");
    var canvas = document.getElementById("trend-line-chart");
    if (!data || !canvas || !window.Chart) return;

    var colors = palette();
    var colorBorder = cssColor("--color-border", "#e7e2da");
    var colorSecondary = cssColor("--color-secondary", "#585e6a");
    var colorSurface = cssColor("--color-container", "#ffffff");
    var main = document.querySelector("main");
    var mode = (window.Alpine && main && window.Alpine.$data(main).trend) || "both";
    var selected = data.periodIsMonth ? data.labels.length - 1 : null;
    var readout = document.getElementById("trend-readout");
    var chips = Array.prototype.slice.call(document.querySelectorAll("#trend-months [data-month]"));
    var styleSeries = { fill: false, tension: 0.25, borderWidth: 2, pointRadius: 3, pointHoverRadius: 4, pointHitRadius: 14 };
    var expenseSet = Object.assign({ label: data.t.expenses, data: data.expense, borderColor: colors[0], backgroundColor: colors[0], pointBackgroundColor: colors[0] }, styleSeries);
    var incomeSet = Object.assign({ label: data.incomeLabel, data: data.income, borderColor: colors[1], backgroundColor: colors[1], pointBackgroundColor: colors[1] }, styleSeries);
    var sets = { exp: [expenseSet], inc: [incomeSet], both: [expenseSet, incomeSet] };

    function renderReadout() {
      if (!readout) return;
      var income = selected === null ? data.periodIncome : Number(data.income[selected]);
      var expense = selected === null ? data.periodExpense : Number(data.expense[selected]);
      var label = selected === null ? data.periodLabel : data.labels[selected];
      var parts = [];
      if (mode !== "inc") parts.push(data.t.expenses + " " + money(-expense));
      if (mode !== "exp") parts.push(data.t.incomes + " " + money(income, true));
      var current = selected !== null && selected === data.labels.length - 1 && data.periodIsMonth;
      readout.textContent = label + " : " + parts.join(" · ") + (current ? " " + data.t.ongoing : "");
    }

    var markerPlugin = {
      id: "selectedMonth",
      afterDatasetsDraw: function (chart) {
        if (selected === null) return;
        var first = chart.getDatasetMeta(0);
        if (!first || !first.data[selected]) return;
        var x = first.data[selected].x;
        var ctx = chart.ctx;
        ctx.save();
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = colorBorder;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, chart.chartArea.top);
        ctx.lineTo(x, chart.chartArea.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        chart.data.datasets.forEach(function (set, index) {
          var point = chart.getDatasetMeta(index).data[selected];
          if (!point) return;
          ctx.beginPath();
          ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
          ctx.fillStyle = set.borderColor;
          ctx.fill();
          ctx.lineWidth = 2;
          ctx.strokeStyle = colorSurface;
          ctx.stroke();
        });
        ctx.restore();
      },
    };

    var chipsBar = document.getElementById("trend-months");
    function alignChips(chart) {
      if (!chipsBar || !chart.chartArea) return;
      chipsBar.style.marginLeft = chart.chartArea.left + "px";
      chipsBar.style.width = chart.chartArea.right - chart.chartArea.left + "px";
    }

    var chart = createChart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: sets[mode] },
      plugins: [markerPlugin, { id: "alignChips", afterLayout: alignChips }],
      options: {
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: "index", intersect: false },
        onClick: function (event, elements) {
          if (elements.length) select(elements[0].index);
        },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { grid: { display: false }, offset: true, ticks: { display: false } },
          y: {
            beginAtZero: true,
            border: { display: false },
            grid: { color: colorBorder },
            ticks: {
              color: colorSecondary,
              callback: function (value) {
                return value >= 1000 ? (value / 1000).toLocaleString(numberLocale()) + " k" : value;
              },
            },
          },
        },
      },
    });

    function select(index) {
      selected = selected === index ? null : index;
      chips.forEach(function (chip, i) {
        chip.setAttribute("aria-pressed", i === selected ? "true" : "false");
      });
      renderReadout();
      chart.update("none");
    }

    chips.forEach(function (chip, i) {
      chip.setAttribute("aria-pressed", i === selected ? "true" : "false");
      chip.addEventListener("click", function () {
        select(i);
      });
    });

    function setMode(next) {
      mode = next;
      chart.data.datasets = sets[next];
      chart.update();
      renderReadout();
    }
    root.__setTrendMode = setMode;
    alignChips(chart);
    renderReadout();
  }

  // --- Flux financier (mobile) ---------------------------------------------------

  function buildFlow(root) {
    var data = readJson(root, "flow");
    var canvas = document.getElementById("cashflow-sankey-chart");
    if (!data || !canvas || !window.Chart || !window.Chart.registry.controllers.get("sankey")) return;
    var colors = palette();
    var primary = cssColor("--color-primary", "#111827");
    var secondary = cssColor("--color-secondary", "#585e6a");
    var byKey = { total: primary };
    var labels = { total: data.t.total };
    var rows = [];
    data.incomeLabels.forEach(function (label, index) {
      var key = "in:" + label;
      labels[key] = label;
      byKey[key] = colors[index % colors.length];
      rows.push({ from: key, to: "total", flow: data.incomeValues[index] });
    });
    data.expenseLabels.forEach(function (label, index) {
      var key = "out:" + label;
      labels[key] = label;
      byKey[key] = colors[index % colors.length];
      rows.push({ from: "total", to: key, flow: data.expenseValues[index] });
    });
    createChart(canvas, {
      type: "sankey",
      data: {
        datasets: [
          {
            label: data.t.title,
            data: rows,
            labels: labels,
            color: secondary,
            colorMode: "gradient",
            colorFrom: function (ctx) {
              return byKey[ctx.raw.from] || secondary;
            },
            colorTo: function (ctx) {
              return byKey[ctx.raw.to] || secondary;
            },
            nodeLabels: { color: primary },
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: {
              title: function () {
                return "";
              },
              label: function (ctx) {
                var raw = ctx.raw._custom;
                var toTotal = String(raw.to.key) === "total";
                var name = toTotal ? labels[raw.from.key] || raw.from.key : labels[raw.to.key] || raw.to.key;
                return (toTotal ? data.t.income : data.t.expense) + name + " : " + money(raw.flow);
              },
            },
          },
        },
      },
    });
  }

  // --- Anneaux : la ligne choisie ----------------------------------------------

  function wireShares(root) {
    Array.prototype.forEach.call(root.querySelectorAll("[data-share]"), function (card) {
      var rows = Array.prototype.slice.call(card.querySelectorAll("[data-share-row]"));
      var arcs = Array.prototype.slice.call(card.querySelectorAll("[data-arc]"));
      var label = card.querySelector("[data-share-label]");
      var total = card.querySelector("[data-share-total]");
      var percent = card.querySelector("[data-share-percent]");
      var home = { label: label && label.textContent, total: total && total.textContent };

      function paint(index) {
        rows.forEach(function (row, i) {
          row.setAttribute("aria-pressed", i === index ? "true" : "false");
        });
        arcs.forEach(function (arc, i) {
          arc.style.opacity = index === null || i === index ? "1" : "0.28";
        });
        if (index === null) {
          if (label) label.textContent = home.label;
          if (total) total.textContent = home.total;
          if (percent) percent.textContent = "";
        } else {
          var row = rows[index];
          if (label) label.textContent = row.dataset.name;
          if (total) total.textContent = row.dataset.amount;
          if (percent) percent.textContent = row.dataset.percent;
        }
      }

      rows.forEach(function (row, index) {
        // Un second clic sur la ligne choisie la referme : on coupe la requête HTMX
        // avant qu'elle ne parte, et on vide le panneau.
        row.addEventListener(
          "click",
          function (event) {
            if (row.getAttribute("aria-pressed") === "true") {
              event.stopImmediatePropagation();
              paint(null);
              var panel = document.getElementById("category-detail");
              if (panel) panel.innerHTML = "";
              return;
            }
            // Une seule ligne choisie à la fois, dans les deux répartitions.
            Array.prototype.forEach.call(root.querySelectorAll("[data-share]"), function (other) {
              if (other !== card) {
                Array.prototype.forEach.call(other.querySelectorAll("[data-share-row]"), function (r) {
                  r.setAttribute("aria-pressed", "false");
                });
                Array.prototype.forEach.call(other.querySelectorAll("[data-arc]"), function (a) {
                  a.style.opacity = "1";
                });
              }
            });
            paint(index);
          },
          true
        );
      });
    });
  }

  // --- « Décaler recettes » ------------------------------------------------------

  // Le serveur ne connaît ce réglage que par ?shift_income=1 ; il est mémorisé dans
  // le navigateur. Quand les deux divergent (retour sur le Panorama sans le
  // paramètre), un seul rechargement les aligne, sans boucle. Hors d'un mois, le
  // serveur ignore volontairement le réglage : l'écart est alors attendu.
  function reconcileShift(root) {
    if (root.dataset.isMonth !== "true") return;
    var stored = false;
    try {
      stored = localStorage.getItem("twiga_panorama_shift_income") === "1";
    } catch (error) {}
    var current = root.dataset.shift === "true";
    if (stored === current) return;
    var url = new URL(window.location.href);
    if (stored) url.searchParams.set("shift_income", "1");
    else url.searchParams.delete("shift_income");
    var form = document.getElementById("dashboard-filters");
    if (form) {
      new FormData(form).forEach(function (value, key) {
        if (key === "shift_income") return;
        if (value !== "") url.searchParams.set(key, value);
        else url.searchParams.delete(key);
      });
    }
    window.location.replace(url.toString());
  }

  // Le compteur « Compter les N opérations à ranger » : il retourne le champ caché `tri` du
  // formulaire des filtres et lui fait envoyer sa requête (la carte des enveloppes est hors
  // du formulaire : on passe par le champ).
  window.twigaToggleTri = function () {
    var field = document.getElementById("panorama-tri");
    if (!field) return;
    field.value = field.value === "1" ? "0" : "1";
    field.dispatchEvent(new Event("change", { bubbles: true }));
  };

  // Appelée par la case « Décaler recettes » : la préférence reste dans le navigateur.
  window.twigaRememberShift = function (checked) {
    try {
      localStorage.setItem("twiga_panorama_shift_income", checked ? "1" : "0");
    } catch (error) {}
  };

  function init() {
    var root = document.getElementById("panorama-data");
    destroyCharts();
    if (!root) return;
    reconcileShift(root);
    buildTrend(root);
    buildFlow(root);
    wireShares(document.getElementById("dashboard-content") || document);
  }

  // « Fermer » du panneau des opérations : on vide le panneau et on rend aux anneaux
  // leur état de départ.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-close-detail]");
    if (!button) return;
    var panel = document.getElementById("category-detail");
    if (panel) panel.innerHTML = "";
    Array.prototype.forEach.call(document.querySelectorAll("[data-share-row]"), function (row) {
      row.setAttribute("aria-pressed", "false");
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-arc]"), function (arc) {
      arc.style.opacity = "1";
    });
  });

  // Série affichée : les pastilles de la carte (état Alpine sur <main>) préviennent la
  // courbe par un évènement.
  window.addEventListener("panorama-trend", function (event) {
    var root = document.getElementById("panorama-data");
    if (root && root.__setTrendMode) root.__setTrendMode(event.detail);
  });

  document.addEventListener("DOMContentLoaded", function () {
    // Un tour de boucle : la mise en page est calculée avant que Chart.js ne mesure.
    window.requestAnimationFrame(init);
  });
  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.target;
    if (target && (target.id === "dashboard-content" || (target.querySelector && target.querySelector("#panorama-data")))) init();
  });
})();
