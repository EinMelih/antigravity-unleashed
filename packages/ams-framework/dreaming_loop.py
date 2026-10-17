import os
import time
import shutil
import argparse
import sys
from pathlib import Path

class DreamingProcess:
    def __init__(self, scratch_dir, dreams_file, memory_pc_file, user_pc_file):
        self.scratch_dir = Path(scratch_dir).resolve()
        self.dreams_file = Path(dreams_file).resolve()
        self.memory_pc_file = Path(memory_pc_file).resolve()
        self.user_pc_file = Path(user_pc_file).resolve()

    def ingest_scratch_files(self):
        """Read all temporary scratch and log files from the root of scratch directory."""
        session_data = []
        if not self.scratch_dir.exists():
            return ""
        
        # Avoid walking subdirectories recursively (prevents token bloat from node_modules, build dirs etc.)
        for file in os.listdir(self.scratch_dir):
            file_path = self.scratch_dir / file
            if file_path.is_file() and file.endswith((".log", ".txt", ".json")):
                # Token-efficiency: skip files larger than 500 KB
                if file_path.stat().st_size > 500000:
                    session_data.append(f"--- File: {file} (Truncated due to size) ---\n[File is too large to ingest]\n")
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    session_data.append(f"--- File: {file} ---\n{content}\n")
                except Exception as e:
                    session_data.append(f"--- Error reading {file}: {str(e)} ---\n")
        return "\n".join(session_data)

    def run_dreaming(self, dynamic_summary=None, dynamic_facts=None):
        """Executes the dreaming loop: Ingest, Summarize, Promote, Prune/Archive."""
        print("[Dreaming] Starting memory consolidation loop...")
        
        # 1. Ingest
        raw_logs = self.ingest_scratch_files()
        if not raw_logs.strip():
            print("[Dreaming] No temporary files found to ingest.")
            return

        # 2. Reflect & Extract
        # Use dynamic inputs if provided, otherwise fall back to mock values
        summary = dynamic_summary or "Consolidated script execution logs and resolved configuration pathing."
        extracted_facts = dynamic_facts or [
            f"User preferred staging environment checked on {time.strftime('%Y-%m-%d')}"
        ]

        # 3. Promote & Deduplicate in MEMORY.pc.md (NEVER directly write to compiled MEMORY.md)
        if self.memory_pc_file.exists():
            try:
                content = self.memory_pc_file.read_text(encoding="utf-8")
                updated_content = content
                
                fact_section = "\n\n## 5. Distilled Facts (Dreaming Loop)\n"
                if "## 5. Distilled Facts" not in content:
                    updated_content += fact_section
                    
                for fact in extracted_facts:
                    # Deduplicate based on core fact content (timestamp-agnostic check)
                    core_fact = fact.split("}: ")[-1] if "}: " in fact else fact
                    if core_fact not in content:
                        updated_content += f"- {fact}\n"
                
                if updated_content != content:
                    self.memory_pc_file.write_text(updated_content, encoding="utf-8")
                    print(f"[Dreaming] Promoted new facts to {self.memory_pc_file.name}.")
            except Exception as e:
                print(f"[Dreaming] Error promoting facts: {e}")

        # 4. Record to DREAMS.md
        dream_entry = (
            f"\n## Dream consolidation - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"### Accomplishments:\n{summary}\n"
            f"### New Memorized Facts:\n" + "\n".join(f"- {fact}" for fact in extracted_facts) + "\n"
        )
        
        try:
            with open(self.dreams_file, "a", encoding="utf-8") as f:
                f.write(dream_entry)
        except Exception as e:
            print(f"[Dreaming] Error recording dream: {e}")

        # 5. Safe Pruning / Archive temp logs in scratch
        archive_dir = self.scratch_dir / ".archive"
        archive_dir.mkdir(exist_ok=True)
        
        grace_period_seconds = 900  # 15 minutes grace period
        current_time = time.time()
        
        for file in os.listdir(self.scratch_dir):
            file_path = self.scratch_dir / file
            # Align extensions: logs, txt, json
            if file_path.is_file() and file.endswith((".log", ".txt", ".json")):
                # Skip files modified within the grace period to avoid cutting off active processes
                if current_time - file_path.stat().st_mtime < grace_period_seconds:
                    continue
                
                try:
                    # Move to archive instead of destructive delete
                    dest_path = archive_dir / file
                    # Handle name collision in archive
                    if dest_path.exists():
                        dest_path = archive_dir / f"{Path(file).stem}_{int(time.time())}{Path(file).suffix}"
                    shutil.move(str(file_path), str(dest_path))
                except Exception as e:
                    print(f"[Dreaming] Failed to archive {file}: {e}")
                
        print("[Dreaming] Memory compaction completed.")

def main():
    parser = argparse.ArgumentParser(description="Consolidate AI scratch memories.")
    parser.add_argument("--summary", type=str, default=None, help="Dynamic summary of the session logs.")
    parser.add_argument("--facts", type=str, nargs="+", default=[], help="List of dynamic facts to add to memory.")
    args = parser.parse_args()

    home = Path.home()
    scratch = home / ".gemini" / "antigravity" / "scratch"
    config = home / ".gemini" / "config"
    
    dreams = config / "DREAMS.md"
    memory_pc = config / "MEMORY.pc.md"
    user_pc = config / "USER.pc.md"
    
    dreamer = DreamingProcess(scratch, dreams, memory_pc, user_pc)
    dreamer.run_dreaming(args.summary, args.facts)
    
    # Trigger compiler to update MEMORY.md and USER.md
    compiler_path = config / "scripts" / "compile_memory.py"
    if compiler_path.exists():
        print("[Dreaming] Recompiling memory files after dream consolidation...")
        subprocess_res = subprocess_run = None
        try:
            import subprocess
            res = subprocess.run([sys.executable, str(compiler_path)], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[Dreaming] Compiler Error: {res.stderr}")
            else:
                print(f"[Dreaming] Compiler Output: {res.stdout.strip()}")
        except Exception as e:
            print(f"[Dreaming] Failed to run compiler: {e}")

if __name__ == "__main__":
    main()
