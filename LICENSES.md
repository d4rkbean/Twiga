# Dependency licenses

Audit of Twiga's direct dependencies (`requirements.txt` and
`frontend/static/vendor/`). All of them use a permissive license
(MIT/BSD/Apache-2.0) or LGPL with a linking exception: compatible with
Twiga's MIT license.

## Backend (Python — `requirements.txt`)

| Dependency | Version | License | Notes |
|---|---|---|---|
| fastapi | 0.115.0 | MIT | |
| uvicorn[standard] | 0.32.0 | BSD-3-Clause | |
| sqlalchemy | 2.0.36 | MIT | |
| alembic | 1.14.0 | MIT | |
| psycopg2-binary | 2.9.10 | LGPL-3.0-or-later with linking exception | The exception allows use from non-GPL code without having to publish that code; only a modification of psycopg2 itself would have to be republished. |
| jinja2 | 3.1.4 | BSD-3-Clause | |
| python-multipart | 0.0.12 | Apache-2.0 | |
| bcrypt | 4.2.1 | Apache-2.0 | |
| itsdangerous | 2.2.0 | BSD-3-Clause | |
| pypdf | 5.1.0 | BSD-3-Clause | Used to extract text from PDF receipts (`backend/receipts_storage.py`). Replaces reportlab/weasyprint, which are not used in this project (no PDF generation). |

`difflib` (used for the similarity scoring of bulk categorization) is part of
the Python standard library (PSF license): no external dependency, no
licensing question.

## Frontend (vendored JS/CSS — `frontend/static/vendor/`)

| Library | Version found | License |
|---|---|---|
| HTMX | (see `htmx.min.js`, no version in the header) | BSD-2-Clause |
| Alpine.js | (see `alpine.min.js`, no version in the header) | MIT |
| Chart.js | 4.5.1 | MIT |
| chartjs-chart-sankey | 0.15.0 | MIT |
| Tailwind CSS | 4.3.3 | MIT |

Shepherd.js is not present in `frontend/static/vendor/`: the guided tour
(`_tour.html`, `static/js/tour.js`) is a home-grown implementation with no
external dependency.

## Conclusion

No GPL/AGPL license among the direct dependencies, so no copyleft
contamination risk. The only license that is not permissive in the strict
sense (LGPL, psycopg2) comes with a linking exception that makes it a
non-constraint in practice for this project.
