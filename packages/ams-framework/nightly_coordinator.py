import os
import sys
import re
import json
import subprocess
import time
import urllib.request
import urllib.error
import sqlite3
from pathlib import Path
from datetime import datetime

def get_ls_info():
    main_log = os.path.join(os.environ['APPDATA'], 'Antigravity', 'logs', 'main.log')
    if not os.path.exists(main_log):
        print(f"Main log not found at {main_log}")
        return None, None
    try:
        with open(main_log, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # find last Spawning: ... --csrf_token <token>
        csrf_matches = re.findall(r'--csrf_token\s+([a-f0-9-]+)', content)
        # find last URL: https://127.0.0.1:<port>/
        port_matches = re.findall(r'https://127.0.0.1:(\d+)/', content)
        
        csrf = csrf_matches[-1] if csrf_matches else None
        port = int(port_matches[-1]) if port_matches else None
        return port, csrf
    except Exception as e:
        print("Error parsing main.log:", e)
        return None, None

def fetch_issues(repo=None, label="antigravity-run"):
    if not repo:
        repo = os.environ.get("ANTIGRAVITY_TARGET_REPO", "owner/repo")
    cmd = ["gh", "issue", "list", "--repo", repo, "--label", label, "--json", "number,title,body"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception as e:
        print(f"Failed to fetch issues from repo {repo} with label {label}: {e}")
        return []

def check_loop(convo_id):
    db_path = os.path.join(os.environ['USERPROFILE'], '.gemini', 'antigravity', 'conversations', f"{convo_id}.db")
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT step_payload, metadata FROM steps ORDER BY idx DESC LIMIT 8;")
        rows = c.fetchall()
        conn.close()
        
        if len(rows) >= 4:
            # Check if the last 4 steps have identical payloads (same command or inputs)
            payloads = [str(r[0]) for r in rows[:4]]
            if len(set(payloads)) == 1 and payloads[0].strip() != "" and payloads[0] != "None":
                return True
        return False
    except Exception as e:
        print(f"Error checking loop for {convo_id}: {e}")
        return False

def cancel_convo(convo_id, port, csrf):
    print(f"Cancelling conversation {convo_id} due to detected loop...")
    convo_pb = os.path.join(os.environ['USERPROFILE'], '.gemini', 'antigravity', 'conversations', f"{convo_id}.pb")
    convo_db = os.path.join(os.environ['USERPROFILE'], '.gemini', 'antigravity', 'conversations', f"{convo_id}.db")
    
    # Write dummy .pb file
    try:
        with open(convo_pb, 'w') as f:
            f.write('')
    except Exception as e:
        print("Failed to write dummy pb:", e)
        
    # Construct grpc-web body
    uuid_bytes = convo_id.encode('utf-8')
    length = 2 + len(uuid_bytes)
    body = bytearray(5 + 2 + len(uuid_bytes))
    body[0] = 0
    body[1] = (length >> 24) & 0xff
    body[2] = (length >> 16) & 0xff
    body[3] = (length >> 8) & 0xff
    body[4] = length & 0xff
    body[5] = 0x0a
    body[6] = len(uuid_bytes)
    body[7:] = uuid_bytes
    
    url = f"http://127.0.0.1:{port + 1}/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'content-type': 'application/grpc-web+proto',
            'x-grpc-web': '1',
            'x-codeium-csrf-token': csrf
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            print(f"gRPC delete request sent for {convo_id}. Status: {res.status}")
    except Exception as e:
        print(f"gRPC delete request failed for {convo_id}: {e}")
        
    # Clean files
    for suffix in ['', '-shm', '-wal']:
        db_file = convo_db + suffix
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
    if os.path.exists(convo_pb):
        try:
            os.remove(convo_pb)
        except Exception:
            pass

def is_run_completed(convo_id):
    db_path = os.path.join(os.environ['USERPROFILE'], '.gemini', 'antigravity', 'conversations', f"{convo_id}.db")
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT step_type, status FROM steps ORDER BY idx DESC LIMIT 1;")
        row = c.fetchone()
        conn.close()
        if row:
            step_type, status = row
            # If the last step is an agent response (15) and status is completed (3)
            if step_type == 15 and status == 3:
                return True
        return False
    except Exception as e:
        return False

def main():
    print("--- Nightly Autonomous Coding Coordinator ---")
    port, csrf = get_ls_info()
    if not port or not csrf:
        print("Error: Could not retrieve language server port or CSRF token from main.log.")
        sys.exit(1)
    
    print(f"Connected to language server on port {port} (gRPC port {port+1})")
    
    # 1. Fetch issues
    issues = fetch_issues()
    if not issues:
        print("No issues found with label 'antigravity-run'. Exiting.")
        sys.exit(0)
    
    print(f"Found {len(issues)} issues to process.")
    
    # Determine target repo and workspace directory
    repo = os.environ.get("ANTIGRAVITY_TARGET_REPO", "owner/repo")
    workspace_dir = os.environ.get("ANTIGRAVITY_WORKSPACE_DIR", os.getcwd())
    if not os.path.exists(workspace_dir):
        workspace_dir = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), '.gemini', 'config')
    
    runs = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create target directory for logs
    log_dir = Path.home() / ".gemini" / "antigravity" / "sidecar_data" / "nightly-autonomic-coding" / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    for issue in issues:
        num = issue['number']
        title = issue['title']
        body = issue.get('body') or ""
        print(f"\nProcessing Issue #{num}: '{title}'")
        
        # 2. Checkout new git branch in the target workspace
        branch_name = f"antigravity/issue-{num}"
        try:
            # Stash changes just in case
            subprocess.run(["git", "stash"], cwd=workspace_dir, capture_output=True)
            # Checkout master first
            subprocess.run(["git", "checkout", "master"], cwd=workspace_dir, capture_output=True)
            # Create and switch to new branch
            subprocess.run(["git", "checkout", "-b", branch_name], cwd=workspace_dir, capture_output=True)
            print(f"Switched to branch '{branch_name}' in {workspace_dir}")
        except Exception as e:
            print(f"Git checkout failed for branch {branch_name}: {e}")
            
        # 3. Spawn autonomous agent via agentapi
        prompt = (
            f"Bearbeite das GitHub Issue #{num}: {title}. "
            f"Beschreibung: {body} "
            f"Nimm die notwendigen Änderungen im Codebase-Verzeichnis vor, "
            f"verifiziere die Änderungen (führe Tests oder Builds aus, falls vorhanden), "
            f"committe die Änderungen lokal auf diesem Branch und erstelle einen Draft Pull Request auf GitHub "
            f"unter Verwendung des Befehls: 'gh pr create --draft --title \"feat: resolve issue #{num}\" --body \"Resolves #{num}\"'."
        )
        
        agentapi_path = os.path.join(os.environ['USERPROFILE'], '.gemini', 'antigravity', 'bin', 'agentapi.bat')
        cmd = [agentapi_path, "new-conversation", "--model=pro", prompt]
        
        print(f"Launching pro coding agent for issue #{num}...")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            convo_id = data['response']['newConversation']['conversationId']
            print(f"Spawned agent conversation ID: {convo_id}")
            
            runs.append({
                "issueNumber": num,
                "title": title,
                "conversationId": convo_id,
                "status": "Running",
                "branch": branch_name,
                "prUrl": "",
                "startTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": ""
            })
        except Exception as e:
            print(f"Failed to spawn agent for issue #{num}: {e}")
            runs.append({
                "issueNumber": num,
                "title": title,
                "conversationId": "",
                "status": "Failed to launch",
                "branch": branch_name,
                "prUrl": "",
                "startTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    # Save initial run list
    run_file_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    run_file_path = log_dir / run_file_name
    
    with open(run_file_path, 'w', encoding='utf-8') as f:
        json.dump({"date": timestamp, "runs": runs}, f, indent=2)

    # 4. Monitor active runs
    active_runs = [r for r in runs if r['status'] == "Running"]
    print(f"\nMonitoring {len(active_runs)} active runs...")
    
    while active_runs:
        time.sleep(15)
        for run in active_runs:
            convo_id = run['conversationId']
            num = run['issueNumber']
            
            # Check for loops
            if check_loop(convo_id):
                print(f"Loop detected in run for issue #{num} ({convo_id})! Terminating.")
                cancel_convo(convo_id, port, csrf)
                run['status'] = "Loop Detected"
                run['endTime'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                active_runs.remove(run)
                
                # Save updated list
                with open(run_file_path, 'w', encoding='utf-8') as f:
                    json.dump({"date": timestamp, "runs": runs}, f, indent=2)
                continue
                
            # Check for completion
            if is_run_completed(convo_id):
                print(f"Run for issue #{num} ({convo_id}) completed successfully.")
                run['status'] = "Success"
                run['endTime'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Try to extract the PR URL if a PR was created
                try:
                    pr_cmd = ["gh", "pr", "list", "--repo", repo, "--head", run['branch'], "--json", "url"]
                    pr_res = subprocess.run(pr_cmd, capture_output=True, text=True)
                    if pr_res.returncode == 0:
                        pr_data = json.loads(pr_res.stdout)
                        if pr_data:
                            run['prUrl'] = pr_data[0]['url']
                            print(f"Found PR URL: {run['prUrl']}")
                except Exception as e:
                    print("Failed to look up PR URL:", e)
                    
                active_runs.remove(run)
                
                # Save updated list
                with open(run_file_path, 'w', encoding='utf-8') as f:
                    json.dump({"date": timestamp, "runs": runs}, f, indent=2)
                continue
                
        # Optional: check if log files exist and write updates
        with open(run_file_path, 'w', encoding='utf-8') as f:
            json.dump({"date": timestamp, "runs": runs}, f, indent=2)
            
    print(f"\nAll nightly autonomic coding runs finished. Summary written to {run_file_path}")

if __name__ == "__main__":
    main()
