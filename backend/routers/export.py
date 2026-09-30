import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from backend import export, restore
from backend.database import SessionLocal, get_db
from backend.templating import templates

router = APIRouter(prefix="/export", tags=["export"])

# État partagé du process (appli mono-utilisateur, un seul worker uvicorn —
# même principe que le cache du backlog) : un import peut prendre plusieurs
# minutes avec des milliers de transactions, donc il tourne en tâche de
# fond pendant que ce dict est mis à jour, et un endpoint séparé le relit
# pour afficher la progression sans bloquer la requête initiale.
_restore_progress: dict = {"status": "idle", "total": 0, "processed": 0, "error": None, "summary": None}


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Objet non sérialisable en JSON : {value!r}")


@router.get("/json")
def export_json(db: Session = Depends(get_db)):
    data = export.build_full_export(db)
    content = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
    filename = f"twiga-export-{date.today().isoformat()}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/transactions.csv")
def export_transactions_csv(db: Session = Depends(get_db)):
    csv_content = export.build_transactions_csv(db)
    filename = f"twiga-operations-{date.today().isoformat()}.csv"
    # BOM UTF-8 pour qu'Excel détecte correctement l'encodage des accents.
    return Response(
        content="﻿" + csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _run_restore(data: dict) -> None:
    # Sa propre Session, indépendante de celle de la requête HTTP qui a
    # démarré l'import : cette fonction continue de tourner après que cette
    # requête a déjà répondu (BackgroundTasks), la Session liée à
    # Depends(get_db) serait alors déjà fermée.
    db = SessionLocal()
    try:
        restore.restore_from_export(db, data, _restore_progress)
    except Exception:
        pass  # déjà consigné dans _restore_progress par restore_from_export
    finally:
        db.close()


@router.post("/restore", response_class=HTMLResponse)
async def start_restore(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if _restore_progress["status"] == "running":
        # Déjà en cours : on réaffiche juste l'état actuel plutôt que de
        # lancer un second import en parallèle sur la même base.
        return templates.TemplateResponse(
            "export/_restore_progress.html", {"request": request, **_restore_progress}
        )

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        _restore_progress.update(
            {"status": "error", "total": 0, "processed": 0, "error": "Fichier JSON invalide.", "summary": None}
        )
        return templates.TemplateResponse(
            "export/_restore_progress.html", {"request": request, **_restore_progress}
        )

    _restore_progress.update({"status": "running", "total": 0, "processed": 0, "error": None, "summary": None})
    background_tasks.add_task(_run_restore, data)

    return templates.TemplateResponse(
        "export/_restore_progress.html", {"request": request, **_restore_progress}
    )


@router.get("/restore/progress", response_class=HTMLResponse)
def restore_progress(request: Request):
    return templates.TemplateResponse(
        "export/_restore_progress.html", {"request": request, **_restore_progress}
    )
