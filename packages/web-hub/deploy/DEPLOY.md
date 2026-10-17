# 🚀 Anti-Gravity Hub — Deployment Guide

> Schritt-für-Schritt-Anleitung für das Deployment auf Linux / Proxmox.

---

## 📋 Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [Server vorbereiten](#2-server-vorbereiten)
3. [Option A: Systemd Deployment (empfohlen)](#3-option-a-systemd-deployment-empfohlen)
4. [Option B: Docker Deployment](#4-option-b-docker-deployment)
5. [Nginx & SSL einrichten](#5-nginx--ssl-einrichten)
6. [DNS Konfiguration](#6-dns-konfiguration)
7. [Firewall Regeln](#7-firewall-regeln)
8. [Monitoring & Logs](#8-monitoring--logs)
9. [Backup Strategie](#9-backup-strategie)
10. [Proxmox: Windows VM vs. Linux](#10-proxmox-windows-vm-vs-linux)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Voraussetzungen

| Komponente       | Minimum              | Empfohlen           |
|:-----------------|:---------------------|:--------------------|
| OS               | Debian 12 / Ubuntu 24.04 | Debian 12 LTS  |
| Python           | 3.11+                | 3.12                |
| Node.js          | 22+                  | 22 LTS              |
| RAM              | 512 MB               | 1 GB                |
| CPU              | 1 vCPU               | 2 vCPU              |
| Speicher         | 5 GB                 | 10 GB               |
| Netzwerk         | Öffentliche IP       | Öffentliche IP + Domain |

> **Architekturgrenze:** Der Hub steuert eine laufende Anti-Gravity-Desktop-App
> über CDP und liest deren Profilzustand. Desktop-App und Hub müssen auf demselben
> Linux-Host und unter demselben Benutzerprofil laufen. Die mitgelieferten Units
> verwenden dafür den Benutzer `antigravity`, dessen Home
> `/home/antigravity`, den Projektstamm `/home/antigravity/Projects` und
> `/home/antigravity/.gemini`. Wer einen anderen Desktop-Benutzer verwendet,
> muss `User`, `Group`, `HOME` und die beiden Home-Pfade in **allen fünf** Units
> vor der Installation konsistent anpassen.

---

## 2. Server vorbereiten

### 2.1 System aktualisieren

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 Python installieren

```bash
sudo apt install -y python3 python3-pip python3-venv git nodejs npm rsync curl ca-certificates

# Die React-Produktion benötigt Node.js 22 oder neuer.
node -e 'const major=Number(process.versions.node.split(".")[0]); if (major < 22) { console.error("Node.js 22+ erforderlich"); process.exit(1) }'
```

### 2.3 Benutzer anlegen

```bash
sudo useradd -r -m -s /bin/bash antigravity
sudo install -d -o antigravity -g antigravity -m 0750 \
    /opt/antigravity-web \
    /opt/antigravity-web/logs \
    /var/lib/antigravity \
    /home/antigravity/.gemini \
    /home/antigravity/Projects
```

### 2.4 Dateien kopieren

Immer das vollständige Repository installieren. Einzelne Root-`*.py`-Dateien
reichen nicht aus, weil `src/`, `dashboard/`, `frontend/` und `deploy/` zur
Laufzeit bzw. zum Build gehören:

```bash
git clone REPOSITORY_URL /tmp/antigravity-web
sudo cp -a /tmp/antigravity-web/. /opt/antigravity-web/
sudo rm -rf /opt/antigravity-web/.git
sudo chown -R antigravity:antigravity /opt/antigravity-web
sudo chmod +x /opt/antigravity-web/start.sh
sudo -u antigravity cp /opt/antigravity-web/config.example.json /opt/antigravity-web/config.json
sudo chmod 640 /opt/antigravity-web/config.json
```

Vor dem Start einen zufälligen API-Token erzeugen und als `auth_token` in
`/opt/antigravity-web/config.json` eintragen:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2.5 Abhängigkeiten reproduzierbar installieren

```bash
sudo -u antigravity python3 -m venv /opt/antigravity-web/venv
sudo -u antigravity /opt/antigravity-web/venv/bin/pip install -r /opt/antigravity-web/requirements.lock.txt
sudo -u antigravity npm --prefix /opt/antigravity-web/frontend ci
sudo -u antigravity npm --prefix /opt/antigravity-web/frontend run build
```

Die mitgelieferten systemd-Units verwenden genau diesen venv-Interpreter. Ein
globales `pip install` ist für die systemd-Variante weder nötig noch empfohlen.

---

## 3. Option A: Systemd Deployment (empfohlen)

### 3.1 Service-Dateien kopieren

```bash
cd /opt/antigravity-web

# Vor der Installation auf unbekannte oder falsch einsortierte Direktiven prüfen.
sudo systemd-analyze verify deploy/antigravity-*.service

sudo cp deploy/antigravity-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Die Units lassen `/var/lib/antigravity` über `StateDirectory=antigravity`
anlegen und setzen `ANTIGRAVITY_HUB_DB` auf
`/var/lib/antigravity/dashboard.db`. Eine vorhandene ältere Datenbank im
Installationsordner wird **vor dem ersten Start** mit der SQLite-Backup-API
übernommen, nicht im laufenden Betrieb roh kopiert:

```bash
if [ -f /opt/antigravity-web/dashboard.db ] && [ ! -f /var/lib/antigravity/dashboard.db ]; then
  sudo -u antigravity env \
    SOURCE_DB=/opt/antigravity-web/dashboard.db \
    TARGET_DB=/var/lib/antigravity/dashboard.db \
    /opt/antigravity-web/venv/bin/python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

source_path = Path(os.environ["SOURCE_DB"]).resolve()
target_path = Path(os.environ["TARGET_DB"]).resolve()
source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
result = target.execute("PRAGMA integrity_check").fetchone()[0]
source.close()
target.close()
if result != "ok":
    raise SystemExit(f"Migration integrity check failed: {result}")
print(f"Migrated verified database to {target_path}")
PY
fi

sudo chown -R antigravity:antigravity /var/lib/antigravity
sudo chmod 0750 /var/lib/antigravity
sudo test -r /opt/antigravity-web/config.json
sudo test -x /opt/antigravity-web/venv/bin/python3
```

### 3.2 Services aktivieren und starten

```bash
# Alle Services aktivieren (starten automatisch bei Boot)
sudo systemctl enable antigravity-bridge
sudo systemctl enable antigravity-proxy
sudo systemctl enable antigravity-sessions
sudo systemctl enable antigravity-healer
sudo systemctl enable antigravity-watchdog

# Alle Services starten
sudo systemctl start antigravity-bridge
sleep 3
sudo systemctl start antigravity-proxy
sudo systemctl start antigravity-sessions
sudo systemctl start antigravity-healer
sudo systemctl start antigravity-watchdog
```

### 3.3 Status prüfen

```bash
# Einzelnen Service prüfen
sudo systemctl status antigravity-bridge

# Alle Anti-Gravity-Dienste auf einen Blick
sudo systemctl list-units 'antigravity-*' --type=service
```

### 3.4 Schnellbefehle

```bash
# Alles stoppen
sudo systemctl stop antigravity-{bridge,proxy,sessions,healer,watchdog}

# Alles neustarten
sudo systemctl restart antigravity-{bridge,proxy,sessions,healer,watchdog}

# Service-Logs anzeigen
sudo journalctl -u antigravity-bridge -f
```

---

## 4. Option B: Docker Deployment

Docker ist hier ein host-integriertes Linux-Profil, kein portabler
zustandsloser Web-Stack. `network_mode: host` erlaubt Loopback-Verbindungen zu
lokalen Diensten, gibt dem Container aber bewusst keinen Zugriff auf den
Host-Prozessraum. Die automatische Desktop-/CDP-Prozesssuche ist damit nicht
Bestandteil des verifizierten Containerprofils. Für die vollständige
Desktop-Integration ist der native Start die unterstützte Wahl; Docker eignet
sich für die gekapselten Hub-Dienste mit explizit erreichbaren Endpunkten.

### 4.1 Docker installieren

```bash
# Docker installieren (Debian/Ubuntu)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Docker Compose Plugin (falls nicht enthalten)
sudo apt install -y docker-compose-plugin
```

### 4.2 Persistenten State explizit ergänzen

Das Basis-Compose persistiert Logs. Für eine langlebige Installation kommt ein
deployment-lokaler Override hinzu, der Hub-Datenbank, Anti-Gravity-Profil und
Projekte explizit einbindet:

```bash
sudo install -d -m 0750 /etc/anti-gravity
sudo tee /etc/anti-gravity/compose.state.yml >/dev/null <<'YAML'
services:
  hub:
    environment:
      HOME: /home/antigravity
      ANTIGRAVITY_HUB_DB: /var/lib/antigravity/dashboard.db
    volumes:
      - antigravity-state:/var/lib/antigravity
      - type: bind
        source: ${ANTIGRAVITY_PROFILE_DIR:?set ANTIGRAVITY_PROFILE_DIR}
        target: /home/antigravity/.gemini
      - type: bind
        source: ${ANTIGRAVITY_PROJECTS_DIR:?set ANTIGRAVITY_PROJECTS_DIR}
        target: /home/antigravity/Projects

volumes:
  antigravity-state:
    name: antigravity-state
  antigravity-logs:
    name: antigravity-logs
YAML

export ANTIGRAVITY_PROFILE_DIR=/home/antigravity/.gemini
export ANTIGRAVITY_PROJECTS_DIR=/home/antigravity/Projects
export ANTIGRAVITY_HUB_CONFIG_FILE=/opt/antigravity-web/config.json

# Vor dem Start Pfade, Variablen und das zusammengeführte Modell prüfen.
docker compose \
  -f docker-compose.yml \
  -f /etc/anti-gravity/compose.state.yml \
  config --quiet
```

Die numerische UID/GID des Containerbenutzers muss Schreibrechte auf den beiden
Bind-Mounts besitzen. Das ist vor dem ersten Start mit `docker compose run --rm
hub id` und `stat -c '%u:%g %n' "$ANTIGRAVITY_PROFILE_DIR"
"$ANTIGRAVITY_PROJECTS_DIR"` zu prüfen und gezielt anzugleichen.

### 4.3 Image bauen und starten

```bash
cd /opt/antigravity-web

# Bauen
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml build

# Starten (im Hintergrund)
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml up -d

# Status prüfen
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml ps

# Logs anzeigen
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml logs -f
```

### 4.4 Docker-Befehle

```bash
# Alles stoppen
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml down

# Neustart
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml restart

# Einzelnen Service neustarten
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml restart hub

# Logs eines Services
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml logs -f hub

# In Container schauen
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml exec hub sh
```

Ohne den Override ist `/app/dashboard.db` Containerzustand und geht beim
Recreate verloren. `docker compose down -v` löscht zusätzlich benannte Volumes
und gehört **nicht** in einen normalen Update-Ablauf.

---

## 5. Nginx & SSL einrichten

Die A-/AAAA-Records aus [Abschnitt 6](#6-dns-konfiguration) müssen bereits auf
diesen Host zeigen. Die TLS-Vorlage wird absichtlich **erst nach** erfolgreicher
Zertifikatsausstellung aktiviert; dadurch referenziert `nginx -t` niemals noch
nicht vorhandene Zertifikatsdateien.

### 5.1 Nginx und Certbot installieren

```bash
sudo apt install -y nginx apache2-utils certbot
```

### 5.2 Phase 1: HTTP-ACME-Bootstrap

```bash
BASE_DOMAIN="example.com"
APP_DOMAIN="app.${BASE_DOMAIN}"
API_DOMAIN="api.${BASE_DOMAIN}"
MONITOR_DOMAIN="monitor.${BASE_DOMAIN}"
CERT_NAME="${APP_DOMAIN}"

sudo install -d -o root -g www-data -m 0755 /var/www/certbot

# Temporäre reine HTTP-Konfiguration: nur ACME ist erreichbar.
sudo tee /etc/nginx/sites-available/antigravity-bootstrap >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${APP_DOMAIN} ${API_DOMAIN} ${MONITOR_DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 503;
    }
}
EOF

sudo ln -sfn \
  /etc/nginx/sites-available/antigravity-bootstrap \
  /etc/nginx/sites-enabled/antigravity-bootstrap
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# Der explizite Zertifikatsname entspricht später exakt /live/CERT_NAME/.
sudo certbot certonly \
  --webroot -w /var/www/certbot \
  --cert-name "${CERT_NAME}" \
  -d "${APP_DOMAIN}" \
  -d "${API_DOMAIN}" \
  -d "${MONITOR_DOMAIN}"

sudo test -r "/etc/letsencrypt/live/${CERT_NAME}/fullchain.pem"
sudo test -r "/etc/letsencrypt/live/${CERT_NAME}/privkey.pem"
```

### 5.3 Phase 2: authentifizierte TLS-Vorlage aktivieren

Im Repository verwendet die Vorlage bewusst getrennte Platzhalter:
`BASE_DOMAIN` für die drei Hosts und `CERT_NAME` für den tatsächlichen
Let's-Encrypt-Verzeichnisnamen.

```bash
# Verpflichtende Anmeldung für App und Monitor erzeugen.
sudo htpasswd -c /etc/nginx/antigravity.htpasswd antigravity-admin
sudo chown root:www-data /etc/nginx/antigravity.htpasswd
sudo chmod 0640 /etc/nginx/antigravity.htpasswd

sudo sed \
  -e "s/BASE_DOMAIN/${BASE_DOMAIN}/g" \
  -e "s/CERT_NAME/${CERT_NAME}/g" \
  deploy/nginx-antigravity.conf \
  | sudo tee /etc/nginx/sites-available/antigravity >/dev/null

sudo rm -f /etc/nginx/sites-enabled/antigravity-bootstrap
sudo rm -f /etc/nginx/sites-available/antigravity-bootstrap
sudo ln -sfn \
  /etc/nginx/sites-available/antigravity \
  /etc/nginx/sites-enabled/antigravity

# Erst jetzt existieren die referenzierten Zertifikate.
sudo nginx -t
sudo systemctl reload nginx
```

Die App- und API-VHosts akzeptieren jeweils maximal `20M` Request-Body. Das ist
die gemeinsame Reverse-Proxy-Grenze für Hub-Attachments und API-Requests.

> **Sicherheitsgrenze:** Port 8000 darf niemals direkt veröffentlicht werden.
> Die TLS-Konfiguration verlangt Basic Auth für App und Monitor und entfernt
> Wildcard-CORS. Für öffentliche Hosts wird zusätzlich ein VPN oder eine
> IP-Allowlist empfohlen. `api.${BASE_DOMAIN}` verwendet weiterhin die eigene
> Bearer-/API-Key-Authentifizierung.

### 5.4 Erneuerung und Reload verifizieren

```bash
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh >/dev/null <<'SH'
#!/bin/sh
set -eu
nginx -t
systemctl reload nginx
SH
sudo chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

sudo certbot renew --dry-run
sudo nginx -t
```

Bei einem Fehler bleibt die bisher geladene Konfiguration aktiv; ein Reload
wird nur nach erfolgreichem Syntax- und Zertifikatstest ausgeführt.

---

## 6. DNS Konfiguration

Beim Domain-Registrar folgende **A-Records** anlegen:

| Subdomain       | Typ | Ziel              | TTL  |
|:----------------|:----|:-------------------|:-----|
| `app.BASE_DOMAIN`    | A   | `DEINE_SERVER_IP` | 300  |
| `api.BASE_DOMAIN`    | A   | `DEINE_SERVER_IP` | 300  |
| `monitor.BASE_DOMAIN`| A   | `DEINE_SERVER_IP` | 300  |

Alternativ ein **Wildcard-Record**:

| Subdomain  | Typ | Ziel              | TTL  |
|:-----------|:----|:-------------------|:-----|
| `*.BASE_DOMAIN` | A   | `DEINE_SERVER_IP` | 300  |

> **Tipp:** DNS-Propagierung kann bis zu 48 Stunden dauern. Prüfen mit:
> ```bash
> dig +short app.example.com
> ```

---

## 7. Firewall Regeln

### Mit UFW (empfohlen)

```bash
# SSH nicht vergessen!
sudo ufw allow 22/tcp

# HTTP und HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Firewall aktivieren
sudo ufw enable

# Status prüfen
sudo ufw status verbose
```

> **Wichtig:** Die Ports 8000-8010 müssen **NICHT** öffentlich geöffnet werden!
> Nginx leitet den Traffic intern weiter.

### Mit iptables (alternativ)

```bash
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -A INPUT -j DROP
```

---

## 8. Monitoring & Logs

### 8.1 Systemd Logs (journalctl)

```bash
# All Anti-Gravity logs live
sudo journalctl -u 'antigravity-*' -f

# Logs eines bestimmten Services
sudo journalctl -u antigravity-bridge -f

# Logs der letzten Stunde
sudo journalctl -u antigravity-bridge --since "1 hour ago"

# Logs seit dem letzten Boot
sudo journalctl -u antigravity-bridge -b
```

### 8.2 Anwendungs-Logs

```bash
# Log-Dateien der Services
ls -la /opt/antigravity-web/logs/

# Live-Monitoring
tail -f /opt/antigravity-web/logs/*.log
```

### 8.3 Health Checks

```bash
# Manuell prüfen
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s http://127.0.0.1:8001/health | python3 -m json.tool
curl -s http://127.0.0.1:8002/health | python3 -m json.tool
curl -s http://127.0.0.1:8007/health | python3 -m json.tool
curl -s http://127.0.0.1:8010/health | python3 -m json.tool

# Watchdog Dashboard (zeigt Gesamtstatus)
curl -s http://127.0.0.1:8010/status | python3 -m json.tool
```

### 8.4 Einfaches Monitoring-Script

```bash
#!/bin/bash
# Speichern als /opt/antigravity-web/check_health.sh
for port in 8000 8001 8002 8007 8010; do
    status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/health" 2>/dev/null)
    if [ "$status" = "200" ]; then
        echo "Port ${port}: ✓ OK"
    else
        echo "Port ${port}: ✗ FEHLER (HTTP ${status})"
    fi
done
```

---

## 9. Backup und Restore

### 9.1 Verbindlicher Zustandsvertrag

| Pfad | Priorität | Inhalt |
|:-----|:----------|:-------|
| `/var/lib/antigravity/dashboard.db` | **Kritisch** | Projekte, Campaigns, Tasks, PR-/Evidence-/Freigabe- und Audit-Zustand |
| `/opt/antigravity-web/logs/uptime.db` | Hoch | Watchdog-Historie und Alerts |
| `/opt/antigravity-web/config.json` | **Kritisch/secret** | Tokens, GitHub-, Service- und Projektbasis-Konfiguration |
| `/home/antigravity/.gemini/` | **Kritisch/privat** | Anti-Gravity-Conversations, Brain, Runtime- und Projektsettings |
| `/home/antigravity/Projects/` | **Kritisch** | lokale Repositories einschließlich noch nicht committeter Arbeit |
| `/opt/antigravity-web/logs/` | Mittel | Diagnose- und Operationslogs |
| Repository und `deploy/` | Niedrig | reproduzierbare Software-/Unit-/Proxy-Konfiguration |

Eine laufende SQLite-Datenbank darf niemals mit `cp` oder `tar` allein gesichert
werden. Entweder wird die SQLite-Backup-API verwendet oder **jeder** schreibende
Prozess wird vorher sauber beendet. Backups enthalten Secrets und private
Projektinhalte; das Backup-Ziel braucht Modus `0700` und eine separate
verschlüsselte Off-host-Kopie.

### 9.2 Vollständiges systemd-/Native-Backup

Für einen vollständigen Snapshot zuerst die Anti-Gravity-Desktop-App regulär
beenden. Danach:

```bash
BACKUP_ROOT=/backups/anti-gravity
BACKUP_ID="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${BACKUP_ID}"

sudo install -d -o root -g root -m 0700 "${BACKUP_ROOT}"
sudo install -d -o antigravity -g antigravity -m 0700 \
  "${BACKUP_DIR}" "${BACKUP_DIR}/databases"

# Keine weiteren Hub-Schreibzugriffe während Profil-/Projekt-Snapshot.
sudo systemctl stop antigravity-{watchdog,healer,sessions,proxy,bridge}

# Auch bei WAL-Datenbanken entsteht über backup() eine geschlossene,
# eigenständig wiederherstellbare Zieldatenbank.
sudo -u antigravity env BACKUP_DIR="${BACKUP_DIR}" \
  /opt/antigravity-web/venv/bin/python3 - <<'PY'
import hashlib
import os
import sqlite3
from pathlib import Path

backup_dir = Path(os.environ["BACKUP_DIR"]) / "databases"
sources = {
    "dashboard.db": Path("/var/lib/antigravity/dashboard.db"),
    "uptime.db": Path("/opt/antigravity-web/logs/uptime.db"),
}
for name, source_path in sources.items():
    if not source_path.is_file():
        raise SystemExit(f"Required database missing: {source_path}")
    destination = backup_dir / name
    source = sqlite3.connect(
        f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True
    )
    target = sqlite3.connect(destination)
    with target:
        source.backup(target)
    result = target.execute("PRAGMA integrity_check").fetchone()[0]
    source.close()
    target.close()
    if result != "ok":
        raise SystemExit(f"Integrity check failed for {name}: {result}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"{name}: integrity=ok sha256={digest}")
PY

# Secret-Konfiguration und geschlossener privater/profile State.
sudo install -o root -g root -m 0600 \
  /opt/antigravity-web/config.json "${BACKUP_DIR}/config.json"
sudo rsync -aHAX --numeric-ids /home/antigravity/.gemini/ \
  "${BACKUP_DIR}/gemini-profile/"
sudo rsync -aHAX --numeric-ids /home/antigravity/Projects/ \
  "${BACKUP_DIR}/projects/"
sudo rsync -aHAX --numeric-ids \
  --exclude='uptime.db' --exclude='uptime.db-wal' --exclude='uptime.db-shm' \
  /opt/antigravity-web/logs/ "${BACKUP_DIR}/logs/"

sudo chown -R root:root "${BACKUP_DIR}"
sudo chmod -R go-rwx "${BACKUP_DIR}"
sudo sh -c "cd '${BACKUP_DIR}' && \
  find . -type f ! -name SHA256SUMS -print0 | sort -z | \
  xargs -0 sha256sum > SHA256SUMS"

sudo systemctl start antigravity-{bridge,proxy,sessions,healer,watchdog}
echo "Backup: ${BACKUP_DIR}"
```

Erst nach der Verifikation aus Abschnitt 9.3 darf ein automatischer Job ältere
Backups entfernen. Ein Cron-/Timer-Job verwendet denselben Ablauf; er darf nicht
auf einen einzelnen `tar`-Befehl verkürzt werden.

### 9.3 Backup vor Rotation verifizieren

```bash
sudo sh -c "cd '${BACKUP_DIR}' && sha256sum --check SHA256SUMS"
sudo env BACKUP_DIR="${BACKUP_DIR}" python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

backup_dir = Path(os.environ["BACKUP_DIR"])
json.loads((backup_dir / "config.json").read_text(encoding="utf-8"))
for database in sorted((backup_dir / "databases").glob("*.db")):
    connection = sqlite3.connect(
        f"file:{database.resolve().as_posix()}?mode=ro", uri=True
    )
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    if result != "ok":
        raise SystemExit(f"{database}: {result}")
    print(f"{database.name}: integrity=ok")
print("config.json: valid JSON")
PY

# Beispiel: erst nach erfolgreicher Prüfung Backups älter als 30 Tage entfernen.
sudo find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime +30 \
  -name '20*T*Z' -exec rm -rf -- {} +
```

### 9.4 systemd-/Native-Restore mit Prüfung

Der Restore überschreibt lokalen Zustand. Vorher den exakten Backup-Pfad
prüfen, eine zusätzliche Kopie des aktuellen Zustands anlegen und Desktop-App
sowie alle Hub-Dienste beenden.

```bash
RESTORE_DIR=/backups/anti-gravity/REPLACE_WITH_BACKUP_ID
sudo test -d "${RESTORE_DIR}/databases"
sudo sh -c "cd '${RESTORE_DIR}' && sha256sum --check SHA256SUMS"
sudo systemctl stop antigravity-{watchdog,healer,sessions,proxy,bridge}

# Geschlossene, bereits verifizierte SQLite-Backups einsetzen; alte WAL-/SHM-
# Sidecars dürfen nicht mit einem neuen Hauptfile kombiniert werden.
sudo rm -f /var/lib/antigravity/dashboard.db{,-wal,-shm}
sudo rm -f /opt/antigravity-web/logs/uptime.db{,-wal,-shm}
sudo install -o antigravity -g antigravity -m 0640 \
  "${RESTORE_DIR}/databases/dashboard.db" \
  /var/lib/antigravity/dashboard.db
sudo install -o antigravity -g antigravity -m 0640 \
  "${RESTORE_DIR}/databases/uptime.db" \
  /opt/antigravity-web/logs/uptime.db
sudo install -o antigravity -g antigravity -m 0640 \
  "${RESTORE_DIR}/config.json" /opt/antigravity-web/config.json

# Erst dry-run lesen, dann dieselben Quellen ohne -n wiederherstellen.
sudo rsync -aHAXn --delete "${RESTORE_DIR}/gemini-profile/" /home/antigravity/.gemini/
sudo rsync -aHAXn --delete "${RESTORE_DIR}/projects/" /home/antigravity/Projects/
sudo rsync -aHAXn --delete \
  --exclude='uptime.db' --exclude='uptime.db-wal' --exclude='uptime.db-shm' \
  "${RESTORE_DIR}/logs/" /opt/antigravity-web/logs/
sudo rsync -aHAX --delete "${RESTORE_DIR}/gemini-profile/" /home/antigravity/.gemini/
sudo rsync -aHAX --delete "${RESTORE_DIR}/projects/" /home/antigravity/Projects/
sudo rsync -aHAX --delete \
  --exclude='uptime.db' --exclude='uptime.db-wal' --exclude='uptime.db-shm' \
  "${RESTORE_DIR}/logs/" /opt/antigravity-web/logs/
sudo chown -R antigravity:antigravity \
  /var/lib/antigravity \
  /opt/antigravity-web/logs \
  /home/antigravity/.gemini \
  /home/antigravity/Projects

sudo systemctl start antigravity-{bridge,proxy,sessions,healer,watchdog}
for port in 8000 8001 8002 8007 8010; do
  curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >/dev/null
done

sudo -u antigravity env ANTIGRAVITY_HUB_DB=/var/lib/antigravity/dashboard.db \
  /opt/antigravity-web/venv/bin/python3 - <<'PY'
import sqlite3
from pathlib import Path

for path in (
    Path("/var/lib/antigravity/dashboard.db"),
    Path("/opt/antigravity-web/logs/uptime.db"),
):
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    if result != "ok":
        raise SystemExit(f"{path}: {result}")
    print(f"{path}: integrity=ok")
PY
```

Erst wenn Healthchecks, DB-Integrität, Projektliste und eine vorhandene Campaign
in der Website korrekt erscheinen, gilt der Restore als bestanden.

### 9.5 Docker-Volumes sichern und wiederherstellen

Mit dem Override aus Abschnitt 4 heißen die Volumes deterministisch
`antigravity-state` und `antigravity-logs`. Für einen WAL-sicheren Snapshot den
Hub und die Desktop-App beenden, dann beide **geschlossenen** Volumes sichern:

```bash
BACKUP_DIR=/backups/anti-gravity/docker-$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o root -g root -m 0700 "${BACKUP_DIR}"
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml stop hub

docker run --rm \
  --mount type=volume,src=antigravity-state,dst=/source,readonly \
  --mount type=bind,src="${BACKUP_DIR}",dst=/backup \
  alpine:3.22 sh -c 'tar -C /source -czf /backup/state-volume.tar.gz .'
docker run --rm \
  --mount type=volume,src=antigravity-logs,dst=/source,readonly \
  --mount type=bind,src="${BACKUP_DIR}",dst=/backup \
  alpine:3.22 sh -c 'tar -C /source -czf /backup/logs-volume.tar.gz .'

# Config und beide Host-Bind-Mounts gehören zum selben Backup-Satz.
sudo install -m 0600 "${ANTIGRAVITY_HUB_CONFIG_FILE}" "${BACKUP_DIR}/config.json"
sudo rsync -aHAX "${ANTIGRAVITY_PROFILE_DIR}/" "${BACKUP_DIR}/gemini-profile/"
sudo rsync -aHAX "${ANTIGRAVITY_PROJECTS_DIR}/" "${BACKUP_DIR}/projects/"
sudo sh -c "cd '${BACKUP_DIR}' && \
  find . -type f ! -name SHA256SUMS -print0 | sort -z | \
  xargs -0 sha256sum > SHA256SUMS"

docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml start hub
```

Restore nur nach `sha256sum --check`, gestopptem Hub und einem kontrollierten
Dry-run der Profil-/Projekt-`rsync`s. Die folgenden Volume-Befehle leeren die
beiden **explizit benannten** Zielvolumes und spielen den geprüften Satz ein:

```bash
RESTORE_DIR=/backups/anti-gravity/REPLACE_WITH_DOCKER_BACKUP_ID
sudo sh -c "cd '${RESTORE_DIR}' && sha256sum --check SHA256SUMS"
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml stop hub

docker run --rm \
  --mount type=volume,src=antigravity-state,dst=/target \
  --mount type=bind,src="${RESTORE_DIR}",dst=/backup,readonly \
  alpine:3.22 sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -C /target -xzf /backup/state-volume.tar.gz'
docker run --rm \
  --mount type=volume,src=antigravity-logs,dst=/target \
  --mount type=bind,src="${RESTORE_DIR}",dst=/backup,readonly \
  alpine:3.22 sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -C /target -xzf /backup/logs-volume.tar.gz'

sudo rsync -aHAXn --delete "${RESTORE_DIR}/gemini-profile/" "${ANTIGRAVITY_PROFILE_DIR}/"
sudo rsync -aHAXn --delete "${RESTORE_DIR}/projects/" "${ANTIGRAVITY_PROJECTS_DIR}/"
# Nach Sichtprüfung werden exakt dieselben Quellen ohne Dry-run eingesetzt.
sudo rsync -aHAX --delete "${RESTORE_DIR}/gemini-profile/" "${ANTIGRAVITY_PROFILE_DIR}/"
sudo rsync -aHAX --delete "${RESTORE_DIR}/projects/" "${ANTIGRAVITY_PROJECTS_DIR}/"
sudo install -o antigravity -g antigravity -m 0640 \
  "${RESTORE_DIR}/config.json" "${ANTIGRAVITY_HUB_CONFIG_FILE}"

# Vor dem Dienststart beide wiederhergestellten SQLite-Dateien im Container
# read-only prüfen. Der temporäre Container startet keinen Hub-Dienst.
docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml \
  run --rm --no-deps -T hub python3 - <<'PY'
import sqlite3
from pathlib import Path

for path in (
    Path("/var/lib/antigravity/dashboard.db"),
    Path("/app/logs/uptime.db"),
):
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    if result != "ok":
        raise SystemExit(f"{path}: {result}")
    print(f"{path}: integrity=ok")
PY

docker compose -f docker-compose.yml -f /etc/anti-gravity/compose.state.yml up -d hub
for port in 8000 8001 8002 8007 8010; do
  curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >/dev/null
done
```

Ein reines „Container läuft“ ist noch kein bestandener Restore: Zusätzlich zu
den fünf Healthchecks müssen Projektliste und eine vorhandene Campaign in der
Website mit dem Backup übereinstimmen.

---

## 10. Proxmox: Windows VM vs. Linux

### Warum eine Windows-VM empfohlen wird

Anti-Gravity Hub nutzt **Browser-Automatisierung über CDP (Chrome DevTools Protocol)**.
Der API Bridge (`api_bridge.py`) verbindet sich per CDP mit einem laufenden Chrome-Browser.

| Aspekt                   | Windows VM          | Linux + Xvfb            |
|:-------------------------|:--------------------|:------------------------|
| Browser-Kompatibilität   | ✅ Nativ, stabil    | ⚠️ Headless, manchmal Probleme |
| GPU-Beschleunigung       | ✅ Möglich via GPU Passthrough | ❌ Nicht möglich       |
| Desktop für Debugging    | ✅ RDP verbinden     | ❌ Kein GUI             |
| Ressourcenverbrauch      | ❌ Höher (2+ GB RAM) | ✅ Niedriger            |
| Automatisierung          | ⚠️ Komplexer        | ✅ Einfacher            |

### Empfehlung

- **Entwicklung/Test:** Linux nur mit einer kompatiblen Anti-Gravity-Desktop-App
- **Produktion:** Windows VM mit echtem Chrome + RDP-Zugriff

### Linux mit virtuellem Display (experimentell)

Xvfb und ein beliebiger Chromium-Prozess sind **kein Ersatz** für die Anti-Gravity-
Desktop-App. Der Hub erwartet deren Profil, Anmeldung und CDP-Endpunkte. Verwende
Linux deshalb nur, wenn eine kompatible Desktop-App für dieselbe Distribution
vorliegt und sie als Benutzer `antigravity` mit `HOME=/home/antigravity` bereits
manuell verifiziert wurde. Erst danach darf ein virtuelles Display in einer
separaten, distributionsspezifischen Unit ergänzt werden. Für eine reproduzierbare
Produktivinstallation ist derzeit die Windows-Variante die unterstützte Wahl.

### Proxmox VM erstellen

1. **Neuen CT/VM erstellen** im Proxmox Web-UI
2. **Template:** Debian 12 Standard (für Linux) oder Windows 11 ISO
3. **Ressourcen zuweisen:**
   - CPU: 2 Kerne
   - RAM: 2048 MB (Linux) / 4096 MB (Windows)
   - Disk: 20 GB
4. **Netzwerk:** Bridge `vmbr0`, DHCP oder statische IP
5. **Nach Erstellung:** SSH aktivieren, Firewall konfigurieren

---

## 11. Troubleshooting

### Service startet nicht

```bash
# Detaillierte Fehlermeldung anzeigen
sudo systemctl status antigravity-bridge -l
sudo journalctl -u antigravity-bridge --no-pager -n 50
```

### Port bereits belegt

```bash
# Prüfen welcher Prozess den Port nutzt
sudo ss -tlnp | grep 8001
sudo lsof -i :8001
```

### Python-Modul fehlt

```bash
# Als antigravity-User prüfen
sudo -u antigravity /opt/antigravity-web/venv/bin/python3 -c "import aiohttp; print(aiohttp.__version__)"
```

### Nginx zeigt 502 Bad Gateway

```bash
# Service läuft?
curl -v http://127.0.0.1:8002/health

# Nginx Error Log prüfen
sudo tail -20 /var/log/nginx/antigravity-api-error.log
```

### config.json Berechtigungen

```bash
# Ensure the service user can read the configuration
sudo chown antigravity:antigravity /opt/antigravity-web/config.json
sudo chmod 640 /opt/antigravity-web/config.json
```

---

## Schnellstart (TL;DR)

Der Schnellstart setzt voraus, dass Benutzer, Verzeichnisse, `config.json`, Tokens,
Node.js und Python gemäß Abschnitten 1–2 vorbereitet wurden. Er ersetzt nicht die
TLS-, Backup- oder Restore-Schritte.

```bash
cd /opt/antigravity-web
sudo -u antigravity python3 -m venv venv
sudo -u antigravity ./venv/bin/python3 -m pip install --upgrade pip
sudo -u antigravity ./venv/bin/python3 -m pip install -r requirements.lock.txt
sudo -u antigravity bash -lc 'cd /opt/antigravity-web/frontend && npm ci && npm run build'

sudo systemd-analyze verify /opt/antigravity-web/deploy/antigravity-*.service
sudo install -o root -g root -m 0644 deploy/antigravity-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now antigravity-{bridge,proxy,sessions,healer,watchdog}

for endpoint in \
  8000/health 8001/health 8002/health 8007/health 8010/health; do
  curl --fail --show-error --silent "http://127.0.0.1:${endpoint}"
done
curl --fail --show-error --silent http://127.0.0.1:8010/status
```

Für öffentlichen HTTPS-Betrieb anschließend DNS setzen und Abschnitt 5 exakt in
zwei Phasen ausführen: zuerst HTTP/ACME-Bootstrap, danach die TLS-Konfiguration.
