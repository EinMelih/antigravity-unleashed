import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def run_cmd(args, cwd=None, timeout=30):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as exc:
        class FailedResult:
            returncode = 1
            stdout = ""
            stderr = str(exc)
        return FailedResult()


def run_git(args, cwd, timeout=30):
    return run_cmd(["git"] + args, cwd=cwd, timeout=timeout)


def determine_memory_file(config_dir: Path) -> Path:
    home_dir = str(Path.home())
    if "hermeswebui" in home_dir or "/etc/" in str(config_dir) or os.name == "posix":
        return config_dir / "MEMORY.server.md"
    return config_dir / "MEMORY.pc.md"


def ensure_gitignore(config_dir: Path) -> None:
    gitignore_path = config_dir / ".gitignore"
    required_entries = [
        "*.log",
        "*.tmp",
        "logs/global_ai_history*.jsonl",
        "*.conflict.*",
        "*.conflict",
        "antigravity-hub/config.json",
        "backups/",
        "*.key",
        "*.pem",
        ".env",
    ]
    existing_lines = []
    if gitignore_path.exists():
        try:
            existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing_lines = []
    existing_set = {line.strip() for line in existing_lines if line.strip()}
    updated = list(existing_lines)
    changed = False
    for entry in required_entries:
        if entry not in existing_set:
            updated.append(entry)
            changed = True
    if changed or not gitignore_path.exists():
        gitignore_path.write_text("\n".join(updated).strip() + "\n", encoding="utf-8")


def ensure_git_repo(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    ensure_gitignore(config_dir)
    if not (config_dir / ".git").exists():
        run_git(["init"], config_dir)
        run_git(["checkout", "-b", "main"], config_dir)
    username_check = run_git(["config", "user.name"], config_dir).stdout.strip()
    if not username_check:
        run_git(["config", "user.name", "Antigravity Agent"], config_dir)
        run_git(["config", "user.email", "antigravity@gemini.local"], config_dir)


def get_sync_settings_path(config_dir: Path) -> Path:
    return config_dir / "sync_settings.json"


def load_sync_settings(config_dir: Path) -> dict:
    settings_path = get_sync_settings_path(config_dir)
    defaults = {"auto_sync_minutes": 0, "updated_at": None}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_sync_settings(config_dir: Path, auto_sync_minutes: int) -> dict:
    config_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "auto_sync_minutes": max(0, int(auto_sync_minutes)),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    get_sync_settings_path(config_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def update_usage_stats(config_dir: Path) -> dict:
    """Aggregate local usage metrics into usage_stats.json so multi-PC sync preserves usage data."""
    import socket

    hostname = socket.gethostname().lower().replace(" ", "_")
    stats_file = config_dir / "usage_stats.json"
    existing = {"hosts": {}, "combined": {}}
    if stats_file.exists():
        try:
            loaded = json.loads(stats_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("hosts"), dict):
                existing = loaded
        except Exception:
            pass

    host_tokens = 0
    host_messages = 0
    models_used = {}
    sessions_seen = set()

    log_dir = config_dir / "logs"
    if log_dir.exists():
        for log_file in log_dir.glob("global_ai_history*.jsonl"):
            try:
                for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    tok = int(entry.get("tokens") or 0)
                    host_tokens += tok
                    host_messages += 1
                    sid = entry.get("session_id")
                    if isinstance(sid, str) and len(sid) == 36 and sid.count("-") == 4:
                        sessions_seen.add(sid)
                    model = str(entry.get("model") or "Unknown").strip()
                    if model:
                        models_used[model] = models_used.get(model, 0) + 1
            except Exception:
                pass

    ag_conv_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    conv_db_count = 0
    if ag_conv_dir.exists():
        try:
            conv_db_count = len(list(ag_conv_dir.glob("*.db")))
        except Exception:
            conv_db_count = 0

    skills_dir = config_dir / "skills"
    skills_count = 0
    if skills_dir.exists():
        try:
            skills_count = len([p for p in skills_dir.iterdir() if p.is_dir()])
        except Exception:
            skills_count = 0

    knowledge_dir = config_dir / "knowledge"
    knowledge_count = 0
    if knowledge_dir.exists():
        try:
            knowledge_count = len(list(knowledge_dir.glob("*.md")))
        except Exception:
            knowledge_count = 0

    existing["hosts"][hostname] = {
        "hostname": hostname,
        "logged_tokens": host_tokens,
        "logged_messages": host_messages,
        "logged_sessions": max(len(sessions_seen), conv_db_count),
        "conversation_dbs": conv_db_count,
        "skills_count": skills_count,
        "knowledge_notes": knowledge_count,
        "models": models_used,
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    total_tokens = 0
    total_messages = 0
    total_sessions = 0
    for h_data in existing["hosts"].values():
        if isinstance(h_data, dict):
            total_tokens += int(h_data.get("logged_tokens") or 0)
            total_messages += int(h_data.get("logged_messages") or 0)
            total_sessions += int(h_data.get("logged_sessions") or 0)

    existing["combined"] = {
        "total_tokens": total_tokens,
        "total_messages": total_messages,
        "total_sessions": total_sessions,
        "synced_hosts": list(existing["hosts"].keys()),
        "skills_count": skills_count,
        "knowledge_notes": knowledge_count,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        stats_file.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return existing


def get_status_info(config_dir: Path) -> dict:
    ensure_git_repo(config_dir)
    usage = update_usage_stats(config_dir)
    settings = load_sync_settings(config_dir)

    remote_res = run_git(["remote", "get-url", "origin"], config_dir)
    remote_url = remote_res.stdout.strip() if remote_res.returncode == 0 else ""

    branch_res = run_git(["branch", "--show-current"], config_dir)
    branch = branch_res.stdout.strip() or "main"

    status_lines = [
        line.strip()
        for line in run_git(["status", "--porcelain"], config_dir).stdout.splitlines()
        if line.strip()
    ]

    last_commit = ""
    log_res = run_git(["log", "-1", "--date=iso", "--format=%cd | %s"], config_dir)
    if log_res.returncode == 0 and log_res.stdout.strip():
        last_commit = log_res.stdout.strip()

    gh_ver = run_cmd(["gh", "--version"], cwd=config_dir, timeout=5)
    gh_installed = gh_ver.returncode == 0
    gh_authenticated = False
    gh_user = ""
    if gh_installed:
        auth_res = run_cmd(["gh", "api", "user", "--jq", ".login"], cwd=config_dir, timeout=8)
        if auth_res.returncode == 0 and auth_res.stdout.strip():
            gh_authenticated = True
            gh_user = auth_res.stdout.strip()
        else:
            status_auth = run_cmd(["gh", "auth", "status"], cwd=config_dir, timeout=8)
            gh_authenticated = status_auth.returncode == 0

    return {
        "status": "success",
        "config_dir": str(config_dir),
        "has_git": (config_dir / ".git").exists(),
        "remote_url": remote_url,
        "branch": branch,
        "uncommitted_count": len(status_lines),
        "last_commit": last_commit,
        "gh_installed": gh_installed,
        "gh_authenticated": gh_authenticated,
        "gh_user": gh_user,
        "auto_sync_minutes": int(settings.get("auto_sync_minutes") or 0),
        "usage": usage.get("combined", {}),
    }


def log_conflict_in_memory(config_dir: Path, filepath: Path, conflict_file: Path) -> None:
    target_path = determine_memory_file(config_dir)
    if not target_path.exists():
        target_path.write_text("# System Memory\n\n## Unresolved Conflicts\n", encoding="utf-8")

    try:
        content = target_path.read_text(encoding="utf-8")
    except OSError:
        content = "# System Memory\n\n## Unresolved Conflicts\n"

    conflict_line = (
        f"\n- [CONFLICT] Conflict in {filepath.name} at "
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')}. Saved local copy as {conflict_file.name}."
    )

    if "## Unresolved Conflicts" not in content:
        content += "\n\n## Unresolved Conflicts"

    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "## Unresolved Conflicts" in line:
            lines.insert(idx + 1, conflict_line)
            break
    else:
        lines.append(conflict_line)

    try:
        target_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Logged conflict in {target_path.name}")
    except OSError as e:
        print(f"Failed to log conflict in {target_path.name}: {e}")

    compiler_path = config_dir / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        subprocess.run([sys.executable, "-X", "utf8", str(compiler_path)], cwd=config_dir, capture_output=True)


def resolve_merge_conflicts(config_dir: Path, remote_branch: str) -> None:
    print(f"Conflict detected during merge with {remote_branch}! Resolving automatically...")

    conflicted_files = run_git(["diff", "--name-only", "--diff-filter=U"], config_dir).stdout.splitlines()

    if not conflicted_files:
        # Merge failed before creating unmerged index entries (e.g., untracked file collision)
        run_git(["merge", "--abort"], config_dir)
        retry = run_git(
            [
                "merge",
                remote_branch,
                "--allow-unrelated-histories",
                "-X",
                "theirs",
                "--no-edit",
                "-m",
                f"Auto-merge {remote_branch} (prefer remote on unrelated history)",
            ],
            config_dir,
        )
        if retry.returncode == 0:
            return

    for f_path in conflicted_files:
        if not f_path.strip():
            continue

        full_path = config_dir / f_path
        ts = int(time.time())
        conflict_file = config_dir / f"{f_path}.conflict.{ts}"

        local_version = run_git(["show", f":2:{f_path}"], config_dir).stdout
        try:
            conflict_file.parent.mkdir(parents=True, exist_ok=True)
            conflict_file.write_text(local_version, encoding="utf-8")
            print(f"Saved local version of conflicted file as {conflict_file.name}")
        except Exception as e:
            print(f"Failed to write conflict file: {e}")

        remote_check = run_git(["show", f":3:{f_path}"], config_dir)
        if remote_check.returncode == 0:
            run_git(["checkout", "--theirs", "--", f_path], config_dir)
            run_git(["add", f_path], config_dir)
        else:
            run_git(["rm", "--", f_path], config_dir)

        log_conflict_in_memory(config_dir, full_path, conflict_file)

    run_git(
        ["commit", "-m", f"Auto-resolved merge conflicts with {remote_branch} (backup files created)"],
        config_dir,
    )


def normalize_remote_target(target: str, config_dir: Path) -> str:
    cleaned = (target or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://") or cleaned.startswith("git@") or cleaned.startswith("ssh://") or "://" in cleaned or cleaned.endswith(".git") or os.path.exists(cleaned):
        return cleaned
    if "/" in cleaned and " " not in cleaned:
        return f"https://github.com/{cleaned}.git"
    # Bare repo name -> resolve GitHub username via gh
    auth_res = run_cmd(["gh", "api", "user", "--jq", ".login"], cwd=config_dir, timeout=8)
    if auth_res.returncode == 0 and auth_res.stdout.strip():
        return f"https://github.com/{auth_res.stdout.strip()}/{cleaned}.git"
    return cleaned


def setup_or_create_remote(config_dir: Path, target: str, create_private: bool = False) -> dict:
    ensure_git_repo(config_dir)
    update_usage_stats(config_dir)

    repo_name = (target or "antigravity-config").strip()

    if create_private:
        gh_user_res = run_cmd(["gh", "api", "user", "--jq", ".login"], cwd=config_dir, timeout=8)
        if gh_user_res.returncode != 0 or not gh_user_res.stdout.strip():
            return {
                "status": "error",
                "message": "GitHub CLI (gh) ist nicht angemeldet. Bitte zuerst auf 'GitHub Login' klicken.",
            }
        gh_user = gh_user_res.stdout.strip()
        full_slug = repo_name if "/" in repo_name else f"{gh_user}/{repo_name}"

        view_res = run_cmd(["gh", "repo", "view", full_slug, "--json", "url"], cwd=config_dir, timeout=10)
        if view_res.returncode != 0:
            create_res = run_cmd(["gh", "repo", "create", full_slug, "--private"], cwd=config_dir, timeout=20)
            if create_res.returncode != 0:
                return {
                    "status": "error",
                    "message": f"Konnte privates GitHub-Repo '{full_slug}' nicht erstellen: {create_res.stderr.strip() or create_res.stdout.strip()}",
                }
        remote_url = f"https://github.com/{full_slug}.git"
    else:
        remote_url = normalize_remote_target(repo_name, config_dir)
        if not remote_url:
            return {"status": "error", "message": "Bitte eine gültige GitHub-Repo-URL oder 'user/repo' angeben."}

    remotes = run_git(["remote"], config_dir).stdout.splitlines()
    if "origin" in remotes:
        set_res = run_git(["remote", "set-url", "origin", remote_url], config_dir)
    else:
        set_res = run_git(["remote", "add", "origin", remote_url], config_dir)

    if set_res.returncode != 0:
        return {"status": "error", "message": f"Fehler beim Setzen von origin: {set_res.stderr.strip()}"}

    # Run a full sync so local files are committed and pushed
    sync_result = perform_sync(config_dir, user_msg="chore(config): initialize cloud config sync")
    return {
        "status": sync_result.get("status", "success"),
        "remote_url": remote_url,
        "message": sync_result.get("message", "Privates Config-Repo erfolgreich verbunden und synchronisiert."),
        "info": get_status_info(config_dir),
    }


def import_from_remote(config_dir: Path, remote_target: str = "") -> dict:
    """Safely import/restore ~/.gemini/config from an existing remote repository onto a new or existing PC."""
    ensure_git_repo(config_dir)

    if remote_target and remote_target.strip():
        remote_url = normalize_remote_target(remote_target, config_dir)
        remotes = run_git(["remote"], config_dir).stdout.splitlines()
        if "origin" in remotes:
            run_git(["remote", "set-url", "origin", remote_url], config_dir)
        else:
            run_git(["remote", "add", "origin", remote_url], config_dir)
    else:
        remote_res = run_git(["remote", "get-url", "origin"], config_dir)
        remote_url = remote_res.stdout.strip() if remote_res.returncode == 0 else ""

    if not remote_url:
        return {
            "status": "error",
            "message": "Kein Remote-Repository angegeben oder als 'origin' konfiguriert.",
        }

    fetch_res = run_git(["fetch", "origin"], config_dir, timeout=45)
    if fetch_res.returncode != 0:
        return {
            "status": "error",
            "message": f"Konnte nicht vom Remote '{remote_url}' laden (git fetch fehlgeschlagen): {fetch_res.stderr.strip()}",
        }

    # Determine remote branch (main or master)
    remote_branch = "origin/main"
    verify_main = run_git(["rev-parse", "--verify", "origin/main"], config_dir)
    if verify_main.returncode != 0:
        verify_master = run_git(["rev-parse", "--verify", "origin/master"], config_dir)
        if verify_master.returncode == 0:
            remote_branch = "origin/master"
        else:
            return {
                "status": "error",
                "message": "Das Remote-Repository ist noch leer (kein 'main' oder 'master' Branch gefunden).",
            }

    # Backup any modified/untracked local config files before importing
    backup_dir = config_dir / "backups" / f"pre-import-{int(time.time())}"
    backed_up_files = []
    for candidate in ["MEMORY.pc.md", "MEMORY.md", "USER.pc.md", "USER.md", "AGENTS.md", "usage_stats.json"]:
        c_path = config_dir / candidate
        if c_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c_path, backup_dir / candidate)
            backed_up_files.append(candidate)

    # Commit any local state first so working tree is clean before merge/checkout
    status_output = run_git(["status", "--porcelain"], config_dir).stdout.strip()
    if status_output:
        run_git(["add", "."], config_dir)
        run_git(["commit", "-m", "chore(config): snapshot local state before remote import"], config_dir)

    has_head = run_git(["rev-parse", "--verify", "HEAD"], config_dir).returncode == 0
    if not has_head:
        checkout_res = run_git(["checkout", "-B", "main", remote_branch], config_dir)
        if checkout_res.returncode != 0:
            run_git(["reset", "--hard", remote_branch], config_dir)
    else:
        merge_res = run_git(
            [
                "merge",
                remote_branch,
                "--allow-unrelated-histories",
                "-X",
                "theirs",
                "--no-edit",
                "-m",
                f"Import config from {remote_branch}",
            ],
            config_dir,
        )
        if merge_res.returncode != 0:
            resolve_merge_conflicts(config_dir, remote_branch)

    # Re-compile MEMORY.md and USER.md and refresh usage_stats.json
    compiler_path = config_dir / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        subprocess.run([sys.executable, "-X", "utf8", str(compiler_path)], cwd=config_dir, capture_output=True)

    # Preserve any host entries from pre-import local usage_stats.json
    backup_usage_path = backup_dir / "usage_stats.json"
    live_usage_path = config_dir / "usage_stats.json"
    if backup_usage_path.exists() and live_usage_path.exists():
        try:
            old_stats = json.loads(backup_usage_path.read_text(encoding="utf-8"))
            new_stats = json.loads(live_usage_path.read_text(encoding="utf-8"))
            if isinstance(old_stats.get("hosts"), dict) and isinstance(new_stats.get("hosts"), dict):
                for h_key, h_val in old_stats["hosts"].items():
                    if h_key not in new_stats["hosts"]:
                        new_stats["hosts"][h_key] = h_val
                live_usage_path.write_text(json.dumps(new_stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    usage = update_usage_stats(config_dir)

    return {
        "status": "success",
        "remote_url": remote_url,
        "remote_branch": remote_branch,
        "backed_up_files": backed_up_files,
        "backup_dir": str(backup_dir) if backed_up_files else "",
        "usage": usage.get("combined", {}),
        "message": f"Konfiguration, Memory, Skills und Nutzungsdaten erfolgreich aus '{remote_url}' importiert!",
        "info": get_status_info(config_dir),
    }


def perform_sync(config_dir: Path, user_msg: str | None = None) -> dict:
    ensure_git_repo(config_dir)

    compiler_path = config_dir / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        print("Compiling dynamic memory files...")
        result = subprocess.run([sys.executable, "-X", "utf8", str(compiler_path)], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR: Memory compilation failed!")
            print(result.stderr)
            return {"status": "error", "message": f"Memory compilation failed: {result.stderr.strip()}"}
        elif result.stdout.strip():
            print(result.stdout.strip())

    # Always update usage_stats.json so usage metrics are persisted in the config repo
    update_usage_stats(config_dir)

    status_output = run_git(["status", "--porcelain"], config_dir).stdout.strip()
    if status_output:
        print("Grouping local changes by category...")

        memory_files = []
        knowledge_files = []
        code_files = []
        chore_files = []

        for line in status_output.splitlines():
            if not line.strip():
                continue

            parts = line[3:].strip()
            if " -> " in parts:
                parts = parts.split(" -> ")[-1].strip()
            if parts.startswith('"') and parts.endswith('"'):
                parts = parts[1:-1]

            filepath = Path(parts)
            filepath_str = parts.replace("\\", "/")

            if filepath.name in [
                "MEMORY.pc.md",
                "MEMORY.server.md",
                "MEMORY.md",
                "USER.pc.md",
                "USER.server.md",
                "USER.md",
                "AGENTS.md",
                "usage_stats.json",
            ]:
                memory_files.append(filepath_str)
            elif filepath_str.startswith("knowledge/"):
                knowledge_files.append(filepath_str)
            elif (
                filepath_str.startswith("skills/")
                or filepath_str.startswith("plugins/")
                or filepath_str.startswith("scripts/")
            ):
                if filepath.name in ["compile_memory.py", "sync_config.py"]:
                    chore_files.append(filepath_str)
                else:
                    code_files.append(filepath_str)
            else:
                chore_files.append(filepath_str)

        def commit_group(files, default_msg, category):
            if not files:
                return
            print(f"Committing {category} updates...")
            for f in files:
                run_git(["add", "--", f], config_dir)
            commit_res = run_git(["commit", "-m", default_msg], config_dir)
            if commit_res.returncode != 0:
                print(f"Commit failed or nothing to commit for {category}: {commit_res.stderr.strip()}")

        commit_group(
            memory_files,
            "docs(memory): auto-update agent memory, usage stats, and preferences",
            "memory",
        )
        commit_group(
            knowledge_files,
            "docs(knowledge): auto-update durable knowledge vault documents",
            "knowledge",
        )

        if code_files:
            code_msg = user_msg
            if not code_msg or not code_msg.strip():
                code_msg = "feat(skills): update custom agent skills and tools"
            else:
                if not any(
                    code_msg.startswith(prefix)
                    for prefix in ["feat(", "fix(", "docs(", "refactor(", "style(", "chore(", "test("]
                ):
                    code_msg = f"feat(skills): {code_msg}"
            commit_group(code_files, code_msg, "code")

        commit_group(
            chore_files,
            "chore(config): auto-update remaining configuration and scripts",
            "chore",
        )

    remotes = run_git(["remote"], config_dir).stdout.splitlines()
    if not remotes:
        print("No remote configured. Local-only commits stored.")
        return {
            "status": "local_only",
            "message": "Lokaler Commit gespeichert (noch kein Cloud-Remote konfiguriert).",
        }

    for r in remotes:
        print(f"Fetching from remote '{r}'...")
        run_git(["fetch", r], config_dir, timeout=45)

    if "origin" in remotes:
        has_origin_main = run_git(["rev-parse", "--verify", "origin/main"], config_dir).returncode == 0
        if has_origin_main:
            print("Merging changes from origin...")
            merge_origin = run_git(
                [
                    "merge",
                    "origin/main",
                    "--allow-unrelated-histories",
                    "--no-edit",
                    "-m",
                    f"Auto-merge origin: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                ],
                config_dir,
            )
            if merge_origin.returncode != 0:
                resolve_merge_conflicts(config_dir, "origin/main")

    if "server" in remotes:
        has_server_main = run_git(["rev-parse", "--verify", "server/main"], config_dir).returncode == 0
        if has_server_main:
            print("Merging changes from server...")
            merge_server = run_git(
                [
                    "merge",
                    "server/main",
                    "--allow-unrelated-histories",
                    "--no-edit",
                    "-m",
                    f"Auto-merge server: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                ],
                config_dir,
            )
            if merge_server.returncode != 0:
                resolve_merge_conflicts(config_dir, "server/main")

    push_errors = []
    if "origin" in remotes:
        print("Pushing to origin...")
        push_origin = run_git(["push", "-u", "origin", "main"], config_dir, timeout=45)
        if push_origin.returncode == 0:
            print("Successfully pushed to origin.")
        else:
            err_txt = push_origin.stderr.strip()
            print(f"Failed to push to origin:\n{err_txt}")
            push_errors.append(f"origin: {err_txt}")

    if "server" in remotes:
        print("Pushing to server...")
        push_server = run_git(["push", "-u", "server", "main"], config_dir, timeout=45)
        if push_server.returncode == 0:
            print("Successfully pushed to server.")
        else:
            err_txt = push_server.stderr.strip()
            print(f"Failed to push to server:\n{err_txt}")
            push_errors.append(f"server: {err_txt}")

    print("Sync process completed.")
    if push_errors:
        return {"status": "warning", "message": "Lokal committet, aber Push-Warnung: " + "; ".join(push_errors)}
    return {"status": "success", "message": "Config, Memory & Nutzungsdaten erfolgreich synchronisiert."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--msg", help="Optional commit message for code/skills changes")
    parser.add_argument("--config-dir", help="Override ~/.gemini/config directory (for testing or custom profiles)")
    parser.add_argument("--status-json", action="store_true", help="Output JSON status info for ~/.gemini/config")
    parser.add_argument("--setup-remote", help="Set up or create origin remote repository (URL or repo name)")
    parser.add_argument("--create-private", action="store_true", help="Create private GitHub repo via gh CLI")
    parser.add_argument("--import-remote", nargs="?", const="", help="Import/pull config from origin or specified URL")
    parser.add_argument("--set-auto-sync", type=int, help="Set auto-sync interval in minutes (0 = disabled)")
    args = parser.parse_args()

    if args.config_dir:
        config_dir = Path(args.config_dir).resolve()
    else:
        config_dir = Path(os.path.expanduser("~/.gemini/config")).resolve()

    if args.set_auto_sync is not None:
        save_sync_settings(config_dir, args.set_auto_sync)
        print(json.dumps(get_status_info(config_dir), ensure_ascii=False))
        return

    if args.status_json:
        print(json.dumps(get_status_info(config_dir), ensure_ascii=False))
        return

    if args.setup_remote is not None:
        res = setup_or_create_remote(config_dir, args.setup_remote, create_private=args.create_private)
        print(json.dumps(res, ensure_ascii=False))
        return

    if args.import_remote is not None:
        res = import_from_remote(config_dir, args.import_remote)
        print(json.dumps(res, ensure_ascii=False))
        return

    perform_sync(config_dir, user_msg=args.msg)


if __name__ == "__main__":
    main()
