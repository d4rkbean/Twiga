(function () {
  "use strict";

  var COMPLETED_KEY = "twiga_tour_completed";
  var STEP_KEY = "twiga_tour_step";
  var SCREEN_KEY = "twiga_screen_tours";

  // Aucune étape n'est écrite ici : la visite de chaque interface (_tour.html,
  // other_way/_tour.html) fournit les siennes en JSON dans data-steps sur la
  // racine de _tour_ui.html, textes déjà traduits compris. Une étape :
  //   id, icon, title, text
  //   target       sélecteur CSS de l'élément à entourer (null : bulle centrée)
  //   altTarget    cible de repli quand target est caché (autre point de rupture)
  //   position     côté de la bulle par rapport à la cible ("top", "bottom",
  //                "left", "right", ou "center" pour les étapes sans cible)
  //   altPosition  position avec altTarget
  //   skipImport   étape retirée pour un rôle sans droit d'import ou une base
  //                déjà remplie (voir tour_context dans backend/templating.py)
  //
  // Deux visites passent par ce composant : celle d'accueil (data-steps,
  // première connexion et « Revoir la visite de bienvenue ») et celle de
  // l'écran ouvert (data-screen-steps, déclarée par la page elle-même : voir
  // backend/tours.py). La seconde se joue depuis Aide ou depuis l'invitation
  // de la première ouverture de l'écran ; une étape dont la cible est absente
  // ou cachée est sautée.

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

  // Sans compte (authentification désactivée), la mémoire des écrans déjà
  // proposés reste dans le navigateur : {identifiant d'écran: true}.
  function readLocalScreens() {
    try {
      return JSON.parse(localStorage.getItem(SCREEN_KEY) || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function rememberScreenLocally(screen) {
    try {
      var seen = readLocalScreens();
      seen[screen] = true;
      localStorage.setItem(SCREEN_KEY, JSON.stringify(seen));
    } catch (error) {}
  }

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function parseSteps(raw) {
    try {
      var steps = JSON.parse(raw || "[]");
      return Array.isArray(steps) ? steps : [];
    } catch (error) {
      return [];
    }
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
      inviteVisible: false,
      mode: "welcome",
      stepIndex: -1,
      step: null,
      hasTarget: false,
      bubbleStyle: "top: -9999px; left: -9999px;",
      spotlightStyle: "top: -9999px; left: -9999px; width: 0; height: 0;",
      steps: [],
      welcomeSteps: [],
      screenSteps: [],
      screen: "",
      screenReported: false,
      inviteTimer: null,
      tracked: false,
      progressTemplate: "{step} / {total}",

      // SVG de l'icône de l'étape, lu dans le <div id="tour-icons"> rendu
      // côté serveur par _tour_ui.html (même jeu d'icônes que la navigation).
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

        // ?tour=1 : relance de la visite d'accueil par rechargement (repli de
        // startTwigaTour() quand aucun composant n'est encore prêt).
        var forcedRestart = window.location.search.indexOf("tour=1") !== -1;
        if (forcedRestart && window.history && window.history.replaceState) {
          window.history.replaceState({}, "", window.location.pathname);
        }

        var dataset = this.$el.dataset;
        this.tracked = dataset.tracked === "true";
        // Gabarit traduit de la progression, fourni par _tour_ui.html
        // comme les textes des étapes.
        this.progressTemplate = dataset.progressLabel || this.progressTemplate;
        var skipImport = dataset.skipImport === "true";
        this.welcomeSteps = parseSteps(dataset.steps).filter(function (step) {
          return !(step.skipImport && skipImport);
        });
        this.screenSteps = parseSteps(dataset.screenSteps);
        this.screen = dataset.screen || "";
        this.steps = this.welcomeSteps;

        // Délai de sécurité : laisse le temps au DOM (et à d'éventuels
        // fragments chargés en HTMX) de finir de se rendre avant de mesurer
        // la position du premier élément ciblé.
        setTimeout(function () {
          if (forcedRestart) {
            self.startWelcome();
            return;
          }

          // Compte connecté : le serveur décide (users.tour_seen_at), pas le
          // navigateur — pas de rejeu sur un nouvel appareil. Sans
          // authentification : repli sur localStorage.
          var welcomePending = self.tracked ? dataset.pending === "true" : !isCompleted();
          if (welcomePending) {
            var storedIndex = getStepIndex();
            self.mode = "welcome";
            self.steps = self.welcomeSteps;
            self.goTo(storedIndex >= 0 ? storedIndex : 0, 1, true);
            return;
          }

          // La visite d'accueil est faite : l'écran propose la sienne, une
          // seule fois, s'il a au moins une étape à montrer.
          var seen = self.tracked ? dataset.screenSeen === "true" : !!readLocalScreens()[self.screen];
          var playable = self.screenSteps.some(function (step) {
            return resolveStep(step).el;
          });
          if (self.screen && !seen && playable) self.showInvite();
        }, 500);
      },

      // Visite d'accueil, depuis le début.
      startWelcome: function () {
        this.hideInvite();
        localStorage.removeItem(COMPLETED_KEY);
        localStorage.removeItem(STEP_KEY);
        this.mode = "welcome";
        this.steps = this.welcomeSteps;
        this.goTo(0, 1, true);
      },

      // Visite de l'écran ouvert (Aide, ou « Oui » de l'invitation).
      startScreen: function () {
        if (!this.screenSteps.length) return;
        this.hideInvite();
        this.rememberScreen();
        this.mode = "screen";
        this.steps = this.screenSteps;
        this.goTo(0, 1, true);
      },

      // L'invitation compte comme proposée dès qu'elle s'affiche : quoi que
      // l'on réponde (ou ne réponde pas), l'écran ne la redemande pas.
      showInvite: function () {
        var self = this;
        this.inviteVisible = true;
        this.rememberScreen();
        // Sans réponse au bout d'un moment, elle se retire d'elle-même.
        this.inviteTimer = setTimeout(function () {
          self.inviteVisible = false;
        }, 20000);
      },

      hideInvite: function () {
        this.inviteVisible = false;
        if (this.inviteTimer) clearTimeout(this.inviteTimer);
        this.inviteTimer = null;
      },

      acceptInvite: function () {
        this.startScreen();
      },

      dismissInvite: function () {
        this.hideInvite();
      },

      // Mémorise que l'écran a été proposé ou joué : sur le compte (le
      // serveur valide l'identifiant) ou, sans compte, dans le navigateur.
      rememberScreen: function () {
        if (!this.screen) return;
        rememberScreenLocally(this.screen);
        if (this.tracked && !this.screenReported && window.fetch) {
          this.screenReported = true;
          fetch("/profile/screen-tour-seen", {
            method: "POST",
            credentials: "same-origin",
            body: new URLSearchParams({ screen: this.screen }),
          });
        }
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
        if (this.mode === "welcome") setStepIndex(index);

        var el = resolveStep(this.step).el;
        if (el) {
          var reduced = prefersReducedMotion();
          el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
          setTimeout(function () {
            self.reposition();
          }, reduced ? 50 : 350);
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

      // Fin normale, bouton « Passer » ou Échap : même effet. La visite
      // d'accueil n'est plus rejouée à la connexion ; celle d'un écran est
      // notée comme vue. Les deux restent relançables depuis Aide.
      complete: function () {
        this.visible = false;
        this.hasTarget = false;
        if (this.mode === "screen") {
          this.rememberScreen();
          return;
        }
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
        return this.progressTemplate
          .replace("{step}", this.stepIndex + 1)
          .replace("{total}", this.steps.length);
      },
    };
  };

  // Relance manuelle de la visite d'accueil (Aide, Paramètres) : sur place
  // quand le composant est prêt, sinon en rechargeant la page avec ?tour=1,
  // que init() détecte pour repartir de la première étape.
  window.startTwigaTour = function () {
    var instance = window.__twigaTourInstance;
    if (instance && instance.startWelcome) {
      instance.startWelcome();
      return;
    }
    localStorage.removeItem(COMPLETED_KEY);
    localStorage.removeItem(STEP_KEY);
    window.location.href = window.location.pathname + "?tour=1";
  };

  // Visite de l'écran ouvert (bouton « Visite de cet écran » de l'aide).
  window.startScreenTour = function () {
    var instance = window.__twigaTourInstance;
    if (instance && instance.startScreen) instance.startScreen();
  };

  // Exposée uniquement pour le harnais de test Node (géométrie pure, sans DOM).
  window.__twigaTourComputeBubblePosition = computeBubblePosition;
})();
