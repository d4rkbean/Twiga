"""Account dots use the data palette, never amber; a colour the user chose stays."""

from types import SimpleNamespace

from backend.templating import _ACCOUNT_COLOR_PALETTE, account_color_filter

DATA_PALETTE = ["#2563eb", "#0d9488", "#9333ea", "#db2777", "#65a30d", "#ea580c", "#0891b2", "#64748b"]
AMBERS = {"#d4a96a", "#f59e0b", "#fbbf24", "#c99a58"}


def test_the_account_palette_is_the_data_palette():
    assert _ACCOUNT_COLOR_PALETTE == DATA_PALETTE


def test_a_colour_chosen_by_the_user_is_kept():
    assert account_color_filter(SimpleNamespace(color="#F59E0B", id=1)) == "#F59E0B"


def test_a_default_colour_is_never_amber():
    for account_id in range(20):
        assert account_color_filter(SimpleNamespace(color=None, id=account_id)).lower() not in AMBERS


def test_the_edit_form_starts_from_the_displayed_colour(clients, demo):
    html = clients["admin"].get(f"/accounts/{demo['account_id']}/edit", headers={"HX-Request": "true"}).text
    assert 'type="color"' in html
    assert "#d4a96a" not in html.lower().split('type="color"')[1].split(">")[0]
