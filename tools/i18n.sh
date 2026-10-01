#!/bin/sh
# Catalogues de traduction (voir backend/i18n.py).
#
#   tools/i18n.sh extract   régénère backend/locale/messages.pot depuis le code
#   tools/i18n.sh update    fusionne le .pot dans backend/locale/en/.../messages.po
#   tools/i18n.sh compile   compile le .po en .mo (celui que l'application lit)
#   tools/i18n.sh check     signale les textes sans traduction et les variables incohérentes
#   tools/i18n.sh all       extract + update + compile
#
# Babel n'est pas une dépendance du projet : il tourne dans un conteneur
# jetable, et seul le .mo compilé (comme tailwind.min.css) est versionné.
set -e
cd "$(dirname "$0")/.."
run() {
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work \
    python:3.12-slim sh -c "pip install -q --user babel jinja2 >/dev/null 2>&1 && PATH=/tmp/.local/bin:\$PATH $1"
}
case "${1:-all}" in
  extract) run "pybabel extract -F babel.cfg -k lazy_gettext -k _t -k ngettext --no-location --sort-output -o backend/locale/messages.pot ." ;;
  update)  run "pybabel update -i backend/locale/messages.pot -d backend/locale -l en --no-fuzzy-matching --no-location" ;;
  compile) run "pybabel compile -d backend/locale" ;;
  check)   run "python tools/i18n_check.py" ;;
  all)     "$0" extract && "$0" update && "$0" compile ;;
  *) echo "usage: $0 extract|update|compile|check|all" >&2; exit 1 ;;
esac
