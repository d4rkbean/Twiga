// Operations screen (transactions/index.html).
//
// The filters live in one Alpine component on <main>; the form
// #transactions-filters carries them (hidden fields bound to that state) and is
// submitted again after each change: htmx swaps the list. The detail of an
// operation is a panel next to the list on a computer, a bottom sheet (<dialog>
// opened as a modal) on a phone.
(function () {
  "use strict";

  var DESKTOP = "(min-width: 1024px)";

  function dialog() {
    return document.getElementById("transaction-detail-dialog");
  }

  // Phones only: the sheet opens once its content is there. On a computer the
  // dialog is always displayed as the side panel (see index.html).
  window.showTransactionDetail = function () {
    var element = dialog();
    if (element && !window.matchMedia(DESKTOP).matches && !element.open) element.showModal();
  };

  window.closeTransactionDetail = function () {
    var element = dialog();
    if (element && element.open) element.close();
  };

  // Back to the "choose an operation" placeholder (cancelled form, deleted operation).
  window.resetTransactionDetail = function () {
    var target = document.getElementById("transaction-detail-content");
    var template = document.getElementById("transaction-detail-empty");
    if (target && template) target.innerHTML = template.innerHTML;
    window.closeTransactionDetail();
    var main = document.querySelector("main[x-data]");
    if (main && window.Alpine) Alpine.$data(main).openId = null;
  };

  document.addEventListener("alpine:init", function () {
    Alpine.data("opsBoard", function (init) {
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
        tree: init.tree,
        adv: false,
        openId: init.openId,

        // The tabs are views over two fields: the type, and "uncategorized".
        get tab() {
          if (this.category === "uncategorized") return "todo";
          if (this.type === "expense" || this.type === "income") return this.type;
          return this.type === "" ? "all" : "";
        },
        get subs() {
          var node = this.tree[this.category];
          return node ? node.children : [];
        },
        get subLabel() {
          var found = this.subs.find(function (child) { return child.id === this.subcategory; }, this);
          return found ? found.name : init.labels.allSubs;
        },
        get subOptions() {
          return [{ id: "", name: init.labels.allSubs }].concat(this.subs);
        },

        submit: function () {
          var self = this;
          this.$nextTick(function () { self.$refs.form.requestSubmit(); });
        },
        setTab: function (name) {
          if (name === "todo") {
            this.category = "uncategorized"; this.subcategory = ""; this.type = "";
          } else {
            if (this.category === "uncategorized") this.category = "";
            this.type = name === "all" ? "" : name;
          }
          this.submit();
        },
        setCategory: function (value) {
          this.category = value;
          this.subcategory = "";
          this.submit();
        },
      };
    });
  });
})();
