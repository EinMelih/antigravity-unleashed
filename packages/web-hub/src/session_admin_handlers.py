import platform

from aiohttp import web

from src.config import config
from src.session_pool import SessionPool


async def stats_handler(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        stats = pool.get_stats()
        stats["sessions"] = [s.to_dict() for s in pool.sessions.values()]
        return web.json_response(stats)
    except Exception as e:
        print(f"[ERROR] stats_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def health_handler(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        stats = pool.get_stats()
        pool_ok = stats["pool"]["idle"] > 0 or stats["pool"]["busy"] > 0

        # Memory usage calculation
        memory_mb = 0.0
        try:
            if platform.system() != 'Windows':
                import resource
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if platform.system() == 'Darwin':
                    memory_mb = round(rss / (1024 * 1024), 1)
                else:
                    memory_mb = round(rss / 1024, 1)
            else:
                try:
                    import ctypes
                    import ctypes.wintypes
                    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                        _fields_ = [
                            ("cb", ctypes.wintypes.DWORD),
                            ("PageFaultCount", ctypes.wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t),
                        ]
                    psapi = ctypes.windll.psapi
                    pmc = PROCESS_MEMORY_COUNTERS()
                    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    handle = ctypes.windll.kernel32.GetCurrentProcess()
                    if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                        memory_mb = round(pmc.WorkingSetSize / (1024 * 1024), 1)
                except Exception:
                    pass
        except Exception:
            pass

        sm_cfg = config.session_manager
        return web.json_response({
            "status": "ok" if pool_ok else "degraded",
            "service": "session_manager",
            "version": "1.0.0",
            "uptime_seconds": stats["uptime_seconds"],
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "memory_usage_mb": memory_mb,
            "port": sm_cfg.get("port", 8002),
            "pool": stats["pool"],
            "performance": stats["performance"],
            "health_check_interval_seconds": sm_cfg.get("health_check_interval_seconds", 30),
            "session_timeout_seconds": sm_cfg.get("session_timeout_seconds", 120),
            "endpoints": {
                "chat_completions": "POST /v1/chat/completions",
                "simple_chat": "POST /api/chat",
                "models": "GET  /v1/models",
                "sessions": "GET  /sessions",
                "register": "POST /sessions",
                "acquire": "POST /sessions/acquire",
                "stats": "GET  /stats",
                "health": "GET  /health",
            }
        })
    except Exception as e:
        print(f"[ERROR] health_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def root_handler(request: web.Request) -> web.Response:
    try:
        return web.json_response({
            "service": "Antigravity Multi-Session Manager v1.0",
            "info": "Verwaltet mehrere API-Bridge-Instanzen für parallele Anfragen.",
            "quickstart": {
                "1_check_health": "GET /health",
                "2_list_sessions": "GET /sessions",
                "3_chat": 'POST /v1/chat/completions  {"model":"antigravity","messages":[{"role":"user","content":"Hi"}]}',
                "4_simple_chat": 'POST /api/chat  {"message": "Hallo!"}',
                "5_add_session": 'POST /sessions  {"name": "bridge-2", "url": "http://127.0.0.1:8003"}',
            },
            "auth": "Authorization: Bearer <configured-token>",
        })
    except Exception as e:
        print(f"[ERROR] root_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)
