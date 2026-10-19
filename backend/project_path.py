"""The path of a project towards its date (Projets, the other way).

A pure function: given today, the deadline and the month the current rhythm
reaches the target, it places the markers on a track of whole months. Every
position is a percentage of the track, so the template only writes `left:` and
`width:`; nothing is measured in the browser.

Months are the columns of the track: the marker of a month sits at the middle
of its column, so "today" is on the first column and the axis labels line up
with the markers.
"""

from __future__ import annotations

from datetime import date

from backend.dates import MONTH_ABBR_EN, MONTH_ABBR_FR
from backend.i18n import current_language

MIN_MONTHS = 12


def _index(start: date, value: date) -> int:
    return (value.year - start.year) * 12 + value.month - start.month


def project_path(today: date, target_date: date, reach: date | None, state: str) -> dict:
    """Geometry of the track.

    Returns {"months": [{"label", "initial", "year"}], "today", "deadline",
    "reach", "solid", "extra"} where the last five are percentages (None when
    the marker does not exist) and `solid` / `extra` are {"left", "width"}:
    the stretch walked at the current rhythm up to the first of the deadline
    and the reach, then the stretch between the two (dashed when the project
    is early, pale when it is late).
    """
    start = today.replace(day=1)
    deadline_index = _index(start, target_date)
    reach_index = _index(start, reach) if reach is not None else None
    span = max(MIN_MONTHS, deadline_index + 2, (reach_index + 2) if reach_index is not None else 0)
    abbreviations = MONTH_ABBR_EN if current_language() == "en" else MONTH_ABBR_FR

    months = []
    for offset in range(span):
        index = start.year * 12 + start.month - 1 + offset
        year, month = index // 12, index % 12
        label = abbreviations[month]
        months.append(
            {
                "label": label,
                "initial": label[0].upper(),
                "year": year if (offset == 0 or month == 0) else None,
            }
        )

    def place(month_index: int) -> float:
        return round((min(max(month_index, 0), span - 1) + 0.5) / span * 100, 2)

    today_at = place(0)
    deadline_at = place(deadline_index)
    reach_at = place(reach_index) if reach_index is not None else None

    solid = extra = None
    if state == "done":
        solid = {"left": today_at, "width": round(deadline_at - today_at, 2)}
    elif reach_at is not None:
        first, last = sorted((deadline_at, reach_at))
        solid = {"left": today_at, "width": round(first - today_at, 2)}
        if last > first:
            extra = {"left": first, "width": round(last - first, 2)}
    return {
        "months": months,
        "today": today_at,
        "deadline": deadline_at,
        "reach": reach_at,
        "solid": solid,
        "extra": extra,
    }
