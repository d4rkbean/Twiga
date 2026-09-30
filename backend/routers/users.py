from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import auth, crud
from backend.database import get_db
from backend.templating import templates

router = APIRouter(prefix="/users", tags=["users"])

_ROLES = ("admin", "editor", "viewer")


def _list_context(db: Session) -> dict:
    return {"users": crud.list_users(db)}


def _active_admin_count(db: Session, exclude_id: int | None = None) -> int:
    return sum(
        1
        for user in crud.list_users(db)
        if user.role == "admin" and user.is_active and user.id != exclude_id
    )


@router.get("", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, "roles": _ROLES, **_list_context(db)}
    return templates.TemplateResponse("users/index.html", context)


@router.get("/list", response_class=HTMLResponse)
def users_list(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("users/_content.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()
    error = None
    if not username:
        error = "Le nom d'utilisateur est obligatoire."
    elif role not in _ROLES:
        error = "Rôle invalide."
    elif len(password) < 8:
        error = "Le mot de passe doit faire au moins 8 caractères."
    elif crud.get_user_by_username(db, username) is not None:
        error = f'Un utilisateur "{username}" existe déjà.'

    context = {"request": request, **_list_context(db)}
    if error:
        context["error"] = error
        return templates.TemplateResponse("users/_content.html", context, status_code=400)

    crud.create_user(db, username, password, role)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("users/_content.html", context)


@router.post("/{user_id}/role", response_class=HTMLResponse)
def update_role(request: Request, user_id: int, role: str = Form(...), db: Session = Depends(get_db)):
    if role not in _ROLES:
        raise HTTPException(status_code=400, detail="Rôle invalide")
    target = crud.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    context = {"request": request, **_list_context(db)}
    if target.role == "admin" and role != "admin" and _active_admin_count(db, exclude_id=user_id) == 0:
        context["error"] = "Impossible : il doit rester au moins un administrateur actif."
        return templates.TemplateResponse("users/_content.html", context, status_code=400)

    crud.set_user_role(db, user_id, role)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("users/_content.html", context)


@router.post("/{user_id}/password", response_class=HTMLResponse)
def reset_password(
    request: Request, user_id: int, new_password: str = Form(...), db: Session = Depends(get_db)
):
    target = crud.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    context = {"request": request, **_list_context(db)}
    if len(new_password) < 8:
        context["error"] = "Le mot de passe doit faire au moins 8 caractères."
        return templates.TemplateResponse("users/_content.html", context, status_code=400)

    crud.set_user_password(db, user_id, new_password)
    context = {"request": request, **_list_context(db)}
    context["success"] = f"Mot de passe de {target.username} réinitialisé."
    return templates.TemplateResponse("users/_content.html", context)


@router.post("/{user_id}/active", response_class=HTMLResponse)
def toggle_active(
    request: Request, user_id: int, is_active: str = Form(""), db: Session = Depends(get_db)
):
    target = crud.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    new_active = is_active == "on"  # case à cocher HTML : présente seulement si cochée

    context = {"request": request, **_list_context(db)}
    if target.role == "admin" and not new_active and _active_admin_count(db, exclude_id=user_id) == 0:
        context["error"] = "Impossible : il doit rester au moins un administrateur actif."
        return templates.TemplateResponse("users/_content.html", context, status_code=400)

    crud.set_user_active(db, user_id, new_active)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("users/_content.html", context)


@router.post("/{user_id}/delete", response_class=HTMLResponse)
def remove_user(request: Request, user_id: int, db: Session = Depends(get_db)):
    target = crud.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    current_user = auth.get_current_user(request)
    context = {"request": request, **_list_context(db)}
    if current_user is not None and current_user.id == user_id:
        context["error"] = "Impossible de supprimer votre propre compte."
        return templates.TemplateResponse("users/_content.html", context, status_code=400)
    if target.role == "admin" and _active_admin_count(db, exclude_id=user_id) == 0:
        context["error"] = "Impossible : il doit rester au moins un administrateur actif."
        return templates.TemplateResponse("users/_content.html", context, status_code=400)

    crud.delete_user(db, user_id)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("users/_content.html", context)
