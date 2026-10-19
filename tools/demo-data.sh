#!/bin/sh
# Demo household for Twiga (tools/demo_data.py): realistic data to review the
# screens and test a pull request.
#
#   DEMO_PASSWORD=... tools/demo-data.sh              fill a blank database
#   DEMO_PASSWORD=... tools/demo-data.sh --reset-demo empty a database that holds
#                                                     nothing but demo data, then fill it
#
# DEMO_PASSWORD is the password of the three demo accounts (alex, sam, lea); it is
# required and never written anywhere. The script runs in a throwaway container of
# the application (same image, same database as `docker compose up`), with the
# tools/ folder mounted since the image does not ship it. It refuses to run on a
# database that already holds operations. Pick the Compose project with
# COMPOSE_PROJECT_NAME as usual.
set -e
cd "$(dirname "$0")/.."
if [ -z "$DEMO_PASSWORD" ]; then
  echo "DEMO_PASSWORD is required: it is the password of the demo accounts." >&2
  exit 2
fi
exec docker compose run --rm -e DEMO_PASSWORD -v "$PWD/tools:/app/tools:ro" app python -m tools.demo_data "$@"
