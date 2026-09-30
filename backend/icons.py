"""Jeu d'icônes au trait — Tabler Icons (MIT), vendorisé.

Les SVG vivent dans `frontend/static/vendor/tabler/`, jamais sur un CDN :
l'application doit fonctionner sans accès Internet (voir PRODUCT.md).

Pourquoi du SVG inline plutôt qu'une police d'icônes : une police impose un
fichier binaire à charger, décale le rendu tant qu'elle n'est pas arrivée, et
lit mal en lecteur d'écran. Le SVG inline hérite de `currentColor`, suit donc
les thèmes clair/sombre sans une seule règle conditionnelle, et n'ajoute
aucune requête.

Les fichiers sont lus UNE SEULE FOIS au démarrage du process, puis servis
depuis ce cache : appeler `icon()` des centaines de fois dans une page ne
retouche jamais au disque.
"""
from __future__ import annotations

import re
from pathlib import Path

from markupsafe import Markup

_ICON_DIR = Path(__file__).resolve().parent.parent / "frontend" / "static" / "vendor" / "tabler"

# Contenu utile d'un SVG Tabler : tout ce qui est entre <svg ...> et </svg>.
# L'en-tête de commentaire (catégorie, tags, version) est ignoré.
_INNER = re.compile(r"<svg[^>]*>(.*)</svg>", re.S)

_cache: dict[str, str] = {}


def _load(name: str) -> str | None:
    if name in _cache:
        return _cache[name]
    path = _ICON_DIR / f"{name}.svg"
    if not path.is_file():
        return None
    match = _INNER.search(path.read_text(encoding="utf-8"))
    if match is None:
        return None
    _cache[name] = " ".join(match.group(1).split())
    return _cache[name]


def icon(name: str, size: int = 20, cls: str = "") -> Markup:
    """Rend une icône inline.

    `size` en pixels (20 par défaut, la taille courante dans l'app).
    `cls` s'ajoute sur le <svg> pour l'espacement ou la couleur.

    aria-hidden systématique : ces icônes accompagnent toujours un libellé
    texte ou un aria-label porté par le contrôle parent. Une icône annoncée
    en plus du libellé ferait doublon au lecteur d'écran.

    Un nom inconnu renvoie une chaîne vide plutôt que de lever : une icône
    manquante ne doit jamais casser le rendu d'une page de comptes.
    """
    inner = _load(name)
    if inner is None:
        return Markup("")
    # `twiga-icon` est indispensable, pas décoratif : le preflight Tailwind
    # pose `svg { display: block }`. Sans cette classe, une icône suivie de
    # son libellé dans un parent NON flex (un <button> ou un <p> ordinaire)
    # occupe toute la ligne et renvoie le texte en dessous — l'icône se
    # retrouve au-dessus du texte au lieu d'être à côté. La règle est dans
    # design-system.css.
    classes = f' class="twiga-icon {cls}"' if cls else ' class="twiga-icon"'
    return Markup(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
        f"{classes}>{inner}</svg>"
    )


def available() -> list[str]:
    """Noms disponibles, pour la page /design-system."""
    return sorted(p.stem for p in _ICON_DIR.glob("*.svg"))
