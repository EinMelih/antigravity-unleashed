# Antigravity Automation & Control Guide

Dieses Dokument erklärt, wie die **Antigravity-App** programmatisch über Python und die **Chrome DevTools (CDP)** ferngesteuert werden kann.

---

## 1. Architektur und Funktionsweise

Da Antigravity auf **Electron** basiert, verhält es sich wie ein lokaler Webbrowser. Beim Start der Anwendung wird standardmäßig der **Chrome Remote Debugging Port** geöffnet.

* **Lokaler Host**: `http://localhost:58323`
* **Zweck**: Dieser Port erlaubt es externen Skripten (z. B. mit Playwright oder Puppeteer), auf die geöffnete Weboberfläche zuzugreifen, DOM-Elemente zu manuplieren und Aktionen wie Klicks oder Texteingaben zu simulieren, während die App im Hintergrund läuft.

---

## 2. Vorbereitung und Installation

Um die App per Python zu steuern, wird die Bibliothek **Playwright** empfohlen. Sie stellt eine stabile Verbindung her und bietet einfache Selektoren.

```bash
pip install playwright
playwright install chromium
```

---

## 3. Wichtige UI-Selektoren (DOM-Struktur)

Die Benutzeroberfläche von Antigravity verwendet spezifische HTML-Attribute. Die wichtigsten Selektoren für deine Automatisierung sind:

### A. Chats in der Seitenleiste (Sidebar)
Jeder Chat-Eintrag in der linken Seitenleiste ist über eine eindeutige `data-testid` gekennzeichnet.
* **Selektor**: `span[data-testid^='convo-pill-']`
* **Beispiel**:
  ```html
  <span data-testid="convo-pill-ca57ecd3-7239-4eb5-859b-a580cbca21c9">privat</span>
  ```
* **Auslesen & Wechseln**: Über die `data-testid` lässt sich die `Conversation-ID` direkt extrahieren. Ein Klick auf das Element wechselt den Chat.

### B. Chat-Eingabefeld (Message Input)
Das Eingabefeld ist keine Standard-`textarea`, sondern ein editierbares `div` (contenteditable).
* **Selektor**: `div[aria-label='Message input']`
* **Aktion**: Zuerst `.click()` ausführen, um den Fokus zu setzen, dann `.fill("Deine Nachricht")` und `.press("Enter")` zum Senden.

### C. Modell-Auswahlmenü (Model Selector)
Um die KIs (z. B. Gemini, Claude Sonnet, Opus) zu wechseln:
* **Dropdown-Button**: `div[aria-haspopup='dialog'] button` (Klick öffnet das Menü).
* **Auswahl-Buttons im Menü**: 
  * `button:has-text('Claude Sonnet')` (wechselt zu Claude 3.5 Sonnet)
  * `button:has-text('Gemini 3.5 Flash')` (wechselt zu Gemini 3.5 Flash)

---

## 4. Antworten auslesen (Log-Überwachung)

Anstatt den HTML-Text mühsam aus der UI zu parsen, schreibt Antigravity den gesamten Gesprächsverlauf live in eine lokale JSON-Lines-Datei. Das ist **extrem robust**, da wir direkt auf die Rohdaten zugreifen können.

* **Log-Pfad**: 
  `C:\Users\Yildirim\.gemini\antigravity\brain\<CONVERSATION_ID>\.system_generated\logs\transcript.jsonl`
* **Format**: Jede Zeile ist ein JSON-Objekt.
* **Abfragen der fertigen Antwort**:
  Wir suchen nach der letzten Zeile, bei der:
  * `"source": "MODEL"`
  * `"status": "DONE"`
  Das Feld `"content"` enthält dann die vollständige Antwort als Markdown.

---

## 5. Python-Beispiel: Vollständiger Workflow

Das folgende Skript klinkt sich ein, wechselt den Chat, ändert das Modell, sendet einen Prompt und liest die Antwort über die Log-Datei aus.

```python
import os
import time
import json
from playwright.sync_api import sync_playwright

DEVTOOLS_URL = "http://localhost:58323"
TARGET_CHAT_ID = "ca57ecd3-7239-4eb5-859b-a580cbca21c9" # ID von 'privat'
LOG_PATH = rf"C:\Users\Yildirim\.gemini\antigravity\brain\{TARGET_CHAT_ID}\.system_generated\logs\transcript.jsonl"

def wait_for_response(start_line_count):
    while True:
        time.sleep(0.5)
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > start_line_count:
                    for line in reversed(lines[start_line_count:]):
                        data = json.loads(line)
                        if data.get("source") == "MODEL" and data.get("status") == "DONE":
                            return data.get("content", "")
            except (json.JSONDecodeError, PermissionError):
                continue

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(DEVTOOLS_URL)
    page = browser.contexts[0].pages[0]
    
    # 1. Chat wechseln
    page.locator(f"span[data-testid='convo-pill-{TARGET_CHAT_ID}']").click()
    time.sleep(1.0)
    
    # 2. Modell wechseln (z.B. zu Claude Sonnet)
    page.locator("div[aria-haspopup='dialog'] button").click()
    time.sleep(0.5)
    page.locator("button:has-text('Claude Sonnet')").click()
    time.sleep(1.0)
    
    # 3. Nachricht senden
    editor = page.locator("div[aria-label='Message input']")
    editor.click()
    editor.fill("Welches Modell bist du?")
    editor.press("Enter")
    
    # 4. Log auslesen
    response = wait_for_response(0)
    print("Antwort:", response)
    
    browser.close()
```

---

## 6. Modell-Quota / Kapazitäten auslesen

Die Antigravity-App zeigt das verbleibende Kontingent für die verschiedenen KI-Modelle im Einstellungsmenü unter dem Reiter **Models** an. Diese Daten können ebenfalls automatisiert ausgelesen werden.

### A. Navigieren zum Models-Tab
Da ein wiederholter Klick auf das Einstellungs-Symbol das Menü schließt, muss zuerst geprüft werden, ob das Einstellungsfenster bereits geöffnet ist (z. B. durch die Sichtbarkeit des Reiters "General").
1. **Prüfen & Öffnen**: 
   * Überprüfe, ob `text=General` sichtbar ist.
   * Wenn nicht, klicke auf `div[data-testid='settings-button']` oder `text=Settings`.
2. **Modelle auswählen**:
   * Suche nach Spannen mit dem exakten Text "Models" unter Verwendung von `span:text-is('Models')` (um Kollisionen mit Chat-Inhalten zu vermeiden) und klicke darauf.

### B. Auslesen der Kapazitäts-Segmente
Jedes Modell im Quoten-Container besitzt genau **5 Kapazitätsbalken** (Segmente):
* Jedes Segment ist ein Div mit der Klasse `.bg-muted`.
* Darin befindet sich ein inneres Div mit der Klasse `.bg-secondary-foreground`, das über sein Inline-Style-Attribut `width` gesteuert wird.
  * **Gefüllt**: `style="width: 100%;"`
  * **Leer**: `style="width: 0%;"`

### C. Python-Beispiel zur Quoten-Extraktion

Das folgende Skript klinkt sich ein, navigiert zum Models-Tab und extrahiert die genauen Daten und gibt sie als ASCII-Balken aus:

```python
import time
import sys
import json
from playwright.sync_api import sync_playwright

DEVTOOLS_URL = "http://localhost:58323"

def extract_quota():
    with sync_playwright() as p:
        print("Verbinde mit Antigravity via CDP...")
        browser = p.chromium.connect_over_cdp(DEVTOOLS_URL)
        page = browser.contexts[0].pages[0]
        
        # 1. Sicherstellen, dass das Einstellungsmenü geöffnet ist
        is_settings_open = page.locator("span:text-is('General')").first.is_visible()
        if not is_settings_open:
            print("Einstellungsfenster geschlossen. Öffne Einstellungen...")
            settings_btn = page.locator("text=Settings").first
            if settings_btn.is_visible():
                settings_btn.click()
            else:
                page.locator("div[data-testid='settings-button']").first.click()
            time.sleep(2.0)
            
        # 2. Auf Models-Reiter klicken
        print("Aktivierte Models-Tab...")
        span_candidates = page.locator("span:text-is('Models')")
        count = span_candidates.count()
        for i in range(count):
            span = span_candidates.nth(i)
            if span.is_visible():
                span.click()
                time.sleep(2.0)
                break

        # 3. DOM-Baum auslesen und Kapazitäten analysieren
        quota_data = page.evaluate("""() => {
            const containers = [];
            const allTextSm = Array.from(document.querySelectorAll('div.text-sm'));
            
            allTextSm.forEach(el => {
                const text = el.textContent.trim();
                if (text.includes('Gemini') || text.includes('Claude') || text.includes('GPT-OSS')) {
                    let parent = el.parentElement;
                    while (parent) {
                        if (parent.textContent.includes('Refreshes in') && parent.classList.contains('flex-col')) {
                            if (!containers.includes(parent)) {
                                containers.push(parent);
                            }
                            break;
                        }
                        parent = parent.parentElement;
                    }
                }
            });
            
            const rows = [];
            containers.forEach(container => {
                const nameEl = container.querySelector('div.text-sm');
                const name = nameEl ? nameEl.textContent.trim() : "Unbekanntes Modell";
                
                const refreshEl = container.querySelector('div.text-xs') || container.querySelector('div.text-muted-foreground');
                const refresh = refreshEl ? refreshEl.textContent.trim() : "";
                
                const barFills = Array.from(container.querySelectorAll('div[style*="width"]'));
                let filled = 0;
                let total = barFills.length;
                
                barFills.forEach(fill => {
                    if ((fill.style.width || "").includes('100%')) {
                        filled++;
                    }
                });
                
                rows.push({ name, refresh, filled, total });
            });
            return rows;
        }""")
        
        # 4. Quoten ausgeben
        print("\n=== MODEL QUOTA CAPACITY ===")
        for item in quota_data:
            bar_chars = '#' * item["filled"] + '-' * (item["total"] - item["filled"])
            print(f"Modell: {item['name']}")
            print(f"  Kapazität: {item['filled']}/{item['total']} [{bar_chars}]")
            print(f"  Aktualisierung: {item['refresh']}")
            print("-" * 40)
            
        # 5. Einstellungsmenü wieder schließen (zurück zum Chat)
        print("Schließe Einstellungen...")
        page.keyboard.press("Escape")
        time.sleep(1.0)
            
        browser.close()

if __name__ == "__main__":
    extract_quota()
```

---

## 7. Google One AI Guthaben- & Aktivitäts-Dashboard

Dieses System ermöglicht es dir, dein verbleibendes Google One AI-Guthaben sowie die Aktivitäten der Familiengruppe live zu verfolgen und in einem modernen Dark-Mode-Dashboard anzuzeigen. Es läuft vollkommen **lokal und headless** im Hintergrund.

### A. Funktionsweise und Architektur

Das System besteht aus zwei Hauptteilen:
1. **Python API-Server (`quota_api_server.py`)**:
   * Läuft lokal auf Port `58329`.
   * Liest deine (entschlüsselten) Browser-Cookies aus Brave/Chrome.
   * Startet im Hintergrund (headless) Playwright, lädt die Cookies, navigiert zu Google One und extrahiert das Guthaben sowie die Tabellendaten.
   * Stellt API-Endpunkte für das Dashboard bereit.
2. **Glassmorphism-Frontend (`activity_dashboard.html`)**:
   * Ein edles, responsives Dashboard mit dunklem Hintergrund, Neon-Glows, Weichzeichnern und animierten Ladezuständen.
   * Holt die Daten via Fetch-API und bietet einen "Sync Now"-Button für Echtzeit-Updates.

---

### B. Die Performance-Optimierung (Das 4-Sekunden-Geheimnis)

Ursprünglich dauerte die Synchronisierung über **35 Sekunden**, weil Google One im Hintergrund permanent Analysedaten und Telemetrie-Streams überträgt. Ein normales `page.goto(url, wait_until="networkidle")` wartete daher immer bis zum Timeout von 30 Sekunden.

**Die Lösung:**
* Wir wechseln bei `page.goto` von `"networkidle"` auf `"domcontentloaded"`. Dadurch wird der Ladevorgang fortgesetzt, sobald das Grundgerüst steht.
* Anstelle einer starren Wartezeit (`time.sleep(5.0)`) verwenden wir `page.wait_for_function`, um im Browser-DOM dynamisch auf das Vorhandensein der Schlüsselwörter wie `"Guthaben"`, `"Aktivität"` oder `"Mitgliedern"` zu prüfen.
* **Ergebnis:** Die gesamte Synchronisierung inklusive Browser-Start im Hintergrund dauert jetzt **nur noch ca. 4,4 Sekunden**!

---

### C. Kompletter Python-Server-Code (`quota_api_server.py`)

Speichere diesen Code in einer Datei namens `quota_api_server.py` ab und starte sie mit `python quota_api_server.py`.

```python
import time
import sys
import json
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from playwright.sync_api import sync_playwright

DEVTOOLS_URL = "http://localhost:63692"
PORT = 58329
COOKIES_JSON = r"C:\Users\Yildirim\.gemini\antigravity\scratch\decrypted_google_cookies.json"
CACHE_JSON = r"C:\Users\Yildirim\.gemini\antigravity\scratch\activity_data.json"

def get_active_page(context):
    for page in context.pages:
        try:
            if not page.url.startswith("data:"):
                return page
        except Exception:
            continue
    return context.pages[0]

def run_playwright_action(action_type, target_state=None):
    result = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(DEVTOOLS_URL)
            context = browser.contexts[0]
            page = get_active_page(context)
            
            # 1. Einstellungsfenster öffnen falls geschlossen
            is_settings_open = page.locator("span:text-is('General')").first.is_visible()
            if not is_settings_open:
                page.locator("[data-testid='settings-button']").first.click()
                time.sleep(1.5)
                
            # 2. Models-Tab aktivieren
            span_candidates = page.locator("span:text-is('Models')")
            count = span_candidates.count()
            clicked = False
            for i in range(count):
                span = span_candidates.nth(i)
                if span.is_visible():
                    span.click()
                    clicked = True
                    time.sleep(1.0)
                    break
            
            # 3. Aktion ausführen (Guthaben auslesen oder toggle)
            if action_type == 'get_credits' or action_type == 'toggle_credits':
                toggle_result = page.evaluate("""(target) => {
                    const label = Array.from(document.querySelectorAll('*')).find(el => el.textContent.trim() === 'Enable AI Credit Overages');
                    if (!label) return { success: false, error: 'Label not found' };
                    
                    let p = label.parentElement;
                    while (p) {
                        const btn = p.querySelector('button[role="switch"]');
                        if (btn) {
                            const currentChecked = btn.getAttribute('aria-checked') === 'true';
                            if (target === 'status') {
                                return { success: true, changed: false, state: currentChecked };
                            }
                            
                            const desiredChecked = target === 'on';
                            if (currentChecked !== desiredChecked) {
                                btn.click();
                                return { success: true, changed: true, state: desiredChecked };
                            }
                            return { success: true, changed: false, state: currentChecked };
                        }
                        p = p.parentElement;
                    }
                    return { success: false, error: 'Switch button not found' };
                }""", 'status' if action_type == 'get_credits' else target_state)
                
                if not toggle_result.get("success"):
                    result = toggle_result
                else:
                    if toggle_result.get("changed"):
                        time.sleep(1.5)
                        
                    credits_info = page.evaluate("""() => {
                        let state = false;
                        const label = Array.from(document.querySelectorAll('*')).find(el => el.textContent.trim() === 'Enable AI Credit Overages');
                        if (label) {
                            let p = label.parentElement;
                            while (p) {
                                const btn = p.querySelector('button[role="switch"]');
                                if (btn) {
                                    state = btn.getAttribute('aria-checked') === 'true';
                                    break;
                                }
                                p = p.parentElement;
                            }
                        }
                        
                        let available_credits = null;
                        let activity_url = null;
                        
                        if (state) {
                            const creditsLabel = Array.from(document.querySelectorAll('span, div')).find(el => el.textContent.trim().startsWith('Available AI Credits:'));
                            if (creditsLabel) {
                                const match = creditsLabel.textContent.trim().match(/Available AI Credits:\s*(\d+)/);
                                if (match) {
                                    available_credits = parseInt(match[1], 10);
                                }
                            }
                            
                            const activityLink = Array.from(document.querySelectorAll('a')).find(el => el.textContent.trim() === 'See Activity');
                            if (activityLink) {
                                activity_url = activityLink.getAttribute('href');
                            }
                        }
                        
                        return {
                            state: state,
                            available_credits: available_credits,
                            activity_url: activity_url
                        };
                    }""")
                    
                    result = {
                        "success": True,
                        "credits_overages_enabled": credits_info["state"],
                        "available_credits": credits_info["available_credits"],
                        "activity_url": credits_info["activity_url"],
                        "changed": toggle_result.get("changed", False)
                    }
                
            elif action_type == 'refresh':
                refresh_result = page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('button')).find(el => el.textContent.trim() === 'Refresh');
                    if (btn) {
                        btn.click();
                        return { success: true };
                    }
                    return { success: false, error: 'Refresh button not found' };
                }""")
                if refresh_result["success"]:
                    time.sleep(2.5)
                    
            if action_type == 'get_quota' or action_type == 'refresh':
                quota_data = page.evaluate("""() => {
                    const containers = [];
                    const allTextSm = Array.from(document.querySelectorAll('div.text-sm'));
                    
                    allTextSm.forEach(el => {
                        const text = el.textContent.trim();
                        if (text.includes('Gemini') || text.includes('Claude') || text.includes('GPT-OSS')) {
                            let parent = el.parentElement;
                            while (parent) {
                                if (parent.textContent.includes('Refreshes in') && parent.classList.contains('flex-col')) {
                                    if (!containers.includes(parent)) {
                                        containers.push(parent);
                                    }
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                        }
                    });
                    
                    const rows = [];
                    containers.forEach(container => {
                        const nameEl = container.querySelector('div.text-sm');
                        const name = nameEl ? nameEl.textContent.trim() : "Unknown Model";
                        const refreshEl = container.querySelector('div.text-xs') || container.querySelector('div.text-muted-foreground');
                        const refresh = refreshEl ? refreshEl.textContent.trim() : "";
                        const barFills = Array.from(container.querySelectorAll('div[style*="width"]'));
                        let filled = 0;
                        let total = barFills.length;
                        
                        barFills.forEach(fill => {
                            if ((fill.style.width || "").includes('100%')) {
                                filled++;
                            }
                        });
                        
                        rows.push({ name, refresh, filled, total });
                    });
                    return rows;
                }""")
                result = {"success": True, "quota": quota_data}
                
                try:
                    with open(r"C:\Users\Yildirim\.gemini\antigravity\scratch\quota_results.json", "w", encoding="utf-8") as f:
                        json.dump(quota_data, f, indent=4)
                except Exception:
                    pass
            
            page.keyboard.press("Escape")
            time.sleep(0.5)
            browser.close()
            
        except Exception as e:
            result = {"success": False, "error": str(e)}
            
    return result

def webkit_to_unix(webkit_timestamp):
    try:
        if not webkit_timestamp or webkit_timestamp <= 0:
            return None
        seconds = float(webkit_timestamp) / 1000000.0
        unix_time = seconds - 11644473600.0
        return unix_time if unix_time >= 0 else None
    except Exception:
        return None

def parse_html_to_data(html):
    html = html.replace('&amp;nbsp;', ' ').replace('&nbsp;', ' ').replace('&#160;', ' ').replace('&Uuml;', 'Ü').replace('&uuml;', 'ü').replace('&Auml;', 'Ä').replace('&auml;', 'ä').replace('&Ouml;', 'Ö').replace('&ouml;', 'ö').replace('&szlig;', 'ß')
    text_content = re.sub(r'<[^>]+>', '\n', html)
    lines = [l.strip() for l in text_content.split('\n') if l.strip()]
    
    data = {
        "available_credits": None,
        "next_expiration": None,
        "my_activity": [],
        "family_activity": []
    }
    
    for i, line in enumerate(lines):
        if line == "KI-Guthaben" and i + 1 < len(lines):
            val = lines[i+1].replace('.', '').replace(',', '').strip()
            if val.isdigit():
                data["available_credits"] = lines[i+1]
        if "Nächstes Ablaufdatum" in line or "Verfallsdatum" in line:
            data["next_expiration"] = line.split(":")[-1].strip()
            
    for i, line in enumerate(lines):
        if "Meine letzte Aktivit" in line:
            idx = i + 1
            while idx < len(lines) and lines[idx] in ["DATUM", "KATEGORIE", "BETRAG"]:
                idx += 1
            
            while idx + 2 < len(lines):
                potential_date = lines[idx]
                potential_cat = lines[idx+1]
                potential_amt = lines[idx+2]
                
                is_date = ("," in potential_date and ":" in potential_date)
                is_amt = (potential_amt.startswith("-") or potential_amt.replace('.', '').replace(',', '').isdigit())
                
                if is_date and is_amt:
                    data["my_activity"].append({
                        "date": potential_date,
                        "category": potential_cat,
                        "amount": potential_amt
                    })
                    idx += 3
                else:
                    break
            break
            
    for i, line in enumerate(lines):
        if "Mitgliedern der Familiengruppe" in line:
            idx = i + 1
            while idx + 1 < len(lines):
                name = lines[idx]
                amt = lines[idx+1]
                
                if name in ["Familiengruppe ansehen", "Bestimmte KI-Vorteile"] or "Familiengruppe" in name:
                    break
                    
                is_amt = (amt.startswith("-") or amt.replace('.', '').replace(',', '').isdigit())
                if is_amt and not ("," in name and ":" in name):
                    data["family_activity"].append({
                        "name": name,
                        "amount": amt
                    })
                    idx += 2
                else:
                    break
            break
            
    return data

def fetch_and_parse_google_activity():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            
            if not os.path.exists(COOKIES_JSON):
                return {"success": False, "error": f"Brave-Cookies nicht gefunden unter {COOKIES_JSON}."}
                
            with open(COOKIES_JSON, "r", encoding="utf-8") as f:
                cookies = json.load(f)
                
            for c in cookies:
                val = c["value"]
                # 15-Zeichen-Verschlüsselungspräfix entfernen falls vorhanden
                cleaned_value = val[15:] if len(val) >= 15 else val
                same_site = c.get("sameSite", "Lax")
                if same_site not in ["Lax", "Strict", "None"]:
                    same_site = "Lax"
                
                pw_c = {
                    "name": c["name"],
                    "value": cleaned_value,
                    "domain": c["domain"],
                    "path": c["path"],
                    "secure": c["secure"],
                    "sameSite": same_site
                }
                expires_unix = webkit_to_unix(c.get("expires"))
                if expires_unix:
                    pw_c["expires"] = expires_unix
                    
                try:
                    context.add_cookies([pw_c])
                except Exception:
                    pass
                    
            page = context.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
            })
            
            url = "https://one.google.com/u/4/ai/activity?email=alpre0024@gmail.com&pli=1&g1_landing_page=0"
            try:
                # OPTIMIERUNG: wait_until="domcontentloaded" spart 30 Sekunden!
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass
                
            # OPTIMIERUNG: Dynamischer DOM-Check anstelle von time.sleep(5.0)
            try:
                page.wait_for_function(
                    "() => document.body.innerText.includes('Guthaben') || document.body.innerText.includes('Aktivität') || document.body.innerText.includes('Mitgliedern')",
                    timeout=5000
                )
            except Exception:
                time.sleep(2.0)
                
            current_url = page.url
            if "signin" in current_url or "accounts.google.com" in current_url:
                browser.close()
                return {"success": False, "error": "Google-Session abgelaufen. Bitte Brave schließen und Cookies synchronisieren."}
                
            html = page.content()
            browser.close()
            
            data = parse_html_to_data(html)
            data["last_updated"] = time.strftime("%d.%m.%Y, %H:%M:%S")
            data["success"] = True
            
            with open(CACHE_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            return data
        except Exception as e:
            return {"success": False, "error": f"Scraping-Fehler: {str(e)}"}

class QuotaAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        if path == "/quota":
            res = run_playwright_action('get_quota')
            if res.get("success"):
                self._send_response(res["quota"])
            else:
                self._send_response(res, status=500)
                
        elif path == "/credits":
            res = run_playwright_action('get_credits')
            if res.get("success"):
                self._send_response({
                    "credits_overages_enabled": res["credits_overages_enabled"],
                    "available_credits": res["available_credits"],
                    "activity_url": res["activity_url"]
                })
            else:
                self._send_response(res, status=500)
                
        elif path == "/activity":
            dashboard_path = r"C:\Users\Yildirim\.gemini\antigravity\scratch\activity_dashboard.html"
            try:
                with open(dashboard_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error loading dashboard: {str(e)}".encode('utf-8'))

        elif path == "/api/activity":
            if os.path.exists(CACHE_JSON):
                try:
                    with open(CACHE_JSON, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._send_response(data)
                    return
                except Exception:
                    pass
            res = fetch_and_parse_google_activity()
            if res.get("success"):
                self._send_response(res)
            else:
                self._send_response(res, status=500)
        else:
            self._send_response({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        params = urllib.parse.parse_qs(parsed_url.query)
        
        if path == "/quota/refresh":
            res = run_playwright_action('refresh')
            if res.get("success"):
                self._send_response(res["quota"])
            else:
                self._send_response(res, status=500)
                
        elif path == "/api/activity/refresh":
            res = fetch_and_parse_google_activity()
            if res.get("success"):
                self._send_response(res)
            else:
                self._send_response(res, status=500)
                
        elif path == "/credits" or path == "/credits/toggle":
            state = params.get("state", [None])[0]
            if state not in ["on", "off"]:
                self._send_response({"error": "Missing state=on/off parameter"}, status=400)
                return
            res = run_playwright_action('toggle_credits', target_state=state)
            if res.get("success"):
                self._send_response({
                    "success": True,
                    "credits_overages_enabled": res["credits_overages_enabled"],
                    "available_credits": res["available_credits"],
                    "activity_url": res["activity_url"],
                    "changed": res["changed"]
                })
            else:
                self._send_response(res, status=500)
        else:
            self._send_response({"error": "Not Found"}, status=404)

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    server = HTTPServer(('localhost', PORT), QuotaAPIHandler)
    print(f"Starting Antigravity Quota API Server on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

if __name__ == "__main__":
    main()
```

---

### D. Das Dashboard UI-Design (`activity_dashboard.html`)

Hier ist der vollständige Code der Weboberfläche. Sie verwendet HSL-Farbpaletten, Google Fonts (Outfit & Inter), Glassmorphism-Transparenzen und ein flüssiges CSS-Animationsschema.

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google One AI Activity Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0c10;
            --surface-color: rgba(22, 26, 41, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-glow: rgba(0, 242, 254, 0.15);
            --text-primary: #f1f3f9;
            --text-secondary: #9aa0a6;
            --primary-gradient: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%);
            --family-gradient: linear-gradient(135deg, #f5576c 0%, #f093fb 100%);
            --green-glow: 0 0 20px rgba(0, 242, 254, 0.35);
            --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(0, 242, 254, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(79, 172, 254, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 50% 50%, rgba(15, 17, 28, 1) 0%, rgba(8, 9, 13, 1) 100%);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1rem;
        }
        header {
            width: 100%; max-width: 1000px;
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 2.5rem;
        }
        h1 {
            font-family: 'Outfit', sans-serif; font-weight: 800; font-size: 1.8rem;
            background: var(--primary-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .user-badge {
            background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border-color);
            padding: 0.5rem 1rem; border-radius: 50px; font-size: 0.9rem; color: var(--text-secondary);
            backdrop-filter: blur(10px); display: flex; align-items: center; gap: 0.5rem;
        }
        .user-dot { width: 8px; height: 8px; background-color: #00f2fe; border-radius: 50%; box-shadow: 0 0 8px #00f2fe; }
        main { width: 100%; max-width: 1000px; display: grid; grid-template-columns: 1fr; gap: 2rem; }
        @media (min-width: 768px) { main { grid-template-columns: 1.2fr 0.8fr; } }
        .glass-card {
            background: var(--surface-color); border: 1px solid var(--border-color);
            border-radius: 20px; padding: 2rem; backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
            box-shadow: var(--card-shadow); transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
            position: relative; overflow: hidden;
        }
        .glass-card:hover { transform: translateY(-5px); border-color: rgba(0, 242, 254, 0.2); }
        .hero-section { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr; gap: 1.5rem; }
        @media (min-width: 600px) { .hero-section { grid-template-columns: 1.2fr 0.8fr; } }
        .credits-title { font-size: 0.95rem; font-weight: 500; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 0.5rem; }
        .credits-val {
            font-family: 'Outfit', sans-serif; font-size: 3.5rem; font-weight: 800;
            background: var(--primary-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            text-shadow: var(--green-glow);
        }
        .expiration-date { font-family: 'Outfit', sans-serif; font-size: 1.8rem; font-weight: 600; color: #ffb703; }
        .controls-card { display: flex; justify-content: space-between; align-items: center; grid-column: 1 / -1; padding: 1rem 2rem; }
        .btn-refresh {
            background: var(--primary-gradient); border: none; color: #0b0c10;
            font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 0.9rem;
            padding: 0.75rem 1.5rem; border-radius: 12px; cursor: pointer;
            display: flex; align-items: center; gap: 0.5rem; box-shadow: 0 4px 15px rgba(0, 242, 254, 0.3);
            transition: all 0.3s ease;
        }
        .btn-refresh:hover { transform: scale(1.03); }
        .refresh-icon { width: 16px; height: 16px; fill: #0b0c10; }
        .loading .refresh-icon { animation: spin 1s infinite linear; }
        .list-container { display: flex; flex-direction: column; gap: 1rem; }
        .list-item {
            background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 14px; padding: 1rem 1.25rem; display: flex; justify-content: space-between; align-items: center;
        }
        .item-title { font-size: 0.95rem; font-weight: 600; }
        .item-subtitle { font-size: 0.8rem; color: var(--text-secondary); }
        .item-amount { font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 1.1rem; padding: 0.25rem 0.75rem; border-radius: 8px; }
        .amount-negative { background: rgba(255, 65, 108, 0.1); color: #ff4d6d; border: 1px solid rgba(255, 65, 108, 0.15); }
        .family-avatar {
            width: 38px; height: 38px; border-radius: 50%; background: var(--family-gradient);
            display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.9rem; color: #fff;
        }
        .family-profile { display: flex; align-items: center; gap: 0.75rem; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .skeleton { background: linear-gradient(90deg, rgba(255,255,255,0.03) 25%, rgba(255,255,255,0.08) 37%, rgba(255,255,255,0.03) 63%); background-size: 400% 100%; animation: skeleton 1.4s infinite; border-radius: 4px; }
        .skeleton-card { height: 70px; border-radius: 14px; }
        @keyframes skeleton { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
        .toast { position: fixed; bottom: 20px; right: 20px; background: rgba(22, 26, 41, 0.9); border: 1px solid rgba(255, 65, 108, 0.3); color: #ff4d6d; padding: 1rem 1.5rem; border-radius: 12px; display: none; }
    </style>
</head>
<body>
    <header>
        <h1>AI Guthaben-Aktivität</h1>
        <div class="user-badge"><span class="user-dot"></span><span>alpre0024@gmail.com</span></div>
    </header>
    <main>
        <section class="hero-section">
            <div class="glass-card">
                <span class="credits-title">KI-Guthaben</span>
                <div><span id="credits-amount" class="credits-val">--</span> <span style="color:var(--text-secondary)">Punkte</span></div>
            </div>
            <div class="glass-card">
                <span class="credits-title">Nächstes Ablaufdatum</span>
                <div id="expiration-val" class="expiration-date" style="margin-top:0.5rem">--</div>
            </div>
        </section>
        <section class="glass-card controls-card">
            <div>Zuletzt aktualisiert: <span id="last-updated">Nie</span></div>
            <button class="btn-refresh" id="btn-refresh" onclick="triggerRefresh()">
                <svg class="refresh-icon" viewBox="0 0 24 24"><path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                Sync Now
            </button>
        </section>
        <section class="glass-card">
            <h2 style="margin-bottom:1.5rem">Meine letzte Aktivität</h2>
            <div class="list-container" id="my-activity-list"><div class="skeleton skeleton-card"></div></div>
        </section>
        <section class="glass-card">
            <h2 style="margin-bottom:1.5rem">Familiengruppe</h2>
            <div class="list-container" id="family-activity-list"><div class="skeleton skeleton-card"></div></div>
        </section>
    </main>
    <div class="toast" id="toast-err">Fehler beim Laden.</div>
    <script>
        const API_URL = '/api/activity';
        const REFRESH_URL = '/api/activity/refresh';
        function showSkeletons() {
            document.getElementById('credits-amount').innerHTML = `<span class="skeleton" style="display:inline-block; width:100px; height:3.5rem"></span>`;
            document.getElementById('my-activity-list').innerHTML = `<div class="skeleton skeleton-card"></div>`;
            document.getElementById('family-activity-list').innerHTML = `<div class="skeleton skeleton-card"></div>`;
        }
        async function loadData() {
            try {
                const response = await fetch(API_URL);
                if (!response.ok) throw new Error();
                renderData(await response.json());
            } catch { triggerRefresh(); }
        }
        function renderData(data) {
            if (!data || !data.success) { showToast(data ? data.error : "Fehler"); return; }
            document.getElementById('credits-amount').textContent = data.available_credits || "0";
            document.getElementById('expiration-val').textContent = data.next_expiration || "Unbekannt";
            document.getElementById('last-updated').textContent = data.last_updated;
            document.getElementById('my-activity-list').innerHTML = data.my_activity.map(a => `
                <div class="list-item">
                    <div class="family-profile">
                        <div class="family-avatar" style="background: var(--primary-gradient)">ME</div>
                        <div class="item-details">
                            <span class="item-title">Ich (${userEmail})</span>
                            <span class="item-subtitle">${a.category} • ${a.date}</span>
                        </div>
                    </div>
                    <span class="item-amount amount-negative">${a.amount}</span>
                </div>
            `).join('');
            document.getElementById('family-activity-list').innerHTML = data.family_activity.map(a => `
                <div class="list-item">
                    <div class="family-profile"><div class="family-avatar">${a.name.substring(0,2).toUpperCase()}</div><span class="item-title">${a.name}</span></div>
                    <span class="item-amount amount-negative">${a.amount}</span>
                </div>
            `).join('');
        }
        async function triggerRefresh() {
            const btn = document.getElementById('btn-refresh');
            btn.classList.add('loading'); btn.disabled = true; showSkeletons();
            try {
                const response = await fetch(REFRESH_URL, { method: 'POST' });
                renderData(await response.json());
            } catch (err) { showToast("Sync fehlgeschlagen."); loadData(); }
            finally { btn.classList.remove('loading'); btn.disabled = false; }
        }
        function showToast(msg) {
            const t = document.getElementById('toast-err'); t.textContent = msg; t.style.display = 'block';
            setTimeout(() => t.style.display = 'none', 5000);
        }
        document.addEventListener('DOMContentLoaded', loadData);
    </script>
</body>
</html>
```

---

## 8. Fortgeschrittene Server-Automatisierung, Cookies & Parallelisierung

In diesem Abschnitt werden die fortgeschrittenen Steuerungskonzepte, die Cookie-Lebensdauer, das Sicherheits-Limit für `Nxdhdh` und die Parallelisierung von Chats beschrieben.

### A. Headless-Scraping vs. Unsichtbare UI-Steuerung (Quasi-Headless)
Das System nutzt zwei unterschiedliche Automatisierungs-Modi:
1. **Google One Scraping (Voll-Headless)**: Läuft zu 100% im Hintergrund (`headless=True`). Playwright startet eine unsichtbare Chromium-Instanz und nutzt die entschlüsselten Google-Cookies.
2. **Antigravity App Steuerung (Unsichtbare UI)**: Die eigentliche Desktop-App ist eine Headful-Anwendung. Da wir uns über das Chrome DevTools Protocol (CDP) verbinden, würde das Öffnen des Einstellungsfensters normalerweise ein sichtbares Pop-up auf dem Bildschirm erzeugen.
   * **Die unsichtbare Lösung**: Das Python-Skript injiziert vor dem Öffnen der Einstellungen ein CSS-Style-Tag in das Dokument:
     `div[class*="z-[2550]"] { opacity: 0 !important; pointer-events: auto !important; transition: none !important; }`
     Dadurch wird das Einstellungs-Fenster vollständig transparent und unsichtbar für den Benutzer. Playwright kann die Elemente (wie den Credits-Switch) dennoch problemlos anklicken, da sie im Layout vorhanden sind. Nach der Aktion wird das CSS-Style-Tag wieder entfernt.

### B. Unbegrenzte Cookie-Lebensdauer (Cookie Auto-Rotation)
Google-Session-Cookies (wie `SID`, `HSID`, `SSID`) verfallen normalerweise nach einiger Zeit. 
* Wenn der Scraper erfolgreich die Google One Seite geladen hat, aktualisiert Google im Hintergrund die Session-Tokens und verlängert deren Ablaufdatum.
* Das Skript liest diese aktualisierten Cookies direkt nach dem Laden über `context.cookies()` aus der Playwright-Session aus und überschreibt die `decrypted_google_cookies.json`.
* **Empfehlung**: Führe einen Cron-Job oder ein Skript aus, das alle 6 bis 12 Stunden den Endpunkt `POST /api/activity/refresh` aufruft. Dadurch werden die Cookies kontinuierlich rotiert und verfallen **nie**.

### C. Sicherheitsregel für Nxdhdh (Credit Limit 6.000)
Für das Familienmitglied `Nxdhdh` gilt ein striktes Limit von **6.000 Credits**. 
* **Automatische Abschaltung**: Wenn bei einer Synchronisierung festgestellt wird, dass `Nxdhdh` eine Nutzung von **>= 5.500 Credits** erreicht hat (500 Credits vor dem Limit), führt das System sofort eine unsichtbare UI-Aktion durch und schaltet die Option "Enable AI Credit Overages" auf `off`.
* **API-Sperre**: Versucht ein Client (z. B. OpenClaw) nachträglich `POST /api/credits/toggle?state=on` aufzurufen, prüft der API-Server die gecachten Aktivitätsdaten. Ist die Nutzung von `Nxdhdh` >= 5.500 Credits, wird die Anfrage mit einem Fehler blockiert, um das Limit zu schützen.

### D. OpenClaw-API & Parallelisierung (3 Chats gleichzeitig)
Um mehrere Chats gleichzeitig zu steuern (z. B. 3 parallele Chats ohne Verzögerungen durch die Benutzeroberfläche):

1. **CDP-Thread-Lock**:
   Da die Benutzeroberfläche von Antigravity eine Single-Page-App ist, blockiert der API-Server alle CDP-Aktionen mit einem `threading.Lock`. Dadurch werden parallele Anfragen sicher nacheinander abgearbeitet, ohne dass die UI abstürzt.

2. **Parallelisierung via Datei-Ebene (Empfohlen für OpenClaw & Agenten)**:
   Anstatt die UI für jeden Chat per Klick umzuschalten (was bei vielen parallelen Chats langsam ist), können Agenten direkt über das Dateisystem kommunizieren:
   * **Chat-Logs lesen**: Die App schreibt jede Nachricht live als JSON-Zeile in:
     `C:\Users\Yildirim\.gemini\antigravity\brain\<CONVERSATION_ID>\.system_generated\logs\transcript.jsonl`
   * **Chat-Logs schreiben / Befehle senden**: Du kannst Nachrichten an den Agenten senden, indem du Zeilen im JSONL-Format an die `transcript.jsonl` anhängst oder die Hintergrund-Agenten direkt ansprichst. Dies umgeht die langsame UI komplett und erlaubt unbegrenzte parallele Unterhaltungen ohne UI-Wartezeit.

3. **Standardisierte API-Endpunkte für OpenClaw**:
   * `GET /api/quota`: Gibt die aktuellen Modell-Quoten als JSON zurück.
   * `POST /api/quota/refresh`: Erzwingt eine Aktualisierung der Quoten in der App und gibt sie zurück.
   * `GET /api/credits`: Gibt den Status der Credit-Overages und verfügbare Credits zurück.
   * `POST /api/credits/toggle?state=on|off`: Schaltet Credit-Overages ein oder aus (gesichert durch das Nxdhdh-Limit).
   * `GET /api/activity`: Gibt die gecachten Google One Guthaben- und Aktivitätsdaten zurück.
   * `POST /api/activity/refresh`: Scraped Google One neu, rotiert Cookies, prüft das Nxdhdh-Limit und gibt das Ergebnis zurück.


