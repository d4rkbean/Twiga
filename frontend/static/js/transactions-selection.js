(function () {
  "use strict";

  // État de sélection PERSISTANT à travers la pagination : #transactions-
  // content est remplacé (hx-swap="innerHTML") à chaque changement de page/
  // filtre/action groupée, ce qui détruit l'x-data Alpine local à chaque
  // fois. Ce fichier vit dans transactions/index.html, JAMAIS swappé, donc
  // window.selectedTransactionAmounts survit intact d'une page à l'autre —
  // exactement ce qu'il faut pour cocher des lignes page 1, aller page 2,
  // et retrouver le total cumulé.
  //
  // Une Map (pas un simple Set) : id -> montant en centimes, pour pouvoir
  // calculer la somme totale sélectionnée MÊME pour des lignes qui ne sont
  // plus dans le DOM (pages déjà quittées) — jamais de flottant JS pour de
  // l'argent, ici comme partout ailleurs dans cette appli.
  window.selectedTransactionAmounts = window.selectedTransactionAmounts || new Map();

  // Miroir de la Map sous forme d'<input type="hidden" name="selected_ids">
  // dans un conteneur qui vit lui aussi hors du fragment swappé
  // (#all-selected-ids-inputs, dans transactions/index.html) : les boutons
  // d'action groupée l'incluent via hx-include, ce qui permet d'envoyer TOUS
  // les ids sélectionnés (pages précédentes comprises), pas seulement les
  // cases à cocher présentes sur la page actuellement affichée. Le backend
  // reçoit toujours "selected_ids" en champs répétés, exactement comme
  // avant — aucun changement côté serveur.
  window.syncSelectedIdsInputs = function () {
    var container = document.getElementById("all-selected-ids-inputs");
    if (!container) return;
    var html = "";
    window.selectedTransactionAmounts.forEach(function (_amountCents, id) {
      html += '<input type="hidden" name="selected_ids" value="' + id + '">';
    });
    container.innerHTML = html;
  };

  // Préférence "résultats par page" : mémorisée en localStorage, appliquée
  // au chargement (redéclenche une recherche si elle diffère de la taille
  // rendue par défaut côté serveur) et à chaque changement.
  var PAGE_SIZE_STORAGE_KEY = "twiga_transactions_page_size";

  window.applyStoredPageSize = function () {
    var select = document.getElementById("f_page_size");
    var form = document.getElementById("transactions-filters");
    if (!select || !form) return;
    var stored = localStorage.getItem(PAGE_SIZE_STORAGE_KEY);
    if (stored && stored !== select.value) {
      select.value = stored;
      form.requestSubmit();
    }
  };

  window.onPageSizeChange = function (value) {
    localStorage.setItem(PAGE_SIZE_STORAGE_KEY, value);
    var form = document.getElementById("transactions-filters");
    // Repart à la page 1 : aucun champ f_page dans ce <form> (la pagination
    // vit dans des hx-vals séparés sur les boutons Précédent/Suivant), donc
    // le soumettre revient déjà naturellement à la première page — la page
    // couramment affichée pourrait ne plus exister avec une taille
    // différente (ex. page 5/25 par page devient hors limites en 100/page).
    if (form) form.requestSubmit();
  };

  document.addEventListener("DOMContentLoaded", window.applyStoredPageSize);
})();
