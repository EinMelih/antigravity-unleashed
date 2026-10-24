import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Empirically calibrated Google AI Ultra (g1-ultra-tier) constants for Gemini 4 Argon (High)
WEEKLY_PCT_PER_WEIGHTED_TOKEN = 0.00000021285
FIVE_HOUR_PCT_PER_WEIGHTED_TOKEN = 0.0000008514
EUR_PER_USD = 0.92


def parse_proto_flat(data):
    pos = 0
    res = {}
    if not data:
        return res
    n = len(data)
    while pos < n:
        try:
            header = 0
            shift = 0
            while True:
                b = data[pos]
                header |= (b & 0x7F) << shift
                pos += 1
                if not (b & 0x80):
                    break
                shift += 7
            fn = header >> 3
            wt = header & 0x07
            if wt == 0:
                val = 0
                shift = 0
                while True:
                    b = data[pos]
                    val |= (b & 0x7F) << shift
                    pos += 1
                    if not (b & 0x80):
                        break
                    shift += 7
                res[fn] = val
            elif wt == 2:
                length = 0
                shift = 0
                while True:
                    b = data[pos]
                    length |= (b & 0x7F) << shift
                    pos += 1
                    if not (b & 0x80):
                        break
                    shift += 7
                res[fn] = data[pos : pos + length]
                pos += length
            elif wt == 1:
                pos += 8
            elif wt == 5:
                pos += 4
            else:
                break
        except IndexError:
            break
    return res


def extract_first_user_title(payload):
    if not payload:
        return ""
    try:
        outer = parse_proto_flat(payload)
        raw = ""
        if isinstance(outer.get(19), bytes):
            inner = parse_proto_flat(outer[19])
            if isinstance(inner.get(2), bytes):
                raw = inner[2].decode("utf-8", errors="ignore")
        if not raw:
            decoded = payload.decode("utf-8", errors="ignore")
            m = re.search(r"<USER_REQUEST>\s*([\s\S]+?)\s*</USER_REQUEST>", decoded)
            if m:
                raw = m.group(1)
        if raw:
            raw = re.sub(r"</?USER_REQUEST>", "", raw).strip()
            first_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
            return first_line[:90]
    except Exception:
        pass
    return ""


def compute_step_cost_usd(uncached, cached, out):
    ctx = uncached + cached
    if ctx > 200_000:
        in_rate, cache_rate, out_rate = 4.00, 0.40, 18.00
    else:
        in_rate, cache_rate, out_rate = 2.00, 0.20, 12.00
    eff = (uncached / 1e6) * in_rate + (cached / 1e6) * cache_rate + (out / 1e6) * out_rate
    raw = (ctx / 1e6) * in_rate + (out / 1e6) * out_rate
    return eff, raw


def analyze_conversation_db(db_path: Path, include_turns: bool = False):
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=1.5)
    try:
        rows = conn.execute(
            "SELECT idx, step_type, metadata, CASE WHEN step_type=14 AND idx < 15 THEN step_payload ELSE NULL END "
            "FROM steps WHERE step_type IN (14, 15) ORDER BY idx ASC"
        ).fetchall()
    except Exception:
        rows = []

    t_un = t_ca = t_out = t_thk = t_resp = 0
    l_un = l_ca = l_out = l_idx = 0
    first_ts = last_ts = 0
    step_count = 0
    turn_count = 0
    cache_miss_count = 0
    wasted_reload_tokens = 0
    eff_usd_total = 0.0
    raw_usd_total = 0.0
    title = ""

    turns = []
    cur_turn = None
    prev_end_ts = 0
    seen_ai_steps = 0
    has_warmed_cache_before = False
    prev_step_had_cache = False

    for idx, st, meta, payload in rows:
        if st == 14 and not title and payload:
            title = extract_first_user_title(payload)

        m = parse_proto_flat(meta) if meta else {}
        start_ts = parse_proto_flat(m.get(1)).get(1, 0) if isinstance(m.get(1), bytes) else 0
        end_blob = m.get(7) or m.get(8) or m.get(32) or m.get(1)
        end_ts = parse_proto_flat(end_blob).get(1, start_ts) if isinstance(end_blob, bytes) else start_ts

        if start_ts > 0 and (first_ts == 0 or start_ts < first_ts):
            first_ts = start_ts
        if end_ts > last_ts:
            last_ts = end_ts

        if st == 14:
            turn_count += 1
            if include_turns and cur_turn and cur_turn["steps"] > 0:
                turns.append(finalize_turn(cur_turn))
            cur_turn = {
                "turnIdx": turn_count,
                "userStepIdx": idx,
                "startTs": start_ts,
                "endTs": end_ts,
                "steps": 0,
                "uncached": 0,
                "cached": 0,
                "out": 0,
                "thinking": 0,
                "effUsd": 0.0,
                "rawUsd": 0.0,
                "cacheHit": False,
                "cacheMiss": False,
                "hadInitialFill": False,
                "reloadedTokens": 0,
                "latestContextTokens": 0,
                "wastedTokens": 0,
                "maxPauseSec": 0,
            }
        elif st == 15 and isinstance(m.get(9), bytes):
            u = parse_proto_flat(m[9])
            unc = int(u.get(2, 0) or 0)
            out = int(u.get(3, 0) or 0)
            cac = int(u.get(5, 0) or 0)
            resp = int(u.get(9, 0) or 0)
            thk = int(u.get(10, 0) or 0)
            if unc == 0 and cac == 0 and out == 0:
                continue

            seen_ai_steps += 1
            step_count += 1
            t_un += unc
            t_ca += cac
            t_out += out
            t_thk += thk
            t_resp += resp
            l_un, l_ca, l_out, l_idx = unc, cac, out, idx

            eff_u, raw_u = compute_step_cost_usd(unc, cac, out)
            eff_usd_total += eff_u
            raw_usd_total += raw_u

            if cur_turn is None:
                turn_count = 1
                cur_turn = {
                    "turnIdx": 1,
                    "userStepIdx": 0,
                    "startTs": start_ts,
                    "endTs": end_ts,
                    "steps": 0,
                    "uncached": 0,
                    "cached": 0,
                    "out": 0,
                    "thinking": 0,
                    "effUsd": 0.0,
                    "rawUsd": 0.0,
                    "cacheHit": False,
                    "cacheMiss": False,
                    "hadInitialFill": False,
                    "reloadedTokens": 0,
                    "latestContextTokens": 0,
                    "wastedTokens": 0,
                    "maxPauseSec": 0,
                }

            pause = (start_ts - prev_end_ts) if (prev_end_ts > 0 and start_ts >= prev_end_ts) else 0
            # A true cache miss only happens AFTER the conversation already had a warm cache once,
            # and a subsequent turn/step drops back to cac == 0 (after an idle pause or model switch).
            # In a brand new chat (before has_warmed_cache_before is True), cac == 0 is "Filling cache"!
            is_miss = (
                has_warmed_cache_before
                and prev_step_had_cache
                and cac == 0
                and unc > 25_000
                and (cur_turn["steps"] == 0 or pause >= 60)
            )
            if is_miss:
                cache_miss_count += 1
                wasted = int(round(unc * 0.9))
                wasted_reload_tokens += wasted
            else:
                wasted = 0

            if cac == 0 and not has_warmed_cache_before:
                cur_turn["hadInitialFill"] = True

            if cac > 0:
                has_warmed_cache_before = True
                prev_step_had_cache = True
            elif is_miss:
                prev_step_had_cache = False

            cur_turn["steps"] += 1
            cur_turn["uncached"] += unc
            cur_turn["cached"] += cac
            cur_turn["out"] += out
            cur_turn["thinking"] += thk
            cur_turn["effUsd"] += eff_u
            cur_turn["rawUsd"] += raw_u
            cur_turn["latestContextTokens"] = unc + cac
            if cac > 0:
                cur_turn["cacheHit"] = True
            if is_miss:
                cur_turn["cacheMiss"] = True
                cur_turn["reloadedTokens"] = max(cur_turn["reloadedTokens"], unc)
                cur_turn["wastedTokens"] += wasted
            if pause > cur_turn["maxPauseSec"]:
                cur_turn["maxPauseSec"] = pause
            if end_ts > cur_turn["endTs"]:
                cur_turn["endTs"] = end_ts

            if end_ts > 0:
                prev_end_ts = end_ts

    # Fallback to gen_metadata if steps had no modelUsage (older DBs)
    if step_count == 0:
        try:
            grows = conn.execute("SELECT idx, data FROM gen_metadata ORDER BY idx ASC").fetchall()
            for gidx, gblob in grows:
                gm = parse_proto_flat(gblob)
                if isinstance(gm.get(1), bytes):
                    gm1 = parse_proto_flat(gm[1])
                    if isinstance(gm1.get(17), bytes):
                        gm17 = parse_proto_flat(gm1[17])
                        if isinstance(gm17.get(2), bytes):
                            u = parse_proto_flat(gm17[2])
                            unc = int(u.get(2, 0) or 0)
                            out = int(u.get(3, 0) or 0)
                            cac = int(u.get(5, 0) or 0)
                            thk = int(u.get(10, 0) or 0)
                            resp = int(u.get(9, 0) or 0)
                            step_count += 1
                            t_un += unc
                            t_ca += cac
                            t_out += out
                            t_thk += thk
                            t_resp += resp
                            l_un, l_ca, l_out, l_idx = unc, cac, out, gidx
                            eff_u, raw_u = compute_step_cost_usd(unc, cac, out)
                            eff_usd_total += eff_u
                            raw_usd_total += raw_u
        except Exception:
            pass

    conn.close()

    if include_turns and cur_turn and cur_turn["steps"] > 0:
        turns.append(finalize_turn(cur_turn))

    if last_ts == 0:
        try:
            last_ts = int(db_path.stat().st_mtime)
        except Exception:
            last_ts = int(time.time())
    if first_ts == 0:
        first_ts = last_ts

    t_in = t_un + t_ca
    l_in = l_un + l_ca
    ratio = round((t_ca / t_in) * 100, 2) if t_in > 0 else 0.0
    weighted = int(round(1.0 * t_un + 0.1 * t_ca + 6.0 * t_out))
    weekly_pct = round(weighted * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4)
    five_h_pct = round(weighted * FIVE_HOUR_PCT_PER_WEIGHTED_TOKEN, 4)
    wasted_weekly_pct = round(wasted_reload_tokens * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4)
    eff_eur = round(eff_usd_total * EUR_PER_USD, 2)
    raw_eur = round(raw_usd_total * EUR_PER_USD, 2)
    saved_eur = round(max(0.0, raw_eur - eff_eur), 2)

    res = {
        "cascadeId": db_path.stem,
        "title": title,
        "stepCount": step_count,
        "turnCount": max(1, turn_count) if step_count > 0 else 0,
        "totalInput": t_in,
        "totalUncached": t_un,
        "totalCached": t_ca,
        "totalOutput": t_out,
        "totalThinking": t_thk,
        "totalResponseOutput": t_resp,
        "latestInput": l_in,
        "latestUncached": l_un,
        "latestCached": l_ca,
        "latestOutput": l_out,
        "latestStepIdx": l_idx,
        "cacheRatio": ratio,
        "cacheMissCount": cache_miss_count,
        "wastedReloadTokens": wasted_reload_tokens,
        "wastedWeeklyPct": wasted_weekly_pct,
        "weightedTokens": weighted,
        "weeklyPctUsed": weekly_pct,
        "fiveHourPctUsed": five_h_pct,
        "apiCostUsd": round(eff_usd_total, 2),
        "apiCostEur": eff_eur,
        "apiRawCostEur": raw_eur,
        "apiSavedEur": saved_eur,
        "firstStepTimestamp": first_ts,
        "lastStepTimestamp": last_ts,
    }
    if include_turns:
        res["turns"] = turns
    return res


def finalize_turn(t):
    tot_in = t["uncached"] + t["cached"]
    weighted = int(round(1.0 * t["uncached"] + 0.1 * t["cached"] + 6.0 * t["out"]))
    weekly_pct = round(weighted * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4)
    five_h_pct = round(weighted * FIVE_HOUR_PCT_PER_WEIGHTED_TOKEN, 4)
    saved_weekly_pct = round(t["cached"] * 0.9 * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4)
    eff_eur = round(t["effUsd"] * EUR_PER_USD, 3)
    raw_eur = round(t["rawUsd"] * EUR_PER_USD, 3)
    return {
        "turnIdx": t["turnIdx"],
        "userStepIdx": t["userStepIdx"],
        "steps": t["steps"],
        "uncached": t["uncached"],
        "cached": t["cached"],
        "totalInput": tot_in,
        "out": t["out"],
        "thinking": t["thinking"],
        "weightedTokens": weighted,
        "weeklyPct": weekly_pct,
        "fiveHourPct": five_h_pct,
        "savedWeeklyPct": saved_weekly_pct,
        "apiCostEur": eff_eur,
        "apiSavedEur": round(max(0.0, raw_eur - eff_eur), 3),
        "cacheHit": t["cacheHit"],
        "cacheMiss": t["cacheMiss"],
        "fillingCache": bool(not t["cacheHit"] and not t["cacheMiss"]),
        "cacheBuiltInTurn": bool(t.get("hadInitialFill") and t["cacheHit"] and not t["cacheMiss"]),
        "reloadedTokens": int(t.get("reloadedTokens") or 0),
        "latestContextTokens": int(t.get("latestContextTokens") or 0),
        "wastedWeeklyPct": round(t["wastedTokens"] * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4),
        "maxPauseSec": t["maxPauseSec"],
        "startTs": t["startTs"],
        "endTs": t["endTs"],
    }


def get_repack_info(conv_dir: Path) -> dict:
    scratch_dir = Path.home() / ".gemini" / "antigravity" / "scratch"
    skill_root = Path(__file__).resolve().parent.parent
    notice_file = scratch_dir / "repack_pending_notice.json"
    state_file = scratch_dir / "auto_repack_guard_state.json"
    status_file = scratch_dir / "injector_status.json"

    if status_file.exists():
        try:
            st_obj = json.loads(status_file.read_text("utf-8"))
            if isinstance(st_obj, dict) and st_obj.get("state") == "running":
                return {
                    "pending": False,
                    "repacking": True,
                    "title": "",
                    "details": "",
                    "runningChatsCount": 0,
                }
        except Exception:
            pass

    notice = {}
    if notice_file.exists():
        try:
            loaded = json.loads(notice_file.read_text("utf-8"))
            if isinstance(loaded, dict):
                notice = loaded
        except Exception:
            pass

    pending = bool(notice.get("pending") or notice.get("await_user_click"))
    title = str(notice.get("title") or "").strip()
    details = str(notice.get("details") or "").strip()

    try:
        scripts_dir_str = str(Path(__file__).resolve().parent)
        if scripts_dir_str not in sys.path:
            sys.path.insert(0, scripts_dir_str)
        from auto_repack_guard import source_signature
        current_hash = source_signature()
        last_hash = ""
        if state_file.exists():
            st_data = json.loads(state_file.read_text("utf-8"))
            if isinstance(st_data, dict):
                last_hash = str(st_data.get("source") or st_data.get("lastSourceHash") or "")
        if last_hash and current_hash != last_hash:
            pending = True
            if not title:
                title = "UI-Modifier Update bereit"
            if not details:
                details = "Änderungen in Unleashed warten auf Repack & Neustart"
        elif last_hash and current_hash == last_hash and not notice.get("force_notice"):
            pending = False
    except Exception:
        pass

    running_chats = 0
    now_ts = time.time()
    try:
        for db_f in conv_dir.glob("*.db"):
            if db_f.stem.startswith("__"):
                continue
            if (now_ts - db_f.stat().st_mtime) < 25:
                running_chats += 1
    except Exception:
        pass

    return {
        "pending": pending,
        "repacking": False,
        "title": title or ("UI-Modifier Update bereit" if pending else ""),
        "details": details or ("Jetzt neu starten, um die Änderungen dauerhaft in app.asar zu übernehmen." if pending else ""),
        "runningChatsCount": running_chats,
        "updatedAt": str(notice.get("updated_at") or ""),
    }


def trigger_repack_from_ui(conv_dir: Path) -> dict:
    scratch_dir = Path.home() / ".gemini" / "antigravity" / "scratch"
    skill_root = Path(__file__).resolve().parent.parent
    scratch_dir.mkdir(parents=True, exist_ok=True)

    last_chat_file = scratch_dir / "last_active_chat_id.txt"
    trigger_chat_file = scratch_dir / "repack_trigger_chat.txt"
    approved_file = scratch_dir / "repack_user_approved.json"
    pause_file = scratch_dir / "auto_repack_guard_pause.json"
    notice_file = scratch_dir / "repack_pending_notice.json"

    chat_id = ""
    # 1. Explicit trigger chat written to app_storage.json by the clicked window
    try:
        roaming = os.environ.get("APPDATA", "")
        storage_path = (Path(roaming) / "Antigravity" / "app_storage.json") if roaming else (Path.home() / "AppData" / "Roaming" / "Antigravity" / "app_storage.json")
        if storage_path.exists():
            st_data = json.loads(storage_path.read_text("utf-8"))
            trig_cid = str(st_data.get("antigravity_repack_trigger_chat_id") or "").strip()
            trig_ts = float(st_data.get("antigravity_repack_trigger_ts") or 0)
            if trig_cid and (time.time() * 1000.0 - trig_ts < 120_000):
                chat_id = trig_cid
    except Exception:
        pass

    # 2. Most recently modified conversation DB (avoid stale background window overwrite)
    if not chat_id:
        try:
            candidates = [f for f in conv_dir.glob("*.db") if not f.stem.startswith("__")]
            if candidates:
                candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                if time.time() - candidates[0].stat().st_mtime < 300:
                    chat_id = candidates[0].stem
        except Exception:
            pass

    if not chat_id and last_chat_file.exists():
        try:
            chat_id = last_chat_file.read_text("utf-8").strip()
        except Exception:
            pass

    if chat_id:
        try:
            trigger_chat_file.write_text(chat_id, encoding="utf-8")
        except Exception:
            pass

    now_sec = time.time()
    try:
        approved_file.write_text(
            json.dumps({"approved": True, "approved_at": now_sec, "timestamp": now_sec, "chatId": chat_id}),
            encoding="utf-8",
        )
    except Exception:
        pass

    for f in (pause_file, notice_file):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass

    ps_script = skill_root / "scripts" / "start_repack_task.ps1"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps_script),
        ],
        cwd=str(skill_root),
        close_fds=True,
        creationflags=flags,
    )
    return {"triggered": True, "chatId": chat_id}


def update_and_load_global_ledger(conv_dir: Path, active_stats: dict):
    config_dir = Path.home() / ".gemini" / "config"
    scratch_dir = Path.home() / ".gemini" / "antigravity" / "scratch"
    ledger_path = config_dir / "quota_usage_log.json"
    now_ts = time.time()

    try:
        trigger_db = conv_dir / "__AMS_REPACK_TRIGGER__.db"
        if not trigger_db.exists():
            trigger_db.write_bytes(b"")
    except Exception:
        pass

    ledger = {"version": 2, "lastFullScan": 0, "chats": {}}
    if ledger_path.exists():
        try:
            loaded = json.loads(ledger_path.read_text("utf-8"))
            if isinstance(loaded, dict) and loaded.get("version") == 2:
                ledger = loaded
        except Exception:
            pass

    chats_cache = ledger.setdefault("chats", {})
    for k in list(chats_cache.keys()):
        if str(k).startswith("__"):
            chats_cache.pop(k, None)

    need_write = False

    # Always update active conversation in cache and persist immediately so concurrent polls never read stale data
    cid = active_stats.get("cascadeId")
    if cid and not str(cid).startswith("__"):
        try:
            st = (conv_dir / f"{cid}.db").stat()
            if now_ts - st.st_mtime < 60:
                scratch_dir.mkdir(parents=True, exist_ok=True)
                (scratch_dir / "last_active_chat_id.txt").write_text(str(cid), encoding="utf-8")
            entry = {k: v for k, v in active_stats.items() if k != "turns"}
            entry["_mtime"] = round(st.st_mtime, 2)
            entry["_size"] = st.st_size
            chats_cache[cid] = entry
            need_write = True
        except Exception:
            pass

    # Incremental mtime-cached scan of all conversations if last scan > 12s ago
    if now_ts - ledger.get("lastFullScan", 0) > 12 or not chats_cache:
        need_write = True
        try:
            for db_file in conv_dir.glob("*.db"):
                stem = db_file.stem
                if stem.startswith("__"):
                    continue
                try:
                    st = db_file.stat()
                    mtime = round(st.st_mtime, 2)
                    size = st.st_size
                except Exception:
                    continue
                cached_entry = chats_cache.get(stem)
                if (
                    cached_entry
                    and cached_entry.get("_mtime") == mtime
                    and cached_entry.get("_size") == size
                ):
                    continue
                if stem == cid:
                    continue
                parsed = analyze_conversation_db(db_file, include_turns=False)
                parsed["_mtime"] = mtime
                parsed["_size"] = size
                chats_cache[stem] = parsed
            ledger["lastFullScan"] = round(now_ts, 2)
        except Exception:
            pass

    # Build compact chatMap (all chats with stepCount > 0, sorted by lastStepTimestamp desc)
    valid_chats = [
        v
        for k, v in chats_cache.items()
        if not str(k).startswith("__") and isinstance(v, dict) and v.get("stepCount", 0) > 0
    ]
    valid_chats.sort(key=lambda x: x.get("lastStepTimestamp", 0), reverse=True)

    # Default weekly window: last 7 days (renderer can refine with exact reset Time from RetrieveUserQuotaSummary)
    week_cutoff = int(now_ts - 7 * 86400)
    w_chats = [c for c in valid_chats if c.get("lastStepTimestamp", 0) >= week_cutoff]

    def summarize(chat_list):
        s_in = sum(c.get("totalInput", 0) for c in chat_list)
        s_un = sum(c.get("totalUncached", 0) for c in chat_list)
        s_ca = sum(c.get("totalCached", 0) for c in chat_list)
        s_out = sum(c.get("totalOutput", 0) for c in chat_list)
        s_thk = sum(c.get("totalThinking", 0) for c in chat_list)
        s_steps = sum(c.get("stepCount", 0) for c in chat_list)
        s_turns = sum(c.get("turnCount", 0) for c in chat_list)
        s_miss = sum(c.get("cacheMissCount", 0) for c in chat_list)
        s_wasted = sum(c.get("wastedReloadTokens", 0) for c in chat_list)
        s_weighted = sum(c.get("weightedTokens", 0) for c in chat_list)
        s_eff_eur = round(sum(c.get("apiCostEur", 0.0) for c in chat_list), 2)
        s_raw_eur = round(sum(c.get("apiRawCostEur", 0.0) for c in chat_list), 2)
        s_saved_eur = round(max(0.0, s_raw_eur - s_eff_eur), 2)
        return {
            "chatCount": len(chat_list),
            "stepCount": s_steps,
            "turnCount": s_turns,
            "totalInput": s_in,
            "totalUncached": s_un,
            "totalCached": s_ca,
            "totalOutput": s_out,
            "totalThinking": s_thk,
            "cacheRatio": round((s_ca / s_in) * 100, 2) if s_in > 0 else 0.0,
            "cacheMissCount": s_miss,
            "wastedReloadTokens": s_wasted,
            "wastedWeeklyPct": round(s_wasted * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4),
            "weightedTokens": s_weighted,
            "weeklyPctUsed": round(s_weighted * WEEKLY_PCT_PER_WEIGHTED_TOKEN, 4),
            "fiveHourPctUsed": round(s_weighted * FIVE_HOUR_PCT_PER_WEIGHTED_TOKEN, 4),
            "apiCostEur": s_eff_eur,
            "apiRawCostEur": s_raw_eur,
            "apiSavedEur": s_saved_eur,
        }

    weekly_summary = summarize(w_chats)
    all_time_summary = summarize(valid_chats)

    ledger["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger["hostname"] = socket.gethostname().lower().replace(" ", "_")
    ledger["weeklySummary"] = weekly_summary
    ledger["allTimeSummary"] = all_time_summary

    if need_write:
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # Return top 160 recent chats for sidebar & Models & Usage table
    compact_chats = []
    for c in valid_chats[:160]:
        compact_chats.append({
            "cascadeId": c["cascadeId"],
            "title": c.get("title", ""),
            "stepCount": c.get("stepCount", 0),
            "turnCount": c.get("turnCount", 0),
            "totalInput": c.get("totalInput", 0),
            "totalUncached": c.get("totalUncached", 0),
            "totalCached": c.get("totalCached", 0),
            "totalOutput": c.get("totalOutput", 0),
            "latestInput": c.get("latestInput", 0),
            "latestUncached": c.get("latestUncached", 0),
            "latestCached": c.get("latestCached", 0),
            "latestStepIdx": c.get("latestStepIdx", 0),
            "cacheRatio": c.get("cacheRatio", 0.0),
            "cacheMissCount": c.get("cacheMissCount", 0),
            "wastedWeeklyPct": c.get("wastedWeeklyPct", 0.0),
            "weightedTokens": c.get("weightedTokens", 0),
            "weeklyPctUsed": c.get("weeklyPctUsed", 0.0),
            "fiveHourPctUsed": c.get("fiveHourPctUsed", 0.0),
            "apiCostEur": c.get("apiCostEur", 0.0),
            "apiRawCostEur": c.get("apiRawCostEur", 0.0),
            "apiSavedEur": c.get("apiSavedEur", 0.0),
            "firstStepTimestamp": c.get("firstStepTimestamp", 0),
            "lastStepTimestamp": c.get("lastStepTimestamp", 0),
        })

    return {
        "logFilePath": str(ledger_path),
        "weeklySummary": weekly_summary,
        "allTimeSummary": all_time_summary,
        "recentChats": compact_chats,
        "repackInfo": get_repack_info(conv_dir),
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "missing_arg"}))
        return

    db_path = Path(sys.argv[1])
    if db_path.stem == "__AMS_REPACK_TRIGGER__":
        res = trigger_repack_from_ui(db_path.parent)
        print(json.dumps(res))
        return

    if not db_path.exists():
        print(json.dumps({"error": "not_found"}))
        return

    active_stats = analyze_conversation_db(db_path, include_turns=True)
    global_data = update_and_load_global_ledger(db_path.parent, active_stats)
    active_stats.update(global_data)
    print(json.dumps(active_stats))


if __name__ == "__main__":
    main()
