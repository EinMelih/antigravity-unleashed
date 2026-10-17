import json
import logging
import os
import sqlite3
import urllib.parse
import uuid
import re
import http.client
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import psutil

logger = logging.getLogger(__name__)

_CACHED_CONNECTION = None
_CACHED_HTTPS_PORT = None
TERMINAL_TOOL_STATUSES = frozenset({3, 6, 7})


def _active_antigravity_backend_port():
    """Resolve the backend of the desktop selected by DevToolsActivePort."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    port_file = Path(appdata) / "Antigravity" / "DevToolsActivePort"
    try:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        if not lines:
            return None
        from src.port_finder import check_port

        target = check_port(int(lines[0].strip()))
        backend_port = target.get("backend_port") if target else None
        return int(backend_port) if backend_port else None
    except (OSError, TypeError, ValueError):
        return None


def _select_language_server_candidate(candidates, active_backend_port):
    """Select only the LS that owns the active desktop backend."""
    usable = [
        candidate
        for candidate in candidates
        if candidate.get("csrf") and candidate.get("ports")
    ]
    if active_backend_port:
        exact = [
            candidate
            for candidate in usable
            if active_backend_port in candidate["ports"]
        ]
        if len(exact) == 1:
            return exact[0]
        adjacent = [
            candidate
            for candidate in usable
            if active_backend_port + 1 in candidate["ports"]
        ]
        return adjacent[0] if len(adjacent) == 1 else None
    return usable[0] if len(usable) == 1 else None


def _plain_http_port(ports, active_backend_port=None):
    """Identify the non-TLS gRPC-Web listener from one LS process."""
    ordered_ports = list(sorted(set(int(port) for port in ports)))
    if active_backend_port and active_backend_port + 1 in ordered_ports:
        ordered_ports.remove(active_backend_port + 1)
        ordered_ports.insert(0, active_backend_port + 1)
    for port in ordered_ports:
        connection = None
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                port,
                timeout=0.2,
            )
            connection.request("GET", "/health")
            response = connection.getresponse()
            response.read(64)
            return port
        except Exception:
            continue
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
    return None


def get_ls_connection_info():
    """Returns (grpc_port, csrf_token) tuple for the active Language Server.
    grpc_port is the LS_ADDRESS port (HTTP).
    Uses socket-verified cache to respond in <5ms, otherwise falls back to port_finder and process scanning.
    """
    global _CACHED_CONNECTION, _CACHED_HTTPS_PORT
    active_backend_port = _active_antigravity_backend_port()

    # Fast cache check. The backend binding prevents reusing a still-open port
    # from another IDE or desktop instance.
    if _CACHED_CONNECTION:
        port = int(_CACHED_CONNECTION["port"])
        csrf = str(_CACHED_CONNECTION["csrf"])
        cached_pid = int(_CACHED_CONNECTION["pid"])
        cached_backend = _CACHED_CONNECTION.get("backend_port")
        try:
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.01)
                result = sock.connect_ex(("127.0.0.1", port))
            owner_ports = {
                connection.laddr.port
                for connection in psutil.Process(cached_pid).net_connections(
                    kind="tcp"
                )
                if connection.status == psutil.CONN_LISTEN
            }
            backend_matches = (
                active_backend_port is not None
                and cached_backend == active_backend_port
            )
            owner_matches = (
                port in owner_ports
                and (
                    not cached_backend
                    or cached_backend in owner_ports
                )
            )
            if result == 0 and backend_matches and owner_matches:
                os.environ["ANTIGRAVITY_CSRF_TOKEN"] = csrf
                return port, csrf
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            pass
        _CACHED_CONNECTION = None
        _CACHED_HTTPS_PORT = None

    candidates = []
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            name = str(proc.info.get("name") or "").lower()
            if "language_server" not in name:
                continue
            try:
                cmdline = proc.cmdline()
                csrf = ""
                for index, argument in enumerate(cmdline):
                    if argument == "--csrf_token" and index + 1 < len(cmdline):
                        csrf = cmdline[index + 1]
                        break
                    if argument.startswith("--csrf_token="):
                        csrf = argument.split("=", 1)[1]
                        break
                connections = proc.net_connections(kind="tcp")
                ports = {
                    connection.laddr.port
                    for connection in connections
                    if connection.status == psutil.CONN_LISTEN
                }
                candidates.append({
                    "pid": int(proc.info["pid"]),
                    "csrf": csrf,
                    "ports": ports,
                })
            except (psutil.AccessDenied, psutil.NoSuchProcess, ValueError):
                continue
    except Exception as e:
        print(f"[AntigravitySync] Process cmdline/port scan failed: {e}")

    candidate = _select_language_server_candidate(
        candidates,
        active_backend_port,
    )
    if not candidate:
        print(
            "[AntigravitySync] Could not uniquely bind a language server "
            "to the active desktop.",
            flush=True,
        )
        return None, None

    http_port = _plain_http_port(candidate["ports"], active_backend_port)
    if not http_port:
        return None, None
    other_ports = sorted(set(candidate["ports"]) - {http_port})
    _CACHED_HTTPS_PORT = (
        active_backend_port
        if active_backend_port in other_ports
        else (other_ports[0] if other_ports else None)
    )
    _CACHED_CONNECTION = {
        "port": http_port,
        "csrf": candidate["csrf"],
        "pid": candidate["pid"],
        "backend_port": active_backend_port,
    }
    os.environ["ANTIGRAVITY_CSRF_TOKEN"] = candidate["csrf"]
    return http_port, candidate["csrf"]

def get_ls_https_port():
    """Returns the HTTPS/gRPC-web port for the language server."""
    global _CACHED_HTTPS_PORT
    if _CACHED_HTTPS_PORT:
        return _CACHED_HTTPS_PORT

    get_ls_connection_info()
    return _CACHED_HTTPS_PORT


def get_ls_grpc_port():
    """Backwards-compatible wrapper: returns only the gRPC port."""
    port, _ = get_ls_connection_info()
    return port

def encode_varint(value):
    parts = []
    while True:
        b = value & 0x7f
        value >>= 7
        if value > 0:
            b |= 0x80
        parts.append(b)
        if value == 0:
            break
    return bytes(parts)

def build_metadata_blob(workspace_path, project_uuid, init_state_uuid):
    """Builds the binary protobuf blob required for the trajectory_metadata_blob table."""
    clean_path = workspace_path.replace('\\', '/')
    if not clean_path.startswith('/'):
        clean_path = '/' + clean_path
    uri = 'file://' + urllib.parse.quote(clean_path)
    uri_bytes = uri.encode('utf-8')

    workspace_folder = b'\x0a' + encode_varint(len(uri_bytes)) + uri_bytes
    git_root = b'\x12' + encode_varint(len(uri_bytes)) + uri_bytes
    repository = b'\x1a\x00'
    branch = b'\x22\x04main'

    workspace_msg = workspace_folder + git_root + repository + branch
    workspaces = b'\x0a' + encode_varint(len(workspace_msg)) + workspace_msg
    created_at = b'\x12\x0c\x08\xec\xff\x9c\xd2\x06\x10\x98\xa5\x8d\xdd\x02'
    init_state = b'\x1a\x24' + init_state_uuid.encode('utf-8')
    workspace_uris = b'\x3a' + encode_varint(len(uri_bytes)) + uri_bytes
    project_id = b'\x92\x01\x24' + project_uuid.encode('utf-8')

    return workspaces + created_at + init_state + workspace_uris + project_id

def create_integrity_convo(workspace_path, project_uuid=None):
    """Create a new empty conversation database in Anti-Gravity's data directory.
    This automatically registers the project/workspace path in Anti-Gravity.
    """
    convo_id = str(uuid.uuid4())
    init_state_uuid = str(uuid.uuid4())
    if not project_uuid:
        project_uuid = str(uuid.uuid4())

    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)
    db_path = convo_dir / f"{convo_id}.db"

    blob = build_metadata_blob(workspace_path, project_uuid, init_state_uuid)

    # Create the database and build the schema
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE `trajectory_meta` (`trajectory_id` text,`cascade_id` text,`trajectory_type` integer,`source` integer,PRIMARY KEY (`trajectory_id`))")
        conn.execute("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,`status` integer NOT NULL DEFAULT 0,`has_subtrajectory` numeric NOT NULL DEFAULT false,`metadata` blob,`error_details` blob,`permissions` blob,`task_details` blob,`render_info` blob,`step_payload` blob,`step_format` integer NOT NULL DEFAULT 0,PRIMARY KEY (`idx`))")
        conn.execute("CREATE INDEX `idx_steps_status` ON `steps`(`status`)")
        conn.execute("CREATE INDEX `idx_steps_step_type` ON `steps`(`step_type`)")
        conn.execute("CREATE TABLE `gen_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
        conn.execute("CREATE TABLE `executor_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
        conn.execute("CREATE TABLE `parent_references` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
        conn.execute("CREATE TABLE `trajectory_metadata_blob` (`id` text DEFAULT \"main\",`data` blob,PRIMARY KEY (`id`))")
        conn.execute("CREATE TABLE `battle_mode_infos` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")

        # Insert initial meta
        traj_id = str(uuid.uuid4())
        conn.execute("INSERT INTO trajectory_meta (trajectory_id, cascade_id, trajectory_type, source) VALUES (?, ?, 4, 1)", (traj_id, convo_id))
        conn.execute("INSERT INTO trajectory_metadata_blob (id, data) VALUES ('main', ?)", (sqlite3.Binary(blob),))
        conn.commit()
    finally:
        conn.close()

    return convo_id


def _grpc_web_status(response_body, headers=None):
    """Return the semantic gRPC status/message from headers or trailer frames."""
    body = bytes(response_body or b"")
    normalized_headers = {}
    if headers is not None:
        try:
            normalized_headers = {
                str(key).lower(): value for key, value in headers.items()
            }
        except (AttributeError, TypeError, ValueError):
            normalized_headers = {}

    direct_status = normalized_headers.get("grpc-status")
    direct_message = normalized_headers.get("grpc-message", "")
    if isinstance(direct_status, (list, tuple)):
        direct_status = direct_status[0] if direct_status else None
    if isinstance(direct_message, (list, tuple)):
        direct_message = direct_message[0] if direct_message else ""
    if direct_status is not None and str(direct_status).isdigit():
        return int(direct_status), urllib.parse.unquote(str(direct_message or ""))

    offset = 0
    while offset + 5 <= len(body):
        flags = body[offset]
        frame_length = int.from_bytes(body[offset + 1:offset + 5], "big")
        frame_end = offset + 5 + frame_length
        if frame_end > len(body):
            break
        if flags & 0x80:
            trailer_text = body[offset + 5:frame_end].decode(
                "utf-8",
                errors="replace",
            )
            trailer_values = {}
            for line in trailer_text.splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    trailer_values[key.strip().lower()] = value.strip()
            trailer_status = trailer_values.get("grpc-status")
            if trailer_status is not None and trailer_status.isdigit():
                return (
                    int(trailer_status),
                    urllib.parse.unquote(trailer_values.get("grpc-message", "")),
                )
        offset = frame_end

    return None, ""


def _parse_protobuf_strict(data):
    """Parse the wire types used by the summary map and reject truncation."""
    payload = bytes(data)
    fields = []
    position = 0

    def read_varint():
        nonlocal position
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(payload):
                raise ValueError("Truncated protobuf varint")
            byte = payload[position]
            position += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
        raise ValueError("Invalid protobuf varint")

    while position < len(payload):
        header = read_varint()
        field_number = header >> 3
        wire_type = header & 0x07
        if field_number <= 0:
            raise ValueError("Invalid protobuf field number")
        if wire_type == 0:
            value = read_varint()
        elif wire_type == 2:
            length = read_varint()
            end = position + length
            if end > len(payload):
                raise ValueError("Truncated protobuf field")
            value = payload[position:end]
            position = end
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
        fields.append((field_number, wire_type, value))
    return fields


def _summary_catalog_contains(convo_id, summary_path=None):
    """Return whether the native summary map contains an ID, or None if unreadable."""
    path = summary_path or (
        Path.home() / ".gemini" / "antigravity" / "agyhub_summaries_proto.pb"
    )
    if not path.exists():
        return None
    try:
        for field_number, wire_type, map_blob in _parse_protobuf_strict(
            path.read_bytes()
        ):
            if field_number != 1 or wire_type != 2:
                raise ValueError("Unexpected summary catalog field")
            map_fields = _parse_protobuf_strict(map_blob)
            key = _first_protobuf_value(map_fields, 1, 2, b"")
            if key.decode("utf-8", errors="ignore").lower() == convo_id.lower():
                return True
        return False
    except (OSError, ValueError):
        return None


def _grpc_web_delete(convo_id, method_name):
    """Call one native deletion RPC and require explicit gRPC success."""
    grpc_port = get_ls_grpc_port()
    if not grpc_port:
        return {
            "grpc_http_status": None,
            "grpc_status": None,
            "grpc_message": "Language server unavailable.",
            "grpc_confirmed": False,
            "native_method": method_name,
        }

    convo_bytes = convo_id.encode("utf-8")
    proto_payload = encode_field_bytes(1, convo_bytes)
    body = b"\x00" + len(proto_payload).to_bytes(4, "big") + proto_payload
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
    connection = None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", grpc_port, timeout=10)
        connection.request(
            "POST",
            f"/exa.language_server_pb.LanguageServerService/{method_name}",
            body=body,
            headers={
                "content-type": "application/grpc-web+proto",
                "x-grpc-web": "1",
                "x-codeium-csrf-token": csrf,
                "content-length": str(len(body)),
            },
        )
        response = connection.getresponse()
        response_body = response.read()
        grpc_status, grpc_message = _grpc_web_status(
            response_body,
            getattr(response, "headers", None),
        )
        http_status = int(response.status)
        confirmed = http_status == 200 and grpc_status == 0
        print(
            f"[AntigravitySync] {method_name} "
            f"HTTP={http_status} gRPC={grpc_status}",
            flush=True,
        )
        return {
            "grpc_http_status": http_status,
            "grpc_status": grpc_status,
            "grpc_message": grpc_message,
            "grpc_confirmed": confirmed,
            "native_method": method_name,
        }
    except Exception as error:
        print(f"[AntigravitySync] Native delete failed: {error}", flush=True)
        return {
            "grpc_http_status": None,
            "grpc_status": None,
            "grpc_message": str(error),
            "grpc_confirmed": False,
            "native_method": method_name,
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _delete_cascade_trajectory(convo_id):
    return _grpc_web_delete(convo_id, "DeleteCascadeTrajectory")


def _delete_trajectory_summary(convo_id):
    return _grpc_web_delete(convo_id, "JetboxDeleteSummary")


def _has_deleted_tombstone(convo_id):
    """Return whether a prior native removal authorizes local-only cleanup."""
    try:
        from src.database import db

        return any(
            str(item.get("conversation_id") or "").lower() == convo_id.lower()
            for item in db.list_managed_antigravity_conversations(
                state="deleted"
            )
        )
    except Exception:
        return False


def delete_integrity_convo(convo_id):
    """Delete one exact conversation and return a verifiable result."""
    import time

    if not re.fullmatch(
        r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
        str(convo_id or ""),
        re.IGNORECASE,
    ):
        raise ValueError("Invalid Anti-Gravity conversation ID")

    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    db_base = convo_dir / convo_id
    suffixes = [".db", ".db-shm", ".db-wal", ".pb"]
    existing_files = [
        Path(str(db_base) + suffix)
        for suffix in suffixes
        if Path(str(db_base) + suffix).exists()
    ]
    summary_present_before = _summary_catalog_contains(convo_id)
    if summary_present_before is None:
        return {
            "success": False,
            "found": True,
            "code": "native_delete_unconfirmed",
            "conversation_id": convo_id,
            "removed_files": [],
            "remaining_files": [],
            "grpc_http_status": None,
            "grpc_status": None,
            "grpc_message": "Native summary index is unavailable.",
            "grpc_confirmed": False,
            "native_method": None,
            "summary_present": None,
        }
    if not existing_files and summary_present_before is False:
        time.sleep(0.1)
        current = _summary_catalog_contains(convo_id)
        if current is False:
            return {
                "success": False,
                "found": False,
                "conversation_id": convo_id,
                "removed_files": [],
                "remaining_files": [],
                "grpc_http_status": None,
                "grpc_status": None,
                "grpc_message": "",
                "grpc_confirmed": False,
                "native_method": None,
                "summary_present": False,
            }
        if current is None:
            return {
                "success": False,
                "found": True,
                "code": "native_delete_unconfirmed",
                "conversation_id": convo_id,
                "removed_files": [],
                "remaining_files": [],
                "grpc_http_status": None,
                "grpc_status": None,
                "grpc_message": "Native summary index is unavailable.",
                "grpc_confirmed": False,
                "native_method": None,
                "summary_present": None,
            }
        summary_present_before = True

    local_cleanup_only = (
        bool(existing_files)
        and summary_present_before is False
        and _has_deleted_tombstone(convo_id)
    )
    if local_cleanup_only:
        time.sleep(0.1)
        stable_summary_state = _summary_catalog_contains(convo_id)
        if stable_summary_state is None:
            return {
                "success": False,
                "found": True,
                "code": "native_delete_unconfirmed",
                "conversation_id": convo_id,
                "removed_files": [],
                "remaining_files": sorted(str(path) for path in existing_files),
                "grpc_http_status": None,
                "grpc_status": None,
                "grpc_message": "Native summary index is unavailable.",
                "grpc_confirmed": False,
                "native_method": None,
                "summary_present": None,
            }
        if stable_summary_state is True:
            summary_present_before = True
            local_cleanup_only = False

    orphaned_summary = not existing_files and summary_present_before is True
    if local_cleanup_only:
        native_result = {
            "grpc_http_status": None,
            "grpc_status": None,
            "grpc_message": "",
            "grpc_confirmed": True,
            "native_method": "tombstone-local-cleanup",
        }
    else:
        native_result = (
            _delete_trajectory_summary(convo_id)
            if orphaned_summary
            else _delete_cascade_trajectory(convo_id)
        )
    if not native_result["grpc_confirmed"]:
        return {
            "success": False,
            "found": True,
            "code": "native_delete_unconfirmed",
            "conversation_id": convo_id,
            "removed_files": [],
            "remaining_files": sorted(str(path) for path in existing_files),
            "summary_present": bool(summary_present_before),
            **native_result,
        }

    def wait_for_summary_absence():
        current = summary_present_before
        consecutive_absent_reads = 0
        for _ in range(30):
            current = _summary_catalog_contains(convo_id)
            if current is False:
                consecutive_absent_reads += 1
                if consecutive_absent_reads >= 2:
                    return False
            else:
                consecutive_absent_reads = 0
            time.sleep(0.1)
        return current

    summary_present = wait_for_summary_absence()
    if (
        summary_present is not False
        and native_result.get("native_method") == "DeleteCascadeTrajectory"
    ):
        native_result = _delete_trajectory_summary(convo_id)
        if native_result["grpc_confirmed"]:
            summary_present = wait_for_summary_absence()
    if summary_present is not False:
        return {
            "success": False,
            "found": True,
            "code": "native_delete_unconfirmed",
            "conversation_id": convo_id,
            "removed_files": [],
            "remaining_files": sorted(str(path) for path in existing_files),
            "summary_present": (
                None if summary_present is None else bool(summary_present)
            ),
            **native_result,
        }

    # The native index is now authoritative. Give the LS a moment to release DB locks.
    time.sleep(0.5)

    removed_files = []
    for attempt in range(10):
        remaining = 0
        for suffix in suffixes:
            fpath = Path(str(db_base) + suffix)
            if fpath.exists():
                try:
                    os.remove(fpath)
                    removed_files.append(str(fpath))
                    print(f"[AntigravitySync] Deleted file: {fpath}", flush=True)
                except Exception as e:
                    remaining += 1
        if remaining == 0:
            print(f"[AntigravitySync] All files for convo {convo_id} deleted successfully.", flush=True)
            break
        time.sleep(0.3)

    remaining_files = [
        str(Path(str(db_base) + suffix))
        for suffix in suffixes
        if Path(str(db_base) + suffix).exists()
    ]
    result = {
        "success": not remaining_files,
        "found": True,
        "conversation_id": convo_id,
        "removed_files": sorted(set(removed_files)),
        "remaining_files": remaining_files,
        "summary_present": False,
        **native_result,
    }
    if remaining_files:
        result["code"] = "local_cleanup_incomplete"
    return result

def parse_protobuf(data):
    fields = []
    pos = 0
    while pos < len(data):
        try:
            header = 0
            shift = 0
            while True:
                b = data[pos]
                header |= (b & 0x7f) << shift
                pos += 1
                if not (b & 0x80): break
                shift += 7
            field_number = header >> 3
            wire_type = header & 0x07
        except IndexError:
            break

        if wire_type == 0:
            shift = 0
            val = 0
            while True:
                try:
                    b = data[pos]
                    val |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                except IndexError:
                    break
            fields.append((field_number, wire_type, val))
        elif wire_type == 2:
            length = 0
            shift = 0
            while True:
                try:
                    b = data[pos]
                    length |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                except IndexError:
                    break
            val = data[pos:pos+length]
            pos += length
            fields.append((field_number, wire_type, val))
        else:
            break
    return fields

def encode_field_bytes(fn, val):
    """Encodes a length-delimited protobuf field (wire type 2)."""
    header = (fn << 3) | 2
    return encode_varint(header) + encode_varint(len(val)) + val

def build_attachment_field(mime_type, file_name, file_path, file_data):
    """Builds the binary protobuf field for a single file attachment (Field 9 of Field 19)."""
    f1 = encode_field_bytes(1, mime_type.encode('utf-8'))
    f4 = encode_field_bytes(4, file_name.encode('utf-8'))
    f5 = encode_field_bytes(5, file_path.encode('utf-8'))
    f6 = encode_field_bytes(6, file_data)
    return f1 + f4 + f5 + f6

def add_attachments_to_payload(payload, attachments):
    """Injects file attachments (Field 9) into the User Prompt payload (Field 19)."""
    outer_fields = parse_protobuf(payload)
    new_outer = []

    for fn, wt, val in outer_fields:
        if fn == 19 and wt == 2:
            inner_fields = parse_protobuf(val)
            new_inner = []

            # Keep all non-attachment inner fields
            for ifn, iwt, ival in inner_fields:
                if ifn != 9:
                    if iwt == 0:
                        header = (ifn << 3) | 0
                        new_inner.append(encode_varint(header) + encode_varint(ival))
                    elif iwt == 2:
                        new_inner.append(encode_field_bytes(ifn, ival))

            # Append new attachments
            for att in attachments:
                att_bytes = build_attachment_field(
                    att['mime_type'],
                    att['file_name'],
                    att['file_path'],
                    att['file_data']
                )
                new_inner.append(encode_field_bytes(9, att_bytes))

            f19_bytes = b"".join(new_inner)
            new_outer.append(encode_field_bytes(19, f19_bytes))
        else:
            if wt == 0:
                header = (fn << 3) | 0
                new_outer.append(encode_varint(header) + encode_varint(val))
            elif wt == 2:
                new_outer.append(encode_field_bytes(fn, val))

    return b"".join(new_outer)

def get_user_prompt_from_payload(payload):
    """Extracts text content and attachments from a User Prompt payload (step 14)."""
    outer_fields = parse_protobuf(payload)
    content = None
    attachments = []
    for fn, wt, val in outer_fields:
        if fn == 19 and wt == 2:
            inner_fields = parse_protobuf(val)
            for ifn, iwt, ival in inner_fields:
                if ifn == 2 and iwt == 2:
                    try:
                        content = ival.decode('utf-8')
                    except:
                        pass
                elif ifn == 3 and iwt == 2 and content is None:
                    try:
                        nested_fields = parse_protobuf(ival)
                        nested_text = next(
                            (
                                nested_val for nested_fn, nested_wt, nested_val in nested_fields
                                if nested_fn == 1 and nested_wt == 2
                            ),
                            None,
                        )
                        content = (nested_text if nested_text is not None else ival).decode('utf-8')
                    except:
                        pass
                elif ifn == 9 and iwt == 2:
                    att_fields = parse_protobuf(ival)
                    mime_type = ""
                    file_name = ""
                    file_path = ""
                    for afn, awt, aval in att_fields:
                        if afn == 1 and awt == 2:
                            mime_type = aval.decode('utf-8', errors='ignore')
                        elif afn == 4 and awt == 2:
                            file_name = aval.decode('utf-8', errors='ignore')
                        elif afn == 5 and awt == 2:
                            file_path = aval.decode('utf-8', errors='ignore')
                    if mime_type or file_name or file_path:
                        attachments.append({
                            "mime_type": mime_type,
                            "file_name": file_name,
                            "file_path": file_path
                        })
    return content, attachments

def get_agent_response_from_payload(payload):
    """Extracts final text content and thinking/reasoning from an Assistant Response payload (step 15)."""
    outer_fields = parse_protobuf(payload)
    content = None
    thinking = None
    for fn, wt, val in outer_fields:
        if fn == 20 and wt == 2:
            inner_fields = parse_protobuf(val)
            if inner_fields:
                for inner_fn, inner_wt, inner_val in inner_fields:
                    if inner_fn in (1, 8) and inner_wt == 2:
                        try:
                            content = inner_val.decode('utf-8')
                        except:
                            pass
                    elif inner_fn == 3 and inner_wt == 2:
                        try:
                            thinking = inner_val.decode('utf-8')
                        except:
                            pass
    return content, thinking


def _first_protobuf_value(
    fields: Iterable[tuple[int, int, Any]],
    field_number: int,
    wire_type: Optional[int] = None,
    default: Any = None,
) -> Any:
    return next(
        (
            value
            for number, actual_wire_type, value in fields
            if number == field_number
            and (wire_type is None or actual_wire_type == wire_type)
        ),
        default,
    )


def _protobuf_timestamp(blob: bytes) -> float:
    fields = parse_protobuf(blob or b"")
    seconds = int(_first_protobuf_value(fields, 1, 0, 0) or 0)
    nanos = int(_first_protobuf_value(fields, 2, 0, 0) or 0)
    return seconds + (nanos / 1_000_000_000)


def _workspace_path_from_uri(uri: str) -> str:
    value = urllib.parse.unquote(str(uri or "").replace("file:///", ""))
    if value.startswith("/") and ":" in value[1:3]:
        value = value[1:]
    return value.replace("/", os.sep)


def _decode_antigravity_summary(
    convo_id: str,
    summary_blob: bytes,
) -> Dict[str, Any]:
    fields = parse_protobuf(summary_blob)
    title_bytes = _first_protobuf_value(fields, 1, 2, b"")
    workspace_blob = _first_protobuf_value(fields, 9, 2, b"")
    workspace_fields = parse_protobuf(workspace_blob)
    workspace_uri = _first_protobuf_value(workspace_fields, 1, 2, b"")
    repository_blob = _first_protobuf_value(workspace_fields, 3, 2, b"")
    repository_fields = parse_protobuf(repository_blob)
    repository_name = _first_protobuf_value(repository_fields, 1, 2, b"")

    annotations_blob = _first_protobuf_value(fields, 15, 2, b"")
    annotation_fields = parse_protobuf(annotations_blob)
    archived = bool(_first_protobuf_value(annotation_fields, 4, 0, 0))
    archived_at_blob = _first_protobuf_value(annotation_fields, 5, 2, b"")

    metadata_blob = _first_protobuf_value(fields, 17, 2, b"")
    metadata_fields = parse_protobuf(metadata_blob)
    root_id = _first_protobuf_value(metadata_fields, 6, 2, b"")
    project_id = _first_protobuf_value(metadata_fields, 18, 2, b"")
    metadata_workspace_uri = _first_protobuf_value(metadata_fields, 7, 2, b"")

    uri_bytes = workspace_uri or metadata_workspace_uri
    workspace_path = _workspace_path_from_uri(
        uri_bytes.decode("utf-8", errors="ignore")
    ) if uri_bytes else ""
    status_code = int(_first_protobuf_value(fields, 5, 0, 0) or 0)
    created_at = _protobuf_timestamp(
        _first_protobuf_value(fields, 7, 2, b"")
    )
    updated_at = _protobuf_timestamp(
        _first_protobuf_value(fields, 3, 2, b"")
    )

    return {
        "convo_id": convo_id,
        "root_conversation_id": (
            root_id.decode("utf-8", errors="ignore") if root_id else convo_id
        ),
        "trajectory_id": (
            _first_protobuf_value(fields, 4, 2, b"")
            .decode("utf-8", errors="ignore")
        ),
        "title": (
            title_bytes.decode("utf-8", errors="ignore") if title_bytes else "Neuer Chat"
        ),
        "workspace_path": workspace_path,
        "project_uuid": (
            project_id.decode("utf-8", errors="ignore") if project_id else ""
        ),
        "project_name": Path(workspace_path).name if workspace_path else "",
        "repository_name": (
            repository_name.decode("utf-8", errors="ignore")
            if repository_name
            else ""
        ),
        "conversation_type": "project" if workspace_path else "normal",
        "archived": archived,
        "archived_at": _protobuf_timestamp(archived_at_blob) if archived_at_blob else 0.0,
        "status": "running" if status_code == 2 else "complete",
        "status_code": status_code,
        "step_count": int(_first_protobuf_value(fields, 2, 0, 0) or 0),
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "source": "antigravity",
    }


def scan_antigravity_conversation_catalog() -> List[Dict[str, Any]]:
    """Read the complete Conversation History catalog with archive annotations."""
    antigravity_dir = Path.home() / ".gemini" / "antigravity"
    convo_dir = antigravity_dir / "conversations"
    summary_file = antigravity_dir / "agyhub_summaries_proto.pb"
    existing_ids = {
        path.stem
        for path in convo_dir.glob("*.db")
    } if convo_dir.exists() else set()
    results: Dict[str, Dict[str, Any]] = {}

    if summary_file.exists():
        try:
            for field_number, wire_type, map_blob in parse_protobuf(
                summary_file.read_bytes()
            ):
                if field_number != 1 or wire_type != 2:
                    continue
                map_fields = parse_protobuf(map_blob)
                convo_id_bytes = _first_protobuf_value(map_fields, 1, 2, b"")
                summary_blob = _first_protobuf_value(map_fields, 2, 2, b"")
                convo_id = convo_id_bytes.decode("utf-8", errors="ignore")
                if not convo_id or convo_id not in existing_ids or not summary_blob:
                    continue
                results[convo_id] = _decode_antigravity_summary(
                    convo_id,
                    summary_blob,
                )
        except Exception as error:
            print(
                f"[AntigravitySync] Error reading conversation summary catalog: {error}",
                flush=True,
            )

    missing_ids = existing_ids - set(results)
    if missing_ids:
        for fallback in scan_integrity_convos(missing_ids):
            fallback["root_conversation_id"] = fallback["convo_id"]
            fallback["project_name"] = (
                Path(fallback["workspace_path"]).name
                if fallback.get("workspace_path")
                else ""
            )
            fallback["repository_name"] = ""
            fallback["conversation_type"] = (
                "project" if fallback.get("workspace_path") else "normal"
            )
            fallback["archived"] = False
            fallback["archived_at"] = 0.0
            fallback["status"] = "complete"
            fallback["status_code"] = 0
            fallback["step_count"] = 0
            fallback["updated_at"] = fallback["created_at"]
            fallback["source"] = "antigravity"
            results[fallback["convo_id"]] = fallback

    return sorted(
        results.values(),
        key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0),
        reverse=True,
    )


def scan_integrity_convos(convo_ids: Optional[Iterable[str]] = None):
    """Scan Anti-Gravity conversation databases and return metadata plus history."""
    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    results = []
    selected_ids = set(convo_ids) if convo_ids is not None else None
    if not convo_dir.exists():
        return results

    for f in convo_dir.glob("*.db"):
        convo_id = f.stem
        if selected_ids is not None and convo_id not in selected_ids:
            continue
        try:
            db_uri = str(f.resolve()).replace('\\', '/')
            conn = sqlite3.connect(f"file:{db_uri}?mode=ro", uri=True)
            try:
                # 1. Resolve workspace and project ID
                row = conn.execute("SELECT data FROM trajectory_metadata_blob WHERE id = 'main'").fetchone()
                if not row:
                    continue
                blob = row[0]
                idx = blob.find(b'file:///')
                workspace_path = ""
                if idx != -1:
                    end = idx
                    while end < len(blob) and 32 <= blob[end] <= 126:
                        end += 1
                    uri = blob[idx:end].decode('utf-8')
                    workspace_path = urllib.parse.unquote(uri.replace('file:///', ''))
                    if workspace_path.startswith('/') and ':' in workspace_path[1:3]:
                        workspace_path = workspace_path[1:] # strip leading slash on windows (e.g. /D:/ -> D:/)

                # Extract project UUID from the blob
                uuids = re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', blob.decode('latin1'), re.IGNORECASE)
                project_uuid = uuids[1] if len(uuids) >= 2 else (uuids[0] if uuids else "")

                # 2. Get first message as title
                title = "Neuer Chat"
                rows_steps = conn.execute(
                    "SELECT step_type, step_payload FROM steps WHERE step_type = 14 ORDER BY idx ASC LIMIT 1"
                ).fetchall()
                for stype, payload in rows_steps:
                    if stype == 14: # user prompt
                        first_msg, _ = get_user_prompt_from_payload(payload)
                        if first_msg:
                            title = first_msg[:60] + ("..." if len(first_msg) > 60 else "")
                            break

                # Get created_at time
                created_at = f.stat().st_mtime

                results.append({
                    "convo_id": convo_id,
                    "workspace_path": workspace_path,
                    "project_uuid": project_uuid,
                    "title": title,
                    "created_at": created_at
                })
            finally:
                conn.close()
        except Exception as e:
            print(f"[AntigravitySync] Error scanning conversation {convo_id}: {e}")

    return results

def parse_tool_call(payload):
    """Parses a tool call step (type 17 or 21) and returns (tool_name, args_json)."""
    try:
        outer_fields = parse_protobuf(payload)
        for fn, wt, val in outer_fields:
            if fn == 5 and wt == 2:
                sub_fields = parse_protobuf(val)
                for sfn, swt, sval in sub_fields:
                    if sfn == 4 and swt == 2:
                        tf = parse_protobuf(sval)
                        tool_name = ""
                        args_json = ""
                        for tfn, twt, tval in tf:
                            if tfn == 2 and twt == 2:
                                tool_name = tval.decode('utf-8', errors='ignore')
                            elif tfn == 3 and twt == 2:
                                args_json = tval.decode('utf-8', errors='ignore')
                        if tool_name:
                            return tool_name, args_json
    except Exception:
        pass

    # Fallback: Regex-based extraction for type 21 (which has different protobuf layout)
    try:
        import re
        text = payload.decode('utf-8', errors='ignore')
        # Type 21 payloads contain tool_name followed by JSON args
        # Pattern: tool_name appears as a readable string, then JSON block
        known_tools = [
            'run_command', 'view_file', 'write_to_file', 'replace_file_content',
            'multi_replace_file_content', 'list_dir', 'grep_search', 'search_web',
            'read_url_content', 'generate_image', 'ask_question', 'ask_permission',
            'invoke_subagent', 'send_message', 'schedule', 'manage_task',
            'manage_subagents', 'define_subagent',
        ]
        for tool in known_tools:
            idx = text.find(tool)
            if idx != -1:
                # Find the JSON args after the tool name
                json_start = text.find('{', idx)
                if json_start != -1:
                    # Find matching closing brace
                    depth = 0
                    end = json_start
                    for i in range(json_start, min(len(text), json_start + 5000)):
                        if text[i] == '{': depth += 1
                        elif text[i] == '}': depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                    args = text[json_start:end]
                    return tool, args
                return tool, ""
    except Exception as e:
        print(f"[AntigravitySync] Error in tool call fallback: {e}")
    return None, None

def parse_tool_output(payload, step_type):
    """Parses a tool output step (type 8/9) and returns the output text."""
    try:
        outer_fields = parse_protobuf(payload)
        if step_type == 8:
            for fn, wt, val in outer_fields:
                if fn == 14 and wt == 2:
                    sub_fields = parse_protobuf(val)
                    for sfn, swt, sval in sub_fields:
                        if sfn == 4 and swt == 2:
                            return sval.decode('utf-8', errors='ignore')
        elif step_type == 9:
            # list_dir output
            for fn, wt, val in outer_fields:
                if fn == 5 and wt == 2:
                    sub_fields = parse_protobuf(val)
                    for sfn, swt, sval in sub_fields:
                        if sfn == 4 and swt == 2:
                            tf = parse_protobuf(sval)
                            for tfn, twt, tval in tf:
                                if tfn == 3 and twt == 2:
                                    args = tval.decode('utf-8', errors='ignore')
                                    return f"List directory contents of: {args}"
    except Exception as e:
        print(f"[AntigravitySync] Error parsing tool output: {e}")
    return None


def extract_step_timing(metadata, status=None):
    """Return normalized timing fields from Anti-Gravity step metadata.

    The desktop app stores protobuf ``Timestamp`` messages in metadata fields
    6 (started) and 8 (finished). Keeping the decoder here makes persisted
    history and the live event stream use the same source of truth.
    """
    if not metadata:
        return {}

    def decode_timestamp(value):
        try:
            fields = parse_protobuf(value)
            seconds = next((item for field, wire, item in fields if field == 1 and wire == 0), None)
            nanos = next((item for field, wire, item in fields if field == 2 and wire == 0), 0)
            if seconds is None:
                return None
            return float(seconds) + (float(nanos) / 1_000_000_000)
        except Exception:
            return None

    try:
        metadata_fields = parse_protobuf(metadata)
    except Exception:
        return {}

    started_at = None
    finished_at = None
    for field, wire, value in metadata_fields:
        if wire != 2:
            continue
        if field == 6 and started_at is None:
            started_at = decode_timestamp(value)
        elif field == 8 and finished_at is None:
            finished_at = decode_timestamp(value)

    timing = {}
    if started_at is not None:
        timing["started_at"] = started_at

    is_terminal = status is None or status in TERMINAL_TOOL_STATUSES
    if is_terminal and finished_at is not None and finished_at >= (started_at or 0):
        timing["finished_at"] = finished_at
        if started_at is not None:
            timing["duration_ms"] = max(0, round((finished_at - started_at) * 1000))
    return timing


_WEB_SENT_LOG = Path.home() / ".gemini" / "antigravity" / "web_sent_messages.json"


def record_web_sent_message(convo_id: str, message: str) -> None:
    """Records that a user message originated from the Web Dashboard."""
    try:
        data = {}
        if _WEB_SENT_LOG.exists():
            with open(_WEB_SENT_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
        convo_msgs = data.setdefault(str(convo_id), [])
        msg_str = (message or "").strip()
        if msg_str and msg_str not in convo_msgs:
            convo_msgs.append(msg_str)
        _WEB_SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_WEB_SENT_LOG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to record web sent message: {e}")


def is_web_sent_message(convo_id: str, message: str) -> bool:
    """Checks if a user message was sent via the Web Dashboard."""
    try:
        if not _WEB_SENT_LOG.exists():
            return False
        with open(_WEB_SENT_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
        convo_msgs = data.get(str(convo_id), [])
        msg_str = (message or "").strip()
        return msg_str in convo_msgs
    except Exception:
        return False


def get_integrity_chat_history(convo_id, *, strict=False):
    """Reads the complete step-by-step history from the specified conversation database."""
    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    db_path = convo_dir / f"{convo_id}.db"
    chat_log = []
    max_idx = 0
    if not db_path.exists():
        return {"history": chat_log, "max_idx": max_idx}

    try:
        db_uri = str(db_path.resolve()).replace('\\', '/')
        conn = sqlite3.connect(f"file:{db_uri}?mode=ro", uri=True)
        try:
            try:
                rows = conn.execute(
                    "SELECT idx, step_type, step_payload, status, metadata "
                    "FROM steps ORDER BY idx ASC"
                ).fetchall()
            except sqlite3.OperationalError as error:
                if "metadata" not in str(error).lower():
                    raise
                legacy_rows = conn.execute(
                    "SELECT idx, step_type, step_payload, status "
                    "FROM steps ORDER BY idx ASC"
                ).fetchall()
                rows = [(*row, None) for row in legacy_rows]
            for idx, stype, payload, status, metadata in rows:
                max_idx = max(max_idx, idx)
                timing = extract_step_timing(metadata, status)
                if stype == 14:
                    txt, atts = get_user_prompt_from_payload(payload)
                    if txt or atts:
                        source_origin = "web" if is_web_sent_message(convo_id, txt) else "desktop"
                        entry = {
                            "idx": idx,
                            "type": "message",
                            "role": "user",
                            "content": txt,
                            "attachments": atts,
                            "complete": status in TERMINAL_TOOL_STATUSES,
                            "source": source_origin,
                        }
                        entry.update(timing)
                        chat_log.append(entry)
                elif stype == 15:
                    txt, thinking = get_agent_response_from_payload(payload)
                    if txt or thinking:
                        entry = {
                            "idx": idx,
                            "type": "message",
                            "role": "assistant",
                            "content": txt,
                            "thinking": thinking,
                            "complete": status in TERMINAL_TOOL_STATUSES,
                        }
                        entry.update(timing)
                        chat_log.append(entry)
                elif stype in (17, 21):
                    tname, targs = parse_tool_call(payload)
                    if tname:
                        enriched = enrich_tool_call(tname, targs, status)
                        step_state = _tool_step_state(status)
                        is_terminal = status in TERMINAL_TOOL_STATUSES
                        entry = {
                            "idx": idx,
                            "type": "tool_call",
                            "tool_name": tname,
                            "args": targs,
                            "status": status,
                            "state": step_state,
                            "is_running": step_state == "running",
                            "is_terminal": is_terminal,
                            "complete": is_terminal,
                            "requires_user_input": status == 9,
                        }
                        if enriched:
                            entry["enriched"] = enriched
                        entry.update(timing)
                        chat_log.append(entry)
                elif stype in (8, 9):
                    tout = parse_tool_output(payload, stype)
                    if tout:
                        entry = {
                            "idx": idx,
                            "type": "tool_output",
                            "output": tout,
                            "complete": status in TERMINAL_TOOL_STATUSES,
                        }
                        entry.update(timing)
                        chat_log.append(entry)
        finally:
            conn.close()
    except Exception as e:
        print(f"[AntigravitySync] Error loading chat history for {convo_id}: {e}")
        if strict:
            raise
    return {"history": chat_log, "max_idx": max_idx}

def patch_sqlite_user_message_attachments(convo_id, attachments):
    """Patches the last step of type 14 (User Prompt) in SQLite to inject attachments."""
    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    db_path = convo_dir / f"{convo_id}.db"
    if not db_path.exists():
        return False

    try:
        conn = sqlite3.connect(db_path)
        try:
            # Get last user prompt step
            row = conn.execute("SELECT idx, step_payload FROM steps WHERE step_type = 14 ORDER BY idx DESC LIMIT 1").fetchone()
            if not row:
                return False

            idx, payload = row
            patched_payload = add_attachments_to_payload(payload, attachments)

            # Update SQLite step payload
            conn.execute("UPDATE steps SET step_payload = ? WHERE idx = ?", (patched_payload, idx))
            conn.commit()
            print(f"[AntigravitySync] Successfully patched user message attachments for step {idx} in {convo_id}.db", flush=True)
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[AntigravitySync] Failed to patch user message attachments: {e}")
    return False


def get_file_diff_stats(file_path):
    """
    Generate unified diff, lines added, and lines removed for a file.
    Compares the current file on disk with its HEAD version from git.
    """
    import subprocess
    import difflib
    from pathlib import Path

    file_path = Path(file_path).resolve()
    if not file_path.exists():
        return 0, 0, ""

    # Find git root
    git_root = None
    curr = file_path.parent
    for _ in range(10):
        if (curr / ".git").exists():
            git_root = curr
            break
        if curr.parent == curr:
            break
        curr = curr.parent

    if not git_root:
        return 0, 0, ""

    # Get relative path to git root
    try:
        rel_path = file_path.relative_to(git_root).as_posix()
    except ValueError:
        return 0, 0, ""

    try:
        # Run git show HEAD:rel_path
        cmd = ["git", "show", f"HEAD:{rel_path}"]
        res = subprocess.run(
            cmd,
            cwd=str(git_root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if res.returncode != 0:
            # Maybe file is new
            head_content = []
        else:
            head_content = res.stdout.splitlines()

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            disk_content = f.read().splitlines()

        diff = list(difflib.unified_diff(
            head_content,
            disk_content,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm=""
        ))

        added = 0
        removed = 0
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1

        diff_text = "\n".join(diff)
        return added, removed, diff_text
    except Exception as e:
        print(f"[AntigravitySync] Error diffing file {file_path}: {e}")
        return 0, 0, ""


def _tool_step_state(status: Optional[int]) -> str:
    if status == 2:
        return "running"
    if status == 3:
        return "complete"
    if status == 6:
        return "cancelled"
    if status == 7:
        return "failed"
    if status == 9:
        return "waiting_user"
    return "pending"


def _command_port(command: str) -> Optional[int]:
    patterns = (
        r"(?:--port(?:=|\s+)|\s-p\s+)(\d{2,5})(?:\D|$)",
        r"https?://(?:localhost|127\.0\.0\.1):(\d{2,5})(?:\D|$)",
        r"(?:http\.server|uvicorn|gunicorn)\s+(\d{2,5})(?:\D|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if not match:
            continue
        port = int(match.group(1))
        if 1 <= port <= 65535:
            return port
    return None


def _looks_like_server_command(command: str) -> bool:
    return bool(re.search(
        (
            r"\b(vite|next\s+dev|nuxt\s+dev|ng\s+serve|http-server|"
            r"python(?:\d+(?:\.\d+)*)?\s+-m\s+http\.server|"
            r"uvicorn|gunicorn|flask\s+run|npm\s+run\s+(?:dev|start)|"
            r"pnpm\s+(?:dev|start)|yarn\s+(?:dev|start))\b"
        ),
        command,
        re.IGNORECASE,
    ))


def enrich_tool_call(tool_name, args_json, status: Optional[int] = None):
    """
    Enriches command calls with runtime metadata and file calls with diff stats.
    Returns a dict with extra info (or None if not applicable).
    """
    import json
    try:
        args = json.loads(args_json)
        if not isinstance(args, dict):
            return None

        if tool_name == "run_command":
            command = str(
                args.get("CommandLine")
                or args.get("command")
                or args.get("cmd")
                or ""
            ).strip()
            if not command:
                return None
            port = _command_port(command)
            step_state = _tool_step_state(status)
            is_server = _looks_like_server_command(command)
            try:
                wait_ms = int(args.get("WaitMsBeforeAsync") or 0)
            except (TypeError, ValueError):
                wait_ms = 0
            return {
                "kind": "command",
                "command": command,
                "cwd": str(
                    args.get("Cwd")
                    or args.get("cwd")
                    or ""
                ),
                "action": str(
                    args.get("toolAction")
                    or args.get("action")
                    or ""
                ),
                "summary": str(
                    args.get("toolSummary")
                    or args.get("summary")
                    or ""
                ),
                "wait_ms": wait_ms,
                "port": port,
                "url": f"http://127.0.0.1:{port}" if port else "",
                "server_command": is_server,
                "background_task": bool(step_state == "running" and is_server),
                "state": step_state,
                "terminal": status in TERMINAL_TOOL_STATUSES,
            }

        if tool_name not in (
            "replace_file_content",
            "multi_replace_file_content",
            "write_to_file",
        ):
            return None

        target_file = args.get('TargetFile') or args.get('targetFile')
        if target_file and os.path.exists(target_file):
            added, removed, diff_text = get_file_diff_stats(target_file)
            # Only return stats if there are actual changes
            if added > 0 or removed > 0:
                file_name = os.path.basename(target_file)
                return {
                    "kind": "file_change",
                    "file_name": file_name,
                    "file_path": target_file.replace('\\', '/'),
                    "lines_added": added,
                    "lines_removed": removed,
                    "diff": diff_text
                }
    except Exception as e:
        print(f"[AntigravitySync] Error enriching tool call: {e}")
    return None
