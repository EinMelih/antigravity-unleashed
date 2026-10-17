import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from src.database import db


class Orchestrator:
    """Manages active agent execution tasks, SSE logs streaming, and recovery."""
    
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Orchestrator, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self.active_tasks: Dict[int, asyncio.Task] = {}
            self.log_queues: Dict[int, List[asyncio.Queue]] = {}
            self.run_events: Dict[int, asyncio.Event] = {}
            self.run_feedbacks: Dict[int, Optional[str]] = {}
            self._initialized = True

    async def wait_for_approval(self, run_id: int) -> str:
        """Pauses execution and awaits user approval or feedback. Returns feedback or empty string."""
        if run_id not in self.run_events:
            self.run_events[run_id] = asyncio.Event()
        
        self.run_feedbacks[run_id] = None
        
        # Wait for event to be set (either via approve or feedback or cancel)
        await self.run_events[run_id].wait()
        
        # Clean up event
        self.run_events.pop(run_id, None)
        
        # Return feedback if any was submitted
        feedback = self.run_feedbacks.pop(run_id, None)
        return feedback or ""

    def approve_run(self, run_id: int) -> bool:
        """Approve a paused run, resuming execution."""
        event = self.run_events.get(run_id)
        if not event:
            return False
        self.run_feedbacks[run_id] = None # No feedback, direct approval
        event.set()
        return True

    def submit_feedback(self, run_id: int, feedback: str) -> bool:
        """Submit feedback for a paused run, resuming execution to process it."""
        event = self.run_events.get(run_id)
        if not event:
            return False
        self.run_feedbacks[run_id] = feedback
        event.set()
        return True

    def register_log_queue(self, run_id: int, queue: asyncio.Queue) -> None:
        """Register a queue to receive real-time log updates for a run."""
        if run_id not in self.log_queues:
            self.log_queues[run_id] = []
        self.log_queues[run_id].append(queue)

    def unregister_log_queue(self, run_id: int, queue: asyncio.Queue) -> None:
        """Unregister a log-streaming queue."""
        if run_id in self.log_queues:
            try:
                self.log_queues[run_id].remove(queue)
            except ValueError:
                pass
            if not self.log_queues[run_id]:
                del self.log_queues[run_id]

    def broadcast_log(self, run_id: int, level: str, message: str) -> None:
        """Saves log to DB and pushes it to all registered queues for real-time streaming.

        Stream-level logs (individual tokens) are only sent to SSE queues,
        NOT persisted to DB to avoid creating thousands of rows per run.
        """
        if level != "stream":
            db.add_run_log(run_id, level, message)

        # Format payload and push to all SSE queues
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message
        }

        if run_id in self.log_queues:
            for q in self.log_queues[run_id]:
                q.put_nowait(payload)

    def start_run(self, issue_id: int, full_auto: bool = True) -> int:
        """Creates a run entry and starts the AgentRunner task in the background."""
        # Check if there is already an active run for this issue
        for rid, task in self.active_tasks.items():
            run = db.get_agent_run(rid)
            if run and run["issue_id"] == issue_id:
                raise ValueError(f"Issue #{issue_id} is already being processed by Run #{rid}.")

        # Create DB entry
        run_id = db.create_agent_run(issue_id, checkpoint="started", status="running", full_auto=full_auto)
        
        # Start background task
        task = asyncio.create_task(self._execute_run(run_id))
        self.active_tasks[run_id] = task
        
        self.broadcast_log(run_id, "info", f"[SYSTEM] 📂 Lauf #{run_id} vom Orchestrator gestartet.")
        return run_id

    def continue_run(self, run_id: int) -> None:
        """Continues an existing run with its accumulated chat history (follow-up)."""
        # Check if this run is already active
        if run_id in self.active_tasks:
            task = self.active_tasks[run_id]
            if not task.done():
                raise ValueError(f"Run #{run_id} läuft bereits.")

        # Start background task in resume mode
        task = asyncio.create_task(self._execute_run_followup(run_id))
        self.active_tasks[run_id] = task
        
        self.broadcast_log(run_id, "info", f"[SYSTEM] 🔄 Lauf #{run_id} wird mit Follow-Up fortgesetzt.")

    async def cancel_run(self, run_id: int) -> bool:
        """Cancels an active agent run."""
        task = self.active_tasks.get(run_id)
        if not task:
            return False

        # Resume any paused event to let the cancel propagate
        event = self.run_events.get(run_id)
        if event:
            event.set()

        task.cancel()
        self.broadcast_log(run_id, "warning", f"[SYSTEM] ⚠️ Lauf #{run_id} wurde vom Benutzer abgebrochen.")
        
        # Wait briefly for cancellation to propagate
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        
        # Update DB state
        db.update_agent_run(run_id, "completed", "cancelled", summary="Cancelled by user.")
        run = db.get_agent_run(run_id)
        if run:
            db.update_issue_status(run["issue_id"], "failed")

        if run_id in self.active_tasks:
            del self.active_tasks[run_id]
            
        return True

    async def recover_active_runs(self) -> None:
        """Recovers and restarts runs that were left in 'running' state during a crash/shutdown."""
        # We query the DB for agent_runs where status = 'running'
        # Since we don't have a specific db query for all running runs, we can select from sqlite directly
        try:
            conn = db._get_connection()
            rows = conn.execute("SELECT id, issue_id FROM agent_runs WHERE status = 'running'").fetchall()
            conn.close()
            
            for row in rows:
                run_id = row["id"]
                issue_id = row["issue_id"]
                print(f"[ORCHESTRATOR] Stelle unvollendeten Lauf #{run_id} für Issue #{issue_id} wieder her...", flush=True)
                
                # Update log
                db.add_run_log(run_id, "warning", "System-Neustart erkannt. Lauf wird wiederhergestellt...")
                
                # Launch task
                task = asyncio.create_task(self._execute_run(run_id))
                self.active_tasks[run_id] = task
        except Exception as e:
            print(f"[ORCHESTRATOR] Fehler bei Recovery: {e}", flush=True)

    async def _execute_run(self, run_id: int) -> None:
        """Executes the runner and cleans up when finished."""
        from src.agent_runner import AgentRunner
        runner = AgentRunner(run_id)
        
        # Override the runner's default logger to use orchestrator broadcasting
        runner.log = lambda level, msg: self.broadcast_log(run_id, level, msg)
        
        try:
            await runner.run()
        except asyncio.CancelledError:
            self.broadcast_log(run_id, "warning", f"[SYSTEM] ⚠️ Ausführung von Lauf #{run_id} abgebrochen.")
            db.update_agent_run(run_id, "completed", "cancelled", summary="Execution cancelled.")
        except Exception as e:
            self.broadcast_log(run_id, "error", f"[SYSTEM] ❌ Unerwarteter Fehler im Orchestrator Execution-Wrapper: {e}")
        finally:
            if run_id in self.active_tasks:
                del self.active_tasks[run_id]
            self.broadcast_log(run_id, "info", f"[SYSTEM] 🏁 Lauf #{run_id} Task beendet.")

    async def _execute_run_followup(self, run_id: int) -> None:
        """Executes the runner in follow-up/resume mode — continues the same conversation."""
        from src.agent_runner import AgentRunner
        runner = AgentRunner(run_id, resume=True)
        
        # Override the runner's default logger to use orchestrator broadcasting
        runner.log = lambda level, msg: self.broadcast_log(run_id, level, msg)
        
        try:
            await runner.run()
        except asyncio.CancelledError:
            self.broadcast_log(run_id, "warning", f"[SYSTEM] ⚠️ Follow-Up Lauf #{run_id} abgebrochen.")
            db.update_agent_run(run_id, "completed", "cancelled", summary="Follow-up cancelled.")
        except Exception as e:
            self.broadcast_log(run_id, "error", f"[SYSTEM] ❌ Fehler im Follow-Up Execution-Wrapper: {e}")
        finally:
            if run_id in self.active_tasks:
                del self.active_tasks[run_id]
            self.broadcast_log(run_id, "info", f"[SYSTEM] 🏁 Follow-Up Lauf #{run_id} Task beendet.")

