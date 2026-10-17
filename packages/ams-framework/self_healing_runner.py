import subprocess
import sys
import os

class SelfHealingRunner:
    def __init__(self, script_path, max_retries=3):
        self.script_path = script_path
        self.max_retries = max_retries

    def run_script(self):
        """Execute the target script in a subprocess and capture output."""
        result = subprocess.run(
            [sys.executable, self.script_path],
            capture_output=True,
            text=True
        )
        return result.returncode, result.stdout, result.stderr

    def request_llm_fix(self, code, error_message):
        """
        Request the LLM to rewrite the faulty code based on traceback context.
        In production, this calls the agent's active LLM client or leaves a trace
        for the agent to fix in the next turn.
        """
        # Save a correction request trace for the agent
        trace_path = f"{self.script_path}.traceback"
        with open(trace_path, "w", encoding="utf-8") as f:
            f.write(f"Script failed: {self.script_path}\nError:\n{error_message}\nCode:\n{code}")
            
        print(f"[Self-Healing] Error trace written to {trace_path}. Agent will repair on next turn.")
        
        # Simple local replacement patch for demo
        fixed_code = code.replace("denominator = 0", "denominator = 1  # Self-healed denominator")
        return fixed_code

    def execute(self):
        """Runs the script with self-healing retry loop."""
        for attempt in range(1, self.max_retries + 1):
            print(f"[Self-Healing] Running script {self.script_path} (Attempt {attempt}/{self.max_retries})...")
            returncode, stdout, stderr = self.run_script()

            if returncode == 0:
                print("[Self-Healing] Execution successful!")
                return True
            
            print(f"[Self-Healing] Failure detected on attempt {attempt}.")
            print(f"Error Stack Trace:\n{stderr}")

            if attempt == self.max_retries:
                break

            # Ingest code
            with open(self.script_path, "r", encoding="utf-8") as f:
                code = f.read()

            # Query fix and apply
            fixed_code = self.request_llm_fix(code, stderr)
            with open(self.script_path, "w", encoding="utf-8") as f:
                f.write(fixed_code)

        print("[Self-Healing] Max retries reached. Self-healing failed.")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python self_healing_runner.py <path_to_script>")
        sys.exit(1)
        
    target_script = sys.argv[1]
    runner = SelfHealingRunner(target_script)
    runner.execute()
