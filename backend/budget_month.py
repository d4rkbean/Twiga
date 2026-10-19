"""The budget month: THE reference for "this month", "last month", "next month".

A household can start its budget month on the 1st, 5th, 10th or 15th
(Paramètres > Préférences > "Début du mois budgétaire", stored in
cap_settings.budget_start_day). Every screen asks this module for the period
it works on instead of computing a calendar month by itself.

Convention: a budget month is named after the calendar month it STARTS in.
With a start on the 10th, "Septembre" runs from 10 September to 9 October.
That is also the month holding the majority of its days (the start day never
goes past the 15th), with no tie to break, and it keeps the key already used
to store budgets and Le Cap entries (the first day of the named month).

With the 1st, a budget month is exactly the calendar month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from backend.dates import month_label, shift_month

# Days a budget month can start on (Paramètres > Préférences).
BUDGET_START_DAYS = (1, 5, 10, 15)


@dataclass(frozen=True)
class BudgetPeriod:
    month: date  # first day of the month it is named after (budgets, Le Cap)
    start: date  # first day included
    end: date  # first day of the next period (excluded)

    @property
    def last_day(self) -> date:
        # Inclusive bound, the one month_range() gives and the queries expect.
        return self.end - timedelta(days=1)

    @property
    def label(self) -> str:
        return month_label(self.month.year, self.month.month)

    def shifted(self, delta: int) -> "BudgetPeriod":
        shifted = shift_month(self.month, delta)
        return period_of_month(shifted.year, shifted.month, self.start.day)


def period_of_month(year: int, month: int, start_day: int = 1) -> BudgetPeriod:
    """The budget month named after (year, month)."""
    named = date(year, month, 1)
    following = shift_month(named, 1)
    return BudgetPeriod(
        month=named,
        start=named.replace(day=start_day),
        end=following.replace(day=start_day),
    )


def period_containing(day: date, start_day: int = 1) -> BudgetPeriod:
    """The budget month a date falls in."""
    named = day.replace(day=1) if day.day >= start_day else shift_month(day, -1)
    return period_of_month(named.year, named.month, start_day)


def period_spanning(start: date, end: date, start_day: int = 1) -> BudgetPeriod | None:
    """The budget month running exactly from start to end (both included), or None."""
    period = period_containing(start, start_day)
    return period if (period.start, period.last_day) == (start, end) else None
