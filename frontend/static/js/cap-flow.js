(function () {
  "use strict";

  // Le rituel du Cap de « L'autre voie » (other_way/cap/_step1_bilan.html et
  // _step2_fixer.html).
  //
  // Six étapes pour l'ordinateur (Bilan, Un mot, Ressources, Les piliers, Épargne,
  // Intention), onze gestes pour le pouce : sur mobile chaque question et chaque
  // pilier a son écran. Ce sont les mêmes onze « sous-étapes » ; l'ordinateur en
  // montre un groupe à la fois, le mobile une seule. Elles vivent TOUTES dans le
  // navigateur, à l'intérieur des trois échanges du serveur :
  //   POST /cap/step2  fin du bilan : le serveur renvoie les sous-étapes 5 à 10
  //   POST /cap/save   fin du plan  : le serveur enregistre et confirme
  //   POST /cap/step1  retour au bilan (la frise, « Précédent » depuis les ressources)
  //
  // data-config (JSON, posé sur l'élément x-data) :
  //   mode         "review" (bilan et un mot : sous-étapes 0 à 4) ou "plan" (5 à 10)
  //   first        premier Cap : pas de bilan, les étapes 1 et 2 sont ignorées
  //   income, withdrawal, goal, imprevu   les montants du plan
  //   groups       { essentiel|choix: [{ id, amount, plan, spent }] } par catégorie
  //   previous     { essentiel|choix|imprevu: { spent, pending } } le mois écoulé
  //   planned      { essentiel|choix|imprevu } ce qui était fixé le mois écoulé
  //   thresholds   { watch, almost, exceeded }
  //   month        { current, previous } noms de mois ("octobre", "septembre")
  //   t            les textes, avec les jetons {amount}, {pillar}, {percent}...
  //   locale       la locale des nombres
  //
  // Chargé avant Alpine (bloc shell_head), qui évalue x-data="twigaCapFlow()".

  var GROUPS = [[0], [1, 2, 3, 4], [5], [6, 7, 8], [9], [10]];

  function groupOf(step) {
    for (var g = 0; g < GROUPS.length; g++) {
      if (GROUPS[g].indexOf(step) !== -1) return g;
    }
    return 0;
  }

  window.twigaCapFlow = function () {
    return {
      mode: "review",
      first: false,
      step: 0,
      max: 0,
      desktop: false,
      income: 0,
      withdrawal: 0,
      goal: 0,
      imprevu: 0,
      imprevuPlan: 0,
      intent: "",
      groups: { essentiel: [], choix: [] },
      previous: {},
      planned: {},
      thresholds: { watch: 75, almost: 90, exceeded: 100 },
      month: { current: "", previous: "" },
      t: {},
      locale: "fr-FR",
      open: {},
      sourcesOpen: false,
      stepsSheet: false,
      answers: {},

      init: function () {
        var config = JSON.parse(this.$el.dataset.config || "{}");
        var self = this;
        this.t = JSON.parse(this.$el.dataset.texts || "{}");
        Object.keys(config).forEach(function (key) {
          self[key] = config[key];
        });
        this.imprevuPlan = this.imprevu;
        this.step = this.firstStep;
        this.max = this.step;
        var query = window.matchMedia("(min-width: 1024px)");
        this.desktop = query.matches;
        var update = function (event) {
          self.desktop = event.matches;
        };
        if (query.addEventListener) query.addEventListener("change", update);
        else if (query.addListener) query.addListener(update);
        this.groupsBase = JSON.stringify(this.groups);
      },

      // --- Où l'on est ---------------------------------------------------------

      get firstStep() {
        if (this.mode === "plan") return 5;
        return 0;
      },
      get lastStep() {
        return this.mode === "plan" ? 10 : 4;
      },
      get group() {
        return groupOf(this.step);
      },
      get lastGroup() {
        return groupOf(this.lastStep);
      },
      get firstGroup() {
        return groupOf(this.firstStep);
      },
      get isLast() {
        return this.desktop ? this.group === this.lastGroup : this.step === this.lastStep;
      },
      get isFirst() {
        return this.desktop ? this.group === this.firstGroup : this.step === this.firstStep;
      },

      // Un panneau est visible quand sa sous-étape est celle d'ici (mobile), ou fait
      // partie du groupe affiché (ordinateur).
      visible: function (k) {
        return this.desktop ? groupOf(k) === this.group : k === this.step;
      },
      showGroup: function (g) {
        return this.group === g;
      },

      next: function () {
        if (this.isLast) {
          this.$refs.flow.requestSubmit();
          return;
        }
        var target = this.desktop ? GROUPS[this.group + 1][0] : this.step + 1;
        this.goStep(target);
      },
      back: function () {
        if (this.isFirst) return;
        var target = this.desktop ? GROUPS[this.group - 1][0] : this.step - 1;
        this.goStep(target);
      },
      goStep: function (k) {
        this.step = k;
        this.max = Math.max(this.max, k);
        this.stepsSheet = false;
        this.$nextTick(function () {
          window.scrollTo({ top: 0 });
        });
      },
      // La frise (ordinateur) : on revient sur une étape déjà vue.
      canGoGroup: function (g) {
        return g >= this.firstGroup && GROUPS[g][0] <= this.max && g <= this.lastGroup;
      },
      goGroup: function (g) {
        if (this.canGoGroup(g)) this.goStep(GROUPS[g][0]);
      },
      groupState: function (g) {
        if (g === this.group) return "current";
        // Avant la seconde moitié : « ignorée » au premier Cap, sinon déjà vue.
        if (g < this.firstGroup) return this.first ? "skipped" : "seen";
        return GROUPS[g][0] <= this.max ? "seen" : "todo";
      },
      stepState: function (k) {
        if (k === this.step) return "current";
        return k <= this.max ? "seen" : "todo";
      },

      get total() {
        return this.lastStep - this.firstStep + 1;
      },
      get counter() {
        return this.step - this.firstStep + 1 + " / " + this.total;
      },
      get progress() {
        return ((this.step - this.firstStep + 1) / this.total) * 100;
      },

      get nextLabel() {
        if (this.isLast) return this.mode === "plan" ? this.t.fix : this.t.next;
        if (!this.desktop && this.mode === "plan") {
          var code = this.step === 6 ? "essentiel" : this.step === 7 ? "choix" : this.step === 8 ? "imprevu" : "";
          if (code) {
            var amount = this.pillarAmount(code);
            return amount === this.planned[code]
              ? this.t.keep.replace("{amount}", this.m(amount))
              : this.t.set.replace("{amount}", this.m(amount));
          }
        }
        return this.t.next;
      },

      // --- Les montants ---------------------------------------------------------

      num: function (text) {
        var n = parseFloat(String(text).replace(/[\s  €]/g, "").replace(",", "."));
        return isNaN(n) ? 0 : Math.abs(n);
      },
      round: function (v) {
        return Math.round((Number(v) || 0) * 100) / 100;
      },
      fmt2: function (v) {
        return (Number(v) || 0).toLocaleString(this.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      },
      fmt: function (v) {
        return new Intl.NumberFormat(this.locale, { style: "currency", currency: "EUR" })
          .format(Number(v) || 0)
          .replace("-", "−");
      },
      signed: function (v) {
        return (v > 0 ? "+" : "") + this.fmt(v);
      },
      // Un montant rond s'écrit sans centimes (« 2 300 € »), les autres avec.
      m: function (v) {
        var n = this.round(v);
        if (Math.abs(n - Math.round(n)) < 0.005) {
          return new Intl.NumberFormat(this.locale, { style: "currency", currency: "EUR", maximumFractionDigits: 0 })
            .format(n)
            .replace("-", "−");
        }
        return this.fmt(n);
      },
      pc: function (v) {
        return Math.round(v) + " %";
      },

      pillarAmount: function (code) {
        if (code === "imprevu") return this.round(this.imprevu);
        var rows = this.groups[code] || [];
        return this.round(
          rows.reduce(function (sum, row) {
            return sum + (Number(row.amount) || 0);
          }, 0)
        );
      },
      get catsTotal() {
        return this.pillarAmount("essentiel") + this.pillarAmount("choix");
      },
      get spend() {
        return this.catsTotal + (Number(this.imprevu) || 0);
      },
      get savings() {
        return this.round(this.income - this.spend);
      },
      // La trésorerie du mois, prélèvement compris : c'est elle qui dit si le plan tient.
      get covered() {
        return this.round(this.income + (Number(this.withdrawal) || 0) - this.spend);
      },

      // Répartir l'enveloppe d'un pilier entre ses catégories, au prorata des montants
      // actuels ; la dernière reçoit le reliquat pour que la somme tombe EXACTEMENT sur
      // la cible.
      spread: function (code, target) {
        var rows = this.groups[code];
        if (!rows || !rows.length) return;
        var total = this.pillarAmount(code);
        var rest = Math.round(Math.max(0, target) * 100);
        rows.forEach(function (row, i) {
          if (i === rows.length - 1) {
            row.amount = Math.max(0, rest) / 100;
            return;
          }
          var share = total > 0 ? (Number(row.amount) || 0) / total : 1 / rows.length;
          var cents = Math.round(Math.max(0, target) * 100 * share);
          row.amount = cents / 100;
          rest -= cents;
        });
      },
      bumpPillar: function (code, delta) {
        if (code === "imprevu") {
          this.imprevu = Math.max(0, this.round(this.imprevu + delta));
          return;
        }
        this.spread(code, this.pillarAmount(code) + delta);
      },
      setPillar: function (code, value) {
        if (code === "imprevu") this.imprevu = Math.max(0, this.round(value));
        else this.spread(code, value);
      },
      bumpCategory: function (row, delta) {
        row.amount = Math.max(0, this.round((Number(row.amount) || 0) + delta));
      },
      resetPillar: function (code) {
        if (code === "imprevu") {
          this.imprevu = this.imprevuPlan;
          return;
        }
        this.groups[code].forEach(function (row) {
          row.amount = row.plan;
        });
      },
      // « Partir de » : le plan du mois écoulé, ou ce que ce mois a réellement coûté
      // (arrondi à la dizaine supérieure).
      startFrom: function (kind) {
        var self = this;
        ["essentiel", "choix"].forEach(function (code) {
          self.groups[code].forEach(function (row) {
            row.amount = kind === "plan" ? row.plan : Math.ceil((Number(row.spent) || 0) / 10) * 10;
          });
        });
        this.base = kind;
      },
      base: "plan",
      toggleTransfer: function (checked, amount) {
        this.income = this.round(Number(this.income) + (checked ? amount : -amount));
      },

      // --- Verdicts : toujours un mot ET une couleur -----------------------------

      verdictOf: function (pct) {
        var th = this.thresholds;
        if (pct > th.exceeded) return { word: this.t.exceeded, text: "text-danger", rank: 3 };
        if (pct > th.almost) return { word: this.t.almost, text: "text-danger", rank: 2 };
        if (pct >= th.watch) return { word: this.t.watch, text: "text-warning", rank: 1 };
        return { word: this.t.ok, text: "text-success", rank: 0 };
      },
      // Le mois écoulé rapporté au montant choisi : « 59 % de ce montant ».
      pillarPct: function (code) {
        var amount = this.pillarAmount(code);
        var past = this.previous[code] || { spent: 0, pending: 0 };
        var cost = (Number(past.spent) || 0) + (Number(past.pending) || 0);
        return amount ? (cost / amount) * 100 : cost ? 999 : 0;
      },
      pillarVerdict: function (code) {
        return this.verdictOf(this.pillarPct(code));
      },
      categoryPct: function (row) {
        var amount = Number(row.amount) || 0;
        return amount ? ((Number(row.spent) || 0) / amount) * 100 : row.spent > 0 ? 999 : 0;
      },
      categoryVerdict: function (row) {
        return this.verdictOf(this.categoryPct(row));
      },

      // --- La phrase de Twiga -----------------------------------------------------

      get answer() {
        if (this.mode === "review") {
          return this.desktop ? this.answers.group[this.group] : this.answers.step[this.step];
        }
        var g = this.desktop ? this.group : null;
        var k = this.desktop ? GROUPS[this.group][0] : this.step;
        if (k === 5) {
          if (this.first) return this.t.welcome;
          return this.income > 0
            ? this.t.incomeAnswer.replace("{amount}", this.m(this.income))
            : this.t.incomeNone;
        }
        if (k >= 6 && k <= 8 && !this.desktop) {
          var code = k === 6 ? "essentiel" : k === 7 ? "choix" : "imprevu";
          var pillar = this.pillarVerdict(code);
          return this.t.pillar
            .replace("{pillar}", this.t.names[code])
            .replace("{amount}", this.m(this.pillarAmount(code)))
            .replace("{feeling}", this.t.feelings[pillar.rank]);
        }
        if (k >= 6 && k <= 8 && this.desktop) {
          return this.savings >= 0
            ? this.t.piles.replace("{amount}", this.fmt(this.savings))
            : this.t.pilesOver.replace("{amount}", this.fmt(-this.savings));
        }
        if (k === 9) {
          if (this.covered < 0) {
            return this.t.savOver.replace("{amount}", this.fmt(-this.covered)).replace(
              "{withdrawal}",
              this.withdrawal > 0 ? this.t.withWithdrawal : ""
            );
          }
          if (this.savings < 0) return this.t.savDeficit.replace("{amount}", this.fmt(-this.savings));
          return this.t.savLeft.replace("{amount}", this.fmt(this.savings));
        }
        return this.t.intentAnswer;
      },
      get detail() {
        if (this.mode === "review") {
          return this.desktop ? this.answers.groupDetail[this.group] : this.answers.stepDetail[this.step];
        }
        var k = this.desktop ? GROUPS[this.group][0] : this.step;
        if (k === 5) {
          if (this.first) return this.t.welcomeDetail;
          return this.income > 0 ? this.t.incomeDetail : this.t.incomeNoneDetail;
        }
        if (k >= 6 && k <= 8 && !this.desktop) {
          var code = k === 6 ? "essentiel" : k === 7 ? "choix" : "imprevu";
          return this.t.pillarDetail.replace("{percent}", this.pc(this.pillarPct(code)));
        }
        if (k >= 6 && k <= 8) {
          return this.t.pilesDetail
            .replace("{essentiel}", this.m(this.pillarAmount("essentiel")))
            .replace("{choix}", this.m(this.pillarAmount("choix")))
            .replace("{imprevu}", this.m(this.imprevu));
        }
        if (k === 9) {
          return this.withdrawal > 0 ? this.t.savWith.replace("{amount}", this.m(this.withdrawal)) : this.t.savAsk;
        }
        return this.t.intentDetail;
      },

      // --- Le panneau « en direct » -------------------------------------------------

      get scale() {
        return Math.max(this.income, this.spend) || 1;
      },
      share: function (value) {
        return (Math.max(0, value) / this.scale) * 100;
      },
      get liveWord() {
        if (this.covered < 0) return { word: this.t.liveOver, text: "text-danger" };
        if (this.savings < 0) return { word: this.t.liveCovered, text: "text-info" };
        return { word: this.t.liveOk, text: "text-success" };
      },
      get alert() {
        if (this.covered < 0) return { text: this.t.alertOver + (this.withdrawal > 0 ? " " + this.t.alertWithdrawal : ""), kind: "danger" };
        if (this.savings < 0) return { text: this.t.alertCovered, kind: "neutral" };
        return null;
      },
    };
  };
})();
