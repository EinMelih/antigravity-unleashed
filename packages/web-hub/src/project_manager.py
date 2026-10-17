import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.database import db
from src.config import config


_HUB_GIT_NAME = "Anti-Gravity Hub"
_HUB_GIT_EMAIL = "antigravity-hub@localhost"


def run_git_command(project_path: str, args: List[str]) -> subprocess.CompletedProcess:
    """Helper to run a git command in the context of the project path."""
    return subprocess.run(
        ["git"] + args,
        cwd=project_path,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )


def git_is_repo(project_path: str) -> bool:
    """Checks if the directory is a git repository."""
    ret = run_git_command(project_path, ["rev-parse", "--is-inside-work-tree"])
    return ret.returncode == 0


def git_has_commit(project_path: str) -> bool:
    """Return whether the repository has a resolvable HEAD commit."""
    ret = run_git_command(project_path, ["rev-parse", "--verify", "HEAD"])
    return ret.returncode == 0


def _enrich_project_status(project: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve local Git state for one project without mutating DB rows."""
    item = dict(project)
    project_path = str(item["path"])
    path_exists = Path(project_path).exists()
    item["git_branch"] = (
        git_current_branch(project_path) if path_exists else "directory_missing"
    )
    has_github = bool(item.get("github_owner") and item.get("github_repo"))
    local_ready = path_exists and git_has_commit(project_path)
    persisted_setup = str(item.get("github_setup_status") or "not_requested")
    item["github_bootstrap_required"] = has_github and (
        not local_ready or persisted_setup == "repair_required"
    )
    item["github_bootstrap_status"] = (
        "repair_required"
        if item["github_bootstrap_required"]
        else ("ready" if has_github else "not_linked")
    )
    item["antigravity_linked"] = bool(item.get("integrity_workspace_path"))
    item["antigravity_project_name"] = str(
        item.get("antigravity_project_name") or ""
    )
    return item


def _git_failure(result: subprocess.CompletedProcess, fallback: str) -> str:
    return (result.stderr or result.stdout or fallback).strip()


def git_init(project_path: str) -> bool:
    """Initialize a repository and guarantee a bootstrap commit.

    The Hub uses command-local author settings so it never changes the user's
    global Git configuration.
    """
    if not git_is_repo(project_path):
        ret = run_git_command(project_path, ["init", "-b", "main"])
        if ret.returncode != 0:
            ret = run_git_command(project_path, ["init"])
        if ret.returncode != 0:
            return False
    if git_has_commit(project_path):
        return True
    branch = run_git_command(project_path, ["branch", "-M", "main"])
    if branch.returncode != 0:
        return False
    staged = run_git_command(project_path, ["add", "-A"])
    if staged.returncode != 0:
        return False
    commit = run_git_command(
        project_path,
        [
            "-c",
            f"user.name={_HUB_GIT_NAME}",
            "-c",
            f"user.email={_HUB_GIT_EMAIL}",
            "commit",
            "--allow-empty",
            "-m",
            "Initial commit from Anti-Gravity Hub",
        ],
    )
    return commit.returncode == 0


def git_current_branch(project_path: str) -> str:
    """Gets the name of the current active branch."""
    ret = run_git_command(project_path, ["branch", "--show-current"])
    if ret.returncode == 0:
        return ret.stdout.strip()
    return "unknown"


def git_create_and_checkout_branch(project_path: str, branch_name: str) -> bool:
    """Creates a new branch and checks it out. If it exists, checks it out."""
    ret = run_git_command(project_path, ["show-ref", f"refs/heads/{branch_name}"])
    if ret.returncode == 0:
        # Checkout existing branch
        ret_co = run_git_command(project_path, ["checkout", branch_name])
        return ret_co.returncode == 0
    else:
        # Create and checkout
        ret_co = run_git_command(project_path, ["checkout", "-b", branch_name])
        return ret_co.returncode == 0


def git_checkout(project_path: str, branch_name: str) -> bool:
    """Checks out an existing branch."""
    ret = run_git_command(project_path, ["checkout", branch_name])
    return ret.returncode == 0


def git_status(project_path: str) -> str:
    """Gets the porcelain git status output."""
    ret = run_git_command(project_path, ["status", "--porcelain"])
    if ret.returncode == 0:
        return ret.stdout
    return ""


def git_diff(project_path: str) -> str:
    """Gets the unstaged and staged git diff of the repository."""
    ret = run_git_command(project_path, ["diff", "HEAD"])
    if ret.returncode == 0:
        return ret.stdout
    return ""


def git_commit(project_path: str, message: str) -> bool:
    """Stages all changes and commits them with the given message.
    If the project path points to the global config directory, we run sync_config.py.
    """
    pp = Path(project_path).resolve()
    if pp.name == "config" and (pp.parent.name == ".gemini" or "config" in pp.parts):
        import sys
        sync_script = pp / "sync_config.py"
        if sync_script.exists():
            ret = subprocess.run(
                [sys.executable, "-Xutf8", str(sync_script), "--msg", message],
                cwd=str(pp),
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return ret.returncode == 0

    run_git_command(project_path, ["add", "-A"])
    ret = run_git_command(project_path, ["commit", "-m", message])
    return ret.returncode == 0


def git_discard_changes(project_path: str) -> bool:
    """Discards all local unstaged and staged changes, including untracked files."""
    run_git_command(project_path, ["reset", "--hard", "HEAD"])
    ret_clean = run_git_command(project_path, ["clean", "-fd"])
    return ret_clean.returncode == 0


def git_push(project_path: str, remote: str = "origin", branch: str = None) -> bool:
    """Pushes the current branch to the specified remote."""
    if not branch:
        branch = git_current_branch(project_path)
    ret = run_git_command(project_path, ["push", remote, branch])
    return ret.returncode == 0


# ============================================================
# Issue-type to GitHub label mapping
# ============================================================
_ISSUE_TYPE_LABELS = {
    "bug": "bug",
    "feature": "feature",
    "task": "task",
}


class ProjectManager:
    """Business logic coordinating projects, issues, database persistence and Git sandboxing."""

    @staticmethod
    async def register_project(
        name: str,
        test_command: str = "python -m unittest",
        custom_path: Optional[str] = None,
        existing_github_url: Optional[str] = None,
        create_github: bool = True,
        github_private: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Register a Hub repo, either by creating it or importing an existing one."""
        from src.github_client import GitHubClient
        slug = GitHubClient.slugify(name)

        existing_url = str(existing_github_url or "").strip().rstrip("/")
        repo_match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?",
            existing_url,
            re.IGNORECASE,
        ) if existing_url else None
        if existing_url and not repo_match:
            raise ValueError("existing_github_url must be a https://github.com/<owner>/<repo> URL")

        if custom_path and custom_path.strip():
            project_dir = Path(custom_path.strip()).resolve()
            project_dir.mkdir(parents=True, exist_ok=True)
        else:
            base = Path(config.projects_base_dir)
            base.mkdir(parents=True, exist_ok=True)
            project_dir = base / slug
            project_dir.mkdir(parents=True, exist_ok=True)

        project_path = str(project_dir.resolve())

        # GitHub integration (optional)
        github_url = ""
        github_owner = ""
        github_repo = ""
        default_branch = "main"
        github_error = ""

        if repo_match:
            github_owner, github_repo = repo_match.group(1), repo_match.group(2)
            github_url = f"https://github.com/{github_owner}/{github_repo}"
            contents = list(project_dir.iterdir())
            if not git_is_repo(project_path):
                if contents:
                    raise ValueError("The selected local path is not empty and is not a Git repository.")
                result = subprocess.run(
                    ["git", "clone", github_url + ".git", project_path],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                if result.returncode != 0:
                    raise ValueError(f"GitHub repository could not be cloned: {result.stderr.strip()}")
            remote = run_git_command(project_path, ["remote", "get-url", "origin"])
            if remote.returncode != 0:
                run_git_command(project_path, ["remote", "add", "origin", github_url + ".git"])
            else:
                normalize_remote = lambda value: value.strip().lower().removesuffix(".git").rstrip("/")
                if normalize_remote(remote.stdout) != normalize_remote(github_url):
                    raise ValueError(
                        f"The selected local clone belongs to {remote.stdout.strip()}, not {github_url}."
                    )
            default_branch = git_current_branch(project_path)
        else:
            # New Hub projects start as local Git repositories and optionally
            # create their GitHub counterpart when credentials are configured.
            if not git_init(project_path):
                raise RuntimeError(f"Git repository could not be initialized: {project_path}")

        if not repo_match and create_github and config.github_configured:
            try:
                gh = GitHubClient(config.github_token)
                is_private = (
                    config.default_repo_visibility == "private"
                    if github_private is None
                    else bool(github_private)
                )
                repo_data = await gh.create_repo(
                    slug,
                    description=f"Antigravity-managed project: {name}",
                    private=is_private,
                    auto_init=False,
                )

                github_url = repo_data["html_url"]
                full_name = str(repo_data.get("full_name") or "")
                owner_from_api, separator, repo_from_api = full_name.partition("/")
                github_owner = owner_from_api if separator else config.github_owner
                github_repo = repo_from_api if separator else slug
                default_branch = repo_data.get("default_branch", "main")

                # Set remote and push
                remote = run_git_command(project_path, ["remote", "get-url", "origin"])
                if remote.returncode == 0:
                    remote_update = run_git_command(
                        project_path,
                        ["remote", "set-url", "origin", repo_data["clone_url"]],
                    )
                else:
                    remote_update = run_git_command(
                        project_path,
                        ["remote", "add", "origin", repo_data["clone_url"]],
                    )
                if remote_update.returncode != 0:
                    github_error = (
                        "GitHub repository was created, but origin could not be configured: "
                        + _git_failure(remote_update, "unknown Git error")
                    )
                else:
                    push = run_git_command(
                        project_path,
                        ["push", "-u", "origin", f"HEAD:{default_branch}"],
                    )
                    if push.returncode != 0:
                        github_error = (
                            "GitHub repository was created, but the initial push failed: "
                            + _git_failure(push, "unknown Git error")
                        )

                # Ensure Antigravity labels on the repo
                try:
                    await gh.ensure_labels(github_owner, github_repo)
                except Exception as label_error:
                    github_error = github_error or (
                        f"GitHub repository was created, but labels failed: {label_error}"
                    )
            except Exception as e:
                github_error = str(e)
                print(f"[ProjectManager] GitHub setup failed (non-fatal): {e}", flush=True)
        elif not repo_match and create_github:
            github_error = "GitHub authentication is not configured."

        # Register in database
        source_kind = "github" if github_owner and github_repo else "hub"
        project_id = db.add_project(
            name, project_path, test_command,
            github_url=github_url,
            github_owner=github_owner,
            github_repo=github_repo,
            default_branch=default_branch,
            source_kind=source_kind,
        )
        github_setup_status = (
            "not_requested"
            if not create_github
            else ("repair_required" if github_error else "ready")
        )
        db.update_project_github_setup(
            project_id,
            github_setup_status,
            github_error,
        )

        return {
            "id": project_id,
            "name": name,
            "path": project_path,
            "test_command": test_command,
            "git_branch": git_current_branch(project_path),
            "github_url": github_url,
            "github_owner": github_owner,
            "github_repo": github_repo,
            "github_error": github_error,
            "github_setup_status": github_setup_status,
            "github_setup_error": github_error,
            "github_bootstrap_required": github_setup_status == "repair_required",
            "source_kind": source_kind,
            "integrity_workspace_path": "",
            "integrity_project_uuid": "",
            "integrity_linked": False,
        }

    @staticmethod
    async def reconcile_github_repository(project_id: int) -> Dict[str, Any]:
        """Repair and verify the local-to-GitHub bootstrap for one project.

        This operation is idempotent. If GitHub already owns the only commit
        (for example after an older ``auto_init`` workflow), an unborn local
        repository adopts that branch before the verified push.
        """
        from src.github_client import GitHubClient

        project = db.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        owner = str(project.get("github_owner") or "").strip()
        repo = str(project.get("github_repo") or "").strip()
        if not owner or not repo:
            raise ValueError("Project is not linked to a GitHub repository")
        if not config.github_configured:
            raise RuntimeError("GitHub authentication is not configured")

        project_path = str(Path(project["path"]).resolve())
        if not Path(project_path).is_dir():
            raise ValueError(f"Local project directory does not exist: {project_path}")

        gh = GitHubClient(config.github_token)
        metadata = await gh.get_repository(owner, repo)
        github_url = str(metadata["html_url"])
        clone_url = str(metadata["clone_url"])
        default_branch = str(metadata.get("default_branch") or "main")

        if not git_is_repo(project_path):
            if not git_init(project_path):
                raise RuntimeError("Local Git repository could not be initialized")

        remote = run_git_command(project_path, ["remote", "get-url", "origin"])
        remote_args = (
            ["remote", "set-url", "origin", clone_url]
            if remote.returncode == 0
            else ["remote", "add", "origin", clone_url]
        )
        remote_update = run_git_command(project_path, remote_args)
        if remote_update.returncode != 0:
            raise RuntimeError(
                "GitHub origin could not be configured: "
                + _git_failure(remote_update, "unknown Git error")
            )

        remote_probe = run_git_command(
            project_path,
            [
                "ls-remote",
                "--exit-code",
                "--heads",
                "origin",
                f"refs/heads/{default_branch}",
            ],
        )
        remote_has_branch = remote_probe.returncode == 0
        if remote_probe.returncode not in {0, 2}:
            raise RuntimeError(
                "GitHub branch could not be inspected: "
                + _git_failure(remote_probe, "unknown Git error")
            )

        if remote_has_branch:
            fetched = run_git_command(
                project_path,
                ["fetch", "origin", default_branch],
            )
            if fetched.returncode != 0:
                raise RuntimeError(
                    "GitHub branch could not be fetched: "
                    + _git_failure(fetched, "unknown Git error")
                )
            remote_ref = f"refs/remotes/origin/{default_branch}"
            if not git_has_commit(project_path):
                checkout = run_git_command(
                    project_path,
                    ["checkout", "-B", default_branch, remote_ref],
                )
                if checkout.returncode != 0:
                    raise RuntimeError(
                        "Local branch could not adopt the GitHub bootstrap: "
                        + _git_failure(checkout, "unknown Git error")
                    )
            else:
                remote_is_ancestor = run_git_command(
                    project_path,
                    ["merge-base", "--is-ancestor", remote_ref, "HEAD"],
                )
                local_is_ancestor = run_git_command(
                    project_path,
                    ["merge-base", "--is-ancestor", "HEAD", remote_ref],
                )
                if remote_is_ancestor.returncode == 0:
                    pass
                elif local_is_ancestor.returncode == 0:
                    fast_forward = run_git_command(
                        project_path,
                        ["merge", "--ff-only", remote_ref],
                    )
                    if fast_forward.returncode != 0:
                        raise RuntimeError(
                            "Local branch could not be fast-forwarded: "
                            + _git_failure(fast_forward, "unknown Git error")
                        )
                else:
                    raise RuntimeError(
                        "Local and GitHub history diverged. The Hub will not overwrite either side."
                    )
        elif not git_init(project_path):
            raise RuntimeError("Local bootstrap commit could not be created")

        current_branch = git_current_branch(project_path)
        if current_branch != default_branch:
            renamed = run_git_command(
                project_path,
                ["branch", "-M", default_branch],
            )
            if renamed.returncode != 0:
                raise RuntimeError(
                    "Local default branch could not be selected: "
                    + _git_failure(renamed, "unknown Git error")
                )

        push = run_git_command(
            project_path,
            ["push", "-u", "origin", f"HEAD:{default_branch}"],
        )
        if push.returncode != 0:
            raise RuntimeError(
                "GitHub push failed: " + _git_failure(push, "unknown Git error")
            )

        await gh.ensure_labels(owner, repo)
        db.update_project_github(
            project_id,
            github_url,
            owner,
            repo,
            default_branch=default_branch,
        )
        db.update_project_github_setup(project_id, "ready", "")
        refreshed = db.get_project(project_id) or project
        refreshed.update(
            {
                "git_branch": git_current_branch(project_path),
                "github_bootstrap_required": False,
                "github_bootstrap_status": "ready",
                "antigravity_linked": bool(
                    refreshed.get("integrity_workspace_path")
                ),
            }
        )
        return refreshed

    @staticmethod
    def get_projects(*, include_archived: bool = False) -> List[Dict[str, Any]]:
        projects = (
            db.get_projects(
                source_kind="github",
                include_archived=include_archived,
            )
            + db.get_projects(
                source_kind="hub",
                include_archived=include_archived,
            )
        )
        projects.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        if not projects:
            return []
        worker_count = min(8, len(projects))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="project-git-status",
        ) as executor:
            return list(executor.map(_enrich_project_status, projects))

    @staticmethod
    async def import_github_repository(
        repository: Dict[str, Any],
        custom_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import one authenticated GitHub repository into an explicit local folder."""
        owner = str(repository.get("owner") or "").strip()
        repo = str(repository.get("name") or "").strip()
        full_name = str(repository.get("full_name") or f"{owner}/{repo}").strip()
        if not owner or not repo or full_name.lower() != f"{owner}/{repo}".lower():
            raise ValueError("Invalid GitHub repository metadata")

        github_url = str(repository.get("html_url") or f"https://github.com/{owner}/{repo}")
        clone_url = str(repository.get("clone_url") or github_url + ".git")
        default_branch = str(repository.get("default_branch") or "main")

        existing = db.get_project_by_github(owner, repo)
        requested_path = str(custom_path or "").strip()
        if requested_path:
            project_dir = Path(requested_path).expanduser()
            if not project_dir.is_absolute():
                raise ValueError("The local project path must be an absolute path.")
            project_dir = project_dir.resolve()
            if project_dir.parent == project_dir:
                raise ValueError("A drive root cannot be used as a project folder.")
            if existing and project_dir != Path(existing["path"]).resolve():
                raise ValueError(
                    "This GitHub repository is already registered at a different local path."
                )
        elif existing:
            project_dir = Path(existing["path"]).resolve()
        else:
            project_dir = (Path(config.projects_base_dir).expanduser().resolve() / repo)

        if project_dir.exists():
            if not git_is_repo(str(project_dir)):
                raise ValueError(
                    f"The automatic clone target already exists and is not a Git repository: {project_dir}"
                )
            remote = run_git_command(str(project_dir), ["remote", "get-url", "origin"])
            normalize = lambda value: value.strip().lower().removesuffix(".git").rstrip("/")
            if remote.returncode != 0 or normalize(remote.stdout) != normalize(github_url):
                actual = remote.stdout.strip() if remote.returncode == 0 else "no origin"
                raise ValueError(
                    f"The existing clone at {project_dir} belongs to {actual}, not {github_url}."
                )
        else:
            project_dir.parent.mkdir(parents=True, exist_ok=True)
            if shutil.which("gh"):
                result = subprocess.run(
                    ["gh", "repo", "clone", full_name, str(project_dir)],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            else:
                result = subprocess.run(
                    ["git", "clone", clone_url, str(project_dir)],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            if result.returncode != 0:
                raise ValueError(
                    f"GitHub repository could not be cloned: {result.stderr.strip()}"
                )

        project_name = repo
        if not existing:
            conflicting = db.get_project_by_name(project_name)
            if conflicting:
                project_name = full_name
            project_id = db.add_project(
                project_name,
                str(project_dir),
                "python -m unittest",
                github_url=github_url,
                github_owner=owner,
                github_repo=repo,
                default_branch=default_branch,
                source_kind="github",
            )
        else:
            project_id = int(existing["id"])
            db.promote_github_project(
                project_id,
                existing.get("name") or project_name,
                str(project_dir),
                github_url,
                owner,
                repo,
                default_branch,
            )

        project = db.get_project(project_id)
        project["git_branch"] = git_current_branch(str(project_dir))
        project["antigravity_linked"] = bool(project.get("integrity_workspace_path"))
        return project

    @staticmethod
    def delete_project(project_id: int) -> bool:
        """Physically delete a project for internal/test cleanup only."""
        project = db.get_project(project_id)
        if not project:
            return False
        db.delete_project(project_id)
        return True

    @staticmethod
    async def add_issue(
        project_id: int,
        title: str,
        description: str,
        source: str = "manual",
        issue_type: str = "task",
    ) -> Dict[str, Any]:
        """Add an issue to the local DB and optionally mirror it on GitHub."""
        from src.github_client import GitHubClient

        project = db.get_project(project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} does not exist.")

        # 1. Add to local DB
        issue_id = db.add_issue(
            project_id, title, description,
            source=source, status="pending", issue_type=issue_type,
        )

        github_number = None
        github_url = ""

        # 2. Create on GitHub if the project is linked
        gh_owner = project.get("github_owner", "")
        gh_repo = project.get("github_repo", "")
        if gh_owner and gh_repo and config.github_token:
            try:
                gh = GitHubClient(config.github_token)
                label = _ISSUE_TYPE_LABELS.get(issue_type, "task")
                gh_issue = await gh.create_issue(
                    gh_owner, gh_repo, title,
                    body=description,
                    labels=[label, "antigravity-managed"],
                )
                github_number = gh_issue["number"]
                github_url = gh_issue["html_url"]

                # Update local issue with GitHub metadata
                db.update_issue_github(issue_id, github_number, github_url)
            except Exception as e:
                print(f"[ProjectManager] GitHub issue creation failed (non-fatal): {e}", flush=True)

        return {
            "id": issue_id,
            "project_id": project_id,
            "title": title,
            "description": description,
            "source": source,
            "status": "pending",
            "issue_type": issue_type,
            "github_number": github_number,
            "github_url": github_url,
        }

    @staticmethod
    async def sync_issues_from_github(project_id: int) -> Dict[str, Any]:
        """Sync issues from GitHub to local DB for a project.

        1. Gets all issues from GitHub
        2. Creates locally missing issues (by github_number)
        3. Updates status of existing local issues based on GitHub state
        Returns count of new and updated issues.
        """
        from src.github_client import GitHubClient

        project = db.get_project(project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} does not exist.")

        gh_owner = project.get("github_owner", "")
        gh_repo = project.get("github_repo", "")
        if not gh_owner or not gh_repo or not config.github_token:
            return {"new": 0, "updated": 0, "error": "GitHub not configured for this project"}

        gh = GitHubClient(config.github_token)
        gh_issues = await gh.get_issues(gh_owner, gh_repo, state="all")

        new_count = 0
        updated_count = 0

        for gh_issue in gh_issues:
            gh_number = gh_issue["number"]
            local_issue = db.get_issue_by_github_number(project_id, gh_number)

            if not local_issue:
                # Determine issue_type from labels
                labels = gh_issue.get("labels", [])
                issue_type = "task"
                for label in labels:
                    if label in ("bug", "feature", "task"):
                        issue_type = label
                        break

                issue_id = db.add_issue(
                    project_id,
                    gh_issue["title"],
                    f"Synced from GitHub #{gh_number}",
                    source="github",
                    status="pending" if gh_issue["state"] == "open" else "done",
                    issue_type=issue_type,
                )
                db.update_issue_github(issue_id, gh_number, gh_issue["html_url"])
                new_count += 1
            else:
                # Update status based on GitHub state
                new_status = "pending" if gh_issue["state"] == "open" else "done"
                if local_issue.get("status") != new_status:
                    db.update_issue_status(local_issue["id"], new_status)
                    updated_count += 1

        return {"new": new_count, "updated": updated_count}

    @staticmethod
    def get_issues(project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return db.get_issues(project_id)

    @staticmethod
    def prepare_issue_sandbox(issue_id: int) -> str:
        """Prepares a Git sandbox branch `ag-run-<issue_id>` for working on the issue."""
        issue = db.get_issue(issue_id)
        if not issue:
            raise ValueError(f"Issue with ID {issue_id} not found.")

        project = db.get_project(issue["project_id"])
        if not project:
            raise ValueError(f"Project with ID {issue['project_id']} not found.")

        p_path = project["path"]
        branch_name = f"ag-run-{issue_id}"

        # Switch to sandbox branch
        success = git_create_and_checkout_branch(p_path, branch_name)
        if not success:
            raise RuntimeError(f"Could not switch to sandbox branch: {branch_name}")

        return branch_name
