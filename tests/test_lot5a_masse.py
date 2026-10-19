"""Traitement en masse of the other way (lot 5a): the lot by category, « Ranger ce groupe »."""

from backend.models import Transaction
from tests.conftest import switch_variant
from tests.test_lot5a_savane import other_way, shop  # noqa: F401  (fixtures)

HTMX = {"HX-Request": "true"}


def test_the_bulk_page_opens_on_the_lot_grouped_by_category(clients, other_way, shop):
    html = clients["editor"].get("/backlog").text
    assert 'id="backlog-head"' in html and "Tout ranger" in html
    assert 'id="backlog-chips"' in html and 'id="backlog-summary"' in html and 'id="backlog-sync"' in html
    assert "Lot5a parent" in html  # the group of the sure operation
    assert f'data-row-ids="{shop["sure"]}"' in html
    assert f'data-row-ids="{shop["doubtful"]}"' not in html
    assert html.count("btn-primary") == 1


def test_a_merchant_the_history_contradicts_says_why(clients, other_way, shop):
    html = clients["editor"].get("/backlog/content?suggestion_filter=all&search=zebrabooks", headers=HTMX).text
    assert f'data-row-ids="{shop["doubtful"]}"' in html
    assert "Rangée là 3 fois sur 4" in html


def test_classic_bulk_page_is_untouched(clients, demo):
    switch_variant("classic")
    html = clients["editor"].get("/backlog").text
    assert 'id="backlog-head"' not in html and 'id="backlog-bulk-d"' in html


def test_filing_a_group_answers_the_fragment_and_its_out_of_band_parts(clients, other_way, shop):
    response = clients["admin"].post(
        "/backlog/validate",
        data={"ids": str(shop["sure"]), "suggestion_filter": "sure", "page": "1"},
        headers=HTMX,
    )
    assert response.status_code == 200
    for landing in (
        "backlog-head", "backlog-chips", "backlog-confidence", "backlog-pending",
        "backlog-summary", "backlog-last-d", "backlog-sync",
    ):
        assert f'id="{landing}"' in response.text, landing
    from backend.database import SessionLocal

    with SessionLocal() as db:
        assert db.get(Transaction, shop["sure"]).category_id == shop["sure_cat"]


def test_the_sure_view_holds_only_the_lot(clients, other_way, shop):
    admin = clients["admin"]
    sure = admin.get("/backlog/content?suggestion_filter=sure", headers=HTMX).text
    assert f'data-row-ids="{shop["sure"]}"' in sure
    assert f'data-row-ids="{shop["doubtful"]}"' not in sure
    everything = admin.get("/backlog/content?suggestion_filter=all&search=zebrabooks", headers=HTMX).text
    assert f'data-row-ids="{shop["doubtful"]}"' in everything
