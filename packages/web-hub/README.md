# 🚀 Antigravity Web v2.1

**Nutze dein Antigravity-Abo als vollständige OpenAI-kompatible API — ohne einen einzigen API-Key.**

---

## 💡 Die Vision

### Das Problem

Du zahlst für dein **Antigravity-Abo** und bekommst Zugang zu den besten AI-Modellen der Welt — Gemini 3.5 Flash, Claude Sonnet 4.6, Claude Opus 4.6, GPT-OSS 120B. Aber du kannst sie nur über die Desktop-App nutzen. Kein API-Zugang. Keine Möglichkeit, andere Tools wie **OpenClaw**, **Claude Code**, **Postman** oder eigene Scripts anzuschließen.

### Die Lösung

**Antigravity Web** verwandelt deine Desktop-App in eine vollwertige API-Plattform:

```
Dein Tool (OpenClaw, curl, eigene App)
          │
          │  ganz normale HTTP-Requests
          │  (OpenAI-kompatibles Format)
          ▼
   ┌──────────────────┐
   │  Antigravity Web  │ ◄── Diese Software hier
   └────────┬─────────┘
            │  steuert automatisch
            │  die Desktop-App
            ▼
   ┌──────────────────┐
   │  Antigravity App  │ ◄── Dein bestehendes Abo
   └──────────────────┘
            │
            ▼
      Gemini · Claude · GPT
      (alles über dein Abo)
```

**Du schickst einen normalen API-Request → Antigravity Web tippt die Nachricht ins Chat-Fenster → wartet auf die Antwort → gibt sie dir als sauberes JSON zurück.**

Das Beste: **Du brauchst keine API-Keys, keine Kreditkarte, keine externen Konten.** Nur dein Antigravity-Abo, das du eh schon hast.

### Was du damit machen kannst

- 🤖 **OpenClaw / Claude Code** mit Antigravity als Backend nutzen
- 🔄 **Zwischen Modellen wechseln** per API (`gemini-3.5-flash-medium`, `claude-sonnet-4.6`, etc.)
- 🌐 **Antigravity im Browser öffnen** (auch auf anderen Geräten im Netzwerk)
- 📊 **Automatisierte Workflows** — Batch-Anfragen, Scripte, CI/CD-Pipelines
- 🛡️ **Selbstheilendes System** — Watchdog, Auto-Healer, Telegram-Alerts
- ⚡ **SSE-Streaming** — Echtzeit-Antworten im OpenAI-Stream-Format
- 📈 **Token-Tracking** — Live-Widget zeigt Verbrauch direkt im Browser
- 🔒 **Security-Hardening** — Rate-Limiting, Multi-Key-Auth, Input-Sanitization
- 🐧 **Linux/Proxmox-Deployment** — Docker, systemd, Nginx-Reverse-Proxy

---

## 📦 Was ist in der Box?

### Die 5 Services

| Service | Port | Was macht er? |
|---------|------|---------------|
| **🌐 Proxy Server** | 8000 | Antigravity Desktop-App im Browser öffnen + Token-Widget |
| **🔌 API Bridge** | 8001 | OpenAI-kompatible REST-API (das Herzstück) |
| **🔀 Session Manager** | 8002 | Mehrere parallele Requests verwalten |
| **🩺 Auto-Healer** | 8007 | Automatische Fehlerbehebung |
| **🔍 Watchdog** | 8010 | Überwacht alles, sendet Telegram-Alerts |

### Wie sie zusammenarbeiten

```
┌──────────────────────────────────────────────────────────────────┐
│                      Deine Tools                                  │
│         OpenClaw · Claude Code · Postman · curl · Python          │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Session Manager  │  Port 8002
              │ (Eingangs-Proxy) │  ← Hier gehen alle Requests hin
              └────────┬────────┘
                       │ verteilt auf
                       ▼
              ┌─────────────────┐
              │   API Bridge     │  Port 8001
              │ (CDP-Automation) │  ← Steuert das Chat-UI
              └────────┬────────┘
                       │ Chrome DevTools Protocol
                       ▼
              ┌─────────────────┐
              │  Antigravity App │  ← Dein bestehendes Abo
              │   (Tauri/Rust)   │
              └─────────────────┘

         ┌──────────────────────────────────┐
         │        Überwachungs-Layer         │
         │                                   │
         │  🔍 Watchdog (8010)               │
         │  → Pollt alle Services alle 10s   │
         │  → Telegram-Alert bei Ausfall     │
         │                                   │
         │  🩺 Auto-Healer (8007)            │
         │  → Erkennt Probleme automatisch   │
         │  → 5 Stufen Selbstheilung         │
         │  → Bridge re-inject → Reconnect   │
         │    → New Chat → App-Restart       │
         └──────────────────────────────────┘

         ┌──────────────────────────────────┐
         │        Token-Usage-Widget         │
         │                                   │
         │  ⚡ Live-Widget (Port 8000)       │
         │  → Zeigt Token-Verbrauch live     │
         │  → Aufschlüsselung nach Modell   │
         │  → Pollt GET /api/stats           │
         └──────────────────────────────────┘
```

---

## ⚡ Schnellstart (5 Minuten)

### Voraussetzungen

- ✅ **Windows 10/11** oder **Linux** (Ubuntu 22+, Proxmox, etc.)
- ✅ **Python 3.11+** — [Download hier](https://www.python.org/downloads/)
- ✅ **Antigravity Desktop App** — installiert und eingeloggt
- ✅ **Antigravity-Abo** — aktiv (Free oder Premium)

### Schritt 1: Repository klonen

```powershell
# In einen Ordner deiner Wahl
cd C:\Users\DEIN_NAME\projects
git clone https://github.com/DEIN_REPO/antigravity-web.git
cd antigravity-web
```

Oder einfach die Dateien in einen Ordner kopieren. Hauptsache alle `.py`-Dateien sind im gleichen Verzeichnis.

### Schritt 2: Abhängigkeit installieren

```powershell
pip install aiohttp
```

Das ist die **einzige** externe Abhängigkeit. Alles andere ist Python-Standardbibliothek.

### Schritt 3: Antigravity App starten

Öffne die **Antigravity Desktop App** ganz normal und logge dich ein. Lass sie im Hintergrund laufen. Ein Chat-Fenster muss offen sein.

### Schritt 4: Antigravity Web starten

```powershell
# Windows — Alles auf einmal starten:
start.bat

# Linux / Proxmox — Alles auf einmal starten:
./start.sh

# ODER nur die API Bridge (Minimum):
python api_bridge.py
```

### Schritt 5: Testen!

```powershell
# Test: Ist alles verbunden?
curl http://127.0.0.1:8001/health

# Test: Eine Frage stellen
curl -X POST http://127.0.0.1:8001/api/chat ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"Was ist 2+2?\"}"
```

Wenn du eine Antwort bekommst — **läuft!** 🎉

---

## 🔧 Konfiguration

Alle Einstellungen stehen in **`config.json`** (im gleichen Ordner).

### Vollständiges Konfigurationsbeispiel (v2.1)

```json
{
  "port": 8001,
  "auth_token": "ag-local-token",
  "debug_mode": true,
  "max_message_length": 100000,
  "telegram_token": "",
  "telegram_chat_id": "",
  "rate_limit": {
    "enabled": false,
    "max_requests_per_minute": 10,
    "whitelist_ips": ["127.0.0.1", "::1"]
  },
  "api_keys": {
    "sk-mein-key-12345": {
      "name": "OpenClaw",
      "rpm": 20
    },
    "sk-team-key-67890": {
      "name": "Team-Account",
      "rpm": 5
    }
  },
  "watchdog": {
    "check_interval_seconds": 10,
    "timeout_ms": 3000,
    "alert_cooldown_seconds": 300,
    "services": [
      {"name": "api_bridge", "url": "http://127.0.0.1:8001/health"},
      {"name": "proxy", "url": "http://127.0.0.1:8000/"},
      {"name": "session_manager", "url": "http://127.0.0.1:8002/health"},
      {"name": "auto_healer", "url": "http://127.0.0.1:8007/health"}
    ]
  },
  "session_manager": {
    "sessions": [
      {"name": "main", "url": "http://127.0.0.1:8001"}
    ],
    "health_check_interval_seconds": 30,
    "session_timeout_seconds": 120
  },
  "auto_healer": {
    "check_interval_seconds": 15,
    "max_healing_cycles": 3,
    "api_bridge_url": "http://127.0.0.1:8001"
  }
}
```

### Was du anpassen kannst

| Einstellung | Standard | Erklärung |
|-------------|----------|-----------|
| `auth_token` | `ag-local-token` | Passwort für die API. Ändern, wenn du die API im Netzwerk erreichbar machst! |
| `debug_mode` | `true` | Detaillierte Fehlermeldungen. Im Produktionsbetrieb auf `false` setzen! |
| `max_message_length` | `100000` | Maximale Zeichenlänge pro Nachricht (Schutz vor Missbrauch) |
| `rate_limit.enabled` | `false` | Rate-Limiting aktivieren (empfohlen bei Netzwerk-Zugriff) |
| `rate_limit.max_requests_per_minute` | `10` | Globales Limit — wird von per-Key `rpm` überschrieben |
| `api_keys` | `{}` | Multi-Key-Auth (siehe [Sicherheit](#-sicherheit)) |
| `telegram_token` | leer | Bot-Token von [@BotFather](https://t.me/BotFather) für Benachrichtigungen |
| `telegram_chat_id` | leer | Deine Chat-ID für Telegram-Alerts |

### Telegram-Alerts einrichten (optional)

1. Öffne Telegram → Suche **@BotFather** → Sende `/newbot` → Folge den Anweisungen
2. Du bekommst einen **Token** (z.B. `7123456789:AAH...`)
3. Schreibe deinem Bot eine Nachricht
4. Öffne `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates` im Browser
5. Finde deine **Chat-ID** im JSON
6. Trage beides in `config.json` ein:
   ```json
   "telegram_token": "7123456789:AAHxxx...",
   "telegram_chat_id": "123456789"
   ```
7. Neustart → Du bekommst jetzt Alerts wenn Services ausfallen! 🔔

---

## 📡 API-Referenz

### Authentifizierung

Alle Requests (außer `/health`) brauchen den Auth-Token:

```
Authorization: Bearer ag-local-token
```

Bei aktivierter Multi-Key-Auth alternativ:

```
Authorization: Bearer sk-mein-key-12345
X-Api-Key: sk-mein-key-12345
```

### Request-ID-Tracking

Jede API-Antwort enthält einen **`X-Request-Id`** Header zur Nachverfolgung:

```
X-Request-Id: a1b2c3d4
```

Diese ID taucht auch in den Server-Logs auf, z.B.:
```
[CHAT] [a1b2c3d4] OpenAI | 3456ms | 1200 chars | ~300 tokens
```

So kannst du jeden einzelnen Request über alle Komponenten hinweg verfolgen — von der Anfrage bis zur CDP-Interaktion.

### Die wichtigsten Endpoints

#### 💬 Chat (OpenAI-Format)

```powershell
curl -X POST http://127.0.0.1:8001/v1/chat/completions ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"antigravity\", \"messages\": [{\"role\": \"user\", \"content\": \"Hallo!\"}]}"
```

**Response:**
```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "model": "antigravity",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Hallo! Wie kann ich dir helfen?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 2,
    "completion_tokens": 8,
    "total_tokens": 10
  }
}
```

#### ⚡ SSE-Streaming

Setze `"stream": true` im Request, um Antworten in Echtzeit als **Server-Sent Events (SSE)** zu erhalten — genauso wie bei der OpenAI-API:

```powershell
curl -N -X POST http://127.0.0.1:8001/v1/chat/completions ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"antigravity\", \"stream\": true, \"messages\": [{\"role\": \"user\", \"content\": \"Hallo!\"}]}"
```

**SSE Event-Format:**

Jedes Event enthält ein `data:`-Feld mit einem JSON-Chunk. Zuerst kommt die Rolle, dann die Content-Deltas, am Ende `[DONE]`:

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hallo"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"! Wie"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

**JavaScript EventSource:**

```javascript
const response = await fetch("http://127.0.0.1:8001/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ag-local-token",
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    model: "antigravity",
    stream: true,
    messages: [{ role: "user", content: "Erkläre Quantenphysik." }]
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const text = decoder.decode(value);
  for (const line of text.split("\n")) {
    if (line.startsWith("data: ") && line !== "data: [DONE]") {
      const chunk = JSON.parse(line.slice(6));
      const content = chunk.choices[0]?.delta?.content;
      if (content) process.stdout.write(content);
    }
  }
}
```

**Python Streaming:**

```python
import requests

response = requests.post(
    "http://127.0.0.1:8001/v1/chat/completions",
    headers={"Authorization": "Bearer ag-local-token"},
    json={
        "model": "antigravity",
        "stream": True,
        "messages": [{"role": "user", "content": "Erkläre Quantenphysik."}]
    },
    stream=True
)

for line in response.iter_lines():
    if line:
        text = line.decode("utf-8")
        if text.startswith("data: ") and text != "data: [DONE]":
            import json
            chunk = json.loads(text[6:])
            content = chunk["choices"][0].get("delta", {}).get("content", "")
            if content:
                print(content, end="", flush=True)
```

**Wie funktioniert das Streaming?**

Die API Bridge pollt das Antigravity-Chat-DOM alle 300ms und sendet neue Zeichen als Deltas. Wenn der Antworttext 3 Sekunden lang stabil bleibt, gilt die Antwort als fertig (`finish_reason: "stop"`).

#### 💬 Chat (Einfaches Format)

```powershell
curl -X POST http://127.0.0.1:8001/api/chat ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"Was ist die Hauptstadt von Frankreich?\"}"
```

**Response:**
```json
{
  "response": "Die Hauptstadt von Frankreich ist Paris.",
  "duration_ms": 3456
}
```

#### 🔄 Modell wechseln

Schicke einfach eine andere `model`-ID im Request:

```powershell
curl -X POST http://127.0.0.1:8001/v1/chat/completions ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"claude-sonnet-4.6\", \"messages\": [{\"role\": \"user\", \"content\": \"Hi\"}]}"
```

Die API Bridge klickt automatisch auf den Modell-Selector im Antigravity-UI und wählt das richtige Modell aus! 🪄

#### 📋 Alle Endpoints auf einen Blick

| Method | Endpoint | Port | Beschreibung |
|--------|----------|------|-------------|
| `POST` | `/v1/chat/completions` | 8001 | OpenAI-kompatibel (Normal + Streaming) |
| `POST` | `/api/chat` | 8001 | Einfaches JSON-Format |
| `GET` | `/v1/models` | 8001 | Verfügbare Modelle |
| `GET` | `/api/stats` | 8001 | Token-Verbrauch (für Live-Widget) |
| `GET` | `/health` | 8001 | API Bridge Status |
| `GET` | `/health/cdp` | 8001 | CDP-Diagnose (detailliert) |
| `GET` | `/api/chat/logs` | 8001 | Request-Logs |
| `DELETE` | `/api/chat/logs` | 8001 | Logs löschen |
| `GET` | `/sessions` | 8002 | Session-Pool Übersicht |
| `POST` | `/v1/chat/completions` | 8002 | Proxy (verteilt Last) |
| `GET` | `/status` | 8007 | Auto-Healer Status |
| `POST` | `/heal` | 8007 | Manuell heilen |
| `GET` | `/status` | 8010 | Alle Services Status |
| `GET` | `/uptime` | 8010 | Uptime-Statistiken |

---

## 📈 Token-Usage-Widget

Der **Proxy Server (Port 8000)** injiziert ein **Live-Token-Widget** in die untere linke Ecke des Antigravity-Browsers:

```
┌─────────────────────────────────────────────────┐
│                                                   │
│            Antigravity Chat (Browser)             │
│                                                   │
│                                                   │
│                                                   │
│                                                   │
│  ┌──────────────────┐                             │
│  │ ⚡ 1.234 tokens  │  ← Klick für Details       │
│  └──────────────────┘                             │
└─────────────────────────────────────────────────┘
```

### Was zeigt es?

- **Badge** (unten links): Gesamtzahl der geschätzten Tokens
- **Panel** (nach Klick): Aufschlüsselung nach Modell — Requests und Tokens pro Modell

### `GET /api/stats` Endpoint

Das Widget fragt regelmäßig den Stats-Endpoint ab:

```powershell
curl http://127.0.0.1:8001/api/stats ^
  -H "Authorization: Bearer ag-local-token"
```

**Response:**
```json
{
  "session": {
    "total_requests": 42,
    "total_prompt_tokens": 5200,
    "total_completion_tokens": 18400,
    "total_tokens": 23600,
    "start_time": "2026-06-02T12:00:00+00:00",
    "requests_by_model": {
      "gemini-3.5-flash-medium": {"requests": 30, "tokens": 15000},
      "claude-sonnet-4.6": {"requests": 12, "tokens": 8600}
    }
  },
  "uptime_seconds": 3600
}
```

### Wie funktioniert die Token-Schätzung?

Da Antigravity keine Token-Counts über die DOM-Schnittstelle bereitstellt, wird eine **Heuristik** verwendet:

```
~1 Token ≈ 4 Zeichen (Durchschnitt über Gemini/Claude/GPT)
```

- `prompt_tokens = max(1, len(nachricht) // 4)`
- `completion_tokens = max(1, len(antwort) // 4)`

Die Werte sind Schätzwerte — gut genug für Monitoring, nicht für exakte Abrechnung.

---

## 🔒 Sicherheit

### Rate-Limiting

Aktiviere Rate-Limiting in `config.json`, um Missbrauch zu verhindern:

```json
"rate_limit": {
  "enabled": true,
  "max_requests_per_minute": 10,
  "whitelist_ips": ["127.0.0.1", "::1"]
}
```

- **Whitelist-IPs** werden nie gedrosselt (Standard: localhost)
- **Per-Key `rpm`** überschreibt das globale Limit (bei Multi-Key-Auth)
- Bei Überschreitung: HTTP `429 Too Many Requests`

**Rate-Limit Response-Headers:**

| Header | Beschreibung |
|--------|-------------|
| `X-RateLimit-Limit` | Max. Requests pro Minute |
| `X-RateLimit-Remaining` | Verbleibende Requests |
| `Retry-After` | Sekunden bis zum nächsten erlaubten Request |

### Multi-Key-Auth

Statt eines einzelnen `auth_token` kannst du mehrere API-Keys vergeben — jeweils mit eigenem Namen und individuellem Rate-Limit:

```json
"api_keys": {
  "sk-openclaw-prod-abc123": {
    "name": "OpenClaw Production",
    "rpm": 20
  },
  "sk-team-dev-xyz789": {
    "name": "Entwicklungs-Key",
    "rpm": 5
  }
}
```

- Wenn `api_keys` gesetzt ist, wird `auth_token` ignoriert
- Keys können über `Authorization: Bearer <key>` oder `X-Api-Key: <key>` gesendet werden
- Jeder Key kann sein eigenes `rpm` (Requests pro Minute) haben

### Input-Sanitization

Alle eingehenden Nachrichten werden **automatisch** bereinigt:

- **Null-Bytes** (`\x00`) werden entfernt
- **Leere Nachrichten** werden mit `400 Bad Request` abgelehnt
- **Zu lange Nachrichten** (über `max_message_length`, Standard 100.000 Zeichen) → `400`
- **Typ-Prüfung**: Nur Strings erlaubt

### Security-Headers

Jede API-Antwort enthält automatisch diese Sicherheits-Header:

| Header | Wert | Zweck |
|--------|------|-------|
| `X-Content-Type-Options` | `nosniff` | MIME-Type-Sniffing verhindern |
| `X-Frame-Options` | `DENY` | Clickjacking-Schutz |
| `Referrer-Policy` | `no-referrer` | Keine Referrer-Leaks |
| `Cache-Control` | `no-store` | Keine API-Responses im Cache |

### Debug- vs. Produktionsmodus

| Einstellung | `debug_mode: true` | `debug_mode: false` |
|-------------|---------------------|----------------------|
| Fehlermeldungen | Detailliert (mit Stacktrace) | Generisch (keine internen Details) |
| CDP-Debug-Info | Sichtbar | Versteckt |
| Empfohlen für | Entwicklung, Debugging | Netzwerk-Zugriff, Produktion |

**⚠️ Wichtig:** Im Produktionsbetrieb immer `"debug_mode": false` setzen! Detaillierte Fehlermeldungen können interne Systeminformationen preisgeben.

---

## 🔄 Verfügbare Modelle

Diese Modelle kannst du per API auswählen (die Bridge wechselt automatisch im UI):

| API Model-ID | Modell im UI |
|--------------|-------------|
| `antigravity` | Standard (was gerade ausgewählt ist) |
| `gemini-3.5-flash-medium` | Gemini 3.5 Flash (Medium) |
| `gemini-3.5-flash-high` | Gemini 3.5 Flash (High) |
| `gemini-3.5-flash-low` | Gemini 3.5 Flash (Low) |
| `gemini-3.1-pro-high` | Gemini 3.1 Pro (High) |
| `gemini-3.1-pro-low` | Gemini 3.1 Pro (Low) |
| `claude-sonnet-4.6` | Claude Sonnet 4.6 (Thinking) |
| `claude-opus-4.6` | Claude Opus 4.6 (Thinking) |
| `gpt-oss-120b` | GPT-OSS 120B (Medium) |

---

## 🔌 Integrationen

### OpenClaw

Füge in `~/.openclaw/openclaw.json` hinzu:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "antigravity": {
        "baseUrl": "http://127.0.0.1:8001/v1",
        "apiKey": "ag-local-token",
        "api": "openai-completions",
        "models": [{
          "id": "antigravity",
          "name": "Antigravity (Frontend)",
          "contextWindow": 1048576
        }]
      }
    }
  }
}
```

Fertig! In OpenClaw einfach "antigravity" als Modell auswählen.

### Claude Code

```powershell
set ANTHROPIC_BASE_URL=http://127.0.0.1:8001/v1
set ANTHROPIC_API_KEY=ag-local-token
claude
```

### Python

```python
import requests

response = requests.post(
    "http://127.0.0.1:8001/v1/chat/completions",
    headers={"Authorization": "Bearer ag-local-token"},
    json={
        "model": "gemini-3.5-flash-medium",
        "messages": [{"role": "user", "content": "Erkläre Quantenphysik in 3 Sätzen."}]
    }
)

print(response.json()["choices"][0]["message"]["content"])
```

### JavaScript / Node.js

```javascript
const response = await fetch("http://127.0.0.1:8001/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ag-local-token",
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    model: "antigravity",
    messages: [{ role: "user", content: "Hallo!" }]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8001/v1",
    api_key="ag-local-token"
)

chat = client.chat.completions.create(
    model="antigravity",
    messages=[{"role": "user", "content": "Was ist 2+2?"}]
)

print(chat.choices[0].message.content)
```

---

## 🌐 Proxy Server (Antigravity im Browser)

Der Proxy Server (Port 8000) macht die Antigravity Desktop-App im Browser verfügbar:

```
http://127.0.0.1:8000
```

### Features
- **Tauri-Shim**: Simuliert die native Tauri-Schnittstelle im Browser
- **File Browser**: Web-basierter Ordner-Picker statt nativer Dialog
- **Netzwerk-Zugriff**: Von anderen Geräten im LAN erreichbar
- **Token-Widget**: Live-Token-Verbrauchsanzeige (unten links)

### Wofür?
- Antigravity auf Tablet/Handy nutzen (gleiches Netzwerk)
- Auf einem Server ohne GUI laufen lassen
- Debugging und Entwicklung
- Token-Verbrauch im Auge behalten

---

## 🛡️ Überwachung & Selbstheilung

### Watchdog Monitor (Port 8010)

Überwacht **alle** Services und meldet Probleme:

```powershell
# Status aller Services
curl http://127.0.0.1:8010/status

# Uptime-Statistiken (1h, 24h, 7d)
curl http://127.0.0.1:8010/uptime

# Test-Alert senden
curl -X POST http://127.0.0.1:8010/alert/test
```

**Was er tut:**
- Prüft alle 10 Sekunden ob jeder Service erreichbar ist
- Eskalation: 1 Fehler → Log, 3 → Warnung, 5 → Kritisch, 10 → Neustart-Hinweis
- Sendet Telegram-Nachrichten bei Ausfällen und Erholungen
- Speichert Uptime-Daten in SQLite für Statistiken

### Auto-Healer (Port 8007)

Repariert Probleme **automatisch** in 5 Eskalationsstufen:

```
Fehler erkannt
    ↓
Level 1: JavaScript Bridge neu injizieren
    ↓ (klappt nicht?)
Level 2: CDP WebSocket neu verbinden
    ↓ (klappt nicht?)
Level 3: Neuen Chat starten
    ↓ (klappt nicht?)
Level 4: Prüfen ob Antigravity-App noch läuft
    ↓ (klappt nicht?)
Level 5: Telegram-Alert an dich senden
```

```powershell
# Status ansehen
curl http://127.0.0.1:8007/status

# Manuell einen Healing-Cycle starten
curl -X POST http://127.0.0.1:8007/heal

# Healing-Historie ansehen
curl http://127.0.0.1:8007/history
```

### Session Manager (Port 8002)

Verwaltet parallele Requests über einen **Session-Pool**:

```powershell
# Alle Sessions ansehen
curl http://127.0.0.1:8002/sessions

# Chat über den Session Manager (verteilt Last automatisch)
curl -X POST http://127.0.0.1:8002/v1/chat/completions ^
  -H "Authorization: Bearer ag-local-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"antigravity\", \"messages\": [{\"role\": \"user\", \"content\": \"Hallo!\"}]}"
```

**Wofür:** Wenn du mehrere Antigravity-Instanzen laufen hast, verteilt der Session Manager die Requests automatisch auf die am wenigsten belastete Instanz.

---

## 🐧 Linux / Proxmox Deployment

### Schnellstart mit `start.sh`

```bash
# Ausführbar machen
chmod +x start.sh

# Alles starten
./start.sh

# Nur API Bridge
./start.sh api

# Nur Proxy
./start.sh proxy

# Alle Agents (Watchdog + Auto-Healer)
./start.sh agents
```

> 📖 **Vollständige Anleitung:** Siehe [`deploy/DEPLOY.md`](deploy/DEPLOY.md) für Schritt-für-Schritt-Anleitung mit Nginx, SSL, Firewall und mehr.

### Docker Quickstart

```bash
# Mit Docker Compose (empfohlen)
docker-compose up -d

# Logs ansehen
docker-compose logs -f api-bridge

# Stoppen
docker-compose down
```

Die `docker-compose.yml` startet alle 5 Services mit den richtigen Port-Mappings und Volume-Mounts.

### Systemd Setup (1-Liner)

```bash
# Alle Service-Dateien installieren
sudo cp deploy/antigravity-*.service /etc/systemd/system/ && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable --now antigravity-bridge antigravity-proxy antigravity-sessions antigravity-watchdog antigravity-healer
```

Einzelne Services verwalten:

```bash
sudo systemctl status antigravity-bridge
sudo systemctl restart antigravity-proxy
sudo journalctl -u antigravity-bridge -f
```

---

## 🧪 Test Suite

Die umfangreiche Test Suite (`test_suite.py`, ~48KB) deckt Unit- und Integrationstests ab:

### Unit-Tests (offline, ohne laufende Services)

```bash
python test_suite.py --unit
```

Testet:
- Token-Schätzung (Leerstring, kurz, lang, Unicode)
- Rate-Limiter (Limit, Reset, Whitelist, Multi-Client)
- Config-Loading (Defaults, Datei, Validierung, ungültiges JSON)
- Input-Validierung (zu lang, leere Nachrichten, Typ-Prüfung)

### Integrationstests (alle Services müssen laufen)

```bash
python test_suite.py --live
```

Testet:
- Health-Checks aller Services
- Chat-Requests (einfach + OpenAI-Format)
- Streaming (SSE)
- Modellwechsel
- Fehlerszenarien (ungültige Auth, fehlende Felder)
- `/api/stats` Endpoint
- Request-ID-Tracking

---

## 📁 Dateien im Projekt

```
antigravity-web/
├── api_bridge.py              ← Das Herzstück: OpenAI-API via CDP
├── proxy_server.py            ← Antigravity im Browser + Token-Widget
├── session_manager.py         ← Parallele Requests (Port 8002)
├── auto_healer.py             ← Automatische Selbstheilung (Port 8007)
├── watchdog_monitor.py        ← Service-Überwachung (Port 8010)
├── config.json                ← Alle Einstellungen (inkl. Security)
├── start.bat                  ← Windows: Startet alles (oder Teile)
├── start.sh                   ← Linux: Startet alles (oder Teile)
├── test_suite.py              ← Umfangreiche Test Suite (~48KB)
├── test_api.py                ← Automatische API-Tests
├── test_chat_live.py          ← Live Chat-Test
├── requirements.txt           ← Nur: aiohttp>=3.9
├── openclaw_config_example.json5  ← OpenClaw-Integrations-Beispiel
├── Dockerfile                 ← Docker-Build für die API Bridge
├── docker-compose.yml         ← Docker Compose: Alle 5 Services
├── .dockerignore              ← Ausschlüsse für Docker-Build
├── deploy/                    ← Deployment-Konfigurationen
│   ├── DEPLOY.md              ← Vollständige Deployment-Anleitung
│   ├── nginx-antigravity.conf ← Nginx Reverse-Proxy-Config
│   ├── antigravity-bridge.service    ← systemd Service
│   ├── antigravity-proxy.service     ← systemd Service
│   ├── antigravity-sessions.service  ← systemd Service
│   ├── antigravity-watchdog.service  ← systemd Service
│   └── antigravity-healer.service    ← systemd Service
└── logs/
    ├── api_requests.jsonl     ← Request-Logs (auto-erstellt)
    └── uptime.db              ← Uptime-Daten (auto-erstellt)
```

---

## 🚀 Start-Modi

### Windows (`start.bat`)

```powershell
# Alles starten (5 Services)
start.bat

# Nur Proxy + API Bridge (Minimum)
start.bat all

# Nur die Agenten (wenn Bridge + Proxy schon laufen)
start.bat agents

# Nur den Proxy
start.bat proxy

# Nur die API Bridge
start.bat api

# Einzeln starten:
python api_bridge.py          # Port 8001
python proxy_server.py        # Port 8000
python session_manager.py     # Port 8002
python auto_healer.py         # Port 8007
python watchdog_monitor.py    # Port 8010
```

### Linux (`start.sh`)

```bash
# Alles starten (5 Services)
./start.sh

# Nur API Bridge
./start.sh api

# Nur Proxy
./start.sh proxy

# Nur Agents (Watchdog + Auto-Healer)
./start.sh agents
```

---

## ❓ Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| `CDP not connected` | Antigravity Desktop App starten und einloggen! |
| `Chat input not found` | Ein Chat-Fenster muss in Antigravity offen sein. Prüfe mit `GET /health/cdp` |
| `Response timeout` | Chat-UI muss sichtbar/aktiv sein (nicht minimiert) |
| `401 Unauthorized` | `Authorization: Bearer ag-local-token` Header prüfen |
| `429 Too Many Requests` | Rate-Limit erreicht — `Retry-After` Header beachten |
| `Connection refused` auf 8001 | `python api_bridge.py` starten |
| Leere Antwort | Antigravity muss eingeloggt sein + Chat offen |
| Modell wechselt nicht | Prüfe ob die Model-ID in der Tabelle oben steht |
| Watchdog meldet `degraded` | Service antwortet langsam (>3s) — meist temporär |
| Auto-Healer macht Level 5 | Antigravity App crasht regelmäßig — App neu installieren? |
| Streaming bricht ab | `timeout`-Parameter im Request erhöhen (max 600s) |

### Debug-Befehle

```powershell
# Detaillierte CDP-Diagnose
curl http://127.0.0.1:8001/health/cdp

# Watchdog: Welche Services sind down?
curl http://127.0.0.1:8010/status

# Auto-Healer: Was wurde versucht?
curl http://127.0.0.1:8007/history

# API Bridge Logs
curl http://127.0.0.1:8001/api/chat/logs?limit=5

# Token-Verbrauch ansehen
curl http://127.0.0.1:8001/api/stats -H "Authorization: Bearer ag-local-token"

# Request nachverfolgen (Suche nach Request-ID in den Logs)
# Die X-Request-Id steht in jeder API-Antwort
```

---

## 🏗️ Wie funktioniert es technisch?

### API Bridge (Das Herzstück)

Die API Bridge verbindet sich über das **Chrome DevTools Protocol (CDP)** direkt zum Tauri-Webview der Antigravity App:

1. **Port scannen** — Sucht den DevTools-Port des Webviews (49152-65535)
2. **WebSocket verbinden** — CDP WebSocket zum Webview aufbauen
3. **JavaScript injizieren** — Bridge-Helfer wird in die Seite eingefügt
4. **Chat-Input finden** — Sucht das Eingabefeld (Lexical Editor, role=combobox)
5. **Text eingeben** — Lexical-kompatibel via `InputEvent('beforeinput')`
6. **Senden** — Klickt den Send-Button (aria-label="Send message")
7. **Warten** — Pollt DOM bis Antwort stabil (3s kein Update)
8. **Extrahieren** — Liest Antworttext, bereinigt Timestamps und UI-Junk
9. **Zurückgeben** — Sauberes OpenAI-kompatibles JSON

### Streaming-Pipeline

Bei `stream: true` läuft ein modifizierter Ablauf:

1. **Nachricht senden** — `prepareAndSend()` sendet ohne auf Antwort zu warten
2. **DOM-Polling** — Alle 300ms wird der aktuelle Antworttext gelesen
3. **Delta berechnen** — Neue Zeichen seit dem letzten Poll werden als Chunk gesendet
4. **Stabilitätsprüfung** — Nach 3s ohne Änderung → `finish_reason: "stop"`
5. **SSE-Events** — Jeder Delta wird als `data: {...}\n\n` Event gesendet
6. **Abschluss** — `data: [DONE]\n\n` markiert das Ende

### Proxy Server

Reverse-Proxy mit **Tauri-Shim-Injection**:
- Fängt HTTPS-Requests ab und leitet sie an das lokale Antigravity-Backend weiter
- Injiziert JavaScript das `nativeStorage`, `nativeFileDialog` und `nativeNotifications` simuliert
- Injiziert das **Token-Usage-Widget** (pollt `/api/stats` und zeigt Live-Verbrauch)
- Ermöglicht Antigravity im normalen Browser ohne Tauri-Runtime

---

## 📜 Lizenz

Privates Projekt. Nicht zur Weiterverbreitung bestimmt.

---

## 🙏 Credits

Gebaut mit:
- [aiohttp](https://docs.aiohttp.org/) — Async HTTP Server/Client
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) — Browser-Automation
- [Antigravity](https://antigravity.dev/) — AI Desktop App
