"""No emoji in the interface texts.

Icons come from Tabler (`{{ icon('...') }}`). Emoji only appear in what a user
typed (the icon of a category, of a payment method), never in a message, a
label or a page title. The checkmarks and cross glyphs count as emoji too.
"""

import re

import pytest

from tests.conftest import ROOT
from tests.test_amber import FULL_PAGES
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
def test_page_titles_have_no_emoji(clients, demo, page):
    client = clients["anonymous"] if page.public else clients["admin"]
    html = request(client, page, demo).text
    match = TITLE.search(html)
    assert match and not PICTOGRAPH.search(match.group(1)), match and match.group(1)


def test_the_flash_fragment_carries_an_icon_and_the_text():
    from backend.templating import flash_html

    html = flash_html("success", "Saved")
    assert "<svg" in html and "Saved" in html
    assert not PICTOGRAPH.search(html)
