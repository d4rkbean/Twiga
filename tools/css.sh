#!/bin/sh
# Feuille de style Tailwind (voir DESIGN.md).
#
#   tools/css.sh build   compile design-system.css en frontend/static/vendor/tailwind.min.css (minifié)
#   tools/css.sh watch   recompile à chaque modification d'un gabarit, d'un script ou de la source
#
# Node n'est pas une dépendance du projet : la CLI Tailwind tourne dans un
# conteneur jetable, et seul le CSS compilé (celui que la page sert) est
# versionné. La version est figée ici : c'est celle de l'en-tête du fichier
# compilé ; la changer revient à changer le rendu de tout le site.
#
# Tailwind doit résoudre `@import "tailwindcss"` depuis un node_modules : il
# est installé dans /tmp/tw (dans le conteneur), et le dossier css du dépôt y
# est relié par un lien symbolique, pour ne rien créer dans le dépôt.
set -e
cd "$(dirname "$0")/.."
TAILWIND_VERSION=4.3.3
run() {
  docker run --rm --init --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work \
    node:22-slim sh -c "mkdir /tmp/tw && cd /tmp/tw \
      && npm install --silent --no-audit --no-fund tailwindcss@$TAILWIND_VERSION @tailwindcss/cli@$TAILWIND_VERSION \
      && ln -s /work/frontend/static/css /tmp/tw/css && cd /work \
      && /tmp/tw/node_modules/.bin/tailwindcss -i /tmp/tw/css/design-system.css -o frontend/static/vendor/tailwind.min.css $1"
}
case "${1:-build}" in
  build) run "--minify" ;;
  watch) run "--minify --watch=always" ;;
  *) echo "usage: $0 build|watch" >&2; exit 1 ;;
esac
