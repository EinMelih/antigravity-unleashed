---
name: antigravity_desktop_ui_modifier
description: Safely rebase, validate, repack, and troubleshoot the Windows Antigravity desktop Electron modifier against an explicitly supported upstream version.
---

# Antigravity Desktop UI Modifier

Dieses Skill-Paket patcht die lokal installierte Antigravity-Desktop-App. Es ist ein
inoffizieller Windows-Workflow und macht weder Antigravity noch enthaltenen
Google-Code automatisch zu Open Source.

Der aktuelle Modifier ist ausschließlich für **Upstream v2.26.0** freigegeben. Die
maschinenlesbare Quelle dafür ist `SUPPORTED_UPSTREAM_VERSION`. Eine andere
installierte Version muss vor dem Repack hart abgewiesen werden.

## Voraussetzungen

- Windows 11 und eine per-user installierte Antigravity-Desktop-App.
- Python 3 mit `aiohttp`.
- Node.js sowie ein lokal ohne Installationsprompt ausführbares `npx.cmd --no-install asar`.
- Schreibzugriff auf den eigenen Antigravity-`resources`-Ordner.
- Eine rechtlich zulässige lokale Antigravity-Installation.

Preflight:

```powershell
python -c "import aiohttp"
node --version
npx.cmd --no-install asar --version
Get-Content .\SUPPORTED_UPSTREAM_VERSION
```

`npx.cmd --no-install asar --version` muss ohne Download funktionieren. Ein
reproduzierbares Dependency-Manifest fehlt derzeit und ist vor einer öffentlichen
Veröffentlichung nachzurüsten.

## Portable Pfade

Standardmäßig werden Pfade aus den Windows-Umgebungsvariablen abgeleitet:

```text
Install:   %LOCALAPPDATA%\Programs\Antigravity
Resources: %LOCALAPPDATA%\Programs\Antigravity\resources
User data: %APPDATA%\Antigravity
```

Optionale Overrides:

| Variable | Zweck |
| --- | --- |
| `ANTIGRAVITY_INSTALL_DIR` | Abweichender Installationsordner mit `Antigravity.exe` |
| `ANTIGRAVITY_RESOURCES_DIR` | Abweichender Ordner mit `app.asar` |
| `ANTIGRAVITY_USER_DATA_DIR` | Abweichender User-Data-Ordner |
| `ANTIGRAVITY_PYTHON` | Python für den Repack-Scheduled-Task |
| `ANTIGRAVITY_PYTHONW` | Fensterloses Python für den Guard |

Die Skripte dürfen keine Benutzerprofilnamen oder festen Python-Versionen
enthalten. Der Task-Launcher löst seine eigenen Dateien relativ zu
`$PSScriptRoot` auf.

## Source-of-Truth

- Modulare Renderer-Erweiterungen liegen unter `src/ui/`.
- `src/ui/preload_header.txt` und `src/ui/preload_footer.txt` bilden zusammen
  mit den UI-Modulen die generierte `src/preload.js`.
- `scripts/build_preload.py` erzeugt `preload.js`; die generierte Datei nicht
  als alleinige Quelle editieren.
- Main-/IPC-Anpassungen liegen in kleinen AMS-Modulen (`src/amsMainBootstrap.js`,
  `src/amsIpcSecurity.js`, `src/amsWindowNavigation.js`) oder in den bewusst
  rebasierten `src/main.js`, `src/ipcHandlers.js`, `src/updater.js` und
  `src/utils.js`.

Vor einem Repack:

```powershell
python .\scripts\build_preload.py
python -m py_compile .\scripts\repack_and_restart.py .\scripts\auto_repack_guard.py
python .\scripts\auto_repack_guard.py --status-json
```

> [!IMPORTANT]
> **PFLICHTREGEL FÜR AGENTEN (Kein automatischer Neustart während andere Agenten arbeiten):**
> Starte `repack_and_restart.py` oder `start_repack_task.ps1` **niemals automatisch**, nachdem du Änderungen an `src/ui/*` oder `src/*` vorgenommen hast, es sei denn der User fordert den sofortigen Neustart ausdrücklich an!
> Stattdessen:
> 1. Kompiliere `preload.js` mit `python .\scripts\build_preload.py`.
> 2. Schreibe `~/.gemini/antigravity/scratch/repack_pending_notice.json` mit `{"title": "<Kurztitel der Änderung>", "details": "<Was das Update bringt>", "await_user_click": true, "updated_at": <epoch>}`.
> 3. Dadurch erscheint in der Antigravity-Leiste automatisch der auffällige gelbe Button **`↻ Neustart für: [Titel]`** (`#antigravity-repack-ready-btn`) sowie die Info-Karte im `UNLEASHED`-Menü. Der User entscheidet selbst per Klick (`window.amsTriggerRepackNow()`), wann seine anderen laufenden Agenten fertig sind und der 3-Sekunden-Repack starten soll.

## Sicherer Repack-Ablauf

`scripts/repack_and_restart.py` muss folgende Reihenfolge einhalten:

1. Exklusive Repack-Dateisperre übernehmen.
2. Optionalen Trigger-Chat atomar übernehmen und als UUID validieren.
3. Portable Installationspfade und Pflichtdateien prüfen.
4. `preload.js` neu bauen.
5. Eine vollständige, frische `app.asar` in ein dediziertes Staging-Verzeichnis
   extrahieren und die Mindeststruktur validieren.
6. `package.json` und die Hashes der überschriebenen Basisdateien gegen
   `SUPPORTED_UPSTREAM_VERSION` und `UPSTREAM_COMPATIBILITY.json` prüfen. Für
   v2.26.0 muss exakt `2.26.0` mit dem freigegebenen Upstream-Build installiert sein.
7. Alle JavaScript-Quellen prüfen und das komplette Overlay in Staging kopieren.
   Ein einzelner `mkdir`-/`copy2`-/Pfadfehler beendet den Lauf mit Nonzero,
   bevor die App beendet oder ein Archiv gepackt wird.
8. Draft und aktive Route bestmöglich sichern.
9. Nur Prozessbäume beenden, deren `Antigravity.exe` exakt aus dem ermittelten
   Installationsordner stammt. Niemals pauschal alle
   `Antigravity.exe`- oder `language_server.exe`-Prozesse beenden.
10. In Staging packen, das neue Archiv erneut extrahieren/validieren, vollständige
    Backups erstellen und erst dann atomar installieren.
11. Die dynamisch ermittelte EXE neu starten und Preload/API/UI ausschließlich
    read-only per CDP prüfen. Der Verifier navigiert nicht, leert keinen Composer,
    sendet keine Nachricht und fokussiert/schließt kein Chatfenster. Erst nach
    erfolgreichem Proof wird der installierte Archivhash atomar an Version und
    Upstream-Vertrags-Hash gebunden, damit spätere Source-Repack-Läufe dieselbe
    verifizierte Modifier-Basis sicher erkennen.
12. Bei echtem Boot-/Preloadfehler das vorherige Archiv und den externen
    `app.asar.unpacked`-Baum wiederherstellen.

Wichtige Einschränkung: Die heutige Reparatur eines unvollständigen
`app.asar.unpacked`-Baums prüft beim `.bak`-Ordner nur Struktur und
Pflichtdateien, aber noch keine kryptografische Bindung an Archivhash und
Upstream-Version. Ein unbekanntes oder versionsfremdes Backup darf deshalb nicht
verwendet werden. Die Manifest-/Hash-Bindung ist ein dokumentierter
Release-Blocker.

## Upstream-Update

Nach jedem offiziellen Antigravity-Update:

1. Pristine `app.asar` und `app.asar.unpacked` sichern.
2. Offizielle `dist`-Dateien mit der zuletzt unterstützten Version vergleichen.
3. Custom-Code auf die neuen offiziellen APIs rebasen; keine alten Main-Dateien
   blind über die neue App kopieren.
4. Syntax-, Unit-, Packaging-, Rollback- und UI-Smoke-Tests auf einer
   isolierten Testinstallation durchführen.
5. Erst nach erfolgreichem Proof `SUPPORTED_UPSTREAM_VERSION` aktualisieren.

Nur die Versionsdatei hochzusetzen ist keine Kompatibilitätsfreigabe.

## Scheduled Tasks

Der portable Launcher verändert den Windows Task Scheduler nur bei expliziter
Ausführung:

```powershell
# Entscheidungen anzeigen; Preflight läuft, Tasks werden nicht registriert/gestartet
& .\scripts\start_repack_task.ps1 -WhatIf

# Nur registrieren
& .\scripts\start_repack_task.ps1 -RegisterOnly

# Guard registrieren und starten
& .\scripts\start_repack_task.ps1 -GuardOnly

# Guard registrieren, Repack registrieren und Repack einmal starten
& .\scripts\start_repack_task.ps1

# Auf das Repack-Ergebnis warten und einen Nonzero-Exit sichtbar melden
& .\scripts\start_repack_task.ps1 -WaitForRepack
```

Bei mehreren Python-Installationen Pfade als Parameter übergeben oder
`ANTIGRAVITY_PYTHON`/`ANTIGRAVITY_PYTHONW` setzen.

`repack.bat` im Repository startet den Launcher mit `-WaitForRepack`, zeigt die
aktuelle Phase, meldet Fehler sichtbar und hält das Konsolenfenster bei einem
Fehler offen. Nach einem verifizierten manuellen Repack erscheint ein Erfolgs-Popup
und der Guard wird gestartet. Der Repack-Task bleibt für die Ergebnisabfrage erhalten.

Der Guard:

- vergleicht installierte ASAR- und Modifier-Signaturen;
- wartet auf eine normal gestartete App;
- startet nur einen transaktionalen Repack;
- speichert nach einem Fehler die beobachtete Signatur und versucht sie nicht
  erneut, solange dieselbe App-Sitzung läuft;
- löst den Failure-Latch erst bei App-Exit, Signaturänderung oder explizitem
  `--retry`;
- wartet bei reinen Quelländerungen 90 s Ruhe ab (App-Updates: drei Polls), damit
  ein mehrstufiger Edit nicht halbfertig gepackt wird;
- pausiert automatische Repacks, solange eine Agent-Selbstheilung analysiert,
  anpasst oder testet (bis der Repack startet, höchstens 30 min ohne
  Fortschrittsmeldung);
- respektiert eine manuelle Pause (`--pause MINUTEN`, max. 240, `--resume`), ohne
  dass der Scheduled Task gestoppt werden muss.

Nach jedem Repack auf einer unveränderten Upstream-Basis legt der Repacker eine
Upstream-Baseline unter `~/.gemini/antigravity/scratch/upstream_baselines/<version>/`
ab (ohne Tests, mit `baseline.json`-Hashes, die neuesten drei Versionen). Bei
einem Update dient sie als Vergleichsbasis für alle `dist`-Dateien.

Die Versionsprüfung liest `package.json` direkt aus der ASAR, bevor ein Build,
eine Extraktion oder das Beenden der App beginnt. Ein unbekanntes Update bleibt
blockiert, bis ein geprüfter Versionsvertrag vorliegt. Die Quellen stammen immer
aus dem Skill-Verzeichnis des laufenden Skripts.

Bei einem Fehler erscheint ein separates Windows-Popup mit Ursache und Logpfad.
Eine identische Fehlermeldung wird bis zum Erfolg oder einer ausdrücklich
angeforderten Wiederholung nur einmal angezeigt. Das Popup blockiert den Guard
nicht. Details und aktuelle Phase stehen in `repack_status.json`.

Status:

```powershell
python .\scripts\auto_repack_guard.py --status-json

# Fehler nach der Behebung erneut versuchen; eine unverifizierte Installation
# wird dabei nicht als erfolgreich gespeichert. Der Guard muss laufen.
python .\scripts\auto_repack_guard.py --retry
```

## Logs und Fehler

```text
~/.gemini/antigravity/scratch/repack_and_restart.log
~/.gemini/antigravity/scratch/repack_error.txt
~/.gemini/antigravity/scratch/repack_status.json
~/.gemini/antigravity/scratch/repack_notification.json
~/.gemini/antigravity/scratch/auto_repack_guard.log
~/.gemini/antigravity/scratch/auto_repack_guard_state.json
~/.gemini/antigravity/scratch/auto_repack_guard_failure.json
~/.gemini/antigravity/scratch/verified_repack_installation.json
```

Ein Nonzero-Exit oder `repack_error.txt` ist ein echter Fehler. Nicht durch
blindes `--mark-current` übergehen.

`--mark-current` wird nach dem read-only Runtime-Proof intern verwendet und prüft
Archivhash, Versionsvertrags-Hash und die gespeicherte Quellsignatur. Quellen, die
sich während des Repack-Laufs ändern, bleiben dadurch als ausstehend erkennbar.

## API-Profil und Desktop-Monitor

Die öffentliche KI-API des Hub verwendet ausschließlich das Desktop-Profil
`api`. Sein eigenes Prozess-Home liegt unter
`%LOCALAPPDATA%\AntigravityApiProfile\home` des normalen Windows-Profils. Darin
liegen eigene `.gemini/config`-Regeln/Memory/Einstellungen, Electron-AppData,
Konversationen unter `.gemini/antigravity-api` und der API-Workspace. Der Start
setzt HOME, USERPROFILE, AppData, Temp und Config-/Cache-Pfade nur fuer diesen
Prozessbaum. Private Einstellungen, Plugins, Sidecars und Memory werden nicht
importiert. Der gleiche Google-Login bleibt ueber den Konto-Speicher bzw. nur
Google-Auth-Cookies erhalten. Alte API-Ordner bleiben als Sicherung bestehen;
alte Chats mit privatem Regelkontext werden nicht in den neuen Lauf importiert.
Das normale Hauptfenster bleibt Profil `default`.

`window.electronNative.getProfileInfo()` liefert den lesenden Profil-Vertrag mit
`profile_contract_version: 2`, Profilname, tatsächlichem Home, Config-Verzeichnis,
Arbeitsverzeichnis und Datenpfaden. Der
API-Client prüft diese Identität vor Bridge-Injektion und bleibt auch bei einem
Reconnect im API-Profil. Ein nicht verifizierter Profil-Vertrag ergibt einen
Fehler; das private Fenster ist kein Fallback.

Der API-Statusknopf im Hauptfenster zeigt den lesenden, authentifizierten
`GET /api/monitor`-Endpunkt auf Port 8001 an. IPC-Operation `api:monitor` nutzt
einen festen Loopback-Host/Pfad; Authentifizierung bleibt im Main-Prozess. Die
Anzeige umfasst Health, Profiltrennung, Modell, Reasoning, Laufzeit und die
begrenzte Request-Historie seit API-Start. Modelldaten stammen live aus der
nativen API-Profil-Oberfläche.

## Sicherheitsregeln

- Renderer erhält keine freien Dateisystem-, Shell-, Netzwerk- oder
  Credential-APIs.
- IPC bleibt tokengebunden und operation-allowlisted.
- Lokale Hub-Zugriffe bleiben auf fest definierte Loopback-Hosts, Ports und Pfade
  beschränkt.
- API-Schlüssel und Hub-Konfiguration liegen außerhalb des Repositories.
- DevTools/CDP wird nur für den lokalen read-only Runtime-Proof benutzt.
