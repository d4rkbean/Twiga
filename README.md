# Twiga 🦒

_Voir loin. Voir juste._ ("See far. See true.")

Twiga ("giraffe" in Swahili) is a personal finance app: a tool for steering
your money (import → categorize → follow your budget), not accounting
software. 100% local and self-hosted: no automatic bank connection, no
outgoing network call, no telemetry.

> **Language:** the interface is available in **French** (default) and **English**
> (beta). Switch in *Settings → Preferences*, where you can also pick the number and
> date format (French, International or United States). The documentation and scripts
> are in English and use the English menu names. In the French interface they read:
> Settings = Paramètres, Data = Données, Preferences = Préférences, Security =
> Sécurité, Users = Utilisateurs, My profile = Mon profil.

## One-command install on Proxmox

On the Proxmox VE host, as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/d4rkbean/Twiga/main/proxmox/twiga-lxc.sh)"
```

The script creates a Debian 13 LXC container, installs Docker and Twiga in it,
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
no effect: change the password from the app (*Settings → Security → Change the password*
once logged in; as an admin, *Settings → Security → Users* resets another
account's password).

**Change this password on your first login**, especially before exposing the
app beyond your local network (`AUTH_ENABLED=true`, the default, protects
every page with a signed session cookie valid for 30 days).

## Security settings (all optional)

Nothing to set for a normal install: every variable below is empty by default
and the app behaves as before. Set them in `.env`, then
`docker compose up -d`.

- **Forms sent by another site are refused** (with or without
  authentication): a POST whose `Origin` (or `Referer`) is not the address
  Twiga is reached at gets a 403. Behind a reverse proxy, the address is the
  `Host` header the proxy forwards, or `X-Forwarded-Host` when the proxy sets
  it. If your proxy changes `Host` and sets neither, list the public address
  in `TRUSTED_ORIGINS` (comma-separated, e.g.
  `TRUSTED_ORIGINS=https://twiga.example.com`); the refusal is logged with the
  address to add.
- `ALLOWED_HOSTS`: the host names Twiga answers to, comma-separated (e.g.
  `ALLOWED_HOSTS=twiga.local,192.168.1.20`). Any other host name gets a 400,
  which blocks DNS rebinding attacks from a web page. Empty: every host name.
- `BIND_ADDRESS`: the host address the port listens on. `127.0.0.1` keeps the
  app reachable from this machine only (when a reverse proxy runs on the same
  host). Empty: every address, as before.
- `COOKIE_SECURE`: `auto` (default) marks the session cookie `Secure` when the
  request arrives over HTTPS, directly or through a reverse proxy that sends
  `X-Forwarded-Proto: https`; HTTPS responses also carry
  `Strict-Transport-Security`. `true` forces `Secure` (the session then only
  works over HTTPS), `false` never sets it.

## Backing up your data

Two complementary options:

- **From the app**: *Settings → Data → Full JSON export*
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

*Settings → Data → Restore from a JSON backup* (admin role
only): pick the exported file and confirm. The restore updates rows that
already exist (same id) and adds new ones; it never deletes anything. A
progress bar is shown during the import (it can take several minutes on a
large database).

User accounts are not part of the JSON export: recreate them in *Settings → Security → Users*
after a restore.

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
