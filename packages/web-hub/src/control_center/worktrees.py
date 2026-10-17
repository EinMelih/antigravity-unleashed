"""Safe, isolated Git worktrees for approved control-plane tasks."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from src.control_center.common import ControlCenterError


_GENERATED_DIRECTORY_NAMES = frozenset({
    ".cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".nyc_output",
    ".parcel-cache",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".tox",
    ".venv",
    ".vite",
    "__pycache__",
    "blob-report",
    "bower_components",
    "build",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "out",
    "playwright-report",
    "test-results",
    "venv",
})
_GENERATED_FILE_NAMES = frozenset({
    ".ds_store",
    "thumbs.db",
})
_GENERATED_FILE_SUFFIXES = (
    ".class",
    ".log",
    ".pyc",
    ".pyo",
)


class WorktreeManager:
    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _flags() -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def _git(
        self,
        repo: Path,
        args: Iterable[str],
        *,
        check: bool = True,
        timeout: int | None = None,
        env: Optional[Dict[str, str]] = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(repo), *list(args)],
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
            timeout=timeout or self.timeout_seconds,
            check=False,
            creationflags=self._flags(),
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown git error").strip()
            raise ControlCenterError(
                f"Git-Befehl fehlgeschlagen: {message[:2000]}",
                code="git_command_failed",
                status=409,
            )
        return result

    def validate_repository(self, project: Dict[str, Any]) -> Path:
        path = Path(str(project.get("path") or "")).expanduser().resolve()
        if not path.is_dir():
            raise ControlCenterError(
                "Der lokale Repository-Pfad existiert nicht.",
                code="repository_path_missing",
                status=409,
            )
        inside = self._git(path, ["rev-parse", "--is-inside-work-tree"])
        if inside.stdout.strip().lower() != "true":
            raise ControlCenterError(
                "Der Projektpfad ist kein Git-Repository.",
                code="not_a_git_repository",
                status=409,
            )
        owner = str(project.get("github_owner") or "").strip()
        repo = str(project.get("github_repo") or "").strip()
        if not owner or not repo:
            raise ControlCenterError(
                "Das Projekt ist nicht mit einem GitHub-Repository verknüpft.",
                code="github_repository_not_linked",
                status=409,
            )
        remote = self._git(path, ["remote", "get-url", "origin"])
        normalized = (
            remote.stdout.strip().lower().replace("\\", "/").removesuffix(".git")
        )
        expected_https = f"github.com/{owner.lower()}/{repo.lower()}"
        expected_ssh = f"github.com:{owner.lower()}/{repo.lower()}"
        if expected_https not in normalized and expected_ssh not in normalized:
            raise ControlCenterError(
                "Der lokale origin-Remote passt nicht zum verknüpften GitHub-Repository.",
                code="github_remote_mismatch",
                status=409,
            )
        return path

    def repository_snapshot(self, project: Dict[str, Any]) -> Dict[str, str]:
        """Return a content-sensitive snapshot for read-only planning gates."""
        repository = self.validate_repository(project)
        head = self._git(repository, ["rev-parse", "HEAD"]).stdout.strip().lower()
        status = self._git(
            repository,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ).stdout
        tracked_diff = self._git(
            repository,
            ["diff", "--binary", "HEAD", "--"],
        ).stdout
        digest = hashlib.sha256()
        digest.update(head.encode("utf-8"))
        digest.update(b"\0status\0")
        digest.update(status.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0diff\0")
        digest.update(tracked_diff.encode("utf-8", errors="surrogatepass"))
        for entry in status.split("\0"):
            if not entry.startswith("?? "):
                continue
            relative = entry[3:]
            candidate = (repository / relative).resolve()
            if repository != candidate and repository not in candidate.parents:
                continue
            digest.update(b"\0untracked\0")
            digest.update(relative.encode("utf-8", errors="surrogatepass"))
            if candidate.is_file():
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return {
            "head": head,
            "status": status,
            "fingerprint": digest.hexdigest(),
        }

    def default_branch_sha(
        self,
        project: Dict[str, Any],
        *,
        fetch: bool = True,
    ) -> str:
        """Resolve the current remote default-branch commit after a bounded fetch."""

        repository = self.validate_repository(project)
        branch = str(project.get("default_branch") or "main").strip()
        if not branch:
            raise ControlCenterError(
                "Das Repository hat keinen Default-Branch.",
                code="default_branch_missing",
                status=409,
            )
        valid = self._git(
            repository,
            ["check-ref-format", "--branch", branch],
            check=False,
        )
        if valid.returncode != 0:
            raise ControlCenterError(
                "Der konfigurierte Default-Branch ist ungültig.",
                code="invalid_default_branch",
                status=409,
            )
        if fetch:
            self._git(repository, ["fetch", "--prune", "origin"])
        remote_ref = f"refs/remotes/origin/{branch}^{{commit}}"
        sha = self._git(
            repository,
            ["rev-parse", "--verify", remote_ref],
        ).stdout.strip().lower()
        if not sha:
            raise ControlCenterError(
                "Der aktuelle Default-Branch-SHA konnte nicht aufgelöst werden.",
                code="default_branch_sha_missing",
                status=409,
            )
        return sha

    @staticmethod
    def worktree_path(repository: Path, task_id: str) -> Path:
        safe_task = "".join(
            char.lower() if char.isalnum() or char in "-_" else "-"
            for char in task_id
        ).strip("-")
        root = repository.parent / ".antigravity-worktrees" / repository.name
        target = (root / safe_task).resolve()
        if root.resolve() not in target.parents:
            raise ControlCenterError(
                "Ungültiger Worktree-Zielpfad.",
                code="invalid_worktree_path",
            )
        return target

    def ensure_worktree(
        self,
        project: Dict[str, Any],
        task: Dict[str, Any],
        *,
        fetch: bool = True,
    ) -> Path:
        repository = self.validate_repository(project)
        branch = str(task["branch_name"])
        base_sha = str(task["base_sha"])
        target = self.worktree_path(repository, str(task["id"]))
        if fetch:
            self._git(repository, ["fetch", "--prune", "origin"])
        if target.exists():
            actual = self._git(target, ["rev-parse", "--show-toplevel"]).stdout.strip()
            if Path(actual).resolve() != target:
                raise ControlCenterError(
                    "Der Worktree-Pfad ist belegt, aber kein passender Git-Worktree.",
                    code="worktree_path_conflict",
                    status=409,
                )
            actual_branch = self._git(
                target,
                ["branch", "--show-current"],
            ).stdout.strip()
            if actual_branch != branch:
                raise ControlCenterError(
                    "Der vorhandene Worktree gehört zu einem anderen Branch.",
                    code="worktree_branch_conflict",
                    status=409,
                )
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = (
            self._git(
                repository,
                ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                check=False,
            ).returncode
            == 0
        )
        args = ["worktree", "add"]
        if not branch_exists:
            args.extend(["-b", branch])
        args.append(str(target))
        args.append(branch if branch_exists else base_sha)
        self._git(repository, args)
        self._git(target, ["config", "user.name", "Anti-Gravity Agent"])
        self._git(
            target,
            ["config", "user.email", "antigravity-agent@users.noreply.github.com"],
        )
        return target

    def changed_files(self, worktree: Path, base_sha: str) -> list[str]:
        result = self._git(
            worktree,
            ["diff", "--name-only", f"{base_sha}...HEAD"],
        )
        committed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        dirty = self._git(
            worktree,
            ["status", "--porcelain", "--untracked-files=all"],
        )
        for line in dirty.stdout.splitlines():
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path and path not in committed:
                committed.append(path)
        return committed

    @staticmethod
    def _status_paths(status: str) -> list[str]:
        """Parse exact paths from porcelain v1's NUL-delimited representation."""
        fields = status.split("\0")
        paths: list[str] = []
        index = 0
        while index < len(fields):
            entry = fields[index]
            index += 1
            if len(entry) < 4:
                continue
            state = entry[:2]
            paths.append(entry[3:])
            if ("R" in state or "C" in state) and index < len(fields):
                source = fields[index]
                index += 1
                if source:
                    paths.append(source)
        return paths

    @staticmethod
    def _generated_artifact_reason(path: str) -> str:
        normalized = str(path or "").replace("\\", "/").strip("/")
        if not normalized:
            return ""
        parts = [part.casefold() for part in normalized.split("/") if part]
        if any(part in _GENERATED_DIRECTORY_NAMES for part in parts[:-1]):
            return "generated directory"
        if parts[-1] in _GENERATED_DIRECTORY_NAMES:
            return "generated directory"
        for index in range(len(parts) - 1):
            if (
                parts[index] == "cypress"
                and parts[index + 1] in {"downloads", "screenshots", "videos"}
            ):
                return "Cypress runtime artifact"
            if parts[index] == ".yarn" and parts[index + 1] == "cache":
                return "generated dependency cache"
        filename = parts[-1]
        if filename in _GENERATED_FILE_NAMES:
            return "generated platform file"
        if filename.endswith(_GENERATED_FILE_SUFFIXES):
            return "generated log or compiled artifact"
        return ""

    def assert_commit_hygiene(
        self,
        worktree: Path,
        *,
        base_sha: str = "",
    ) -> None:
        """Reject generated artifacts and whitespace defects before staging."""
        status = self._git(
            worktree,
            [
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
        ).stdout
        offenders = sorted({
            path
            for path in self._status_paths(status)
            if self._generated_artifact_reason(path)
        })
        if offenders:
            shown = offenders[:20]
            remainder = len(offenders) - len(shown)
            detail = ", ".join(shown)
            if remainder:
                detail += f" (+{remainder} weitere)"
            raise ControlCenterError(
                "Repository-Hygiene blockiert den Commit. Generierte "
                "Abhängigkeiten, Build-/Test-Artefakte und Logs müssen entfernt "
                f"oder passend in .gitignore ausgeschlossen werden: {detail}",
                code="repository_hygiene_violation",
                status=409,
            )

        # Build the exact prospective commit in an isolated index. This covers
        # tracked, already-staged, and untracked files while preserving the
        # user's real staging area if the check rejects the change.
        with tempfile.TemporaryDirectory(prefix="ag-commit-index-") as temp_dir:
            env = os.environ.copy()
            env["GIT_INDEX_FILE"] = str(Path(temp_dir) / "index")
            self._git(worktree, ["read-tree", "HEAD"], env=env)
            self._git(worktree, ["add", "--all"], env=env)
            prospective_tree = self._git(
                worktree,
                ["write-tree"],
                env=env,
            ).stdout.strip()
            if base_sha:
                self._git(
                    worktree,
                    ["rev-parse", "--verify", f"{base_sha}^{{commit}}"],
                )
                whitespace = self._git(
                    worktree,
                    ["diff", "--check", base_sha, prospective_tree],
                    check=False,
                )
            else:
                whitespace = self._git(
                    worktree,
                    ["diff", "--cached", "--check"],
                    check=False,
                    env=env,
                )
        if whitespace.returncode != 0:
            detail = (whitespace.stdout or whitespace.stderr).strip()[:4000]
            raise ControlCenterError(
                "Repository-Hygiene blockiert den Commit. Git hat "
                f"Whitespace-Fehler gefunden:\n{detail}",
                code="repository_hygiene_violation",
                status=409,
            )

    def commit_changes(self, worktree: Path, message: str) -> str:
        self.assert_commit_hygiene(worktree)
        status = self._git(
            worktree,
            ["status", "--porcelain", "--untracked-files=all"],
        ).stdout.strip()
        if status:
            self._git(worktree, ["add", "--all"])
            self._git(worktree, ["commit", "-m", message[:250]])
        return self._git(worktree, ["rev-parse", "HEAD"]).stdout.strip().lower()

    def push_branch(self, worktree: Path, branch: str) -> None:
        self._git(
            worktree,
            ["push", "--set-upstream", "origin", branch],
            timeout=max(self.timeout_seconds, 300),
        )

    def _filtered_working_tree_snapshot(
        self,
        worktree: Path,
        *,
        base_sha: str,
    ) -> Dict[str, Any]:
        """Hash the repair overlay without generated task artifacts.

        A separate index seeded from ``base_sha`` makes files introduced by the
        rejected commit untracked for snapshot purposes. Current ignore rules
        are therefore honored even when the rejected HEAD tracked
        ``node_modules``. The hygiene classifier then removes any remaining
        generated paths explicitly before the tree is written.
        """

        with tempfile.TemporaryDirectory(prefix="ag_repair_index_") as temp:
            environment = dict(os.environ)
            environment["GIT_INDEX_FILE"] = str(Path(temp) / "index")
            self._git(
                worktree,
                ["read-tree", str(base_sha).lower()],
                env=environment,
            )
            self._git(worktree, ["add", "--all"], env=environment)
            indexed = self._git(
                worktree,
                ["ls-files", "-z"],
                env=environment,
            ).stdout
            indexed_paths = [path for path in indexed.split("\0") if path]
            generated = sorted(
                path
                for path in indexed_paths
                if self._generated_artifact_reason(path)
            )
            if generated:
                self._git(
                    worktree,
                    ["update-index", "--force-remove", "-z", "--stdin"],
                    env=environment,
                    input_text="\0".join(generated) + "\0",
                )
            tree_hash = self._git(
                worktree,
                ["write-tree"],
                env=environment,
            ).stdout.strip().lower()
            preserved = [
                path for path in indexed_paths if path not in set(generated)
            ]
            return {
                "tree_hash": tree_hash,
                "preserved_paths": preserved,
                "generated_paths": generated,
            }

    def rewind_unpublished_task_commit(
        self,
        project: Dict[str, Any],
        task: Dict[str, Any],
        *,
        expected_head: str,
    ) -> Dict[str, Any]:
        """Move one unpublished task branch back to base without losing files.

        The caller must separately prove that neither a remote ref nor a pull
        request exists. This method only accepts the Hub-owned worktree path and
        ``ag/`` branch for the supplied task, and fails closed on any local
        drift before moving the branch ref.
        """

        repository = self.validate_repository(project)
        task_id = str(task.get("id") or "")
        branch = str(task.get("branch_name") or "").strip()
        base_sha = str(task.get("base_sha") or "").strip().lower()
        old_sha = str(expected_head or "").strip().lower()
        configured = Path(str(task.get("worktree_path") or "")).resolve()
        expected_worktree = self.worktree_path(repository, task_id)

        if configured != expected_worktree:
            raise ControlCenterError(
                "Der Task verweist nicht auf seinen systemeigenen Worktree.",
                code="protected_repair_worktree_mismatch",
                status=409,
            )
        if not configured.is_dir():
            raise ControlCenterError(
                "Der systemeigene Task-Worktree fehlt.",
                code="worktree_missing",
                status=409,
            )
        if not branch.startswith("ag/"):
            raise ControlCenterError(
                "Nur systemeigene ag/-Branches dürfen zurückgesetzt werden.",
                code="protected_repair_branch_not_owned",
                status=409,
            )

        top_level = Path(
            self._git(configured, ["rev-parse", "--show-toplevel"]).stdout.strip()
        ).resolve()
        if top_level != configured:
            raise ControlCenterError(
                "Der konfigurierte Task-Pfad ist nicht die Worktree-Wurzel.",
                code="protected_repair_worktree_mismatch",
                status=409,
            )
        actual_branch = self._git(
            configured,
            ["branch", "--show-current"],
        ).stdout.strip()
        if actual_branch != branch:
            raise ControlCenterError(
                "Der Task-Worktree steht auf einem anderen Branch.",
                code="worktree_branch_conflict",
                status=409,
            )
        actual_head = self._git(
            configured,
            ["rev-parse", "HEAD"],
        ).stdout.strip().lower()
        if not old_sha or actual_head != old_sha:
            raise ControlCenterError(
                "Der lokale Worktree-HEAD entspricht nicht dem abgelehnten SHA.",
                code="protected_repair_head_mismatch",
                status=409,
            )

        verified_base = self._git(
            configured,
            ["rev-parse", "--verify", f"{base_sha}^{{commit}}"],
        ).stdout.strip().lower()
        if verified_base != base_sha or base_sha == old_sha:
            raise ControlCenterError(
                "Der Task besitzt keinen zurücksetzbaren Commit oberhalb des Base-SHA.",
                code="protected_repair_invalid_base",
                status=409,
            )
        ancestor = self._git(
            configured,
            ["merge-base", "--is-ancestor", base_sha, old_sha],
            check=False,
        )
        if ancestor.returncode != 0:
            raise ControlCenterError(
                "Der Base-SHA ist kein Vorfahr des abgelehnten Commits.",
                code="protected_repair_invalid_base",
                status=409,
            )

        overlay = self._filtered_working_tree_snapshot(
            configured,
            base_sha=base_sha,
        )
        all_changed_files = self.changed_files(configured, base_sha)
        changed_files = [
            path
            for path in all_changed_files
            if not self._generated_artifact_reason(path)
        ]
        excluded_generated = [
            path
            for path in all_changed_files
            if self._generated_artifact_reason(path)
        ]
        if not changed_files:
            raise ControlCenterError(
                "Der abgelehnte Commit enthält keinen Repository-Diff.",
                code="protected_repair_empty_diff",
                status=409,
            )

        self._git(configured, ["reset", "--mixed", base_sha])
        new_head = self._git(
            configured,
            ["rev-parse", "HEAD"],
        ).stdout.strip().lower()
        rewound_overlay = self._filtered_working_tree_snapshot(
            configured,
            base_sha=base_sha,
        )
        if (
            new_head != base_sha
            or rewound_overlay["tree_hash"] != overlay["tree_hash"]
        ):
            if new_head == base_sha:
                self._git(configured, ["reset", "--mixed", old_sha])
            raise ControlCenterError(
                "Der sichere Branch-Rücklauf konnte nicht verifiziert werden.",
                code="protected_repair_rewind_verification_failed",
                status=409,
            )
        return {
            "old_sha": old_sha,
            "base_sha": base_sha,
            "branch_name": branch,
            "worktree_path": str(configured),
            "changed_files": changed_files,
            "overlay_tree": overlay["tree_hash"],
            "excluded_generated_count": len(excluded_generated),
            "excluded_generated_sample": excluded_generated[:20],
        }

    def restore_unpublished_task_head(
        self,
        worktree: Path,
        *,
        base_sha: str,
        old_sha: str,
        overlay_tree: str,
    ) -> None:
        """Best-effort compensation if persistence fails after a local rewind."""

        current = self._git(
            worktree,
            ["rev-parse", "HEAD"],
        ).stdout.strip().lower()
        if current != str(base_sha).lower():
            raise ControlCenterError(
                "Der kompensierende Branch-Rücklauf wurde wegen HEAD-Drift verweigert.",
                code="protected_repair_compensation_refused",
                status=409,
            )
        current_overlay = self._filtered_working_tree_snapshot(
            worktree,
            base_sha=str(base_sha).lower(),
        )
        if current_overlay["tree_hash"] != str(overlay_tree).lower():
            raise ControlCenterError(
                "Der kompensierende Branch-Rücklauf wurde wegen Datei-Drift verweigert.",
                code="protected_repair_compensation_refused",
                status=409,
            )
        self._git(worktree, ["reset", "--mixed", str(old_sha).lower()])
        restored_overlay = self._filtered_working_tree_snapshot(
            worktree,
            base_sha=str(base_sha).lower(),
        )
        if restored_overlay["tree_hash"] != str(overlay_tree).lower():
            raise ControlCenterError(
                "Der kompensierende Branch-Rücklauf konnte nicht verifiziert werden.",
                code="protected_repair_compensation_refused",
                status=409,
            )
