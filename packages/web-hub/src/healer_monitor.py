import asyncio

from src.config import config
from src.telegram import send_telegram
from src.healer_logic import (
    state,
    now_iso,
    uptime_str,
    record_event,
    check_api_bridge,
    check_process_running,
    run_healing_cycle,
)


async def monitor_loop() -> None:
    """Indefinite checker loop triggering healing when issues arise."""
    interval = config.auto_healer.get("check_interval_seconds", 15)
    print(f"[MONITOR] Überwachungsschleife gestartet (alle {interval}s)", flush=True)

    await asyncio.sleep(5)
    was_healthy = True

    while True:
        try:
            state["total_checks"] += 1
            state["last_check"] = now_iso()

            # Run check
            check = await check_api_bridge()

            state["api_bridge_healthy"] = check["reachable"]
            state["cdp_connected"] = check["cdp_connected"]
            state["bridge_injected"] = check["bridge_injected"]

            if state["total_checks"] % 5 == 0:
                state["process_running"] = await check_process_running()

            problems = []
            if not check["reachable"]:
                problems.append("API Bridge nicht erreichbar")
            elif not check["cdp_connected"]:
                problems.append("CDP nicht verbunden")
            elif not check["bridge_injected"]:
                problems.append("JS Bridge nicht injiziert")

            if check.get("response_time_ms") and check["response_time_ms"] > 8000:
                problems.append(f"Langsame Antwort: {check['response_time_ms']}ms")

            if problems:
                state["healthy"] = False
                state["consecutive_failures"] += 1
                state["last_error"] = "; ".join(problems)
                was_healthy_before = was_healthy
                was_healthy = False

                print(f"[MONITOR] ⚠️ Probleme erkannt ({state['consecutive_failures']}x): {', '.join(problems)}", flush=True)

                # Run cycle
                await run_healing_cycle(source="monitor")

                await asyncio.sleep(2)
                recheck = await check_api_bridge()
                if recheck["reachable"] and recheck["cdp_connected"]:
                    state["healthy"] = True
                    state["consecutive_failures"] = 0
                    state["last_success"] = now_iso()
                    state["total_recoveries"] += 1
                    was_healthy = True

                    print("[MONITOR] ✅ System wiederhergestellt!", flush=True)
                    record_event(0, "System wiederhergestellt nach Heilung", True)

                    if was_healthy_before is False:
                        msg = (
                            f"🔧 [Antigravity Auto-Healer] ✅ System wiederhergestellt!\n"
                            f"Betriebszeit: {uptime_str()}\n"
                            f"Gesamtchecks: {state['total_checks']}"
                        )
                        await send_telegram(msg)
            else:
                if not was_healthy:
                    state["healthy"] = True
                    state["consecutive_failures"] = 0
                    state["last_success"] = now_iso()
                    state["total_recoveries"] += 1
                    was_healthy = True
                    print("[MONITOR] ✅ System wiederhergestellt!", flush=True)
                    record_event(0, "System wiederhergestellt (automatisch erholt)", True)

                    msg = (
                        f"🔧 [Antigravity Auto-Healer] ✅ System wiederhergestellt (automatisch erholt)!\n"
                        f"Betriebszeit: {uptime_str()}"
                    )
                    await send_telegram(msg)

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            print("[MONITOR] Überwachungsschleife abgebrochen", flush=True)
            break
        except Exception as e:
            print(f"[MONITOR] Fehler in Überwachungsschleife: {e}", flush=True)
            await asyncio.sleep(interval)
