"""Shared validation and identifiers for the Hub control plane."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict


RISK_LEVELS = {"low", "medium", "high", "critical"}
RECOMMENDATION_STATES = {"new", "accepted", "deferred", "rejected"}
CONTROL_MODES = {"observer", "guided", "campaign", "autopilot"}
ENTITY_TYPES = {
    "recommendation",
    "idea_seed",
    "idea_group",
    "design_document",
    "planning_job",
    "adr",
    "campaign",
    "pr_candidate",
    "work_order",
    "agent_task",
    "evidence_pack",
    "deployment",
}
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")

PLANNING_DEPTHS = {"compact", "balanced", "deep", "exhaustive"}
ACTIVATION_POLICIES = {"per_candidate", "campaign_wave", "autopilot"}
QUESTION_STATES = {
    "open",
    "researching",
    "answered",
    "grounded",
    "assumption-accepted",
    "discovery-assigned",
    "deferred",
    "contradiction",
    "resolved",
}
FINDING_CLASSES = {"BLOCKER", "REQUIRED", "QUESTION", "SUGGESTION", "NIT"}
TASK_STATES = {
    "queued",
    "leased",
    "running",
    "waiting_ci",
    "waiting_review",
    "waiting_human",
    "repair",
    "paused",
    "failed",
    "completed",
    "cancelled",
}


class ControlCenterError(Exception):
    """Expected validation or state-machine failure."""

    def __init__(self, message: str, *, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def canonical_json_sha256(value: Any) -> str:
    """Hash a JSON-compatible value with the control plane's canonical encoding."""
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def git_head(project: Dict[str, Any]) -> str:
    path = str(project.get("path") or "").strip()
    if not path or not Path(path).is_dir():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip().lower() if result.returncode == 0 else ""


def git_file_at_sha(
    project: Dict[str, Any],
    sha: str,
    relative_path: str,
) -> str | None:
    """Read one repository-relative blob from an exact local Git commit."""
    root = str(project.get("path") or "").strip()
    if not root or not Path(root).is_dir() or not SHA_PATTERN.fullmatch(str(sha)):
        return None
    try:
        prefix = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-prefix"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if prefix.returncode != 0:
            return None
        object_path = (
            prefix.stdout.strip().replace("\\", "/") + relative_path
        )
        object_spec = f"{sha}:{object_path}"
        size = subprocess.run(
            ["git", "-C", root, "cat-file", "-s", object_spec],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if size.returncode != 0 or int(size.stdout.strip() or 0) > 2_000_000:
            return None
        result = subprocess.run(
            ["git", "-C", root, "show", object_spec],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def clean_text(value: Any, field: str, *, minimum: int = 1, maximum: int = 10000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise ControlCenterError(f"{field} ist erforderlich.", code=f"missing_{field}")
    if len(text) > maximum:
        raise ControlCenterError(
            f"{field} darf höchstens {maximum} Zeichen enthalten.",
            code=f"{field}_too_long",
        )
    return text


def validate_acceptance_criteria(value: Any) -> list[str]:
    """Return normalized acceptance criteria or reject an invalid contract."""
    if not isinstance(value, list):
        raise ControlCenterError(
            "Akzeptanzkriterien müssen als Liste von Texten angegeben werden.",
            code="invalid_acceptance_criteria",
        )
    if not value:
        raise ControlCenterError(
            "Mindestens ein Akzeptanzkriterium ist erforderlich.",
            code="criteria_required",
        )

    criteria: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str):
            raise ControlCenterError(
                f"Akzeptanzkriterium {index} muss ein Text sein.",
                code="invalid_acceptance_criteria",
            )
        criterion = item.strip()
        if not criterion:
            raise ControlCenterError(
                f"Akzeptanzkriterium {index} darf nicht leer sein.",
                code="invalid_acceptance_criteria",
            )
        if len(criterion) > 1000:
            raise ControlCenterError(
                f"Akzeptanzkriterium {index} darf höchstens 1000 Zeichen enthalten.",
                code="acceptance_criterion_too_long",
            )
        criteria.append(criterion)
    return criteria


def public_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"
