#!/bin/sh
# Tests automatisés (tests/).
#
#   tools/test.sh            joue toute la suite
#   tools/test.sh -k roles   arguments passés tels quels à pytest
#
# Rien à installer sur la machine hors Docker : une base PostgreSQL jetable
# (service db-test, profil "test") et un conteneur Python jetable (service
# test) tournent le temps de la suite, puis sont supprimés. Les dépendances de
# développement (requirements-dev.txt) ne sont jamais dans l'image de
# l'application. PostgreSQL est indispensable (crud.py utilise date_trunc,
# extract, ilike) : pas de repli sur SQLite.
set -e
cd "$(dirname "$0")/.."
status=0
if [ "$#" -gt 0 ]; then
  docker compose --profile test run --rm test sh -c 'pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -p no:cacheprovider "$@"' pytest "$@" || status=$?
else
  docker compose --profile test run --rm test || status=$?
fi
# "rm" plutôt que "down" : "down" arrêterait aussi l'application et sa base si
# elles tournent dans ce même projet Compose.
docker compose --profile test rm -sf db-test test >/dev/null 2>&1
exit $status
