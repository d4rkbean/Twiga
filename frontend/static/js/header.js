(function () {
  "use strict";

  // Swipe-to-dismiss du bottom sheet menu utilisateur (mobile, voir
  // _header.html). Extrait d'un handler Alpine @touchmove inline : Alpine
  // compile ses expressions via `new AsyncFunction(...)`, où une
  // déclaration `var`/`let`/`const` est un SyntaxError silencieux côté
  // handler (le swipe ne faisait plus rien). Fonction nommée exposée sur
  // window pour rester appelable depuis l'expression Alpine du template.
  window.handleMenuSwipe = function (event, startY) {
    var delta = event.touches[0].clientY - startY;
    return delta > 0 ? delta : 0;
  };
})();
