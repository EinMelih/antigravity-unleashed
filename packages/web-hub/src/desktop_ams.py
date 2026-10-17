"""Reuse verified desktop AMS UI and expose only its bounded native methods."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from src.cdp_client import AntigravityCDP
from src.redaction import redact_sensitive_text


@dataclass(frozen=True)
class NativeMethod:
    namespace: str
    method: str
    minimum: int
    maximum: int
    readonly: bool


METHODS: dict[str, NativeMethod] = {}


def _register(names: str, minimum: int, maximum: int, readonly: bool, namespace: str = 'electronNative') -> None:
    for name in names.split():
        key = name if namespace == 'electronNative' else f'{namespace}.{name}'
        METHODS[key] = NativeMethod(namespace, name, minimum, maximum, readonly)


_register('getProfileInfo getWindowRole getSyncStatus getReviews getHistory isMaximized', 0, 0, True)
_register('getPRs getIssues getGitStatus getRunLog getTaskPlan getNotes getCompactionCount getTokenStats', 0, 1, True)
_register('getGitDiff', 2, 3, True)
_register('openBrain minimize maximize unmaximize close toggleDevTools zoomIn zoomOut resetZoom', 0, 0, False)
_register('openExternal writeToClipboard', 1, 1, False)
_register('applyMemorySuggestion', 2, 2, False)
_register('setTitleBarOverlay', 1, 1, False)
_register('commitAndPush setTaskPlan', 1, 2, False)
_register('generateCommitMsg deleteTempConversation consolidateMemory', 2, 2, False)
_register('setNotes', 2, 3, False)
_register('openDuplicateWindow readSwitchRequest', 0, 1, False)
_register('writeStatus', 2, 2, False)
_register('hubRequest', 3, 3, False)
_register('getItems', 0, 0, True, 'nativeStorage')
_register('getState', 0, 0, True, 'electronUpdater')
_register('checkForUpdates applyUpdate quitAndInstall', 0, 0, False, 'electronUpdater')
_register('showOpenDialog showOpenMultipleFolderDialog', 0, 1, False, 'dialog')
_register('isInstalled', 0, 0, True, 'ide')
_register('getState', 0, 0, True, 'wsl')
_register('connect', 1, 1, False, 'wsl')
_register('send', 1, 1, False, 'nativeNotifications')
_register('openSystemPreferences', 0, 0, False, 'nativeNotifications')
READ_HUB_OPERATIONS = frozenset({'services:status', 'api:monitor'})


def extract_ams_template(source: str) -> str:
    """Extract one interpolation-free template literal without executing preload."""
    match = re.search(r'\bconst\s+amsScriptContent\s*=\s*`', source)
    if not match:
        raise ValueError('Installed desktop does not contain the AMS UI script.')
    start = match.end() - 1
    cursor = start + 1
    while cursor < len(source):
        character = source[cursor]
        if character == '\\':
            cursor += 2
            continue
        if source.startswith('${', cursor):
            raise ValueError('Interpolated desktop AMS scripts are not supported.')
        if character == '`':
            return source[start:cursor + 1]
        cursor += 1
    raise ValueError('Installed desktop AMS script is incomplete.')


def _archive_file(archive: bytes, filename: str) -> bytes:
    if len(archive) < 16:
        raise ValueError('Installed desktop archive is incomplete.')
    _, header_size, _, json_size = struct.unpack('<4I', archive[:16])
    header = json.loads(archive[16:16 + json_size])
    entry = header
    for component in filename.split('/'):
        entry = entry['files'][component]
    if entry.get('unpacked') or entry.get('link'):
        raise ValueError('Desktop AMS sources must be contained in the verified archive.')
    start = 8 + header_size + int(entry['offset'])
    end = start + entry['size']
    if start < 8 + header_size or end > len(archive):
        raise ValueError('Desktop AMS source is outside the archive payload.')
    return archive[start:end]


def desktop_archive_path() -> Path:
    override = os.environ.get('ANTIGRAVITY_RESOURCES_DIR')
    if override:
        return Path(override).expanduser().resolve() / 'app.asar'
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('The local desktop installation is unavailable.')
    return Path(local) / 'Programs/Antigravity/resources/app.asar'


def protect_quota_updates(source: str) -> str:
    """Keep confirmed quotas when an optional model status omits its fraction."""
    for provider in ('gemini', 'claude'):
        condition = f'{provider}Config && {provider}Config.quotaInfo'
        source = source.replace(f'if ({condition}) {{',
                                f'if ({condition} && Number.isFinite({provider}Config.quotaInfo.remainingFraction)) {{')
    return source


@functools.lru_cache(maxsize=2)
def _load_bundle(archive_path: str, modified: int, size: int, record_modified: int) -> str:
    archive = Path(archive_path).read_bytes()
    record_path = Path.home() / '.gemini/antigravity/scratch/verified_repack_installation.json'
    record = json.loads(record_path.read_text(encoding='utf-8'))
    digest = hashlib.sha256(archive).hexdigest()
    if record.get('installed_asar_sha256') != digest or record.get('profile_contract_version') != 2:
        raise RuntimeError('The installed desktop AMS archive has not been verified.')
    source = _archive_file(archive, 'dist/preload.js').decode('utf-8')
    literal = extract_ams_template(source)
    # The literal is proven to contain no executable interpolations. Node only
    # decodes JavaScript escapes; neither preload nor desktop APIs are executed.
    decoder = "const fs=require('node:fs'); const vm=require('node:vm'); process.stdout.write(vm.runInNewContext(fs.readFileSync(0,'utf8'), Object.create(null), {timeout:100}));"
    result = subprocess.run(['node', '-e', decoder], input=literal, text=True, encoding='utf-8',
                            capture_output=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not result.stdout.strip():
        raise RuntimeError('The verified desktop AMS script could not be decoded.')
    return protect_quota_updates(result.stdout)


def desktop_bundle() -> str:
    archive = desktop_archive_path()
    record = Path.home() / '.gemini/antigravity/scratch/verified_repack_installation.json'
    return _load_bundle(str(archive), archive.stat().st_mtime_ns, archive.stat().st_size, record.stat().st_mtime_ns)


async def desktop_bundle_handler(request: web.Request) -> web.Response:
    try:
        import asyncio
        source = await asyncio.to_thread(desktop_bundle)
        return web.Response(text=source, content_type='application/javascript',
                            headers={'Cache-Control': 'no-store', 'Cross-Origin-Resource-Policy': 'same-origin', 'X-Content-Type-Options': 'nosniff'})
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        message = redact_sensitive_text(str(error))
        return web.Response(status=503, text='throw new Error(' + json.dumps('AMS: ' + message) + ');', content_type='application/javascript',
                            headers={'Cache-Control': 'no-store'})


def _validate_args(operation: str, arguments: list) -> NativeMethod:
    spec = METHODS.get(operation)
    if not spec:
        raise ValueError('Unknown desktop AMS operation.')
    if not isinstance(arguments, list) or not spec.minimum <= len(arguments) <= spec.maximum:
        raise ValueError('Invalid desktop AMS arguments.')
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Desktop AMS arguments exceed the supported size.')
    return spec


async def invoke_native_method(operation: str, arguments: list):
    spec = _validate_args(operation, arguments)
    client = AntigravityCDP()
    try:
        await client.connect()
        identity = await client.evaluate('window.electronNative?.getProfileInfo?.()', timeout=5)
        if not isinstance(identity, dict) or identity.get('profile') != 'default' or identity.get('profile_contract_version') != 2:
            raise ConnectionError('AMS requires the verified private desktop profile; the API profile is not a fallback.')
        namespace = json.dumps(spec.namespace)
        method = json.dumps(spec.method)
        values = json.dumps(json.dumps(arguments, ensure_ascii=False, allow_nan=False), ensure_ascii=False)
        expression = f'''(async () => {{
            try {{
                const api = window[{namespace}];
                const method = api?.[{method}];
                if (typeof method !== 'function') return {{ok:false,error:{{code:'AMS_METHOD_MISSING',message:'Desktop function unavailable'}}}};
                const data = await method.apply(api, JSON.parse({values}));
                return {{ok:true,data:data === undefined ? null : data}};
            }} catch (error) {{ return {{ok:false,error:{{code:error.code || 'AMS_NATIVE_ERROR',message:error.message || String(error)}}}}; }}
        }})()'''
        timeout = 180 if operation in {'generateCommitMsg', 'consolidateMemory', 'commitAndPush'} else 30
        result = await client.evaluate(expression, timeout=timeout)
        if not isinstance(result, dict) or result.get('ok') is not True:
            detail = result.get('error', {}) if isinstance(result, dict) else {}
            raise RuntimeError(detail.get('message', 'Desktop returned an invalid AMS result.'))
        return result.get('data')
    finally:
        await client.disconnect()


def _is_readonly(operation: str, arguments: list) -> bool:
    return METHODS[operation].readonly or (operation == 'hubRequest' and arguments[1] in READ_HUB_OPERATIONS)


def _same_origin(request: web.Request) -> bool:
    origin = request.headers.get('Origin')
    if not origin:
        return False
    parsed = urlsplit(origin)
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        return False
    return origin == f'{request.scheme}://{request.host}'


async def native_rpc_handler(request: web.Request) -> web.Response:
    operation = request.match_info['operation']
    try:
        if operation not in METHODS:
            raise ValueError('Unknown desktop AMS operation.')
        if request.method == 'GET':
            arguments = json.loads(request.query.get('args', '[]'))
        elif request.method == 'POST':
            if request.content_type != 'application/json':
                raise web.HTTPUnsupportedMediaType(reason='AMS requests require JSON.')
            if not _same_origin(request):
                raise web.HTTPForbidden(reason='AMS actions require the local Hub origin.')
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != {'args'}:
                raise ValueError('Invalid desktop AMS request.')
            arguments = payload['args']
        else:
            raise web.HTTPMethodNotAllowed(request.method, ['GET', 'POST'])
        _validate_args(operation, arguments)
        if request.method == 'GET' and not _is_readonly(operation, arguments):
            raise web.HTTPMethodNotAllowed('GET', ['POST'])
        result = await invoke_native_method(operation, arguments)
        if isinstance(result, dict) and (result.get('status') in {'error', 'failed'} or result.get('ok') is False or result.get('success') is False):
            detail = result.get('error')
            message = detail.get('message') if isinstance(detail, dict) else detail
            return web.json_response({'ok': False, 'native_result': result,
                                      'error': {'code': 'AMS_NATIVE_ACTION_FAILED', 'message': message or result.get('message') or 'Native AMS action failed.'}},
                                     status=503, headers={'Cache-Control': 'no-store'})
        return web.json_response({'ok': True, 'data': result}, headers={'Cache-Control': 'no-store'})
    except web.HTTPException:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return web.json_response({'ok': False, 'error': {'code': 'AMS_INVALID_REQUEST', 'message': str(error)}}, status=400)
    except Exception as error:
        return web.json_response({'ok': False, 'error': {'code': 'AMS_UNAVAILABLE', 'message': redact_sensitive_text(str(error))}}, status=503,
                                 headers={'Cache-Control': 'no-store'})
