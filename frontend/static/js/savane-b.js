// La Savane of the other way (other_way/inbox/*).
//
// Three small pieces, none of them holding data that the server owns:
//  - twigaQuestion: the state of the question card (the label being renamed, the
//    « Imprévu » switch, the payment method chosen for « Oui », the swipe);
//  - the swipe of a line of the lot, which does what a touch does (leave the lot);
//  - the budget alert of a card, dismissed for the month in localStorage, with
//    the same keys as the alerts panel of Classic.
// The keyboard shortcuts are inbox-shortcuts.js, shared with Classic: the
// buttons keep the ids it clicks (inbox-validate-btn, inbox-skip-btn...).
document.addEventListener("alpine:init", function () {
  Alpine.data("twigaQuestion", function (init) {
    return {
      label: init.label,
      draft: init.label,
      editing: false,
      unexpected: init.unexpected,
      pay: init.pay,
      payLabels: init.payLabels,
      payOpen: false,
      transferDismissed: !init.possibleTransfer,
      dragX: 0,
      dragging: false,
      startX: 0,
      startY: 0,
      horizontal: false,

      get payText() {
        return this.payLabels[this.pay] || "";
      },

      edit: function () {
        this.draft = this.label;
        this.editing = true;
        var self = this;
        this.$nextTick(function () { if (self.$refs.labelInput) self.$refs.labelInput.focus(); });
      },
      saveLabel: function () {
        var value = this.draft.trim();
        if (value) this.label = value;
        this.editing = false;
      },
      cancelLabel: function () {
        this.editing = false;
      },
      propose: function (text) {
        this.draft = text;
      },
      choosePay: function (code) {
        this.pay = code;
        this.payOpen = false;
      },

      // Swipe: right says « Oui », left says « Passer », like the two buttons.
      onStart: function (event) {
        if (this.editing) return;
        this.dragging = true;
        this.horizontal = false;
        this.startX = event.touches[0].clientX;
        this.startY = event.touches[0].clientY;
      },
      onMove: function (event) {
        if (!this.dragging) return;
        var dx = event.touches[0].clientX - this.startX;
        var dy = event.touches[0].clientY - this.startY;
        if (!this.horizontal && Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.5) this.horizontal = true;
        if (this.horizontal) this.dragX = dx;
      },
      onEnd: function () {
        if (!this.dragging) return;
        this.dragging = false;
        var threshold = 100;
        if (this.dragX > threshold) {
          var yes = document.getElementById("inbox-validate-btn");
          if (yes) { this.dragX = 600; yes.click(); return; }
        } else if (this.dragX < -threshold) {
          var skip = document.getElementById("inbox-skip-btn");
          if (skip) { this.dragX = -600; skip.click(); return; }
        }
        this.dragX = 0;
      },
    };
  });
});

(function () {
  "use strict";

  // A swipe on a line of the lot leaves the lot, as a touch does.
  var swipe = null;
  document.addEventListener("touchstart", function (event) {
    var row = event.target.closest && event.target.closest("[data-lot-row]");
    swipe = row ? { row: row, x: event.touches[0].clientX, y: event.touches[0].clientY } : null;
  }, { passive: true });
  document.addEventListener("touchend", function (event) {
    if (!swipe) return;
    var touch = event.changedTouches[0];
    var dx = touch.clientX - swipe.x;
    var dy = touch.clientY - swipe.y;
    var row = swipe.row;
    swipe = null;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.5) row.click();
  }, { passive: true });

  // Budget alert of the card: hidden for the month once dismissed.
  function dismissed(key) {
    try { return localStorage.getItem(key) === "true"; } catch (error) { return false; }
  }

  function applyBudgetAlerts() {
    document.querySelectorAll("[data-budget-alert]").forEach(function (alert) {
      var hidden = dismissed(alert.dataset.key);
      alert.hidden = hidden;
      var reveal = alert.parentElement && alert.parentElement.querySelector("[data-budget-reveal]");
      if (reveal) reveal.hidden = !hidden;
    });
  }

  document.addEventListener("click", function (event) {
    var close = event.target.closest && event.target.closest("[data-budget-dismiss]");
    if (close) {
      var alert = close.closest("[data-budget-alert]");
      try { localStorage.setItem(alert.dataset.key, "true"); } catch (error) {}
      applyBudgetAlerts();
      return;
    }
    var reveal = event.target.closest && event.target.closest("[data-budget-reveal]");
    if (reveal) {
      var suffix = reveal.dataset.suffix;
      var prefix = reveal.dataset.prefix;
      try {
        var keys = [];
        for (var i = 0; i < localStorage.length; i++) {
          var key = localStorage.key(i);
          if (key && key.indexOf(prefix) === 0 && key.slice(-suffix.length) === suffix) keys.push(key);
        }
        keys.forEach(function (key) { localStorage.removeItem(key); });
      } catch (error) {}
      applyBudgetAlerts();
    }
  });

  // The mid-month notice: gone for the month once closed (same key as Classic).
  function applyNotices() {
    var notice = document.querySelector("[data-dismiss-key]");
    if (notice && dismissed(notice.dataset.dismissKey)) notice.remove();
  }

  document.addEventListener("click", function (event) {
    var close = event.target.closest && event.target.closest("[data-dismiss]");
    var notice = close && close.closest("[data-dismiss-key]");
    if (notice) {
      try { localStorage.setItem(notice.dataset.dismissKey, "true"); } catch (error) {}
      notice.remove();
    }
  });

  function applyAll() {
    applyBudgetAlerts();
    applyNotices();
  }

  document.addEventListener("DOMContentLoaded", applyAll);
  document.addEventListener("htmx:afterSettle", applyAll);
})();
