#!/usr/bin/env bash
# Twiga — creates a Debian 13 LXC container on Proxmox VE with Docker and
# Twiga installed and running.
#
# Run it as root on the Proxmox HOST (not inside a container):
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/d4rkbean/Twiga/main/proxmox/twiga-lxc.sh)"
#
# Everything is set through environment variables, all optional:
#   CTID        container ID               (default: next free ID)
#   CT_NAME     hostname                   (default: twiga)
#   CORES       CPU cores                  (default: 2)
#   RAM_MB      memory in MB               (default: 2048)
#   DISK_GB     disk size in GB            (default: 20)
#   STORAGE     storage for the disk       (default: first "rootdir" storage)
#   TPL_STORAGE storage for templates      (default: local)
#   BRIDGE      network bridge             (default: vmbr0)
#   IP          "dhcp" or 192.168.1.50/24  (default: dhcp)
#   GATEWAY     gateway, for a static IP
#   PORT        port exposed by Twiga      (default: 8181)
#   BRANCH      repository branch          (default: main)
#   REPO_URL    repository to clone        (default: https://github.com/d4rkbean/Twiga.git)
#
# Example with a static IP:
#   IP=192.168.1.50/24 GATEWAY=192.168.1.1 bash twiga-lxc.sh

set -Eeuo pipefail

CT_NAME="${CT_NAME:-twiga}"
CORES="${CORES:-2}"
RAM_MB="${RAM_MB:-2048}"
DISK_GB="${DISK_GB:-20}"
TPL_STORAGE="${TPL_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GATEWAY="${GATEWAY:-}"
PORT="${PORT:-8181}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/d4rkbean/Twiga.git}"

msg()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

CREATED=0
on_error() {
  local line="$1"
  printf '\033[1;31m✘ Failed at line %s.\033[0m\n' "$line" >&2
  if [[ "$CREATED" == 1 && -n "${CTID:-}" ]]; then
    printf 'Container %s was created but the installation is incomplete.\n' "$CTID" >&2
    printf 'To start over: pct stop %s; pct destroy %s\n' "$CTID" "$CTID" >&2
  fi
}
trap 'on_error $LINENO' ERR

# --- Checks ------------------------------------------------------------------
[[ $EUID -eq 0 ]] || fail "This script must be run as root."
command -v pct >/dev/null && command -v pveam >/dev/null \
  || fail "pct/pveam not found: run this script on the Proxmox VE host, not inside a container."

if [[ "$IP" != "dhcp" && -z "$GATEWAY" ]]; then
  fail "Static IP requested: also set GATEWAY (e.g. GATEWAY=192.168.1.1)."
fi

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
if pct status "$CTID" >/dev/null 2>&1; then
  fail "Container $CTID already exists. Pick another CTID."
fi

if [[ -z "${STORAGE:-}" ]]; then
  STORAGE="$(pvesm status --content rootdir | awk 'NR>1 {print $1; exit}')"
  [[ -n "$STORAGE" ]] || fail "No storage supporting 'rootdir' found. Set STORAGE."
fi

msg "Twiga will be installed in an LXC container:"
printf '    CTID %s · %s · %s cores · %s MB RAM · %s GB on %s · network %s (%s)\n' \
  "$CTID" "$CT_NAME" "$CORES" "$RAM_MB" "$DISK_GB" "$STORAGE" "$BRIDGE" "$IP"
if [[ -t 0 ]]; then
  read -r -p "Continue? [Y/n] " answer
  [[ "${answer:-Y}" =~ ^[Yy]$ ]] || fail "Cancelled."
fi

# --- Debian 13 template ------------------------------------------------------
msg "Looking for the Debian 13 template..."
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '/debian-13-standard/ {print $2}' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || fail "debian-13-standard template not found: run apt full-upgrade on the Proxmox host, then pveam update, and retry."
if ! pveam list "$TPL_STORAGE" | grep -q "$TEMPLATE"; then
  msg "Downloading $TEMPLATE..."
  pveam download "$TPL_STORAGE" "$TEMPLATE" >/dev/null
fi

# --- Container creation ------------------------------------------------------
if [[ "$IP" == "dhcp" ]]; then
  NET="name=eth0,bridge=${BRIDGE},ip=dhcp"
else
  NET="name=eth0,bridge=${BRIDGE},ip=${IP},gw=${GATEWAY}"
fi

msg "Creating container $CTID..."
pct create "$CTID" "${TPL_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$CT_NAME" \
  --cores "$CORES" \
  --memory "$RAM_MB" \
  --swap 512 \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --net0 "$NET" \
  --features nesting=1,keyctl=1 \
  --unprivileged 1 \
  --onboot 1 \
  --ostype debian \
  --tags twiga >/dev/null
CREATED=1

msg "Starting..."
pct start "$CTID"

msg "Waiting for the network..."
CT_IP=""
for _ in $(seq 1 60); do
  CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -n "$CT_IP" ]] && pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
[[ -n "$CT_IP" ]] || fail "The container did not get an IP address."
pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 \
  || fail "The container has no Internet access (DNS/gateway)."
ok "Container reachable at $CT_IP"

# --- Installation inside the container --------------------------------------
# The script is pushed and run inside the container rather than passed on the
# command line: it avoids any quoting or stdin issue with pct exec.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/install.sh" <<'INNER'
#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
# shellcheck disable=SC1091
source /root/twiga-install.env

echo "==> Updating the system"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq curl git ca-certificates openssl cron

echo "==> Installing Docker"
curl -fsSL https://get.docker.com | sh >/dev/null
systemctl enable --now docker >/dev/null 2>&1

echo "==> Fetching Twiga"
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" /opt/twiga
cd /opt/twiga

DB_PASSWORD="$(openssl rand -hex 16)"
ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-16)"
cp .env.example .env
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=${DB_PASSWORD}|" .env
sed -i "s|^AUTH_PASSWORD=.*|AUTH_PASSWORD=${ADMIN_PASSWORD}|" .env
sed -i "s|^PORT=.*|PORT=${PORT}|" .env
chmod 600 .env

echo "==> Building and starting (a few minutes)"
docker compose up -d --build

echo "==> Waiting for the application"
for _ in $(seq 1 90); do
  if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
[[ "${READY:-0}" == 1 ]] || { echo "The application is not answering: docker compose logs app"; exit 1; }

echo "==> Daily backup and update command"
cat > /opt/twiga/backup.sh <<'EOF'
#!/bin/bash
set -euo pipefail
DATE=$(date +%Y%m%d_%H%M)
BACKUP_DIR=/opt/twiga/backups
mkdir -p "$BACKUP_DIR"
cd /opt/twiga
docker compose exec -T db pg_dump -U finance finance > "$BACKUP_DIR/twiga-$DATE.sql"
find "$BACKUP_DIR" -name "*.sql" -mtime +30 -delete
echo "Backup done: twiga-$DATE.sql"
EOF
chmod +x /opt/twiga/backup.sh
echo "0 3 * * * root /opt/twiga/backup.sh >> /var/log/twiga-backup.log 2>&1" > /etc/cron.d/twiga-backup
systemctl enable --now cron >/dev/null 2>&1

cat > /usr/local/bin/twiga-update <<'EOF'
#!/bin/bash
set -euo pipefail
cd /opt/twiga
git pull --ff-only
docker compose up -d --build
echo "Twiga is up to date."
EOF
chmod +x /usr/local/bin/twiga-update

echo "ADMIN_PASSWORD=${ADMIN_PASSWORD}" > /root/twiga-install.result
chmod 600 /root/twiga-install.result
INNER

cat > "$WORK/twiga-install.env" <<ENVFILE
BRANCH='${BRANCH}'
REPO_URL='${REPO_URL}'
PORT='${PORT}'
ENVFILE

pct push "$CTID" "$WORK/install.sh" /root/twiga-install.sh --perms 700
pct push "$CTID" "$WORK/twiga-install.env" /root/twiga-install.env --perms 600

msg "Installing Twiga inside the container (several minutes)..."
pct exec "$CTID" -- bash /root/twiga-install.sh

ADMIN_PASSWORD="$(pct exec "$CTID" -- sed -n 's/^ADMIN_PASSWORD=//p' /root/twiga-install.result)"
pct exec "$CTID" -- rm -f /root/twiga-install.sh /root/twiga-install.env /root/twiga-install.result

echo
ok "Twiga is installed."
cat <<DONE

  Address      http://${CT_IP}:${PORT}
  Login        admin
  Password     ${ADMIN_PASSWORD}

  Write this password down now, then change it in Paramètres > Profil
  (Settings > Profile). It also stays in /opt/twiga/.env, readable by root only.

  Update             pct exec ${CTID} -- twiga-update
  Backups            daily at 3 a.m. in /opt/twiga/backups (30 days)
                     Copy them regularly outside this container.
  Restore your data  Paramètres > Données > Restaurer depuis une sauvegarde JSON
                     (Settings > Data > Restore from a JSON backup)

DONE
