from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))
    # Solde D'OUVERTURE, avant la première transaction importée — jamais le
    # solde courant. Le solde réel affiché partout ailleurs (dashboard, liste
    # des comptes) se calcule à la volée : balance + SUM(transactions), voir
    # crud.get_account_balances / get_accounts_overview.
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str] = mapped_column(String(10))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    # Ordre d'affichage parmi les catégories de même niveau (même parent_id) :
    # assigné en incrémental à la création (voir crud.create_category), donc
    # les catégories apparaissent dans leur ordre d'ajout, puis par nom pour
    # celles restées à 0 (import QIF).
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # "essentiel" / "choix" / "imprevu" / NULL — pilier "Le Cap" de cette
    # catégorie. NULL sur une sous-catégorie = hérite du pilier de son
    # parent ; NULL sur une catégorie racine = non défini, résolu en
    # "choix" par défaut (voir crud.resolve_category_pillar). Chaîne brute
    # plutôt qu'un enum Postgres : cohérent avec Account.type ailleurs dans
    # ce schéma, et plus simple à faire évoluer.
    pillar: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # True pour une catégorie qui n'est pas une dépense (salaire, autres
    # revenus...) : masquée de l'écran Budgets (voir
    # crud.get_budgetable_categories), qui n'a pas de sens pour un revenu.
    # Reste utilisable partout ailleurs (catégorisation, règles, rapports).
    excluded_from_budget: Mapped[bool] = mapped_column(Boolean, default=False)

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", order_by="[Category.sort_order, Category.name]"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")
    rules: Mapped[list["Rule"]] = relationship(back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(255))
    raw_label: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    # "Passer" dans La Savane (flux carte par carte) : déprioritise juste
    # l'ordre de passage, ne filtre jamais rien (voir get_next_pending_transaction) —
    # une opération passée reste visible partout ailleurs, y compris dans le
    # Backlog.
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # "✗ Non merci" dans le Backlog (rejet d'une suggestion) : lui, à
    # l'inverse, doit bien exclure l'opération de cette vue précise, sinon
    # elle y réapparaîtrait à l'identique juste après avoir été rejetée. Champ
    # séparé de skipped_at à dessein : les deux actions ne doivent surtout pas
    # partager le même champ, sous peine qu'un simple "Passer" dans La Savane
    # fasse disparaître l'opération du Backlog (bug réel corrigé ici — un
    # Backlog qui semblait vide après usage intensif de "Passer").
    backlog_rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Virement interne entre deux comptes suivis par l'app : inclus dans le
    # solde par compte, mais exclu du solde total et des agrégats
    # recettes/dépenses (sinon un même virement est compté comme dépense
    # d'un côté ET recette de l'autre, ce qui gonfle artificiellement les
    # deux totaux même si le net reste correct).
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    # Nom d'une ligne de la table payment_methods (voir PaymentMethod
    # ci-dessous), ou NULL si non renseigné — toujours facultatif, jamais
    # requis pour catégoriser une transaction. Pas de ForeignKey volontaire :
    # un moyen de paiement supprimé ne doit pas bloquer/casser les
    # transactions qui le référençaient encore, juste ne plus matcher aucune
    # option affichée (voir crud.get_payment_methods_dict). String(50) pour
    # matcher PaymentMethod.name (un moyen de paiement personnalisé plus
    # long que 20 caractères lèverait sinon une erreur PostgreSQL dès la
    # première tentative de l'utiliser ici).
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Libre, facultatif — jamais utilisé pour du calcul, juste un mémo
    # affiché sur la transaction (ex : "Remboursement Pierre...").
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Marqueur "Le Cap" : dépense/recette imprévue du mois, posée manuellement
    # (bouton dans La Savane, case dans Opérations) — jamais déduit
    # automatiquement d'une catégorie. Prioritaire sur tout pilier de
    # catégorie dans la résolution "Le Cap" (voir crud.resolve_transaction_pillar) :
    # une transaction is_unexpected=True vaut toujours 🆘 Imprévu, quelle que
    # soit sa catégorie.
    is_unexpected: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")
    receipt_items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="ReceiptItem.sort_order",
    )


class ReceiptItem(Base):
    # Détail ligne par ligne d'un ticket/facture (voir Transaction.receipt_*
    # ci-dessus) : une note historique consultable depuis la transaction,
    # jamais agrégée dans les totaux de catégorie ailleurs (Budgets,
    # Rapports, Le Cap continuent de sommer la transaction entière sous sa
    # catégorie unique habituelle — voir la discussion produit associée).
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    label: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    # Rayon d'hypermarché (voir backend/receipt_families.py), PAS une
    # Category : ce classement n'a de sens que pour décomposer un ticket,
    # jamais réutilisé ailleurs dans l'app (Budgets, Règles, Rapports).
    family: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    transaction: Mapped["Transaction"] = relationship(back_populates="receipt_items")


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    month: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))

    category: Mapped["Category"] = relationship(back_populates="budgets")


class BudgetMonth(Base):
    # Valeurs de budget qui portent sur le MOIS entier et non sur une
    # catégorie — une ligne par mois (même convention que Budget.month et
    # CapEntry.month : le 1er du mois), pas de contrainte unique en base,
    # appliquée en code par crud.save_savings_withdrawal façon
    # crud.save_budgets. Distinct de CapEntry, qui n'existe que si le rituel
    # du Cap a été fait pour ce mois-là : l'écran Budgets ne doit pas en
    # dépendre.
    __tablename__ = "budget_months"

    id: Mapped[int] = mapped_column(primary_key=True)
    # index=True doit rester déclaré ici : la migration b7e4c1a9d2f8 crée
    # ix_budget_months_month en base, et sans cette déclaration
    # `alembic check` détecte une dérive et proposerait de le supprimer.
    month: Mapped[date] = mapped_column(Date, index=True)
    # Somme prélevée sur l'épargne pour compenser le mois : elle s'ajoute à
    # la recette du mois précédent pour former le "disponible à répartir".
    savings_withdrawal: Mapped[Decimal] = mapped_column(Numeric(15, 2))


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    target_date: Mapped[date] = mapped_column(Date)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)

    movements: Mapped[list["ProjectMovement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMovement(Base):
    __tablename__ = "project_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    # Signé, comme Transaction.amount : positif = ajout, négatif = dépense.
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="movements")


class CapSettings(Base):
    """Réglages du rituel du Cap — table à une seule ligne (id=1).

    Sert aujourd'hui à une seule question, mais une question structurante :
    **d'où viennent les ressources du mois ?** Les foyers y répondent
    différemment — salaire reçu pendant le mois, salaire reçu fin du mois
    précédent, virements vers un pot commun à plusieurs, ou enveloppe fixe
    décidée quand le revenu est irrégulier.

    Le moteur, lui, ne connaît qu'un concept : le montant engagé pour le
    mois, saisi dans le rituel (CapEntry.planned_income). C'est lui seul que
    le suivi compare aux dépenses. Ce réglage ne pilote donc QUE le
    pré-remplissage de ce champ — jamais le calcul. Une organisation
    particulière reste une configuration, elle n'entre pas dans le moteur.

    Table dédiée plutôt qu'AppState : celui-ci est volontairement exclu de
    l'export/restauration (voir restore.py), le réglage y serait perdu à
    chaque réinstallation.
    """

    __tablename__ = "cap_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "recettes_precedent" (défaut) | "recettes_courant" | "virements" | "fixe"
    income_source: Mapped[str] = mapped_column(String(30), default="recettes_precedent")
    # Compte dont on relève les virements entrants, quand income_source vaut
    # "virements" — le « compte commun » d'un foyer, sans avoir à inventer
    # cette notion sur Account, qui n'en a pas besoin ailleurs.
    income_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    # Enveloppe fixe, quand income_source vaut "fixe".
    income_fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    income_account: Mapped["Account | None"] = relationship()


class CapEntry(Base):
    # "Le Cap" : rituel budgétaire mensuel du couple — une ligne par mois
    # (comme Budget.month), pas de contrainte unique en base (appliquée en
    # code par crud.save_cap_entry, façon crud.save_budgets : delete-then-
    # upsert). Les 4 champs reflection_* portent sur le mois qui vient de se
    # terminer mais sont saisis avec le cap du NOUVEAU mois (étape 3 du
    # wizard = seul point de sauvegarde), donc stockés sur cette même ligne
    # plutôt que sur celle du mois précédent.
    __tablename__ = "cap_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date)
    planned_income: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    planned_essentiel: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    planned_choix: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    planned_imprevu: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    intention: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reflection_unexpected: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection_regret: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection_proud: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection_worked_well: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuleSuggestion(Base):
    """Règle proposée mais pas encore validée.

    Ces propositions étaient jusqu'ici purement éphémères : calculées à la
    volée après une catégorisation, affichées, puis perdues si on ne
    cliquait pas. En catégorisation de masse, où l'on valide des dizaines
    d'opérations d'un coup, elles s'empilaient à l'écran plus vite qu'on ne
    pouvait les traiter — et tout ce qui n'était pas validé disparaissait.

    Les persister leur donne un endroit où être retrouvées (page Règles), et
    permet surtout de RETENIR UN REFUS : sans ça, « Non merci » ne valait que
    pour l'affichage courant et la même proposition revenait indéfiniment.

    Unicité (keyword, category_id) appliquée en code (voir
    crud.record_rule_suggestion), comme pour Budget et CapEntry.
    """

    __tablename__ = "rule_suggestions"
    # Déclaré ici et pas seulement dans la migration : sinon `alembic check`
    # voit une dérive et proposerait de supprimer l'index (même précaution
    # que BudgetMonth.month).
    __table_args__ = (
        Index("ix_rule_suggestions_keyword_category", "keyword", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    # Nombre de fois que la proposition s'est représentée : sert à trier les
    # plus rentables en tête, un commerçant vu dix fois valant mieux qu'un
    # achat unique.
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Refus mémorisé plutôt que ligne supprimée : une ligne effacée serait
    # recréée à la prochaine catégorisation du même libellé.
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped["Category"] = relationship()


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    # Optionnel : si présent, La Savane pré-sélectionne ce mode de paiement
    # quand cette règle propose sa catégorie (voir routers/transactions.py).
    # String(50) pour matcher PaymentMethod.name (un moyen de paiement
    # personnalisé plus long que 20 caractères lèverait sinon une erreur
    # PostgreSQL dès la première tentative de l'utiliser ici).
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Rayon de ticket (voir backend/receipt_families.py) pour les commerces à
    # famille de produit unique (boulangerie, primeur...) : quand cette règle
    # matche une transaction déjà catégorisée "Courses" et sans aucune ligne
    # de ticket, une ligne unique couvrant tout le montant est ajoutée
    # automatiquement (voir crud._maybe_add_receipt_family_line) — inutile
    # d'attendre une vraie facture à importer pour un commerce qui ne vend
    # qu'un seul type de produit. Réservé en pratique aux règles ciblant
    # "Courses" (seule catégorie où le rapport par rayon a du sens) — imposé
    # côté crud/formulaire (routers/rules.py), pas de contrainte en base.
    receipt_family: Mapped[str | None] = mapped_column(String(30), nullable=True)

    category: Mapped["Category"] = relationship(back_populates="rules")


class AppState(Base):
    # Table à une seule ligne (id=1) : sert à retenir le dernier mois où la
    # bannière "routine mensuelle" a été vue/fermée (pour ne l'afficher
    # qu'une fois par mois), et le secret de signature des cookies de
    # session (session_secret) : généré aléatoirement une seule fois (voir
    # backend/auth.py, load_session_secret), partagé par TOUTES les sessions
    # de TOUS les utilisateurs — contrairement à l'ancienne authentification
    # à mot de passe unique, ce secret n'est plus dérivé d'un mot de passe
    # (chaque utilisateur a désormais le sien, voir User) mais reste stable
    # indépendamment des changements de mot de passe individuels.
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_routine_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    session_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)


class User(Base):
    # Authentification multi-utilisateur (remplace l'ancien mot de passe
    # unique — voir la migration a4d8e2f6c1b9 -> son successeur pour la
    # transition). role : "admin" (accès complet, y compris import, suppr-
    # ession, paramètres, gestion des utilisateurs), "editor" (catégoriser,
    # modifier les opérations, créer budgets/projets), "viewer" (lecture
    # seule). Pas de colonne "session_version" séparée pour invalider les
    # sessions au changement de mot de passe : backend/auth.py embarque une
    # empreinte de hashed_password dans le jeton signé et la revérifie à
    # chaque requête, réutilisant cette seule colonne plutôt que d'en
    # ajouter une hors du schéma demandé.
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Facultatif : nom affiché dans le menu utilisateur à la place du nom de
    # connexion quand renseigné (voir routers/profile.py) — jamais utilisé
    # pour l'authentification elle-même, qui reste basée sur username.
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Visite guidée : NULL = pas encore vue (elle démarre à la première
    # connexion), sinon date de fin ou d'abandon. Côté serveur et non en
    # localStorage pour qu'un nouvel appareil ou un navigateur vidé ne la
    # rejoue pas. La migration marque les comptes existants comme l'ayant vue.
    tour_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RecurringPattern(Base):
    # Décision de l'utilisateur (confirmé/ignoré) sur un abonnement récurrent
    # détecté par crud.detect_recurring_patterns. La détection elle-même est
    # recalculée à chaque visite (jamais stockée) ; seule la décision
    # persiste, retrouvée par label_pattern d'une exécution à l'autre.
    __tablename__ = "recurring_patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    label_pattern: Mapped[str] = mapped_column(String(255), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    frequency_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)


class PendingCheck(Base):
    # Paiement émis dont le débit bancaire n'apparaîtra que plus tard, sous
    # un libellé peu explicite — historiquement un chèque (numéro de chèque),
    # étendu aux paiements via un intermédiaire comme Wero/PayPal (le libellé
    # bancaire dit rarement à qui/pourquoi, juste le nom du service). En
    # attente ⇔ matched_transaction_id est NULL — pas de champ "status"
    # séparé à garder synchronisé. Voir crud.match_pending_checks : le
    # rapprochement automatique (après import) exige TOUJOURS le montant
    # exact ET une ancre textuelle retrouvée dans le libellé brut — soit
    # check_number (chèque, aucune limite de délai), soit payment_method
    # (Wero/PayPal/..., fenêtre resserrée) — jamais les deux vides, pour
    # éviter tout faux positif sur un simple coup de chance.
    __tablename__ = "pending_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Nom d'une ligne de la table payment_methods (comme Transaction.
    # payment_method) : ancre de rapprochement alternative quand il n'y a pas
    # de numéro de chèque — le libellé bancaire d'un paiement Wero/PayPal
    # contient généralement le nom du service, même sans référence précise.
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    issued_date: Mapped[date] = mapped_column(Date)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    matched_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    category: Mapped["Category"] = relationship()
    account: Mapped["Account"] = relationship()
    matched_transaction: Mapped["Transaction | None"] = relationship()
