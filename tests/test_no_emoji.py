"""No emoji in the interface texts.

Icons come from Tabler (`{{ icon('...') }}`). Emoji only appear in what a user
typed (the icon of a category, of a payment method), never in a message, a
label or a page title. The checkmarks and cross glyphs count as emoji too.
"""

import re

import pytest

from tests.conftest import ROOT
from tests.test_amber import FULL_PAGES, render
from tests.test_pages import request

PICTOGRAPH = re.compile("[↩☀-➿⭐⭕️\U0001f000-\U0001faff]")
TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def test_no_translatable_text_carries_an_emoji():
    # The template catalogue has empty translations: every non-comment line
    # is (part of) a source text.
    lines = (ROOT / "backend/locale/messages.pot").read_text(encoding="utf-8").splitlines()
    offenders = [line for line in lines if not line.startswith("#") and PICTOGRAPH.search(line)]
    assert offenders == []


@pytest.mark.parametrize("page", FULL_PAGES, ids=lambda page: page.template)
def test_page_titles_have_no_emoji(clients, demo, variant, page):
    html = render(clients, demo, page, variant).text
    match = TITLE.search(html)
    assert match and not PICTOGRAPH.search(match.group(1)), match and match.group(1)


def test_the_shell_and_the_tour_have_no_emoji(clients, demo, variant):
    # Everything the shell writes: the bars and the menus before <main>, the
    # bottom bar, and the steps of the guided tour (titles and texts).
    html = request(clients["admin"], next(page for page in FULL_PAGES if page.template == "/dashboard"), demo).text
    shell = html[: html.index("<main")] + html[html.rindex("<nav "):][:4000]
    shell = re.sub(r"<script.*?</script>|<!--.*?-->", "", shell, flags=re.S)
    assert not PICTOGRAPH.search(shell), PICTOGRAPH.search(shell).group(0)
    steps = re.search(r'data-steps="([^"]*)"', html).group(1)
    assert not PICTOGRAPH.search(steps)


def test_the_flash_fragment_carries_an_icon_and_the_text():
    from backend.templating import flash_html

    html = flash_html("success", "Saved")
    assert "<svg" in html and "Saved" in html
    assert not PICTOGRAPH.search(html)
