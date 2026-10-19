"""Fidelity of the settings-side screens to the mock-ups: Projets (rhythm,
effort, dialogs), Import (history, back button, size limit), Paramètres (one
page, start of the budget month, sensitive zone), payment-mode icons and
Mon profil.
"""

from datetime import date, timedelta
from decimal import Decimal

from backend import crud
from backend.database import SessionLocal
from backend.models import ImportLog, Project, ProjectMovement

CSV = "Date;Libellé;Montant\n02/10/2026;CB TEST FIDELITY SHOP;-12,30\n03/10/2026;PRLV TEST FIDELITY ELEC;-40,00\n"


# --- Projets ----------------------------------------------------------------


def test_project_rhythm_states():
    today = date(2026, 10, 15)
    done = crud.project_rhythm(Decimal("100"), Decimal("100"), date(2027, 1, 1), Decimal("0"), today)
    assert done["state"] == "done"
    none = crud.project_rhythm(Decimal("900"), Decimal("340"), date(2027, 3, 1), Decimal("0"), today)
    assert none["state"] == "none"
    # 560 missing at 60 a month: 10 months, October 2026 + 10 = August 2027.
    late = crud.project_rhythm(Decimal("900"), Decimal("340"), date(2027, 3, 1), Decimal("60"), today)
    assert (late["state"], late["reach"], late["gap_months"]) == ("late", date(2027, 8, 1), 5)
    early = crud.project_rhythm(Decimal("2000"), Decimal("1200"), date(2027, 6, 1), Decimal("150"), today)
    assert early["state"] == "early" and early["gap_months"] < 0
    exact = crud.project_rhythm(Decimal("200"), Decimal("0"), date(2026, 12, 1), Decimal("100"), today)
    assert exact["state"] == "on_time"


def test_project_effort_counts_deposits_of_the_last_three_months(demo):
    today = date.today()
    with SessionLocal() as db:
        project = crud.create_project(db, "Fidelity effort", Decimal("1000"), today + timedelta(days=300), Decimal("0"))
        db.add(ProjectMovement(project_id=project.id, date=today, amount=Decimal("90")))
        db.add(ProjectMovement(project_id=project.id, date=today, amount=Decimal("-50")))
        db.add(ProjectMovement(project_id=project.id, date=today - timedelta(days=400), amount=Decimal("999")))
        db.commit()
        # 90 of deposits over 3 months; the spending and the old deposit do not count.
        assert crud.compute_project_effort(db, project.id, today) == Decimal("30.00")
        db.delete(project)
        db.commit()


def test_projects_page_has_rhythm_effort_and_dialogs(clients):
    with SessionLocal() as db:
        project = crud.create_project(db, "Fidelity trip", Decimal("1000"), date.today() + timedelta(days=200), Decimal("100"))
        account = crud.list_accounts(db)[0]
        crud.add_project_funds(db, project, Decimal("50"), None, account.id)
        project_id = project.id
        account_name = account.name
    try:
        html = clients["admin"].get("/projects").text
        for text in ("Au rythme actuel", "Effort", "Pour tenir l'échéance", "Ajouter de l'argent", "Dépenser depuis le projet", "Depuis", "Date cible"):
            assert text in html
        assert 'class="select-field"' in html
        assert account_name in html  # the account shows in the history detail
    finally:
        with SessionLocal() as db:
            crud.delete_project(db, db.get(Project, project_id))


def test_spending_more_than_the_project_holds_is_refused(clients):
    with SessionLocal() as db:
        project = crud.create_project(db, "Fidelity spend", Decimal("500"), date.today() + timedelta(days=200), Decimal("20"))
        project_id = project.id
    try:
        clients["admin"].post(f"/projects/{project_id}/spend", data={"amount": "50", "note": ""})
        with SessionLocal() as db:
            assert db.get(Project, project_id).current_amount == Decimal("20.00")
        clients["admin"].post(f"/projects/{project_id}/spend", data={"amount": "5", "note": ""})
        with SessionLocal() as db:
            assert db.get(Project, project_id).current_amount == Decimal("15.00")
    finally:
        with SessionLocal() as db:
            crud.delete_project(db, db.get(Project, project_id))


# --- Import -----------------------------------------------------------------


def _upload_csv(client, account_id: int):
    return client.post(
        "/imports/preview",
        files={"file": ("fidelity.csv", CSV.encode("utf-8"), "text/csv")},
        data={"account_id": str(account_id)},
    )


def test_import_flow_has_back_buttons_state_column_and_history(clients, demo):
    account_id = demo["account_id"]
    step2 = _upload_csv(clients["admin"], account_id)
    assert step2.status_code == 200
    html = step2.text
    for text in ("Colonne A ·", "Première ligne lue", "Précédent", "Continuer", "points-virgules"):
        assert text in html
    assert "JJ/MM/AAAA" in html
    import_id = html.split("/imports/")[1].split("/confirm")[0]

    step3 = clients["admin"].post(
        f"/imports/{import_id}/confirm",
        data={"format": "csv", "account_id": str(account_id), "date_column": "0", "label_column": "1", "amount_column": "2", "date_format": "%d/%m/%Y"},
    ).text
    for text in ("Lignes lues", "Doublons ignorés", "Virements exclus", "À importer", "Vérifier ligne par ligne", "À trier"):
        assert text in step3
    assert f"/imports/back?import_id={import_id}" in step3

    back = clients["admin"].get("/imports/back", params={"import_id": import_id, "format": "csv", "account_id": account_id})
    assert back.status_code == 200 and "Confirmer les colonnes" in back.text
    assert "Choisir le fichier" in clients["admin"].get("/imports/step1").text
    # A vanished upload sends the wizard back to its first step.
    gone = clients["admin"].get("/imports/back", params={"import_id": "0" * 32, "format": "csv", "account_id": account_id})
    assert "Choisir le fichier" in gone.text

    done = clients["admin"].post(
        f"/imports/{import_id}/execute",
        data={"format": "csv", "account_id": str(account_id), "date_column": "0", "label_column": "1", "amount_column": "2", "date_format": "%d/%m/%Y", "include": ["0", "1"]},
    ).text
    assert "Derniers imports" in done and "fidelity.csv" in done and 'hx-swap-oob="true"' in done
    with SessionLocal() as db:
        log = crud.list_import_logs(db, 1)[0]
        assert (log.filename, log.lines, log.imported) == ("fidelity.csv", 2, 2)
    assert "fidelity.csv" in clients["admin"].get("/imports/new").text


def test_import_refuses_a_file_over_five_megabytes(clients, demo):
    big = b"a" * (5 * 1024 * 1024 + 1)
    response = clients["admin"].post(
        "/imports/preview",
        files={"file": ("big.csv", big, "text/csv")},
        data={"account_id": str(demo["account_id"])},
    )
    assert "5 Mo maximum" in response.text


def test_import_log_is_part_of_the_backup(clients):
    with SessionLocal() as db:
        if not db.query(ImportLog).count():
            crud.record_import_log(db, "x.csv", "A", 1, 0, 1)
    assert '"import_logs"' in clients["admin"].get("/export/json").text


# --- Paramètres -------------------------------------------------------------


def test_settings_is_one_page_with_every_section(clients):
    html = clients["admin"].get("/settings").text
    for anchor in ("s-gerer", "s-comptes", "s-categories", "s-regles", "s-cap", "s-preferences", "s-utilisateurs", "s-donnees"):
        assert f'id="{anchor}"' in html
    for text in ("Budgets", "Détecter les modes de paiement manquants", "Début du mois budgétaire", "Zone sensible", "instance locale"):
        assert text in html
    viewer_html = clients["viewer"].get("/settings").text
    assert "Zone sensible" not in viewer_html


def test_budget_start_day_is_saved_and_validated(clients):
    assert clients["admin"].post("/settings/budget-start-day", data={"budget_start_day": "10"}).status_code == 200
    with SessionLocal() as db:
        assert crud.get_cap_settings(db).budget_start_day == 10
    assert clients["admin"].post("/settings/budget-start-day", data={"budget_start_day": "7"}).status_code == 400
    clients["admin"].post("/settings/budget-start-day", data={"budget_start_day": "1"})
    with SessionLocal() as db:
        assert crud.get_cap_settings(db).budget_start_day == 1


def test_delete_all_transactions_is_admin_only_and_needs_the_confirmation(clients):
    for role in ("editor", "viewer"):
        assert clients[role].post("/settings/delete-all-transactions", data={"confirm": "yes"}).status_code == 403
    assert clients["admin"].post("/settings/delete-all-transactions", data={}).status_code == 400
    with SessionLocal() as db:
        assert crud.get_account_balances(db)  # nothing was touched


# --- Modes de paiement ------------------------------------------------------


def test_sensitive_settings_refuse_a_request_from_another_site(clients):
    """A page on another site cannot wipe the operations or change the login
    page, even for a signed-in administrator: its Origin is not Twiga's."""
    foreign = {"Origin": "http://evil.example"}
    admin = clients["admin"]
    assert admin.post("/settings/delete-all-transactions", data={"confirm": "yes"}, headers=foreign).status_code == 403
    assert admin.post("/settings/login-accounts", data={"show": "on"}, headers=foreign).status_code == 403
    same = {"Origin": "http://testserver"}
    assert admin.post("/settings/login-accounts", data={"show": ""}, headers=same).status_code == 200


def test_payment_method_icon_is_chosen_from_the_picker(clients):
    page = clients["admin"].get("/payment-methods").text
    assert 'role="radiogroup"' in page and 'value="piggy-bank"' not in page
    clients["admin"].post("/payment-methods/create", data={"name": "Fidelity Wero", "icon": "gift"})
    from backend.models import PaymentMethod
    from backend.payment_methods import get_payment_method_icon_name, refresh_chosen_icons

    refresh_chosen_icons()
    try:
        assert get_payment_method_icon_name("Fidelity Wero") == "gift"
    finally:
        with SessionLocal() as db:
            for pm in db.query(PaymentMethod).filter(PaymentMethod.name == "Fidelity Wero"):
                db.delete(pm)
            db.commit()
        refresh_chosen_icons()
    # An icon outside the picker falls back to the first one.
    clients["admin"].post("/payment-methods/create", data={"name": "Fidelity Odd", "icon": "not-an-icon"})
    with SessionLocal() as db:
        odd = db.query(PaymentMethod).filter(PaymentMethod.name == "Fidelity Odd").one()
        assert odd.icon == "credit-card"
        db.delete(odd)
        db.commit()
    refresh_chosen_icons()


# --- Mon profil -------------------------------------------------------------


def test_profile_shows_member_since_and_the_password_meter(clients):
    html = clients["admin"].get("/profile").text
    for text in ("membre depuis", "Identité", "Identifiant", "Mot de passe", "Affichage sur cet appareil", "8 caractères au moins."):
        assert text in html
