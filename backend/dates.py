from calendar import monthrange
from datetime import date

from backend.i18n import current_format, current_language

MONTH_NAMES_FR = [
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
]


MONTH_NAMES_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def month_names() -> list[str]:
    # Noms de mois dans la langue de la requête : MONTH_NAMES_FR sert de
    # source, le reste vient de la langue courante (voir backend/i18n.py).
    return MONTH_NAMES_EN if current_language() == "en" else MONTH_NAMES_FR


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def month_label(year: int, month: int) -> str:
    return f"{month_names()[month - 1]} {year}"


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    start, _ = month_range(year, start_month)
    _, end = month_range(year, start_month + 2)
    return start, end


def quarter_label(year: int, quarter: int) -> str:
    return f"T{quarter} {year}"


def semester_range(year: int, semester: int) -> tuple[date, date]:
    start_month = 1 if semester == 1 else 7
    start, _ = month_range(year, start_month)
    _, end = month_range(year, start_month + 5)
    return start, end


def semester_label(year: int, semester: int) -> str:
    return f"S{semester} {year}"


def year_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def year_label(year: int) -> str:
    return str(year)


def trailing_months_ending(year: int, month: int, count: int = 12) -> list[tuple[date, date, str]]:
    # Partagé entre le Dashboard et la page Rapports : les N mois civils se
    # terminant à (year, month) inclus, du plus ancien au plus récent.
    months = []
    y, m = year, month
    for _ in range(count):
        start, end = month_range(y, m)
        months.append((start, end, month_label(y, m)))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    return months


def shift_month(value: date, delta: int) -> date:
    # Décale une date "premier du mois" de `delta` mois (positif ou négatif)
    # — ex. shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1). Utilisé
    # par le "Décalage période" du rapport (recettes du mois M-1 finançant
    # les dépenses du mois M) ; // et % gèrent correctement les deltas
    # négatifs en Python (contrairement à d'autres langages).
    month_index = value.month - 1 + delta
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def months_between(start: date, end: date) -> list[tuple[date, date, str]]:
    # Tous les mois civils entre start et end (inclus), du plus ancien au
    # plus récent — contrairement à trailing_months_ending (toujours ancrée
    # sur aujourd'hui), ici bornée par la période réellement sélectionnée
    # (voir reports.py, Détail mensuel de l'onglet Balance : doit couvrir
    # TOUTE la période, mois sans transaction inclus, pas seulement les mois
    # qui tombent dans la fenêtre glissante de 12 mois de cashflow_months).
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        month_start, month_end = month_range(y, m)
        months.append((month_start, month_end, month_label(y, m)))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return months


WEEKDAY_NAMES_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
WEEKDAY_NAMES_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def format_date_long(value: date) -> str:
    # En-tête de groupe de la liste des opérations (regroupement par jour).
    # date.weekday() : lundi=0 ... dimanche=6.
    #   français        "mercredi 5 août 2026"
    #   international   "Wednesday 5 August 2026"
    #   américain       "Wednesday, August 5, 2026"
    if current_language() == "en":
        weekday = WEEKDAY_NAMES_EN[value.weekday()]
        month = MONTH_NAMES_EN[value.month - 1]
        if current_format() == "en-US":
            return f"{weekday}, {month} {value.day}, {value.year}"
        return f"{weekday} {value.day} {month} {value.year}"
    weekday = WEEKDAY_NAMES_FR[value.weekday()]
    month = MONTH_NAMES_FR[value.month - 1].lower()
    return f"{weekday} {value.day} {month} {value.year}"


# Ancien nom conservé pour les appelants existants.
format_date_long_fr = format_date_long
