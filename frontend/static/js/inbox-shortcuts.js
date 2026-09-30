(function () {
  "use strict";

  // Raccourcis clavier desktop pour La Savane :
  //   → ou Espace : Passer      ← : Précédente
  //   1-9         : catégorie par position (voir .shortcut-category-btn)
  //   Entrée      : valider la catégorie proposée
  //   Échap       : retour aux catégories
  // Fichier statique dédié (jamais passé par Jinja, aucune donnée dynamique
  // à embarquer) : ne peut pas souffrir du souci d'échappement qui a cassé
  // un <script> inline plus tôt dans ce projet. Chaque élément est requêté
  // en direct à chaque appui (document.getElementById/querySelectorAll),
  // jamais mis en cache, pour rester correct après un remplacement htmx de
  // #transaction-card (nouvelle transaction, nouvelle étape du flux...).

  function isTypingContext(target) {
    if (!target) return false;
    var tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable === true;
  }

  function clickById(id) {
    var el = document.getElementById(id);
    if (el) el.click();
  }

  document.addEventListener("keydown", function (event) {
    if (isTypingContext(event.target)) return;
    if (!document.getElementById("transaction-card")) return;

    if (event.key === "ArrowRight" || event.key === " ") {
      event.preventDefault();
      clickById("inbox-skip-btn");
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      clickById("inbox-previous-btn");
    } else if (event.key === "Enter") {
      event.preventDefault();
      clickById("inbox-validate-btn");
    } else if (event.key === "Escape") {
      event.preventDefault();
      clickById("inbox-back-to-categories-btn");
    } else if (event.key >= "1" && event.key <= "9") {
      var buttons = document.querySelectorAll(".shortcut-category-btn");
      var index = parseInt(event.key, 10) - 1;
      if (buttons[index]) {
        event.preventDefault();
        buttons[index].click();
      }
    }
  });
})();
