"""Unit tests for GitHub control-plane API primitives."""

import unittest
from unittest.mock import AsyncMock

from src.github_client import GitHubClient


class TestGitHubControlPlaneClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = GitHubClient("test-token")
        self.client._request = AsyncMock()

    async def test_issue_marker_prevents_duplicate_remote_issue(self):
        self.client._request.return_value = [
            {
                "number": 7,
                "html_url": "https://github.test/o/r/issues/7",
                "title": "Task",
                "state": "open",
                "body": "Details\n<!-- antigravity-task:TASK-1 -->",
            }
        ]
        issue = await self.client.find_issue_by_marker(
            "o",
            "r",
            "<!-- antigravity-task:TASK-1 -->",
        )
        self.assertEqual(issue["number"], 7)
        self.client._request.assert_awaited_once_with(
            "GET",
            "/repos/o/r/issues",
            params={"state": "all", "per_page": "100", "page": "1"},
        )

    async def test_draft_pull_request_contract(self):
        self.client._request.return_value = {
            "number": 3,
            "html_url": "https://github.test/o/r/pull/3",
            "title": "Change",
            "state": "open",
            "draft": True,
            "head": {"sha": "a" * 40, "ref": "ag/task"},
            "base": {"ref": "main"},
            "mergeable": None,
            "mergeable_state": "unknown",
            "merged": False,
        }
        pull = await self.client.create_pull_request(
            "o",
            "r",
            title="Change",
            head="ag/task",
            base="main",
            body="Evidence pending",
        )
        self.assertTrue(pull["draft"])
        self.assertEqual(pull["head_sha"], "a" * 40)
        request = self.client._request.await_args
        self.assertEqual(request.args[:2], ("POST", "/repos/o/r/pulls"))
        self.assertTrue(request.kwargs["json_body"]["draft"])

    async def test_checks_and_commit_status_are_normalized(self):
        self.client._request.side_effect = [
            {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "unit",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://checks/1",
                    }
                ]
            },
            {
                "state": "success",
                "statuses": [
                    {
                        "context": "legacy",
                        "state": "success",
                        "description": "ok",
                        "target_url": "https://status/1",
                    }
                ],
            },
        ]
        checks = await self.client.get_check_runs("o", "r", "a" * 40)
        status = await self.client.get_commit_status("o", "r", "a" * 40)
        self.assertEqual(checks[0]["conclusion"], "success")
        self.assertEqual(status["state"], "success")

    async def test_merge_method_is_validated_before_network(self):
        with self.assertRaises(ValueError):
            await self.client.merge_pull_request(
                "o",
                "r",
                1,
                merge_method="force",
            )
        self.client._request.assert_not_awaited()

    async def test_merge_uses_expected_sha_precondition(self):
        self.client._request.return_value = {
            "sha": "b" * 40,
            "merged": True,
            "message": "merged",
        }
        await self.client.merge_pull_request(
            "o",
            "r",
            4,
            expected_sha="a" * 40,
        )
        request = self.client._request.await_args
        self.assertEqual(request.kwargs["json_body"]["sha"], "a" * 40)

    async def test_close_issue_is_idempotent_when_pr_already_closed_it(self):
        self.client._request.side_effect = [
            {
                "number": 1,
                "html_url": "https://github.test/o/r/issues/1",
                "title": "Proof",
                "state": "closed",
            },
            {
                "id": 9,
                "html_url": "https://github.test/o/r/issues/1#issuecomment-9",
                "body": "Merged.",
            },
        ]
        closed = await self.client.close_issue(
            "o",
            "r",
            1,
            comment="Merged.",
        )
        self.assertEqual(closed["state"], "closed")
        methods = [call.args[0] for call in self.client._request.await_args_list]
        self.assertEqual(methods, ["GET", "POST"])


if __name__ == "__main__":
    unittest.main()
