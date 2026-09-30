# Twiga 🦒

_Voir loin. Voir juste._ ("See far. See true.")

Twiga ("giraffe" in Swahili) is a personal finance app: a tool for steering
your money (import → categorize → follow your budget), not accounting
software. 100% local and self-hosted: no automatic bank connection, no
outgoing network call, no telemetry.

> **Language:** the user interface is currently in French. The documentation
> and scripts are in English. Menu names are quoted in French, with a
> translation the first time they appear.

## One-command install on Proxmox

On the Proxmox VE host, as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/d4rkbean/Twiga/main/proxmox/twiga-lxc.sh)"
```

The script creates a Debian 12 LXC container, installs Docker and Twiga in it,
generates the passwords, schedules a daily backup, and prints the address and
the admin password. Settings (container ID, static IP, resources...) are
passed as environment variables, see the header of the script. Read it before
running it.

## Requirements

- Docker
- Docker Compose (included with Docker Desktop, or the `docker-compose-plugin`
  package on Linux)

## Install

```bash
git clone https://github.com/d4rkbean/Twiga.git twiga
cd twiga
cp .env.example .env
# Edit .env: set at least a DB_PASSWORD and an AUTH_PASSWORD different from
# the defaults before exposing the app beyond your own machine.
docker compose up -d
```

Open **http://localhost:8181** (internal port 8080; change `PORT` in `.env` to
change the port exposed on the host).

`entrypoint.sh` runs the migrations (`alembic upgrade head`) every time the
`app` container starts, so there is nothing to run by hand in normal use.

## Default credentials — ⚠️ change them

On the very first start with an empty database, an **admin** account is
created with the password set in `AUTH_PASSWORD` in `.env` (`changeme` if you
did not change it in `.env.example`).

**Important**: `AUTH_PASSWORD` is only read on that first initialization. Once
the admin account exists, editing `AUTH_PASSWORD` in `.env` and restarting has
no effect: change the password from the app ("Paramètres" (Settings) >
"Profil" (Profile) once logged in, or "Paramètres" > "Utilisateurs" (Users) to
reset another account's password).

**Change this password on your first login**, especially before exposing the
app beyond your local network (`AUTH_ENABLED=true`, the default, protects
every page with a signed session cookie valid for 30 days).

## Backing up your data

Two complementary options:

- **From the app**: "Paramètres" > "Données" (Data) > "Export JSON complet"
  downloads a `twiga-export-YYYY-MM-DD.json` file with all your data
  (accounts, categories, transactions, budgets, projects, rules, pending
  checks, etc. — user accounts excluded).
- **PostgreSQL dump** (recommended for automated backups, restores the exact
  state of the database):
  ```bash
  docker compose exec -T db pg_dump -U finance finance > twiga-$(date +%Y%m%d).sql
  ```
  See `INSTALL.md` to schedule a daily backup.

## Restoring from a JSON backup

"Paramètres" > "Données" > "Restaurer depuis une sauvegarde JSON" (admin role
only): pick the exported file and confirm. The restore updates rows that
already exist (same id) and adds new ones; it never deletes anything. A
progress bar is shown during the import (it can take several minutes on a
large database).

User accounts are not part of the JSON export: recreate them in "Paramètres" >
"Utilisateurs" after a restore.

To restore a PostgreSQL dump instead, see `INSTALL.md`.

## Updating

```bash
git pull
docker compose up --build -d
```

Alembic migrations are applied automatically on restart.

## License

Code under the [MIT](LICENSE) license. See `LICENSES.md` for the audit of
third-party dependencies.
