from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.templating import templates

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/quick", response_class=HTMLResponse)
def quick_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = q.strip()
    if len(query) < 2:
        # Le client ne déclenche déjà qu'à partir de 2 caractères, mais on
        # se protège aussi côté serveur (accès direct à l'URL, etc.).
        return HTMLResponse(content="")

    context = {
        "request": request,
        "query": query,
        "transactions": crud.search_transactions_quick(db, query),
        "categories": crud.search_categories_quick(db, query),
        "projects": crud.search_projects_quick(db, query),
    }
    return templates.TemplateResponse("search/_results.html", context)
