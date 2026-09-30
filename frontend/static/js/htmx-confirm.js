// Remplace le window.confirm() natif de htmx (déclenché par hx-confirm="...")
// par le <dialog> stylé #twiga-confirm-dialog (voir base.html) : la boîte
// native affiche toujours un préfixe imposé par le navigateur ("La page à
// l'adresse http://... indique :"), impossible à retirer ou personnaliser
// pour une page web — seul un dialogue "maison" permet une confirmation qui
// ressemble à une vraie application plutôt qu'à une alerte de navigateur.
(function () {
  document.addEventListener("htmx:confirm", function (event) {
    var question = event.detail.question;
    if (!question) return; // pas de hx-confirm sur cet élément : laisser htmx suivre son cours normal.

    event.preventDefault();

    var dialog = document.getElementById("twiga-confirm-dialog");
    var message = document.getElementById("twiga-confirm-message");
    var okBtn = document.getElementById("twiga-confirm-ok");
    var cancelBtn = document.getElementById("twiga-confirm-cancel");
    if (!dialog || !message || !okBtn || !cancelBtn) {
      // Filet de sécurité : si le dialogue custom est absent pour une
      // raison quelconque, ne jamais bloquer silencieusement l'action.
      event.detail.issueRequest(true);
      return;
    }

    message.textContent = question;
    var confirmed = false;

    function onOk() {
      confirmed = true;
      dialog.close();
    }
    function onCancel() {
      dialog.close();
    }
    function onClose() {
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      dialog.removeEventListener("close", onClose);
      // "close" se déclenche aussi bien sur clic Confirmer, clic Annuler,
      // que touche Échap (via l'événement "cancel" natif du <dialog>) : un
      // seul point de sortie pour décider si la requête doit vraiment partir.
      if (confirmed) event.detail.issueRequest(true);
    }

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    dialog.addEventListener("close", onClose);
    dialog.showModal();
  });
})();
