FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
COPY backend/ backend/
COPY frontend/ frontend/
COPY imports/ imports/

# Never run as root in the container: a dedicated unprivileged account limits
# the impact of a possible flaw (upload, compromised dependency...) to what
# that user can do, not root on the host. /app belongs to root after the
# previous COPY steps, hence the explicit chown (fixed uid/gid to stay stable
# across rebuilds).
RUN groupadd -g 1000 twiga && useradd -u 1000 -g twiga -M -s /usr/sbin/nologin twiga \
    && chown -R twiga:twiga /app
USER twiga

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
