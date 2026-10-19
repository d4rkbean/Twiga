"""The demo data set (tools/demo_data.py): deterministic, busy enough, and every page answers with it.

The loading itself is checked in tests/demo_data_check.py, which needs a database
of its own (it empties it, and the session database holds the minimal data the
other tests rely on): this module creates a second throwaway database on the same
server, runs that file in a child pytest pointed at it, and drops it.
"""

import os
import subprocess
import sys
from datetime import date

import pytest
from sqlalchemy import text

from tests.conftest import ROOT
from tests.test_pages import PAGES

DEMO_DATABASE = "finance_demo_test"


@pytest.mark.parametrize("today", [date(2026, 10, 19), date(2026, 3, 2), date(2027, 1, 31)])
def test_the_operations_are_deterministic_and_busy(today):
    import random

    from tools import demo_data

    first = demo_data.build_operations(random.Random(demo_data.SEED), today)
    second = demo_data.build_operations(random.Random(demo_data.SEED), today)
    assert first == second, "the same day must give the same household"

    assert max(op.day for op in first) <= today
    assert min(op.day for op in first) >= demo_data.month_start(today, -(demo_data.MONTHS - 1))
    per_month: dict[date, int] = {}
    for op in first:
        per_month[op.day.replace(day=1)] = per_month.get(op.day.replace(day=1), 0) + 1
    for month, count in per_month.items():
        if month != today.replace(day=1):  # the current month is partial
            assert 60 <= count <= 90, f"{month}: {count} operations"
    assert len([op for op in first if op.pending]) == len(demo_data.PENDING)


def test_the_demo_set_loads_and_every_page_answers():
    from sqlalchemy.engine import make_url

    from backend.database import engine

    url = make_url(str(engine.url.render_as_string(hide_password=False)))
    assert url.database.endswith("_test"), "refusing to create databases next to a real one"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {DEMO_DATABASE} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {DEMO_DATABASE}"))
    try:
        environment = dict(
            os.environ,
            DATABASE_URL=url.set(database=DEMO_DATABASE).render_as_string(hide_password=False),
            DEMO_PASSWORD="demo-test-password",
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-x", "tests/demo_data_check.py"],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=900,
        )
        assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-2000:]
        # Every page of the inventory, in both interfaces, plus the content and guard checks.
        passed = int(result.stdout.rsplit(" passed", 1)[0].split()[-1])
        assert passed >= 2 * len(PAGES), result.stdout[-2000:]
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {DEMO_DATABASE} WITH (FORCE)"))
