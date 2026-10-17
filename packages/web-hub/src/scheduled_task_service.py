"""Native Anti-Gravity scheduled-task control through the live renderer.

Anti-Gravity models scheduled tasks as ``SidecarStatusInfo`` records.  The
renderer already owns a typed Language Server client, so this adapter discovers
the same ``extensibility`` service used by the native UI and calls its public
methods.  This avoids duplicating private protobuf descriptors and works while
the renderer is minimized or showing a conversation.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from src.cdp_client import AntigravityCDP


_CONTROLLER_VERSION = 2
_SERVICE_LOCK: Optional[asyncio.Lock] = None
_CRON_PART = re.compile(r"^[\d*/,-]+$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


def _service_lock() -> asyncio.Lock:
    global _SERVICE_LOCK
    if _SERVICE_LOCK is None:
        _SERVICE_LOCK = asyncio.Lock()
    return _SERVICE_LOCK


def slugify_task_name(name: str) -> str:
    """Match the task-ID normalization used by the Anti-Gravity UI."""
    normalized = re.sub(r"[/\\]", " ", str(name or "")).strip().lower()
    normalized = re.sub(r"[^a-z0-9\s_-]", "", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")


def validate_task_id(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    if not _TASK_ID.fullmatch(normalized):
        raise ValueError("Invalid scheduled task ID.")
    return normalized


def validate_cron(expression: str) -> str:
    """Validate the five-field cron shape accepted by the native editor."""
    normalized = " ".join(str(expression or "").strip().split())
    parts = normalized.split(" ")
    if len(parts) != 5 or any(not _CRON_PART.fullmatch(part) for part in parts):
        raise ValueError(
            "schedule must be a five-field cron expression, for example '0 9 * * *'."
        )
    return normalized


def normalize_create_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    task_id = slugify_task_name(name)
    project_id = str(payload.get("project_id") or "").strip()
    all_projects = bool(payload.get("all_projects", False))

    if not name:
        raise ValueError("name is required.")
    if not task_id:
        raise ValueError("name must contain at least one ASCII letter or digit.")
    if len(name) > 160:
        raise ValueError("name must be 160 characters or fewer.")
    if not prompt:
        raise ValueError("prompt is required.")
    if len(prompt) > 100_000:
        raise ValueError("prompt must be 100000 characters or fewer.")
    if not all_projects and not project_id:
        raise ValueError("project_id is required unless all_projects is true.")

    return {
        "id": task_id,
        "name": name,
        "schedule": validate_cron(payload.get("schedule", "")),
        "prompt": prompt,
        "project_id": project_id,
        "all_projects": all_projects,
        "enabled": bool(payload.get("enabled", False)),
    }


def normalize_update_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed: Dict[str, Any] = {}
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("name cannot be empty.")
        if len(name) > 160:
            raise ValueError("name must be 160 characters or fewer.")
        allowed["name"] = name
    if "schedule" in payload:
        allowed["schedule"] = validate_cron(payload.get("schedule", ""))
    if "prompt" in payload:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt cannot be empty.")
        if len(prompt) > 100_000:
            raise ValueError("prompt must be 100000 characters or fewer.")
        allowed["prompt"] = prompt
    if "enabled" in payload:
        allowed["enabled"] = bool(payload["enabled"])
    if "project_id" in payload:
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id and not bool(payload.get("all_projects", False)):
            raise ValueError("project_id cannot be empty.")
        allowed["project_id"] = project_id
    if "all_projects" in payload:
        allowed["all_projects"] = bool(payload["all_projects"])
    if not allowed:
        raise ValueError("At least one editable field is required.")
    return allowed


_CONTROLLER_SOURCE = r"""
(() => {
  const VERSION = %d;
  if (window.__agyScheduledTasks?.version === VERSION) return true;

  const safeStringify = value => {
    const seen = new WeakSet();
    return JSON.stringify(value, (key, item) => {
      if (typeof item === "bigint") return item.toString();
      if (typeof item === "function") return undefined;
      if (item && typeof item === "object") {
        if (seen.has(item)) return undefined;
        seen.add(item);
      }
      return item;
    });
  };

  const findExtensibility = () => {
    const visitedFibers = new Set();
    for (const element of document.querySelectorAll("*")) {
      const fiberKey = Object.keys(element).find(key => key.startsWith("__reactFiber$"));
      let fiber = fiberKey ? element[fiberKey] : null;
      let hops = 0;
      while (fiber && hops < 24 && !visitedFibers.has(fiber)) {
        visitedFibers.add(fiber);
        let context = fiber.dependencies?.firstContext || null;
        let contextIndex = 0;
        while (context && contextIndex < 64) {
          const registry = context.memoizedValue;
          if (registry && typeof registry.get === "function") {
            let extension = null;
            try {
              extension = registry.get("extensibility");
            } catch {
              extension = null;
            }
            if (
              extension?.provider &&
              typeof extension.createSidecar === "function" &&
              typeof extension.updateSidecar === "function"
            ) {
              return extension;
            }
          }
          context = context.next;
          contextIndex += 1;
        }
        fiber = fiber.return;
        hops += 1;
      }
    }
    throw new Error("Native Anti-Gravity extensibility service is not ready.");
  };

  const scheduleTasks = extension => (
    extension.provider.getState() || []
  ).filter(item => (
    item?.config?.mode?.case === "builtin" &&
    item?.config?.mode?.value === "schedule"
  ));

  const findTask = (extension, taskId) => {
    const task = scheduleTasks(extension).find(item => item.sidecarId === taskId);
    if (!task) throw new Error(`SCHEDULED_TASK_NOT_FOUND:${taskId}`);
    return task;
  };

  const waitFor = async (extension, predicate, timeoutMs = 8000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const result = predicate(scheduleTasks(extension));
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error("Timed out waiting for Anti-Gravity scheduled-task state.");
  };

  const taskMatchesPayload = (task, payload) => {
    if (!task) return false;
    const config = task.config || {};
    const args = config.args || [];
    const userConfig = task.userConfig || {};
    const projectScope = userConfig.projectScope || {};
    if (
      Object.prototype.hasOwnProperty.call(payload, "name") &&
      config.displayName !== payload.name
    ) return false;
    if (
      Object.prototype.hasOwnProperty.call(payload, "schedule") &&
      args[0] !== payload.schedule
    ) return false;
    if (
      Object.prototype.hasOwnProperty.call(payload, "prompt") &&
      args[3] !== payload.prompt
    ) return false;
    if (
      Object.prototype.hasOwnProperty.call(payload, "enabled") &&
      userConfig.enabled !== Boolean(payload.enabled)
    ) return false;
    if (
      payload.all_projects === true &&
      !(
        projectScope.case === "allProjects" &&
        Boolean(projectScope.value)
      )
    ) return false;
    if (
      payload.all_projects !== true &&
      Object.prototype.hasOwnProperty.call(payload, "project_id") &&
      !(
        projectScope.case === "projectId" &&
        projectScope.value === payload.project_id
      )
    ) return false;
    return true;
  };

  const makeConfig = payload => ({
    $typeName: "exa.cortex_pb.SidecarConfig",
    mode: {case: "builtin", value: "schedule"},
    restartPolicy: "always",
    args: [
      payload.schedule,
      "agentapi",
      "new-conversation",
      payload.prompt
    ],
    description: "",
    hasWebUi: false,
    env: {},
    displayName: payload.name,
    disabled: false,
    arguments: []
  });

  window.__agyScheduledTasks = {
    version: VERSION,

    list() {
      const extension = findExtensibility();
      return safeStringify({
        connected: extension.connectionStatusProvider?.getState?.() ?? true,
        tasks: scheduleTasks(extension)
      });
    },

    async create(payload) {
      const extension = findExtensibility();
      if (scheduleTasks(extension).some(item => item.sidecarId === payload.id)) {
        throw new Error(`SCHEDULED_TASK_EXISTS:${payload.id}`);
      }
      await extension.createSidecar(
        payload.id,
        makeConfig(payload),
        payload.all_projects ? "" : payload.project_id
      );
      await waitFor(
        extension,
        tasks => tasks.find(item => item.sidecarId === payload.id)
      );
      if (payload.all_projects) {
        await extension.setSidecarAllProjects(payload.id, true);
      } else if (payload.project_id) {
        await extension.setSidecarProject(payload.id, payload.project_id);
      }
      await extension.setSidecarEnabled(payload.id, Boolean(payload.enabled));
      const task = await waitFor(
        extension,
        tasks => {
          const current = tasks.find(item => item.sidecarId === payload.id);
          return taskMatchesPayload(current, payload) ? current : null;
        }
      );
      return safeStringify(task);
    },

    async update(taskId, payload) {
      const extension = findExtensibility();
      const existing = findTask(extension, taskId);
      const args = [...(existing.config?.args || [])];
      while (args.length < 4) args.push("");
      args[1] = args[1] || "agentapi";
      args[2] = args[2] || "new-conversation";
      if (Object.prototype.hasOwnProperty.call(payload, "schedule")) {
        args[0] = payload.schedule;
      }
      if (Object.prototype.hasOwnProperty.call(payload, "prompt")) {
        args[3] = payload.prompt;
      }
      if (
        Object.prototype.hasOwnProperty.call(payload, "name") ||
        Object.prototype.hasOwnProperty.call(payload, "schedule") ||
        Object.prototype.hasOwnProperty.call(payload, "prompt")
      ) {
        const config = {
          ...existing.config,
          args,
          displayName: payload.name ?? existing.config?.displayName ?? taskId
        };
        await extension.updateSidecar(taskId, config);
      }
      if (payload.all_projects === true) {
        await extension.setSidecarAllProjects(taskId, true);
      } else if (Object.prototype.hasOwnProperty.call(payload, "project_id")) {
        await extension.setSidecarProject(taskId, payload.project_id);
      }
      if (Object.prototype.hasOwnProperty.call(payload, "enabled")) {
        await extension.setSidecarEnabled(taskId, Boolean(payload.enabled));
      }
      const task = await waitFor(
        extension,
        tasks => {
          const current = tasks.find(item => item.sidecarId === taskId);
          return taskMatchesPayload(current, payload) ? current : null;
        }
      );
      return safeStringify(task);
    },

    async run(taskId) {
      const extension = findExtensibility();
      findTask(extension, taskId);
      await extension.restartSidecar(taskId);
      return safeStringify({success: true, task_id: taskId});
    },

    async remove(taskId) {
      const extension = findExtensibility();
      const existing = findTask(extension, taskId);
      if (existing?.userConfig?.enabled) {
        await extension.setSidecarEnabled(taskId, false);
        await waitFor(
          extension,
          tasks => {
            const current = tasks.find(item => item.sidecarId === taskId);
            return current?.userConfig?.enabled === false ? current : null;
          }
        );
      }
      await new Promise(resolve => setTimeout(resolve, 750));
      let lastError = null;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        try {
          await extension.deleteSidecar(taskId);
          lastError = null;
          break;
        } catch (error) {
          lastError = error;
          if (!scheduleTasks(extension).some(item => item.sidecarId === taskId)) {
            lastError = null;
            break;
          }
          await new Promise(resolve => (
            setTimeout(resolve, 300 + (attempt * 150))
          ));
        }
      }
      if (lastError) throw lastError;
      await waitFor(
        extension,
        tasks => !tasks.some(item => item.sidecarId === taskId)
      );
      return safeStringify({success: true, task_id: taskId});
    },

    async events(taskId) {
      const extension = findExtensibility();
      findTask(extension, taskId);
      const events = await extension.getEvents(taskId);
      return safeStringify({task_id: taskId, events: events || []});
    }
  };
  return true;
})()
""" % _CONTROLLER_VERSION


def _task_to_public(task: Dict[str, Any]) -> Dict[str, Any]:
    config = task.get("config") or {}
    user_config = task.get("userConfig") or {}
    args = list(config.get("args") or [])
    while len(args) < 4:
        args.append("")
    project_scope = user_config.get("projectScope") or {}
    scope_case = str(project_scope.get("case") or "")
    return {
        "id": str(task.get("sidecarId") or ""),
        "name": str(config.get("displayName") or task.get("sidecarId") or ""),
        "schedule": str(args[0] or ""),
        "command": [str(args[1] or ""), str(args[2] or "")],
        "prompt": str(args[3] or ""),
        "enabled": bool(user_config.get("enabled", False)),
        "project_id": (
            str(project_scope.get("value") or "")
            if scope_case == "projectId"
            else ""
        ),
        "all_projects": scope_case == "allProjects" and bool(project_scope.get("value")),
        "status_code": int(task.get("status") or 0),
        "last_error": str(task.get("lastError") or ""),
        "start_time_ms": str(task.get("startTimeMs") or ""),
        "is_bundled": bool(task.get("isBundled", False)),
    }


class ScheduledTaskService:
    """Serialize access to the native scheduled-task provider."""

    async def _call(
        self,
        method: str,
        *arguments: Any,
    ) -> Any:
        async with _service_lock():
            client = AntigravityCDP()
            await client.connect()
            try:
                try:
                    await client.evaluate(
                        "window.electronNative?.prepareAutomation?.() ?? "
                        "{success: true, legacy: true}",
                        timeout=5,
                    )
                except Exception:
                    # Provider calls do not require the optional repack wake API.
                    pass

                ready = False
                for _ in range(40):
                    ready = bool(await client.evaluate(_CONTROLLER_SOURCE, timeout=5))
                    if ready:
                        try:
                            probe = await client.evaluate(
                                "window.__agyScheduledTasks.list()",
                                timeout=5,
                            )
                            if probe:
                                break
                        except Exception:
                            ready = False
                    await asyncio.sleep(0.25)
                if not ready:
                    raise RuntimeError(
                        "Native Anti-Gravity scheduled-task service is not ready."
                    )

                encoded_arguments = ", ".join(
                    json.dumps(argument, ensure_ascii=False) for argument in arguments
                )
                expression = (
                    f"window.__agyScheduledTasks.{method}({encoded_arguments})"
                )
                raw = await client.evaluate(expression, timeout=30)
                if not isinstance(raw, str):
                    raise RuntimeError(
                        "Anti-Gravity returned an invalid scheduled-task response."
                    )
                return json.loads(raw)
            except RuntimeError as error:
                message = str(error)
                if "SCHEDULED_TASK_NOT_FOUND:" in message:
                    raise KeyError(message.rsplit(":", 1)[-1]) from error
                if "SCHEDULED_TASK_EXISTS:" in message:
                    raise FileExistsError(message.rsplit(":", 1)[-1]) from error
                raise
            finally:
                await client.disconnect()

    async def list_tasks(self) -> Dict[str, Any]:
        result = await self._call("list")
        tasks = [_task_to_public(task) for task in result.get("tasks") or []]
        tasks.sort(key=lambda item: (item["name"].lower(), item["id"]))
        return {
            "connected": bool(result.get("connected", False)),
            "tasks": tasks,
            "count": len(tasks),
        }

    async def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize_create_payload(payload)
        task = await self._call("create", normalized)
        return _task_to_public(task)

    async def update_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_id = validate_task_id(task_id)
        normalized = normalize_update_payload(payload)
        task = await self._call("update", normalized_id, normalized)
        return _task_to_public(task)

    async def set_enabled(self, task_id: str, enabled: bool) -> Dict[str, Any]:
        return await self.update_task(task_id, {"enabled": enabled})

    async def restart_task(self, task_id: str) -> Dict[str, Any]:
        return await self._call("run", validate_task_id(task_id))

    async def run_task(self, task_id: str) -> Dict[str, Any]:
        """Compatibility alias; native action 4 restarts the scheduler."""
        return await self.restart_task(task_id)

    async def delete_task(self, task_id: str) -> Dict[str, Any]:
        return await self._call("remove", validate_task_id(task_id))

    async def get_events(self, task_id: str) -> Dict[str, Any]:
        return await self._call("events", validate_task_id(task_id))
