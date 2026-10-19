// Bulk processing of the other way (other_way/backlog/*).
//
// One Alpine component on <main>, never swapped: the filters, the lines left
// aside (`excluded`), the selection of the « Choisir les lignes soi-même » mode,
// the open line, the category chosen for the selection. Only #backlog-list is
// replaced by htmx, with a few out-of-band fragments (the sentence, the counters,
// the summary) that the server renders from the same filters.
//
// Every request carries the filters through the hidden form #backlog-form, whose
// fields are bound to this state: the server stays stateless, and a reload with
// ?search=...&suggestion_filter=... lands on the same view.
//
// The lot is the set of operations whose suggestion is sure (the server says
// which: `lotIds`). « Tout ranger » files it without the lines left aside;
// touching a line leaves it aside, it stays pending (it comes back as a
// question in La Savane).
document.addEventListener("alpine:init", function () {
  Alpine.data("masseBoard", function (init) {
    return {
      q: init.q,
      conf: init.conf,
      acc: init.acc,
      cat: init.cat,
      group: init.group,
      page: init.page,
      labels: init.labels,
      lotIds: init.lotIds,
      shownIds: init.shownIds,
      excluded: [],
      selected: [],
      mode: "lot",
      adjust: false,
      openRow: null,
      pick: null,
      bcat: null,
      pay: "",
      askReject: false,
      askApply: false,

      get lotCount() {
        var self = this;
        return this.lotIds.filter(function (id) { return self.excluded.indexOf(id) < 0; }).length;
      },
      get nFilters() {
        return (this.q.trim() ? 1 : 0) + (this.conf !== "sure" ? 1 : 0) + (this.acc ? 1 : 0) + (this.cat ? 1 : 0) + (this.group ? 1 : 0);
      },
      get summary() {
        return (
          this.labels.categoryWord + " " + (this.bcat ? this.bcat.path : this.labels.proposed) +
          " · " + this.labels.paymentWord + " " + (this.pay || this.labels.none)
        );
      },
      get allSelected() {
        var self = this;
        return this.shownIds.length > 0 && this.shownIds.every(function (id) { return self.selected.indexOf(id) >= 0; });
      },

      // --- Requests ---------------------------------------------------------
      refresh: function () {
        var self = this;
        this.$nextTick(function () { htmx.trigger(self.$refs.form, "refresh"); });
      },
      filterChanged: function () {
        this.page = 1;
        this.askReject = false;
        this.refresh();
      },
      setConf: function (value) { this.conf = value; this.filterChanged(); },
      setAcc: function () { this.filterChanged(); },
      setCat: function () { this.filterChanged(); },
      reset: function () {
        this.q = ""; this.conf = "sure"; this.acc = ""; this.cat = ""; this.group = false;
        this.filterChanged();
      },
      toggleGroup: function () {
        this.group = !this.group;
        this.selected = [];
        this.filterChanged();
      },
      goTo: function (page) {
        this.page = page;
        this.refresh();
      },
      post: function (url, values) {
        var self = this;
        this.$nextTick(function () {
          htmx.ajax("POST", url, { source: self.$refs.form, target: "#backlog-list", swap: "innerHTML", values: values });
        });
      },

      // --- The lot ----------------------------------------------------------
      ids: function (raw) {
        return raw ? raw.split(",").filter(Boolean).map(Number) : [];
      },
      inLot: function (raw) {
        var self = this;
        var ids = this.ids(raw);
        return ids.length > 0 && ids.every(function (id) {
          return self.lotIds.indexOf(id) >= 0 && self.excluded.indexOf(id) < 0;
        });
      },
      sure: function (raw) {
        var self = this;
        return this.ids(raw).every(function (id) { return self.lotIds.indexOf(id) >= 0; });
      },
      toggleLot: function (raw) {
        var ids = this.ids(raw);
        if (this.inLot(raw)) {
          this.excluded = this.excluded.concat(ids.filter(function (id) { return this.excluded.indexOf(id) < 0; }, this));
        } else {
          this.excluded = this.excluded.filter(function (id) { return ids.indexOf(id) < 0; });
        }
      },
      // The ids of a group that are still in the lot.
      groupLot: function (raw) {
        var self = this;
        return this.ids(raw).filter(function (id) { return self.excluded.indexOf(id) < 0; });
      },
      groupCount: function (raw) {
        return this.groupLot(raw).length;
      },
      fileAll: function () {
        var self = this;
        var ids = this.lotIds.filter(function (id) { return self.excluded.indexOf(id) < 0; });
        if (ids.length) this.post("/backlog/validate", { ids: ids.join(","), category_id: "" });
      },
      fileGroup: function (raw) {
        var ids = this.groupLot(raw);
        if (ids.length) this.post("/backlog/validate", { ids: ids.join(","), category_id: "" });
      },
      fileRow: function (raw) {
        this.post("/backlog/validate", { ids: raw, category_id: "" });
      },
      rejectRow: function (raw) {
        this.post("/backlog/reject", { ids: raw });
      },
      payRow: function (raw, code) {
        this.post("/backlog/bulk-apply", {
          selected_ids: this.ids(raw),
          apply_category_id: "",
          apply_payment_method: code,
        });
      },
      rejectUnsure: function () {
        this.askReject = false;
        this.post("/backlog/bulk-reject", { max_confidence: 70 });
      },

      // Told by the fragment the server sends after each swap: what is drawn,
      // what is in the filtered view, and which of it is the lot.
      sync: function (shownIds, visibleIds, lotIds) {
        this.shownIds = shownIds;
        this.lotIds = lotIds;
        this.excluded = this.excluded.filter(function (id) { return visibleIds.indexOf(id) >= 0; });
        this.selected = this.selected.filter(function (id) { return visibleIds.indexOf(id) >= 0; });
        this.openRow = null;
      },

      // --- Selection by hand -----------------------------------------------
      startSelect: function () {
        this.mode = "select";
        this.adjust = false;
        this.openRow = null;
      },
      endSelect: function () {
        this.mode = "lot";
        this.selected = [];
        this.bcat = null;
        this.pay = "";
        this.askApply = false;
      },
      rowSelected: function (raw) {
        var self = this;
        return this.ids(raw).every(function (id) { return self.selected.indexOf(id) >= 0; });
      },
      toggleRow: function (raw) {
        var ids = this.ids(raw);
        this.selected = this.rowSelected(raw)
          ? this.selected.filter(function (id) { return ids.indexOf(id) < 0; })
          : this.selected.concat(ids.filter(function (id) { return this.selected.indexOf(id) < 0; }, this));
      },
      toggleAll: function () {
        var shown = this.shownIds;
        this.selected = this.allSelected
          ? this.selected.filter(function (id) { return shown.indexOf(id) < 0; })
          : this.selected.concat(shown.filter(function (id) { return this.selected.indexOf(id) < 0; }, this));
      },
      applied: function () {
        this.bcat = null;
        this.pay = "";
        this.askApply = false;
        this.selected = [];
      },

      // --- Category picker ---------------------------------------------------
      openPick: function (ids, title) { this.pick = { ids: ids, title: title }; },
      openPickSelection: function (title) { this.pick = { ids: null, title: title }; },
      closePick: function () { this.pick = null; },
      choose: function (id, path) {
        var pick = this.pick;
        this.pick = null;
        if (pick && pick.ids) {
          this.post("/backlog/validate", { ids: pick.ids, category_id: id });
        } else {
          this.bcat = { id: id, path: path };
        }
      },
      setPay: function (value) { this.pay = value; },
    };
  });
});
