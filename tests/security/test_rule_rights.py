"""Creating a rule is the administrator's, from the Rules screen as from a
suggestion of the backlog."""

from backend import auth
from backend.database import SessionLocal
from backend.models import Rule


def _rules_with(keyword: str) -> int:
    with SessionLocal() as db:
        return db.query(Rule).filter(Rule.keyword == keyword).count()


def test_the_policy_is_the_same_on_both_routes():
    for path in ("/rules/create", "/backlog/create-rule"):
        assert auth.check_role_access("admin", "POST", path)
        assert not auth.check_role_access("editor", "POST", path)
        assert not auth.check_role_access("viewer", "POST", path)
    assert auth.check_role_access("editor", "POST", "/backlog/bulk-apply")


def test_an_editor_cannot_create_a_rule_from_a_suggestion(signed_in, security_data):
    response = signed_in["editor"].post(
        "/backlog/create-rule",
        data={"keyword": "SEC-EDITOR-RULE", "category_id": security_data["category_id"]},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 403
    assert _rules_with("SEC-EDITOR-RULE") == 0


def test_an_administrator_still_can(signed_in, security_data):
    response = signed_in["admin"].post(
        "/backlog/create-rule",
        data={"keyword": "SEC-ADMIN-RULE", "category_id": security_data["category_id"]},
    )
    try:
        assert response.status_code == 200
        assert _rules_with("SEC-ADMIN-RULE") == 1
    finally:
        with SessionLocal() as db:
            db.query(Rule).filter(Rule.keyword == "SEC-ADMIN-RULE").delete()
            db.commit()
