"""Access log lines without the query string.

uvicorn writes the full URL of every request to its access log: searches,
labels and amounts typed in filters end up in `docker compose logs`. The path
is kept ("GET /transactions/list HTTP/1.1" 200), everything after "?" is not.
"""

from __future__ import annotations

import logging


class QueryStringFilter(logging.Filter):
    # uvicorn's access record: args = (client, method, path with query, HTTP version, status).
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, QueryStringFilter) for existing in logger.filters):
        logger.addFilter(QueryStringFilter())
