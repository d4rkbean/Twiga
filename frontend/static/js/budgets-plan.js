(function () {
  "use strict";

  // Le plan du mois de « L'autre voie » (other_way/budgets/_content.html) : ce que
  // la page calcule pendant qu'on règle les montants, sans requête. La phrase en
  // tête (« Il reste 1 965,60 € à répartir. ») est écrite par le serveur au premier
  // affichage (backend/answers.py, budgets_answer) ; ici elle est recomposée avec
  // les mêmes mots, fournis par le gabarit dans data-config.t.
  //
  // data-config (JSON) :
  //   income        ressources du mois (le montant du Cap, ou la proposition du réglage)
  //   withdrawal    prélèvement sur épargne prévu
  //   amounts       { id de catégorie: montant }
  //   groups        [{ code, ids: [id de catégorie] }]
  //   thresholds    { watch, almost, exceeded } : les seuils des jauges
  //   t             les textes (avec le jeton {amount} / {total}...)
  //   locale        la locale des nombres
  //
  // Chargé avant Alpine (bloc shell_head), qui évalue x-data="twigaBudgetPlan()".
  window.twigaBudgetPlan = function () {
    return {
      income: 0,
      withdrawal: 0,
      step: 10,
      amounts: {},
      groups: [],
      thresholds: { watch: 75, almost: 90, exceeded: 100 },
      t: {},
      locale: "fr-FR",
      initial: "",

      init: function () {
        var config = JSON.parse(this.$el.dataset.config || "{}");
        this.income = Number(config.income) || 0;
        this.withdrawal = Number(config.withdrawal) || 0;
        this.amounts = config.amounts || {};
        this.groups = config.groups || [];
        this.thresholds = config.thresholds || this.thresholds;
        this.t = config.t || {};
        this.locale = config.locale || this.locale;
        this.initial = this.snapshot();
      },

      snapshot: function () {
        return JSON.stringify([this.withdrawal, this.amounts]);
      },

      // « Rien à enregistrer » tant que rien n'a bougé depuis l'affichage.
      get dirty() {
        return this.snapshot() !== this.initial;
      },

      get available() {
        return this.income + (Number(this.withdrawal) || 0);
      },
      get total() {
        var amounts = this.amounts;
        return Object.keys(amounts).reduce(function (sum, id) {
          return sum + (Number(amounts[id]) || 0);
        }, 0);
      },
      get left() {
        return Math.round((this.available - this.total) * 100) / 100;
      },
      get totalPct() {
        return this.available ? (this.total / this.available) * 100 : 0;
      },

      pct: function (id) {
        return this.available ? ((Number(this.amounts[id]) || 0) / this.available) * 100 : 0;
      },
      groupTotal: function (code) {
        var amounts = this.amounts;
        var group = this.groups.filter(function (g) {
          return g.code === code;
        })[0];
        if (!group) return 0;
        return group.ids.reduce(function (sum, id) {
          return sum + (Number(amounts[id]) || 0);
        }, 0);
      },
      groupPct: function (code) {
        return this.available ? (this.groupTotal(code) / this.available) * 100 : 0;
      },

      bump: function (id, direction) {
        var next = (Number(this.amounts[id]) || 0) + direction * this.step;
        this.amounts[id] = Math.max(0, Math.round(next * 100) / 100);
      },
      bumpWithdrawal: function (direction) {
        var next = (Number(this.withdrawal) || 0) + direction * this.step;
        this.withdrawal = Math.max(0, Math.round(next * 100) / 100);
      },

      num: function (text) {
        var n = parseFloat(String(text).replace(/\s/g, "").replace(",", "."));
        return isNaN(n) ? 0 : n;
      },
      fmt2: function (v) {
        return (Number(v) || 0).toLocaleString(this.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      },
      fmt: function (v) {
        return new Intl.NumberFormat(this.locale, { style: "currency", currency: "EUR" })
          .format(Number(v) || 0)
          .replace("-", "−");
      },

      // La phrase de Twiga, recomposée à chaque geste.
      get headline() {
        if (this.available <= 0) return this.t.none;
        if (this.left > 0) return this.t.left.replace("{amount}", this.fmt(this.left));
        if (this.left === 0) return this.t.zero;
        return this.t.over.replace("{amount}", this.fmt(-this.left));
      },
      get sub() {
        if (this.available <= 0) return this.t.subNone.replace("{total}", this.fmt(this.total));
        return this.t.sub.replace("{total}", this.fmt(this.total)).replace("{available}", this.fmt(this.available));
      },

      // Le verdict du total : toujours un mot ET une couleur.
      get verdict() {
        var pct = this.totalPct;
        var th = this.thresholds;
        if (this.available <= 0) return { word: "", tone: "text-secondary" };
        if (pct > th.exceeded) return { word: this.t.exceeded, tone: "text-danger" };
        if (pct > th.almost) return { word: this.t.almost, tone: "text-danger" };
        if (pct >= th.watch) return { word: this.t.watch, tone: "text-warning" };
        return { word: this.t.ok, tone: "text-success" };
      },
    };
  };
})();
