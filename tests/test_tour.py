"""The guided tour takes every visible text from the server, translated."""

from tests.conftest import ROOT


def test_the_progress_label_comes_from_the_template(clients):
    html = clients["admin"].get("/dashboard").text
    assert 'data-progress-label="Étape {step} sur {total}"' in html


def test_the_tour_script_holds_no_french_text():
    script = (ROOT / "frontend/static/js/tour.js").read_text(encoding="utf-8")
    assert "Étape" not in script
