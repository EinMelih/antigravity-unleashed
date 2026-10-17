"""Bounded, read-only project stack inspection for registered Hub projects."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import tomllib
from pathlib import Path
from typing import Any, Iterable, Mapping

MAX_SCAN_DEPTH = 4
MAX_SCANNED_FILES = 3_000
MAX_MANIFEST_FILES = 32
MAX_DOCKERFILES = 16
MAX_COMPOSE_FILES = 12
MAX_MANIFEST_BYTES = 512 * 1024
MAX_DOCKERFILE_BYTES = 256 * 1024
MAX_COMPOSE_BYTES = 512 * 1024
MAX_SQLITE_FILES = 12
MAX_SQLITE_BYTES = 64 * 1024 * 1024
MAX_TABLES_PER_DATABASE = 20
SQLITE_INSPECTION_SECONDS = 1.5

IGNORED_DIRECTORIES = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".turbo",
    ".venv",
    "__pycache__",
    "backup",
    "backups",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "out",
    "scratch",
    "target",
    "venv",
}

COMPOSE_FILE_RE = re.compile(
    r"^(?:docker-)?compose(?:[._-][a-z0-9_-]+)?\.ya?ml$",
    re.IGNORECASE,
)
REQUIREMENTS_FILE_RE = re.compile(
    r"^requirements(?:[._-][a-z0-9_-]+)?\.txt$",
    re.IGNORECASE,
)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SQLITE_HEADER = b"SQLite format 3\x00"

TECHNOLOGY_SPECS = {
    "nodejs": ("Node.js", "runtime"),
    "python": ("Python", "runtime"),
    "rust": ("Rust", "runtime"),
    "go": ("Go", "runtime"),
    "react": ("React", "frontend"),
    "nextjs": ("Next.js", "framework"),
    "vue": ("Vue", "frontend"),
    "nuxt": ("Nuxt", "framework"),
    "svelte": ("Svelte", "frontend"),
    "vite": ("Vite", "build"),
    "express": ("Express", "backend"),
    "fastify": ("Fastify", "backend"),
    "nestjs": ("NestJS", "backend"),
    "typescript": ("TypeScript", "language"),
    "django": ("Django", "framework"),
    "flask": ("Flask", "framework"),
    "fastapi": ("FastAPI", "framework"),
    "aiohttp": ("aiohttp", "backend"),
    "sqlalchemy": ("SQLAlchemy", "database"),
    "prisma": ("Prisma", "database"),
    "gin": ("Gin", "framework"),
    "echo": ("Echo", "framework"),
    "fiber": ("Fiber", "framework"),
    "docker": ("Docker", "container"),
    "compose": ("Docker Compose", "container"),
}

DEPENDENCY_TECHNOLOGIES = {
    "@nestjs/core": "nestjs",
    "aiohttp": "aiohttp",
    "django": "django",
    "express": "express",
    "fastapi": "fastapi",
    "fastify": "fastify",
    "flask": "flask",
    "github.com/gofiber/fiber": "fiber",
    "github.com/labstack/echo": "echo",
    "github.com/gin-gonic/gin": "gin",
    "next": "nextjs",
    "nuxt": "nuxt",
    "prisma": "prisma",
    "@prisma/client": "prisma",
    "react": "react",
    "sqlalchemy": "sqlalchemy",
    "svelte": "svelte",
    "typescript": "typescript",
    "vite": "vite",
    "vue": "vue",
}

DATABASE_DRIVER_SPECS = {
    "sqlite": "SQLite",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
}

DEPENDENCY_DATABASE_DRIVERS = {
    "aiomysql": "mysql",
    "aiosqlite": "sqlite",
    "asyncpg": "postgresql",
    "better-sqlite3": "sqlite",
    "github.com/go-sql-driver/mysql": "mysql",
    "github.com/jackc/pgx": "postgresql",
    "github.com/lib/pq": "postgresql",
    "github.com/mattn/go-sqlite3": "sqlite",
    "github.com/redis/go-redis": "redis",
    "go.mongodb.org/mongo-driver": "mongodb",
    "ioredis": "redis",
    "mariadb": "mariadb",
    "mongodb": "mongodb",
    "mongoose": "mongodb",
    "motor": "mongodb",
    "mysql2": "mysql",
    "mysqlclient": "mysql",
    "pg": "postgresql",
    "psycopg": "postgresql",
    "psycopg2": "postgresql",
    "psycopg2-binary": "postgresql",
    "pymongo": "mongodb",
    "pymysql": "mysql",
    "redis": "redis",
    "rusqlite": "sqlite",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
}


class ProjectPathUnavailable(RuntimeError):
    """Raised when a registered project root cannot be inspected safely."""


class ProjectPathViolation(ValueError):
    """Raised when a candidate path is not relative to the project root."""


def _safe_label(value: Any, maximum: int = 128) -> str:
    text = "".join(
        character if character.isprintable() else "?"
        for character in str(value or "")
    ).strip()
    return text[:maximum]


def _resolve_project_root(project: Mapping[str, Any]) -> Path:
    raw_path = str(project.get("path") or "").strip()
    if not raw_path:
        raise ProjectPathUnavailable("Registered project directory is unavailable.")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise ProjectPathUnavailable("Registered project directory is unavailable.")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProjectPathUnavailable(
            "Registered project directory is unavailable."
        ) from error
    if not resolved.is_dir():
        raise ProjectPathUnavailable("Registered project directory is unavailable.")
    try:
        with os.scandir(resolved) as entries:
            next(entries, None)
    except OSError as error:
        raise ProjectPathUnavailable(
            "Registered project directory is unavailable."
        ) from error
    return resolved


def _resolve_relative_file(root: Path, relative_path: str) -> Path:
    relative = Path(str(relative_path or ""))
    if (
        not str(relative)
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProjectPathViolation("Project file path must be relative.")
    try:
        candidate = (root / relative).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProjectPathViolation(
            "Project file path must stay inside the registered project."
        ) from error
    if not candidate.is_file():
        raise ProjectPathViolation("Project file is unavailable.")
    return candidate


def _relative_display_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ProjectPathViolation(
            "Project file path must stay inside the registered project."
        ) from error
    return relative.as_posix()


def _is_dockerfile(name: str) -> bool:
    lowered = name.casefold()
    return lowered == "dockerfile" or lowered.startswith("dockerfile.")


def _is_manifest(name: str) -> bool:
    lowered = name.casefold()
    return lowered in {
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
    } or bool(REQUIREMENTS_FILE_RE.fullmatch(name))


def _is_sqlite_candidate(name: str) -> bool:
    return Path(name).suffix.casefold() in {".db", ".sqlite", ".sqlite3"}


def _is_skipped_directory(path: Path) -> bool:
    if path.name.casefold() in IGNORED_DIRECTORIES:
        return True
    try:
        return path.is_symlink() or bool(
            getattr(path, "is_junction", lambda: False)()
        )
    except OSError:
        return True


def _discover_candidates(root: Path) -> dict[str, Any]:
    found: dict[str, list[str]] = {
        "manifests": [],
        "dockerfiles": [],
        "compose_files": [],
        "databases": [],
    }
    limits = {
        "manifests": MAX_MANIFEST_FILES,
        "dockerfiles": MAX_DOCKERFILES,
        "compose_files": MAX_COMPOSE_FILES,
        "databases": MAX_SQLITE_FILES,
    }
    considered = 0
    truncated = False

    for current_dir, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_dir)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            directory_names[:] = []
            continue

        if depth >= MAX_SCAN_DEPTH:
            directory_names[:] = []
        else:
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not _is_skipped_directory(current / name)
            )

        for file_name in sorted(file_names):
            considered += 1
            if considered > MAX_SCANNED_FILES:
                truncated = True
                break

            category = None
            if _is_manifest(file_name):
                category = "manifests"
            elif _is_dockerfile(file_name):
                category = "dockerfiles"
            elif COMPOSE_FILE_RE.fullmatch(file_name):
                category = "compose_files"
            elif _is_sqlite_candidate(file_name):
                category = "databases"
            if category is None:
                continue

            candidate = current / file_name
            relative = _relative_display_path(root, candidate)
            try:
                _resolve_relative_file(root, relative)
            except ProjectPathViolation:
                continue

            if len(found[category]) >= limits[category]:
                truncated = True
                continue
            found[category].append(relative)

        if considered > MAX_SCANNED_FILES:
            break

    for values in found.values():
        values.sort(key=str.casefold)
    return {
        **found,
        "files_considered": min(considered, MAX_SCANNED_FILES),
        "truncated": truncated,
    }


def _read_text_limited(path: Path, maximum_bytes: int) -> tuple[str | None, str | None]:
    try:
        if path.stat().st_size > maximum_bytes:
            return None, "size_limit"
        with path.open("rb") as file_handle:
            payload = file_handle.read(maximum_bytes + 1)
    except OSError:
        return None, "parse_error"
    if len(payload) > maximum_bytes:
        return None, "size_limit"
    try:
        return payload.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return None, "parse_error"


def _normalize_dependency(value: Any) -> str:
    dependency = str(value or "").strip().casefold()
    if not dependency:
        return ""
    if dependency.startswith("@"):
        version_separator = dependency.find("@", 1)
        return dependency[:version_separator] if version_separator > 0 else dependency
    dependency = re.split(r"[\s<>=!~;\[]", dependency, maxsplit=1)[0]
    return dependency.replace("_", "-")


def _requirement_name(line: str) -> str:
    stripped = line.strip()
    if (
        not stripped
        or stripped.startswith(("#", "-", ".", "/", "git+", "http:" , "https:"))
    ):
        return ""
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", stripped)
    return _normalize_dependency(match.group(1)) if match else ""


def _parse_package_json(payload: Mapping[str, Any]) -> tuple[set[str], int, int]:
    dependencies = payload.get("dependencies")
    development = payload.get("devDependencies")
    normal = set(dependencies) if isinstance(dependencies, dict) else set()
    dev = set(development) if isinstance(development, dict) else set()
    return {_normalize_dependency(item) for item in normal | dev if item}, len(normal), len(dev)


def _python_dependency_name(value: Any) -> str:
    return _requirement_name(str(value or ""))


def _parse_pyproject(payload: Mapping[str, Any]) -> tuple[set[str], int, int]:
    normal: set[str] = set()
    development: set[str] = set()
    project = payload.get("project")
    if isinstance(project, dict):
        for value in project.get("dependencies") or []:
            dependency = _python_dependency_name(value)
            if dependency:
                normal.add(dependency)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    for value in group:
                        dependency = _python_dependency_name(value)
                        if dependency:
                            development.add(dependency)

    tool = payload.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        dependencies = poetry.get("dependencies")
        if isinstance(dependencies, dict):
            normal.update(
                _normalize_dependency(name)
                for name in dependencies
                if str(name).casefold() != "python"
            )
        groups = poetry.get("group")
        if isinstance(groups, dict):
            for group in groups.values():
                group_dependencies = (
                    group.get("dependencies") if isinstance(group, dict) else None
                )
                if isinstance(group_dependencies, dict):
                    development.update(
                        _normalize_dependency(name) for name in group_dependencies
                    )

    dependency_groups = payload.get("dependency-groups")
    if isinstance(dependency_groups, dict):
        for values in dependency_groups.values():
            if isinstance(values, list):
                for value in values:
                    dependency = _python_dependency_name(value)
                    if dependency:
                        development.add(dependency)

    normal.discard("")
    development.discard("")
    return normal | development, len(normal), len(development)


def _parse_cargo(payload: Mapping[str, Any]) -> tuple[set[str], int, int]:
    normal: set[str] = set()
    development: set[str] = set()

    def add_table(table: Any, destination: set[str]) -> None:
        if isinstance(table, dict):
            destination.update(_normalize_dependency(name) for name in table)

    add_table(payload.get("dependencies"), normal)
    add_table(payload.get("build-dependencies"), development)
    add_table(payload.get("dev-dependencies"), development)
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        add_table(workspace.get("dependencies"), normal)
    targets = payload.get("target")
    if isinstance(targets, dict):
        for target in targets.values():
            if isinstance(target, dict):
                add_table(target.get("dependencies"), normal)
                add_table(target.get("build-dependencies"), development)
                add_table(target.get("dev-dependencies"), development)
    normal.discard("")
    development.discard("")
    return normal | development, len(normal), len(development)


def _parse_go_mod(text: str) -> tuple[set[str], int, int]:
    dependencies: set[str] = set()
    inside_require = False
    for raw_line in text.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if line == "require (":
            inside_require = True
            continue
        if inside_require and line == ")":
            inside_require = False
            continue
        if line.startswith("require "):
            line = line[len("require ") :].strip()
        elif not inside_require:
            continue
        dependency = line.split(None, 1)[0].strip()
        if dependency:
            dependencies.add(dependency.casefold())
    return dependencies, len(dependencies), 0


def _record_detection(
    target: dict[str, dict[str, Any]],
    identifier: str,
    evidence: str,
    specs: Mapping[str, Any],
) -> None:
    if identifier not in specs:
        return
    if identifier not in target:
        spec = specs[identifier]
        if isinstance(spec, tuple):
            target[identifier] = {
                "id": identifier,
                "name": spec[0],
                "category": spec[1],
                "evidence": set(),
            }
        else:
            target[identifier] = {
                "id": identifier,
                "name": spec,
                "evidence": set(),
            }
    target[identifier]["evidence"].add(evidence)


def _apply_dependency_detections(
    dependencies: Iterable[str],
    evidence: str,
    technologies: dict[str, dict[str, Any]],
    database_drivers: dict[str, dict[str, Any]],
) -> None:
    for raw_dependency in dependencies:
        dependency = _normalize_dependency(raw_dependency)
        technology = DEPENDENCY_TECHNOLOGIES.get(dependency)
        if technology:
            _record_detection(
                technologies,
                technology,
                evidence,
                TECHNOLOGY_SPECS,
            )
        driver = DEPENDENCY_DATABASE_DRIVERS.get(dependency)
        if driver:
            _record_detection(
                database_drivers,
                driver,
                evidence,
                DATABASE_DRIVER_SPECS,
            )


def _inspect_manifest(
    root: Path,
    relative_path: str,
    technologies: dict[str, dict[str, Any]],
    database_drivers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    file_name = Path(relative_path).name.casefold()
    if file_name == "package.json":
        kind, ecosystem, baseline = "package.json", "node", "nodejs"
    elif file_name == "pyproject.toml":
        kind, ecosystem, baseline = "pyproject.toml", "python", "python"
    elif file_name == "cargo.toml":
        kind, ecosystem, baseline = "Cargo.toml", "rust", "rust"
    elif file_name == "go.mod":
        kind, ecosystem, baseline = "go.mod", "go", "go"
    else:
        kind, ecosystem, baseline = "requirements.txt", "python", "python"

    summary = {
        "path": relative_path,
        "kind": kind,
        "ecosystem": ecosystem,
        "status": "parsed",
        "dependency_count": 0,
        "dev_dependency_count": 0,
    }
    try:
        path = _resolve_relative_file(root, relative_path)
    except ProjectPathViolation:
        return {**summary, "status": "skipped", "reason": "parse_error"}

    text, reason = _read_text_limited(path, MAX_MANIFEST_BYTES)
    if text is None:
        return {**summary, "status": "skipped", "reason": reason}

    try:
        if file_name == "package.json":
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            dependencies, normal_count, dev_count = _parse_package_json(payload)
        elif file_name == "pyproject.toml":
            dependencies, normal_count, dev_count = _parse_pyproject(
                tomllib.loads(text)
            )
        elif file_name == "cargo.toml":
            dependencies, normal_count, dev_count = _parse_cargo(
                tomllib.loads(text)
            )
        elif file_name == "go.mod":
            dependencies, normal_count, dev_count = _parse_go_mod(text)
        else:
            dependencies = {
                dependency
                for line in text.splitlines()
                if (dependency := _requirement_name(line))
            }
            normal_count, dev_count = len(dependencies), 0
    except (
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        return {**summary, "status": "invalid", "reason": "parse_error"}

    _record_detection(technologies, baseline, relative_path, TECHNOLOGY_SPECS)
    _apply_dependency_detections(
        dependencies,
        relative_path,
        technologies,
        database_drivers,
    )
    summary["dependency_count"] = normal_count
    summary["dev_dependency_count"] = dev_count
    return summary


def _sanitize_image(value: str) -> str:
    image = value.strip().strip("'\"")[:256]
    if (
        not image
        or "$" in image
        or "<variable>" in image
        or re.search(r"://[^/\s]+@", image)
        or any(character.isspace() for character in image)
    ):
        return "<configured-image>"
    return image


def _docker_logical_lines(text: str) -> Iterable[str]:
    pending = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = f"{pending} {stripped}".strip() if pending else stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        yield pending
        pending = ""
    if pending:
        yield pending


def _inspect_dockerfile(root: Path, relative_path: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": relative_path,
        "status": "parsed",
        "stages": [],
        "base_images": [],
        "exposed_ports": [],
        "healthcheck": "absent",
    }
    try:
        path = _resolve_relative_file(root, relative_path)
    except ProjectPathViolation:
        return {**summary, "status": "skipped", "reason": "parse_error"}
    text, reason = _read_text_limited(path, MAX_DOCKERFILE_BYTES)
    if text is None:
        return {**summary, "status": "skipped", "reason": reason}

    for line in _docker_logical_lines(text):
        from_match = re.match(
            r"^FROM\s+(?:--[^\s]+\s+)*(\S+)(?:\s+AS\s+([A-Za-z0-9_.-]+))?\s*$",
            line,
            re.IGNORECASE,
        )
        if from_match:
            image = _sanitize_image(from_match.group(1))
            stage_name = from_match.group(2)
            summary["stages"].append(
                {"name": stage_name or None, "base_image": image}
            )
            if image not in summary["base_images"]:
                summary["base_images"].append(image)
            continue
        expose_match = re.match(r"^EXPOSE\s+(.+)$", line, re.IGNORECASE)
        if expose_match:
            for value in expose_match.group(1).split():
                port_match = re.fullmatch(r"(\d{1,5})(?:/(tcp|udp))?", value, re.I)
                if (
                    not port_match
                    or int(port_match.group(1)) <= 0
                    or int(port_match.group(1)) > 65535
                ):
                    continue
                normalized = port_match.group(1)
                if port_match.group(2):
                    normalized += f"/{port_match.group(2).casefold()}"
                if normalized not in summary["exposed_ports"]:
                    summary["exposed_ports"].append(normalized)
            continue
        health_match = re.match(r"^HEALTHCHECK\s+(.+)$", line, re.IGNORECASE)
        if health_match:
            summary["healthcheck"] = (
                "none"
                if health_match.group(1).strip().casefold() == "none"
                else "configured"
            )
    return summary


def _strip_yaml_comment(value: str) -> str:
    quote = None
    escaped = False
    result = []
    for index, character in enumerate(value):
        if escaped:
            result.append(character)
            escaped = False
            continue
        if character == "\\" and quote == '"':
            result.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
            result.append(character)
            continue
        if character == "#" and quote is None and (
            index == 0 or value[index - 1].isspace()
        ):
            break
        result.append(character)
    return "".join(result).rstrip()


def _yaml_key_value(content: str) -> tuple[str, str] | None:
    match = re.match(r"^([^:#][^:]{0,127}):(?:\s*(.*))?$", content)
    if not match:
        return None
    key = match.group(1).strip().strip("'\"")
    return key, (match.group(2) or "").strip()


def _yaml_scalar(value: str) -> str:
    scalar = _strip_yaml_comment(value).strip().strip("'\"")[:512]
    scalar = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*", "<variable>", scalar)
    return scalar


def _inline_list(value: str) -> list[str]:
    scalar = _strip_yaml_comment(value).strip()
    if not (scalar.startswith("[") and scalar.endswith("]")):
        return []
    inner = scalar[1:-1]
    return [
        item
        for raw_item in inner.split(",")
        if (item := _yaml_scalar(raw_item))
    ][:64]


def _relative_compose_reference(value: str) -> tuple[str | None, bool]:
    reference = _yaml_scalar(value)
    if not reference or "<variable>" in reference:
        return None, True
    normalized = reference.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("/"):
        return None, True
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if ".." in parts:
        return None, True
    return "/".join(parts) or ".", False


def _compose_volume(value: str) -> dict[str, Any] | None:
    scalar = _yaml_scalar(value)
    if not scalar:
        return None

    windows_bind = re.match(r"^([A-Za-z]:[\\/].*?):([^:]+)(?::.*)?$", scalar)
    if windows_bind:
        return {
            "source": "<external-path>",
            "target": windows_bind.group(2)[:256],
            "type": "bind",
            "external": True,
        }

    segments = scalar.split(":")
    if len(segments) == 1:
        return {
            "source": "",
            "target": segments[0][:256],
            "type": "anonymous",
            "external": False,
        }

    source, target = segments[0], segments[1]
    if source.startswith(("/", "~")):
        return {
            "source": "<external-path>",
            "target": target[:256],
            "type": "bind",
            "external": True,
        }
    if source.startswith((".", "..")):
        relative_source, external = _relative_compose_reference(source)
        return {
            "source": relative_source or "<external-path>",
            "target": target[:256],
            "type": "bind",
            "external": external,
        }
    return {
        "source": source[:128],
        "target": target[:256],
        "type": "volume",
        "external": False,
    }


def _compose_long_volume(fields: Mapping[str, str]) -> dict[str, Any] | None:
    """Summarize Compose long mount syntax without exposing host paths."""
    mount_type = _yaml_scalar(fields.get("type", "")).casefold()
    if mount_type not in {"bind", "tmpfs", "volume"}:
        return None

    target = _yaml_scalar(fields.get("target", ""))
    if not target or "<variable>" in target:
        target = ""
    target = target[:256]

    if mount_type == "tmpfs":
        return {
            "source": "",
            "target": target,
            "type": "tmpfs",
            "external": False,
        }

    raw_source = fields.get("source", "")
    if mount_type == "bind":
        source, external = _relative_compose_reference(raw_source)
        return {
            "source": source or "<external-path>",
            "target": target,
            "type": "bind",
            "external": external,
        }

    source = _yaml_scalar(raw_source)
    if not SAFE_NAME_RE.fullmatch(source):
        source = "<configured-volume>"
    return {
        "source": source,
        "target": target,
        "type": "volume",
        "external": False,
    }


def _new_compose_service(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "image": None,
        "build": None,
        "ports": [],
        "volumes": [],
        "depends_on": [],
        "healthcheck": False,
    }


def _inspect_compose(root: Path, relative_path: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": relative_path,
        "status": "parsed",
        "services": [],
        "named_volumes": [],
        "networks": [],
    }
    try:
        path = _resolve_relative_file(root, relative_path)
    except ProjectPathViolation:
        return {**summary, "status": "skipped", "reason": "parse_error"}
    text, reason = _read_text_limited(path, MAX_COMPOSE_BYTES)
    if text is None:
        return {**summary, "status": "skipped", "reason": reason}

    services: dict[str, dict[str, Any]] = {}
    section = ""
    section_indent = -1
    item_indent: int | None = None
    service: dict[str, Any] | None = None
    service_indent: int | None = None
    property_name = ""
    property_indent: int | None = None
    property_item_indent: int | None = None
    pending_volume: dict[str, str] | None = None
    pending_volume_indent: int | None = None

    def flush_pending_volume() -> None:
        nonlocal pending_volume, pending_volume_indent
        if pending_volume is not None and service is not None:
            volume = _compose_long_volume(pending_volume)
            if volume:
                service["volumes"].append(volume)
        pending_volume = None
        pending_volume_indent = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        content = _strip_yaml_comment(raw_line.strip())
        if not content or content in {"---", "..."}:
            continue
        pair = _yaml_key_value(content)

        is_pending_volume_field = bool(
            pending_volume is not None
            and pending_volume_indent is not None
            and property_name == "volumes"
            and pair
            and not content.startswith("-")
            and indent > pending_volume_indent
            and pair[0].casefold() in {"source", "target", "type"}
        )
        if pending_volume is not None and not is_pending_volume_field:
            flush_pending_volume()

        if indent == 0 and pair:
            key = pair[0].casefold()
            section = key if key in {"services", "volumes", "networks"} else ""
            section_indent = indent
            item_indent = None
            service = None
            service_indent = None
            property_name = ""
            property_indent = None
            property_item_indent = None
            continue
        if not section or indent <= section_indent:
            continue

        if section in {"volumes", "networks"}:
            if not pair:
                continue
            if item_indent is None:
                item_indent = indent
            if indent == item_indent and SAFE_NAME_RE.fullmatch(pair[0]):
                target = "named_volumes" if section == "volumes" else "networks"
                if pair[0] not in summary[target]:
                    summary[target].append(pair[0])
            continue

        if not pair and service is None:
            continue
        if service_indent is None:
            if pair and SAFE_NAME_RE.fullmatch(pair[0]):
                service_indent = indent
            else:
                continue
        if indent == service_indent and pair:
            name = pair[0]
            if not SAFE_NAME_RE.fullmatch(name):
                service = None
                continue
            service = services.setdefault(name, _new_compose_service(name))
            property_name = ""
            property_indent = None
            property_item_indent = None
            continue
        if service is None or indent <= service_indent:
            continue

        if pair and (property_indent is None or indent <= property_indent):
            property_name = pair[0].casefold()
            property_indent = indent
            property_item_indent = None
            value = pair[1]
            if property_name == "image" and value:
                service["image"] = _sanitize_image(_yaml_scalar(value))
            elif property_name == "build":
                context = None
                external = False
                if value:
                    context_match = re.search(r"context\s*:\s*([^,}]+)", value)
                    raw_context = context_match.group(1) if context_match else value
                    context, external = _relative_compose_reference(raw_context)
                service["build"] = {"context": context, "external": external}
            elif property_name in {"ports", "volumes", "depends_on"}:
                for item in _inline_list(value):
                    if property_name == "ports":
                        service["ports"].append(item[:128])
                    elif property_name == "volumes":
                        volume = _compose_volume(item)
                        if volume:
                            service["volumes"].append(volume)
                    elif SAFE_NAME_RE.fullmatch(item):
                        service["depends_on"].append(item)
            elif property_name == "healthcheck":
                service["healthcheck"] = _yaml_scalar(value).casefold() not in {
                    "false",
                    "null",
                    "~",
                }
            continue

        if property_indent is None or indent <= property_indent:
            continue
        if is_pending_volume_field and pair and pending_volume is not None:
            pending_volume[pair[0].casefold()] = pair[1]
            continue
        if property_name in {"ports", "volumes", "depends_on"} and content.startswith("-"):
            item = _yaml_scalar(content[1:])
            if property_name == "ports" and item:
                service["ports"].append(item[:128])
            elif property_name == "volumes":
                long_pair = _yaml_key_value(content[1:].strip())
                if long_pair and long_pair[0].casefold() in {
                    "source",
                    "target",
                    "type",
                }:
                    pending_volume = {
                        long_pair[0].casefold(): long_pair[1]
                    }
                    pending_volume_indent = indent
                else:
                    volume = _compose_volume(item)
                    if volume:
                        service["volumes"].append(volume)
            elif property_name == "depends_on" and SAFE_NAME_RE.fullmatch(item):
                service["depends_on"].append(item)
        elif property_name == "depends_on" and pair:
            if property_item_indent is None:
                property_item_indent = indent
            if indent == property_item_indent and SAFE_NAME_RE.fullmatch(pair[0]):
                service["depends_on"].append(pair[0])
        elif property_name == "build" and pair and pair[0].casefold() == "context":
            context, external = _relative_compose_reference(pair[1])
            service["build"] = {"context": context, "external": external}

    flush_pending_volume()
    for compose_service in services.values():
        compose_service["ports"] = list(dict.fromkeys(compose_service["ports"]))[:64]
        compose_service["depends_on"] = list(
            dict.fromkeys(compose_service["depends_on"])
        )[:64]
        compose_service["volumes"] = compose_service["volumes"][:64]
    summary["services"] = list(services.values())[:128]
    summary["named_volumes"].sort(key=str.casefold)
    summary["networks"].sort(key=str.casefold)
    return summary


def _sqlite_result(relative_path: str, size_bytes: int) -> dict[str, Any]:
    return {
        "path": relative_path,
        "size_bytes": size_bytes,
        "status": "unavailable",
        "quick_check": "unavailable",
        "table_count": None,
        "tables": [],
        "tables_truncated": False,
    }


def _inspect_sqlite(root: Path, relative_path: str) -> dict[str, Any]:
    try:
        path = _resolve_relative_file(root, relative_path)
        size_bytes = path.stat().st_size
    except (OSError, ProjectPathViolation):
        return _sqlite_result(relative_path, 0)

    result = _sqlite_result(relative_path, size_bytes)
    if size_bytes > MAX_SQLITE_BYTES:
        return {**result, "status": "skipped", "reason": "size_limit"}
    try:
        with path.open("rb") as file_handle:
            header = file_handle.read(len(SQLITE_HEADER))
    except OSError:
        return result
    if header != SQLITE_HEADER:
        return {**result, "status": "invalid", "reason": "not_sqlite"}

    connection: sqlite3.Connection | None = None
    deadline = time.monotonic() + SQLITE_INSPECTION_SECONDS

    def progress_handler() -> int:
        return int(time.monotonic() >= deadline)

    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=0.25,
        )
        connection.execute("PRAGMA query_only = ON")
        connection.set_progress_handler(progress_handler, 1_000)
        try:
            quick_value = connection.execute("PRAGMA quick_check(1)").fetchone()
            result["quick_check"] = (
                "ok" if quick_value and quick_value[0] == "ok" else "failed"
            )
        except sqlite3.Error:
            result["quick_check"] = (
                "limited" if time.monotonic() >= deadline else "failed"
            )

        count_row = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchone()
        result["table_count"] = int(count_row[0]) if count_row else 0
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            LIMIT ?
            """,
            (MAX_TABLES_PER_DATABASE + 1,),
        ).fetchall()
        result["tables_truncated"] = len(rows) > MAX_TABLES_PER_DATABASE
        for row in rows[:MAX_TABLES_PER_DATABASE]:
            table_name = str(row[0])
            table = {
                "name": _safe_label(table_name),
                "row_count": None,
                "count_status": "unavailable",
            }
            if time.monotonic() >= deadline:
                table["count_status"] = "limited"
            else:
                quoted_name = table_name.replace('"', '""')
                try:
                    row_count = connection.execute(
                        f'SELECT COUNT(*) FROM "{quoted_name}"'
                    ).fetchone()
                    table["row_count"] = int(row_count[0]) if row_count else 0
                    table["count_status"] = "ok"
                except sqlite3.Error:
                    table["count_status"] = (
                        "limited" if time.monotonic() >= deadline else "unavailable"
                    )
            result["tables"].append(table)
        result["status"] = "ok"
    except sqlite3.Error:
        result["status"] = "unavailable"
    finally:
        if connection is not None:
            connection.close()
    return result


def _finalize_detections(values: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for value in values.values():
        finalized.append(
            {
                **value,
                "evidence": sorted(value["evidence"], key=str.casefold),
            }
        )
    return sorted(finalized, key=lambda item: (item["name"].casefold(), item["id"]))


def inspect_project_stack(project: Mapping[str, Any]) -> dict[str, Any]:
    """Inspect one registered project without executing code or returning contents."""
    root = _resolve_project_root(project)
    candidates = _discover_candidates(root)
    technologies: dict[str, dict[str, Any]] = {}
    database_drivers: dict[str, dict[str, Any]] = {}

    manifests = [
        _inspect_manifest(root, path, technologies, database_drivers)
        for path in candidates["manifests"]
    ]
    dockerfiles = [
        _inspect_dockerfile(root, path)
        for path in candidates["dockerfiles"]
    ]
    compose_files = [
        _inspect_compose(root, path)
        for path in candidates["compose_files"]
    ]
    databases = [
        _inspect_sqlite(root, path)
        for path in candidates["databases"]
    ]

    for dockerfile in dockerfiles:
        if dockerfile["status"] == "parsed":
            _record_detection(
                technologies,
                "docker",
                dockerfile["path"],
                TECHNOLOGY_SPECS,
            )
    for compose_file in compose_files:
        if compose_file["status"] == "parsed":
            _record_detection(
                technologies,
                "compose",
                compose_file["path"],
                TECHNOLOGY_SPECS,
            )
    for database in databases:
        if database["status"] == "ok":
            _record_detection(
                database_drivers,
                "sqlite",
                database["path"],
                DATABASE_DRIVER_SPECS,
            )

    return {
        "project": {
            "id": int(project["id"]),
            "name": _safe_label(project.get("name"), maximum=200),
        },
        "technologies": _finalize_detections(technologies),
        "database_drivers": _finalize_detections(database_drivers),
        "manifests": manifests,
        "docker": {
            "dockerfiles": dockerfiles,
            "compose_files": compose_files,
        },
        "databases": databases,
        "scan": {
            "read_only": True,
            "truncated": bool(candidates["truncated"]),
            "files_considered": int(candidates["files_considered"]),
            "limits": {
                "max_depth": MAX_SCAN_DEPTH,
                "max_files": MAX_SCANNED_FILES,
                "max_manifest_bytes": MAX_MANIFEST_BYTES,
                "max_sqlite_files": MAX_SQLITE_FILES,
                "max_sqlite_bytes": MAX_SQLITE_BYTES,
                "max_tables_per_database": MAX_TABLES_PER_DATABASE,
            },
        },
        "privacy": {
            "notice": (
                "This read-only summary contains bounded stack metadata only; "
                "review the project itself for complete configuration."
            ),
            "guarantees": [
                "Only registered project files with relative response paths are inspected.",
                ".env files, secret values, environment values, and source contents are not returned.",
                "SQLite rows and SQL text are never returned; only bounded schema counts are read.",
                "No Docker command or project code is executed.",
            ],
        },
    }
