"""Verify the installed AMS preload contract through local Chrome DevTools."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import urllib.request
from pathlib import Path

import aiohttp


SCRIPT_DIR = Path(__file__).resolve().parent


def load_repack_module():
    script_path = SCRIPT_DIR / "repack_and_restart.py"
    spec = importlib.util.spec_from_file_location("ams_repack_runtime", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_targets(port: int) -> list[dict[str, object]]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/json")
    with urllib.request.urlopen(request, timeout=2) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise RuntimeError("DevTools target response exceeded 2 MiB.")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("DevTools target response is not a list.")
    return [target for target in payload if isinstance(target, dict)]


def page_targets(port: int) -> list[dict[str, object]]:
    return [
        target
        for target in read_targets(port)
        if target.get("type") == "page"
        and isinstance(target.get("id"), str)
        and isinstance(target.get("webSocketDebuggerUrl"), str)
    ]


async def cdp_call(ws, request_id: int, method: str, params=None):
    request = {"id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    await ws.send_json(request)
    async for message in ws:
        if message.type != aiohttp.WSMsgType.TEXT:
            continue
        payload = json.loads(message.data)
        if payload.get("id") != request_id:
            continue
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result", {})
    raise RuntimeError("DevTools connection closed before the response arrived.")


async def evaluate(ws, request_id: int, expression: str):
    result = await cdp_call(
        ws,
        request_id,
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    if result.get("exceptionDetails"):
        raise RuntimeError(
            str(result["exceptionDetails"].get("text", "Runtime evaluation failed."))
        )
    return result.get("result", {}).get("value")


async def target_role(session, target, request_id: int):
    async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
        return await evaluate(
            ws,
            request_id,
            "window.electronNative?.getWindowRole?.()",
        )


async def close_new_duplicates(session, port: int, before_ids: set[str]) -> set[str]:
    closed: set[str] = set()
    for index, target in enumerate(page_targets(port)):
        target_id = target["id"]
        if target_id in before_ids:
            continue
        try:
            async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                role = await evaluate(
                    ws,
                    900 + index * 2,
                    "window.electronNative?.getWindowRole?.()",
                )
                if role != "duplicate":
                    continue
                await evaluate(
                    ws,
                    901 + index * 2,
                    "window.electronNative.close(); true",
                )
                closed.add(target_id)
        except Exception:
            continue
    return closed


async def verify() -> dict[str, bool]:
    repack = load_repack_module()
    _install_dir, _resources_dir, app_path = repack.resolve_install_paths()
    port_file = repack.resolve_user_data_dir() / "DevToolsActivePort"
    port = repack.find_devtools_port(port_file, app_path, io.StringIO())
    if port is None:
        raise RuntimeError("DevTools endpoint for the exact installation was not found.")

    before = page_targets(port)
    before_ids = {target["id"] for target in before}
    results = {
        "devtools": True,
        "primary_role": False,
        "hub_request": False,
        "prepare_automation": False,
        "open_duplicate": False,
        "duplicate_role": False,
        "duplicate_prepare_automation": False,
        "test_duplicate_closed": False,
    }

    async with aiohttp.ClientSession() as session:
        duplicate_id = None
        try:
            primary = None
            for index, target in enumerate(before):
                try:
                    if await target_role(session, target, 10 + index) == "primary":
                        primary = target
                        break
                except Exception:
                    continue
            if primary is None:
                raise RuntimeError("Primary Antigravity target was not found.")
            results["primary_role"] = True

            async with session.ws_connect(primary["webSocketDebuggerUrl"]) as ws:
                hub_result = await evaluate(
                    ws,
                    100,
                    """(async () => {
                        const result = await window.electronNative.hubRequest(
                            '', 'services:status', {}
                        );
                        return {
                            object: Boolean(result) && typeof result === 'object',
                            success: result?.success !== false,
                            error: typeof result?.error === 'string' && result.error.length > 0,
                        };
                    })()""",
                )
                results["hub_request"] = bool(
                    hub_result
                    and hub_result.get("object")
                    and hub_result.get("success")
                    and not hub_result.get("error")
                )
                prepare_result = await evaluate(
                    ws,
                    101,
                    "window.electronNative.prepareAutomation()",
                )
                results["prepare_automation"] = bool(
                    prepare_result and prepare_result.get("success")
                )
                open_result = await evaluate(
                    ws,
                    102,
                    "window.electronNative.openDuplicateWindow('')",
                )
                results["open_duplicate"] = bool(
                    open_result and open_result.get("success")
                )

            await asyncio.sleep(1.5)
            for index, target in enumerate(page_targets(port)):
                if target["id"] in before_ids:
                    continue
                try:
                    async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                        role = await evaluate(
                            ws,
                            200 + index * 2,
                            "window.electronNative?.getWindowRole?.()",
                        )
                        if role != "duplicate":
                            continue
                        duplicate_id = target["id"]
                        results["duplicate_role"] = True
                        prepared = await evaluate(
                            ws,
                            201 + index * 2,
                            "window.electronNative.prepareAutomation()",
                        )
                        results["duplicate_prepare_automation"] = bool(
                            prepared and prepared.get("success")
                        )
                        break
                except Exception:
                    continue
        finally:
            closed = await close_new_duplicates(session, port, before_ids)
            await asyncio.sleep(0.75)
            remaining = {target["id"] for target in page_targets(port)}
            results["test_duplicate_closed"] = bool(
                duplicate_id and duplicate_id in closed and duplicate_id not in remaining
            )
    return results


def main() -> int:
    results = asyncio.run(verify())
    print(json.dumps(results, sort_keys=True))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
