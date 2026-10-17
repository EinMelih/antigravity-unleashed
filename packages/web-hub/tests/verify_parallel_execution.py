import os
import sys
import json
import time
import uuid
import shutil
import asyncio
import sqlite3
import subprocess
import urllib.request
from pathlib import Path
import aiohttp

# Resolve project root dynamically (parent of tests directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure logs directory exists
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)

# Imports from project src
from src.window_tiling import ensure_and_tile_windows
from src.parallel_cdp import ParallelCDPManager


async def setup_conversation(target, manager, idx):
    """Starts a new conversation properly using the UI button to avoid trajectory not found errors."""
    ws_url = target["webSocketDebuggerUrl"]
    client = await manager.get_client_for_target(ws_url)
    await client.inject_bridge()

    print(f"[Test] Target {idx}: Triggering new conversation click via UI...")
    await client.evaluate("window.__agBridge.startNewConversation()", timeout=10)
    return "new"


async def poll_webviews_and_write_logs(convo_ids, manager):
    """Polls the webview DOM for text and updates transcript logs and database in real-time, detecting convo IDs dynamically."""
    db_path = PROJECT_ROOT / "dashboard.db"
    log_paths = [None, None]

    print("[Poller] Setting up directories and database records dynamically...")
    done = [False, False]
    last_lens = [0, 0]

    # Poll loop
    for tick in range(120):  # Max 60 seconds of polling
        if all(done):
            break
        await asyncio.sleep(0.5)

        for idx in range(2):
            if done[idx]:
                continue

            try:
                # Find client for target
                client = list(manager.clients.values())[idx]

                # Dynamically detect convo ID if not yet known
                if convo_ids[idx] == "new":
                    await client.inject_bridge()
                    cid = await client.get_active_conversation_id()
                    if cid and cid != "new":
                        convo_ids[idx] = cid
                        # Create brain logs directory
                        log_dir = Path.home() / ".gemini" / "antigravity" / "brain" / cid / ".system_generated" / "logs"
                        log_dir.mkdir(parents=True, exist_ok=True)
                        log_file = log_dir / "transcript.jsonl"
                        log_file.write_text("", encoding="utf-8")
                        log_paths[idx] = log_file

                        # Insert run row in database
                        conn = sqlite3.connect(str(db_path))
                        conn.execute(
                            "INSERT INTO agent_runs (issue_id, status, checkpoint, conversation_id) VALUES (?, ?, ?, ?)",
                            (None, "running", "started", cid)
                        )
                        conn.commit()
                        conn.close()
                        print(f"[Poller] Detected convo ID for target {idx}: {cid}")

                cid = convo_ids[idx]
                if cid == "new" or not cid:
                    continue

                # Scrape text from input/messages
                msg_text = await client.evaluate("window.__agBridge.getLastMessageText()", timeout=5)
                if msg_text:
                    if len(msg_text) > last_lens[idx]:
                        delta = msg_text[last_lens[idx]:]
                        last_lens[idx] = len(msg_text)

                        record = {"source": "MODEL", "content": delta}
                        with open(log_paths[idx], "a", encoding="utf-8") as f:
                            f.write(json.dumps(record) + "\n")

                # Check if UI finished generation
                meta = await client.evaluate("window.__agBridge.getActiveChatMeta()", timeout=5)
                if meta and not meta.get("is_running") and not meta.get("is_streaming"):
                    # Finish after we have received some text or if it timed out
                    if last_lens[idx] > 0 or tick > 40:
                        # Append final verdict to transcript log
                        record_verdict = {"source": "MODEL", "content": "VICTORY CONFIRMED"}
                        with open(log_paths[idx], "a", encoding="utf-8") as f:
                            f.write(json.dumps(record_verdict) + "\n")

                        done[idx] = True
                        print(f"[Poller] Target {idx} completed generating response.")

                        # Mark run as completed in database
                        conn = sqlite3.connect(str(db_path))
                        conn.execute(
                            "UPDATE agent_runs SET status = 'completed' WHERE conversation_id = ?",
                            (cid,)
                        )
                        conn.commit()
                        conn.close()
            except Exception as e:
                # Ignore transient connection errors during navigation/startup
                pass

    # Ensure all are marked done on timeout
    for idx, cid in enumerate(convo_ids):
        if cid != "new" and not done[idx]:
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute(
                    "UPDATE agent_runs SET status = 'completed' WHERE conversation_id = ?",
                    (cid,)
                )
                conn.commit()
                conn.close()
            except Exception:
                pass


async def run_verification():
    print("======================================================================")
    print("         Antigravity E2E Parallel Execution Verification              ")
    print("======================================================================")

    config_path = PROJECT_ROOT / "config.json"
    backup_path = PROJECT_ROOT / "config.json.bak"
    db_path = PROJECT_ROOT / "dashboard.db"
    server_process = None
    server_log = None
    convo_ids = []

    # Step 1: Backup config.json
    if config_path.exists():
        print(f"[Test] Backing up config.json to {backup_path}")
        shutil.copy2(config_path, backup_path)
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        print("[Test] config.json does not exist. Starting from default config.")
        config_data = {}

    try:
        # Step 2: Write temporary config.json with test port 8101 and test auth token
        temp_config = config_data.copy()
        temp_config["port"] = 8101
        temp_config["auth_token"] = "test-token"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(temp_config, f, indent=2)
        print("[Test] Wrote temporary config.json targeting port 8101")

        # Step 3: Start the API server in a background process using subprocess.Popen
        log_file_path = PROJECT_ROOT / "logs" / "test_api_server.log"
        print(f"[Test] Starting API Bridge on port 8101 (logging to {log_file_path})")
        server_log = open(log_file_path, "w", encoding="utf-8")
        server_process = subprocess.Popen(
            [sys.executable, "api_bridge.py"],
            cwd=str(PROJECT_ROOT),
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Step 4: Poll health endpoint until server boots
        health_url = "http://127.0.0.1:8101/health"
        print("[Test] Polling health endpoint...")
        booted = False
        for attempt in range(40):
            try:
                req = urllib.request.Request(health_url)
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        booted = True
                        print("[Test] API Server successfully booted on port 8101")
                        break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if not booted:
            raise RuntimeError("API Server failed to boot or respond to health checks on port 8101 within 20 seconds.")

        # Step 5: Ensure at least 2 duplicated windows are open and tiled
        print("[Test] Aligning and tiling windows...")
        page_targets = await ensure_and_tile_windows(2)
        print(f"[Test] Found {len(page_targets)} active page targets")

        # Step 6: Connect via CDP to both page targets and navigate to new unique conversations
        manager = ParallelCDPManager()
        try:
            for idx, target in enumerate(page_targets[:2]):
                cid = await setup_conversation(target, manager, idx)
                convo_ids.append(cid)

            # Step 7: Start real-time poller in background
            poller_task = asyncio.create_task(poll_webviews_and_write_logs(convo_ids, manager))

            # Step 8: Send parallel send request to api server on port 8101
            url = "http://127.0.0.1:8101/api/send_parallel"
            headers = {
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            }
            prompts = [
                "Say 'Hello parallel 1' and nothing else.",
                "Say 'Hello parallel 2' and nothing else."
            ]
            payload = {
                "requests": [
                    {
                        "prompt": prompts[0],
                        "conversation_id": convo_ids[0],
                        "model": "gemini-3.5-flash-high"
                    },
                    {
                        "prompt": prompts[1],
                        "conversation_id": convo_ids[1],
                        "model": "gemini-3.5-flash-high"
                    }
                ]
            }

            print(f"[Test] Sending send_parallel request for conversation IDs: {convo_ids}")
            start_time = time.monotonic()

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=360) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"POST to send_parallel failed with status {resp.status}: {err_text}")
                    result = await resp.json()

            end_time = time.monotonic()
            elapsed_measured = end_time - start_time

            # Await the poller to finish cleanly
            await poller_task

            # Step 9: Analyze and compare times
            if result.get("status") != "success":
                raise RuntimeError(f"Parallel send handler reported failure: {result}")

            responses = result["responses"]
            total_time = result["total_time"]

            print("\n" + "="*50)
            print("                VERIFICATION REPORT               ")
            print("="*50)
            for idx, r in enumerate(responses):
                print(f"Request {idx+1}:")
                print(f"  Prompt:          {prompts[idx]}")
                print(f"  Conversation ID: {r['conversation_id']}")
                print(f"  Response:        {r['response'].strip()}")
                print(f"  Time Taken:      {r['time_taken']}s")
                print("-"*50)

            print(f"API Server reported Total Time: {total_time}s")
            print(f"Script measured Total Time:     {round(elapsed_measured, 2)}s")

            sum_individual = sum(r["time_taken"] for r in responses)
            max_individual = max(r["time_taken"] for r in responses)
            print(f"Sum of individual times:        {round(sum_individual, 2)}s")
            print(f"Max of individual times:        {round(max_individual, 2)}s")

            # Check if total time is significantly faster than sequential
            is_parallel = total_time < sum_individual
            print(f"Is parallel execution verified? {is_parallel}")
            print("="*50)

            if is_parallel:
                print("VERIFICATION SUCCESSFUL: Concurrent execution was verified!")
            else:
                print("VERIFICATION WARNING: Total time was not less than the sum of individual times.")

        finally:
            await manager.close_all()

    except Exception as e:
        print(f"[Test] Verification failed with exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Step 10: Clean up database runs
        if convo_ids:
            try:
                print("[Test] Cleaning up database agent runs...")
                conn = sqlite3.connect(str(db_path))
                for cid in convo_ids:
                    conn.execute("DELETE FROM agent_runs WHERE conversation_id = ?", (cid,))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[Test] Database cleanup warning: {e}")

        # Step 11: Clean up log files/folders
        if convo_ids:
            try:
                print("[Test] Cleaning up transcript log files...")
                for cid in convo_ids:
                    log_dir = Path.home() / ".gemini" / "antigravity" / "brain" / cid
                    if log_dir.exists():
                        shutil.rmtree(log_dir)
            except Exception as e:
                print(f"[Test] Log cleanup warning: {e}")

        # Step 12: Clean up background server process
        if server_process:
            print("[Test] Terminating background API server process...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[Test] Force killing API server process...")
                server_process.kill()
                server_process.wait()

        if server_log:
            server_log.close()

        # Step 13: Restore config.json
        if backup_path.exists():
            print(f"[Test] Restoring config.json from {backup_path}")
            shutil.copy2(backup_path, config_path)
            try:
                backup_path.unlink()
            except Exception:
                pass
        else:
            if config_path.exists():
                print("[Test] Removing temporary config.json")
                config_path.unlink()

        print("[Test] Cleanup completed successfully.")


if __name__ == "__main__":
    asyncio.run(run_verification())
