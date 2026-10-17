import base64
import mimetypes
from pathlib import Path
from aiohttp import web

from src.database import db

# Maximum file sizes for preview (in bytes)
MAX_TEXT_SIZE = 512 * 1024    # 512 KB for text files
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB for images

# Known image extensions
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.ico', '.avif'}
# Known text extensions
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.htm', '.css', '.scss',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.md', '.txt', '.rst', '.log', '.sh', '.bash', '.bat', '.ps1',
    '.gitignore', '.env', '.dockerignore', '.editorconfig',
    '.c', '.cpp', '.h', '.hpp', '.java', '.go', '.rs', '.rb', '.php',
    '.sql', '.r', '.m', '.swift', '.kt', '.dart', '.lua', '.pl',
    '.makefile', '.dockerfile', '.csv', '.tsv',
}


def _registered_roots() -> list[Path]:
    """Return filesystem roots that are explicitly registered in the Hub."""
    roots: list[Path] = []
    for project in db.get_projects():
        for key in ("path", "integrity_workspace_path"):
            value = str(project.get(key) or "").strip()
            if not value:
                continue
            try:
                root = Path(value).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if root not in roots:
                roots.append(root)
    return roots


def _registered_root(path: Path, *, exact: bool = False) -> Path:
    """Return the registered root containing ``path`` or reject the request."""
    resolved = path.expanduser().resolve()
    for root in sorted(_registered_roots(), key=lambda item: len(item.parts), reverse=True):
        if exact and resolved == root:
            return root
        if not exact:
            try:
                resolved.relative_to(root)
                return root
            except ValueError:
                continue
    raise PermissionError("Path is outside every registered project.")


async def file_preview_handler(request: web.Request) -> web.Response:
    """Serve file content for preview in the dashboard.
    
    Query params:
        project_path: Absolute path to the project root directory
        file_path: Relative path to the file within the project
    
    Returns JSON with:
        - type: 'image' | 'text' | 'binary'
        - content: base64 data URI for images, text content for text files
        - filename: basename of the file
        - size: file size in bytes
    """
    project_path = request.query.get('project_path', '')
    file_path = request.query.get('file_path', '')

    if not project_path or not file_path:
        return web.json_response(
            {"error": "Both 'project_path' and 'file_path' are required."},
            status=400
        )

    try:
        project_dir = Path(project_path).expanduser().resolve()
        _registered_root(project_dir, exact=True)
        full_path = (project_dir / file_path).resolve()

        # Security: ensure the resolved path is within the project directory
        try:
            full_path.relative_to(project_dir)
        except ValueError:
            return web.json_response(
                {"error": "Path traversal detected."},
                status=403
            )

        if not full_path.exists():
            return web.json_response(
                {"error": f"File not found: {file_path}"},
                status=404
            )

        if not full_path.is_file():
            return web.json_response(
                {"error": "Not a file."},
                status=400
            )

        file_size = full_path.stat().st_size
        suffix = full_path.suffix.lower()
        basename = full_path.name

        # Handle image files
        if suffix in IMAGE_EXTENSIONS:
            if file_size > MAX_IMAGE_SIZE:
                return web.json_response({
                    "type": "image",
                    "error": f"Image too large ({file_size:,} bytes, max {MAX_IMAGE_SIZE:,}).",
                    "filename": basename,
                    "size": file_size,
                })

            mime_type = mimetypes.guess_type(str(full_path))[0] or 'application/octet-stream'
            if suffix == '.svg':
                mime_type = 'image/svg+xml'

            raw = full_path.read_bytes()
            b64 = base64.b64encode(raw).decode('ascii')
            data_uri = f"data:{mime_type};base64,{b64}"

            return web.json_response({
                "type": "image",
                "content": data_uri,
                "filename": basename,
                "size": file_size,
                "mime": mime_type,
            })

        # Handle text files
        if suffix in TEXT_EXTENSIONS or suffix == '' or basename.startswith('.'):
            if file_size > MAX_TEXT_SIZE:
                return web.json_response({
                    "type": "text",
                    "error": f"File too large ({file_size:,} bytes, max {MAX_TEXT_SIZE:,}).",
                    "filename": basename,
                    "size": file_size,
                })

            try:
                content = full_path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                content = full_path.read_text(encoding='latin-1')

            return web.json_response({
                "type": "text",
                "content": content,
                "filename": basename,
                "size": file_size,
                "suffix": suffix,
            })

        # Unknown binary file
        return web.json_response({
            "type": "binary",
            "filename": basename,
            "size": file_size,
            "message": f"Preview not supported for '{suffix}' files.",
        })

    except PermissionError:
        return web.json_response({"error": "Permission denied."}, status=403)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def browse_handler(request: web.Request) -> web.Response:
    """List directory contents for the web-based file picker."""
    dir_path = str(request.query.get('path') or '').strip()
    if not dir_path:
        return web.json_response(
            {"error": "A registered project path is required."},
            status=400,
        )

    try:
        p = Path(dir_path).expanduser().resolve()
        root = _registered_root(p)
        if not p.exists():
            return web.json_response({"error": "Path does not exist"}, status=404)
        if not p.is_dir():
            return web.json_response({"error": "Not a directory"}, status=400)

        items = []
        try:
            # Sort folders first, then files alphabetically
            for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    items.append({
                        "name": entry.name,
                        "type": "folder" if entry.is_dir() else "file",
                        "path": str(entry).replace('\\', '\\\\'),
                    })
                except PermissionError:
                    continue
        except PermissionError:
            return web.json_response({"error": "Permission denied"})

        parent = (
            str(p.parent).replace('\\', '\\\\')
            if p != root and p.parent != p
            else None
        )

        return web.json_response({
            "path": str(p).replace('\\', '\\\\'),
            "parent": parent,
            "items": items,
        })
    except PermissionError:
        return web.json_response({"error": "Path is not inside a registered project."}, status=403)
    except Exception as e:
        return web.json_response({"error": str(e)})
