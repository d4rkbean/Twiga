# Twiga — Installation on a Proxmox LXC

The quick way is `proxmox/twiga-lxc.sh` (see the README). This page describes
the same installation step by step, plus the restore and backup procedures.

## Requirements

- Proxmox VE 8 or 9, up to date (`apt update && apt full-upgrade`), whose template list includes `debian-13-standard`. Check with `pveam update && pveam available --section system | grep debian-13`.
- Access to the Proxmox web interface

## Step 1 — Create the LXC container

- Template: Debian 13
- RAM: 1024 MB (2048 recommended)
- CPU: 2 cores
- Disk: 20 GB
- Network: static IP on the local network
- Options: enable **"Nesting"** (required to run Docker inside the LXC)

## Step 2 — Install Docker in the LXC

```bash
apt update && apt upgrade -y
apt install -y curl git
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

## Step 3 — Deploy Twiga

No image is published: `docker-compose.yml` builds the image from the
repository (`build: .`), so clone the whole repository.

```bash
git clone https://github.com/d4rkbean/Twiga.git /opt/twiga
cd /opt/twiga
cp .env.example .env
nano .env   # set at least DB_PASSWORD and AUTH_PASSWORD
docker compose up -d --build
```

`.env` expects these variables (see `.env.example`):

```
DB_PASSWORD=...       # PostgreSQL password
AUTH_ENABLED=true
AUTH_PASSWORD=...      # admin account password, READ ONLY ONCE (see Step 4)
PORT=8181              # port exposed on the host, the app listens on 8080 inside
```

There is no `SECRET_KEY` to provide: the secret that signs session cookies is
generated randomly by the application on its very first start and stored in
the database, never in a configuration file.

Set `DB_PASSWORD` **before the first start**: on an already-initialized
`pgdata` volume, changing it does not change the password stored in
PostgreSQL.

## Step 4 — Check the deployment

```bash
docker compose ps
docker compose logs app --tail=20
```

Open `http://[LXC_IP]:8181` (or the port chosen with `PORT`).

Default login: **admin** / the value of `AUTH_PASSWORD` in `.env`.

**Important**: `AUTH_PASSWORD` is only read when the database is first
initialized (creation of the admin account). Changing it in `.env` afterwards
and running `docker compose up -d` again has NO effect on the existing
password. **Change your password on first login**, in "Paramètres" (Settings)
> "Profil" (Profile).

Both services (`app` and `db`) use `restart: always` in `docker-compose.yml`:
they restart automatically after a reboot of the LXC or a crash. The
PostgreSQL port (5432) is deliberately not exposed outside the internal Docker
network; only the `app` container can reach it.

## Step 5 — Restore your data (optional)

To migrate from another instance, export from it ("Paramètres" > "Données", or
`GET /export/json`), then on the new one:

- Log in as `admin` and change the password.
- "Paramètres" > "Données" > "Restaurer depuis une sauvegarde JSON".
- Upload the `twiga-export-YYYY-MM-DD.json` file and wait for the confirmation.

Things to know after a JSON restore:

- **User accounts are not exported** (on purpose: no password hashes in a
  file). Only `admin` exists; recreate the others in "Paramètres" >
  "Utilisateurs" (Users).
- The JSON restore never deletes: rows already present are updated, new ones
  are added.

To keep everything, users included, restore a SQL dump on an empty database
instead, before the app's first start:

```bash
docker compose up -d db
docker compose exec -T db psql -U finance -d postgres \
  -c "DROP DATABASE IF EXISTS finance" -c "CREATE DATABASE finance OWNER finance"
docker compose exec -T db psql -U finance finance < twiga-20260101.sql
docker compose up -d --build
```

## Step 6 — Automatic backups

A PostgreSQL dump is the most faithful backup: it restores the exact state of
the database, user accounts included (unlike the JSON export of the app, which
excludes them on purpose). It runs on the host side, not from the application
itself: giving an application container access to Docker or to the dumps of
its own database service would amount to near-root access on the host, which
goes against the "100% local, no needless dependency" spirit of the project.

Create `/opt/twiga/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail
DATE=$(date +%Y%m%d_%H%M)
BACKUP_DIR=/opt/twiga/backups
mkdir -p "$BACKUP_DIR"
cd /opt/twiga
docker compose exec -T db pg_dump -U finance finance > "$BACKUP_DIR/twiga-$DATE.sql"
# Keep only the last 30 days
find "$BACKUP_DIR" -name "*.sql" -mtime +30 -delete
echo "Backup done: $BACKUP_DIR/twiga-$DATE.sql"
```

Make it executable and schedule it every night at 3 a.m.:

```bash
chmod +x /opt/twiga/backup.sh
echo "0 3 * * * root /opt/twiga/backup.sh" > /etc/cron.d/twiga-backup
```

These backups stay inside the same container: copy them somewhere else
regularly (another machine, a NAS), otherwise losing the LXC loses them too.

## Step 7 — Updating

```bash
cd /opt/twiga
git pull origin main
docker compose up -d --build
```

Alembic migrations are applied automatically on restart (`entrypoint.sh`), so
there is no extra manual step. Running `backup.sh` before each update is still
recommended.

## Post-deployment checklist

- [ ] App reachable on `http://[LXC_IP]:8181`
- [ ] Admin login works
- [ ] Data restored (check the number of transactions)
- [ ] Other user accounts recreated
- [ ] Backup scheduled (`cat /etc/cron.d/twiga-backup`, then run `/opt/twiga/backup.sh` once)
- [ ] Admin password changed

## Local domain name (optional)

Add this to the DNS of your router or Pi-hole:

```
twiga.local → [LXC_IP]
```

Then open `http://twiga.local:8181`.

## HTTPS reverse proxy (optional)

For HTTPS with a local certificate, install Nginx Proxy Manager or Caddy on
Proxmox (or in another LXC) in front of port `8181`. If the proxy serves Twiga
over HTTPS, remember to set the session cookie to `Secure` (currently only
`httponly` + `SameSite=Lax`, which suits local HTTP; see
`backend/routers/auth.py`).
