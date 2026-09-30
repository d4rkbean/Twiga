#!/bin/sh
set -e

python <<'PY'
import os
import sys
import time

import psycopg2

url = os.environ["DATABASE_URL"]

for attempt in range(30):
    try:
        conn = psycopg2.connect(url)
        conn.close()
        break
    except psycopg2.OperationalError:
        print("Waiting for the database...", file=sys.stderr)
        time.sleep(1)
else:
    print("Could not reach the database.", file=sys.stderr)
    sys.exit(1)
PY

alembic upgrade head

exec "$@"
