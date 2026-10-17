"""Privacy Compliance, File Integrity, and Release Readiness Test Suite.

Automated verification suite enforcing monorepo-wide sanitization,
zero-leak constraints, git history cleanliness, image asset resolution,
template presence, and open-source governance compliance.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_forbidden_patterns():
    """Dynamically assemble forbidden regex patterns.
    
    Tokens are constructed at runtime to avoid storing forbidden literals
    in source code or self-triggering static scanners.
    """
    token_user_path = r"Users[/\\]" + "EinMelih"
    token_gh_oauth = "gh" + "o_"
    token_personality = "user_" + "personality"
    token_backup = "".join(["win11 ", "alt ", "backup"])
    token_klein = "Klein" + "anzeigen"
    token_luchs = "Luchs" + "Watch"
    token_snipe = "Snipe" + "Tower"
    token_gams = "Gams" + "Go"

    return [
        (token_user_path, re.compile(token_user_path, re.IGNORECASE)),
        (token_gh_oauth, re.compile(token_gh_oauth, re.IGNORECASE)),
        (token_personality, re.compile(token_personality, re.IGNORECASE)),
        (token_backup, re.compile(token_backup, re.IGNORECASE)),
        (token_klein, re.compile(token_klein, re.IGNORECASE)),
        (token_luchs, re.compile(token_luchs, re.IGNORECASE)),
        (token_snipe, re.compile(token_snipe, re.IGNORECASE)),
        (token_gams, re.compile(token_gams, re.IGNORECASE)),
    ]


class TestPrivacyCompliance(unittest.TestCase):
    """Test suite for repository sanitization and release compliance."""

    def setUp(self):
        self.root = PROJECT_ROOT
        self.forbidden_patterns = get_forbidden_patterns()

    def test_01_recursive_scan_for_forbidden_patterns(self):
        """Test 1: Recursive scan of all files in repository (excluding .git/ and .agents/).
        
        Must return 0 matches across all configured forbidden privacy patterns.
        """
        violations = []
        excluded_dirs = {".git", ".agents", "__pycache__"}

        scanned_count = 0
        for root, dirs, files in os.walk(self.root):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in files:
                # Skip compiled bytecode files
                if filename.endswith((".pyc", ".pyo")):
                    continue

                filepath = Path(root) / filename
                rel_path = filepath.relative_to(self.root)

                scanned_count += 1
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            for name, pattern in self.forbidden_patterns:
                                match = pattern.search(line)
                                if match:
                                    violations.append({
                                        "file": str(rel_path),
                                        "line": line_num,
                                        "pattern": name,
                                        "matched_text": match.group(0),
                                        "context": line.strip()[:120],
                                    })
                except Exception as err:
                    violations.append({
                        "file": str(rel_path),
                        "line": 0,
                        "pattern": "READ_ERROR",
                        "matched_text": str(err),
                        "context": "",
                    })

        self.assertGreater(scanned_count, 10, "Should scan substantial repository files")
        failure_msg = (
            f"Found {len(violations)} forbidden pattern violations in {scanned_count} files:\n"
            + "\n".join(
                f"  [{v['pattern']}] {v['file']}:{v['line']} -> '{v['matched_text']}' in: {v['context']}"
                for v in violations
            )
        )
        self.assertEqual(len(violations), 0, failure_msg)

    def test_02_forbidden_file_extensions_and_live_state(self):
        """Test 2: Check for forbidden file extensions.
        
        Zero *.db, *.db-wal, *.db-shm, *.jsonl, *.conflict, USER.md, MEMORY.md
        may exist outside .git and .agents.
        """
        forbidden_extensions = {".db", ".db-wal", ".db-shm", ".jsonl", ".sqlite", ".sqlite3"}
        forbidden_exact_names = {"user.md", "memory.md", "user.pc.md", "memory.pc.md"}
        violations = []
        excluded_dirs = {".git", ".agents"}

        scanned_count = 0
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in files:
                scanned_count += 1
                low_name = filename.lower()
                rel_path = (Path(root) / filename).relative_to(self.root)

                for ext in forbidden_extensions:
                    if low_name.endswith(ext):
                        violations.append((str(rel_path), f"Forbidden extension: {ext}"))

                if ".conflict" in low_name:
                    violations.append((str(rel_path), "Contains .conflict in filename"))

                if low_name in forbidden_exact_names:
                    violations.append((str(rel_path), f"Forbidden live persona/memory filename: {filename}"))

        failure_msg = (
            f"Found {len(violations)} forbidden file violations in {scanned_count} files:\n"
            + "\n".join(f"  {path}: {reason}" for path, reason in violations)
        )
        self.assertEqual(len(violations), 0, failure_msg)

    def test_03_git_log_contains_zero_forbidden_patterns(self):
        """Test 3: Check git log diffs.
        
        'git log -p' must contain 0 occurrences of the forbidden patterns.
        """
        try:
            log_output = subprocess.check_output(
                ["git", "log", "-p"],
                cwd=str(self.root),
                encoding="utf-8",
                errors="ignore",
            )
        except subprocess.CalledProcessError as e:
            self.fail(f"Failed to execute 'git log -p': {e}")

        violations = []
        for line_num, line in enumerate(log_output.splitlines(), 1):
            for name, pattern in self.forbidden_patterns:
                match = pattern.search(line)
                if match:
                    violations.append({
                        "line": line_num,
                        "pattern": name,
                        "matched_text": match.group(0),
                        "snippet": line.strip()[:120],
                    })

        failure_msg = (
            f"Found {len(violations)} forbidden pattern matches in git log history:\n"
            + "\n".join(
                f"  [{v['pattern']}] Line {v['line']}: '{v['matched_text']}' in: {v['snippet']}"
                for v in violations
            )
        )
        self.assertEqual(len(violations), 0, failure_msg)

    def test_04_markdown_image_links_resolve_and_valid(self):
        """Test 4: Check markdown image links in README.md.
        
        Verify every referenced local file exists on disk, is non-empty (>5KB for images),
        and has valid PNG or SVG format.
        """
        doc_files = ["README.md"]
        png_magic = b"\x89PNG\r\n\x1a\n"
        
        verified_images = []
        missing_or_invalid = []

        for rel_doc in doc_files:
            doc_path = self.root / rel_doc
            self.assertTrue(doc_path.exists(), f"Document file missing: {rel_doc}")

            content = doc_path.read_text(encoding="utf-8")

            # Extract markdown image links: ![alt](path)
            md_links = re.findall(r"!\[.*?\]\((.*?)\)", content)
            # Extract HTML img src links: <img src="path" ... />
            html_links = re.findall(r'<img [^>]*src=[\'"](.*?)[\'"]', content)

            all_links = md_links + html_links

            for link in all_links:
                # Strip fragments or title text
                clean_link = link.strip().split()[0].split("#")[0]

                # Ignore external URLs (e.g. shields.io badges)
                if clean_link.startswith(("http://", "https://")):
                    continue

                target_path = (self.root / clean_link).resolve()

                # 1. Existence check
                if not target_path.exists() or not target_path.is_file():
                    missing_or_invalid.append(
                        f"[{rel_doc}] Image not found on disk: {clean_link} -> {target_path}"
                    )
                    continue

                # 2. File size check (> 5KB = 5120 bytes)
                file_size = target_path.stat().st_size
                if file_size <= 5120:
                    missing_or_invalid.append(
                        f"[{rel_doc}] Image too small (<= 5KB): {clean_link} ({file_size} bytes)"
                    )
                    continue

                # 3. Format header verification
                ext = target_path.suffix.lower()
                if ext == ".png":
                    with open(target_path, "rb") as img_f:
                        header = img_f.read(8)
                    if header != png_magic:
                        missing_or_invalid.append(
                            f"[{rel_doc}] Invalid PNG header for {clean_link}: {header!r}"
                        )
                        continue
                elif ext == ".svg":
                    svg_content = target_path.read_text(encoding="utf-8", errors="ignore")
                    if "<svg" not in svg_content:
                        missing_or_invalid.append(
                            f"[{rel_doc}] Invalid SVG content for {clean_link}: missing <svg root tag"
                        )
                        continue
                else:
                    missing_or_invalid.append(
                        f"[{rel_doc}] Unsupported image format extension: {ext} for {clean_link}"
                    )
                    continue

                verified_images.append((rel_doc, clean_link, file_size))

        # Ensure we verified the logo asset in README.md
        self.assertGreaterEqual(
            len(verified_images),
            1,
            f"Expected at least 1 branding asset verified, found: {len(verified_images)}",
        )
        self.assertEqual(len(missing_or_invalid), 0, "\n".join(missing_or_invalid))

    def test_05_template_files_exist(self):
        """Test 5: Verify template files exist and are populated.
        
        Requires: config.example.json, USER.example.md, MEMORY.example.md.
        """
        required_templates = [
            "config.example.json",
            "USER.example.md",
            "MEMORY.example.md",
        ]

        for filename in required_templates:
            template_path = self.root / filename
            self.assertTrue(
                template_path.exists(),
                f"Required template missing: {filename}",
            )
            self.assertTrue(
                template_path.is_file(),
                f"Template must be a regular file: {filename}",
            )
            size = template_path.stat().st_size
            self.assertGreater(
                size,
                100,
                f"Template {filename} is suspiciously empty ({size} bytes)",
            )

    def test_06_governance_files_exist(self):
        """Test 6: Verify governance files exist and are populated.
        
        Requires: LICENSE, SECURITY.md, CONTRIBUTING.md, .gitignore.
        """
        required_governance = [
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            ".gitignore",
        ]

        for filename in required_governance:
            gov_path = self.root / filename
            self.assertTrue(
                gov_path.exists(),
                f"Required governance file missing: {filename}",
            )
            self.assertTrue(
                gov_path.is_file(),
                f"Governance file must be a regular file: {filename}",
            )
            size = gov_path.stat().st_size
            self.assertGreater(
                size,
                500,
                f"Governance file {filename} is suspiciously empty ({size} bytes)",
            )

        # Content checks for key legal terms
        license_text = (self.root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Google Antigravity", license_text)

        security_text = (self.root / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", security_text)

        contributing_text = (self.root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("Contributing to Antigravity Unleashed", contributing_text)


if __name__ == "__main__":
    unittest.main()
