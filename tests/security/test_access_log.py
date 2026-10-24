"""The access log keeps the path of a request, never its query string."""

import logging

from backend import access_log


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1:5000", "GET", path, "1.1", 200), None,
    )


def test_the_query_string_is_removed_from_an_access_line():
    record = _access_record("/transactions/list?f_search=pharmacie%20dr%20martin&f_min=-120")

    assert access_log.QueryStringFilter().filter(record) is True
    assert record.getMessage() == '192.0.2.1:5000 - "GET /transactions/list HTTP/1.1" 200'


def test_a_line_without_query_string_is_unchanged():
    record = _access_record("/dashboard")

    access_log.QueryStringFilter().filter(record)

    assert record.getMessage() == '192.0.2.1:5000 - "GET /dashboard HTTP/1.1" 200'


def test_the_filter_is_installed_once_with_the_application(security_app):
    access_log.install()

    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, access_log.QueryStringFilter)]
    assert len(filters) == 1
