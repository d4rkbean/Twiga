(function () {
  "use strict";

  var COMPLETED_KEY = "twiga_tour_completed";
  var STEP_KEY = "twiga_tour_step";

  // Cinq étapes, sans changement de page : la visite raconte la boucle
  // importer → catégoriser → piloter, puis les raccourcis. Les cibles
  // (en-tête, navigation) existent sur toutes les pages. skipImport :
  // étape retirée pour un rôle sans droit d'import ou une base déjà remplie
  // (voir tour_context dans backend/templating.py).
  // position: côté de la bulle par rapport à la cible ("top"/"bottom", ou
  // "center" pour les étapes sans cible).
  var STEPS = [
    {
      id: "welcome",
      icon: "compass",
      target: null,
      position: "center",
      title: "Bienvenue dans Twiga",
      text:
        "<p>Trois temps : importer ses opérations, les catégoriser, puis suivre ses comptes.</p>" +
        "<p>Les données restent sur ce serveur. Rien n'est envoyé sur Internet.</p>",
    },
    {
      id: "import",
      icon: "file-import",
      skipImport: true,
      target: "#tour-import",
      position: "bottom",
      title: "Importer",
      text:
        "<p>Tout commence par un relevé bancaire : QIF, CSV ou OFX.</p>" +
        "<p>Les doublons sont détectés et ignorés.</p>",
    },
    {
      id: "nav-savane",
      icon: "inbox",
      target: "#tour-nav-savane",
      altTarget: "#tour-sidebar-savane",
      position: "top",
      altPosition: "right",
      title: "La Savane",
      text:
        "<p>Chaque nouvelle opération y attend une catégorie, une carte à la fois.</p>" +
        "<p>Les choix répétés sont mémorisés et proposés ensuite.</p>",
    },
    {
      id: "nav-dashboard",
      icon: "chart-bar",
      target: "#tour-nav-dashboard",
      altTarget: "#tour-sidebar-dashboard",
      position: "top",
      altPosition: "right",
      title: "Panorama et Mon mois",
      text:
        "<p>Le Panorama montre où va l'argent. Mon mois fixe ce qu'on se donne " +
        "le droit de dépenser.</p>",
    },
    {
      id: "search-icon",
      icon: "search",
      target: "#tour-search-icon",
      altTarget: "#tour-desktop-search",
      position: "bottom",
      title: "Raccourcis",
      text:
        "<p>Ctrl+K cherche une opération, une catégorie ou un projet.</p>" +
        "<p>L'icône en forme d'œil masque les montants.</p>",
    },
  ];

  function getStepIndex() {
    var raw = localStorage.getItem(STEP_KEY);
    var index = raw !== null ? parseInt(raw, 10) : NaN;
    return isNaN(index) ? -1 : index;
  }

  function setStepIndex(index) {
    localStorage.setItem(STEP_KEY, String(index));
  }

  function isCompleted() {
    return localStorage.getItem(COMPLETED_KEY) === "true";
  }

  function markCompleted() {
    localStorage.setItem(COMPLETED_KEY, "true");
    localStorage.removeItem(STEP_KEY);
  }

  // Certaines cibles n'existent que sur un breakpoint (bandeau du bas et
  // logo/recherche/confidentialité du header mobile sont lg:hidden, remplacés
  // par la sidebar en desktop) : l'élément reste dans le DOM mais avec un
  // rectangle 0x0 une fois caché, ce qui casserait le spotlight. isVisible()
  // s'appuie sur offsetWidth/offsetHeight (0 dès qu'un ancêtre quelconque est
  // display:none), sans dépendre de connaître la chaîne d'ancêtres.
  function isVisible(el) {
    return !!el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
  }

  // Résout la cible RÉELLEMENT visible pour une étape donnée (mobile OU son
  // équivalent desktop via altTarget/altPosition), ou aucune cible si ni
  // l'une ni l'autre n'est visible (repli sur bulle centrée plutôt qu'un
  // spotlight sur un élément caché).
  function resolveStep(step) {
    if (!step || !step.target) {
      return { el: null, position: step ? step.position : "center" };
    }
    var primary = document.querySelector(step.target);
    if (isVisible(primary)) {
      return { el: primary, position: step.position };
    }
    if (step.altTarget) {
      var alt = document.querySelector(step.altTarget);
      if (isVisible(alt)) {
        return { el: alt, position: step.altPosition || step.position };
      }
    }
    return { el: null, position: "center" };
  }

  // Géométrie pure (aucun accès DOM) pour rester testable sans navigateur :
  // calcule la position de la bulle par rapport au rectangle de la cible
  // (ou centrée si rect est null), avec un cadrage pour ne jamais déborder
  // du viewport.
  function computeBubblePosition(rect, position, bubbleSize, viewport, gap) {
    var margin = 12;

    if (!rect || position === "center") {
      return {
        top: Math.max(margin, (viewport.height - bubbleSize.height) / 2),
        left: Math.max(margin, (viewport.width - bubbleSize.width) / 2),
      };
    }

    var top;
    if (position === "top") {
      top = rect.top - bubbleSize.height - gap;
    } else if (position === "left" || position === "right") {
      top = rect.top + rect.height / 2 - bubbleSize.height / 2;
    } else {
      top = rect.bottom + gap;
    }

    var left;
    if (position === "left") {
      left = rect.left - bubbleSize.width - gap;
    } else if (position === "right") {
      left = rect.right + gap;
    } else {
      left = rect.left + rect.width / 2 - bubbleSize.width / 2;
    }

    top = Math.min(Math.max(top, margin), viewport.height - bubbleSize.height - margin);
    left = Math.min(Math.max(left, margin), viewport.width - bubbleSize.width - margin);

    return { top: top, left: left };
  }

  // Alpine lit "twigaTour" comme une fonction globale au moment où il scanne
  // le DOM (au DOMContentLoaded, donc après ce script chargé en defer juste
  // avant lui dans base.html) : pas besoin de Alpine.data()/alpine:init.
  window.twigaTour = function () {
    return {
      visible: false,
      stepIndex: -1,
      step: null,
      hasTarget: false,
      bubbleStyle: "top: -9999px; left: -9999px;",
      spotlightStyle: "top: -9999px; left: -9999px; width: 0; height: 0;",
      steps: STEPS,
      tracked: false,

      // SVG de l'icône de l'étape, lu dans le <div id="tour-icons"> rendu
      // côté serveur par _tour.html (même jeu d'icônes que la navigation).
      stepIcon: function () {
        if (!this.step || !this.step.icon) return "";
        var holder = document.querySelector('#tour-icons [data-icon="' + this.step.icon + '"]');
        return holder ? holder.innerHTML : "";
      },

      init: function () {
        var self = this;
        window.addEventListener("resize", function () {
          if (self.visible) self.reposition();
        });
        window.addEventListener(
          "scroll",
          function () {
            if (self.visible) self.reposition();
          },
          { passive: true, capture: true }
        );

        window.__twigaTourInstance = this;

        // startTwigaTour() redirige vers /transactions/inbox?tour=1 plutôt
        // que d'essayer de relancer le tour en place depuis la page
        // Paramètres : ça évite de partir sur la mauvaise page (dont les
        // éléments de la première étape ne sont pas présents) et évite
        // aussi de dépendre d'un composant Alpine déjà initialisé sur la
        // page courante.
        var forcedRestart = window.location.search.indexOf("tour=1") !== -1;
        if (forcedRestart && window.history && window.history.replaceState) {
          window.history.replaceState({}, "", window.location.pathname);
        }

        var dataset = this.$el.dataset;
        this.tracked = dataset.tracked === "true";
        var skipImport = dataset.skipImport === "true";
        this.steps = STEPS.filter(function (step) {
          return !(step.skipImport && skipImport);
        });

        // Délai de sécurité : laisse le temps au DOM (et à d'éventuels
        // fragments chargés en HTMX) de finir de se rendre avant de mesurer
        // la position du premier élément ciblé.
        setTimeout(function () {
          if (forcedRestart) {
            localStorage.removeItem(COMPLETED_KEY);
            localStorage.removeItem(STEP_KEY);
            self.goTo(0, 1, true);
            return;
          }

          // Compte connecté : le serveur décide (users.tour_seen_at), pas le
          // navigateur — pas de rejeu sur un nouvel appareil. Sans
          // authentification : repli sur localStorage.
          if (self.tracked ? dataset.pending !== "true" : isCompleted()) return;
          var storedIndex = getStepIndex();
          self.goTo(storedIndex >= 0 ? storedIndex : 0, 1, true);
        }, 500);
      },

      // allowNavigate=true seulement pour une action délibérée (clic sur
      // Suivant/Précédent, ou relance manuelle) : voir commentaire ci-dessus.
      goTo: function (index, direction, allowNavigate) {
        if (index < 0 || index >= this.steps.length) {
          this.complete();
          return;
        }

        var candidate = this.steps[index];

        if (candidate.target && !resolveStep(candidate).el) {
          this.goTo(index + direction, direction, allowNavigate);
          return;
        }

        this.show(index);
      },

      show: function (index) {
        var self = this;
        this.stepIndex = index;
        this.step = this.steps[index];
        this.visible = true;
        this.hasTarget = false;
        setStepIndex(index);

        var el = resolveStep(this.step).el;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          setTimeout(function () {
            self.reposition();
          }, 350);
        }

        this.$nextTick(function () {
          self.reposition();
        });
      },

      // Repositionne à la fois la bulle et, si la cible existe, le masque
      // "spotlight" qui découpe un trou dans l'assombrissement autour
      // d'elle (voir tour.css pour l'explication de la technique). Appelée
      // après affichage, après défilement, et sur resize/scroll.
      reposition: function () {
        var resolved = resolveStep(this.step);
        var rect = resolved.el ? resolved.el.getBoundingClientRect() : null;

        this.hasTarget = !!rect;
        if (rect) {
          var pad = 4;
          this.spotlightStyle =
            "top: " + (rect.top - pad) + "px; left: " + (rect.left - pad) + "px; " +
            "width: " + (rect.width + pad * 2) + "px; height: " + (rect.height + pad * 2) + "px;";
        }

        var bubbleEl = this.$refs.bubble;
        var bubbleSize = bubbleEl
          ? { width: bubbleEl.offsetWidth, height: bubbleEl.offsetHeight }
          : { width: 320, height: 160 };
        var viewport = { width: window.innerWidth, height: window.innerHeight };
        var pos = computeBubblePosition(rect, resolved.position, bubbleSize, viewport, 16);

        this.bubbleStyle = "top: " + pos.top + "px; left: " + pos.left + "px;";
      },

      next: function () {
        this.goTo(this.stepIndex + 1, 1, true);
      },

      prev: function () {
        this.goTo(this.stepIndex - 1, -1, true);
      },

      // Fin normale, bouton « Passer » ou Échap : même effet, le compte
      // ne revoit plus la visite (relançable depuis Aide).
      complete: function () {
        this.visible = false;
        this.hasTarget = false;
        markCompleted();
        if (this.tracked && window.fetch) {
          fetch("/profile/tour-seen", { method: "POST", credentials: "same-origin" });
        }
      },

      isFirst: function () {
        return this.stepIndex === 0;
      },

      isLast: function () {
        return this.stepIndex === this.steps.length - 1;
      },

      progressDots: function () {
        var dots = "";
        for (var i = 0; i < this.steps.length; i++) {
          dots += i === this.stepIndex ? "●" : "○";
        }
        return dots;
      },

      progressLabel: function () {
        return "Étape " + (this.stepIndex + 1) + " sur " + this.steps.length;
      },
    };
  };

  // Relance manuelle (Aide, Paramètres) : recharge la page courante avec
  // ?tour=1, que init() détecte pour repartir de la première étape sans
  // dépendre d'un composant Alpine déjà initialisé.
  window.startTwigaTour = function () {
    localStorage.removeItem(COMPLETED_KEY);
    localStorage.removeItem(STEP_KEY);
    window.location.href = window.location.pathname + "?tour=1";
  };

  // Exposée uniquement pour le harnais de test Node (géométrie pure, sans DOM).
  window.__twigaTourComputeBubblePosition = computeBubblePosition;

  console.log("tour.js chargé, startTwigaTour disponible :", typeof window.startTwigaTour);
})();
