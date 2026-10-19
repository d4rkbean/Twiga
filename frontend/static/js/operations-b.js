// Operations of the other way (other_way/transactions/*).
//
// One Alpine component on <main>, never swapped: it carries the filters, the
// open row, the selection (kept across pages and across swaps, since the
// component itself is never replaced), and the menus of the pills. The form
// #transactions-filters holds the filters as hidden fields bound to this state
// and is submitted again after each change: htmx swaps the list
// (#transactions-content) and, out of band, the sentence, the counters and the
// side panel, which the server computes from the same filters.
//
// The server stays stateless: a reload with ?f_search=... lands on the same
// view. Bulk actions send the filters (query string) and the selected ids.
(function () {
  "use strict";

  var STORAGE_KEY = "twiga_transactions_page_size";

  function money(cents) {
    var sign = cents > 0 ? "+" : cents < 0 ? "−" : "";
    var formatter = new Intl.NumberFormat(document.documentElement.dataset.numberLocale || "fr-FR", {
      style: "currency",
      currency: "EUR",
    });
    return sign + formatter.format(Math.abs(cents) / 100);
  }

  document.addEventListener("alpine:init", function () {
    Alpine.data("opsBoardB", function (init) {
      return {
        q: init.q,
        type: init.type,
        category: init.category,
        subcategory: init.subcategory,
        account: init.account,
        pay: init.pay,
        sort: init.sort,
        size: init.size,
        amin: init.amin,
        amax: init.amax,
        dfrom: init.dfrom,
        dto: init.dto,
        openId: init.openId,
        tree: init.tree,
        labels: init.labels,
        period: init.period,
        menu: "",
        sub: "",
        pageIds: [],
        amounts: {},
        sel: {},
        bcat: null,
        bpay: "",
        ask: "",
        bulkMenu: false,

        // The pills are views over the type and the "uncategorized" category.
        get tab() {
          if (this.category === "uncategorized") return "todo";
          if (this.type === "expense" || this.type === "income" || this.type === "transfer") return this.type;
          return this.type === "" ? "all" : "";
        },
        get subs() {
          var node = this.tree[this.category];
          return node ? node.children : [];
        },
        get categoryLabel() {
          if (this.category === "uncategorized") return this.labels.todo;
          var node = this.tree[this.category];
          if (!node) return this.labels.category;
          var found = node.children.find(function (child) { return child.id === this.subcategory; }, this);
          return found ? node.name + " › " + found.name : node.name;
        },
        get payLabel() { return this.labels.pay[this.pay] || this.labels.payment; },
        get sortLabel() { return this.labels.sort[this.sort]; },
        get critCount() { return (this.amin ? 1 : 0) + (this.amax ? 1 : 0); },
        get count() { return Object.keys(this.sel).length; },
        get sumCents() {
          var total = 0;
          for (var id in this.sel) total += this.sel[id];
          return total;
        },
        get sumLabel() { return money(this.sumCents); },
        get phrase() {
          var template = this.count === 1 ? this.labels.selOne : this.labels.selMany;
          return template.replace("{n}", this.count);
        },
        get allOnPage() {
          var self = this;
          return this.pageIds.length > 0 && this.pageIds.every(function (id) { return id in self.sel; });
        },
        get bcatLabel() { return this.bcat ? this.bcat.path : this.labels.category; },
        get bpayLabel() { return this.labels.pay[this.bpay] || this.labels.payment; },
        // The filters in force, each with how to take it off (the side panel).
        get active() {
          var list = [];
          if (this.q.trim()) list.push({ key: "q", label: "« " + this.q.trim() + " »" });
          if (this.type) list.push({ key: "type", label: this.labels.type[this.type] });
          if (this.category) list.push({ key: "category", label: this.categoryLabel });
          if (this.account) list.push({ key: "account", label: this.labels.account[this.account] });
          if (this.pay) list.push({ key: "pay", label: this.labels.pay[this.pay] });
          if (this.amin) list.push({ key: "amin", label: this.labels.min + " " + this.amin });
          if (this.amax) list.push({ key: "amax", label: this.labels.max + " " + this.amax });
          return list;
        },

        submit: function () {
          var self = this;
          this.menu = "";
          this.$nextTick(function () { self.$refs.form.requestSubmit(); });
        },
        setTab: function (name) {
          if (name === "todo") {
            this.category = "uncategorized"; this.subcategory = ""; this.type = "";
          } else {
            if (this.category === "uncategorized") this.category = "";
            this.type = name === "all" ? "" : name;
          }
          this.openId = null;
          this.submit();
        },
        setAccount: function (id) {
          this.account = this.account === id ? "" : id;
          this.openId = null;
          this.submit();
        },
        setCategory: function (id) {
          this.category = id;
          this.subcategory = "";
          this.sub = "";
          this.openId = null;
          this.submit();
        },
        setSub: function (parent, id) {
          this.category = parent;
          this.subcategory = id;
          this.openId = null;
          this.submit();
        },
        setPay: function (code) { this.pay = code; this.openId = null; this.submit(); },
        setSort: function (code) { this.sort = code; this.submit(); },
        setPeriod: function (from, to) {
          this.dfrom = from; this.dto = to;
          this.openId = null;
          this.submit();
        },
        step: function (which) {
          var target = this.period[which];
          if (target) this.setPeriod(target.from, target.to);
        },
        clear: function (key) {
          if (key === "q") this.q = "";
          else if (key === "type") this.type = "";
          else if (key === "category") { this.category = ""; this.subcategory = ""; }
          else if (key === "account") this.account = "";
          else if (key === "pay") this.pay = "";
          else if (key === "amin") this.amin = "";
          else if (key === "amax") this.amax = "";
          this.openId = null;
          this.submit();
        },
        toggleOpen: function (id) {
          this.openId = this.openId === id ? null : id;
          this.submit();
        },
        setSize: function (value) {
          this.size = value;
          try { localStorage.setItem(STORAGE_KEY, value); } catch (error) {}
          this.submit();
        },

        // Told by the fragment the server sends after each swap: the ids and
        // amounts of the page. A selected operation that is on no page of the
        // new view stays selected (the selection spans pages).
        sync: function (ids, amounts) {
          this.pageIds = ids;
          this.amounts = amounts;
          for (var id in amounts) if (id in this.sel) this.sel[id] = amounts[id];
        },
        isSelected: function (id) { return id in this.sel; },
        toggle: function (id) {
          var next = Object.assign({}, this.sel);
          if (id in next) delete next[id]; else next[id] = this.amounts[id] || 0;
          this.sel = next;
        },
        toggleAll: function () {
          var next = Object.assign({}, this.sel);
          var self = this;
          if (this.allOnPage) this.pageIds.forEach(function (id) { delete next[id]; });
          else this.pageIds.forEach(function (id) { next[id] = self.amounts[id] || 0; });
          this.sel = next;
        },
        clearSelection: function () {
          this.sel = {};
          this.bcat = null;
          this.bpay = "";
          this.ask = "";
          this.bulkMenu = false;
          this.menu = "";
        },

        // Bulk actions: the filters travel in the query string, the ids in the body.
        bulk: function (url, values) {
          var self = this;
          var query = new URLSearchParams(new FormData(this.$refs.form)).toString();
          var body = Object.assign({ selected_ids: Object.keys(this.sel).map(Number) }, values || {});
          htmx.ajax("POST", url + "?" + query, { target: "#transactions-content", swap: "innerHTML", values: body })
            .then(function () { self.clearSelection(); });
        },
        applySelection: function () {
          this.bulk("/transactions/bulk-apply", {
            category_id: this.bcat ? this.bcat.id : "",
            payment_method: this.bpay,
          });
        },
        exportHref: function () {
          return "/export/transactions.csv?" + new URLSearchParams(new FormData(this.$refs.form)).toString();
        },
      };
    });
  });

  // The page size remembered on this device: applied once, on load.
  document.addEventListener("DOMContentLoaded", function () {
    var main = document.querySelector("main[x-data]");
    var stored = null;
    try { stored = localStorage.getItem(STORAGE_KEY); } catch (error) {}
    if (!main || !stored || !window.Alpine) return;
    setTimeout(function () {
      var data = Alpine.$data(main);
      if (data && data.size !== stored) data.setSize(stored);
    }, 0);
  });
})();
