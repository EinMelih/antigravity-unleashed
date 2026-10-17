import os
import re
import ast
import shutil
import tempfile
import sys
import subprocess
from pathlib import Path

# Ensure UTF-8 stdout encoding to prevent Windows cp1252 console crashes
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class ImportRewriter(ast.NodeTransformer):
    """AST transformer to rewrite deprecated imports."""
    def __init__(self, old_import, new_import):
        self.old_import = old_import
        self.new_import = new_import
        self.modified = False

    def visit_ImportFrom(self, node):
        if node.module and (node.module == self.old_import or node.module.startswith(self.old_import + ".")):
            node.module = node.module.replace(self.old_import, self.new_import, 1)
            self.modified = True
        return node

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == self.old_import or alias.name.startswith(self.old_import + "."):
                alias.name = alias.name.replace(self.old_import, self.new_import, 1)
                self.modified = True
        return node

class SkillsCurator:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir

    def restore_conflict_files(self):
        """Finds all *.conflict.<timestamp> files and restores them if original is missing."""
        if not self.skills_dir.exists():
            return
        print(f"Scanning for conflict files to restore in {self.skills_dir}...")
        for root, _, files in os.walk(self.skills_dir):
            for file in files:
                if ".conflict." in file:
                    conflict_path = Path(root) / file
                    original_name = re.sub(r"\.conflict\.\d+", "", file)
                    original_path = Path(root) / original_name
                    
                    if not original_path.exists():
                        print(f"Restoring {conflict_path} -> {original_path}")
                        shutil.copy2(conflict_path, original_path)

    def refactor_skill_files(self, old_pkg: str, new_pkg: str):
        """Walks all Python files in the skills directory and updates imports & uv metadata."""
        if not self.skills_dir.exists():
            return
        print(f"Refactoring imports from '{old_pkg}' to '{new_pkg}' in {self.skills_dir}...")
        for root, _, files in os.walk(self.skills_dir):
            for file in files:
                if not file.endswith(".py") or ".conflict." in file:
                    continue
                
                file_path = Path(root) / file
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue

                # 1. Update UV script metadata (PEP 723 comment blocks)
                modified_content = content
                # Replace dependencies name
                modified_content = re.sub(
                    rf'"{old_pkg}"',
                    f'"{new_pkg.replace("_", "-")}"',
                    modified_content
                )
                # Replace uv source paths using safe string concatenation to avoid f-string syntax issues with brackets
                pattern = re.escape(old_pkg) + r'\s*=\s*\{\s*path\s*=\s*"(.*?)"\s*\}'
                repl = new_pkg.replace("_", "-") + ' = { path = "../../' + new_pkg + '" }'
                modified_content = re.sub(pattern, repl, modified_content)

                # 2. Update Python Imports via AST
                try:
                    tree = ast.parse(modified_content)
                    # We need to handle nested import rewrites
                    rewriter = ImportRewriter(
                        f"science_skills.skills.{old_pkg}",
                        f"science_skills.{new_pkg}"
                    )
                    rewriter.visit(tree)
                    
                    # Also handle absolute imports like from scienceskillscommon import http_client
                    rewriter_direct = ImportRewriter(
                        old_pkg,
                        f"science_skills.{new_pkg}" # rewrite to absolute canonical namespace
                    )
                    rewriter_direct.visit(tree)
                    
                    if rewriter.modified or rewriter_direct.modified or modified_content != content:
                        ast.fix_missing_locations(tree)
                        final_code = ast.unparse(tree)
                        
                        # Preserve UV metadata block at the top if it was removed by ast.unparse
                        metadata_match = re.match(r"(#\s*///.*?#\s*///)", content, re.DOTALL)
                        if metadata_match:
                            metadata = metadata_match.group(1)
                            # Ensure we update the metadata inside the header
                            metadata = re.sub(rf'"{old_pkg}"', f'"{new_pkg.replace("_", "-")}"', metadata)
                            metadata = re.sub(pattern, repl, metadata)
                            final_code = metadata + "\n\n" + final_code
                        
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(final_code)
                        print(f"Successfully refactored {file_path}")
                except Exception as e:
                    print(f"Skipped refactoring for {file_path} due to error: {e}")

    def patch_http_client_compatibility(self, client_path: Path):
        """Applies a platform-agnostic file lock to http_client.py."""
        if not client_path.exists():
            print(f"Error: {client_path} not found.")
            return

        print(f"Patching {client_path} for Windows cross-platform compatibility...")
        try:
            with open(client_path, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            print(f"Error reading {client_path}: {e}")
            return

        # 1. Replace Unix-specific fcntl import with conditional imports
        if "import fcntl" in code:
            code = re.sub(
                r"^import fcntl$",
                "try:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n\ntry:\n    import msvcrt\nexcept ImportError:\n    msvcrt = None",
                code,
                flags=re.MULTILINE
            )

        # 2. Match from def __init__ all the way to def _maybe_decompress and replace
        wait_pattern = r"  def __init__\(self, hostname: str, qps: float\):.*?(?=def _maybe_decompress)"
        
        new_methods_body = """  def __init__(self, hostname: str, qps: float):
    \"\"\"Initialize rate limiter.

    Args:
      hostname: Hostname of the API.
      qps: Maximum queries per second.
    \"\"\"
    self._min_interval = 1.0 / qps
    import tempfile
    self._lock_file = os.path.join(tempfile.gettempdir(), f"science_skills-{hostname}.lock")

  def wait(self, min_sleep: float = 0.0):
    \"\"\"Block until the next request is allowed.

    Args:
      min_sleep: Additional minimum sleep in seconds.  The actual delay is
        `max(rate_limit_gap, min_sleep)`, which lets callers fold retry back-off
        into the same call.
    \"\"\"
    os.makedirs(os.path.dirname(self._lock_file), exist_ok=True)
    with open(self._lock_file, "a+") as f:
      if fcntl:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
      elif msvcrt:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 100)
      try:
        f.seek(0)
        content = f.read().strip()
        last_ts = float(content) if content else 0.0
        now = time.monotonic()
        gap = self._min_interval - (now - last_ts)
        delay = max(gap, min_sleep)
        if delay > 0:
          time.sleep(delay)
        f.seek(0)
        f.truncate()
        f.write(str(time.monotonic()))
        f.flush()
      finally:
        if fcntl:
          fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        elif msvcrt:
          f.seek(0)
          msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 100)

"""
        # Let's perform replacement only if def __init__ is found
        if "def __init__(self, hostname: str," in code:
            code = re.sub(wait_pattern, new_methods_body, code, flags=re.DOTALL)

        try:
            with open(client_path, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"Patched cross-platform locking in {client_path}")
        except Exception as e:
            print(f"Error writing to {client_path}: {e}")

    def merge_and_clean(self, old_dir: Path, new_dir: Path):
        """Removes the old duplicate directory after successful refactoring."""
        if old_dir.exists() and old_dir != new_dir:
            print(f"Removing deprecated directory: {old_dir}")
            try:
                shutil.rmtree(old_dir)
                print("Cleanup completed.")
            except Exception as e:
                print(f"Error cleaning up old directory: {e}")

    def validate_skills_frontmatter(self) -> tuple[bool, list[dict]]:
        """Parses and validates the YAML frontmatter in all SKILL.md files in self.skills_dir."""
        if not self.skills_dir.exists():
            return True, []
        print(f"Validating SKILL.md frontmatter in {self.skills_dir}...")
        errors = []
        
        for root, _, files in os.walk(self.skills_dir):
            if "SKILL.md" in files:
                skill_file = Path(root) / "SKILL.md"
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    # Match frontmatter block at the very start of the file
                    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                    if not match:
                        errors.append({
                            "file": str(skill_file),
                            "error": "Missing or malformed frontmatter delimiters (---)"
                        })
                        continue
                    
                    frontmatter_text = match.group(1)
                    metadata = {}
                    for line in frontmatter_text.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            metadata[k.strip()] = v.strip().strip('"').strip("'")
                    
                    # Validate required keys
                    for key in ["name", "description"]:
                        if key not in metadata:
                            errors.append({
                                "file": str(skill_file),
                                "error": f"Missing required frontmatter key: '{key}'"
                            })
                    
                    # Validate name rules
                    name = metadata.get("name", "")
                    if name:
                        if not re.match(r"^[a-z0-9-_]+$", name):
                            errors.append({
                                "file": str(skill_file),
                                "error": f"Invalid name format '{name}' (must be lowercase, alphanumeric, hyphens or underscores only)"
                            })
                        if len(name) > 64:
                            errors.append({
                                "file": str(skill_file),
                                "error": f"Skill name '{name}' exceeds maximum length of 64 characters"
                            })
                    
                    # Validate description rules
                    description = metadata.get("description", "")
                    if description and len(description) > 1024:
                        errors.append({
                            "file": str(skill_file),
                            "error": f"Description exceeds maximum length of 1024 characters ({len(description)} chars)"
                        })
                        
                except Exception as e:
                    errors.append({
                        "file": str(skill_file),
                        "error": f"Failed to parse skill: {e}"
                    })
                    
        return len(errors) == 0, errors

    def test_synthesized_skills(self) -> dict:
        """Executes automated verification and dry runs for all installed skills in self.skills_dir."""
        if not self.skills_dir.exists():
            return {}
        print(f"Executing automated test suite for synthesized skills in {self.skills_dir}...")
        results = {}
        
        # Get set of all installed skill names for dependency verification
        installed_skills = set()
        for item in self.skills_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                installed_skills.add(item.name)
                
        for root, dirs, files in os.walk(self.skills_dir):
            # Skip shared/common libraries
            if "science_skills_common" in root or "scienceskillscommon" in root:
                continue
                
            skill_dir = Path(root)
            if "SKILL.md" not in files:
                continue
                
            skill_name = skill_dir.name
            results[skill_name] = {"syntax_ok": True, "dry_run_ok": True, "dependencies_ok": True, "errors": []}
            
            # 1. Verify markdown dependencies
            try:
                content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                dep_section = re.search(r"## Dependencies\n(.*?)(?=\n##|$)", content, re.DOTALL)
                if dep_section:
                    deps = re.findall(r"-\s*`?([a-zA-Z0-9_-]+)`?", dep_section.group(1))
                    for dep in deps:
                        if dep not in installed_skills:
                            results[skill_name]["dependencies_ok"] = False
                            results[skill_name]["errors"].append(f"Missing dependency: '{dep}'")
            except Exception as e:
                results[skill_name]["errors"].append(f"Failed to analyze dependencies: {e}")
                
            # 2. Python-specific CLI tests
            py_files = [f for f in files if f.endswith(".py") and ".conflict." not in f]
            for py_file in py_files:
                py_path = skill_dir / py_file
                
                # A. Syntax Check
                syntax_check = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(py_path)],
                    capture_output=True, text=True
                )
                if syntax_check.returncode != 0:
                    results[skill_name]["syntax_ok"] = False
                    results[skill_name]["errors"].append(f"Syntax Error in {py_file}: {syntax_check.stderr.strip()}")
                    continue
                    
                # B. Dry Run Help Check
                try:
                    code = py_path.read_text(encoding="utf-8")
                    if "argparse" in code or "sys.argv" in code:
                        # Try running with uv first, fall back to sys.executable
                        try:
                            dry_run = subprocess.run(
                                ["uv", "run", str(py_path), "--help"],
                                capture_output=True, text=True, timeout=5
                            )
                        except (subprocess.SubprocessError, FileNotFoundError):
                            dry_run = subprocess.run(
                                [sys.executable, str(py_path), "--help"],
                                capture_output=True, text=True, timeout=5
                            )
                            
                        # Success if code is 0 or usage/help is displayed
                        is_help_displayed = "usage:" in dry_run.stdout.lower() or "options:" in dry_run.stdout.lower() or "help" in dry_run.stdout.lower()
                        if dry_run.returncode != 0 and not is_help_displayed:
                            results[skill_name]["dry_run_ok"] = False
                            results[skill_name]["errors"].append(
                                f"Dry run '--help' failed for {py_file} (Code {dry_run.returncode}): {dry_run.stderr.strip()}"
                            )
                except Exception as e:
                    results[skill_name]["errors"].append(f"Failed to run help check on {py_file}: {e}")
                        
        return results

def main():
    config_dir = Path(os.path.expanduser("~/.gemini/config")).resolve()
    
    # 1. Execute Science Skills Refactoring
    science_skills_dir = config_dir / "plugins" / "science" / "skills"
    if science_skills_dir.exists():
        science_curator = SkillsCurator(science_skills_dir)
        science_curator.restore_conflict_files()
        
        old_pkg_dir = science_skills_dir / "scienceskillscommon"
        new_pkg_dir = science_skills_dir / "science_skills_common"
        
        if not new_pkg_dir.exists() and old_pkg_dir.exists():
            print(f"Creating {new_pkg_dir} from {old_pkg_dir}...")
            shutil.copytree(old_pkg_dir, new_pkg_dir)
            
        science_curator.patch_http_client_compatibility(new_pkg_dir / "http_client.py")
        science_curator.refactor_skill_files("scienceskillscommon", "science_skills_common")
        science_curator.merge_and_clean(old_pkg_dir, new_pkg_dir)
        print("Science skills refactoring complete.\n")
    
    # 2. Run Validation & Automated Tests for both global and plugin skills
    skills_folders = [
        config_dir / "skills",
        config_dir / "plugins" / "science" / "skills"
    ]
    
    all_passed = True
    for folder in skills_folders:
        if not folder.exists():
            continue
            
        curator = SkillsCurator(folder)
        
        # A. Frontmatter Validation
        valid, fm_errors = curator.validate_skills_frontmatter()
        if not valid:
            all_passed = False
            print(f"\n[ERROR] FRONTMATTER VALIDATION FAILED in {folder}:")
            for err in fm_errors:
                print(f"  - File: {err['file']}\n    Error: {err['error']}")
        else:
            print(f"Frontmatter validation passed for {folder}")
            
        # B. Automated Verification
        test_results = curator.test_synthesized_skills()
        if test_results:
            print(f"\nVerification Results for {folder}:")
            for skill, res in test_results.items():
                status = "PASSED"
                if not (res["syntax_ok"] and res["dry_run_ok"] and res["dependencies_ok"]):
                    status = "FAILED"
                    all_passed = False
                print(f"  - {skill}: {status}")
                if res["errors"]:
                    for err in res["errors"]:
                        print(f"    * {err}")
            print()
            
    if all_passed:
        print("All skills verified successfully.")
    else:
        print("Some skills failed verification.")

if __name__ == "__main__":
    main()
