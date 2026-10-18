import json
import time
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import object_session

from backend.account_types import ACCOUNT_TYPES, get_account_type_icon, get_account_type_label
from backend.auth import get_current_user
from backend.category_icons import get_category_icon, get_category_icon_name
from backend.crud import resolve_category_pillar, resolve_transaction_pillar
from backend.icons import available as icon_names, icon
from backend.formatting import format_amount, format_amount_as, format_date, format_date_as
from backend import i18n, preferences
from backend.models import Account
from backend.payment_methods import get_payment_method_icon_name, get_payment_method_label
from backend.pillars import PILLAR_ORDER, PILLARS, get_pillar_label
from backend.receipt_families import receipt_family_display

BASE_DIR = Path(__file__).resolve().parent.parent


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, i18n.LazyString):
        return str(value)
    raise TypeError(f"Objet non sérialisable en JSON : {value!r}")


def tojson_filter(value) -> Markup:
    # Échappe "<" pour empêcher qu'une valeur contenant "</script>" (ex. un
    # nom de catégorie) ne casse le bloc <script> dans lequel le JSON est
    # embarqué côté template.
    #
    # Renvoie un Markup (pas un str) : sans ça, l'auto-échappement HTML de
    # Jinja s'applique QUAND MÊME au résultat déjà encodé en JSON et
    # transforme par ex. "&" en "&amp;" — invisible dans un attribut HTML
    # (le navigateur le décode), mais catastrophique dans le contenu brut
    # d'une balise <script> (jamais décodé par le parseur HTML), où ça casse
    # la syntaxe JS. C'est exactement le bug qui a cassé FILTER_QS (une
    # querystring construite avec urlencode() contient un "&" littéral dès
    # que plusieurs filtres sont actifs). Un Markup dit à Jinja "déjà sûr,
    # ne pas ré-échapper" ; {{ valeur | tojson }} suffit alors, {{ valeur |
    # tojson | safe }} reste équivalent (redondant mais inoffensif).
    return Markup(json.dumps(value, default=_json_default).replace("<", "\\u003c"))


# Même palette que les graphiques du dashboard (--color-chart-1 à 8 dans
# design-system.css : bleu, sarcelle, violet, rose, vert olive, orange, cyan,
# ardoise), pour une identité visuelle cohérente. Ni ambre, ni vert/rouge de
# verdict. Couleur déterministe par id de catégorie (pas de champ "color" en
# base) : aucune configuration nécessaire, toujours stable d'un rendu à
# l'autre.
_CATEGORY_PALETTE = [
    "#2563eb",
    "#0d9488",
    "#9333ea",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#0891b2",
    "#64748b",
]
_UNCATEGORIZED_COLOR = "#9ca3af"


def category_color_filter(category_id: int | None) -> str:
    # A reference to the data-palette token rather than a hex value, so the dot
    # follows the theme (lighter hues in dark). Only ever used in inline
    # `style` attributes, where var() resolves.
    if category_id is None:
        return "var(--color-secondary)"
    return f"var(--color-chart-{category_id % len(_CATEGORY_PALETTE) + 1})"


# Pastilles de compte : la palette de données du design system (la même que
# les catégories, jamais d'ambre, réservé à l'action principale). Une couleur
# choisie par l'utilisateur dans le formulaire d'édition prime toujours.
_ACCOUNT_COLOR_PALETTE = _CATEGORY_PALETTE


def account_color_filter(account) -> str:
    # Couleur explicite si définie (formulaire d'édition du compte), sinon
    # couleur déterministe basée sur le RANG du compte parmi tous les
    # comptes triés par nom (même ordre que crud.list_accounts) — jamais
    # account.id % N, qui produit des doublons dès que des ids ne sont plus
    # contigus (compte supprimé) ou dépassent la taille de la palette.
    #
    # Trois requêtes différentes alimentent des templates affichant des
    # pastilles de compte (crud.list_accounts, crud.get_account_balances,
    # crud.get_accounts_overview) : plutôt que de dupliquer ce calcul de
    # rang dans chacune, on le fait ici en réutilisant la Session déjà
    # attachée à l'objet Account (object_session) — la même Session que
    # celle de la requête HTTP en cours, donc aucune connexion
    # supplémentaire ouverte. La table comptes est minuscule (usage
    # personnel, quelques comptes), cette requête de plus est sans impact
    # mesurable. Repli sur account.id % N si l'objet n'est pas rattaché à
    # une Session (ex. objet détaché, fixtures de test) : couleur toujours
    # renvoyée, juste sans garantie d'unicité dans ce cas limite.
    if account is None:
        return _UNCATEGORIZED_COLOR
    if account.color:
        return account.color
    index = None
    try:
        session = object_session(account)
        if session is not None:
            ids_in_order = session.execute(
                select(Account.id).order_by(Account.name)
            ).scalars().all()
            index = list(ids_in_order).index(account.id)
    except Exception:
        index = None
    if index is None:
        index = account.id
    return _ACCOUNT_COLOR_PALETTE[index % len(_ACCOUNT_COLOR_PALETTE)]


def category_display_filter(name: str | None) -> str:
    # Filet de sécurité d'affichage : une catégorie encore mal importée
    # ("Parent:Enfant" à plat, jamais nettoyée par la migration de
    # correctif) s'affiche lisiblement plutôt que de montrer le ":" brut.
    # Ne corrige PAS la donnée elle-même, juste sa présentation.
    if not name or ":" not in name:
        return name or ""
    parent, _, child = name.rpartition(":")
    return f"{parent.strip()} → {child.strip()}"


_ROLE_LABELS = {
    "admin": i18n.lazy_gettext("Administrateur"),
    "editor": i18n.lazy_gettext("Éditeur"),
    "viewer": i18n.lazy_gettext("Lecture seule"),
}
_USER_DISPLAY_NAME_MAX = 16


def user_display_name(user) -> str:
    # Nom affiché si renseigné (voir routers/profile.py), sinon nom de
    # connexion — tronqué à 16 caractères (menu utilisateur, espace réduit
    # dans la sidebar/l'en-tête mobile), jamais utilisé pour l'authentification
    # elle-même.
    if user is None:
        return ""
    name = (user.display_name or user.username or "").strip()
    if len(name) > _USER_DISPLAY_NAME_MAX:
        return name[:_USER_DISPLAY_NAME_MAX] + "…"
    return name


def user_initials(user) -> str:
    # "JD" pour "Jean Dupont" (initiale de chaque mot du nom affiché) ; à
    # défaut de nom affiché à plusieurs mots (nom affiché absent ou nom de
    # connexion, ex. "admin"), les 2 premiers caractères du nom de connexion.
    if user is None:
        return ""
    name = (user.display_name or user.username or "").strip()
    if not name:
        return ""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def user_role_label(role: str | None) -> str:
    return _ROLE_LABELS.get(role or "", role or "")


# Un seul horodatage de démarrage de process pour TOUS les assets statiques
# (JS/CSS) : ajouté en ?v=... sur chaque référence dans les templates. Sans
# ça, le Service Worker (fetch "réseau d'abord") ET le cache HTTP natif du
# navigateur peuvent tous deux continuer à servir une version périmée d'un
# fichier après un redéploiement (déjà vu une fois : "le mode sombre ne fait
# rien", voir sw.js) — une nouvelle query string force un fetch réellement
# nouveau côté navigateur ET une nouvelle clé de cache côté Service Worker.
# Recalculé à chaque redémarrage du process (donc à chaque déploiement, vu
# que le workflow ici est rebuild d'image + restart du container).
ASSET_VERSION = str(int(time.time()))


def static_url(path: str) -> str:
    return f"{path}?v={ASSET_VERSION}"


def jsq_filter(value) -> str:
    # Texte traduit à placer dans une chaîne JS entre apostrophes, elle-même
    # dans un attribut HTML (Alpine : :aria-label="x ? '...' : '...'"). Renvoie
    # un str (pas un Markup) : l'auto-échappement HTML passe ensuite, et le
    # navigateur décode les entités avant qu'Alpine n'évalue l'expression.
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def format_preview(number_format: str) -> str:
    # Exemple affiché sur chaque carte du sélecteur de format (Paramètres >
    # Préférences) : la même date et le même montant rendus dans chaque format.
    from datetime import date

    return f"{format_date_as(date(2026, 12, 31), number_format)} · {format_amount_as(Decimal('1234.56'), number_format)}"


def tour_context(request) -> dict:
    # État de la visite guidée pour _tour.html. tracked : un compte connecté
    # mémorise l'avancement côté serveur (users.tour_seen_at) ; sans
    # authentification, tour.js garde l'ancien repli localStorage.
    # skip_import : l'étape Importer n'a de sens que pour un admin (seul rôle
    # autorisé) et sur une base encore vide.
    user = get_current_user(request)
    if user is None:
        return {"tracked": False, "pending": False, "skip_import": False}
    pending = user.tour_seen_at is None
    skip_import = False
    if pending:
        skip_import = user.role != "admin"
        if not skip_import:
            from backend.database import SessionLocal
            from backend.models import Transaction

            with SessionLocal() as db:
                skip_import = db.query(Transaction.id).first() is not None
    return {"tracked": True, "pending": pending, "skip_import": skip_import}


def configure_environment(env: Environment) -> Environment:
    """Filters, globals and the translation extension, shared by both interfaces.

    Called once per Jinja environment (the Classic one and the other way's):
    a filter added here exists in both, so a template never depends on which
    interface renders it.
    """
    env.filters["eur"] = format_amount
    env.filters["fr_date"] = format_date
    env.filters["tojson"] = tojson_filter
    env.filters["category_color"] = category_color_filter
    env.filters["category_display"] = category_display_filter
    env.filters["account_color"] = account_color_filter
    env.filters["receipt_family_display"] = receipt_family_display
    env.filters["pm_label"] = get_payment_method_label
    env.filters["jsq"] = jsq_filter
    env.globals["get_category_icon"] = get_category_icon
    env.globals["get_category_icon_name"] = get_category_icon_name
    env.globals["get_payment_method_icon_name"] = get_payment_method_icon_name
    env.globals["account_types"] = ACCOUNT_TYPES
    env.globals["get_current_user"] = get_current_user

    # Traduction : jinja2.ext.i18n + gettext/ngettext lus dans la langue de la
    # requête (backend/i18n.py). newstyle=True permet {{ _("Bonjour %(nom)s", nom=x) }}
    # et les blocs {% trans %}.
    env.add_extension("jinja2.ext.i18n")
    env.install_gettext_callables(i18n.gettext, i18n.ngettext, newstyle=True)

    env.globals["current_language"] = i18n.current_language
    env.globals["current_format"] = i18n.current_format
    env.globals["number_locale"] = i18n.number_locale
    env.globals["format_preview"] = format_preview
    env.globals["zero_eur"] = lambda: format_amount(Decimal("0"))
    env.globals["default_format_for"] = i18n.default_format_for
    env.globals["LANGUAGES"] = i18n.LANGUAGES
    env.globals["FORMATS"] = i18n.FORMATS
    env.globals["current_ui_variant"] = preferences.current_ui_variant
    env.globals["current_theme"] = preferences.current_theme
    env.globals["current_density"] = preferences.current_density
    env.globals["other_way_enabled"] = preferences.other_way_enabled
    env.globals["tour_context"] = tour_context
    env.globals["get_account_type_icon"] = get_account_type_icon
    env.globals["get_account_type_label"] = get_account_type_label
    env.globals["user_display_name"] = user_display_name
    env.globals["user_initials"] = user_initials
    env.globals["user_role_label"] = user_role_label
    env.globals["static_url"] = static_url
    # Jeu d'icônes au trait vendorisé (voir backend/icons.py) : {{ icon("wallet") }}
    env.globals["icon"] = icon
    env.globals["icon_names"] = icon_names
    env.globals["PILLARS"] = PILLARS
    env.globals["PILLAR_ORDER"] = PILLAR_ORDER
    env.globals["get_pillar_label"] = get_pillar_label
    env.globals["resolve_category_pillar"] = resolve_category_pillar
    env.globals["resolve_transaction_pillar"] = resolve_transaction_pillar
    return env


TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
OTHER_WAY_DIR = TEMPLATES_DIR / "other_way"


def _make_templates(*directories: Path) -> Jinja2Templates:
    loader = ChoiceLoader([FileSystemLoader(directory) for directory in directories])
    return Jinja2Templates(env=configure_environment(Environment(loader=loader, autoescape=True)))


class VariantTemplates:
    """The two interfaces behind one `templates` object.

    Classic looks templates up in `frontend/templates/`; the other way looks in
    `frontend/templates/other_way/` first and falls back on the same folder, so
    a template that `other_way/` does not override is the Classic one (the
    other way is complete from its first day, screens are replaced one by one).
    The routers keep calling `templates.TemplateResponse(name, context)`: the
    variant of the request (`request.state.ui_variant`, set by
    LocaleMiddleware) picks the environment. Fragments built in Python
    (`flash_html`) have no request at hand and read the ContextVar instead.
    """

    def __init__(self) -> None:
        self.classic = _make_templates(TEMPLATES_DIR)
        self.other_way = _make_templates(OTHER_WAY_DIR, TEMPLATES_DIR)

    @property
    def env(self) -> Environment:
        # The Classic environment: kept for code that touches `templates.env`.
        return self.classic.env

    def for_variant(self, variant: str | None) -> Jinja2Templates:
        return self.other_way if variant == "other_way" else self.classic

    def get_template(self, name: str):
        return self.for_variant(preferences.current_ui_variant()).env.get_template(name)

    def TemplateResponse(self, *args, **kwargs):
        if args and isinstance(args[0], str):
            context = args[1] if len(args) > 1 else kwargs.get("context") or {}
            request = context.get("request")
        elif args:
            request = args[0]
        else:
            request = kwargs.get("request") or (kwargs.get("context") or {}).get("request")
        variant = getattr(getattr(request, "state", None), "ui_variant", None)
        if variant is None:
            variant = preferences.current_ui_variant()
        return self.for_variant(variant).TemplateResponse(*args, **kwargs)


templates = VariantTemplates()


def flash_html(kind: str, message: str) -> str:
    """Feedback fragment returned by an HTMX action, see frontend/templates/_flash.html."""
    return templates.get_template("_flash.html").render(kind=kind, message=message)
