// Par défaut, htmx NE SWAPPE PAS le corps d'une réponse 4xx/5xx dans la
// cible (hx-target) — seul l'événement htmx:responseError se déclenche,
// silencieusement sans handler dédié. Beaucoup de routes de cette appli
// renvoient volontairement un code 4xx (401 mot de passe incorrect, 400
// validation d'un formulaire...) avec un message d'erreur dans le corps
// HTML, destiné à s'afficher via ce même swap — sans ce correctif, ce
// message n'apparaît jamais (bug silencieux, aucune erreur JS visible).
// On aligne juste le comportement des 4xx/5xx sur celui des 2xx/3xx pour le
// swap, en gardant error:true : htmx continue de considérer la requête
// comme un échec (event.detail.successful reste false, utilisé par ex. par
// hx-on:htmx:after-request="if(event.detail.successful) this.reset()" pour
// ne réinitialiser un formulaire qu'en cas de vrai succès).
htmx.config.responseHandling = [
  { code: "204", swap: false },
  { code: "[23]..", swap: true },
  { code: "[45]..", swap: true, error: true },
];
