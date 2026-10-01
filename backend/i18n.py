"""Internationalisation : langue de l'interface et formats régionaux.

Le français est la langue SOURCE : chaque texte visible s'écrit en français
dans le code et les gabarits (`_("Importer")`), et le catalogue anglais
(backend/locale/en/LC_MESSAGES/messages.po, compilé en .mo) fournit la
traduction. Un texte absent du catalogue s'affiche donc en français plutôt
que de casser la page. Aucune dépendance à l'exécution : seule la
bibliothèque standard (gettext) est utilisée ; Babel ne sert qu'à extraire
et compiler les catalogues en développement (voir babel.cfg).

Langue et format sont deux réglages séparés : on peut lire l'interface en
anglais avec des dates au format français, ou l'inverse. La langue courante
vit dans une ContextVar posée par LocaleMiddleware pour chaque requête, ce
qui permet de traduire aussi bien dans les gabarits que dans le code Python
(messages d'erreur, libellés) sans passer la langue de fonction en fonction.
"""

from __future__ import annotations

import gettext as _gettext
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup, escape

LOCALE_DIR = Path(__file__).resolve().parent / "locale"

DEFAULT_LANGUAGE = "fr"
LANGUAGES: dict[str, str] = {"fr": "Français", "en": "English"}

# Formats régionaux : js_locale sert aux Intl.NumberFormat / toLocaleString
# côté navigateur (voir base.html, data-number-locale).
FORMATS: dict[str, dict[str, str]] = {
    "fr": {"js_locale": "fr-FR"},
    "en-GB": {"js_locale": "en-GB"},
    "en-US": {"js_locale": "en-US"},
}
DEFAULT_FORMAT = "fr"

_LANGUAGE_COOKIE = "twiga_lang"
_FORMAT_COOKIE = "twiga_fmt"

_current_language: ContextVar[str] = ContextVar("twiga_language", default=DEFAULT_LANGUAGE)
_current_format: ContextVar[str] = ContextVar("twiga_format", default=DEFAULT_FORMAT)


def default_format_for(language: str) -> str:
    # Format proposé tant que l'utilisateur n'en a pas choisi un : celui de sa
    # langue. L'anglais démarre sur le format international (jour/mois/année) ;
    # le format américain reste un choix explicite.
    return "fr" if language == "fr" else "en-GB"


def current_language() -> str:
    return _current_language.get()


def current_format() -> str:
    return _current_format.get()


def number_locale() -> str:
    return FORMATS[current_format()]["js_locale"]


def set_locale(language: str, number_format: str) -> None:
    _current_language.set(language if language in LANGUAGES else DEFAULT_LANGUAGE)
    _current_format.set(number_format if number_format in FORMATS else DEFAULT_FORMAT)


def resolve_locale(user, cookies: dict[str, str]) -> tuple[str, str]:
    # Priorité : réglage du compte connecté, puis cookie (authentification
    # désactivée, ou page de connexion), puis défaut. Pas de détection
    # automatique via Accept-Language tant que l'anglais est incomplet.
    language = getattr(user, "language", None) if user is not None else None
    if language not in LANGUAGES:
        language = cookies.get(_LANGUAGE_COOKIE)
    if language not in LANGUAGES:
        language = DEFAULT_LANGUAGE

    number_format = getattr(user, "number_format", None) if user is not None else None
    if number_format not in FORMATS:
        number_format = cookies.get(_FORMAT_COOKIE)
    if number_format not in FORMATS:
        number_format = default_format_for(language)
    return language, number_format


@lru_cache(maxsize=None)
def _catalog(language: str) -> _gettext.NullTranslations:
    if language == DEFAULT_LANGUAGE:
        return _gettext.NullTranslations()
    return _gettext.translation("messages", localedir=LOCALE_DIR, languages=[language], fallback=True)


def gettext(message: str) -> str:
    return _catalog(current_language()).gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _catalog(current_language()).ngettext(singular, plural, n)


class LazyString:
    # Texte traduit au moment de l'affichage, pas de l'import du module : pour
    # les constantes de niveau module (libellés de piliers, types de compte)
    # évaluées avant qu'une requête n'ait fixé la langue.
    __slots__ = ("_message",)

    def __init__(self, message: str) -> None:
        self._message = message

    def __str__(self) -> str:
        return gettext(self._message)

    def __html__(self) -> Markup:
        return Markup(escape(str(self)))

    def __repr__(self) -> str:
        return f"LazyString({self._message!r})"

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(self._message)

    def __add__(self, other: object) -> str:
        return str(self) + str(other)

    def __radd__(self, other: object) -> str:
        return str(other) + str(self)

    def __mod__(self, other):
        return str(self) % other

    def __len__(self) -> int:
        return len(str(self))

    def __getattr__(self, name: str):
        return getattr(str(self), name)


def lazy_gettext(message: str) -> LazyString:
    return LazyString(message)
