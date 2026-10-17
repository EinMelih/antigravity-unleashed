import asyncio
import json
import time
from pathlib import Path
from src.database import db


async def monitor_subagent_transcript(convo_id: str, timeout: float = 300.0) -> dict:
    """
    Tails the transcript.jsonl file for the specified conversation ID
    and queries the database for completion status.
    """
    log_file = (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "brain"
        / convo_id
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )

    start_time = time.monotonic()
    last_pos = 0
    collected_responses = []

    print(f"[LogMonitor] Starting log monitor for convo: {convo_id}", flush=True)

    while time.monotonic() - start_time < timeout:
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_pos)
                    lines = f.readlines()
                    last_pos = f.tell()

                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            if record.get("source") == "MODEL" and record.get("content"):
                                collected_responses.append(record["content"])
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                print(f"[LogMonitor] Warning reading transcript for {convo_id}: {e}", flush=True)

        # Check database for status completion
        try:
            with db._get_connection() as conn:
                row = conn.execute(
                    "SELECT status FROM agent_runs WHERE conversation_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (convo_id,),
                ).fetchone()
                if row and row["status"] in ("completed", "failed", "cancelled"):
                    print(
                        f"[LogMonitor] DB status '{row['status']}' "
                        f"detected for {convo_id}",
                        flush=True,
                    )
                    # Execute a final read
                    if log_file.exists():
                        try:
                            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                                f.seek(last_pos)
                                lines = f.readlines()
                                for line in lines:
                                    if not line.strip():
                                        continue
                                    try:
                                        record = json.loads(line)
                                        if record.get("source") == "MODEL" and record.get("content"):
                                            collected_responses.append(record["content"])
                                    except json.JSONDecodeError:
                                        pass
                        except Exception:
                            pass
                    break
        except Exception as e:
            print(
                f"[LogMonitor] DB query warning for {convo_id}: {e}",
                flush=True,
            )

        await asyncio.sleep(0.5)

    # Determine final verdict
    final_verdict = ""
    for resp in reversed(collected_responses):
        if "VICTORY CONFIRMED" in resp or "VICTORY REJECTED" in resp:
            final_verdict = "VICTORY CONFIRMED" if "VICTORY CONFIRMED" in resp else "VICTORY REJECTED"
            break

    return {
        "conversation_id": convo_id,
        "response": collected_responses[-1] if collected_responses else "",
        "full_history": collected_responses,
        "verdict": final_verdict,
    }
