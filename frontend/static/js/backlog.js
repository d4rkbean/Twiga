// Bulk processing screen (backlog/index.html).
//
// The state of the screen lives here, in one Alpine component that is never
// swapped: filters, selection, the category and payment chosen for the
// selection, the open menus. Only the list (#backlog-list) is replaced by
// htmx, together with a few out-of-band fragments (counters, last message)
// that the server renders from the same filters.
//
// Every request carries the filters through the hidden form #backlog-form,
// whose fields are bound to this state: the server stays stateless and a
// reload with ?search=...&suggestion_filter=... lands on the same view.
document.addEventListener("alpine:init", function () {
  Alpine.data("backlogBoard", function (init) {
    return {
      q: init.q,
      conf: init.conf,
      acc: init.acc,
      cat: init.cat,
      group: init.group,
      limit: init.limit,
      step: init.step,
      labels: init.labels,
      shownIds: init.shownIds,
      selected: [],
      menu: "",
      filtersOpen: false,
      pick: null,
      bcat: null,
      pay: "",
      payOpen: false,

      get accLabel() {
        return (this.acc && this.labels.acc[this.acc]) || this.labels.allAccounts;
      },
      get catLabel() {
        return (this.cat && this.labels.cat[this.cat]) || this.labels.allCategories;
      },
      get nFilters() {
        return (this.q.trim() ? 1 : 0) + (this.conf !== "all" ? 1 : 0) + (this.acc ? 1 : 0) + (this.cat ? 1 : 0);
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

      // Ask the server for the list again, once the hidden fields have caught up.
      refresh: function () {
        var self = this;
        this.$nextTick(function () { htmx.trigger(self.$refs.form, "refresh"); });
      },
      filterChanged: function () {
        this.limit = this.step;
        this.menu = "";
        this.refresh();
      },
      setConf: function (value) { this.conf = value; this.filterChanged(); },
      setAcc: function (value) { this.acc = value; this.filterChanged(); },
      setCat: function (value) { this.cat = value; this.filterChanged(); },
      reset: function () {
        this.q = ""; this.conf = "all"; this.acc = ""; this.cat = "";
        this.filterChanged();
      },
      toggleGroup: function () {
        this.group = !this.group;
        this.selected = [];
        this.filterChanged();
      },
      showMore: function () {
        this.limit += this.step;
        this.refresh();
      },
      toggleMenu: function (name) { this.menu = this.menu === name ? "" : name; },

      // Called by the fragment the server sends after each swap: what is
      // displayed now, and what is still in the filtered list (a selected
      // operation that left it is no longer selected).
      sync: function (shownIds, visibleIds) {
        this.shownIds = shownIds;
        this.selected = this.selected.filter(function (id) { return visibleIds.indexOf(id) >= 0; });
      },

      ids: function (raw) { return raw.split(",").map(Number); },
      rowSelected: function (raw) {
        var self = this;
        return this.ids(raw).every(function (id) { return self.selected.indexOf(id) >= 0; });
      },
      toggleRow: function (raw, on) {
        var ids = this.ids(raw);
        this.selected = on
          ? this.selected.concat(ids.filter(function (id) { return this.selected.indexOf(id) < 0; }, this))
          : this.selected.filter(function (id) { return ids.indexOf(id) < 0; });
      },
      toggleAll: function (on) {
        var shown = this.shownIds;
        this.selected = on
          ? this.selected.concat(shown.filter(function (id) { return this.selected.indexOf(id) < 0; }, this))
          : this.selected.filter(function (id) { return shown.indexOf(id) < 0; });
      },

      // The "choose a category" panel: for one row (ids given), or for the whole selection.
      openPick: function (ids, title) { this.pick = { ids: ids, title: title }; this.payOpen = false; },
      openPickSelection: function (title) { this.pick = { ids: null, title: title }; this.payOpen = false; },
      closePick: function () { this.pick = null; },
      choose: function (id, path) {
        var pick = this.pick;
        this.pick = null;
        if (pick && pick.ids) {
          htmx.ajax("POST", "/backlog/validate", {
            source: this.$refs.form,
            target: "#backlog-list",
            swap: "innerHTML",
            values: { ids: pick.ids, category_id: id },
          });
        } else {
          this.bcat = { id: id, path: path };
        }
      },
      setPay: function (value) { this.pay = value; this.payOpen = false; },
      applied: function () { this.bcat = null; this.pay = ""; },
    };
  });
});
