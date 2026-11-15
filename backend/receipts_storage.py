"""Extraction du contenu d'un ticket/facture joint à une transaction.

Le fichier uploadé (photo ou PDF) n'est JAMAIS conservé sur disque : traité
en mémoire le temps d'en extraire les lignes (voir routers/receipts.py),
puis jeté. Seules les lignes qui en sont tirées (ReceiptItem) sont gardées
en base — une note historique, pas un original à ressortir plus tard.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from io import BytesIO


def extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ocr_variants(content: bytes):
    """Versions pré-traitées d'une photo, de la plus douce à la plus agressive.

    Papier carbone / thermique pâle : l'encre est bleutée et peu contrastée.
    Le canal ROUGE la fait ressortir (le bleu y absorbe), puis on retranche
    le fond flou pour gommer ombres et plis, et on binarise.
    """
    from PIL import Image, ImageChops, ImageFilter, ImageOps

    image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
    width = image.size[0]
    if width < 1600:  # trop petit : Tesseract lit mal sous ~25 px de haut/lettre
        ratio = 1800 / width
        image = image.resize((1800, round(image.size[1] * ratio)), Image.LANCZOS)
    else:
        image.thumbnail((2200, 2200))

    gray = ImageOps.autocontrast(image.convert("L"))
    yield gray

    red = image.split()[0]
    background = red.filter(ImageFilter.GaussianBlur(25))
    # fond - encre = « quantité d'encre » ; inversé pour retrouver du noir sur blanc.
    flat = ImageOps.invert(ImageChops.subtract(background, red))
    flat = ImageOps.autocontrast(flat, cutoff=1)
    yield flat
    yield flat.point(lambda v: 255 if v > 150 else 0)


def extract_image_text(content: bytes) -> str:
    """OCR local (Tesseract, aucune API tierce) d'une photo de ticket de caisse.

    Plusieurs pré-traitements sont essayés et on garde la lecture qui donne
    le plus de lignes d'articles exploitables. `--psm 6` : bloc de texte
    uniforme, le plus adapté à un ticket en colonne.
    """
    import pytesseract

    texts = [
        pytesseract.image_to_string(v, lang="fra", config="--psm 6")
        for v in _ocr_variants(content)
    ]
    # Totaux lus sur TOUTES les variantes : un « 26,13 » mal lu sur l'une est
    # corrigé par le « 28,13 » des autres.
    totals = set().union(*(receipt_total_candidates(t) for t in texts))
    best_text, best_score = "", None
    for text in texts:
        items = parse_receipt_lines(text)
        total = sum((i["amount"] for i in items), Decimal("0"))
        # 1) la somme retombe sur un total imprimé ; 2) plus d'articles ; 3) plus de texte.
        score = (total in totals, len(items), len(text))
        if best_score is None or score > best_score:
            best_text, best_score = text, score
    return best_text


def _normalize(text: str) -> str:
    # Majuscules, accents retirés, tirets ramenés à des espaces ("Sous-total"
    # -> "SOUS TOTAL", pour matcher le même préfixe que "Sous total" ou
    # "SOUS-TOTAL"), espaces multiples réduits — pour matcher les en-têtes de
    # rayon et les lignes de pied de facture indépendamment des accents et
    # de la ponctuation que pypdf restitue parfois différemment selon
    # l'enseigne.
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    stripped = stripped.replace("-", " ")
    return re.sub(r"\s+", " ", stripped).strip().upper()


# Les factures PDF des applications d'enseignes (constaté sur Leclerc) sont
# groupées PAR RAYON avec un en-tête "NOM DU RAYON (N produits)" au-dessus
# de chaque groupe d'articles — un signal bien plus fiable que deviner le
# rayon mot-clé par mot-clé (voir receipt_families.guess_receipt_family,
# gardé en repli quand aucun en-tête n'a encore été rencontré, ex. sur une
# facture d'une autre enseigne qui ne groupe pas ses articles ainsi).
_FAMILY_HEADERS: dict[str, str] = {
    "FRUITS LEGUMES": "fruits_legumes",
    "EPICERIE SALEE": "epicerie_salee",
    "EPICERIE SUCREE": "epicerie_sucree",
    "PAINS PATISSERIES": "pains_patisseries",
    "PATISSERIE": "pains_patisseries",
    "VIANDES POISSONS": "viandes_poissons",
    "BOUCHERIE POISSONNERIE": "viandes_poissons",
    "LAITIER OEUFS VEGETAL": "laitiers_oeufs",
    "LAITIER OEUFS": "laitiers_oeufs",
    "CREMERIE": "laitiers_oeufs",
    "CHARCUTERIE TRAITEUR": "charcuterie_traiteur",
    "SURGELES": "surgeles",
    "BOISSONS": "boissons",
    "HYGIENE BEAUTE": "hygiene_beaute",
    "PARAPHARMACIE": "hygiene_beaute",
    "ANIMALERIE": "animalerie",
    "ENTRETIEN NETTOYAGE": "entretien_nettoyage",
    "DROGUERIE": "entretien_nettoyage",
    "MAISON LOISIRS": "maison_loisirs",
    "BAZAR": "maison_loisirs",
}

_HEADER_RE = re.compile(r"^(?P<name>[A-Z ÀÂÉÈÊËÎÏÔŒÙÛÜŸÇ'-]+?)\s*\(\d+\s*PRODUITS?\)\s*$")

# Lignes de pied de facture (total, moyens de paiement...) ou d'en-tête de
# tableau qui se terminent aussi par un nombre à deux décimales — sans ce
# filtre elles seraient prises pour des articles (constaté : "Total de la
# commande", "Carte bancaire"... remontaient comme "produits").
_NON_PRODUCT_PREFIXES = (
    # "TOTAL" seul couvre aussi "TOTAL A PAYER", "TOTAL TTC", "TOTAL DE LA
    # COMMANDE"... mais pas "SOUS TOTAL", qui commence par un autre mot.
    "TOTAL",
    "SOUS TOTAL",
    "MES ECONOMIES",
    "SOLDE AVOIRS",
    "REGLEMENT",
    "CARTE",
    "A PAYER",
    "MONTANT",
    "MERCI",
    "CHEQUE",
    "ESPECES",
    "DETAIL DE VOTRE COMMANDE",
    # Pied de ticket de caisse Intermarché en magasin : moyens de paiement,
    # solde de fidélité, coordonnées du magasin. Un numéro de téléphone du
    # type "TEL 01.23.45.67.89" se terminait sur ses 2 derniers chiffres
    # décimaux et repartait comme un article (montant fantaisiste en euros).
    "MONTANT",
    "TRD",
    "CB",
    "ANCIEN SOLDE",
    "NOUVEAU SOLDE",
    "A RENDRE",
    "NOMBRE D'ARTICLES",
    "RECAPITULATIF",
    "CODE TVA",
    "TEL",
    "SIRET",
    "PRIX UNITAIRE",
    "PV HT",
    "PV TTC",
    "DESIGNATION",
    "DESCRIPTION",
    "QUANTITE",
    "TVA",
    "ORIGINE",
)

# Ligne de détail du taux de TVA (ex. "5,50% : 5,10€", vu sur une facture
# Intermarché) : matcherait sinon la regex d'article ci-dessous comme un
# "produit" nommé "5,50% :".
_PERCENT_LINE_RE = re.compile(r"^\d{1,3}(?:[,.]\d{1,2})?\s*%")

# Ligne du récapitulatif TVA d'un ticket de caisse, préfixée par son code de
# taux : "A  5,50%   12,83     0,71      13,54". Se terminant par un montant,
# elle repartait sinon comme un article (constaté sur un ticket Intermarché).
_VAT_CODE_LINE_RE = re.compile(r"^[A-Z]\s+\d{1,3}[,.]\d{1,2}\s*%")

# Fin de la partie "articles" d'une facture Leclerc : tout ce qui suit est
# le détail des réductions ("LOT BADOIT ... 1.80", montants POSITIFS mais
# qui sont des économies, pas des achats) puis du texte marketing. Sans
# cette borne, ces lignes de remise repartaient comme de faux produits (et
# gonflaient le total, constaté sur une vraie facture).
_STOP_MARKERS = (
    "DETAIL DE MES ECONOMIES",
    "VOUS AVEZ ECONOMISE",
)

# Heuristique volontairement simple pour la ligne elle-même (un libellé
# suivi d'un montant en fin de ligne) : les factures PDF mettent
# généralement chaque article sur sa propre ligne avec son prix total à
# droite (une éventuelle quantité/prix unitaire avant ne gêne pas, ils sont
# juste absorbés dans le libellé). Le groupe final optionnel absorbe une
# quantité en toute fin de ligne (constaté sur un ticket Grand Frais : "...
# 2.99€    1", où "1" est la quantité et non un second article — sans ce
# groupe, AUCUNE ligne de ce ticket ne matchait, le prix n'étant alors
# jamais la toute dernière chose sur la ligne). Jamais une extraction
# fiable à 100 % — l'utilisateur DOIT relire et corriger avant d'enregistrer
# quoi que ce soit (voir routers/receipts.py, qui insère ces suggestions
# telles quelles).
_RECEIPT_LINE_RE = re.compile(
    r"^(?P<label>.{2,}?)\s+(?P<amount>\d{1,4}[,.]\d{2})\s*(?:€|EUR)?\s*(?:[A-Z]|\d{1,3})?\s*$"
)

# Format "colonnes inversées" constaté sur une vraie facture PDF Leclerc :
# pypdf restitue chaque ligne de produit comme "Total TTC  Quantité
# Prix-unitaire" + désignation COLLÉE juste après (aucun espace), soit
# l'inverse visuel du tableau affiché (Désignation | Quantité | Prix
# unitaire | Total TTC) — sans ce format, AUCUNE ligne ne matchait
# _RECEIPT_LINE_RE, qui suppose le prix à la fin. Essayé EN PREMIER : les
# deux formats ne peuvent pas matcher la même ligne (celui-ci exige un
# chiffre en tout début de ligne, l'autre une lettre).
_REVERSED_RECEIPT_LINE_RE = re.compile(
    r"^\s*(?P<amount>\d{1,4}[,.]\d{2})\s+\d{1,3}\s+\d{1,4}[,.]\d{2}(?P<label>\D.*)$"
)

# Sous-ligne "quantité x prix unitaire" (ex. "3 x 1.99€", sous CONCOMBRE
# NANTAIS sur un ticket Grand Frais) : explique le prix de l'article
# juste au-dessus, n'EST PAS un article à part — matcherait pourtant la
# regex ci-dessus (le "€" final la rend indiscernable d'un vrai article
# très court) une fois le groupe de quantité en fin de ligne autorisé, donc
# à exclure explicitement avant de tenter l'extraction normale.
_QTY_TIMES_PRICE_RE = re.compile(r"^\d+(?:[.,]\d+)?\s*[xX]\s*\d{1,4}[,.]\d{2}\s*(?:€|EUR)?$")


# --- Facture Drive Intermarché (PDF "FACTURE N°...") ----------------------
# Chaque article = un libellé (sur 1 à 3 lignes) puis UNE ligne de chiffres
# "qté commandée  qté livrée  TVA %  HT €  TTC €  Total TTC €" (les quantités
# peuvent être en kg). Les rayons sont des en-têtes "NOM (N)" sans le mot
# "produits". Les remises sont des lignes "[PROMO] Vous avez bénéficié de X €
# de remise immédiate", avec "-X €" sur la même ligne ou, quand le montant
# est absent, le montant NET de l'article repris après la ligne de chiffres.
_DRIVE_NUMBERS_RE = re.compile(
    r"^(?:(?P<label>.*?)\s+)?(?P<q1>\d+(?:,\d+)?(?:kg)?)\s+(?P<q2>\d+(?:,\d+)?(?:kg)?)\s+\d{1,2}(?:,\d+)?\s*%\s+"
    r"\d+,\d{2}\s*€\s+\d+,\d{2}\s*€\s+(?P<amount>\d+,\d{2})\s*€$"
)
_DRIVE_PROMO_RE = re.compile(
    r"^\[PROMO\].*?(?P<value>\d+,\d{2})\s*€\s+de remise immédiate(?:\s+-\s*(?P<neg>\d+,\d{2})\s*€)?\s*$"
)
_DRIVE_GROUP_RE = re.compile(r"^(?P<name>[^\d(][^()]*?)\s*\(\d+\)$")
_DRIVE_NET_RE = re.compile(r"^(?P<amount>\d+,\d{2})\s*€$")
_DRIVE_FOOTNOTE_START_RE = re.compile(r"^Page \d+ sur", re.IGNORECASE)

_DRIVE_GROUPS: dict[str, str | None] = {
    "PROMOTIONS": None,
    "CHARCUTERIE": "charcuterie_traiteur",
    "ENTRETIEN ET NETTOYAGE": "entretien_nettoyage",
    "EPICERIE SALEE": "epicerie_salee",
    "EPICERIE SUCREE": "epicerie_sucree",
    "FROMAGES, CREMERIE ET OEUFS": "laitiers_oeufs",
    "YAOURTS ET DESSERTS": "laitiers_oeufs",
    "SURGELES": "surgeles",
    "FRUITS ET LEGUMES": "fruits_legumes",
    "BOUCHERIE": "viandes_poissons",
    "POISSONNERIE": "viandes_poissons",
    "BOULANGERIE ET PATISSERIE": "pains_patisseries",
    "BOISSONS": "boissons",
    "HYGIENE ET BEAUTE": "hygiene_beaute",
    "ANIMALERIE": "animalerie",
}


def _dec(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "."))


def _is_drive_invoice(text: str) -> bool:
    return any(_DRIVE_NUMBERS_RE.match(line.strip()) for line in text.splitlines())


def _parse_drive_invoice(text: str) -> list[dict]:
    items: list[dict] = []
    family: str | None = None
    label_parts: list[str] = []
    pending_promo = Decimal("0")
    last_item: dict | None = None
    in_footnote = False
    started = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if in_footnote:
            # Pied de page répété à chaque page : jusqu'à sa dernière ligne.
            if _normalize(line).endswith("COMMANDE."):
                in_footnote = False
            continue
        if _DRIVE_FOOTNOTE_START_RE.match(line):
            in_footnote = True
            continue

        normalized = _normalize(line)
        if normalized.startswith("TOTAL REMISES IMMEDIATES"):
            break

        group = _DRIVE_GROUP_RE.match(normalized)
        if group and group.group("name").strip() in _DRIVE_GROUPS:
            family = _DRIVE_GROUPS[group.group("name").strip()]
            started = True
            label_parts = []
            continue
        if not started:
            # Tout ce qui précède le tableau (en-tête, magasin, livraison...).
            continue

        promo = _DRIVE_PROMO_RE.match(line)
        if promo:
            if promo.group("neg") and last_item is not None and not label_parts:
                # Remise affichée APRÈS l'article (ou le lot d'articles) concerné.
                last_item["amount"] -= _dec(promo.group("neg"))
            else:
                # Remise affichée AVANT les chiffres de l'article en cours.
                pending_promo = _dec(promo.group("value"))
            continue

        numbers = _DRIVE_NUMBERS_RE.match(line)
        if numbers:
            if numbers.group("label"):
                label_parts.append(numbers.group("label"))
            label = " ".join(
                p for p in label_parts if not p.startswith("[Produit à poids variable")
            ).strip(" .:-*")
            label_parts = []
            if not label:
                continue
            amount = _dec(numbers.group("amount")) - pending_promo
            pending_promo = Decimal("0")
            last_item = {"label": label, "amount": amount, "family": family}
            items.append(last_item)
            continue

        net = _DRIVE_NET_RE.match(line)
        if net and last_item is not None and not label_parts:
            # Montant net repris après la ligne de chiffres : déjà soustrait.
            continue

        if normalized.startswith(("LIBELLE PRODUIT", "QUANTITE", "LIVREE", "COMMANDEE", "TVA PRIX")):
            continue
        if normalized in {"PRODUITS (34)"} or re.match(r"^PRODUITS \(\d+\)$", normalized):
            continue
        label_parts.append(line)

    return [i for i in items if i["amount"] > 0]


# --- Ticket « colonnes » (Lidl : Article | P.U.EUR | Qté | EUR) -------------
# Chaque article : libellé, prix unitaire, quantité, montant, code TVA ("A T").
# Un article au poids n'a que le montant, et sa ligne suivante
# ("0,202 kg x 7,95 EUR/kg") est une explication, pas un article. Une remise
# ("Prix en baisse  -0,10") se déduit de l'article juste au-dessus. L'OCR
# abîme souvent le MONTANT (« 1,9 », « 2,/5 ») alors que P.U. et Qté sont
# plus nets : on recalcule P.U. x Qté plutôt que de se fier au montant lu.
_COLUMNS_HEADER_RE = re.compile(r"P[.,]?\s?U[.,]?\s?EUR|\bQt[eé]\b|TICKET DE VENTE", re.IGNORECASE)
# Signature d'une ligne d'article « P.U.  Qté  montant » : sert à reconnaître
# le format même quand l'OCR a abîmé l'en-tête (« P,U,EUR », « Ticket de vente »
# illisible...).
_COLUMNS_ROW_RE = re.compile(r"\d+[,.]\d{2}\s+\d{1,2}\s+\d+[,.]?\d{0,2}")


def _is_columns_ticket(text: str) -> bool:
    return bool(_COLUMNS_HEADER_RE.search(text)) or len(_COLUMNS_ROW_RE.findall(text)) >= 3
_COLUMNS_DISCOUNT_RE = re.compile(r"^(?P<label>[^\d\-].*?)\s+-\s?(?P<amount>\d+[.,]\d{2})\s*$")
_COLUMNS_END_RE = re.compile(r"^NOMBRE DE LIGNES", re.IGNORECASE)
_TOTAL_LINE_PREFIXES = ("A PAYER", "TOTAL ELIGIBLE", "CARTE", "TOTAL TTC", "TOTAL A PAYER")


def _parse_columns_ticket(text: str) -> list[dict]:
    items: list[dict] = []
    # Sans en-tête lisible, on part du début : les lignes d'avant (enseigne,
    # adresse) n'ont pas de prix décimal en milieu de ligne et sont ignorées.
    started = not _COLUMNS_HEADER_RE.search(text)
    for raw in text.splitlines():
        line = raw.strip(" |_.:;'\"")
        if not line:
            continue
        if not started:
            started = bool(_COLUMNS_HEADER_RE.search(line))
            continue
        normalized_line = _normalize(line)
        if _COLUMNS_END_RE.match(normalized_line) or normalized_line.startswith(_TOTAL_LINE_PREFIXES):
            break
        if re.search(r"\bkg\s*[xX]\b|EUR\s*/\s*kg", line, re.IGNORECASE):
            continue
        discount = _COLUMNS_DISCOUNT_RE.match(line)
        if discount and items:
            items[-1]["amount"] -= Decimal(discount.group("amount").replace(",", "."))
            continue
        # Le libellé s'arrête au premier montant décimal ; tout ce qui suit
        # (qté, montant, code TVA plus ou moins déformé par l'OCR) est lu en
        # tolérance, y compris du bruit du genre « LE AT ».
        first = re.search(r"\s(\d+[,.]\d{1,2})(?!\d)", line)
        if not first:
            continue
        label = line[: first.start()].strip(" |_.:-*")
        if len(label) < 2 or label[0].isdigit():
            continue
        rest = line[first.start():]
        decimals = re.findall(r"\d+[,.]\d{1,2}(?!\d)", rest)
        values = [Decimal(d.replace(",", ".")) for d in decimals]
        unit = values[0]
        qty_match = re.match(r"\s*\d+[,.]\d{1,2}\s+(\d{1,2})(?!\d|[,.])", rest)
        qty = int(qty_match.group(1)) if qty_match else 1
        if len(values) == 1 or qty == 1:
            amount = unit * qty  # poids / quantité 1 : le prix lu en tête est le plus net
        else:
            amount = values[-1]  # qté > 1 : le montant imprimé (« 1,9 » -> 1,90)
        if amount > 0:
            items.append({"label": label, "amount": amount, "family": None})
    return [i for i in items if i["amount"] > 0]


def receipt_total_candidates(text: str) -> set[Decimal]:
    """Montants lus sur les lignes « À payer » / « Carte »… : sert à valider
    une lecture OCR (la somme des articles doit retomber dessus)."""
    found: set[Decimal] = set()
    for raw in text.splitlines():
        line = raw.strip(" |_.:;")
        if _normalize(line).startswith(_TOTAL_LINE_PREFIXES):
            for d in re.findall(r"\d+[,.]\d{2}(?!\d)", line):
                found.add(Decimal(d.replace(",", ".")))
    return found


def parse_receipt_lines(text: str) -> list[dict]:
    if _is_columns_ticket(text):
        columns = _parse_columns_ticket(text)
        if columns:
            return columns
    if _is_drive_invoice(text):
        return _parse_drive_invoice(text)
    items: list[dict] = []
    current_family: str | None = None

    for raw_line in text.splitlines():
        # "|" parasite en bord de ligne : trait de tableau lu par l'OCR.
        line = raw_line.strip(" |")
        if not line:
            continue
        normalized = _normalize(line)

        if any(marker in normalized for marker in _STOP_MARKERS):
            break

        header_match = _HEADER_RE.match(normalized)
        if header_match:
            current_family = _FAMILY_HEADERS.get(header_match.group("name").strip())
            continue

        if any(normalized.startswith(prefix) for prefix in _NON_PRODUCT_PREFIXES):
            continue

        if (
            _QTY_TIMES_PRICE_RE.match(line)
            or _PERCENT_LINE_RE.match(line)
            or _VAT_CODE_LINE_RE.match(normalized)
        ):
            continue

        match = _REVERSED_RECEIPT_LINE_RE.match(line) or _RECEIPT_LINE_RE.match(line)
        if not match:
            continue
        label = match.group("label").strip(" .:-*")
        if not label:
            continue
        amount_str = match.group("amount").replace(",", ".")
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            continue
        if amount <= 0:
            continue
        items.append({"label": label, "amount": amount, "family": current_family})

    return items
