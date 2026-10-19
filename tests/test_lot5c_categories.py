"""Lot 5, group C: Catégories in the other way (the tree and its pillars)."""

from types import SimpleNamespace

from backend import answers, categories_view
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def category(name, pillar=None, children=(), parent=None, excluded=False):
    node = SimpleNamespace(name=name, pillar=pillar, children=list(children), parent=parent, excluded_from_budget=excluded)
    for child in node.children:
        child.parent = node
    return node


def test_the_sentence_says_every_category_counts_in_a_pillar():
    full = answers.categories_answer(9, 0, 1, 1)

    assert full["phrase"] == "9 catégories, toutes rangées dans un pilier du Cap."
    assert "1 sous-catégorie a son propre pilier" in full["detail"] and "1 catégorie de revenu ne compte pas" in full["detail"]
    assert "2 sans pilier choisi : elles comptent dans Choix." in answers.categories_answer(9, 2, 0, 0)["phrase"]
    assert answers.categories_answer(1, 0, 0, 0)["phrase"].startswith("1 catégorie,")


def test_the_pillars_summary_lists_roots_and_the_sub_categories_that_moved():
    furniture = category("Mobilier", pillar="choix")
    housing = category("Logement", pillar="essentiel", children=[furniture, category("Loyer")])
    leisure = category("Loisirs", pillar="choix")
    tree = [housing, leisure, category("Divers")]

    summary = {item["code"]: item for item in categories_view.pillar_summary(tree)}

    assert summary["essentiel"]["roots"] == ["Logement"]
    assert summary["choix"]["roots"] == ["Loisirs", "Divers"]  # no pillar: Choix by default
    assert summary["choix"]["moved"] == ["Logement › Mobilier"]
    assert categories_view.overrides(tree) == [furniture]
    assert [c.name for c in categories_view.unset_roots(tree)] == ["Divers"]


def test_the_categories_screen_keeps_every_gesture(clients, other_way):
    html = page_of(clients, "admin", "/categories")
    body = text_of(html)

    for text in ("Nouvelle catégorie", "Les piliers du Cap", "Réinitialiser les piliers", "Ouvrir Le Cap", "Ajouter une sous-catégorie"):
        assert text in body, text
    for hook in ('id="categories-head"', 'id="categories-content"', 'id="categories-pillars"', "/categories/create",
                 "/edit?is_child=false", "Afficher les sous-catégories"):
        assert hook in html, hook


def test_a_category_panel_has_the_name_the_pillar_the_income_switch_and_delete(clients, other_way, demo):
    panel = clients["admin"].get(f"/categories/{demo['category_id']}/edit", headers=HX)
    body = text_of(panel.text)

    assert panel.status_code == 200
    for text in ("Nom de la catégorie", "Pilier du Cap", "Essentiel", "Choix", "Imprévus", "Revenu, pas une dépense", "Supprimer", "Fermer"):
        assert text in body, text
    assert "update-pillar" in panel.text and "panel=true" in panel.text


def test_picking_a_pillar_in_the_panel_keeps_the_panel_open(clients, other_way, demo):
    response = clients["admin"].post(
        f"/categories/{demo['category_id']}/update-pillar", params={"is_child": "false", "panel": "true"},
        data={"pillar": "essentiel"}, headers=HX,
    )

    assert response.status_code == 200 and "Pilier du Cap" in text_of(response.text)
    plain = clients["admin"].post(
        f"/categories/{demo['category_id']}/update-pillar", params={"is_child": "false"}, data={"pillar": "essentiel"}, headers=HX,
    )
    assert "Pilier du Cap" not in text_of(plain.text)  # the row alone, as in the Classic screen


def test_deleting_a_category_in_use_asks_where_to_put_what_it_holds(clients, other_way, demo):
    response = clients["admin"].get(f"/categories/{demo['subcategory_id']}/delete-confirm", params={"is_child": "true"}, headers=HX)
    body = text_of(response.text)

    assert response.status_code == 200 and "Où ranger ces éléments" in body and "Réaffecter et supprimer" in body


def test_the_head_and_the_pillars_refresh_on_their_own(clients, other_way):
    assert 'id="categories-head"' in clients["admin"].get("/categories/head", headers=HX).text
    assert 'id="categories-pillars"' in clients["admin"].get("/categories/pillars", headers=HX).text


def test_a_reader_sees_the_tree_without_the_gestures_that_write(clients, other_way):
    body = text_of(page_of(clients, "viewer", "/categories"))

    assert "Catégories" in body and "Nouvelle catégorie" not in body and "Réinitialiser les piliers" not in body
