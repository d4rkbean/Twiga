"""Lot 5, group C: Import in the other way (one file, one confirmation)."""

import re
from datetime import date

import pytest

from backend import answers, import_recap
from backend.formatting import format_integer
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)


# --- The sentences ------------------------------------------------------------


def test_the_drop_screen_says_one_file_is_enough_or_asks_for_a_homebank_history_first():
    assert answers.import_idle_answer(True).title == "Un fichier suffit, Twiga reconnaît le reste."
    assert "HomeBank" in answers.import_idle_answer(False).title


def test_the_recap_names_the_account_the_count_and_the_duplicates():
    result = answers.import_recap_answer("csv", "Compte courant", 23, 3, ";")

    assert result.title == "Compte courant : 23 opérations à importer."
    assert "points-virgules" in result.detail and "3 doublons" in result.detail
    assert answers.import_recap_answer("ofx", "Livret", 1, 0).title == "Livret : 1 opération à importer."
    assert "déjà en base" in answers.import_recap_answer("csv", "Livret", 0, 4).title


def test_a_homebank_history_is_told_with_its_accounts_categories_and_operations():
    result = answers.import_qif_answer(3, 24, 1482, 72, 1)

    assert result.title == f"Un historique HomeBank : 3 comptes, 24 catégories, {format_integer(1482)} opérations."
    assert "72 doublons" in result.detail and "crée les comptes" in result.detail


@pytest.mark.parametrize("count, minutes", [(1, 1), (14, 2), (30, 3), (95, 10)])
def test_the_time_to_sort_follows_thirty_operations_in_three_minutes(count, minutes):
    assert answers.minutes_to_sort(count) == minutes


def test_the_result_says_what_waits_in_la_savane():
    text = answers.import_result_detail(23, 3, 9, 23)

    assert "23 opérations importées, 3 doublons écartés." in text
    assert "9 ont une règle" in text and "14 autres" in text and "3 minutes" in text
    assert "rien à ranger" in answers.import_result_detail(5, 0, 0, 0)


def test_whole_numbers_and_file_sizes_follow_the_chosen_format():
    from backend.formatting import _THIN_SPACE, format_integer, format_kilobytes

    assert format_integer(1482) == f"1{_THIN_SPACE}482"
    assert format_integer(7) == "7"
    assert format_kilobytes(3277) == "3,2"


# --- The helpers --------------------------------------------------------------


class Named:
    def __init__(self, name):
        self.name = name


def test_the_account_is_found_by_the_file_name_then_by_the_latest_import_then_the_first():
    accounts = [Named("Compte courant"), Named("Compte joint"), Named("Livret")]

    assert import_recap.guess_account(accounts, "compte-joint-juin.csv", []).name == "Compte joint"
    assert import_recap.guess_account(accounts, "releve.ofx", ["Livret", "Compte courant"]).name == "Livret"
    assert import_recap.guess_account(accounts, "releve.ofx", []).name == "Compte courant"
    assert import_recap.guess_account([], "releve.ofx", []) is None


def test_the_span_and_the_transfer_groups_of_a_statement():
    assert import_recap.date_span([date(2026, 9, 25), date(2026, 9, 1)]) == (date(2026, 9, 1), date(2026, 9, 25))
    assert import_recap.date_span([]) is None
    groups = import_recap.transfer_groups(
        [(date(2026, 9, 7), "Livret"), (date(2026, 9, 15), "Compte joint"), (date(2026, 9, 9), "Livret"), (date(2026, 9, 1), None)],
        "Compte courant",
    )
    assert [(g["to"], g["count"]) for g in groups] == [("Compte joint", 1), ("Livret", 2)]
    assert groups[1]["dates"] == [date(2026, 9, 7), date(2026, 9, 9)]


# --- The screen ----------------------------------------------------------------

CSV = "Date;Libellé;Montant\n01/10/2026;CB EPICERIE;-12,50\n02/10/2026;VIR SALAIRE;1500,00\n"


def recap_of(clients, name, content, role="admin"):
    return clients[role].post(
        "/imports/recap",
        files={"file": (name, content.encode() if isinstance(content, str) else content)},
        headers={"HX-Request": "true"},
    )


def test_the_drop_screen_is_one_zone_and_the_history(clients, other_way):
    html = page_of(clients, "admin", "/imports/new")
    body = text_of(html)

    assert "Un fichier suffit" in body and "Dépose un relevé ici" in body
    assert 'id="import-wizard"' in html and 'hx-post="/imports/recap"' in html
    assert 'id="import-next"' not in html and "Étapes de l'import" not in body  # no more steps


def test_a_csv_is_recognised_and_the_recap_waits_for_one_confirmation(clients, other_way):
    response = recap_of(clients, "releve-octobre.csv", CSV)
    body = text_of(response.text)

    assert response.status_code == 200
    assert "2 opérations à importer" in body and "CSV séparé par des points-virgules" in body
    assert "Ajuster" in body and "Voir les 2 lignes" in body and "Changer de fichier" in body
    assert 'id="import-confirm-form"' in response.text and "/execute" in response.text
    assert response.text.count('name="include"') == 2


def test_adjusting_sends_the_same_fields_again_and_keeps_the_panel_open(clients, other_way):
    first = recap_of(clients, "releve.csv", CSV).text
    import_id = re.search(r"/imports/([0-9a-f]{32})/confirm", first).group(1)
    account_id = re.search(r'name="account_id" value="(\d+)"', first).group(1)
    response = clients["admin"].post(
        f"/imports/{import_id}/confirm",
        data={"format": "csv", "account_id": account_id, "date_column": "0", "label_column": "1",
              "amount_column": "2", "date_format": "%d/%m/%Y", "adjust": "1"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "adjust: true" in response.text and "Colonne Montant" in text_of(response.text)


@pytest.mark.parametrize(
    "name, content, expected",
    [
        ("export.pdf", b"%PDF-1.4", "Format de fichier non reconnu"),
        ("archive.csv", b"x" * (5 * 1024 * 1024 + 1), "la limite est de 5 Mo"),
        ("tronque.csv", "Date;Libellé;Montant\n01/10/2026;CB X;-1,00\n02/10/2026;CB Y\n", "colonnes manquantes"),
    ],
)
def test_a_file_that_cannot_be_read_gets_a_screen_with_the_reason(clients, other_way, name, content, expected):
    response = recap_of(clients, name, content)
    body = text_of(response.text)

    assert response.status_code == 200
    assert "Je n'arrive pas à lire ce fichier." in body and expected in body and name in body
    assert "Réessayer" in body


def test_a_homebank_history_is_told_before_it_creates_anything(clients, other_way):
    qif = "!Type:Cat\nNFood\nE\n^\n!Account\nNMain\nTBank\n^\n!Type:Bank\nD01/09/2026\nT-10.00\nPShop\nLFood\n^\n"
    body = text_of(recap_of(clients, "historique.qif", qif).text)

    assert "Un historique HomeBank" in body and "Voir le détail" in body and "Importer 1 opération" in body


def test_confirming_the_import_shows_the_result_and_the_way_to_la_savane(clients, other_way):
    first = recap_of(clients, "releve.csv", "Date;Libellé;Montant\n05/10/2026;CB UNIQUE ZZ;-3,00\n").text
    import_id = re.search(r"/imports/([0-9a-f]{32})/execute", first).group(1)
    account_id = re.search(r'name="account_id" value="(\d+)"', first).group(1)
    response = clients["admin"].post(
        f"/imports/{import_id}/execute",
        data={"format": "csv", "account_id": account_id, "date_column": "0", "label_column": "1",
              "amount_column": "2", "date_format": "%d/%m/%Y", "include": ["0"]},
        headers={"HX-Request": "true"},
    )
    body = text_of(response.text)

    assert response.status_code == 200
    assert "Twiga a tout avalé" in body and "Aller à La Savane" in body and "Importer un autre fichier" in body


def test_only_an_administrator_can_use_the_one_file_import(clients, other_way):
    assert recap_of(clients, "releve.csv", CSV, role="editor").status_code == 403
