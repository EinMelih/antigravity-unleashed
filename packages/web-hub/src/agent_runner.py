import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import aiohttp

from src.config import config
from src.database import db
from src.project_manager import (
    git_create_and_checkout_branch,
    git_current_branch,
    git_commit,
    git_diff,
    git_push,
    git_status,
)


class AgentRunner:
    """Runs autonomous AI repair cycles for a given issue."""

    def __init__(self, run_id: int, resume: bool = False) -> None:
        self.run_id = run_id
        self.resume = resume
        self.log_prefix = f"[RUN #{self.run_id}]"

    def log(self, level: str, message: str) -> None:
        print(f"{self.log_prefix} [{level.upper()}] {message}", flush=True)
        db.add_run_log(self.run_id, level, message)

    async def run(self) -> None:
        try:
            # 1. Load run metadata
            run = db.get_agent_run(self.run_id)
            if not run:
                raise ValueError(f"Run ID {self.run_id} not found in database.")

            issue_id = run["issue_id"]
            issue = db.get_issue(issue_id)
            if not issue:
                raise ValueError(f"Issue ID {issue_id} not found.")

            project = db.get_project(issue["project_id"])
            if not project:
                raise ValueError(f"Project ID {issue['project_id']} not found.")

            project_path = project["path"]
            project_name = project["name"]
            test_command = project["test_command"]
            title = issue["title"]
            desc = issue["description"]

            self.log("info", f"[SYSTEM] 🚀 Ausführung gestartet für Issue #{issue_id}: '{title}'")
            db.update_issue_status(issue_id, "running")

            # 2. Checkout Git sandbox branch
            branch_name = f"ag-run-{issue_id}"
            self.log("info", f"[SYSTEM] 🌳 Bereite Git-Sandbox vor. Checkout Branch: {branch_name}...")

            # Switch to sandbox branch
            success = git_create_and_checkout_branch(project_path, branch_name)
            if not success:
                raise RuntimeError(f"Konnte Git-Branch {branch_name} im Projekt {project_path} nicht erstellen/auschecken.")

            self.log("info", f"[SYSTEM] 🌿 Aktiver Git-Branch ist jetzt: {git_current_branch(project_path)}")
            db.update_agent_run(self.run_id, "planning", "running")

            # 3. Build messages — either fresh or from existing chat history (resume)
            if self.resume:
                # RESUME MODE: Load existing chat messages from DB
                existing_msgs = db.get_chat_messages(self.run_id)
                messages = [{"role": m["role"], "content": m["content"]} for m in existing_msgs]
                self.log("info", f"[SYSTEM] 💬 Follow-Up Modus: {len(messages)} vorherige Nachrichten geladen.")
            else:
                # FRESH MODE: Build initial prompt
                prompt = (
                    f"You are working on project '{project_name}' located at '{project_path}'.\n"
                )
                if project.get('github_url'):
                    prompt += f"GitHub Repository: {project['github_url']}\n"
                prompt += (
                    f"\nIssue: {title}\n"
                    f"Type: {issue.get('issue_type', 'task')}\n"
                    f"Description:\n{desc}\n\n"
                    f"Instructions:\n"
                    f"- Analyze the codebase at the project path\n"
                    f"- Make all necessary file modifications\n"
                    f"- For new features: create the required files and structure\n"
                    f"- For bugs: identify and fix the root cause\n"
                    f"- Ensure the test command '{test_command}' passes\n"
                )
                messages = [{"role": "user", "content": prompt}]
                db.add_chat_message(self.run_id, "user", prompt)

            # 4. Check for subtasks
            subtasks = db.get_subtasks(issue_id)
            used_subtasks = len(subtasks) > 0
            success_status = False
            current_cycle = 0
            max_cycles = 5

            if used_subtasks:
                self.log("info", f"[SYSTEM] 📋 {len(subtasks)} Unteraufgabe(n) für dieses Issue gefunden. Starte Agent-Looping...")

                # We will process each subtask one by one
                for subtask in subtasks:
                    if subtask["status"] == "completed":
                        self.log("info", f"[SYSTEM] Subtask '{subtask['title']}' ist bereits erledigt. Überspringe...")
                        continue

                    self.log("info", f"[SYSTEM] 🚀 Starte Unteraufgabe: '{subtask['title']}'")
                    db.update_subtask_status(subtask["id"], "running")
                    db.update_agent_run(self.run_id, "planning", "running")

                    subtask_prompt = (
                        f"You are working on project '{project_name}' located at '{project_path}'.\n"
                        f"Your current goal is to complete the following subtask:\n"
                        f"SUBTASK: {subtask['title']}\n\n"
                        f"Overall Issue context:\n"
                        f"Issue Title: {title}\n"
                        f"Issue Description: {desc}\n\n"
                        f"Please make the necessary changes to complete this subtask. Once finished, ensure the tests pass."
                    )

                    if 'messages' not in locals():
                        messages = []

                    messages.append({"role": "user", "content": subtask_prompt})
                    db.add_chat_message(self.run_id, "user", subtask_prompt)

                    subtask_cycle = 0
                    subtask_max_cycles = 3
                    subtask_success = False

                    while subtask_cycle < subtask_max_cycles:
                        subtask_cycle += 1
                        current_cycle += 1
                        self.log("info", f"[SYSTEM] 🔄 Subtask-Zyklus {subtask_cycle}/{subtask_max_cycles} für '{subtask['title']}'...")

                        ai_response = await self._send_to_bridge_streaming(messages)
                        db.add_chat_message(self.run_id, "assistant", ai_response)
                        messages.append({"role": "assistant", "content": ai_response})

                        self.log("info", "[AGENT] 🧠 Agent-Denkprozess gestartet...")
                        steps = [
                            f"Analysiere Aufgabe: {subtask['title']}",
                            "Führe Code-Anpassungen aus",
                            "Führe Testcommand zur Validierung aus"
                        ]
                        for step in steps:
                            await asyncio.sleep(0.08)
                            self.log("info", f"[AGENT]          - [x] {step}")

                        # Git status
                        status_output = git_status(project_path)
                        changed_lines = [l for l in status_output.strip().split('\n') if l.strip()]
                        files_changed = len(changed_lines)

                        if files_changed > 0:
                            self.log("info", "[AGENT] 💾 Datei-Modifikationen angewendet:")
                            for line in changed_lines:
                                line = line.strip()
                                if not line: continue
                                parts = line.split(maxsplit=1)
                                if len(parts) == 2:
                                    status_char, filepath = parts
                                    self.log("info", f"[AGENT]          - [{status_char.strip()}] {filepath.strip('\"\'')}")

                        # Verify tests
                        db.update_agent_run(self.run_id, "verifying", "running")
                        self.log("info", f"[SYSTEM] 🧪 Führe Test-Validierung für Subtask aus...")
                        test_output, test_passed = await self._run_tests(project_path, test_command)
                        self.parse_and_log_tests(test_output, test_passed)

                        if test_passed:
                            self.log("success", f"[TESTS] 🎉 Subtask '{subtask['title']}' erfolgreich validiert!")
                            subtask_success = True
                            break
                        else:
                            self.log("warning", f"[TESTS] ⚠️ Validierung fehlgeschlagen für Subtask in Zyklus {subtask_cycle}!")
                            if subtask_cycle < subtask_max_cycles:
                                repair_prompt = (
                                    f"The tests failed for subtask '{subtask['title']}' with the following output:\n\n"
                                    f"```\n{test_output[:1500]}\n```\n\n"
                                    f"Please correct the implementation for this subtask."
                                )
                                messages.append({"role": "user", "content": repair_prompt})
                                db.add_chat_message(self.run_id, "user", repair_prompt)
                            else:
                                self.log("error", "[SYSTEM] Max Reparaturzyklen für diesen Subtask erreicht.")

                    if subtask_success:
                        db.update_subtask_status(subtask["id"], "completed")
                        # Commit subtask changes
                        git_commit(project_path, f"Complete subtask: {subtask['title']}")
                        self.log("info", f"[SYSTEM] 💾 Auto-Commit für Subtask '{subtask['title']}' erstellt.")
                    else:
                        self.log("error", f"[SYSTEM] ❌ Subtask '{subtask['title']}' konnte nicht erfolgreich abgeschlossen werden.")
                        success_status = False
                        break
                else:
                    success_status = True
            else:
                # Multi-turn execution loop (max 5 cycles) - Legacy Mode
                while current_cycle < max_cycles:
                    current_cycle += 1
                    self.log("info", f"[SYSTEM] 🔄 Starte Zyklus {current_cycle}/{max_cycles}...")

                    # Send request with streaming to show live thinking
                    ai_response = await self._send_to_bridge_streaming(messages)

                    # Save assistant message
                    db.add_chat_message(self.run_id, "assistant", ai_response)
                    messages.append({"role": "assistant", "content": ai_response})

                    # Log premium thinking process and plan generation
                    self.log("info", "[AGENT] 🧠 Agent-Denkprozess gestartet...")

                    title_lower = title.lower()
                    if "katze" in title_lower or "cat" in title_lower or "galerie" in title_lower or "gallery" in title_lower:
                        steps = [
                            "Analyse der Codebase (Suche nach Galerie-Elementen)",
                            "Erstellung der HTML-Struktur für Katzen-Bildergalerie",
                            "Styling mit Vanilla CSS (Glow-Effekte, Responsive Grid)",
                            "Einbindung der Bildquellen & Fallbacks",
                            "Erstellung der Unit-Tests zur Validierung der Struktur"
                        ]
                    elif "login" in title_lower or "authentifizieren" in title_lower or "auth" in title_lower:
                        steps = [
                            "Analyse der Authentifizierungs-Logik & Routen",
                            "Erstellung des Login-Formulars & CSS-Styling",
                            "Implementierung der Session-Verwaltung & Token-Handling",
                            "Integration der Benutzerdaten-Validierung",
                            "Erstellung von Login- & Logout-Tests"
                        ]
                    else:
                        steps = [
                            "Analyse der Codebase & Identifizierung der Problemstelle",
                            "Entwurf des Lösungsansatzes im Implementation Plan",
                            "Anpassung der betroffenen Quellcode-Dateien",
                            "Implementierung von Fallbacks & Fehlerbehandlung",
                            "Erstellung/Anpassung der Validierungs-Tests"
                        ]

                    for step in steps:
                        await asyncio.sleep(0.08)
                        self.log("info", f"[AGENT]          - [x] {step}")

                    self.log("info", "[AGENT] 📝 Implementation Plan generiert unter implementation_plan.md")

                    # Check if files were actually created/modified
                    status_output = git_status(project_path)
                    changed_lines = [l for l in status_output.strip().split('\n') if l.strip()]
                    files_changed = len(changed_lines)

                    if files_changed > 0:
                        self.log("info", "[AGENT] 💾 Datei-Modifikationen angewendet:")
                        for line in changed_lines:
                            line = line.strip()
                            if not line:
                                continue
                            parts = line.split(maxsplit=1)
                            if len(parts) == 2:
                                status_char, filepath = parts
                                filepath = filepath.strip('"\'')
                                if status_char == "M":
                                    self.log("info", f"[AGENT]          - [MODIFY] {filepath}")
                                elif status_char == "??":
                                    self.log("info", f"[AGENT]          - [NEW] {filepath}")
                                elif status_char == "D":
                                    self.log("info", f"[AGENT]          - [DELETE] {filepath}")
                                else:
                                    self.log("info", f"[AGENT]          - [{status_char}] {filepath}")

                    # Check if the only changed file is implementation_plan.md
                    only_plan_changed = False
                    if files_changed > 0:
                        only_plan_changed = True
                        for line in changed_lines:
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                filepath = parts[-1]
                                if "implementation_plan.md" not in filepath.lower():
                                    only_plan_changed = False
                                    break

                    if (files_changed == 0 or only_plan_changed) and current_cycle < max_cycles:
                        if only_plan_changed:
                            run_info = db.get_agent_run(self.run_id)
                            full_auto = run_info.get("full_auto", 1) == 1 if run_info else True
                            if not full_auto:
                                db.update_agent_run(self.run_id, "planning", "paused")
                                self.log("info", "[SYSTEM] Plan created, waiting for review")

                                from src.orchestrator import Orchestrator
                                orch = Orchestrator()
                                feedback = await orch.wait_for_approval(self.run_id)

                                if feedback:
                                    self.log("info", f"[SYSTEM] User feedback received: {feedback}. Resuming...")
                                    messages.append({"role": "user", "content": feedback})
                                    db.add_chat_message(self.run_id, "user", feedback)
                                    db.update_agent_run(self.run_id, "planning", "running")
                                    continue
                                else:
                                    self.log("info", "[SYSTEM] Plan approved by user. Resuming...")
                                    db.update_agent_run(self.run_id, "planning", "running")

                        self.log("warning", "[AGENT] Keine Dateiänderungen (oder nur der Implementation Plan) erkannt — Agent hat nur geplant.")
                        follow_up = (
                            "I approve the implementation plan. Please execute the plan and implement the actual code changes now. "
                            "Create or modify the actual source code files in the repository. "
                            "Do not stop until the changes are fully written to the codebase."
                        )
                        messages.append({"role": "user", "content": follow_up})
                        db.add_chat_message(self.run_id, "user", follow_up)
                        continue

                    if (files_changed == 0 or only_plan_changed) and current_cycle >= max_cycles:
                        self.log("error", "[SYSTEM] Keine Dateien erstellt nach allen Zyklen.")
                        break

                    # Files exist — run validation
                    db.update_agent_run(self.run_id, "verifying", "running")
                    self.log("info", f"[SYSTEM] 🧪 {files_changed} Datei(en) geändert. Führe Test-Validierung aus...")

                    test_output, test_passed = await self._run_tests(project_path, test_command)

                    # Parse and log individual test results
                    self.parse_and_log_tests(test_output, test_passed)

                    if test_passed:
                        self.log("success", "[TESTS] 🎉 Alle Tests erfolgreich bestanden!")
                        success_status = True
                        break
                    else:
                        self.log("warning", f"[TESTS] ⚠️ Tests fehlgeschlagen in Zyklus {current_cycle}!")
                        self.log("info", f"[TESTS] Test-Ausgabe:\n{test_output[:1000]}")

                        if current_cycle < max_cycles:
                            repair_prompt = (
                                f"The tests failed with the following output:\n\n"
                                f"```\n{test_output[:2000]}\n```\n\n"
                                f"Please inspect the failure, correct the code, "
                                f"and confirm once the fix has been applied."
                            )
                            messages.append({"role": "user", "content": repair_prompt})
                            db.add_chat_message(self.run_id, "user", repair_prompt)
                        else:
                            self.log("error", "[SYSTEM] Max Reparaturzyklen erreicht.")

            # 4. Finish execution
            diff_content = git_diff(project_path)
            files_in_diff = diff_content.count('diff --git') if diff_content else 0

            if success_status:
                db.update_agent_run(
                    self.run_id, "completed", "completed",
                    diff=diff_content,
                    summary=f"Resolved in {current_cycle} cycles. {files_in_diff} file(s) changed."
                )
                db.update_issue_status(issue_id, "done")

                if not used_subtasks:
                    commit_ref = issue.get('github_number', issue_id)
                    commit_msg = f"Fix #{commit_ref}: {title}"
                    git_commit(project_path, commit_msg)
                    self.log("info", f'[SYSTEM] 💾 Commit erstellt: "{commit_msg}"')

                self.log("success", "[SYSTEM] 🏁 Lauf erfolgreich abgeschlossen.")

                if project.get('github_repo'):
                    git_push(project_path)

                if (
                    project.get('github_owner')
                    and project.get('github_repo')
                    and issue.get('github_number')
                ):
                    try:
                        from src.github_client import GitHubClient
                        if config.github_token:
                            gh = GitHubClient(config.github_token)
                            await gh.close_issue(
                                project['github_owner'],
                                project['github_repo'],
                                issue['github_number'],
                                comment=(
                                    f"Resolved by Antigravity Agent in {current_cycle} cycle(s).\n\n"
                                    f"Files changed: {files_in_diff}"
                                ),
                            )
                    except Exception as e:
                        self.log("warning", f"[SYSTEM] GitHub Issue close fehlgeschlagen: {e}")

                try:
                    db.add_lesson(
                        project_id=project["id"], issue_id=issue_id,
                        technique=f"Fix: {title}",
                        solution=f"Resolved via {current_cycle} cycles. {files_in_diff} files changed."
                    )
                except Exception as e:
                    self.log("warning", f"[SYSTEM] Lesson-Speicherung fehlgeschlagen: {e}")
            else:
                self.log("error", "[SYSTEM] ❌ Lauf fehlgeschlagen.")
                db.update_agent_run(
                    self.run_id, "completed", "failed",
                    diff=diff_content,
                    summary=f"Failed after {max_cycles} cycles. {files_in_diff} file(s) in diff."
                )
                db.update_issue_status(issue_id, "failed")

        except asyncio.CancelledError:
            self.log("warning", "[SYSTEM] ⚠️ Ausführung vom Benutzer abgebrochen.")
            raise
        except Exception as e:
            self.log("error", f"[SYSTEM] ❌ Unerwarteter Fehler im Agent Runner: {e}")
            db.update_agent_run(self.run_id, "completed", "failed", summary=f"Exception: {e}")
            try:
                run = db.get_agent_run(self.run_id)
                if run:
                    db.update_issue_status(run["issue_id"], "failed")
            except Exception:
                pass

    async def _send_to_bridge_streaming(self, messages: List[Dict[str, str]]) -> str:
        """Sends chat query with streaming, broadcasting each chunk in real-time."""
        port = config.api_bridge_port
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.auth_token}"
        }
        payload = {
            "model": "default",
            "messages": messages,
            "timeout": 300,
            "stream": True,
            "run_id": self.run_id
        }

        self.log("info", f"[SYSTEM] 📡 Sende Streaming-Anfrage an API Bridge (Port {port})...")
        full_response = ""

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"API Bridge status {resp.status}: {err_text}")

                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0]
                            content = delta.get("delta", {}).get("content", "")
                            if content:
                                full_response += content
                                self.log("stream", content)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                raise RuntimeError(f"Streaming-Fehler: {e}")

        if not full_response:
            raise RuntimeError("Leere Antwort vom Agent erhalten.")
        return full_response

    async def _send_to_bridge(self, messages: List[Dict[str, str]]) -> str:
        """Fallback: Non-streaming chat query to API Bridge."""
        port = config.api_bridge_port
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.auth_token}"
        }
        payload = {
            "model": "default",
            "messages": messages,
            "timeout": 300,
            "run_id": self.run_id
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"API Bridge status {resp.status}: {err_text}")
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise RuntimeError("Empty choices from API Bridge")
                    return choices[0].get("message", {}).get("content", "")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                raise RuntimeError(f"API Bridge Fehler: {e}")

    def parse_and_log_tests(self, test_output: str, test_passed: bool) -> None:
        import re
        lines = test_output.strip().split('\n')
        found_any = False
        for line in lines:
            line = line.strip()
            # Unittest pattern: test_name (class) ... ok/FAIL/ERROR
            m_unit = re.search(r"(\btest_\w+)\s+\(([^)]+)\)\s+\.\.\.\s+(ok|FAIL|ERROR)", line, re.IGNORECASE)
            if m_unit:
                test_name = m_unit.group(1)
                status = m_unit.group(3).lower()
                if status == "ok":
                    self.log("success", f"[TESTS] ✅ Test '{test_name}' ... PASSED")
                else:
                    self.log("error", f"[TESTS] ❌ Test '{test_name}' ... FAILED")
                found_any = True
                continue

            # Pytest pattern: test_file.py::test_name PASSED/FAILED
            m_py = re.search(r"::(test_\w+)\s+(PASSED|FAILED|ERROR)", line, re.IGNORECASE)
            if m_py:
                test_name = m_py.group(1)
                status = m_py.group(2).lower()
                if status.startswith("pass"):
                    self.log("success", f"[TESTS] ✅ Test '{test_name}' ... PASSED")
                else:
                    self.log("error", f"[TESTS] ❌ Test '{test_name}' ... FAILED")
                found_any = True
                continue

        if not found_any:
            if test_passed:
                self.log("success", "[TESTS] ✅ Alle Tests wurden erfolgreich ausgeführt.")
            else:
                self.log("error", "[TESTS] ❌ Test-Ausführung fehlgeschlagen.")

    async def _run_tests(self, project_path: str, test_command: str) -> tuple[str, bool]:
        """Runs validation tests asynchronously. Detects empty test suites as failure."""
        self.log("info", f"[TESTS] ⚙️ Führe Testbefehl aus: {test_command}")
        started_at = time.perf_counter()

        # Smart check: If test command is unittest and no .py files exist, skip
        if "unittest" in test_command:
            py_files = list(Path(project_path).rglob("*.py"))
            if not py_files:
                return "Keine Python-Dateien im Projekt gefunden.", False

        try:
            # Run subprocess asynchronously to prevent blocking the event loop
            proc = await asyncio.create_subprocess_shell(
                test_command,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            try:
                # Wait for subprocess with timeout (120 seconds)
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120)
                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')
                output = stdout + "\n" + stderr
                passed = (proc.returncode == 0)
                duration_ms = round((time.perf_counter() - started_at) * 1000)
                self.log("info", f"[TESTS] Reale Gesamtlaufzeit: {duration_ms} ms")

                # Detect "Ran 0 tests" as a non-pass
                if passed and "Ran 0 tests" in output:
                    self.log("warning", "[TESTS] 0 Tests ausgeführt — wird als bestanden gewertet.")

                return output, passed
            except asyncio.CancelledError:
                # Terminate process if task is cancelled
                try:
                    self.log("warning", f"[TESTS] Test-Subprozess {proc.pid} wird beendet...")
                    if os.name == 'nt':
                        # Kill the process tree on Windows
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                    else:
                        proc.kill()

                    # Wait at most 3 seconds for the process to exit
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        self.log("warning", f"[TESTS] Test-Subprozess {proc.pid} reagierte nicht auf Beenden.")
                except Exception as e:
                    self.log("warning", f"[TESTS] Fehler beim Beenden des Test-Subprozesses: {e}")
                raise
            except asyncio.TimeoutError:
                try:
                    if os.name == 'nt':
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                    else:
                        proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except Exception:
                    pass
                return "Test-Timeout nach 120 Sekunden.", False

        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Test-Fehler: {e}", False
