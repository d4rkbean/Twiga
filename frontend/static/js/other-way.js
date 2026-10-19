(function () {
  "use strict";

  // État de la coque de « L'autre voie » (other_way/base.html), mélangé dans le
  // x-data de <body> : `shell` vaut le nom du menu ouvert ("more", "user",
  // "help", "search") ou null. Un seul menu à la fois : en ouvrir un en ferme
  // un autre. La barre du haut et la barre du bas pilotent le même état, d'où
  // sa place sur <body> et non sur l'une des deux.
  //
  // Alpine évalue x-data="{ ..., ...twigaShell() }" au démarrage : ce fichier
  // est chargé avant lui (voir le bloc shell_head de _layout.html).
  window.twigaShell = function () {
    return {
      shell: null,

      openShell: function (name) {
        this.shell = name;
        if (name === "search") {
          this.$nextTick(function () {
            var field = document.getElementById("shell-search-input");
            if (field) field.focus();
          });
        }
      },

      toggleShell: function (name) {
        this.shell = this.shell === name ? null : name;
      },

      closeShell: function () {
        this.shell = null;
      },

      // Ctrl/Cmd+K ouvre la recherche (la même que dans l'interface
      // Classique), Échap ferme le menu ouvert.
      onShellKey: function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key && event.key.toLowerCase() === "k") {
          event.preventDefault();
          this.openShell("search");
        } else if (event.key === "Escape" && this.shell !== null) {
          this.shell = null;
        }
      },

      // Efface les résultats quand le champ repasse sous deux caractères (la
      // requête ne part qu'à partir de deux, voir hx-trigger).
      clearShortSearch: function (event) {
        if (event.target.value.length < 2) {
          var results = document.getElementById("shell-search-results");
          if (results) results.innerHTML = "";
        }
      },
    };
  };
})();
