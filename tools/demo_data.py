"""A realistic demo household for Twiga, to review the screens and test a pull request.

    DEMO_PASSWORD=... python -m tools.demo_data [--reset-demo]

(see tools/demo-data.sh, which runs it in the application container.)

The household is the one of the mockups: three accounts (alex, sam, lea), three
bank accounts, a two-level category tree, six months of bank operations up to
today, La Savane waiting to be sorted, rules, budgets, a fixed Cap for last
month, projects, pending cheques, a detailed receipt and a list of imports.

Everything goes through the models and the functions of the application
(crud.py): the operations enter through the import path (payment method
detection, internal transfers, cheque matching) and are filed with
`categorize_transaction`, the rules and the rule suggestions are created the way
the screens create them. The data is deterministic: a fixed seed, dates relative
to today, so the same day gives the same household.

Safety. The script only runs on a database without any operation (and without
accounts or categories): it must never touch a real database. `--reset-demo`
empties the database first, and is accepted only when the database holds nothing
but the demo data this script created: it left a marker (the note of the account
"Compte courant", with a fingerprint of the users, the accounts and the number of
operations). Anything that changed those three things makes it refuse.

The texts of the data set are French, like the rest of the demo; the messages of
this tool are English, it is a development tool.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

SEED = 20240611
MONTHS = 6  # calendar months, the current (partial) one included
RECENT_DAYS = 11  # the latest days are left to La Savane, no filed variable operation

MARKER_NOTE = "Données de démonstration"
MAIN_ACCOUNT = "Compte courant"
JOINT_ACCOUNT = "Compte joint"
SAVINGS_ACCOUNT = "Livret"

# The balance each account should have today; the opening balances are derived.
TARGET_BALANCES = {
    "cc": Decimal("3412.76"),
    "joint": Decimal("1847.30"),
    "livret": Decimal("12400.00"),
}
ACCOUNTS = {
    "cc": (MAIN_ACCOUNT, "courant", "#2f6f5e"),
    "joint": (JOINT_ACCOUNT, "courant", "#b5651d"),
    "livret": (SAVINGS_ACCOUNT, "livret", "#3b6ea5"),
}

USERS = (
    ("alex", "Alex", "admin", True),
    ("sam", "Sam", "editor", True),
    ("lea", "Léa", "viewer", False),  # never signed in
)

# (name, pillar, excluded from budgets, [(sub-category, pillar override)])
CATEGORIES = [
    ("Alimentation", "essentiel", False, [("Courses", None), ("Boulangerie", None), ("Primeur", None)]),
    ("Logement", "essentiel", False, [("Loyer", None), ("Énergie", None), ("Internet", None), ("Ameublement", "choix")]),
    ("Transport", "essentiel", False, [("Carburant", None), ("Train", None), ("Péage", None)]),
    ("Santé", "essentiel", False, [("Pharmacie", None), ("Médecin", None), ("Mutuelle", None)]),
    ("Loisirs", "choix", False, [("Sport", None), ("Culture", None), ("Presse", None), ("Streaming", None)]),
    ("Sorties", "choix", False, [("Restaurant", None), ("Cinéma", None), ("Bar", None)]),
    ("Épargne", "choix", False, [("Virement livret", None)]),
    ("Retraits", "choix", False, [("Espèces", None)]),
    ("Revenus", None, True, [("Salaire", None), ("Remboursement", None), ("Allocations", None)]),
]

# (bank keyword, (parent, child), payment method) — the rules of the household.
RULES = [
    ("CARREFOUR", ("Alimentation", "Courses"), "CB"),
    ("BOULANGERIE", ("Alimentation", "Boulangerie"), "CB"),
    ("PHARMACIE", ("Santé", "Pharmacie"), "CB"),
    ("SNCF", ("Transport", "Train"), None),
    ("EDF", ("Logement", "Énergie"), "Prélèvement"),
    ("FREE TELECOM", ("Logement", "Internet"), "Prélèvement"),
    ("BASIC FIT", ("Loisirs", "Sport"), "Prélèvement"),
    ("SPOTIFY", ("Loisirs", "Streaming"), None),
    ("NETFLIX", ("Loisirs", "Streaming"), "CB"),
    ("RETRAIT DAB", ("Retraits", "Espèces"), "Espèces"),
    ("SALAIRE", ("Revenus", "Salaire"), "Virement"),
    ("CAF ALLOCATIONS", ("Revenus", "Allocations"), "Virement"),
]

# Rules Twiga proposes and nobody has answered yet: (label, category, times seen).
RULE_SUGGESTIONS = [
    ("Lidl", ("Alimentation", "Courses"), 5),
    ("Leclerc", ("Alimentation", "Courses"), 4),
    ("TotalEnergies", ("Transport", "Carburant"), 3),
]

# Monthly budgets per top-level category, for the months -2, -1 and 0.
BUDGETS = {
    "Alimentation": (820, 840, 850),
    "Logement": (1280, 1290, 1290),
    "Transport": (330, 340, 340),
    "Santé": (180, 190, 190),
    "Loisirs": (140, 150, 150),
    "Sorties": (300, 310, 320),
    "Retraits": (120, 120, 120),
}

# The detailed receipt: (label, amount, shelf).
RECEIPT_LINES = [
    ("Tomates grappe", "3.42", "fruits_legumes"),
    ("Bananes", "2.18", "fruits_legumes"),
    ("Courgettes", "2.96", "fruits_legumes"),
    ("Pommes Gala", "3.89", "fruits_legumes"),
    ("Baguette tradition", "1.35", "pains_patisseries"),
    ("Pâtes penne", "1.89", "epicerie_salee"),
    ("Riz basmati", "3.45", "epicerie_salee"),
    ("Sauce tomate", "2.20", "epicerie_salee"),
    ("Biscuits sablés", "2.65", "epicerie_sucree"),
    ("Confiture de fraises", "2.95", "epicerie_sucree"),
    ("Poulet fermier", "8.76", "viandes_poissons"),
    ("Saumon fumé", "5.49", "viandes_poissons"),
    ("Lait demi-écrémé x6", "7.14", "laitiers_oeufs"),
    ("Oeufs x12", "3.28", "laitiers_oeufs"),
    ("Emmental râpé", "2.39", "laitiers_oeufs"),
    ("Yaourts nature", "3.12", "laitiers_oeufs"),
    ("Jambon blanc", "3.89", "charcuterie_traiteur"),
    ("Pizza surgelée", "4.58", "surgeles"),
    ("Petits pois surgelés", "1.95", "surgeles"),
    ("Jus d'orange", "2.49", "boissons"),
    ("Eau gazeuse x6", "3.30", "boissons"),
    ("Bière blonde x6", "6.60", "boissons"),
    ("Shampooing", "3.99", "hygiene_beaute"),
    ("Dentifrice", "2.45", "hygiene_beaute"),
    ("Liquide vaisselle", "2.15", "entretien_nettoyage"),
    ("Essuie-tout", "3.20", "entretien_nettoyage"),
    ("Ampoule LED", "4.50", "maison_loisirs"),
]


class DemoRefused(Exception):
    """The run is refused: the message says why."""


# --- The operations --------------------------------------------------------


@dataclass
class Op:
    day: date
    account: str  # key of ACCOUNTS
    raw: str  # the label as the bank writes it
    amount: Decimal
    label: str | None = None  # the clean label the household gave it
    category: tuple[str, str] | None = None
    payment: str | None = None  # None: detected from the bank label
    unexpected: bool = False
    pair: str | None = None  # the two legs of an internal transfer share it
    pending: bool = False  # left in La Savane
    receipt: bool = False
    cheque: bool = False  # settles a pending cheque, matched by the import


def money(rng: random.Random, low: float, high: float) -> Decimal:
    return Decimal(str(round(rng.uniform(low, high), 2))).quantize(Decimal("0.01"))


def month_start(today: date, offset: int) -> date:
    index = today.year * 12 + today.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def month_end(first: date) -> date:
    return first.replace(day=monthrange(first.year, first.month)[1])


def spread(rng: random.Random, first: date, count: int, today: date) -> list[date]:
    """`count` dates in the month (fewer in the current one), none in the recent days."""
    end = month_end(first)
    limit = min(end, today - timedelta(days=RECENT_DAYS))
    if limit < first:
        return []
    span = (limit - first).days + 1
    wanted = count if limit == end else round(count * span / monthrange(first.year, first.month)[1])
    return sorted(first + timedelta(days=rng.randrange(span)) for _ in range(wanted))


# (bank label, clean label, price range, weight): the shops of each category.
GROCERIES = [
    ("CB CARREFOUR MARKET", "Carrefour Market", (24, 96), 4),
    ("CB LECLERC", "Leclerc", (35, 130), 3),
    ("CB LIDL", "Lidl", (12, 58), 4),
    ("CB INTERMARCHE", "Intermarché", (20, 70), 2),
]
BAKERIES = [
    ("CB BOULANGERIE LA FOURNEE", "Boulangerie La Fournée", (2.4, 9.5), 3),
    ("CB PAUL", "Paul", (3.0, 12.0), 1),
]
GREENGROCERS = [("CB PRIMEUR DU MARCHE", "Primeur du marché", (8, 26), 1)]
FUEL = [("CB TOTALENERGIES", "TotalEnergies", (42, 68), 3), ("CB STATION U", "Station U", (38, 62), 2)]
TRAINS = [("CB SNCF CONNECT", "SNCF Connect", (18, 74), 1)]
TOLLS = [("CB APRR PEAGE", "Péage APRR", (6.4, 18.2), 1)]
PHARMACIES = [("CB PHARMACIE CENTRALE", "Pharmacie centrale", (4.5, 31), 1)]
DOCTORS = [("CB DR LEFEBVRE", "Dr Lefebvre", (26.5, 30), 1)]
SPORT = [("CB DECATHLON", "Decathlon", (12, 80), 1)]
CULTURE = [("CB FNAC", "Fnac", (9, 32), 1)]
RESTAURANTS = [
    ("CB BRASSERIE DES ARCADES", "Brasserie des Arcades", (28, 85), 2),
    ("CB PIZZERIA DA LUIGI", "Pizzeria Da Luigi", (22, 54), 2),
    ("CB SUSHI SHOP", "Sushi Shop", (24, 48), 1),
    ("CB UBER EATS", "Uber Eats", (15, 38), 1),
]
CINEMAS = [("CB CINEMA LE REGENT", "Cinéma Le Régent", (9.5, 24), 1)]
BARS = [("CB BAR LE MARIN", "Bar Le Marin", (6, 28), 2), ("CB CAFE DE LA PLACE", "Café de la Place", (4.8, 16), 2)]
FURNISHING = [("CB IKEA", "Ikea", (35, 190), 2), ("CB LEROY MERLIN", "Leroy Merlin", (20, 120), 2)]


def pick(rng: random.Random, shops: list) -> tuple:
    return rng.choices(shops, weights=[shop[3] for shop in shops])[0]


def shop_ops(
    rng: random.Random, first: date, today: date, account: str, shops: list,
    low: int, high: int, category: tuple[str, str], minimum: int = 0,
) -> list[Op]:
    ops = []
    for when in spread(rng, first, max(rng.randint(low, high), minimum), today):
        raw, label, (cheap, dear), _weight = pick(rng, shops)
        ops.append(Op(when, account, raw, -money(rng, cheap, dear), label, category))
    return ops


def monthly_ops(rng: random.Random, first: date, offset: int, today: date) -> list[Op]:
    """What one month of the household looks like, up to today."""
    ops: list[Op] = []

    def fixed(day: int, account: str, raw: str, amount: str | Decimal, label: str, category, **extra) -> None:
        when = first.replace(day=min(day, monthrange(first.year, first.month)[1]))
        if when <= today:
            ops.append(Op(when, account, raw, Decimal(amount), label, category, **extra))

    # Income and standing orders of the main account.
    fixed(2, "cc", "VIR SEPA SALAIRE ALEX", "2140.00", "Salaire Alex", ("Revenus", "Salaire"))
    fixed(4, "cc", "VIR SEPA SALAIRE SAM", "1780.00", "Salaire Sam", ("Revenus", "Salaire"))
    fixed(6, "cc", "VIR SEPA CAF ALLOCATIONS", "96.30", "Allocation logement", ("Revenus", "Allocations"))
    fixed(5, "cc", "PRLV SEPA LOYER SCI DES FILAOS", "-1060.00", "Loyer", ("Logement", "Loyer"))
    fixed(8, "cc", "PRLV SEPA EDF", -money(rng, 72, 77), "EDF", ("Logement", "Énergie"))
    fixed(10, "cc", "PRLV SEPA FREE TELECOM", "-29.99", "Box internet", ("Logement", "Internet"))
    fixed(12, "cc", "PRLV SEPA ORANGE MOBILE", "-12.99", "Forfait mobile", ("Logement", "Internet"))
    fixed(3, "cc", "PRLV SEPA MUTUELLE MGEN", "-58.20", "Mutuelle", ("Santé", "Mutuelle"))
    fixed(9, "cc", "PRLV SEPA BASIC FIT", "-24.99", "Salle de sport", ("Loisirs", "Sport"))
    fixed(14, "cc", "PRLV SEPA SPOTIFY", "-10.99", "Spotify", ("Loisirs", "Streaming"))
    # The same service billed a second time, under another bank label.
    fixed(15, "cc", "CB SPOTIFY AB SE STOCKHOLM SUEDE", "-10.99", "Spotify AB", ("Loisirs", "Streaming"))
    fixed(18, "cc", "CB NETFLIX INTERNATIONAL", "-13.49", "Netflix", ("Loisirs", "Streaming"))
    fixed(20, "cc", "PRLV SEPA LE MONDE", "-11.99", "Le Monde", ("Loisirs", "Presse"))

    # Internal transfers: to the joint account and to the savings book.
    for key, raw_out, raw_in, label_out, label_in, day, amount in (
        ("joint", "VIR SEPA VERS COMPTE JOINT", "VIR SEPA RECU COMPTE COURANT", "Virement vers le compte joint",
         "Virement du compte courant", 3, "1150.00"),
        ("livret", "VIR SEPA VERS LIVRET", "VIR SEPA RECU COMPTE COURANT", "Virement vers le Livret",
         "Virement du compte courant", 7, "700.00"),
    ):
        when = first.replace(day=day)
        if when <= today:
            category = ("Épargne", "Virement livret") if key == "livret" else None
            ops.append(Op(when, "cc", raw_out, -Decimal(amount), label_out, category, pair=f"{key}-{first}"))
            ops.append(Op(when + timedelta(days=1 if key == "livret" else 0), key, raw_in, Decimal(amount),
                          label_in, category, pair=f"{key}-{first}"))

    # The variable spending. Groceries and the like are paid from the joint account.
    ops += shop_ops(rng, first, today, "joint", GROCERIES, 13, 17, ("Alimentation", "Courses"))
    ops += shop_ops(rng, first, today, "joint", BAKERIES, 8, 11, ("Alimentation", "Boulangerie"))
    ops += shop_ops(rng, first, today, "joint", GREENGROCERS, 2, 4, ("Alimentation", "Primeur"), minimum=1)
    ops += shop_ops(rng, first, today, "cc", FUEL, 3, 4, ("Transport", "Carburant"))
    ops += shop_ops(rng, first, today, "cc", TRAINS, 1, 2, ("Transport", "Train"))
    ops += shop_ops(rng, first, today, "cc", TOLLS, 1, 3, ("Transport", "Péage"))
    ops += shop_ops(rng, first, today, "cc", PHARMACIES, 2, 3, ("Santé", "Pharmacie"))
    ops += shop_ops(rng, first, today, "cc", DOCTORS, 0, 1, ("Santé", "Médecin"))
    ops += shop_ops(rng, first, today, "cc", SPORT, 0, 1, ("Loisirs", "Sport"))
    ops += shop_ops(rng, first, today, "joint", CULTURE, 1, 2, ("Loisirs", "Culture"))
    ops += shop_ops(rng, first, today, "joint", RESTAURANTS, 4, 6, ("Sorties", "Restaurant"))
    ops += shop_ops(rng, first, today, "joint", CINEMAS, 1, 2, ("Sorties", "Cinéma"), minimum=1)
    ops += shop_ops(rng, first, today, "joint", BARS, 3, 5, ("Sorties", "Bar"))
    if offset % 2 == 0:
        ops += shop_ops(rng, first, today, "joint", FURNISHING, 1, 1, ("Logement", "Ameublement"))
    for when in spread(rng, first, rng.choice([1, 2]), today):
        ops.append(Op(when, "cc", "RETRAIT DAB CREDIT MUTUEL", -Decimal(rng.choice([20, 40, 60, 80, 100])),
                      "Retrait", ("Retraits", "Espèces")))
    if rng.random() < 0.8:
        for when in spread(rng, first, 1, today):
            ops.append(Op(when, "cc", "VIR SEPA CPAM REMBOURSEMENT", money(rng, 14.2, 23.5),
                          "Remboursement CPAM", ("Revenus", "Remboursement")))
    return ops


def special_ops(today: date) -> list[Op]:
    """The operations written by hand: unexpected ones, the bookshop, cheques, the receipt."""
    ops: list[Op] = []
    limit = today - timedelta(days=RECENT_DAYS)

    def add(offset: int, day: int, op: Op) -> None:
        first = month_start(today, offset)
        op.day = first.replace(day=min(day, monthrange(first.year, first.month)[1]))
        if op.day <= limit:
            ops.append(op)

    # Unexpected expenses of the month.
    add(-4, 12, Op(today, "joint", "CB LEROY MERLIN", Decimal("-189.00"), "Leroy Merlin",
                   ("Logement", "Ameublement"), unexpected=True))
    add(-2, 21, Op(today, "cc", "CB PHARMACIE CENTRALE", Decimal("-47.30"), "Pharmacie centrale",
                   ("Santé", "Pharmacie"), unexpected=True))
    add(-1, 9, Op(today, "cc", "CB DR LEFEBVRE", Decimal("-60.00"), "Dr Lefebvre",
                  ("Santé", "Médecin"), unexpected=True))
    add(0, 3, Op(today, "cc", "CB PHARMACIE CENTRALE", Decimal("-22.60"), "Pharmacie centrale",
                 ("Santé", "Pharmacie"), unexpected=True))

    # A bookshop filed 7 times under Culture and once under Presse (the oldest),
    # the one La Savane will ask about: "already filed there 7 times out of 8".
    schedule = [(-5, 8, "Presse"), (-5, 24, "Culture"), (-4, 15, "Culture"), (-4, 27, "Culture"),
                (-3, 11, "Culture"), (-2, 6, "Culture"), (-2, 19, "Culture"), (-1, 13, "Culture")]
    for offset, day, child in schedule:
        add(offset, day, Op(today, "joint", "CB LIBRAIRIE LE PHARE", Decimal("-19.90") - Decimal(day) / 10,
                            "Librairie Le Phare", ("Loisirs", child)))

    # Cheques that were pending and have been debited since (matched at import).
    for days_ago, number, amount, label, category in (
        (36, "0004489", "-240.00", "Chèque Menuiserie Alibé", ("Logement", "Ameublement")),
        (25, "0004497", "-60.00", "Chèque Dr Lefebvre", ("Santé", "Médecin")),
    ):
        ops.append(Op(today - timedelta(days=days_ago), "cc", f"CHEQUE {number}", Decimal(amount), label,
                      category, cheque=True))

    # The receipt: a big shop with the detail of every shelf.
    total = sum((Decimal(amount) for _, amount, _ in RECEIPT_LINES), Decimal("0.00"))
    ops.append(Op(today - timedelta(days=13), "joint", "CB CARREFOUR MARKET", -total, "Carrefour Market",
                  ("Alimentation", "Courses"), receipt=True))
    return ops


# The latest days, left to La Savane: (days ago, account, bank label, amount or range).
PENDING = [
    (0, "joint", "CB CARREFOUR MARKET", (28, 72)),  # a rule
    (0, "cc", "CB TOTALENERGIES", (44, 62)),  # the history
    (1, "joint", "CB BOULANGERIE LA FOURNEE", (3, 8)),  # a rule
    (1, "joint", "CB LIDL", (18, 55)),  # the history
    (2, "cc", "CB PHARMACIE CENTRALE", (6, 24)),  # a rule
    (2, "joint", "CB PRIMEUR DU MARCHE", (9, 22)),  # the history
    (3, "cc", "CB SNCF CONNECT", (22, 68)),  # a rule
    (3, "joint", "CB LIBRAIRIE LE PHARE", (14, 30)),  # filed 7 times out of 8: a question
    (4, "cc", "CB AMZN MKTP FR", (12, 60)),  # unknown: a question
    (5, "joint", "CB CINEMA LE REGENT", (9, 22)),  # the history
    (5, "cc", "CB PAYPAL *VINTED", (8, 40)),  # a generic payee: a question
    (6, "joint", "CB LECLERC", (38, 96)),  # the history
    (7, "joint", "CB RESTAURANT CHEZ ISA", (35, 80)),  # unknown: a question
    (7, "cc", "VIR SEPA M LEROUX PIERRE", (20, 60)),  # an unknown credit: a question
    (8, "cc", "CB STATION U", (40, 60)),  # the history
    (9, "cc", "VIR SEPA VERS LIVRET", Decimal("-400.00")),  # an internal transfer, both legs
    (9, "livret", "VIR SEPA RECU COMPTE COURANT", Decimal("400.00")),
]


def pending_ops(rng: random.Random, today: date) -> list[Op]:
    ops = []
    for days_ago, account, raw, amount in PENDING:
        if isinstance(amount, tuple):
            value = money(rng, *amount)
            amount = value if raw.startswith("VIR") else -value
        ops.append(Op(today - timedelta(days=days_ago), account, raw, amount, pending=True,
                      pair="pending-transfer" if "LIVRET" in raw or "RECU COMPTE" in raw else None))
    return ops


def keep_transfers_unambiguous(ops: list[Op]) -> None:
    """Nudge any amount that would look like the other leg of a transfer by accident.

    The import pairs a debit and a credit of two accounts within 3 days and 1 euro
    (crud.detect_transfer_matches): only the intended pairs must be found.
    """
    for index, op in enumerate(ops):
        if op.pair or op.receipt or op.cheque:  # amounts that must stay as written
            continue
        for other in ops[:index]:
            if (
                other.account != op.account
                and (other.amount > 0) != (op.amount > 0)
                and abs(abs(other.amount) - abs(op.amount)) <= 1
                and abs((other.day - op.day).days) <= 3
            ):
                op.amount += Decimal("1.37") if op.amount > 0 else Decimal("-1.37")
                break


def make_unique(ops: list[Op]) -> None:
    """No two operations with the same date, label and amount (they are matched back by that key)."""
    seen: set[tuple] = set()
    for op in ops:
        while (op.account, op.day, op.raw, op.amount) in seen:
            op.amount += Decimal("0.01") if op.amount > 0 else Decimal("-0.01")
        seen.add((op.account, op.day, op.raw, op.amount))


def build_operations(rng: random.Random, today: date) -> list[Op]:
    ops: list[Op] = []
    for offset in range(-(MONTHS - 1), 1):
        ops += monthly_ops(rng, month_start(today, offset), offset, today)
    ops += special_ops(today)
    ops += pending_ops(rng, today)
    ops.sort(key=lambda op: (op.day, op.account, op.raw))
    keep_transfers_unambiguous(ops)
    make_unique(ops)
    return ops


# --- The guard --------------------------------------------------------------


def fingerprint(db: Session) -> str:
    from backend.models import Account, Transaction, User

    usernames = sorted(db.scalars(select(User.username)))
    accounts = sorted(db.scalars(select(Account.name)))
    operations = db.scalar(select(func.count()).select_from(Transaction))
    text = "|".join([*usernames, "#", *accounts, "#", str(operations)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def demo_blocker(db: Session) -> str | None:
    """Why this database is not a pure demo database (None: it is one)."""
    from backend.models import Account

    account = db.scalars(select(Account).where(Account.name == MAIN_ACCOUNT)).first()
    notes = (account.notes or "") if account else ""
    if not notes.startswith(MARKER_NOTE):
        return "no demo marker was found: this database was not filled by this tool"
    if notes.rsplit("·", 1)[-1].strip() != fingerprint(db):
        return "the users, the accounts or the number of operations changed since the demo data was created"
    return None


def wipe(db: Session) -> None:
    """Empty every table the demo fills (payment methods, app state and settings stay)."""
    from backend.database import Base
    from backend.models import CapSettings

    keep = {"alembic_version", "payment_methods", "app_state", "cap_settings"}
    db.execute(update(CapSettings).values(income_account_id=None))
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in keep:
            db.execute(table.delete())
    db.commit()


def check_blank(db: Session) -> None:
    from backend.models import Account, Category, Transaction, User

    operations = db.scalar(select(func.count()).select_from(Transaction))
    if operations:
        raise DemoRefused(
            f"this database already holds {operations} operations; the demo data only goes in a blank database "
            "(--reset-demo replaces a database that holds nothing but demo data)"
        )
    if db.scalar(select(func.count()).select_from(Account)) or db.scalar(select(func.count()).select_from(Category)):
        raise DemoRefused("this database already holds accounts or categories; the demo data only goes in a blank database")
    users = list(db.scalars(select(User)))
    # The migrations seed one administrator "admin"; nothing else may exist yet.
    if any(user.username != "admin" or user.last_login is not None for user in users):
        raise DemoRefused("this database already holds users; the demo data only goes in a blank database")


# --- The loading ------------------------------------------------------------


def create_users(db: Session, password: str) -> None:
    from backend import crud

    # The administrator seeded by the migrations, never used, makes room for the household.
    for user in crud.list_users(db):
        if user.username == "admin" and user.last_login is None:
            crud.delete_user(db, user.id)
    now = datetime.now()
    for username, display_name, role, signed_in in USERS:
        user = crud.create_user(db, username, password, role)
        error = crud.update_user_profile(db, user.id, display_name, username)
        if error:
            raise RuntimeError(error)
        if signed_in:
            crud.touch_last_login(db, user.id)
            user.tour_seen_at = now
    db.commit()


def create_categories(db: Session) -> dict[tuple[str, str], object]:
    from backend import crud

    categories = {}
    for name, pillar, excluded, children in CATEGORIES:
        parent = crud.create_category(db, name, None)
        crud.update_category_pillar(db, parent, pillar)
        if excluded:
            crud.update_category_budget_exclusion(db, parent, True)
        categories[(name, "")] = parent
        for child_name, override in children:
            child = crud.create_category(db, child_name, parent)
            if override:
                crud.update_category_pillar(db, child, override)
            categories[(name, child_name)] = child
    return categories


def insert_history(db: Session, ops: list[Op], accounts: dict) -> dict[int, object]:
    """Bring the filed operations in through the import path; returns the rows by index of `ops`."""
    from backend import crud
    from backend.models import Transaction
    from imports.common import ParsedTransaction

    history = [op for op in ops if not op.pending]
    for key, account in accounts.items():
        batch = [op for op in history if op.account == key]
        crud.bulk_insert_transactions(
            db, account, [ParsedTransaction(account.name, op.day, op.raw, op.amount) for op in batch]
        )
    db.commit()
    rows = {}
    for key, account in accounts.items():
        by_key = {
            (row.date, row.raw_label, row.amount): row
            for row in db.scalars(select(Transaction).where(Transaction.account_id == account.id))
        }
        for index, op in enumerate(ops):
            if op.account == key and not op.pending:
                rows[index] = by_key[(op.day, op.raw, op.amount)]
    return rows


def file_history(db: Session, ops: list[Op], rows: dict, categories: dict) -> None:
    """Sort what the import left: categorize with the app function, relabel the transfers and cheques."""
    from backend import crud

    valid_methods = set(crud.get_payment_methods_dict(db))
    for index, row in rows.items():
        op = ops[index]
        category = categories[op.category] if op.category else None
        payment = op.payment if op.payment in valid_methods else None
        if row.is_transfer:
            crud.mark_transaction_as_transfer(db, row, label=op.label)
            if category is not None:
                crud.bulk_update_transactions(db, [row], category=category)
        elif row.validated:  # a cheque matched at import
            crud.categorize_transaction(db, row, categories[op.category], label=op.label)
        elif category is not None:
            crud.categorize_transaction(
                db, row, category, label=op.label, payment_method=payment, is_unexpected=True if op.unexpected else None
            )
        if op.receipt:
            crud.bulk_add_receipt_items(
                db, row.id,
                [{"label": label, "amount": Decimal(amount), "family": family} for label, amount, family in RECEIPT_LINES],
            )


def insert_pending(db: Session, ops: list[Op], accounts: dict) -> None:
    """The operations of La Savane: as an import leaves them, not filed and not paired."""
    from backend.models import Transaction
    from backend.payment_methods import detect_payment_from_label

    for op in ops:
        if op.pending:
            db.add(Transaction(
                date=op.day, label=op.raw, raw_label=op.raw, amount=op.amount, account_id=accounts[op.account].id,
                validated=False, payment_method=detect_payment_from_label(op.raw),
            ))
    db.commit()


def create_pending_cheques(db: Session, today: date, categories: dict, accounts: dict) -> None:
    from backend import crud

    account = accounts["cc"]
    # The two debited ones first (the import matches them), then the three still waiting.
    for days_ago, number, amount, recipient, category in (
        (48, "0004489", "240.00", "Menuiserie Alibé", ("Logement", "Ameublement")),
        (33, "0004497", "60.00", "Dr Lefebvre", ("Santé", "Médecin")),
        (12, "0004506", "85.00", "Cours de yoga", ("Loisirs", "Sport")),
        (5, "0004519", "128.90", "Optique du port", ("Santé", "Médecin")),
        (2, "0004523", "36.00", "Association Escale", ("Loisirs", "Culture")),
    ):
        crud.create_pending_check(
            db, Decimal(amount), today - timedelta(days=days_ago), categories[category], account,
            check_number=number, recipient=recipient,
        )


def create_rules(db: Session, categories: dict) -> None:
    from backend import crud

    valid_methods = set(crud.get_payment_methods_dict(db))
    for keyword, category, payment in RULES:
        crud.create_rule(db, keyword, categories[category], payment if payment in valid_methods else None)
    for label, category, times in RULE_SUGGESTIONS:
        for _ in range(times):
            crud.record_rule_suggestion(db, label, categories[category].id)


def create_budgets_and_cap(db: Session, today: date, categories: dict) -> None:
    from backend import crud

    for position, offset in enumerate((-2, -1, 0)):
        crud.save_budgets(
            db, month_start(today, offset),
            {categories[(name, "")].id: Decimal(amounts[position]) for name, amounts in BUDGETS.items()},
        )
    # The Cap of last month is fixed, with its review and its intention; this month's is not.
    last = month_start(today, -1)
    planned = crud.get_pillar_budget_sums(db, last)
    crud.save_cap_entry(
        db, last,
        planned_income=crud.get_income_prefill(db, last),
        planned_essentiel=planned["essentiel"],
        planned_choix=planned["choix"],
        planned_imprevu=Decimal("150.00"),
        savings_goal=Decimal("600.00"),
        intention="Moins de repas à emporter, et mettre 600 € de côté sans y toucher.",
        reflection_unexpected="Le chauffe-eau a lâché : 189 € de plomberie qu'on n'avait pas prévus.",
        reflection_regret="Trop de sorties en fin de mois, surtout les commandes le week-end.",
        reflection_proud="Le virement vers le Livret est parti dès le début du mois, sans y penser.",
        reflection_worked_well="Faire les courses au drive avec une liste : moins de tickets, moins d'écart.",
    )


def create_projects(db: Session, today: date, accounts: dict) -> None:
    from backend import crud
    from backend.models import ProjectMovement

    # (name, target, deadline in months, deposit, deposits, days since the last one, spent)
    plans = (
        ("Vacances en Bretagne", "2400.00", 8, "250.00", 6, 4, ("-180.00", "Acompte pour le gîte")),  # ahead
        ("Canapé", "1800.00", 3, "90.00", 5, 6, None),  # behind
        ("Vélo électrique", "1200.00", 1, "200.00", 6, 9, None),  # reached
    )
    for name, target, months, deposit, deposits, last_gap, spent in plans:
        deadline = month_end(month_start(today, months))
        project = crud.create_project(db, name, Decimal(target), deadline, Decimal("0.00"))
        total = Decimal("0.00")
        for step in range(deposits):
            when = today - timedelta(days=last_gap + 30 * step)
            account = accounts["livret"] if step % 2 == 0 else accounts["cc"]
            db.add(ProjectMovement(project_id=project.id, date=when, amount=Decimal(deposit),
                                   note="Versement mensuel", account_id=account.id))
            total += Decimal(deposit)
        if spent:
            db.add(ProjectMovement(project_id=project.id, date=today - timedelta(days=40),
                                   amount=Decimal(spent[0]), note=spent[1]))
            total += Decimal(spent[0])
        project.current_amount = total
        db.commit()


def create_import_logs(db: Session, rng: random.Random, today: date, ops: list[Op], accounts: dict) -> None:
    """One import per account and month, as the statements were brought in."""
    from backend import crud

    slugs = {"cc": "compte-courant", "joint": "compte-joint", "livret": "livret"}
    for offset in range(-(MONTHS - 1), 1):
        first = month_start(today, offset)
        done_on = min(month_end(first) + timedelta(days=1), today - timedelta(days=1))
        for key, account in accounts.items():
            count = sum(1 for op in ops if op.account == key and op.day.replace(day=1) == first and not op.pending)
            if offset == 0:
                count += sum(1 for op in ops if op.account == key and op.pending)
            duplicates = rng.randint(1, 4) if offset > -(MONTHS - 1) else 0
            log = crud.record_import_log(
                db, f"releve_{slugs[key]}_{first:%Y-%m}.csv", account.name, count + duplicates, duplicates, count
            )
            log.imported_on = done_on
    db.commit()


def settle_recurring_decisions(db: Session, today: date) -> None:
    """Confirm the obvious subscriptions, ignore nothing: the duplicate stays to be merged."""
    from backend import crud

    for pattern in crud.detect_recurring_patterns(db, today):
        if pattern["label_pattern"] in ("NETFLIX INTERNATIONAL", "FREE TELECOM", "MUTUELLE MGEN", "LOYER SCI DES FILAOS"):
            crud.set_recurring_pattern_status(
                db, pattern["label_pattern"], pattern["amount"], pattern["frequency_days"],
                pattern["category"].id if pattern["category"] else None, "confirmed",
            )


def load(db: Session, password: str, today: date | None = None) -> dict:
    """Fill a blank database with the demo household; returns the figures of what was created."""
    from backend import crud, savane
    from backend.models import ProjectMovement, Transaction

    today = today or date.today()
    rng = random.Random(SEED)
    ops = build_operations(rng, today)

    create_users(db, password)
    categories = create_categories(db)

    # The opening balance of each account is what makes today's balance the wanted one.
    accounts = {}
    for key, (name, kind, color) in ACCOUNTS.items():
        net = sum((op.amount for op in ops if op.account == key), Decimal("0.00"))
        accounts[key] = crud.create_account(db, name, kind, TARGET_BALANCES[key] - net, color=color)

    create_rules(db, categories)
    create_pending_cheques(db, today, categories, accounts)
    rows = insert_history(db, ops, accounts)
    file_history(db, ops, rows, categories)
    insert_pending(db, ops, accounts)
    create_budgets_and_cap(db, today, categories)
    create_projects(db, today, accounts)
    create_import_logs(db, rng, today, ops, accounts)
    settle_recurring_decisions(db, today)

    # The marker comes last: its fingerprint covers what the guard checks later.
    main = accounts["cc"]
    crud.update_account(db, main, main.name, main.type, main.balance, main.color,
                        f"{MARKER_NOTE} · {fingerprint(db)}")

    split = savane.pending_split(db)
    return {
        "users": len(USERS),
        "accounts": len(accounts),
        "categories": len(categories),
        "operations": db.scalar(select(func.count()).select_from(Transaction)),
        "waiting": crud.count_pending_transactions(db),
        "lot": len(split["lot"]),
        "questions": len(split["questions"]),
        "rules": len(RULES),
        "rule_suggestions": crud.count_pending_rule_suggestions(db),
        "pending_cheques": len(crud.get_outstanding_pending_checks(db)),
        "matched_cheques": len(crud.get_matched_pending_checks(db)),
        "project_movements": db.scalar(select(func.count()).select_from(ProjectMovement)),
    }


def run(db: Session, password: str, reset: bool = False, today: date | None = None) -> dict:
    """The guarded entry point: refuses anything but a blank database (or a pure demo one with `reset`)."""
    from backend.models import Account, Transaction

    if reset:
        holds_data = db.scalar(select(func.count()).select_from(Transaction)) or db.scalar(
            select(func.count()).select_from(Account)
        )
        if holds_data:
            reason = demo_blocker(db)
            if reason:
                raise DemoRefused(f"--reset-demo refused: {reason}")
            wipe(db)
    check_blank(db)
    return load(db, password, today)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.demo_data",
        description="Fill a blank Twiga database with a demo household. The password of the three demo "
        "accounts (alex, sam, lea) is read from the DEMO_PASSWORD environment variable.",
    )
    parser.add_argument(
        "--reset-demo", action="store_true",
        help="empty the database first; only accepted when it holds nothing but the demo data this tool created",
    )
    args = parser.parse_args(argv)

    password = os.environ.get("DEMO_PASSWORD", "")
    if not password:
        print("DEMO_PASSWORD is required: it is the password of the demo accounts.", file=sys.stderr)
        return 2

    from backend.database import SessionLocal

    with SessionLocal() as db:
        try:
            summary = run(db, password, reset=args.reset_demo)
        except DemoRefused as error:
            print(f"Refused: {error}", file=sys.stderr)
            return 1
    print("Demo data created:")
    for name, value in summary.items():
        print(f"  {name.replace('_', ' ')}: {value}")
    print("Sign in as alex (administrator), sam (editor) or lea (read-only) with the DEMO_PASSWORD you gave.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
