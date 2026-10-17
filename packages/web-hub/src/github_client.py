"""
Async GitHub REST API v3 client for Antigravity Web Hub.

Provides repository management, issue/PR CRUD, checks, reviews, refs,
label syncing, and token validation against the GitHub API.
"""

import re
import aiohttp
from typing import Optional, List, Dict, Any


class GitHubAPIError(RuntimeError):
    """Structured GitHub response error without changing RuntimeError callers."""

    def __init__(self, status: int, method: str, path: str, message: str) -> None:
        self.status = int(status)
        self.method = str(method).upper()
        self.path = str(path)
        self.message = str(message)
        super().__init__(
            f"GitHub API error {self.status} on {self.method} {self.path}: "
            f"{self.message}"
        )


# Default labels that Antigravity manages on every linked repo
_DEFAULT_LABELS: List[Dict[str, str]] = [
    {"name": "antigravity-managed", "color": "7B2D8B"},
    {"name": "bug", "color": "d73a4a"},
    {"name": "feature", "color": "0075ca"},
    {"name": "task", "color": "0e8a16"},
]


class GitHubClient:
    """Async GitHub REST API v3 client for repository and issue management."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Antigravity-Hub/1.0",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        """Perform an HTTP request against the GitHub API and return parsed JSON.

        Raises ``RuntimeError`` with a descriptive message on non-2xx responses.
        Returns ``None`` for 204 No Content.
        """
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.request(
                method, url, json=json_body, params=params
            ) as resp:
                if resp.status == 204:
                    return None
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    msg = body.get("message", resp.reason) if isinstance(body, dict) else resp.reason
                    raise GitHubAPIError(resp.status, method, path, str(msg))
                return body

    # ------------------------------------------------------------------
    # Token / User
    # ------------------------------------------------------------------

    async def check_token(self) -> dict:
        """Validates the token and returns authenticated user info.

        Returns dict with keys: login, id, name, avatar_url, html_url.
        """
        data = await self._request("GET", "/user")
        return {
            "login": data["login"],
            "id": data["id"],
            "name": data.get("name", ""),
            "avatar_url": data.get("avatar_url", ""),
            "html_url": data.get("html_url", ""),
        }

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    async def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        auto_init: bool = True,
    ) -> dict:
        """Creates a new GitHub repository.

        Returns dict with: full_name, html_url, clone_url, ssh_url, default_branch.
        """
        payload = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": bool(auto_init),
        }
        data = await self._request("POST", "/user/repos", json_body=payload)
        return {
            "full_name": data["full_name"],
            "html_url": data["html_url"],
            "clone_url": data["clone_url"],
            "ssh_url": data["ssh_url"],
            "default_branch": data.get("default_branch", "main"),
        }

    async def list_repositories(self) -> List[dict]:
        """List repositories owned by the authenticated user, newest first."""
        repositories: List[dict] = []
        for page in range(1, 11):
            data = await self._request(
                "GET",
                "/user/repos",
                params={
                    "affiliation": "owner",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": "100",
                    "page": str(page),
                },
            )
            for item in data:
                owner = item.get("owner") or {}
                repositories.append({
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "full_name": item.get("full_name", ""),
                    "owner": owner.get("login", ""),
                    "html_url": item.get("html_url", ""),
                    "clone_url": item.get("clone_url", ""),
                    "description": item.get("description") or "",
                    "private": bool(item.get("private")),
                    "default_branch": item.get("default_branch") or "main",
                    "updated_at": item.get("updated_at") or "",
                })
            if len(data) < 100:
                break
        return repositories

    async def get_repository(self, owner: str, repo: str) -> dict:
        """Return repository metadata needed by the control plane."""
        data = await self._request("GET", f"/repos/{owner}/{repo}")
        return {
            "id": data["id"],
            "full_name": data["full_name"],
            "html_url": data["html_url"],
            "clone_url": data["clone_url"],
            "ssh_url": data["ssh_url"],
            "private": bool(data.get("private")),
            "default_branch": data.get("default_branch") or "main",
            "archived": bool(data.get("archived")),
            "disabled": bool(data.get("disabled")),
        }

    async def delete_repo(self, owner: str, repo: str) -> bool:
        """Deletes a GitHub repository. Returns ``True`` on success."""
        await self._request("DELETE", f"/repos/{owner}/{repo}")
        return True

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: Optional[List[str]] = None,
    ) -> dict:
        """Creates a GitHub issue. Returns issue metadata dict."""
        payload: Dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        data = await self._request(
            "POST", f"/repos/{owner}/{repo}/issues", json_body=payload
        )
        return {
            "number": data["number"],
            "html_url": data["html_url"],
            "title": data["title"],
            "state": data["state"],
        }

    async def get_issues(
        self, owner: str, repo: str, state: str = "all"
    ) -> List[dict]:
        """Lists issues for a repo, filtering out pull requests."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": "100"},
        )
        # GitHub returns PRs via the issues endpoint — exclude them
        return [
            {
                "number": item["number"],
                "html_url": item["html_url"],
                "title": item["title"],
                "state": item["state"],
                "labels": [lb["name"] for lb in item.get("labels", [])],
            }
            for item in data
            if "pull_request" not in item
        ]

    async def find_issue_by_marker(
        self,
        owner: str,
        repo: str,
        marker: str,
    ) -> Optional[dict]:
        """Find an open or closed issue containing an idempotency marker."""
        for page in range(1, 11):
            data = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues",
                params={"state": "all", "per_page": "100", "page": str(page)},
            )
            for item in data:
                if "pull_request" in item:
                    continue
                if marker in str(item.get("body") or ""):
                    return {
                        "number": item["number"],
                        "html_url": item["html_url"],
                        "title": item["title"],
                        "state": item["state"],
                    }
            if len(data) < 100:
                break
        return None

    async def update_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        state: Optional[str] = None,
        body: Optional[str] = None,
        title: Optional[str] = None,
    ) -> dict:
        """Updates an existing issue (title, body, and/or state)."""
        payload: Dict[str, Any] = {}
        if state is not None:
            payload["state"] = state
        if body is not None:
            payload["body"] = body
        if title is not None:
            payload["title"] = title
        data = await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{number}",
            json_body=payload,
        )
        return {
            "number": data["number"],
            "html_url": data["html_url"],
            "title": data["title"],
            "state": data["state"],
        }

    async def close_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        comment: Optional[str] = None,
    ) -> dict:
        """Closes an issue, optionally adding a closing comment first."""
        current = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{number}",
        )
        if comment:
            await self.add_issue_comment(owner, repo, number, comment)
        if str(current.get("state") or "").lower() != "closed":
            return await self.update_issue(owner, repo, number, state="closed")
        return {
            "number": current["number"],
            "html_url": current["html_url"],
            "title": current["title"],
            "state": current["state"],
        }

    async def add_issue_comment(
        self, owner: str, repo: str, number: int, body: str
    ) -> dict:
        """Adds a comment to an issue."""
        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json_body={"body": body},
        )
        return {
            "id": data["id"],
            "html_url": data["html_url"],
            "body": data["body"],
        }

    # ------------------------------------------------------------------
    # Git refs / branches
    # ------------------------------------------------------------------

    async def get_branch(self, owner: str, repo: str, branch: str) -> dict:
        """Return branch metadata, including the current commit SHA."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches/{branch}",
        )
        return {
            "name": data["name"],
            "sha": data["commit"]["sha"],
            "protected": bool(data.get("protected")),
        }

    async def get_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
    ) -> Optional[dict]:
        """Return a Git ref or ``None`` if GitHub reports it missing."""
        try:
            data = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/git/ref/{ref}",
            )
        except GitHubAPIError as exc:
            if exc.status == 404:
                return None
            raise
        return {
            "ref": data["ref"],
            "sha": data["object"]["sha"],
            "url": data.get("url", ""),
        }

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
        sha: str,
    ) -> dict:
        """Create a branch ref at an exact commit SHA."""
        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        return {
            "ref": data["ref"],
            "sha": data["object"]["sha"],
            "url": data.get("url", ""),
        }

    async def delete_branch(self, owner: str, repo: str, branch: str) -> bool:
        """Delete a branch ref."""
        await self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
        )
        return True

    # ------------------------------------------------------------------
    # Pull requests / review / checks
    # ------------------------------------------------------------------

    @staticmethod
    def _pull_request(data: Dict[str, Any]) -> dict:
        return {
            "number": data["number"],
            "html_url": data["html_url"],
            "title": data["title"],
            "state": data["state"],
            "draft": bool(data.get("draft")),
            "head_sha": (data.get("head") or {}).get("sha", ""),
            "head_ref": (data.get("head") or {}).get("ref", ""),
            "base_ref": (data.get("base") or {}).get("ref", ""),
            "mergeable": data.get("mergeable"),
            "mergeable_state": data.get("mergeable_state", ""),
            "merged": bool(data.get("merged")),
            "merge_commit_sha": data.get("merge_commit_sha") or "",
        }

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = True,
    ) -> dict:
        """Create a pull request, draft by default."""
        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json_body={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": bool(draft),
            },
        )
        return self._pull_request(data)

    async def find_pull_request_by_head(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> Optional[dict]:
        """Find an existing PR for ``owner:branch`` to avoid duplicates."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "all",
                "head": f"{owner}:{branch}",
                "per_page": "100",
            },
        )
        return self._pull_request(data[0]) if data else None

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> dict:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
        )
        return self._pull_request(data)

    async def update_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        base: Optional[str] = None,
    ) -> dict:
        payload: Dict[str, Any] = {}
        for key, value in {
            "title": title,
            "body": body,
            "state": state,
            "base": base,
        }.items():
            if value is not None:
                payload[key] = value
        data = await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{number}",
            json_body=payload,
        )
        return self._pull_request(data)

    async def mark_pull_request_ready(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> dict:
        """Convert a draft PR to ready using GitHub's GraphQL mutation."""
        pull = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
        )
        node_id = pull["node_id"]
        query = """
        mutation($pullRequestId: ID!) {
          markPullRequestReadyForReview(input: {pullRequestId: $pullRequestId}) {
            pullRequest { number url isDraft }
          }
        }
        """
        data = await self._request(
            "POST",
            "/graphql",
            json_body={"query": query, "variables": {"pullRequestId": node_id}},
        )
        result = data["data"]["markPullRequestReadyForReview"]["pullRequest"]
        return {
            "number": result["number"],
            "html_url": result["url"],
            "draft": bool(result["isDraft"]),
        }

    async def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> List[dict]:
        files: List[dict] = []
        for page in range(1, 31):
            data = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": "100", "page": str(page)},
            )
            files.extend(
                {
                    "filename": item["filename"],
                    "status": item["status"],
                    "additions": int(item.get("additions") or 0),
                    "deletions": int(item.get("deletions") or 0),
                    "changes": int(item.get("changes") or 0),
                    "previous_filename": item.get("previous_filename", ""),
                }
                for item in data
            )
            if len(data) < 100:
                break
        return files

    async def get_check_runs(
        self,
        owner: str,
        repo: str,
        sha: str,
    ) -> List[dict]:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
            params={"per_page": "100"},
        )
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "status": item["status"],
                "conclusion": item.get("conclusion"),
                "html_url": item.get("html_url", ""),
                "started_at": item.get("started_at"),
                "completed_at": item.get("completed_at"),
            }
            for item in data.get("check_runs", [])
        ]

    async def get_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
    ) -> dict:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{sha}/status",
        )
        return {
            "state": data["state"],
            "statuses": [
                {
                    "context": item["context"],
                    "state": item["state"],
                    "description": item.get("description", ""),
                    "target_url": item.get("target_url", ""),
                }
                for item in data.get("statuses", [])
            ],
        }

    async def get_pull_request_reviews(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> List[dict]:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            params={"per_page": "100"},
        )
        return [
            {
                "id": item["id"],
                "state": item["state"],
                "body": item.get("body") or "",
                "user": (item.get("user") or {}).get("login", ""),
                "commit_id": item.get("commit_id", ""),
                "submitted_at": item.get("submitted_at"),
            }
            for item in data
        ]

    async def get_review_comments(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> List[dict]:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}/comments",
            params={"per_page": "100"},
        )
        return [
            {
                "id": item["id"],
                "body": item.get("body") or "",
                "path": item.get("path") or "",
                "line": item.get("line") or item.get("original_line"),
                "user": (item.get("user") or {}).get("login", ""),
                "commit_id": item.get("commit_id", ""),
                "html_url": item.get("html_url", ""),
            }
            for item in data
        ]

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        commit_title: str = "",
        commit_message: str = "",
        merge_method: str = "squash",
        expected_sha: str = "",
    ) -> dict:
        if merge_method not in {"merge", "squash", "rebase"}:
            raise ValueError("merge_method must be merge, squash, or rebase")
        payload: Dict[str, Any] = {"merge_method": merge_method}
        if expected_sha:
            payload["sha"] = expected_sha
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        data = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            json_body=payload,
        )
        return {
            "sha": data.get("sha", ""),
            "merged": bool(data.get("merged")),
            "message": data.get("message", ""),
        }

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    async def ensure_labels(
        self, owner: str, repo: str, labels: Optional[List[Dict[str, str]]] = None
    ) -> None:
        """Creates default Antigravity labels if they don't already exist.

        ``labels`` overrides the built-in defaults when provided.
        Each entry must have ``name`` and ``color`` keys.
        """
        desired = labels or _DEFAULT_LABELS
        existing_data = await self._request(
            "GET", f"/repos/{owner}/{repo}/labels", params={"per_page": "100"}
        )
        existing_names = {lb["name"].lower() for lb in existing_data}

        for label in desired:
            if label["name"].lower() not in existing_names:
                await self._request(
                    "POST",
                    f"/repos/{owner}/{repo}/labels",
                    json_body={"name": label["name"], "color": label["color"]},
                )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def slugify(name: str) -> str:
        """Converts a project name to a valid GitHub repository name.

        * lowercased
        * spaces and special characters replaced with hyphens
        * consecutive hyphens collapsed
        * leading/trailing hyphens stripped
        """
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9\-]", "-", slug)
        slug = re.sub(r"-{2,}", "-", slug)
        return slug.strip("-")
