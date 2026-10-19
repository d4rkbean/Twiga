"""Real WCAG 2.x contrast ratios of the dark theme.

The values are read from the `.dark` block of design-system.css, not copied
here, so changing a token without checking its contrast fails this test.
"""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parent.parent / "frontend" / "static" / "css" / "design-system.css"


def dark_tokens() -> dict[str, str]:
    css = CSS.read_text()
    block = re.search(r"^\.dark \{(.*?)^\}", css, re.S | re.M).group(1)
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return dict(re.findall(r"--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def theme_tokens() -> dict[str, str]:
    css = CSS.read_text()
    block = re.search(r"@theme \{(.*?)^\}", css, re.S | re.M).group(1)
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return dict(re.findall(r"--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# (foreground, background, minimum ratio)
PAIRS = [
    ("primary", "page", 7),
    ("primary", "container", 7),
    ("primary", "sunken", 7),
    ("secondary", "page", 4.5),
    ("secondary", "container", 4.5),
    ("secondary", "sunken", 4.5),
    ("accent-ink", "container", 4.5),
    ("accent-ink", "page", 4.5),
    ("accent-ink", "accent-soft", 4.5),
    ("on-accent", "accent", 4.5),
    ("on-accent", "accent-hover", 4.5),
    ("success", "container", 4.5),
    ("warning", "container", 4.5),
    ("danger", "container", 4.5),
    ("info", "container", 4.5),
    ("success", "success-soft", 4.5),
    ("warning", "warning-soft", 4.5),
    ("danger", "danger-soft", 4.5),
    ("info", "info-soft", 4.5),
    ("border", "container", 1.5),
    ("border-strong", "container", 1.5),
    ("field", "container", 3),
    ("warning-gauge", "container", 3),
    *[(f"chart-{n}", "container", 3) for n in range(1, 9)],
]


@pytest.mark.parametrize(("foreground", "background", "minimum"), PAIRS)
def test_dark_pair_contrast(foreground, background, minimum):
    tokens = {**theme_tokens(), **dark_tokens()}
    value = ratio(tokens[foreground], tokens[background])
    assert value >= minimum, f"{foreground} on {background}: {value:.2f}:1, expected {minimum}:1"


def test_dark_theme_has_no_provisional_or_navy_value():
    css = CSS.read_text()
    block = re.search(r"^\.dark \{(.*?)^\}", css, re.S | re.M).group(1)
    assert "PROVISOIRE" not in css
    for navy in ("#0f172a", "#1e293b", "#334155"):
        assert navy not in block, navy
