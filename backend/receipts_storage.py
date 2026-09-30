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
    "CARTE BANCAIRE",
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


def parse_receipt_lines(text: str) -> list[dict]:
    items: list[dict] = []
    current_family: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
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
