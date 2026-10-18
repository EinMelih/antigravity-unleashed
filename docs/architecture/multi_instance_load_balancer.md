# Antigravity Multi-Instance Load Balancer & Headless Linux Deployment

Dieses Dokument beschreibt das Konzept, um Antigravity-Anfragen durch **Load Balancing über mehrere parallele App-Instanzen** zu beschleunigen, Dienste automatisch zu starten, automatische Updates zu blockieren und das System für Docker/Dokploy auf Linux vorzubereiten.

---

## 1. Skalierung & Load Balancing (Die Idee der 3 Fenster)

Da ein einzelnes Antigravity-Fenster (Single-Threaded Electron) bei parallelen UI-Zugriffen blockiert, starten wir **3 parallele Instanzen** mit getrennten Benutzerprofilen und Remote-Debugging-Ports. Ein zentraler **Load Balancer (Broker)** verteilt die Anfragen.

### Architektur des Load Balancers

```
                       +-----------------------+
                       |   Client (OpenClaw)   |
                       +-----------------------+
                                   |
                                   v  (POST /api/chat)
                       +-----------------------+
                       | Load Balancer (Port)  |
                       +-----------------------+
                        /          |          \
                       /           |           \
                      v            v            v
           [Instance 1]         [Instance 2]         [Instance 3]
           Port: 58323          Port: 58324          Port: 58325
           Profile: prof1       Profile: prof2       Profile: prof3
```

### Python-Implementierung des Brokers (`load_balancer.py`)

Dieses Skript verwaltet den Belegungsstatus der Instanzen und leitet Anfragen an das erste freie Fenster weiter:

```python
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request

# Ports der 3 Antigravity-Instanzen
INSTANCES = [
    {"port": 58323, "busy": False, "lock": threading.Lock()},
    {"port": 58324, "busy": False, "lock": threading.Lock()},
    {"port": 58325, "busy": False, "lock": threading.Lock()}
]

class LoadBalancerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/chat":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Finde freie Instanz
            instance = self.get_free_instance()
            if not instance:
                self.send_error(503, "All Antigravity instances are busy. Try again later.")
                return
                
            # Anfrage weiterleiten
            try:
                response = self.forward_request(instance, post_data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(response)
            except Exception as e:
                self.send_error(500, f"Error forwarding to port {instance['port']}: {str(e)}")
            finally:
                # Instanz wieder freigeben
                with instance["lock"]:
                    instance["busy"] = False

    def get_free_instance(self):
        # Einfaches Round-Robin / Freie Suche
        for inst in INSTANCES:
            with inst["lock"]:
                if not inst["busy"]:
                    inst["busy"] = True
                    return inst
        return None

    def forward_request(self, instance, data):
        url = f"http://localhost:{instance['port']}/api/chat"
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return response.read()

if __name__ == "__main__":
    server = HTTPServer(('0.0.0.0', 8080), LoadBalancerHandler)
    print("Load Balancer läuft auf Port 8080...")
    server.serve_forever()
```

---

## 2. Docker & Dokploy-Integration (Headless Linux)

Da Dokploy auf Linux (meist Debian/Ubuntu-Servern) läuft, besitzt der Server standardmäßig keine grafische Oberfläche (GUI). Electron-Apps benötigen jedoch einen Bildschirm (Display Server), um zu starten.

### A. Die Lösung: Xvfb (X Virtual Framebuffer)
Xvfb simuliert einen Monitor direkt im Arbeitsspeicher des Linux-Servers. Antigravity merkt nicht, dass es "headless" läuft.

### B. Das Docker-Setup (`Dockerfile`)
Dieses Dockerfile installiert alle Abhängigkeiten, konfiguriert die virtuellen Displays und startet die Dienste:

```dockerfile
FROM node:20-slim

# System-Abhängigkeiten für Electron, Xvfb und Playwright installieren
RUN apt-get update && apt-get install -y \
    xvfb \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libxtst6 \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libxss1 \
    libasound2 \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python-Vorbereitungen
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install playwright
RUN playwright install chromium

# Antigravity App-Dateien kopieren (v2.01 extrahierte Version)
COPY ./antigravity_v2.01 /app/antigravity

# Start-Skript kopieren
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
```

### C. Das Start-Skript (`entrypoint.sh`)
Dieses Skript wird im Docker-Container aufgerufen. Es startet den virtuellen Bildschirm (Xvfb) und anschließend die 3 Antigravity-Instanzen mit getrennten Ports und Profilordnern:

```bash
#!/bin/bash

# 1. Virtuellen Display-Server auf Display :99 starten
Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99

# Kurz warten, bis Xvfb bereit ist
sleep 2

# 2. Antigravity Instanzen starten
# Instanz 1
/app/antigravity/antigravity --remote-debugging-port=58323 --user-data-dir=/app/profiles/prof1 &
# Instanz 2
/app/antigravity/antigravity --remote-debugging-port=58324 --user-data-dir=/app/profiles/prof2 &
# Instanz 3
/app/antigravity/antigravity --remote-debugging-port=58325 --user-data-dir=/app/profiles/prof3 &

# 3. Load Balancer / API Server starten
python /app/load_balancer.py
```

---

## 3. Blockieren von Antigravity-Updates (v2.01 einfrieren)

Damit die App sich nicht selbstständig updatet und unsere Selektoren bricht, müssen wir die Update-Verbindung kappen:

### Methode 1: Windows `hosts`-Datei
Trage in `C:\Windows\System32\drivers\etc\hosts` folgende Zeilen ein:
```hosts
127.0.0.1   update.antigravity.ai
127.0.0.1   updates.antigravity.io
```
*(Dies leitet alle Update-Anfragen der App ins Leere um).*

### Methode 2: Docker / Linux DNS-Blocking
In der Docker-Konfiguration (`docker-compose.yml` auf Dokploy) können wir dem Container den Internet-Zugriff auf Update-Server verbieten, oder die DNS-Auflösung über ein lokales Netzwerk blockieren:
```yaml
services:
  antigravity-service:
    build: .
    extra_hosts:
      - "update.antigravity.ai:127.0.0.1"
      - "updates.antigravity.io:127.0.0.1"
```
*(Dadurch wird die Namensauflösung für den Container manipuliert, sodass der Updater keine Server erreicht).*
