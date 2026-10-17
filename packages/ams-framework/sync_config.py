import subprocess
import os
import sys
import time
from pathlib import Path

def run_git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)

def determine_memory_file(config_dir):
    # Determine whether we run on server (Linux) or PC (Windows)
    home_dir = str(Path.home())
    if "hermeswebui" in home_dir or "/etc/" in str(config_dir) or os.name == 'posix':
        return config_dir / "MEMORY.server.md"
    return config_dir / "MEMORY.pc.md"

def log_conflict_in_memory(config_dir, filepath, conflict_file):
    target_path = determine_memory_file(config_dir)
    if not target_path.exists():
        target_path.write_text("# System Memory\n\n## Unresolved Conflicts\n", encoding="utf-8")
    
    try:
        content = target_path.read_text(encoding="utf-8")
    except OSError:
        content = "# System Memory\n\n## Unresolved Conflicts\n"
        
    conflict_line = f"\n- [CONFLICT] Conflict in {filepath.name} at {time.strftime('%Y-%m-%dT%H:%M:%SZ')}. Saved local copy as {conflict_file.name}."
    
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
    
    # Recompile the MEMORY.md
    compiler_path = config_dir / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        subprocess.run([sys.executable, "-X", "utf8", str(compiler_path)], cwd=config_dir, capture_output=True)

def resolve_merge_conflicts(config_dir, remote_branch):
    print(f"Conflict detected during merge with {remote_branch}! Resolving automatically...")
    
    # Only get REAL unmerged files (status 'U')
    conflicted_files = run_git(["diff", "--name-only", "--diff-filter=U"], config_dir).stdout.splitlines()
    
    for f_path in conflicted_files:
        if not f_path.strip():
            continue
        
        full_path = config_dir / f_path
        ts = int(time.time())
        conflict_file = config_dir / f"{f_path}.conflict.{ts}"
        
        # Save our local version (Stage 2 = ours) to the conflict backup file
        local_version = run_git(["show", f":2:{f_path}"], config_dir).stdout
        try:
            conflict_file.parent.mkdir(parents=True, exist_ok=True)
            conflict_file.write_text(local_version, encoding="utf-8")
            print(f"Saved local version of conflicted file as {conflict_file.name}")
        except Exception as e:
            print(f"Failed to write conflict file: {e}")
        
        # Overwrite active working copy with remote version (Stage 3 = theirs)
        # If the file was deleted on remote, Stage 3 does not exist -> delete locally
        remote_check = run_git(["show", f":3:{f_path}"], config_dir)
        if remote_check.returncode == 0:
            run_git(["checkout", "--theirs", "--", f_path], config_dir)
            run_git(["add", f_path], config_dir)
        else:
            run_git(["rm", "--", f_path], config_dir)
            
        log_conflict_in_memory(config_dir, full_path, conflict_file)
    
    # Finalize the merge commit after conflicts are resolved
    run_git(["commit", "-m", f"Auto-resolved merge conflicts with {remote_branch} (backup files created)"], config_dir)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--msg", help="Optional commit message for code/skills changes")
    args = parser.parse_args()
    user_msg = args.msg

    config_dir = Path(os.path.expanduser("~/.gemini/config")).resolve()
    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)

    gitignore_path = config_dir / ".gitignore"
    if not gitignore_path.exists():
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("*.log\n*.tmp\nlogs/global_ai_history.jsonl\n*.conflict.*\n*.conflict\n")

    if not (config_dir / ".git").exists():
        print("Initializing Git repo...")
        run_git(["init"], config_dir)
        run_git(["checkout", "-b", "main"], config_dir)

    # Set default Git user if not already set (prevents commit errors on clean environments)
    username_check = run_git(["config", "user.name"], config_dir).stdout.strip()
    if not username_check:
        run_git(["config", "user.name", "Antigravity Agent"], config_dir)
        run_git(["config", "user.email", "antigravity@gemini.local"], config_dir)

    # Compile memory and user files before checking status
    compiler_path = config_dir / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        print("Compiling dynamic memory files...")
        result = subprocess.run([sys.executable, "-X", "utf8", str(compiler_path)], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR: Memory compilation failed!")
            print(result.stderr)
            sys.exit(result.returncode)
        else:
            if result.stdout.strip():
                print(result.stdout.strip())

    # Add and commit local changes by category
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
            
            # Extract file path
            parts = line[3:].strip()
            if parts.startswith('"') and parts.endswith('"'):
                parts = parts[1:-1]
                
            filepath = Path(parts)
            filepath_str = parts.replace("\\", "/")
            
            # Classify
            if filepath.name in ["MEMORY.pc.md", "MEMORY.server.md", "MEMORY.md", "USER.pc.md", "USER.server.md", "USER.md", "AGENTS.md"]:
                memory_files.append(filepath_str)
            elif filepath_str.startswith("knowledge/"):
                knowledge_files.append(filepath_str)
            elif filepath_str.startswith("skills/") or filepath_str.startswith("plugins/") or filepath_str.startswith("scripts/"):
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
                run_git(["add", f], config_dir)
            commit_res = run_git(["commit", "-m", default_msg], config_dir)
            if commit_res.returncode != 0:
                print(f"Commit failed or nothing to commit for {category}: {commit_res.stderr.strip()}")
            
        # 1. Commit Memory
        commit_group(
            memory_files, 
            "docs(memory): auto-update agent memory, rules, and preferences", 
            "memory"
        )
        
        # 2. Commit Knowledge
        commit_group(
            knowledge_files, 
            "docs(knowledge): auto-update durable knowledge vault documents", 
            "knowledge"
        )
        
        # 3. Commit Code
        if code_files:
            code_msg = user_msg
            if not code_msg or not code_msg.strip():
                code_msg = "feat(skills): update custom agent skills and tools"
            else:
                if not any(code_msg.startswith(prefix) for prefix in ["feat(", "fix(", "docs(", "refactor(", "style(", "chore(", "test("]):
                    code_msg = f"feat(skills): {code_msg}"
            commit_group(code_files, code_msg, "code")
            
        # 4. Commit Chore
        commit_group(
            chore_files, 
            "chore(config): auto-update remaining configuration and scripts", 
            "chore"
        )

    remotes = run_git(["remote"], config_dir).stdout.splitlines()
    if not remotes:
        print("No remote configured. Local-only commits stored.")
        return

    # Fetch all remotes first to get latest updates
    for r in remotes:
        print(f"Fetching from remote '{r}'...")
        run_git(["fetch", r], config_dir)
    
    # Merge changes from origin first
    if "origin" in remotes:
        print("Merging changes from origin...")
        merge_origin = run_git(["merge", "origin/main", "--no-edit", "-m", f"Auto-merge origin: {time.strftime('%Y-%m-%d %H:%M:%S')}"], config_dir)
        if merge_origin.returncode != 0:
            resolve_merge_conflicts(config_dir, "origin/main")
            
    # Merge changes from server next (resolves divergence locally before pushing)
    if "server" in remotes:
        print("Merging changes from server...")
        merge_server = run_git(["merge", "server/main", "--no-edit", "-m", f"Auto-merge server: {time.strftime('%Y-%m-%d %H:%M:%S')}"], config_dir)
        if merge_server.returncode != 0:
            resolve_merge_conflicts(config_dir, "server/main")
        
    # Execute pushes only to configured remotes
    if "origin" in remotes:
        print("Pushing to origin...")
        push_origin = run_git(["push", "origin", "main"], config_dir)
        if push_origin.returncode == 0:
            print("Successfully pushed to origin.")
        else:
            print(f"Failed to push to origin:\n{push_origin.stderr}")

    if "server" in remotes:
        print("Pushing to server...")
        push_server = run_git(["push", "server", "main"], config_dir)
        if push_server.returncode == 0:
            print("Successfully pushed to server.")
        else:
            print(f"Failed to push to server:\n{push_server.stderr}")
            
    print("Sync process completed.")

if __name__ == "__main__":
    main()
