"""What a role can do, read from the rules of the application itself.

The reader's view of the other way ("Tu peux consulter, pas modifier.") lists what
the role allows. The answers are not written a second time here: each line asks
`auth.check_role_access`, the function the middleware uses, with a typical request,
so the list cannot drift from what the application really refuses.
"""

from __future__ import annotations

from backend.auth import check_role_access
from backend.i18n import lazy_gettext

# (label, the request that stands for the capability)
CAPABILITIES = [
    (lazy_gettext("Consulter les opérations, les rapports, les budgets et les projets"), "GET", "/transactions/list"),
    (lazy_gettext("Ranger et modifier les opérations, les budgets, les projets et Le Cap"), "POST", "/transactions/1/update"),
    (lazy_gettext("Supprimer, régler les comptes, les catégories et les règles"), "POST", "/accounts/create"),
    (lazy_gettext("Importer un relevé et gérer les utilisateurs"), "POST", "/users/create"),
]


def capabilities(role: str) -> list[tuple[str, bool]]:
    """[(label, allowed)] for a role, in the order of the screen."""
    return [(str(label), check_role_access(role, method, path)) for label, method, path in CAPABILITIES]
